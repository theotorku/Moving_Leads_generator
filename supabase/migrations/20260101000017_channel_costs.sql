-- =============================================================================
-- 20260101000017_channel_costs.sql
-- Cost per acquisition channel -> ROI by source. The leads_by_source() rollup
-- already knows volume, quality, and revenue per channel; giving each channel a
-- cost-per-lead lets it compute spend, profit, ROI, and cost-per-booked-move so
-- an operator can see which channels actually pay off.
--
-- Cost lives per *channel* (not per partner key) because the rollup groups by
-- channel and most channels (the public form's direct/organic/google_ads) have
-- no ingest_sources row. RLS-locked to service_role like every other table.
-- =============================================================================

create table if not exists public.channel_costs (
    channel       text primary key,
    cost_per_lead numeric(10, 2) not null default 0,
    updated_at    timestamptz not null default now()
);

alter table public.channel_costs enable row level security;
revoke all on public.channel_costs from anon, authenticated;

comment on table public.channel_costs is
    'Acquisition cost-per-lead per channel; joined by leads_by_source() to derive '
    'spend / profit / ROI / cost-per-booked-move. service_role only.';

-- Rebuild the rollup to fold in cost and the derived ROI metrics.
create or replace function public.leads_by_source()
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
    with agg as (
        select
            coalesce(l.source_channel, l.source, 'unknown')   as channel,
            count(*)                                          as leads,
            round(avg(l.score))                               as avg_score,
            round(avg(l.booking_probability))                 as avg_booking_probability,
            count(*) filter (where l.status = 'sold')         as sold,
            count(p.id) filter (where p.outcome = 'booked')   as booked,
            count(p.id) filter (where p.outcome = 'disputed') as disputed,
            coalesce(sum(p.price_paid), 0)                    as revenue,
            coalesce(sum(p.booked_revenue) filter (where p.outcome = 'booked'), 0) as booked_revenue,
            round(
                count(p.id) filter (where p.outcome = 'booked')::numeric
                / nullif(count(*), 0) * 100, 1)               as book_rate
        from public.leads l
        left join public.lead_purchases p on p.lead_id = l.id
        group by coalesce(l.source_channel, l.source, 'unknown')
    ),
    costed as (
        select
            agg.*,
            coalesce(cc.cost_per_lead, 0)                     as cost_per_lead,
            round(agg.leads * coalesce(cc.cost_per_lead, 0), 2) as spend
        from agg
        left join public.channel_costs cc on cc.channel = agg.channel
    )
    select coalesce(jsonb_agg(
        jsonb_build_object(
            'channel',                 channel,
            'leads',                   leads,
            'avg_score',               avg_score,
            'avg_booking_probability', avg_booking_probability,
            'sold',                    sold,
            'booked',                  booked,
            'disputed',                disputed,
            'revenue',                 revenue,
            'booked_revenue',          booked_revenue,
            'book_rate',               book_rate,
            'cost_per_lead',           cost_per_lead,
            'spend',                   spend,
            'profit',                  round(revenue - spend, 2),
            'roi_pct',                 case when spend > 0 then round((revenue - spend) / spend * 100, 1) end,
            'cost_per_booked',         case when booked > 0 then round(spend / booked, 2) end
        ) order by leads desc
    ), '[]'::jsonb)
    from costed;
$$;

comment on function public.leads_by_source() is
    'Per-channel acquisition rollup: volume, avg score/booking probability, '
    'sold/booked/disputed, marketplace revenue, booked move value, book_rate, '
    'plus cost_per_lead/spend/profit/roi_pct/cost_per_booked from channel_costs.';

revoke all on function public.leads_by_source() from public, anon, authenticated;
grant execute on function public.leads_by_source() to service_role;
