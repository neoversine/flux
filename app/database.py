from motor.motor_asyncio import AsyncIOMotorClient
from .config import settings

client = AsyncIOMotorClient(settings.MONGO_URI)
db = client[settings.DATABASE_NAME]

async def create_indexes():
    # create unique index for username and secret_token
    await db.users.create_index("username", unique=True)
    await db.users.create_index("secret_token", unique=True, sparse=True)
