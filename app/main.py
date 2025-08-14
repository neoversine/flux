from fastapi import FastAPI
from app.routers import items, invoice

app = FastAPI(title="Simple FastAPI CRUD API")

app.include_router(items.router)
app.include_router(invoice.router, prefix="/tools", tags=["Tools"])

async def read_root():
    return {"message": "Welcome to the Simple FastAPI CRUD API! Visit /docs for API documentation. 💎💎💎"}
# hi
@app.get("/hi/{name}", tags=["Greeting"])
async def say_hi(name: str):
    return {"message": f"Hi {name}!"}

@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Welcome to the Simple FastAPI CRUD API! Visit /docs for API documentation 💎💎💎."}

@app.get("/tools/{name}", tags=["Greeting"])
async def say_hi(name: str):
    return {"message": f"getting ready {name}!"}