"""Admin CSV bulk import: turn an uploaded list of leads into scored, persisted
rows via the shared scoring pipeline. Each row is mapped, validated, scored, and
stored; failures are collected per-row so a few bad rows don't sink the batch.
"""
import csv
import io
import logging

from fastapi import HTTPException
from pydantic import ValidationError

from ..models import RawLead
from .attribution import normalize_channel
from .ingest_service import map_intake_payload
from .scoring_service import score_and_store_lead

logger = logging.getLogger(__name__)

# Scoring calls the AI per row, so cap a single upload to keep it responsive.
MAX_ROWS = 200


async def import_leads_from_csv(content: str, *, channel: str = "manual") -> dict:
    """Parse CSV text, score+persist each row, and report imported/skipped."""
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no header row.")

    chan = normalize_channel(channel) if channel else "manual"
    rows = list(reader)
    overflow = max(0, len(rows) - MAX_ROWS)
    imported = 0
    skipped: list[dict] = []

    for index, row in enumerate(rows[:MAX_ROWS], start=2):  # row 1 is the header
        mapped = map_intake_payload(row)
        try:
            lead = RawLead(**mapped)
        except ValidationError as exc:
            reasons = "; ".join(f"{e['loc'][-1]}: {e['msg']}" for e in exc.errors())
            skipped.append({"row": index, "reason": reasons})
            continue

        source_fields = {
            "source": chan,
            "source_channel": chan,
            "source_medium": None,
            "source_campaign": mapped.get("source_campaign"),
            "source_referrer": None,
            "source_partner": mapped.get("source_partner"),
            "source_url": None,
            "landing_page": None,
        }
        try:
            await score_and_store_lead(
                lead, source_fields=source_fields, source_ip=None, verified=True
            )
            imported += 1
        except HTTPException:
            skipped.append({"row": index, "reason": "could not be saved (database error)"})

    if overflow:
        skipped.append({"row": None, "reason": f"{overflow} rows beyond the {MAX_ROWS}-row limit were not processed"})

    return {"imported": imported, "skipped": skipped, "channel": chan, "total_rows": len(rows)}
