# 🐳 Docker Guide for Moving Leads AI

This guide provides instructions for building and running the **Moving Leads AI** application using Docker.

## 📋 Prerequisites

*   [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed on your machine.
*   A valid `.env` file with necessary API keys (OpenAI, Supabase, Stripe).

## 🛠️ 1. Build the Docker Image

Navigate to the project root directory and build the image. You can tag it as `moving-leads-ai`:

```bash
docker build -t moving-leads-ai .
```

*   `-t moving-leads-ai`: Tags the image with the name `moving-leads-ai`.
*   `.`: Specifies the current directory as the build context.

## ⚙️ 2. Configure Environment

Ensure you have a `.env` file in your project root. If not, copy the example:

```bash
cp .env.example .env
```
*(On Windows PowerShell: `Copy-Item .env.example .env`)*

Open `.env` and fill in your credentials:

```properties
OPENAI_API_KEY=sk-...
SUPABASE_URL=...
SUPABASE_KEY=...
STRIPE_SECRET_KEY=...
ADMIN_PASSWORD=...
```

## 🚀 3. Run the Container

Run the container, mapping port 8000 and passing your environment variables:

```bash
docker run -d -p 8000:8000 --env-file .env --name moving-leads-container moving-leads-ai
```

**Command Breakdown:**
*   `-d`: Runs the container in **detached** mode (in the background).
*   `-p 8000:8000`: Maps port 8000 on your host to port 8000 in the container.
*   `--env-file .env`: Injects environment variables from your `.env` file.
*   `--name moving-leads-container`: Assigns a friendly name to the running container.

## 🌐 4. Access the Application

Once running, the application is accessible at:

*   **Lead Form (Frontend):** [http://localhost:8000](http://localhost:8000)
*   **Admin Dashboard:** [http://localhost:8000/admin](http://localhost:8000/admin)
    *   *Default User:* `admin`
    *   *Default Pass:* Check your `.env` file (default in example is `changeme`)

## 🛑 5. Managing the Container

**Stop the container:**
```bash
docker stop moving-leads-container
```

**Remove the container:**
```bash
docker rm moving-leads-container
```

**View Logs:**
If something isn't working, check the application logs:
```bash
docker logs -f moving-leads-container
```

## 🚢 Production Notes

*   **Health Checks:** The current Dockerfile is minimal. For production, consider adding a `HEALTHCHECK` instruction.
*   **Reverse Proxy:** In a production environment, you should run this behind a reverse proxy like Nginx or Traefik with SSL/HTTPS enabled.
*   **Database:** This container connects to a remote Supabase instance. It does *not* run a local database.
