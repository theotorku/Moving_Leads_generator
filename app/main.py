from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

app = FastAPI()

from .routes import leads, customers, admin as admin_routes
app.include_router(leads.router)
app.include_router(customers.router)
app.include_router(admin_routes.router)

# Serve static files
app.mount("/static", StaticFiles(directory="frontend"), name="static")

# Serve the HTML form at the root
@app.get("/", response_class=FileResponse)
async def read_index():
    return FileResponse("frontend/index.html")

# Serve admin dashboard
@app.get("/admin", response_class=FileResponse)
async def read_admin():
    return FileResponse("frontend/admin.html")
