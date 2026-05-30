-- =============================================================================
-- 20260101000003_stripe_events.sql
-- Idempotency ledger for Stripe webhook events.
--
-- The webhook handler records each event_id here before processing. The UNIQUE
-- constraint on event_id is what makes delivery idempotent: Stripe retries the
-- same event_id, and a duplicate insert fails (23505) so we skip re-processing.
-- =============================================================================

create table if not exists public.stripe_events (
    id           uuid primary key default gen_random_uuid(),
    event_id     text not null unique,
    type         text not null,
    status       text not null default 'received',
    payload      jsonb,
    error        text,
    received_at  timestamptz not null default now(),
    processed_at timestamptz
);

create index if not exists stripe_events_type_idx on public.stripe_events (type);
create index if not exists stripe_events_received_at_idx on public.stripe_events (received_at desc);

do $$
begin
    if not exists (select 1 from pg_constraint where conname = 'stripe_events_status_valid') then
        alter table public.stripe_events add constraint stripe_events_status_valid
            check (status in ('received', 'processed', 'ignored', 'failed'));
    end if;
end $$;
