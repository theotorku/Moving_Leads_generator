# Supabase migration / RPC layer

Real, versioned database schema for the Moving Leads platform. These migrations
define every table the backend uses, add the constraints that make the system
safe, and move the lead-sale and analytics logic into Postgres functions.

## Why this exists

The Python services talked to Supabase with ad-hoc, multi-call sequences and no
schema source of truth. That caused three concrete problems this layer fixes:

| Problem | Root cause | Fix |
| --- | --- | --- |
| **Analytics 500s** | `sum()` over a NULL `price_paid`; `PRICING_TIERS[tier]` KeyError on an unknown tier | `admin_analytics()` RPC: COALESCE every aggregate, MRR via JOIN to `pricing_tiers`; `price_paid` is `NOT NULL DEFAULT 0` |
| **Duplicate / partial lead sales** | read-then-write race (double-sell) + 3 non-atomic writes (partial state) | `assign_lead_to_customer()` does it all in one transaction with `SELECT … FOR UPDATE`; `unique(lead_id)` on `lead_purchases` as a hard backstop |
| **Fragile billing reconciliation** | overage charges not linked to Stripe, no per-charge uniqueness, no collected-vs-recorded view | reconciliation columns (`payment_status`, `stripe_payment_intent_id`, `idempotency_key`) + `billing_reconciliation` / `billing_reconciliation_summary` views |

## Files (apply in order)

1. `migrations/20260101000000_core_schema.sql` — extensions, `pricing_tiers`
   (seeded source of truth), `customers`, `subscriptions`, `leads`,
   `lead_purchases`; all columns, FKs, CHECK constraints, indexes, and the
   `updated_at` trigger. Idempotent and safe against the existing populated DB.
2. `migrations/20260101000001_assign_lead_rpc.sql` — the atomic
   `assign_lead_to_customer(p_lead_id, p_customer_id, p_idempotency_key)` RPC.
3. `migrations/20260101000002_analytics_and_reconciliation.sql` —
   `admin_analytics()` RPC and the two reconciliation views.
4. `migrations/20260101000003_stripe_events.sql` — `stripe_events` idempotency
   ledger for the webhook handler (`unique(event_id)`).
5. `migrations/20260101000005_widen_subscription_status_check.sql` — drop the
   legacy narrow status CHECK so normalized statuses are accepted.
6. `migrations/20260101000006_advisor_hardening.sql` — pin `set_updated_at`
   search_path; `security_invoker` on the reconciliation views.
7. `migrations/20260101000004_rls_hardening.sql` + `…0007_revoke_anon_grants.sql`
   + `…0008_lock_down_leads_anon.sql` — enable RLS and lock down anon (see
   Security below). **Apply these last, and only after the backend is on the
   service_role key.**
8. `migrations/20260101000009_lead_outcomes.sql` — outcome columns on
   `lead_purchases` plus `record_lead_outcome()` and `conversion_analytics()`
   RPCs: the feedback loop (sold → contacted → appointment → booked, plus
   lost/disputed) and **cost per booked move**.
9. `migrations/20260101000010_lead_segment_stats.sql` — `lead_segment_stats()`
   RPC feeding outcomes back into scoring: a new lead's AI booking probability
   is blended toward the real book rate of its route+urgency segment, and high
   dispute segments bump fraud risk (see `app/ai/calibration.py`).

## Security model (RLS)

- **Backend** authenticates with the **service_role** key (`SUPABASE_KEY` in
  `moving-leads-ai/.env`) and bypasses RLS — it performs all writes, admin reads,
  and RPC calls.
- **The UI is the FastAPI-served vanilla frontend** in `frontend/` (`/`,
  `/admin`, `/portal`); it calls backend endpoints only. No browser client reads
  Supabase directly. (The separate React app that did was retired.)
- The `assign_lead_to_customer` and `admin_analytics` RPCs are `EXECUTE`-revoked
  from anon/authenticated and granted to `service_role` only.

As of `20260101000008_lock_down_leads_anon.sql`, **anon/authenticated have no
access to any table** — the database is fully locked to `service_role`.

## Webhook reconciliation

