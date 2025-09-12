from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session
from app.agents.summarizer import EmailSummarizer
from app.db.database import get_db
from app.models.database import Email, EmailSummary
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/summarize", tags=["summarization"])

# Initialize summarizer instance
summarizer = EmailSummarizer()

class EmailSummarizationRequest(BaseModel):
    subject: str = Field(..., description="Email subject line")
    body: str = Field(..., description="Email body content")
    sender: str = Field(..., description="Sender email address")

class EmailSummarizationResponse(BaseModel):
    bullet_points: List[str] = Field(..., description="Key points in bullet format")
    tldr: str = Field(..., description="One-line summary")
    priority_score: float = Field(..., description="Priority score (0-10)")
    priority_level: str = Field(..., description="Priority level: low, medium, high")
    confidence: float = Field(..., description="Confidence score (0-1)")
    method: str = Field(..., description="Summarization method used")
    privacy_protected: bool = Field(..., description="Privacy protection status")
    word_count: int = Field(..., description="Original content word count")
    reasoning: List[str] = Field(default=[], description="Priority reasoning")
    key_actions: Optional[List[str]] = Field(default=None, description="Key actions required")
    sentiment: Optional[str] = Field(default=None, description="Email sentiment")
    estimated_read_time: Optional[str] = Field(default=None, description="Estimated reading time")
    generated_at: str = Field(..., description="Generation timestamp")

class ThreadSummarizationRequest(BaseModel):
    emails: List[EmailSummarizationRequest] = Field(..., description="List of emails in thread")

class BatchSummarizationRequest(BaseModel):
    email_ids: List[int] = Field(..., description="List of email IDs to summarize")

class StoredEmailSummaryResponse(BaseModel):
    id: int
    email_id: int
    summary: EmailSummarizationResponse
    created_at: str

@router.post("/email", response_model=EmailSummarizationResponse)
async def summarize_email(request: EmailSummarizationRequest):
    """
    Summarize a single email using privacy-first AI summarization
    """
    try:
        # Prepare email data
        email_data = {
            "subject": request.subject,
            "body": request.body,
            "sender": request.sender
        }
        
        # Generate summary
        result = await summarizer.summarize_email(email_data)
        
        return EmailSummarizationResponse(**result)
        
    except Exception as e:
        logger.error(f"Email summarization failed: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Summarization failed: {str(e)}"
        )

@router.post("/thread", response_model=EmailSummarizationResponse)
async def summarize_thread(request: ThreadSummarizationRequest):
    """
    Summarize an entire email thread
    """
    try:
        # Convert request emails to dict format
        emails_data = [
            {
                "subject": email.subject,
                "body": email.body,
                "sender": email.sender
            }
            for email in request.emails
        ]
        
        # Generate thread summary
        result = await summarizer.summarize_thread(emails_data)
        
        return EmailSummarizationResponse(**result)
        
    except Exception as e:
        logger.error(f"Thread summarization failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Thread summarization failed: {str(e)}"
        )

@router.post("/batch")
async def summarize_batch(
    request: BatchSummarizationRequest,
    db: Session = Depends(get_db)
):
    """
    Summarize multiple emails from database by their IDs
    """
    try:
        results = []
        
        for email_id in request.email_ids:
            # Get email from database
            email = db.query(Email).filter(Email.id == email_id).first()
            if not email:
                logger.warning(f"Email with ID {email_id} not found")
                continue
            
            # Check if summary already exists
            existing_summary = db.query(EmailSummary).filter(
                EmailSummary.email_id == email_id
            ).first()
            
            if existing_summary:
                # Return existing summary
                summary_data = {
                    "bullet_points": existing_summary.summary_text.split('\n') if existing_summary.summary_text else [],
                    "tldr": existing_summary.tldr or "",
                    "priority_score": existing_summary.priority_score or 0.0,
                    "priority_level": existing_summary.priority_level or "medium",
                    "confidence": 0.9,  # Stored summaries are considered reliable
                    "method": "database_cached",
                    "privacy_protected": True,
                    "word_count": len((email.body_plain or "").split()),
                    "generated_at": existing_summary.generated_at.isoformat()
                }
                results.append({
                    "email_id": email_id,
                    "summary": summary_data,
                    "cached": True
                })
                continue
            
            # Generate new summary
            email_data = {
                "subject": email.subject or "",
                "body": email.body_plain or email.body_html or "",
                "sender": email.sender_email or ""
            }
            
            summary_result = await summarizer.summarize_email(email_data)
            
            # Store summary in database
            email_summary = EmailSummary(
                email_id=email_id,
                summary_text='\n'.join(summary_result.get('bullet_points', [])),
                tldr=summary_result.get('tldr', ''),
                key_points=str(summary_result.get('key_actions', [])),
                priority_score=summary_result.get('priority_score', 0.0),
                priority_level=summary_result.get('priority_level', 'medium'),
                generated_by_agent="summarizer",
                generated_at=datetime.utcnow()
            )
            
            db.add(email_summary)
            db.commit()
            db.refresh(email_summary)
            
            results.append({
                "email_id": email_id,
                "summary": summary_result,
                "cached": False
            })
        
        return {
            "message": f"Successfully processed {len(results)} emails",
            "results": results,
            "total_requested": len(request.email_ids),
            "total_processed": len(results)
        }
        
    except Exception as e:
        logger.error(f"Batch summarization failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Batch summarization failed: {str(e)}"
        )

