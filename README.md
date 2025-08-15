python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
 kill ->
 lsof -i :8010 
# Agents Tool Kit

This repository contains a collection of tools and resources for building and managing AI agents.

## Available Tools

### 1. Web Scraper

A web scraper with a Gradio interface that can extract text from multiple pages of a website.

**How to use:**

1.  Run the FastAPI application.
2.  Open your browser and navigate to `https://fast.finnofarms.in/webscraper`.
3.  Enter the URL of the website you want to scrape and the number of pages to crawl.
4.  Click "Submit" to see the scraped text.

### 2. Invoice Generator

An API endpoint to generate PDF invoices from a template.

**How to use:**

- Send a POST request to `/tools/invoice/` with the invoice details in the request body.

### 3. Items API

A simple CRUD API for managing items.

**Endpoints:**

- `GET /items/`: Get a list of items.
- `POST /items/`: Create a new item.
- `GET /items/{item_id}`: Get a specific item.
- `PUT /items/{item_id}`: Update an item.
- `DELETE /items/{item_id}`: Delete an item.

## FastAPI Server Management Tips

When deploying and managing FastAPI applications, consider the following best practices:

*   **Use an ASGI Server:** FastAPI is an ASGI framework, so use a production-ready ASGI server like Uvicorn or Hypercorn. Gunicorn can be used as a process manager for Uvicorn workers.
*   **Process Management:** Employ change a process manager (e.g., Gunicorn, Supervisor, systemd) to ensure your FastAPI application restarts automatically if it crashes and to manage multiple worker processes for concurrency.
*   **Asynchronous Operations:** Leverage FastAPI's asynchronous capabilities (`async def`, `await`) for I/O-bound operations (database calls, external API requests) to avoid blocking the event loop and improve responsiveness.
*   **Dependency Injection:** Utilize FastAPI's dependency injection system to manage database connections, external clients, and other resources. This promotes modularity and testability.
*   **Error Handling:** Implement robust error handling using FastAPI's `HTTPException` for expected errors and custom exception handlers for global error management.
*   **Logging:** Configure comprehensive logging for your application. Log requests, responses, errors, and important events to aid in debugging and monitoring.
*   **Configuration Management:** Separate configuration from code. Use environment variables, `.env` files, or dedicated configuration libraries (e.g., Pydantic's `BaseSettings`) to manage settings for different environments (development, staging, production).
*   **Database Migrations:** For applications using databases, use a migration tool (e.g., Alembic for SQLAlchemy) to manage schema changes in a controlled manner.
*   **Security:**
    *   **Input Validation:** Always validate incoming data using Pydantic models.
    .
    *   **Authentication & Authorization:** Implement secure authentication (e.g., OAuth2, JWT) and authorization mechanisms.
    *   **CORS:** Configure Cross-Origin Resource Sharing (CORS) appropriately to prevent unauthorized access from different origins.
    *   **Rate Limiting:** Consider implementing rate limiting to protect against abuse and denial-of-service attacks.
    *   **Sensitive Data:** Never hardcode sensitive information. Use environment variables or a secure secret management system.
*   **Monitoring & Alerting:** Integrate with monitoring tools (e.g., Prometheus, Grafana, Dat