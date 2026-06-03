-- =============================================================================
-- 20260101000001_assign_lead_rpc.sql
-- assign_lead_to_customer(): sell a lead to a customer in ONE transaction.
--
-- Replaces the previous 4-call Python sequence (app/services/admin_service.py)
-- which had a read-then-write race that could double-sell a lead and a
-- read-modify-write race that lost leads_used increments.
--
-- Guarantees:
--   * The lead row is locked FOR UPDATE, so concurrent assignments serialize and
--     the second one sees status='sold' -> raises lead_already_assigned.
--   * leads_used is incremented in-SQL (leads_used + 1), never lost.
--   * All writes commit together or not at all (no partial sale).
--   * Idempotent on p_idempotency_key: a retried call returns the original sale
--     instead of creating a second purchase.
--   * unique(lead_id) on lead_purchases is the final backstop.
--
-- Errors are raised with ERRCODE 'P0001' and a stable machine token as the
-- message so the API layer can map them to HTTP 404 / 409. Tokens:
--   lead_not_found | no_subscription | lead_already_assigned |
--   billing_not_assignable:<status>
-- =============================================================================

create or replace function public.assign_lead_to_customer(
    p_lead_id         uuid,
    p_customer_id     uuid,
    p_idempotency_key text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_lead          public.leads%rowtype;
    v_sub           public.subscriptions%rowtype;
    v_existing      public.lead_purchases%rowtype;
    v_is_overage    boolean;
    v_purchase_type text;
    v_price         numeric(10, 2);
    v_overage_price numeric(10, 2);
    v_payment_status text;
    v_purchase_id   uuid;
begin
    -- 0) Idempotent replay: same key -> return the original sale, no new writes.
    if p_idempotency_key is not null then
        select * into v_existing
        from public.lead_purchases
        where idempotency_key = p_idempotency_key;

        if found then
            return jsonb_build_object(
                'success',       true,
                'idempotent',    true,
                'purchase_id',   v_existing.id,
                'purchase_type', v_existing.purchase_type,
                'price',         v_existing.price_paid,
                'payment_status', v_existing.payment_status,
                'lead_status',   'sold',
                'note',          'Lead assignment already recorded.'
            );
        end if;
    end if;

    -- 1) Lock the lead. This is what serializes concurrent sale attempts.
    select * into v_lead
    from public.leads
    where id = p_lead_id
    for update;

    if not found then
        raise exception 'lead_not_found' using errcode = 'P0001';
    end if;

    if v_lead.status = 'sold' then
        raise exception 'lead_already_assigned' using errcode = 'P0001';
    end if;

    -- 2) Pick + lock the customer's current subscription (active/trialing first,
    --    then newest) to mirror the app's selection and to atomically bump usage.
    select * into v_sub
    from public.subscriptions
    where customer_id = p_customer_id
    order by (status in ('active', 'trialing')) desc, created_at desc
    limit 1
    for update;

    if not found then
        raise exception 'no_subscription' using errcode = 'P0001';
    end if;

    if v_sub.status not in ('active', 'trialing') then
        -- carry the status back so the API can render the right billing message
        raise exception 'billing_not_assignable:%', v_sub.status using errcode = 'P0001';
    end if;

    -- 3) Pricing from the single source of truth.
    select overage_price into v_overage_price
    from public.pricing_tiers
    where tier = v_sub.tier;

    v_is_overage    := v_sub.leads_used >= v_sub.leads_included;
    v_purchase_type := case when v_is_overage then 'overage' else 'included' end;
    v_price         := case when v_is_overage then coalesce(v_overage_price, 0) else 0 end;
    -- included leads need no collection; overage starts pending until Stripe confirms
    v_payment_status := case when v_is_overage then 'pending' else 'recorded' end;

    -- 4) The three writes, atomically.
    update public.leads
    set status = 'sold', assigned_to = p_customer_id
    where id = p_lead_id;

    insert into public.lead_purchases (
        lead_id, customer_id, subscription_id,
        purchase_type, price_paid, payment_status, idempotency_key
    )
    values (
        p_lead_id, p_customer_id, v_sub.id,
        v_purchase_type, v_price, v_payment_status, p_idempotency_key
    )
    returning id into v_purchase_id;

    update public.subscriptions
    set leads_used = leads_used + 1
    where id = v_sub.id;

    return jsonb_build_object(
        'success',        true,
        'idempotent',     false,
        'purchase_id',    v_purchase_id,
        'purchase_type',  v_purchase_type,
        'price',          v_price,
        'payment_status', v_payment_status,
        'subscription_id', v_sub.id,
        'lead_status',    'sold',
        'note',           'Lead assigned to customer'
    );
end;
$$;

comment on function public.assign_lead_to_customer(uuid, uuid, text) is
    'Atomically sell a lead to a customer: locks the lead, validates billing, '
    'records the purchase, and increments subscription usage in one transaction. '
    'Idempotent on p_idempotency_key.';
