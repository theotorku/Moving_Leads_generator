# Moving Leads AI

An AI-powered lead generation and monetization platform for the moving industry, featuring intelligent lead scoring, subscription management, and a comprehensive admin dashboard.

## 🚀 Features

### Lead Generation & AI Scoring
- **Structured Lead Intelligence** - OpenAI returns score, booking probability, job value, route type, complexity, fraud risk, confidence, and follow-up guidance
- **Smart Lead Capture** - Modern, responsive form with real-time validation
- **Automated Reasoning** - AI provides detailed scoring rationale
- **Outcome-Calibrated Scores** - A new lead's AI booking probability is blended toward the *real* book rate of its route+urgency segment (shrinkage toward the AI prior), and high-dispute segments bump fraud risk — scores get sharper as outcomes accrue
- **Lead Attribution, Provenance & TCPA Consent** - Every lead records channel, medium, campaign, partner/referrer, landing page, source URL, capture IP (first `X-Forwarded-For` hop), and explicit TCPA consent (text + timestamp) — the compliance layer for selling exclusive leads
- **Multi-Source Ingestion** - Leads enter via the public form, an authenticated partner API (`POST /leads/intake` with per-partner keys), or admin CSV bulk-import — all sharing one scoring/persistence pipeline so every channel is scored and attributed identically
- **Source ROI** - Set a cost-per-lead per channel; the Sources view derives spend, profit, ROI, and acquisition cost-per-booked-move so you can see which channels actually pay off

