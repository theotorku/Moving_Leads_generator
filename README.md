# Moving Leads AI

This project is an AI-powered lead generation system for the moving industry, utilizing FastAPI, Pydantic AI, Supabase, OpenAI, and Docker.

## Project Structure

```
moving-leads-ai/
│
├── app/
│   ├── main.py               # FastAPI entrypoint (app & static files)
│   ├── models.py             # Pydantic schemas (RawLead, ScoredLead)
│   ├── routes/
│   │   └── leads.py          # Lead scoring & persistence logic
│   ├── ai/
│   │   └── scorer.py         # OpenAI-powered lead analysis
│   └── db.py                 # Supabase client connection
│
├── frontend/
│   └── index.html            # Lead capture form
│
├── tests/
│   └── test_api.py           # Pytest API & Integration tests
│
├── .env                      # Secrets (OpenAI & Supabase Keys) - NOT IN GIT
├── Dockerfile                # Production container config
├── requirements.txt
└── README.md
```

## Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/theotorku/Moving_Leads_generator.git
   cd moving-leads-ai
   ```

2. **Environment Variables**:
   Create a `.env` file in the root directory:
   ```bash
   OPENAI_API_KEY="sk-..."
   SUPABASE_URL="https://your-project.supabase.co"
   SUPABASE_KEY="your-anon-key"
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the Application**:
   ```bash
   uvicorn app.main:app --reload
   ```
   Visit `http://localhost:8000` to see the form.

5. **Run Tests**:
   ```bash
   pytest
   ```

## Docker

To run the application using Docker:

1. Build the Docker image:
   ```bash
   docker build -t moving-leads-ai .
   ```
2. Run the Docker container:
   ```bash
   docker run -p 8000:8000 --env-file .env moving-leads-ai
   ```

## Features

- Lead Capture & Validation
- AI-Powered Lead Scoring
- Optional Dashboard for viewing and managing leads
- Monetization strategies included

## Requirements

- fastapi
- uvicorn
- pydantic
- pydantic-ai
- openai
- httpx
- supabase
- python-dotenv
