from pydantic import BaseModel
from datetime import date

class RawLead(BaseModel):
    full_name: str
    email: str
    phone: str
    move_date: date
    origin_zip: str
    destination_zip: str
    home_size: str
    budget: str
    urgency: str

class ScoredLead(RawLead):
    score: int
    reasoning: str