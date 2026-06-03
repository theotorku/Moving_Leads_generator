-- =============================================================================
-- 20260101000004_rls_hardening.sql
-- Lock down anon access now that the backend authenticates with the
-- service_role key (which BYPASSES RLS). After this:
--   * Backend (service_role): full access to everything, bypasses RLS.
--   * Frontend (anon, public key shipped in the browser bundle): may ONLY read
--     the leads table (for the dashboard); everything else is denied.
--   * The privileged RPCs can no longer be called with the anon key.
--
-- PREREQUISITE: the backend's SUPABASE_KEY must be the service_role key BEFORE
-- applying this, or the backend's table reads/writes and RPC calls will be
-- denied. (The public lead form posts through the backend, not directly.)
-- =============================================================================

-- 1) Enable RLS on every public table. With RLS on and no permissive policy,
--    anon/authenticated are denied; service_role bypasses RLS.
alter table public.leads          enable row level security;
alter table public.customers      enable row level security;
alter table public.subscriptions  enable row level security;
alter table public.lead_purchases enable row level security;
alter table public.pricing_tiers  enable row level security;
alter table public.stripe_events  enable row level security;

-- 2) The only direct anon access the frontend needs: read the leads dashboard.
--    NOTE: this still exposes lead PII to anyone holding the public anon key.
--    Recommended follow-up: put the dashboard behind auth and drop this policy.
drop policy if exists leads_anon_select on public.leads;
create policy leads_anon_select
    on public.leads
    for select
    to anon, authenticated
    using (true);

-- 3) Lock down the privileged RPCs: only the backend (service_role) may call them.
revoke all on function public.assign_lead_to_customer(uuid, uuid, text) from public, anon, authenticated;
revoke all on function public.admin_analytics() from public, anon, authenticated;
grant execute on function public.assign_lead_to_customer(uuid, uuid, text) to service_role;
grant execute on function public.admin_analytics() to service_role;
