-- =============================================================================
-- 20260101000002_analytics_and_reconciliation.sql
-- admin_analytics() RPC + billing reconciliation views.
--
-- Fixes the analytics HTTP 500 at the foundation: every aggregate is COALESCEd,
-- MRR is computed by JOINing subscriptions to pricing_tiers (so an unknown/NULL
-- tier can never throw a KeyError), and NULL price_paid can never break a SUM
-- (the column is now NOT NULL DEFAULT 0, and we COALESCE anyway).
-- =============================================================================

create or replace function public.admin_analytics()
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
    select jsonb_build_object(
        'total_customers',
            (select count(*) from public.customers),

        'active_subscriptions',
            (select count(*) from public.subscriptions where status = 'active'),

        'monthly_recurring_revenue',
            coalesce((
                select sum(pt.monthly_price)
                from public.subscriptions s
                join public.pricing_tiers pt on pt.tier = s.tier
                where s.status = 'active'
            ), 0),

        'total_leads',
            (select count(*) from public.leads),

        'available_leads',
            (select count(*) from public.leads where coalesce(status, 'available') = 'available'),

        'sold_leads',
            (select count(*) from public.leads where status = 'sold'),

        -- recorded overage revenue (what we believe we sold)
        'overage_revenue',
            coalesce((
                select sum(price_paid) from public.lead_purchases
                where purchase_type = 'overage'
            ), 0),

        -- collected overage revenue (what Stripe actually confirmed)
        'overage_revenue_collected',
            coalesce((
                select sum(price_paid) from public.lead_purchases
                where purchase_type = 'overage' and payment_status = 'paid'
            ), 0),

        -- overage owed but not yet collected (pending/failed)
        'overage_revenue_outstanding',
            coalesce((
                select sum(price_paid) from public.lead_purchases
                where purchase_type = 'overage' and payment_status in ('pending', 'failed')
            ), 0),

        'total_revenue',
            coalesce((
                select sum(pt.monthly_price)
                from public.subscriptions s
                join public.pricing_tiers pt on pt.tier = s.tier
                where s.status = 'active'
            ), 0)
            +
            coalesce((
                select sum(price_paid) from public.lead_purchases
                where purchase_type = 'overage'
            ), 0)
    );
$$;

comment on function public.admin_analytics() is
    'Null-safe platform analytics (customers, subscriptions, MRR, lead counts, '
    'recorded vs collected overage revenue). Replaces the Python aggregation '
    'that 500d on NULL price_paid / unknown tier.';

-- -----------------------------------------------------------------------------
-- billing_reconciliation: one row per overage sale, with the flags an operator
-- needs to chase money. "Safer reconciliation" = every overage purchase is
-- visible alongside its Stripe link and collection state.
-- -----------------------------------------------------------------------------
create or replace view public.billing_reconciliation as
select
    lp.id                       as purchase_id,
    lp.lead_id,
    lp.customer_id,
    c.company_name,
    lp.subscription_id,
    lp.purchase_type,
    lp.price_paid,
    lp.currency,
    lp.payment_status,
    lp.stripe_payment_intent_id,
    lp.purchased_at,
    -- overage we still need to collect
    (lp.purchase_type = 'overage' and lp.payment_status in ('pending', 'failed'))
                                as needs_collection,
    -- money we think is collected but that has no Stripe charge linked
    (lp.purchase_type = 'overage' and lp.payment_status = 'paid'
        and lp.stripe_payment_intent_id is null)
                                as paid_but_unlinked
from public.lead_purchases lp
join public.customers c on c.id = lp.customer_id
where lp.purchase_type = 'overage';

comment on view public.billing_reconciliation is
    'Per-overage-sale reconciliation: flags rows that still need collection or '
    'that are marked paid without a linked Stripe payment intent.';

-- -----------------------------------------------------------------------------
-- billing_reconciliation_summary: one-row rollup for dashboards / alerts.
-- -----------------------------------------------------------------------------
create or replace view public.billing_reconciliation_summary as
select
    count(*)                                                          as overage_sales,
    coalesce(sum(price_paid), 0)                                     as recorded_revenue,
    coalesce(sum(price_paid) filter (where payment_status = 'paid'), 0)
                                                                      as collected_revenue,
    coalesce(sum(price_paid) filter (where payment_status in ('pending', 'failed')), 0)
                                                                      as outstanding_revenue,
    count(*) filter (where payment_status in ('pending', 'failed'))   as sales_needing_collection,
    count(*) filter (where payment_status = 'paid' and stripe_payment_intent_id is null)
                                                                      as paid_but_unlinked
from public.lead_purchases
where purchase_type = 'overage';

comment on view public.billing_reconciliation_summary is
    'Single-row reconciliation rollup: recorded vs collected vs outstanding '
    'overage revenue and counts of rows needing attention.';