@router.get("/email/{email_id}", response_model=StoredEmailSummaryResponse)
async def get_email_summary(email_id: int, db: Session = Depends(get_db)):
    """
    Get stored summary for a specific email
    """
    try:
        # Get email and summary from database
        email = db.query(Email).filter(Email.id == email_id).first()
        if not email:
            raise HTTPException(status_code=404, detail="Email not found")
        
        summary = db.query(EmailSummary).filter(
            EmailSummary.email_id == email_id
        ).first()
        
        if not summary:
            raise HTTPException(status_code=404, detail="Summary not found for this email")
        
        # Format response
        summary_data = {
            "bullet_points": summary.summary_text.split('\n') if summary.summary_text else [],
            "tldr": summary.tldr or "",
            "priority_score": summary.priority_score or 0.0,
            "priority_level": summary.priority_level or "medium",
            "confidence": 0.9,
            "method": "database_stored",
            "privacy_protected": True,
            "word_count": len((email.body_plain or "").split()),
            "reasoning": [],
            "generated_at": summary.generated_at.isoformat()
        }
        
        return StoredEmailSummaryResponse(
            id=summary.id,
            email_id=email_id,
            summary=EmailSummarizationResponse(**summary_data),
            created_at=summary.generated_at.isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get summary failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve summary: {str(e)}"
        )

@router.post("/test")
async def test_summarization():
    """
    Test endpoint with sample email data
    """
    try:
        sample_emails = [
            {
                "subject": "Q3 Financial Report and Budget Planning Meeting",
                "body": """Hi team,

I hope this email finds you well. I wanted to follow up on our previous discussion regarding the Q3 financial report and schedule our upcoming budget planning meeting.

As you know, we need to review the quarterly numbers before the board meeting next Friday. The finance team has compiled the preliminary reports, but we need your input on the departmental budget allocations for Q4.

Key items to discuss:
1. Revenue projections for Q4
2. Cost optimization opportunities
3. Resource allocation for new projects
4. Review of current spending vs budget

Please review the attached documents before our meeting and come prepared with your departmental needs and justifications.

The meeting is scheduled for Thursday, 2 PM in Conference Room A. If you cannot attend, please send a representative who can make decisions on behalf of your department.

Best regards,
Sarah Johnson
Finance Director""",
                "sender": "sarah.johnson@company.com"
            },
            {
                "subject": "Urgent: Server maintenance tonight",
                "body": "Hi, we need to perform emergency server maintenance tonight from 11 PM to 3 AM. Please save your work. Thanks, IT Team",
                "sender": "it-support@company.com"
            }
        ]
        
        results = []
        for email_data in sample_emails:
            result = await summarizer.summarize_email(email_data)
            results.append({
                "original_email": email_data,
                "summary": result
            })
        
        return {
            "message": "Summarization test successful",
            "test_results": results
        }
        
    except Exception as e:
        logger.error(f"Summarization test failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Test failed: {str(e)}"
        )

@router.get("/stats")
async def get_summarization_stats(db: Session = Depends(get_db)):
    """
    Get summarization statistics
    """
    try:
        total_summaries = db.query(EmailSummary).count()
        
        # Priority distribution
        priority_stats = db.query(EmailSummary.priority_level, db.func.count(EmailSummary.id)).group_by(EmailSummary.priority_level).all()
        
        # Recent summaries (last 24 hours)
        from datetime import timedelta
        recent_cutoff = datetime.utcnow() - timedelta(hours=24)
        recent_summaries = db.query(EmailSummary).filter(EmailSummary.generated_at >= recent_cutoff).count()
        
        return {
            "total_summaries": total_summaries,
            "priority_distribution": {level: count for level, count in priority_stats},
            "recent_summaries_24h": recent_summaries,
            "average_priority_score": db.query(db.func.avg(EmailSummary.priority_score)).scalar() or 0.0
        }
        
    except Exception as e:
        logger.error(f"Stats retrieval failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve stats: {str(e)}"
        )
