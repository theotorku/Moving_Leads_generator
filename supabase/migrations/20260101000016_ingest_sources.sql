-- =============================================================================
-- 20260101000016_ingest_sources.sql
-- Per-partner intake credentials. Each inbound lead source (an aggregator, a
-- referral partner, a Zapier/FB Lead Ads webhook) gets a row with its own API
-- key. We store only the SHA-256 hash of the key — the plaintext is shown once
-- at creation and never again. A presented key maps to a normalized channel and
-- partner id so POST /leads/intake can attribute and persist the lead.
--
-- RLS-locked like every other table: only the service_role backend touches it.
-- =============================================================================

create table if not exists public.ingest_sources (
    id            uuid primary key default gen_random_uuid(),
    slug          text not null unique,
    label         text not null,
    channel       text not null default 'webhook',
    partner       text,
    api_key_hash  text not null unique,
    active        boolean not null default true,
    created_at    timestamptz not null default now(),
    last_used_at  timestamptz
);

create index if not exists ingest_sources_active_idx on public.ingest_sources (active);

alter table public.ingest_sources enable row level security;
revoke all on public.ingest_sources from anon, authenticated;

comment on table public.ingest_sources is
    'Per-partner intake API keys (SHA-256 hashed). Resolves an inbound key to a '
    'source channel + partner for POST /leads/intake. service_role only.';
