-- =============================================================================
-- 20260101000018_admin_audit_log.sql
-- Audit trail for mutating admin actions. The admin UI authenticates with a
-- single shared HTTP Basic credential, so there's no per-user identity in the
-- request itself — this log records who (the admin username), what action, on
-- which target, with a JSON detail blob and the source IP, so money/PII actions
-- (selling a lead, recording an outcome, minting/revoking a partner key, setting
-- a channel cost) leave a trace. RLS-locked to service_role like every table.
-- =============================================================================

create table if not exists public.admin_audit_log (
    id          uuid primary key default gen_random_uuid(),
    admin_user  text,
    action      text not null,
    target_type text,
    target_id   text,
    detail      jsonb,
    ip          text,
    created_at  timestamptz not null default now()
);

create index if not exists admin_audit_log_created_idx on public.admin_audit_log (created_at desc);

alter table public.admin_audit_log enable row level security;
revoke all on public.admin_audit_log from anon, authenticated;

comment on table public.admin_audit_log is
    'Append-only trail of mutating admin actions (who/action/target/detail/ip). '
    'service_role only.';
