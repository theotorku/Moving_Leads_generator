-- =============================================================================
-- 20260101000008_lock_down_leads_anon.sql
-- The React frontend (which read Supabase directly with the anon key) has been
-- retired. The only UI now is the FastAPI-served vanilla frontend, which talks
-- to the backend (service_role) — no browser client touches Supabase directly.
--
-- So remove the last anon access: the leads dashboard read. The database is now
-- fully locked to service_role; anon/authenticated can reach nothing.
-- =============================================================================

drop policy if exists leads_anon_select on public.leads;
revoke all on table public.leads from anon, authenticated;
