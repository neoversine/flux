
from fastapi import FastAPI, Depends, HTTPException
from .database import db, create_indexes
from .config import settings
from .auth import hash_password, create_access_token
from .routes import auth as auth_router_module, api as api_router_module, usage
from .deps import get_current_user
from .schemas import GenerateSecretOut, UserOut
from datetime import date
import secrets
from bson import ObjectId
from datetime import datetime
import sys
import asyncio
from fastapi import Request
from datetime import datetime
import time
from .database import db
from fastapi.middleware.cors import CORSMiddleware


if sys.platform == "win32" and sys.version_info >= (3, 8):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

app = FastAPI(title="FastAPI Mongo API - Usage limits")

# include routers
app.include_router(auth_router_module.router)
app.include_router(api_router_module.router)
app.include_router(usage.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    # ensure indexes
    await create_indexes()


@app.middleware("http")
async def log_api_usage(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = int((time.time() - start) * 1000)

    # Extract user email from API key (if provided)
    api_key = request.headers.get("x-api-key")
    user_email = None
    if api_key:
        user = await db.users.find_one({"api_key": api_key})
        if user:
            user_email = user["email"]

    if user_email:
        await db.api_usage.insert_one({
            "user_email": user_email,
            "endpoint": request.url.path,
            "method": request.method,
            "timestamp": datetime.utcnow(),
            "success": True if response.status_code < 400 else False,
            "response_time_ms": duration
        })

    return response


@app.get("/auth/me", response_model=UserOut)
@app.post("/auth/generate-secret", response_model=GenerateSecretOut)
async def generate_secret(current_user=Depends(get_current_user)):
    # current_user is a dict from deps.get_current_user
    user_db_id = current_user["_id"]
    token = secrets.token_hex(24)  # 48 hex chars
    # set token (upsert)
    await db.users.update_one({"_id": user_db_id}, {"$set": {"secret_token": token}})
    return {"secret_token": token}

@app.get("/auth/me", response_model=UserOut)
def me(current_user=Depends(get_current_user)):
    # convert _id to str
    return {
        "id": str(current_user["_id"]),
        "username": current_user["username"],
        "plan": current_user.get("plan", 0),
        "secret_token": current_user.get("secret_token")
    }

# Simple route to change plan for demonstration (not required but helpful)
@app.post("/auth/upgrade/{plan_id}")
async def upgrade_plan(plan_id: int, current_user=Depends(get_current_user)):
    if plan_id not in (0,1,2):
        raise HTTPException(status_code=400, detail="Invalid plan id")
    await db.users.update_one({"_id": current_user["_id"]}, {"$set": {"plan": plan_id}})
    return {"msg": "plan updated", "plan": plan_id}
