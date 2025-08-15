from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import items, invoice
import gradio as gr
from app.scraper import scrape_multiple_pages

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

# --------------------------
# Gradio Interface
# --------------------------
gradio_app = gr.Interface(
    fn=scrape_multiple_pages,
    inputs=[
        gr.Textbox(label="Enter URL", placeholder="https://example.com or example.com"),
        gr.Slider(minimum=1, maximum=10, value=3, step=1, label="How many pages to crawl?")
    ],
    outputs=gr.Textbox(label="Scraped Multi-Page Text"),
    title="React Website Multi-Page Scraper",
    description="Extracts readable text from JavaScript-rendered websites using Playwright."
)

# --------------------------
# FastAPI App
# --------------------------
# Mount Gradio inside FastAPI
app = gr.mount_gradio_app(app, gradio_app, path="/webscraper")

async def read_root():
    return {"message": "Welcome to the Simple FastAPI CRUD API! Visit /docs for API documentation. 💎💎💎"}
# hi
@app.get("/hi/{name}", tags=["Greeting"])
async def say_hi(name: str):
    return {"message": f"Hi {name}!"}

@app.get("/", tags=["Root"])
def root():
    return {"message": "Go to /webscraper to use the scraper interface"}
