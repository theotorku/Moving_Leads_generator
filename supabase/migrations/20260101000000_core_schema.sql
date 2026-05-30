-- =============================================================================
-- 20260101000000_core_schema.sql
-- Core schema for the Moving Leads platform.
--
-- Goals:
--   * Define every table/column the backend already uses (app/models.py,
--     app/services/*).
--   * Add the constraints that make analytics, lead sales, and billing safe.
--   * Be IDEMPOTENT and SAFE TO RUN against the existing, populated database
--     (CREATE ... IF NOT EXISTS, ADD COLUMN IF NOT EXISTS, backfill-then-NOT NULL,
--     guarded constraint creation).
--
-- Enum-like columns are enforced with CHECK constraints (not Postgres ENUM
-- types) to match how the Python layer sends normalized strings and to keep
-- value sets easy to evolve.
-- =============================================================================

create extension if not exists pgcrypto;  -- gen_random_uuid()

-- -----------------------------------------------------------------------------
-- Pricing tiers: single source of truth for plan price / allocation / overage.
-- Both the assign RPC and admin_analytics() read from this table, which removes
-- the PRICING_TIERS[tier] KeyError class of bugs at the database level.
-- -----------------------------------------------------------------------------
create table if not exists public.pricing_tiers (
    tier            text primary key,
    monthly_price   numeric(10, 2) not null check (monthly_price >= 0),
    leads_included  integer        not null check (leads_included >= 0),
    overage_price   numeric(10, 2) not null check (overage_price >= 0),
    constraint pricing_tiers_tier_valid
        check (tier in ('starter', 'professional', 'enterprise'))
);

insert into public.pricing_tiers (tier, monthly_price, leads_included, overage_price)
values
    ('starter',      299, 30,  12),
    ('professional', 599, 75,  10),
    ('enterprise',   999, 150, 8)
on conflict (tier) do update set
    monthly_price  = excluded.monthly_price,
    leads_included = excluded.leads_included,
    overage_price  = excluded.overage_price;

-- -----------------------------------------------------------------------------
-- customers
-- -----------------------------------------------------------------------------
create table if not exists public.customers (
    id                 uuid primary key default gen_random_uuid(),
    company_name       text not null,
    email              text not null,
    phone              text,
    stripe_customer_id text,
    created_at         timestamptz not null default now()
);

create unique index if not exists customers_email_lower_key
    on public.customers (lower(email));
create unique index if not exists customers_stripe_customer_id_key
    on public.customers (stripe_customer_id)
    where stripe_customer_id is not null;

-- -----------------------------------------------------------------------------
-- subscriptions
-- -----------------------------------------------------------------------------
create table if not exists public.subscriptions (
    id                     uuid primary key default gen_random_uuid(),
    customer_id            uuid not null references public.customers (id) on delete cascade,
    tier                   text not null references public.pricing_tiers (tier),
    status                 text not null default 'unknown',
    leads_included         integer not null default 0,
    leads_used             integer not null default 0,
    stripe_subscription_id text,
    current_period_start   timestamptz,
    current_period_end     timestamptz,
    created_at             timestamptz not null default now()
);

-- Backfill nulls that may exist in the live table before tightening NOT NULL.
update public.subscriptions set status         = 'unknown' where status is null;
update public.subscriptions set leads_included = 0         where leads_included is null;
update public.subscriptions set leads_used     = 0         where leads_used is null;

alter table public.subscriptions
    alter column status         set not null,
    alter column status         set default 'unknown',
    alter column leads_included set not null,
    alter column leads_used     set not null,
    alter column leads_used     set default 0;

create unique index if not exists subscriptions_stripe_subscription_id_key
    on public.subscriptions (stripe_subscription_id)
    where stripe_subscription_id is not null;
create index if not exists subscriptions_customer_id_idx
    on public.subscriptions (customer_id);

do $$
begin
    -- NOT VALID: enforce on all new writes immediately without scanning (and
    -- possibly failing on) pre-existing rows. VALIDATE later after any cleanup.
    if not exists (select 1 from pg_constraint where conname = 'subscriptions_status_valid') then
        alter table public.subscriptions add constraint subscriptions_status_valid
            check (status in ('active','trialing','canceled','past_due','unpaid','incomplete','paused','unknown'))
            not valid;
    end if;
    if not exists (select 1 from pg_constraint where conname = 'subscriptions_usage_nonneg') then
        alter table public.subscriptions add constraint subscriptions_usage_nonneg
            check (leads_used >= 0 and leads_included >= 0) not valid;
    end if;
end $$;

-- -----------------------------------------------------------------------------
-- leads
-- -----------------------------------------------------------------------------
create table if not exists public.leads (
    id                       uuid primary key default gen_random_uuid(),
    full_name                text not null,
    email                    text not null,
    phone                    text not null,
    move_date                date not null,
    origin_zip               text not null,
    destination_zip          text not null,
    home_size                text,
    budget                   integer,
    urgency                  text,
    score                    integer,
    reasoning                text,
    booking_probability      integer,
    estimated_job_value      integer,
    route_type               text default 'unknown',
    move_complexity          text default 'medium',
    fraud_risk               text default 'medium',
    missing_info             text[] not null default '{}',
    recommended_followup     text,
    confidence               integer,
    best_customer_fit_reason text,
    status                   text not null default 'available',
    assigned_to              uuid references public.customers (id) on delete set null,
    created_at               timestamptz not null default now(),
    updated_at               timestamptz not null default now()
);

-- Columns added defensively in case the live table predates some AI fields.
alter table public.leads add column if not exists booking_probability      integer;
alter table public.leads add column if not exists estimated_job_value      integer;
alter table public.leads add column if not exists route_type               text default 'unknown';
alter table public.leads add column if not exists move_complexity          text default 'medium';
alter table public.leads add column if not exists fraud_risk               text default 'medium';
alter table public.leads add column if not exists missing_info             text[] not null default '{}';
alter table public.leads add column if not exists recommended_followup     text;
alter table public.leads add column if not exists confidence               integer;
alter table public.leads add column if not exists best_customer_fit_reason text;
alter table public.leads add column if not exists assigned_to              uuid references public.customers (id) on delete set null;
alter table public.leads add column if not exists updated_at               timestamptz not null default now();

update public.leads set status = 'available' where status is null;
alter table public.leads
    alter column status set not null,
    alter column status set default 'available';

create index if not exists leads_status_idx     on public.leads (status);
create index if not exists leads_score_idx       on public.leads (score);
create index if not exists leads_created_at_idx   on public.leads (created_at desc);
create index if not exists leads_assigned_to_idx  on public.leads (assigned_to);

do $$
begin
    if not exists (select 1 from pg_constraint where conname = 'leads_status_valid') then
        alter table public.leads add constraint leads_status_valid
            check (status in ('available', 'sold')) not valid;
    end if;
    -- A sold lead must always name its buyer; an available lead must not.
    if not exists (select 1 from pg_constraint where conname = 'leads_sold_requires_buyer') then
        alter table public.leads add constraint leads_sold_requires_buyer
            check (
                (status = 'sold' and assigned_to is not null)
                or (status = 'available' and assigned_to is null)
            ) not valid;
    end if;
    -- FK for assigned_to in case the column pre-existed without one (ADD COLUMN
    -- IF NOT EXISTS above is skipped when the column already exists).
    if not exists (select 1 from pg_constraint where conname = 'leads_assigned_to_fkey') then
        alter table public.leads add constraint leads_assigned_to_fkey
            foreign key (assigned_to) references public.customers (id) on delete set null
            not valid;
    end if;
end $$;

-- -----------------------------------------------------------------------------
-- lead_purchases  (one row == one sale of one lead)
-- -----------------------------------------------------------------------------
create table if not exists public.lead_purchases (
    id                       uuid primary key default gen_random_uuid(),
    lead_id                  uuid not null references public.leads (id) on delete cascade,
    customer_id              uuid not null references public.customers (id) on delete cascade,
    subscription_id          uuid references public.subscriptions (id) on delete set null,
    purchase_type            text not null,
    price_paid               numeric(10, 2) not null default 0,
    currency                 text not null default 'usd',
    -- Billing reconciliation fields:
    payment_status           text not null default 'recorded',
    stripe_payment_intent_id text,
    idempotency_key          text,
    purchased_at             timestamptz not null default now()
);

-- Reconciliation columns added defensively for a pre-existing table.
alter table public.lead_purchases add column if not exists subscription_id          uuid references public.subscriptions (id) on delete set null;
alter table public.lead_purchases add column if not exists currency                 text not null default 'usd';
alter table public.lead_purchases add column if not exists payment_status           text not null default 'recorded';
alter table public.lead_purchases add column if not exists stripe_payment_intent_id text;
alter table public.lead_purchases add column if not exists idempotency_key          text;

update public.lead_purchases set price_paid = 0 where price_paid is null;
alter table public.lead_purchases
    alter column price_paid set not null,
    alter column price_paid set default 0;

create index if not exists lead_purchases_customer_id_idx on public.lead_purchases (customer_id);
create index if not exists lead_purchases_purchased_at_idx on public.lead_purchases (purchased_at desc);

-- THE hard guard against duplicate / double sales: a lead can be purchased once.
-- NOTE: if the live table already contains duplicate lead_ids this index will
-- fail to build. Detect them first with:
--   select lead_id, count(*) from public.lead_purchases group by lead_id having count(*) > 1;
create unique index if not exists lead_purchases_lead_id_key
    on public.lead_purchases (lead_id);

-- Idempotency + one DB row per Stripe charge.
create unique index if not exists lead_purchases_idempotency_key_key
    on public.lead_purchases (idempotency_key)
    where idempotency_key is not null;
create unique index if not exists lead_purchases_stripe_pi_key
    on public.lead_purchases (stripe_payment_intent_id)
    where stripe_payment_intent_id is not null;

do $$
begin
    if not exists (select 1 from pg_constraint where conname = 'lead_purchases_type_valid') then
        alter table public.lead_purchases add constraint lead_purchases_type_valid
            check (purchase_type in ('included', 'overage')) not valid;
    end if;
    if not exists (select 1 from pg_constraint where conname = 'lead_purchases_payment_status_valid') then
        alter table public.lead_purchases add constraint lead_purchases_payment_status_valid
            check (payment_status in ('recorded', 'pending', 'paid', 'failed', 'refunded'));
    end if;
    if not exists (select 1 from pg_constraint where conname = 'lead_purchases_price_nonneg') then
        alter table public.lead_purchases add constraint lead_purchases_price_nonneg
            check (price_paid >= 0);
    end if;
end $$;

-- -----------------------------------------------------------------------------
-- keep leads.updated_at fresh
-- -----------------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

drop trigger if exists leads_set_updated_at on public.leads;
create trigger leads_set_updated_at
    before update on public.leads
    for each row execute function public.set_updated_at();