### Feedback Loop & Routing
- **Outcome Tracking** - Record each sold lead's progress (contacted → appointment → booked, or lost/disputed/refunded) and surface **cost per booked move** and conversion analytics
- **Buyer Routing Profiles** - Per-customer fit rules (service ZIPs/prefixes, accepted route types & home sizes, minimum job value, FMCSA #); assignment ranks buyers by fit and down-ranks mismatches with a clear reason

### Monetization System
- **Hybrid Revenue Model** - Base subscription + pay-per-lead overage
- **Webhook Reconciliation** - Stripe subscription/payment events keep the database in sync via `POST /stripe/webhook` (idempotent); set `RECONCILE_VIA_WEBHOOK=true` to make it authoritative and skip per-read Stripe calls
- **Three Pricing Tiers:**
  - **Starter:** $299/mo - 30 leads included, $12/lead overage
  - **Professional:** $599/mo - 75 leads included, $10/lead overage
  - **Enterprise:** $999/mo - 150 leads included, $8/lead overage
- **Stripe Integration** - Automated subscription and payment processing
- **Usage Tracking** - Real-time lead allocation monitoring

### Admin Dashboard ("Command Center")
- **Analytics Overview** - MRR, customer count, lead metrics, plus conversion + cost-per-booked-move
- **Lead Management** - View, filter, and assign leads to customers, with source channel/campaign visible in the lead grid and assignment panel
- **AI-Guided Assignment** - Rank customers by lead intelligence, routing-profile fit, assignment readiness, remaining capacity, and billing health; the assignment panel shows TCPA consent / source / "Exclusive (sold once)"
- **Outcome Tracker** - Mark a purchased lead's outcome to feed the calibration loop
- **Customer Management** - Track subscriptions and usage; edit each buyer's routing profile; register new customers in-dashboard
- **Secure Authentication** - Basic HTTP auth for admin routes

### Customer Experience
- **Self-Serve Portal** - Customers can review subscription status, remaining allocation, and recent lead purchases

### Technical Stack
- **Backend:** FastAPI (Python 3.11+)
- **Database:** Supabase (PostgreSQL)
- **AI:** OpenAI `gpt-4o-mini` (structured JSON), with a deterministic heuristic fallback
- **Payments:** Stripe
- **Frontend:** Vanilla HTML/CSS/JS with glassmorphism design
- **Deployment:** Docker ready

## 📁 Project Structure

```
Moving_Leads_generator/
│
├── app/
│   ├── main.py                  # FastAPI app, routers, static frontend
│   ├── config.py                # Settings (env-driven; secrets via SecretStr)
│   ├── models.py                # Pydantic schemas
│   ├── db.py                    # Supabase client (uses the service_role key)
│   ├── routes/
│   │   ├── leads.py             # Lead scoring & persistence
│   │   ├── customers.py         # Customer registration, usage, portal
│   │   ├── admin.py             # Admin dashboard API
│   │   └── webhooks.py          # Stripe webhook endpoint
│   ├── ai/
│   │   ├── scorer.py            # OpenAI lead analysis
│   │   └── calibration.py       # Blend AI scores with real segment outcomes
│   └── services/
│       ├── admin_service.py     # Assignment (RPC + routing fit), analytics, outcomes
│       ├── customer_service.py  # Registration & portal
│       ├── stripe_service.py    # Stripe + pricing tiers
│       └── webhook_service.py   # Webhook verification & reconciliation
│
├── frontend/                    # Server-rendered UI (no build step)
│   ├── index.html / style.css            # Lead capture form  (/)
│   ├── admin.html / admin.css            # Admin dashboard     (/admin)
│   └── customer.html / customer.css      # Customer portal     (/portal)
│
├── supabase/
│   ├── migrations/              # Schema, RPCs, RLS (apply with `supabase db push`)
│   └── README.md                # DB layer + security model
│
├── tests/
│   ├── test_api.py              # API tests (mocked Supabase)
│   └── integration/             # Opt-in live-DB smoke tests (RUN_SUPABASE_IT=1)
│
├── .env.example                 # Environment variables template
├── Dockerfile                   # Production container
├── render.yaml                  # Render deploy blueprint
├── requirements.txt
└── README.md
```

## 🛠️ Setup

### Prerequisites
- Python 3.11+
- Supabase account
- OpenAI API key
- Stripe account (for monetization)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/theotorku/Moving_Leads_generator.git
   cd Moving_Leads_generator
   ```

2. **Create virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables:**
   
   Copy `.env.example` to `.env` and fill in your credentials:
   ```bash
   # OpenAI
   OPENAI_API_KEY=sk-...

   # Supabase — the backend uses the SERVICE_ROLE key (bypasses RLS; keep server-side only)
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_KEY=your-service-role-key

   # Stripe (for monetization)
   STRIPE_SECRET_KEY=sk_test_...
   STRIPE_WEBHOOK_SECRET=whsec_...          # for POST /stripe/webhook
   RECONCILE_VIA_WEBHOOK=false              # set true once the webhook is live

   # Admin Dashboard (replace defaults before production)
   ADMIN_USERNAME=admin
   ADMIN_PASSWORD=your-secure-password
   ```

5. **Apply the database migrations:**

   The schema, RPCs, and row-level security live in `supabase/migrations/`. Apply
   them to your project (don't hand-create tables) — see `supabase/README.md`:
   ```bash
   supabase link --project-ref <your-project-ref>
   supabase db push
   ```
   Or paste each migration, in order, into the Supabase SQL Editor. This creates
   `leads` (with provenance + consent columns), `customers`, `subscriptions`,
   `lead_purchases` (with outcome columns), `pricing_tiers`, `routing_profiles`, and
   `stripe_events`; the `assign_lead_to_customer` / `admin_analytics` /
   `record_lead_outcome` / `conversion_analytics` / `lead_segment_stats` RPCs; the
   reconciliation views; and enables RLS. See `supabase/README.md` for the full
   ordered list (migrations 0-14).

### Lead Attribution

The public lead form captures acquisition data from the page URL and sends it
with each scored lead. Use standard tracking parameters on campaigns and partner
links:

```text
/?utm_source=google_lsa&utm_medium=cpc&utm_campaign=dallas_summer&partner=realtor42
```

Supported fields are `utm_source`/`source`/`src`/`lead_source`,
`utm_medium`/`medium`, `utm_campaign`/`campaign`, and
`partner`/`partner_id`/`affiliate`/`affiliate_id`. The backend normalizes common
sources into channels such as `direct`, `organic`, `google_lsa`, `google_ads`,
`yelp`, `angi`, `thumbtack`, `realtor_partner`, `referral_partner`, `email`,
`social`, `webhook`, and `manual`.

6. **Run the application:**
   ```bash
   uvicorn app.main:app --reload
   ```
   
   Visit `http://localhost:8000` for the lead form
   Visit `http://localhost:8000/admin` for the dashboard
   Visit `http://localhost:8000/portal` for the customer portal

## 🐳 Docker Deployment

1. **Build the image:**
   ```bash
   docker build -t moving-leads-ai .
   ```

2. **Run the container:**
   ```bash
   docker run -p 8000:8000 --env-file .env moving-leads-ai
   ```
   (The image honors `$PORT`; defaults to 8000.)

## 🚀 Production deploy (Render)

Push-to-`main` autodeploys via `render.yaml`. See **[DEPLOY.md](DEPLOY.md)** for the
full runbook: rotating secrets, scrubbing test data, setting Render env vars,
registering the Stripe webhook, and the production smoke test.

## 🧪 Testing

Run the test suite:
```bash
pytest
```

## 📊 API Endpoints

### Public Endpoints
- `POST /leads/score` - Submit and score a lead (returns the scored lead + persistence status)

### Partner Intake (API key)
- `POST /leads/intake` - Authenticated inbound lead intake for partners / aggregators / webhooks. Send the partner's key as the `X-API-Key` header; the key resolves to a registered channel + partner (which is stamped onto the lead — partners can't spoof attribution), then the lead runs the same scoring + persistence pipeline and is marked `verified`. Accepts common aliased field names (`name`→`full_name`, `origin`→`origin_zip`, etc.).

