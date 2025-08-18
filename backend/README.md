# Mail Mind AI Backend

FastAPI backend for the Mail Mind AI email assistant.

## Setup

1. **Create virtual environment:**

   ```bash
   python -m venv venv
   source venv/bin/activate  # On macOS/Linux
   # or
   venv\Scripts\activate  # On Windows
   ```

2. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Environment setup:**

   ```bash
   cp .env.template .env
   # Edit .env with your actual values
   ```

4. **Run the development server:**
   ```bash
   python main.py
   # or
   uvicorn main:app --reload --port 8000
   ```

## API Documentation

Once running, visit:

- API docs: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Project Structure

```
backend/
├── main.py              # FastAPI application entry point
├── requirements.txt     # Python dependencies
├── .env.template       # Environment variables template
├── app/
│   ├── __init__.py
│   ├── api/            # API routes
│   │   └── v1/         # API version 1
│   ├── agents/         # AI agents (classifier, summarizer, etc.)
│   ├── models/         # Database models
│   ├── db/            # Database configuration
│   └── core/          # Core utilities and config
```

## Next Steps

1. Set up Google OAuth credentials
2. Configure database
3. Implement authentication endpoints
4. Build AI agents
