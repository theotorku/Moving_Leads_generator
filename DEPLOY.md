# Deployment runbook — Moving Leads AI

Target: **Render** web service (Python runtime), autodeploy on `main`, reusing the
existing Supabase project `vycmndrlixxefvlfkdxg`, **Stripe in test mode** first.

The app serves its own frontend same-origin (no CORS) and talks to Supabase with
the `service_role` key. Database migrations live in `supabase/migrations/` and are
applied out-of-band (Render does not run them).

---

## 0. Prerequisites
- Repo pushed to GitHub (`main`).
- Accounts: Render, Supabase (existing project), OpenAI, Stripe (test mode).
- Migrations 0–17 are already applied to `vycmndrlixxefvlfkdxg`.

## 1. Rotate the leaked secrets  ⚠️ blocker — do this first
Both were pasted into a chat transcript and must be considered compromised:
- **Supabase `service_role` key** — Supabase Dashboard → Project Settings → API →
  *Roll* the `service_role` key. Copy the new value (used as `SUPABASE_KEY`).
- **Stripe secret key** — Stripe Dashboard → Developers → API keys → roll the
  `sk_test_…` key. Copy the new value.

Do **not** put either in the repo — they go into Render's dashboard (step 4).

## 2. Scrub test data from Supabase
In the Supabase SQL editor (verify the rows first, then delete what you don't want
to ship). Leave `pricing_tiers` (seeded reference data) intact.
```sql
-- inspect
select id, email, source_channel, created_at from public.leads order by created_at;
select id, company_name, email from public.customers;

-- remove leftover test/demo rows (adjust the filter to taste)
delete from public.lead_purchases where lead_id in (select id from public.leads where email like '%@example.com');
delete from public.leads      where email like '%@example.com';
delete from public.channel_costs;     -- any leftover cost rows
delete from public.ingest_sources where slug like 'verify%';
-- subscriptions/customers: delete the trial customer if it's only test data
```

## 3. Create the Render service
Option A — **Blueprint (recommended):** Render → *New* → *Blueprint* → pick this
repo. Render reads `render.yaml` (service `moving-leads-ai`, `starter` plan,
`healthCheckPath: /health`, autodeploy on `main`).

Option B — manual web service: runtime Python, build `pip install -r requirements.txt`,
start `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2`.

## 4. Set secrets in the Render dashboard
The `sync: false` vars in `render.yaml` are **not** committed — set them under
the service's *Environment*:

| Key | Value |
| --- | --- |
| `SUPABASE_KEY` | the **rotated** `service_role` key |
| `OPENAI_API_KEY` | your OpenAI key |
| `ADMIN_PASSWORD` | a strong password (not `changeme`) |
| `STRIPE_SECRET_KEY` | the **rotated** `sk_test_…` key |
| `STRIPE_WEBHOOK_SECRET` | set in step 6 (leave empty for now) |

Already in `render.yaml` (no action): `SUPABASE_URL`, `ADMIN_USERNAME`,
`RECONCILE_VIA_WEBHOOK=false`, `RATE_LIMIT_PER_MINUTE=30`, `PYTHON_VERSION`.

## 5. Deploy & verify health
Trigger the first deploy (autodeploys on push to `main`). When live:
```bash
curl https://<your-app>.onrender.com/health     # -> {"status":"ok"}
```
Open `/` (form), `/admin` (login with your new admin creds), `/portal`.

## 6. Register the Stripe webhook (test mode)
1. Stripe Dashboard (test mode) → Developers → Webhooks → *Add endpoint*:
   `https://<your-app>.onrender.com/stripe/webhook`
2. Events: `customer.subscription.*`, `invoice.payment_succeeded`,
   `invoice.payment_failed`, `payment_intent.succeeded`,
   `payment_intent.payment_failed`, `charge.refunded`.
3. Copy the signing secret (`whsec_…`) → set `STRIPE_WEBHOOK_SECRET` in Render.
4. Once confirmed working, set `RECONCILE_VIA_WEBHOOK=true` in Render (removes the
   per-read Stripe sync). Redeploy/restart to pick up env changes.

## 7. Production smoke test
- **Form + attribution:** submit `/?utm_source=google_lsa&utm_campaign=test` → lead
  appears in `/admin` with channel `google_lsa`.
- **Admin:** analytics load, select a lead → recommendation panel renders.
- **Intake:** Sources view → create a partner key → `POST /leads/intake` with
  `X-API-Key` → lead appears (verified, attributed to the key's channel).
- **CSV import:** upload a small CSV → imported/skipped report.
- **Billing (test):** register a customer → Stripe test subscription created;
  trigger a test event (`stripe trigger payment_intent.succeeded`) → reconciled.

## 8. (Optional) Custom domain
Render → service → *Settings* → *Custom Domains* → add domain, create the CNAME at
your DNS provider. TLS is provisioned automatically.

---

## Going to Stripe **live** later
1. Swap `STRIPE_SECRET_KEY` to the `sk_live_…` key.
2. Create a **live-mode** webhook (repeat step 6) and update `STRIPE_WEBHOOK_SECRET`.
3. Confirm the Stripe business account is fully activated (payouts enabled).

## Notes & known limits
- **Rate limiting is per-process.** With `--workers 2` the effective public limit
  is ~`2 × RATE_LIMIT_PER_MINUTE` per IP — enough for cost protection, not a hard
  cluster cap. A strict limit would need Redis.
- **Admin auth is HTTP Basic** with a single shared credential over TLS. Fine for a
  small operator; consider per-user auth if the team grows.
- **CI/CD:** pushes to `main` autodeploy on Render. GitHub Actions runs the mocked
  suite on every push; set the `SUPABASE_*`/`OPENAI`/`ADMIN_*` repo secrets to also
  run the live smoke + browser E2E jobs (ideally against a separate test project).
- **Migrations:** apply new files in `supabase/migrations/` via `supabase db push`
  (or the SQL editor) before/with the deploy that needs them.
