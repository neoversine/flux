from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class RegisterIn(BaseModel):
    username: str
    password: str

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"

class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserOut(BaseModel):
    id: str
    username: str
    # plan: int
    # secret_token: Optional[str] = None

class GenerateSecretOut(BaseModel):
    secret_token: str

class UsageOut(BaseModel):
    calls_made_month: int
    calls_today: int
    plan_limit: int


class User(BaseModel):
    email: str
    api_key: str
    created_at: datetime

# API Usage log model
class ApiUsage(BaseModel):
    user_email: str
    endpoint: str
    method: str
    timestamp: datetime
    success: bool
    response_time_ms: Optional[int] = None