### Webhooks
- `POST /stripe/webhook` - Stripe event reconciliation (signature-verified, idempotent via `stripe_events`)

### Customer Endpoints
- `POST /customers/register` - Register new customer with subscription
- `GET /customers/portal/access` - Load a customer portal summary using customer ID + email
- `GET /customers/{id}` - Get customer details
- `GET /customers/{id}/usage` - Get lead usage statistics

### Admin Endpoints (requires authentication)
- `GET /admin/analytics` - Revenue and usage metrics
- `GET /admin/conversion` - Conversion funnel + cost per booked move
- `GET /admin/sources` - Per-channel acquisition rollup (volume, quality, conversion, revenue, **spend / ROI / cost-per-booked**) — *where leads come from*
- `PUT /admin/sources/{channel}/cost` - Set a channel's acquisition cost-per-lead (drives spend / ROI)
- `GET /admin/leads` - List all leads (with filters)
- `GET /admin/leads/{id}/assignment-options` - Suggest the best-fit customer targets for a lead (routing fit + billing health)
- `POST /admin/leads/{id}/assign` - Assign lead to customer
- `POST /admin/purchases/{id}/outcome` - Record a purchased lead's outcome (feeds calibration)
- `GET /admin/customers` - List all customers
- `GET /admin/customers/{id}/routing-profile` - Read a buyer's routing profile
- `PUT /admin/customers/{id}/routing-profile` - Create/update a buyer's routing profile
- `GET /admin/ingest-sources` - List partner intake keys (metadata only)
- `POST /admin/ingest-sources` - Create a partner intake key (returns the key **once**)
- `POST /admin/ingest-sources/{id}/revoke` - Deactivate a partner key
- `POST /admin/leads/import` - Bulk-import leads from an uploaded CSV (scored + persisted per row)

## 💰 Revenue Model

The platform uses a hybrid monetization strategy:

1. **Subscription Revenue:** Predictable monthly recurring revenue
2. **Overage Revenue:** Additional income from high-volume customers
3. **Tiered Pricing:** Caters to different customer sizes

**Example Revenue Projection:**
- 10 Starter customers: $2,990/month MRR
- Plus overage revenue from lead purchases
- Scalable to hundreds of customers

## 🎨 UI Features

- **Glassmorphism Design** - Modern, premium aesthetic
- **Responsive Layout** - Works on all devices
- **Loading States** - Smooth user experience
- **Dynamic Scoring** - Color-coded lead quality indicators
- **Real-time Analytics** - Live dashboard updates

## 🔒 Security

- **Service-role backend / locked-down database** - the backend authenticates with
  the Supabase `service_role` key and is the only client that touches the database.
  **RLS is enabled on every table** and anon/authenticated have no access; the
  privileged RPCs are `EXECUTE`-restricted to `service_role`. See `supabase/README.md`.
- **Atomic lead sales** - `assign_lead_to_customer` runs as a single Postgres
  transaction with row locking + a `unique(lead_id)` guard, preventing duplicate or
  partial sales. Overage charges are linked to Stripe and surfaced in the
  `billing_reconciliation` views.
- **Attribution, provenance & TCPA consent** - each lead stores source channel,
  medium, campaign, partner/referrer, landing page, source URL, capture IP, and
  explicit consent (text + timestamp). The public form requires a consent checkbox
  and the Command Center surfaces consent status/source before a buyer purchases -
  the audit trail for selling contactable, exclusive leads.
- Startup validation with environment-based configuration warnings
- Basic HTTP authentication for admin routes (replace the default credentials)
- Secrets via `SecretStr`, excluded from version control

## 📝 License

MIT License - See LICENSE file for details

## 🤝 Contributing

Contributions welcome! Please open an issue or submit a pull request.

## 📧 Support

For questions or support, please open an issue on GitHub.

---

**Built with ❤️ for the moving industry**
