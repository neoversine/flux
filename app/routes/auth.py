from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pymongo.errors import DuplicateKeyError
from ..schemas import RegisterIn, TokenOut, UserOut, GenerateSecretOut
from ..database import db
from ..auth import hash_password, verify_password, create_access_token
from datetime import date
import secrets
from bson import ObjectId
from ..deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

# plan limits: plan_id -> monthly calls
PLANS = {0: 10, 1: 20, 2: 30}

@router.post("/register", status_code=201)
async def register(data: RegisterIn):
    existing = await db.users.find_one({"username": data.username})
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    user_doc = {
        "username": data.username,
        "password": hash_password(data.password),
        "plan": 0,
        "secret_token": None
    }
    try:
        res = await db.users.insert_one(user_doc)
        # create usage doc
        usage_doc = {
            "user_id": res.inserted_id,
            "calls_made_month": 0,
            "calls_today": 0,
            "last_day_reset": date.today().isoformat(),
            "last_month_reset": date.today().isoformat(),
        }
        await db.usage.insert_one(usage_doc)
        return {"msg": "user created"}
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="User with this username or email already exists.")

@router.post("/login", response_model=TokenOut)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await db.users.find_one({"username": form_data.username})
    if not user or not verify_password(form_data.password, user["password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect credentials")
    token = create_access_token(subject=user["username"])
    return {"access_token": token, "token_type": "bearer"}

@router.post("/generate-secret", response_model=GenerateSecretOut)
async def generate_secret(current_user=Depends(get_current_user)):
    import secrets
    token = secrets.token_hex(24)
    await db.users.update_one({"_id": current_user["_id"]}, {"$set": {"secret_token": token}})
    return {"secret_token": token}


@router.get("/get-secret", response_model=GenerateSecretOut)
async def get_secret(current_user=Depends(get_current_user)):
    user = await db.users.find_one({"_id": current_user["_id"]}, {"secret_token": 1})
    return {"secret_token": user.get("secret_token")}

