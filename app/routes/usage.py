from fastapi import APIRouter, Depends, HTTPException
from ..database import db
from ..deps import get_current_user   # import the user dependency
from datetime import date, timedelta, datetime
from ..routes.api import _reset_usage_if_needed  # reuse same reset function

router = APIRouter(prefix="/usage", tags=["usage"])

PLANS = {0: 10, 1: 20, 2: 30}


@router.get("/dashboard")
async def get_dashboard(user=Depends(get_current_user)):
    """
    Enhanced Dashboard showing API usage stats & analytics for the authenticated user.
    """

    # Fetch usage
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

    # Reset usage if needed (daily or monthly)
    usage, changed = await _reset_usage_if_needed(usage)
    if changed:
        if usage.get("_id"):
            await db.usage.update_one({"_id": usage["_id"]}, {"$set": usage})
        else:
            await db.usage.update_one({"user_id": user["_id"]}, {"$set": usage})

    # Get plan info
    plan = user.get("plan", 0)
    plan_limit = PLANS.get(plan, 10)

    # --- Daily usage stats from logs (db.calls collection) ---
    today = date.today()
    start_date = today - timedelta(days=6)

    pipeline = [
        {"$match": {
            "user_id": user["_id"],
            "time": {"$gte": datetime.combine(start_date, datetime.min.time()).isoformat()}
        }},
        {
            "$project": {
                "day": {"$substr": ["$time", 0, 10]},  # extract YYYY-MM-DD
            }
        },
        {
            "$group": {
                "_id": "$day",
                "calls": {"$sum": 1},
            }
        },
        {"$sort": {"_id": 1}},
    ]

    daily_stats = await db.calls.aggregate(pipeline).to_list(length=None)

    # Convert pipeline output into dict {date: calls}
    daily_dict = {item["_id"]: item["calls"] for item in daily_stats}

    # Fill missing days with 0
    trend = []
    for i in range(7):
        day = (start_date + timedelta(days=i)).isoformat()
        trend.append({"date": day, "calls": daily_dict.get(day, 0)})

    # Compare today vs yesterday
    today_calls = trend[-1]["calls"]
    yesterday_calls = trend[-2]["calls"] if len(trend) > 1 else 0
    if today_calls > yesterday_calls:
        comparison = "increased"
    elif today_calls < yesterday_calls:
        comparison = "decreased"
    else:
        comparison = "same"

    # Extra analytics
    avg_daily_calls = round(sum(item["calls"] for item in trend) / 7, 2)
    quota_used = round((usage.get("calls_made_month", 0) / plan_limit) * 100, 2)

    return {
        "username": user["username"],
        "plan": plan,
        "plan_limit": plan_limit,
        "calls_today": usage.get("calls_today", 0),
        "calls_made_month": usage.get("calls_made_month", 0),
        "remaining_quota": plan_limit - usage.get("calls_made_month", 0),
        "quota_used_percent": quota_used,
        "daily_trend": trend,  # list of {date, calls}
        "comparison_today_vs_yesterday": {
            "status": comparison,
            "today": today_calls,
            "yesterday": yesterday_calls
        },
        "average_daily_calls": avg_daily_calls,
        "last_day_reset": usage["last_day_reset"],
        "last_month_reset": usage["last_month_reset"],
    }
