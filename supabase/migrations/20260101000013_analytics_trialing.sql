-- =============================================================================
-- 20260101000013_analytics_trialing.sql
-- Surface trialing subscriptions in analytics.
--
-- Assignment treats `trialing` as an assignable subscription (see the order-by in
-- assign_lead_to_customer), but admin_analytics only counted status='active'. A
-- platform whose only customer is on a trial therefore showed
-- active_subscriptions: 0 while that customer was happily receiving leads.
--
-- We keep `active_subscriptions` (and MRR) as truly-active, paying subscriptions —
-- trials don't bill yet, so they must not inflate revenue — and add explicit
-- `trialing_subscriptions` and `active_or_trialing_subscriptions` counts so the
-- dashboard can show how many buyers are actually eligible for assignment.
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

        'trialing_subscriptions',
            (select count(*) from public.subscriptions where status = 'trialing'),

        -- the count that matches what assignment will actually accept
        'active_or_trialing_subscriptions',
            (select count(*) from public.subscriptions where status in ('active', 'trialing')),

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
    'Null-safe platform analytics. active_subscriptions / MRR count only paying '
    '(status=active) subs; active_or_trialing_subscriptions matches what lead '
    'assignment will accept so a trial-only platform does not read as empty.';
