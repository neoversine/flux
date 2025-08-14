from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import items, invoice

app = FastAPI(title="Simple FastAPI CRUD API")

# --- Add CORS Middleware ---
# This allows requests from any origin.
# For production, you might want to restrict this to specific domains.
# e.g., origins = ["https://your-frontend-domain.com"]
origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allows all headers
)
# -------------------------

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
