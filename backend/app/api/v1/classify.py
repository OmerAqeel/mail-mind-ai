from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Any
from ...agents.classifier import EmailClassifier
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/classify", tags=["classification"])

# Initialize classifier instance
classifier = EmailClassifier()

class EmailClassificationRequest(BaseModel):
    subject: str
    body: str
    sender: str

class EmailClassificationResponse(BaseModel):
    category: str
    priority: str
    confidence: float
    reasoning: str
    method: str
    privacy_protected: bool

@router.post("/email", response_model=EmailClassificationResponse)
async def classify_email(request: EmailClassificationRequest):
    """
    Classify an email using privacy-first AI classification
    """
    try:
        # Prepare email data
        email_data = {
            "subject": request.subject,
            "body": request.body,
            "sender": request.sender
        }
        
        # Classify the email
        result = await classifier.classify_email(email_data)
        
        return EmailClassificationResponse(**result)
        
    except Exception as e:
        logger.error(f"Email classification failed: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Classification failed: {str(e)}"
        )

@router.post("/test")
async def test_classification():
    """
    Test endpoint with sample email data
    """
    try:
        sample_email = {
            "subject": "Urgent: Invoice Payment Required",
            "body": "Your invoice #12345 for $150.00 is overdue. Please pay immediately.",
            "sender": "billing@company.com"
        }
        
        result = await classifier.classify_email(sample_email)
        
        return {
            "message": "Classification test successful",
            "sample_email": sample_email,
            "classification_result": result
        }
        
    except Exception as e:
        logger.error(f"Classification test failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Test failed: {str(e)}"
        )

@router.get("/categories")
async def get_categories():
    """
    Get available email categories
    """
    categories = [
        "work",
        "personal", 
        "financial",
        "promotional",
        "support",
        "meetings",
        "notifications",
        "action_required",
        "spam",
        "other"
    ]
    
    priorities = ["high", "medium", "low"]
    
    return {
        "categories": categories,
        "priorities": priorities,
        "description": "Available classification categories and priority levels"
    }
