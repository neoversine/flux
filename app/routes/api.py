from fastapi import APIRouter, Header, HTTPException, Query
from ..database import db
from datetime import date, datetime, timedelta, timezone
from bson import ObjectId
from ..utils.scraper import format_json_output, format_text_output, format_markdown_output, scrape_multiple_pages

router = APIRouter(prefix="/api", tags=["api"])

PLANS = {0: 10, 1: 20, 2: 30}

async def _reset_usage_if_needed(usage_doc):
    today = date.today()

    # Separate reset fields
    last_day_reset_str = usage_doc.get("last_day_reset")
    last_month_reset_str = usage_doc.get("last_month_reset")

    try:
        last_day_reset = datetime.fromisoformat(last_day_reset_str).date()
    except Exception:
        last_day_reset = today

    try:
        last_month_reset = datetime.fromisoformat(last_month_reset_str).date()
    except Exception:
        last_month_reset = today

    updated = False

    # Reset monthly if 30+ days passed
    if (today - last_month_reset).days >= 30:
        usage_doc["calls_made_month"] = 0
        usage_doc["last_month_reset"] = today.isoformat()
        updated = True

    # Reset daily if new day
    if last_day_reset != today:
        usage_doc["calls_today"] = 0
        usage_doc["last_day_reset"] = today.isoformat()
        updated = True

    return usage_doc, updated


@router.get("/scrapper")
async def use_api(
    x_api_key: str = Header(None),
    url: str = Query(..., min_length=1, description="Target URL to scrape"),
):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="x-api-key header required")

    user = await db.users.find_one({"secret_token": x_api_key})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")

    usage = await db.usage.find_one({"user_id": user["_id"]})
    if not usage:
        usage = {
            "user_id": user["_id"],
            "calls_made_month": 0,
            "calls_today": 0,
            "last_day_reset": date.today().isoformat(),
            "last_month_reset": date.today().isoformat(),
        }
        await db.usage.insert_one(usage)
    usage, changed = await _reset_usage_if_needed(usage)
    if changed:
        if usage.get("_id"):
            await db.usage.update_one({"_id": usage["_id"]}, {"$set": usage})
        else:
            await db.usage.update_one({"user_id": user["_id"]}, {"$set": usage})

    plan = user.get("plan", 0)
    plan_limit = PLANS.get(plan, 10)

    if usage["calls_made_month"] >= plan_limit:
        raise HTTPException(status_code=403, detail="Monthly API limit exceeded for your plan")

    new_calls_made = usage["calls_made_month"] + 1
    new_calls_today = usage["calls_today"] + 1
    await db.usage.update_one(
        {"user_id": user["_id"]},
        {
            "$set": {
                "calls_made_month": new_calls_made,
                "calls_today": new_calls_today,
                "last_day_reset": usage["last_day_reset"],
                "last_month_reset": usage["last_month_reset"],
            }
        },
    )

    # Save API call log
    await db.calls.insert_one({
        "user_id": user["_id"],
        "url": url,
        "time": date.today().isoformat()
    })

    results = await scrape_multiple_pages(url, max_pages=3)

    if not results or results[0].get('url') is None:
        raise HTTPException(status_code=500, detail="Scraping failed to retrieve URL information or URL key is missing in the result.")

    return {
        "message": "API call successful",
        "url": url,
        "calls_today": new_calls_today,
        "calls_made_month": new_calls_made,
        "plan_limit": plan_limit,
        "last_day_reset": usage["last_day_reset"],
        "last_month_reset": usage["last_month_reset"],
        "result1": format_json_output(results),
        "result2": format_text_output(results),
        "result3": format_markdown_output(results)
    }
