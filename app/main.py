from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import gradio as gr
import os

from app.routers import items, invoice
from app.scraper import scrape_multiple_pages

app = FastAPI(title="Simple FastAPI CRUD API")

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routers ---
app.include_router(items.router)
app.include_router(invoice.router, prefix="/tools", tags=["Tools"])

# --- Gradio Interface ---
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

# Mount Gradio app
app = gr.mount_gradio_app(app, gradio_app, path="/webscraper")

# --- Serve Gradio static files manually ---
# Find where Gradio stores its static assets
gradio_static_dir = os.path.join(os.path.dirname(gr.__file__), "templates", "frontend", "assets")

# Mount them so requests to /webscraper/assets/... work
app.mount("/assets", StaticFiles(directory=gradio_static_dir), name="assets")

# Serve manifest.json so it doesn't 404
manifest_path = os.path.join(gradio_static_dir, "..", "manifest.json")
@app.get("/manifest.json")
async def serve_manifest():
    return FileResponse(os.path.abspath(manifest_path))

# --- Extra routes ---
@app.get("/hi/{name}", tags=["Greeting"])
async def say_hi(name: str):
    return {"message": f"Hi {name}!"}

@app.get("/", tags=["Root"])
def root():
    return {"message": "Go to /webscraper to use the scraper interface"}