`POST /stripe/webhook` (handler: `app/services/webhook_service.py`) verifies the
Stripe signature, records each event in `stripe_events` (the `unique(event_id)`
constraint dedupes Stripe retries), then keeps the DB in sync:

| Stripe event | Effect |
| --- | --- |
| `customer.subscription.created/updated/deleted` | update `subscriptions.status` + period dates by `stripe_subscription_id` |
| `invoice.payment_succeeded` / `…_failed` | set subscription `active` / `past_due` |
| `payment_intent.succeeded` / `…_failed` | set matching `lead_purchases.payment_status` to `paid` / `failed` |
| `charge.refunded` | set `lead_purchases.payment_status` to `refunded` |

Configure `STRIPE_WEBHOOK_SECRET`, point a Stripe webhook at `/stripe/webhook`,
then set `RECONCILE_VIA_WEBHOOK=true` to stop the per-read Stripe sync calls
(removes the N+1 latency on admin endpoints).

### Registering the endpoint

**Local dev (Stripe CLI):**
```bash
stripe listen --forward-to localhost:8000/stripe/webhook   # prints whsec_… -> STRIPE_WEBHOOK_SECRET
stripe trigger payment_intent.succeeded                    # send a test event
```

**Production (Dashboard):** Developers → Webhooks → *Add endpoint* →
`https://<your-host>/stripe/webhook`; subscribe to `customer.subscription.*`,
`invoice.payment_succeeded/failed`, `payment_intent.succeeded/payment_failed`,
`charge.refunded`; copy the signing secret to `STRIPE_WEBHOOK_SECRET`.

> Note: with `RECONCILE_VIA_WEBHOOK=true`, subscription/payment state is updated
> **only** by webhook events — make sure the endpoint is actually registered and
> reachable (in local dev, keep `stripe listen` running), or set it back to
> `false` to fall back to per-read Stripe sync.

## Applying

**Supabase CLI (recommended):**

```bash
supabase link --project-ref <your-project-ref>
supabase db push
```

**Or paste each file, in order, into the Supabase SQL Editor.**

> ⚠️ Before first apply, check for pre-existing duplicate sales — the new
> `unique(lead_id)` index will fail to build if any exist:
> ```sql
> select lead_id, count(*) from public.lead_purchases
> group by lead_id having count(*) > 1;
> ```
> Resolve duplicates, then re-run.

Several CHECK/FK constraints are added `NOT VALID` so the migration never fails
on pre-existing dirty rows — they still enforce on every new write. Once the
historical data is clean you can fully validate them, e.g.:

```sql
alter table public.leads validate constraint leads_sold_requires_buyer;
alter table public.subscriptions validate constraint subscriptions_status_valid;
```

## How the backend uses it

`app/services/admin_service.py` now calls the RPCs instead of issuing raw writes:

- `assign_lead_to_customer(...)` → `supabase.rpc("assign_lead_to_customer", {...})`.
  Errors raised by the function map to HTTP codes:
  `lead_not_found`/`no_subscription` → 404, `lead_already_assigned` (or SQLSTATE
  `23505`) → 409, `billing_not_assignable:<status>` → 409 with the billing message.
- `get_admin_analytics()` → `supabase.rpc("admin_analytics", {})`.

## Verification

After applying, from the SQL editor / psql:

```sql
-- analytics never throws, returns the full object
select public.admin_analytics();

-- a clean sale
select public.assign_lead_to_customer(
    '<available_lead_uuid>', '<customer_with_active_sub_uuid>');

-- selling the same lead again -> ERROR: lead_already_assigned
select public.assign_lead_to_customer(
    '<same_lead_uuid>', '<any_customer_uuid>');

-- idempotent replay returns the original sale, no new purchase row
select public.assign_lead_to_customer(
    '<lead_uuid>', '<customer_uuid>', 'retry-key-123');
select public.assign_lead_to_customer(
    '<lead_uuid>', '<customer_uuid>', 'retry-key-123');  -- "idempotent": true

-- money to chase
select * from public.billing_reconciliation_summary;
```

End-to-end via the API: `GET /admin/analytics` (200, no 500) and
`POST /admin/leads/{lead_id}/assign?customer_id=…` (second call on the same lead
returns 409).
