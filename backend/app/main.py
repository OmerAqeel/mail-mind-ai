from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from app.api.v1 import api_router
from app.core.config import settings
from app.db.database import engine
from app.models.database import Base

# Create database tables
Base.metadata.create_all(bind=engine)

# Initialize FastAPI app
app = FastAPI(
    title="Mail Mind AI",
    description="AI-powered email management system with intelligent classification, summarization, and auto-reply capabilities",
    version="1.0.0",
    openapi_url="/api/v1/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix="/api/v1")

# Health check endpoint
@app.get("/health")
async def health_check():
    """
    Health check endpoint to verify the API is running
    """
    return {
        "status": "healthy",
        "service": "Mail Mind AI",
        "version": "1.0.0"
    }

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """
    Global exception handler for unhandled errors
    """
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": "An unexpected error occurred",
            "type": "internal_error"
        }
    )

# Startup event
@app.on_event("startup")
async def startup_event():
    """
    Application startup tasks
    """
    print("Mail Mind AI API starting up...")
    print("Database tables created/verified")
    print("API documentation available at /docs")

# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    """
    Application shutdown tasks
    """
    print("Mail Mind AI API shutting down...")

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
