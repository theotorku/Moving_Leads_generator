-- =============================================================================
-- 20260101000010_lead_segment_stats.sql
-- Outcomes -> scoring. Aggregate real conversion history for a lead "segment"
-- (route_type + urgency) so the scorer can calibrate a new lead's booking
-- probability against what actually happened to similar sold leads.
-- =============================================================================

create or replace function public.lead_segment_stats(
    p_route_type text,
    p_urgency    text
)
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
    with seg as (
        select lp.outcome
        from public.lead_purchases lp
        join public.leads l on l.id = lp.lead_id
        where coalesce(l.route_type, 'unknown') = coalesce(p_route_type, 'unknown')
          and coalesce(l.urgency, '')          = coalesce(p_urgency, '')
    )
    select jsonb_build_object(
        'n',        (select count(*) from seg),
        'booked',   (select count(*) from seg where outcome = 'booked'),
        'disputed', (select count(*) from seg where outcome = 'disputed')
    );
$$;

comment on function public.lead_segment_stats(text, text) is
    'Conversion history (n / booked / disputed) for a route_type+urgency segment, '
    'used to calibrate new-lead booking probability against real outcomes.';

revoke all on function public.lead_segment_stats(text, text) from public, anon, authenticated;
grant execute on function public.lead_segment_stats(text, text) to service_role;
