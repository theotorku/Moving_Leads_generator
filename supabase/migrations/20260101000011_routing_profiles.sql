-- =============================================================================
-- 20260101000011_routing_profiles.sql
-- Per-buyer routing profiles: route leads by FIT (service area, accepted route
-- types / home sizes, minimum job value), not just availability. Empty array =
-- "no restriction" (serves everything).
-- =============================================================================

create table if not exists public.routing_profiles (
    customer_id          uuid primary key references public.customers (id) on delete cascade,
    service_zips         text[] not null default '{}',   -- exact ZIPs or prefixes ("100"); empty = nationwide
    accepted_route_types text[] not null default '{}',   -- subset of local/intrastate/interstate; empty = all
    accepted_home_sizes  text[] not null default '{}',   -- empty = all
    min_job_value        integer not null default 0,
    fmcsa_number         text,
    updated_at           timestamptz not null default now()
);

alter table public.routing_profiles enable row level security;  -- service_role only (bypasses RLS)
revoke all on table public.routing_profiles from anon, authenticated;

drop trigger if exists routing_profiles_set_updated_at on public.routing_profiles;
create trigger routing_profiles_set_updated_at
    before update on public.routing_profiles
    for each row execute function public.set_updated_at();
