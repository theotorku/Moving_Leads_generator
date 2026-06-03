-- =============================================================================
-- 20260101000005_widen_subscription_status_check.sql
-- Drop the legacy narrow status CHECK on subscriptions.
--
-- The pre-existing live table had:
--   CHECK (status IN ('active','canceled','past_due','trialing'))
-- which would reject the normalized statuses the app also writes
-- ('unpaid','incomplete','paused','unknown'). The full set is enforced by
-- subscriptions_status_valid (added in 20260101000000_core_schema.sql).
-- No-op on fresh installs (the narrow constraint never existed there).
-- =============================================================================

alter table public.subscriptions drop constraint if exists subscriptions_status_check;
