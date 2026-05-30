# Moving Leads AI

An AI-powered lead generation and monetization platform for the moving industry, featuring intelligent lead scoring, subscription management, and a comprehensive admin dashboard.

## 🚀 Features

### Lead Generation & AI Scoring
- **Structured Lead Intelligence** - OpenAI returns score, booking probability, job value, route type, complexity, fraud risk, confidence, and follow-up guidance
- **Smart Lead Capture** - Modern, responsive form with real-time validation
- **Automated Reasoning** - AI provides detailed scoring rationale

### Monetization System
- **Hybrid Revenue Model** - Base subscription + pay-per-lead overage
- **Subscription Health Sync** - Stripe subscription status is refreshed before key customer and assignment workflows
- **Three Pricing Tiers:**
  - **Starter:** $299/mo - 30 leads included, $12/lead overage
  - **Professional:** $599/mo - 75 leads included, $10/lead overage
  - **Enterprise:** $999/mo - 150 leads included, $8/lead overage
- **Stripe Integration** - Automated subscription and payment processing
- **Usage Tracking** - Real-time lead allocation monitoring

### Admin Dashboard
- **Analytics Overview** - MRR, customer count, lead metrics
- **Lead Management** - View, filter, and assign leads to customers
- **AI-Guided Assignment** - Rank customers by lead intelligence, assignment readiness, remaining capacity, and billing health
- **Customer Management** - Track subscriptions and usage
- **Secure Authentication** - Basic HTTP auth for admin routes

### Customer Experience
- **Self-Serve Portal** - Customers can review subscription status, remaining allocation, and recent lead purchases

### Technical Stack
- **Backend:** FastAPI (Python 3.11+)
- **Database:** Supabase (PostgreSQL)
- **AI:** OpenAI GPT-3.5/4
- **Payments:** Stripe
- **Frontend:** Vanilla HTML/CSS/JS with glassmorphism design
- **Deployment:** Docker ready

## 📁 Project Structure

```
Moving_Leads_generator/
│
├── app/
│   ├── main.py                  # FastAPI app & routes
│   ├── models.py                # Pydantic schemas
│   ├── db.py                    # Supabase client
│   ├── routes/
│   │   ├── leads.py             # Lead scoring & persistence
│   │   ├── customers.py         # Customer registration & usage
│   │   └── admin.py             # Admin dashboard API
│   ├── ai/
│   │   └── scorer.py            # OpenAI lead analysis
│   └── services/
│       └── stripe_service.py    # Payment processing
│
├── frontend/
│   ├── index.html               # Product landing page + lead capture form
│   ├── style.css                # Landing page and form styling
│   ├── admin.html               # Admin dashboard
│   └── admin.css                # Dashboard styling
│
├── tests/
│   └── test_api.py              # API integration tests
│
├── .env.example                 # Environment variables template
├── Dockerfile                   # Production container
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
   
   # Supabase
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_KEY=your-anon-key
   
   # Stripe (for monetization)
   STRIPE_SECRET_KEY=sk_test_...
   STRIPE_PUBLISHABLE_KEY=pk_test_...
   
    # Admin Dashboard (replace defaults before production)
    ADMIN_USERNAME=admin
    ADMIN_PASSWORD=your-secure-password
   ```

5. **Set up Supabase data tables:**
    
   Create the tables used by the application in your Supabase project:
   - `leads`
   - `customers`
   - `subscriptions`
   - `lead_purchases`

   The `leads` table should include the base lead fields plus AI intelligence columns:
   `score`, `reasoning`, `booking_probability`, `estimated_job_value`, `route_type`,
   `move_complexity`, `fraud_risk`, `missing_info`, `recommended_followup`,
   `confidence`, `best_customer_fit_reason`, `status`, and `assigned_to`.

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

## 🧪 Testing

Run the test suite:
```bash
pytest
```

## 📊 API Endpoints

### Public Endpoints
- `POST /leads/score` - Submit and score a lead

### Customer Endpoints
- `POST /customers/register` - Register new customer with subscription
- `GET /customers/portal/access` - Load a customer portal summary using customer ID + email
- `GET /customers/{id}` - Get customer details
- `GET /customers/{id}/usage` - Get lead usage statistics

### Admin Endpoints (requires authentication)
- `GET /admin/analytics` - Revenue and usage metrics
- `GET /admin/leads` - List all leads (with filters)
- `GET /admin/leads/{id}/assignment-options` - Suggest the safest customer assignment targets for a lead
- `POST /admin/leads/{id}/assign` - Assign lead to customer
- `GET /admin/customers` - List all customers

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

- Startup validation with environment-based configuration warnings
- Basic HTTP authentication for admin routes
- Row-level security ready (Supabase)
- Secrets excluded from version control

## 📝 License

MIT License - See LICENSE file for details

## 🤝 Contributing

Contributions welcome! Please open an issue or submit a pull request.

## 📧 Support

For questions or support, please open an issue on GitHub.

---

**Built with ❤️ for the moving industry**
