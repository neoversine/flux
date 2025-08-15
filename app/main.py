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
# --------------------------
# Gradio Blocks UI
# --------------------------

with gr.Blocks(title="React Website Multi-Page Scraper") as gradio_app:
    gr.Markdown("# 🕷 React Website Multi-Page Scraper")
    gr.Markdown("Extracts readable text from JavaScript-rendered websites using Playwright.")

    with gr.Row():
        url = gr.Textbox(label="Enter URL", placeholder="https://example.com or example.com")
        pages = gr.Slider(minimum=1, maximum=10, value=3, step=1, label="How many pages to crawl?")

    output = gr.Textbox(label="Scraped Multi-Page Text", lines=20)
    scrape_btn = gr.Button("Scrape Website")
    scrape_btn.click(scrape_multiple_pages, inputs=[url, pages], outputs=[output])

# --------------------------
# Mount Gradio inside FastAPI
# --------------------------
app = gr.mount_gradio_app(app, gradio_app, path="/webscraper")
# --- Extra routes ---
@app.get("/hi/{name}", tags=["Greeting"])
async def say_hi(name: str):
    return {"message": f"Hi {name}!"}

@app.get("/", tags=["Root"])
def root():
    return {"message": "Go to /webscraper to use the scraper interface"}
