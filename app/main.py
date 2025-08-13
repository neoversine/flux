from fastapi import FastAPI
from app.routers import items

app = FastAPI(title="Simple FastAPI CRUD API")

app.include_router(items.router)

@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Welcome to the Simple FastAPI CRUD API! Visit /docs for API documentation."}
