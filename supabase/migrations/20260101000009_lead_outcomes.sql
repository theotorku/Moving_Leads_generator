-- =============================================================================
-- 20260101000009_lead_outcomes.sql
-- Outcome feedback loop: track what happens to a sold lead (contacted ->
-- appointment -> booked, or lost/disputed) so we can compute the metric movers
-- actually buy on — cost per booked move — and feed conversion data back.
-- =============================================================================

alter table public.lead_purchases
    add column if not exists outcome            text not null default 'purchased',
    add column if not exists booked_revenue     numeric(10, 2) not null default 0,
    add column if not exists dispute_reason     text,
    add column if not exists outcome_updated_at timestamptz;

do $$
begin
    if not exists (select 1 from pg_constraint where conname = 'lead_purchases_outcome_valid') then
        alter table public.lead_purchases add constraint lead_purchases_outcome_valid
            check (outcome in ('purchased','contacted','appointment','booked','lost','disputed','refunded'))
            not valid;
    end if;
end $$;

create index if not exists lead_purchases_outcome_idx on public.lead_purchases (outcome);

-- ---------------------------------------------------------------------------
-- record_lead_outcome: advance a purchase through the funnel (or dispute it).
-- ---------------------------------------------------------------------------
create or replace function public.record_lead_outcome(
    p_purchase_id    uuid,
    p_outcome        text,
    p_booked_revenue numeric default null,
    p_dispute_reason text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_row public.lead_purchases%rowtype;
begin
    if p_outcome not in ('purchased','contacted','appointment','booked','lost','disputed','refunded') then
        raise exception 'invalid_outcome:%', p_outcome using errcode = 'P0001';
    end if;

    update public.lead_purchases
    set outcome = p_outcome,
        outcome_updated_at = now(),
        booked_revenue = case when p_outcome = 'booked'
                              then coalesce(p_booked_revenue, booked_revenue) else booked_revenue end,
        dispute_reason = case when p_outcome = 'disputed' then p_dispute_reason else dispute_reason end,
        payment_status = case when p_outcome = 'refunded' then 'refunded' else payment_status end
    where id = p_purchase_id
    returning * into v_row;

    if not found then
        raise exception 'purchase_not_found' using errcode = 'P0001';
    end if;

    return jsonb_build_object(
        'success',        true,
        'purchase_id',    v_row.id,
        'outcome',        v_row.outcome,
        'booked_revenue', v_row.booked_revenue,
        'payment_status', v_row.payment_status,
        'note',           'Outcome recorded'
    );
end;
$$;

comment on function public.record_lead_outcome(uuid, text, numeric, text) is
    'Advance a lead_purchase through the funnel (contacted/appointment/booked) '
    'or mark it lost/disputed/refunded; sets booked_revenue when booked.';

-- ---------------------------------------------------------------------------
-- conversion_analytics: funnel counts + cost per booked move (null-safe).
-- Stages are cumulative by current outcome (contacted counts contacted-or-further).
-- ---------------------------------------------------------------------------
create or replace function public.conversion_analytics()
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
    select jsonb_build_object(
        'sold',          (select count(*) from public.lead_purchases),
        'contacted',     (select count(*) from public.lead_purchases where outcome in ('contacted','appointment','booked')),
        'appointment',   (select count(*) from public.lead_purchases where outcome in ('appointment','booked')),
        'booked',        (select count(*) from public.lead_purchases where outcome = 'booked'),
        'lost',          (select count(*) from public.lead_purchases where outcome = 'lost'),
        'disputed',      (select count(*) from public.lead_purchases where outcome = 'disputed'),
        'booked_revenue', coalesce((select sum(booked_revenue) from public.lead_purchases where outcome = 'booked'), 0),
        'lead_spend',     coalesce((select sum(price_paid) from public.lead_purchases), 0),
        'cost_per_booked_move',
            coalesce((select sum(price_paid) from public.lead_purchases), 0)
            / nullif((select count(*) from public.lead_purchases where outcome = 'booked'), 0),
        'book_rate',
            round(
                (select count(*) from public.lead_purchases where outcome = 'booked')::numeric
                / nullif((select count(*) from public.lead_purchases), 0) * 100, 1)
    );
$$;

comment on function public.conversion_analytics() is
    'Sold->contacted->appointment->booked funnel, booked revenue, and cost per '
    'booked move (total lead spend / booked count).';

-- Lock execute to the backend role only (consistent with the other RPCs).
revoke all on function public.record_lead_outcome(uuid, text, numeric, text) from public, anon, authenticated;
revoke all on function public.conversion_analytics() from public, anon, authenticated;
grant execute on function public.record_lead_outcome(uuid, text, numeric, text) to service_role;
grant execute on function public.conversion_analytics() to service_role;
