-- =============================================================================
-- 20260101000007_revoke_anon_grants.sql
-- Defense in depth on top of RLS: remove the anon/authenticated table grants on
-- everything except leads, so the sensitive tables aren't even discoverable in
-- the API / GraphQL schema. service_role (backend) is unaffected & bypasses RLS.
-- leads keeps anon SELECT for the public dashboard (read-only).
-- =============================================================================

revoke all on table public.customers      from anon, authenticated;
revoke all on table public.subscriptions  from anon, authenticated;
revoke all on table public.lead_purchases from anon, authenticated;
revoke all on table public.pricing_tiers  from anon, authenticated;
revoke all on table public.stripe_events  from anon, authenticated;
revoke all on table public.billing_reconciliation         from anon, authenticated;
revoke all on table public.billing_reconciliation_summary from anon, authenticated;

revoke insert, update, delete, truncate on table public.leads from anon, authenticated;
grant select on table public.leads to anon, authenticated;
