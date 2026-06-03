-- =============================================================================
-- 20260101000015_leads_by_source.sql
-- "Where are the leads coming from?" — a per-channel rollup over the attribution
-- columns added in migration 14, joined to outcomes (migration 9) so each source
-- shows not just volume but quality and what it actually converts to.
--
-- Per channel: lead count, avg score, avg booking probability, how many were
-- sold, booked, or disputed, marketplace revenue (sum of price_paid) and the
-- booked move value, plus book_rate = booked / leads (end-to-end yield).
-- =============================================================================

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
            'book_rate',               book_rate
        ) order by leads desc
    ), '[]'::jsonb)
    from agg;
$$;

comment on function public.leads_by_source() is
    'Per-channel acquisition rollup: volume, avg score/booking probability, '
    'sold/booked/disputed counts, marketplace revenue, booked move value, and '
    'book_rate (booked/leads). Answers "where are the leads coming from".';

revoke all on function public.leads_by_source() from public, anon, authenticated;
grant execute on function public.leads_by_source() to service_role;
