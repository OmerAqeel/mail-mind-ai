from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from root directory
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Import database
from app.db.database import engine
from app.models.database import Base

# Create database tables
Base.metadata.create_all(bind=engine)

# Create FastAPI app instance
app = FastAPI(
    title="Mail Mind AI",
    description="Privacy-conscious AI-powered email assistant",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Next.js dev server
        "http://127.0.0.1:3000",
        "https://mail-mind-ai.vercel.app",  # Production frontend (update with your domain)
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint returning basic API information"""
    return {
        "message": "Mail Mind AI Backend",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs"
    }

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {
        "status": "healthy",
        "service": "Mail Mind AI Backend",
        "timestamp": "2025-08-17"  # You can make this dynamic later
    }

# API version endpoint
@app.get("/api/v1")
async def api_v1():
    """API v1 base endpoint"""
    return {
        "version": "v1",
        "endpoints": {
            "auth": "/api/v1/auth",
            "emails": "/api/v1/emails",
            "classify": "/api/v1/classify",
            "agents": "/api/v1/agents"
        }
    }

# Include routers (will be added as we build features)
from app.api.v1.auth import router as auth_router
from app.api.v1.emails import router as emails_router
from app.api.v1.classify import router as classify_router
# from app.api.v1.agents import router as agents_router

app.include_router(auth_router, prefix="/api/v1/auth", tags=["authentication"])
app.include_router(emails_router, prefix="/api/v1/emails", tags=["emails"])
app.include_router(classify_router, tags=["classification"])
# app.include_router(agents_router, prefix="/api/v1/agents", tags=["agents"])

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler for unhandled errors"""
    return JSONResponse(
        status_code=500,
        content={
            "message": "Internal server error",
            "detail": "An unexpected error occurred"
        }
    )

# Run the app (for development)
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )