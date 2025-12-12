# Moving Leads AI

This project is an AI-powered lead generation system for the moving industry, utilizing FastAPI, Pydantic AI, Supabase, OpenAI, and Docker.

## Project Structure

```
moving-leads-ai/
│
├── app/
│   ├── main.py               # FastAPI entrypoint
│   ├── models.py             # Pydantic schemas (RawLead, ScoredLead, etc.)
│   ├── routes/
│   │   └── leads.py          # Lead ingestion, scoring, storage
│   ├── ai/
│   │   └── scorer.py         # Pydantic AI lead scoring logic
│   └── db.py                 # Supabase client
│
├── .env
├── Dockerfile
├── requirements.txt
└── README.md
```

## Setup

1. Clone the repository.
2. Navigate to the project directory.
3. Create a virtual environment and activate it.
4. Install the dependencies:
   ```
   pip install -r requirements.txt
   ```
5. Set up the environment variables in the `.env` file.
6. Run the application:
   ```
   uvicorn app.main:app --reload
   ```

## Docker

To run the application using Docker:

1. Build the Docker image:
   ```
   docker build -t moving-leads-ai .
   ```
2. Run the Docker container:
   ```
   docker run -p 8000:8000 moving-leads-ai
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
