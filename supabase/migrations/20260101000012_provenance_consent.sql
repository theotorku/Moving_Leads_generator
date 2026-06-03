-- =============================================================================
-- 20260101000012_provenance_consent.sql
-- Lead provenance + TCPA consent — the trust + compliance layer. Every lead can
-- now prove where/when it came from, whether the consumer consented to contact
-- (with the exact disclosure text + timestamp), and whether it's verified.
-- Exclusivity is already enforced by unique(lead_id) on lead_purchases.
--
-- These columns live on `leads`, which is RLS-locked to service_role, so
-- source_ip / consent records are never exposed to the anon (browser) key.
-- =============================================================================

alter table public.leads
    add column if not exists source        text not null default 'public_form',
    add column if not exists source_url    text,
    add column if not exists source_ip     text,
    add column if not exists consent_tcpa  boolean not null default false,
    add column if not exists consent_text  text,
    add column if not exists consent_at    timestamptz,
    add column if not exists verified      boolean not null default false,
    add column if not exists verified_at   timestamptz;

create index if not exists leads_source_idx on public.leads (source);
