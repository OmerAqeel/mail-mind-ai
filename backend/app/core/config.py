from pydantic_settings import BaseSettings
from typing import Optional
import os

class Settings(BaseSettings):
    """
    Application settings and configuration
    """
    
    # App settings
    APP_NAME: str = "Mail Mind AI"
    DEBUG: bool = False
    VERSION: str = "1.0.0"
    
    # Database settings
    DATABASE_URL: str = "postgresql://username:password@localhost/mailmind_db"
    DATABASE_ECHO: bool = False
    
    # Security settings
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    
    # AI/LLM settings
    OPENAI_API_KEY: Optional[str] = None
    CLAUDE_API_KEY: Optional[str] = None
    DEFAULT_MODEL: str = "gpt-3.5-turbo"
    MAX_TOKENS: int = 1000
    TEMPERATURE: float = 0.7
    
    # Email provider settings
    GMAIL_CLIENT_ID: Optional[str] = None
    GMAIL_CLIENT_SECRET: Optional[str] = None
    GMAIL_REDIRECT_URI: str = "http://localhost:8000/auth/gmail/callback"
    
    # SMTP settings
    SMTP_SERVER: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    
    # Processing settings
    MAX_EMAIL_BODY_LENGTH: int = 50000
    BATCH_PROCESSING_SIZE: int = 10
    CLASSIFICATION_CONFIDENCE_THRESHOLD: float = 0.8
    SUMMARIZATION_MAX_LENGTH: int = 500
    
    # Security settings
    AUTO_REPLY_SAFETY_CHECK: bool = True
    REQUIRE_APPROVAL_FOR_REPLIES: bool = True
    MAX_DAILY_AUTO_REPLIES: int = 50
    SUSPICIOUS_CONTENT_BLOCK: bool = True
    
    # Rate limiting
    REQUESTS_PER_MINUTE: int = 60
    EMAILS_PER_HOUR: int = 100
    
    # File upload settings
    MAX_ATTACHMENT_SIZE: int = 25 * 1024 * 1024  # 25MB
    ALLOWED_ATTACHMENT_TYPES: list = [
        'pdf', 'doc', 'docx', 'txt', 'jpg', 'jpeg', 'png', 'gif'
    ]
    
    class Config:
        env_file = ".env"
        case_sensitive = True

# Create global settings instance
settings = Settings()

# Environment-specific overrides
if os.getenv("ENVIRONMENT") == "production":
    settings.DEBUG = False
    settings.DATABASE_ECHO = False
elif os.getenv("ENVIRONMENT") == "development":
    settings.DEBUG = True
    settings.DATABASE_ECHO = True
