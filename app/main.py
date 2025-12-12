from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

app = FastAPI()

from .routes import leads
app.include_router(leads.router)

# Serve static files
app.mount("/static", StaticFiles(directory="frontend"), name="static")

# Serve the HTML form at the root
@app.get("/", response_class=FileResponse)
async def read_index():
    return FileResponse("frontend/index.html")
