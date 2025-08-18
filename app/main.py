from fastapi import FastAPI ,Query
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.responses import FileResponse
# import gradio as gr
# import os
# import bcrypt
# # from sqladmin import Admin
# from sqladmin.authentication import AuthenticationBackend
# from starlette.requests import Request

# from app.routers import items, invoice, api_keys, payments
# from app.scraper import scrape_multiple_pages
# from app.database import engine, SessionLocal
# from app import models
# from app.admin import UserAdmin, ApiKeyAdmin, PlanAdmin, SubscriptionAdmin, UsageAdmin, ItemAdmin
from app.scraper import scrape_multiple_pages, format_json_output, format_text_output,format_markdown_output

# Create database tables
# models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Simple FastAPI CRUD API")

# --- Admin Panel Authentication ---
# class BasicAuth(AuthenticationBackend):
# async def login(self, request: Request) -> bool:
#         form = await request.form()
#         username, password = form["username"], form["password"]
        
#         db = SessionLocal()
#         # Use email for login
#         user = db.query(models.User).filter(models.User.email == username).first()
#         db.close()

#         if user and bcrypt.checkpw(password.encode('utf-8'), user.password.encode('utf-8')):
#             request.session.update({"token": "..."})  # A simple token
#             return True
#         return False

#     async def logout(self, request: Request) -> bool:
#         request.session.clear()
#         return True

#     async def authenticate(self, request: Request) -> bool:
#         return "token" in request.session

# authentication_backend = BasicAuth(secret_key="please_change_this_secret")

# --- Admin Panel Setup ---
# admin = Admin(app, engine, authentication_backend=authentication_backend)
# admin.add_view(UserAdmin)
# admin.add_view(ApiKeyAdmin)
# admin.add_view(PlanAdmin)
# admin.add_view(SubscriptionAdmin)
# admin.add_view(UsageAdmin)
# admin.add_view(ItemAdmin)

# @app.on_event("startup")
# async def startup():
#     """Create a default admin user."""
#     db = SessionLocal()
#     if not db.query(models.User).filter(models.User.email == "admin@example.com").first():
#         hashed_password = bcrypt.hashpw("admin".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
#         admin_user = models.User(
#             email="admin@example.com",
#                 password=hashed_password,
#             is_active=True
#         )
#         db.add(admin_user)
#         db.commit()
#     db.close()

# --- CORS ---
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# --- Routers ---
# app.include_router(items.router)
# app.include_router(invoice.router, prefix="/tools", tags=["Tools"])
# app.include_router(api_keys.router, prefix="/auth", tags=["API Keys"])
# app.include_router(payments.router, prefix="/payments", tags=["Payments"])

# --- Gradio Interface ---
# gradio_app = gr.Blocks(title="React Website Multi-Page Scraper")
# with gradio_app:
#     gr.Markdown("# 🕷 React Website Multi-Page Scraper")
#     gr.Markdown("Extracts readable text from JavaScript-rendered websites using Playwright.")
#     with gr.Row():
#         url = gr.Textbox(label="Enter URL", placeholder="https://example.com")
#         pages = gr.Slider(minimum=1, maximum=10, value=3, step=1, label="How many pages to crawl?")
#     output = gr.Textbox(label="Scraped Multi-Page Text", lines=20)
#     scrape_btn = gr.Button("Scrape Website")
#     scrape_btn.click(scrape_multiple_pages, inputs=[url, pages], outputs=[output])

# app = gr.mount_gradio_app(app, gradio_app, path="/webscraper")

# --- Static Files & Extra Routes ---
# @app.get("/manifest.json", include_in_schema=False)
# async def manifest():
#     return FileResponse("app/static/manifest.json")

@app.get("/hi/{name}", tags=["Greeting"])
async def say_hi(name: str):
    return {"message": f"Hi {name}!"}

@app.get("/", tags=["Root"])
def root():
    return {"message": "Go to /webscraper or /admin"}

@app.get("/scrape")
def scrape(
    url: str = Query(..., description="Website URL to scrape"),
    max_pages: int = Query(3, ge=1, le=10, description="Number of pages to scrape"),
    output_format: str = Query("json", regex="^(json|text|markdown)$", description="Output format: json, text, or markdown")
):
    # call scraper function
    results = scrape_multiple_pages(url, max_pages=max_pages)

    # choose format
    if output_format == "json":
        return {"results": format_json_output(format_markdown_output(results))}
    elif output_format == "text":
        return {"results": format_text_output(results)}
    elif output_format == "markdown":
        return {"results": format_markdown_output(results)}
