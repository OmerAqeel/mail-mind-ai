from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import asyncio
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.database import SentEmail, ScheduledEmail, EmailReplyDraft, Email, EmailDeliveryEvent
from app.agents.email_sender import EmailSender, EmailProvider, EmailStatus
from app.auth import verify_token

router = APIRouter()
security = HTTPBearer()

# Initialize email sender
email_sender = EmailSender()

# Request/Response Models
class SendEmailRequest(BaseModel):
    to: EmailStr = Field(..., description="Recipient email address")
    subject: str = Field(..., description="Email subject")
    body: str = Field(..., description="Email body (plain text)")
    html_body: Optional[str] = Field(None, description="Email body (HTML)")
    provider: str = Field("gmail_api", description="Email provider: gmail_api, smtp_gmail, smtp_outlook")
    reply_to: Optional[EmailStr] = Field(None, description="Reply-to email address")
    in_reply_to: Optional[str] = Field(None, description="Message ID this email is replying to")
    include_original: bool = Field(True, description="Include original message in reply")

class ScheduleEmailRequest(BaseModel):
    to: EmailStr = Field(..., description="Recipient email address")
    subject: str = Field(..., description="Email subject")
    body: str = Field(..., description="Email body (plain text)")
    html_body: Optional[str] = Field(None, description="Email body (HTML)")
    scheduled_for: datetime = Field(..., description="When to send the email")
    provider: str = Field("gmail_api", description="Email provider")
    priority: int = Field(5, ge=1, le=10, description="Priority level (1=highest, 10=lowest)")

class SendReplyDraftRequest(BaseModel):
    reply_draft_id: int = Field(..., description="ID of the approved reply draft to send")
    provider: str = Field("gmail_api", description="Email provider")
    send_immediately: bool = Field(True, description="Send immediately or use estimated send time")

class BatchSendRequest(BaseModel):
    email_requests: List[SendEmailRequest] = Field(..., description="List of emails to send")
    batch_delay_seconds: int = Field(5, description="Delay between each email in seconds")

# Response Models
class SendEmailResponse(BaseModel):
    id: int
    status: str
    message_id: Optional[str]
    recipient: str
    subject: str
    provider: str
    sent_at: Optional[datetime]
    error_message: Optional[str]
    warnings: List[str] = []

class ScheduledEmailResponse(BaseModel):
    id: int
    recipient: str
    subject: str
    scheduled_for: datetime
    status: str
    priority: int
    created_at: datetime

class DeliveryStatsResponse(BaseModel):
    total_sent: int
    total_delivered: int
    total_opened: int
    total_bounced: int
    delivery_rate: float
    open_rate: float
    bounce_rate: float

@router.post("/send", response_model=SendEmailResponse)
async def send_email(
    request: SendEmailRequest,
    db: Session = Depends(get_db),
    token: str = Depends(security)
):
    """
    Send an email immediately
    """
    try:
        # Verify authentication
        user_id = verify_token(token.credentials)
        
        # Prepare email data
        email_data = {
            'to': request.to,
            'subject': request.subject,
            'body': request.body,
            'html_body': request.html_body,
            'reply_to': request.reply_to,
            'in_reply_to': request.in_reply_to
        }
        
        # Prepare send config
        send_config = {
            'provider': request.provider,
            'user_id': user_id,
            'credentials': None,  # TODO: Get from user's stored credentials
            'smtp_credentials': None  # TODO: Get from user's SMTP settings
        }
        
        # For demo purposes, use template-based sending without actual credentials
        if not send_config['credentials'] and not send_config['smtp_credentials']:
            # Simulate successful send for testing
            result = {
                'status': 'sent',
                'message_id': f'demo_{datetime.now(timezone.utc).timestamp()}',
                'provider': request.provider,
                'sent_at': datetime.now(timezone.utc).isoformat()
            }
        else:
            # Send the email
            result = await email_sender.send_email(email_data, send_config)
        
        # Save to database
        sent_email = SentEmail(
            user_id=user_id,
            recipient_email=request.to,
            sender_email="user@example.com",  # TODO: Get from user profile
            subject=request.subject,
            body_plain=request.body,
            body_html=request.html_body,
            provider=request.provider,
            message_id=result.get('message_id'),
            status=result['status'],
            sent_at=datetime.now(timezone.utc) if result['status'] == 'sent' else None,
            is_reply=bool(request.in_reply_to),
            body_length=len(request.body),
            error_message=result.get('error'),
            warnings=result.get('warnings', [])
        )
        
        db.add(sent_email)
        db.commit()
        db.refresh(sent_email)
        
        return SendEmailResponse(
            id=sent_email.id,
            status=sent_email.status,
            message_id=sent_email.message_id,
            recipient=sent_email.recipient_email,
            subject=sent_email.subject,
            provider=sent_email.provider,
            sent_at=sent_email.sent_at,
            error_message=sent_email.error_message,
            warnings=sent_email.warnings or []
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Email sending failed: {str(e)}")

@router.post("/send-reply-draft", response_model=SendEmailResponse)
async def send_reply_draft(
    request: SendReplyDraftRequest,
    db: Session = Depends(get_db),
    token: str = Depends(security)
):
    """
    Send an approved reply draft
    """
    try:
        # Verify authentication
        user_id = verify_token(token.credentials)
        
        # Get the reply draft
        reply_draft = db.query(EmailReplyDraft).filter(
            EmailReplyDraft.id == request.reply_draft_id,
            EmailReplyDraft.user_id == user_id
        ).first()
        
        if not reply_draft:
            raise HTTPException(status_code=404, detail="Reply draft not found")
        
        if not reply_draft.user_approved:
            raise HTTPException(status_code=400, detail="Reply draft must be approved before sending")
        
        if reply_draft.status == 'sent':
            raise HTTPException(status_code=400, detail="Reply draft has already been sent")
        
        # Get the original email
        original_email = db.query(Email).filter(Email.id == reply_draft.email_id).first()
        if not original_email:
            raise HTTPException(status_code=404, detail="Original email not found")
        
        # Create reply email data
        reply_email_data = email_sender.create_reply_email(
            original_email={
                'subject': original_email.subject,
                'sender': original_email.sender_email,
                'body': original_email.body_plain,
                'message_id': original_email.gmail_id,
                'received_at': original_email.received_at.isoformat() if original_email.received_at else None
            },
            reply_content=reply_draft.reply_content,
            include_original=True
        )
        
        # Prepare send config
        send_config = {
            'provider': request.provider,
            'user_id': user_id,
            'draft_id': reply_draft.id,
            'credentials': None,  # TODO: Get from user's stored credentials
            'smtp_credentials': None  # TODO: Get from user's SMTP settings
        }
        
        # Check if we should delay sending
        if not request.send_immediately and reply_draft.estimated_send_time:
            if datetime.now(timezone.utc) < reply_draft.estimated_send_time:
                # Schedule for later
                scheduled_email = ScheduledEmail(
                    user_id=user_id,
                    reply_draft_id=reply_draft.id,
                    recipient_email=reply_email_data['to'],
                    sender_email="user@example.com",  # TODO: Get from user
                    subject=reply_email_data['subject'],
                    body_plain=reply_email_data['body'],
                    email_data=reply_email_data,
                    scheduled_for=reply_draft.estimated_send_time,
                    send_config=send_config,
                    status='scheduled'
                )
                
                db.add(scheduled_email)
                reply_draft.status = 'scheduled'
                db.commit()
                
                return SendEmailResponse(
                    id=scheduled_email.id,
                    status='scheduled',
                    message_id=None,
                    recipient=reply_email_data['to'],
                    subject=reply_email_data['subject'],
                    provider=request.provider,
                    sent_at=None,
                    error_message=None,
                    warnings=[f"Email scheduled for {reply_draft.estimated_send_time}"]
                )
        
        # Send immediately
        # For demo purposes, simulate successful send
        result = {
            'status': 'sent',
            'message_id': f'reply_{datetime.now(timezone.utc).timestamp()}',
            'provider': request.provider,
            'sent_at': datetime.now(timezone.utc).isoformat()
        }
        
        # Save to database
        sent_email = SentEmail(
            user_id=user_id,
            original_email_id=reply_draft.email_id,
            reply_draft_id=reply_draft.id,
            recipient_email=reply_email_data['to'],
            sender_email="user@example.com",  # TODO: Get from user
            subject=reply_email_data['subject'],
            body_plain=reply_email_data['body'],
            provider=request.provider,
            message_id=result.get('message_id'),
            status=result['status'],
            sent_at=datetime.now(timezone.utc),
            is_reply=True,
            is_auto_reply=True,
            body_length=len(reply_email_data['body']),
            error_message=result.get('error'),
            warnings=result.get('warnings', [])
        )
        
        db.add(sent_email)
        
        # Update reply draft status
        reply_draft.status = 'sent'
        
        db.commit()
        db.refresh(sent_email)
        
        return SendEmailResponse(
            id=sent_email.id,
            status=sent_email.status,
            message_id=sent_email.message_id,
            recipient=sent_email.recipient_email,
            subject=sent_email.subject,
            provider=sent_email.provider,
            sent_at=sent_email.sent_at,
            error_message=sent_email.error_message,
            warnings=sent_email.warnings or []
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reply sending failed: {str(e)}")

@router.post("/schedule", response_model=ScheduledEmailResponse)
async def schedule_email(
    request: ScheduleEmailRequest,
    db: Session = Depends(get_db),
    token: str = Depends(security)
):
    """
    Schedule an email for future sending
    """
    try:
        # Verify authentication
        user_id = verify_token(token.credentials)
        
        # Validate schedule time
        if request.scheduled_for <= datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="Scheduled time must be in the future")
        
        # Prepare email data
        email_data = {
            'to': request.to,
            'subject': request.subject,
            'body': request.body,
            'html_body': request.html_body
        }
        
        # Prepare send config
        send_config = {
            'provider': request.provider,
            'user_id': user_id,
            'credentials': None,  # TODO: Get from user's stored credentials
            'smtp_credentials': None  # TODO: Get from user's SMTP settings
        }
        
        # Validate email using the sender
        validation = email_sender.validate_email_data(email_data)
        if not validation['is_valid']:
            raise HTTPException(
                status_code=400,
                detail=f"Email validation failed: {', '.join(validation['errors'])}"
            )
        
        # Create scheduled email
        scheduled_email = ScheduledEmail(
            user_id=user_id,
            recipient_email=request.to,
            sender_email="user@example.com",  # TODO: Get from user
            subject=request.subject,
            body_plain=request.body,
            body_html=request.html_body,
            email_data=email_data,
            scheduled_for=request.scheduled_for,
            send_config=send_config,
            priority=request.priority,
            status='scheduled'
        )
        
        db.add(scheduled_email)
        db.commit()
        db.refresh(scheduled_email)
        
        return ScheduledEmailResponse(
            id=scheduled_email.id,
            recipient=scheduled_email.recipient_email,
            subject=scheduled_email.subject,
            scheduled_for=scheduled_email.scheduled_for,
            status=scheduled_email.status,
            priority=scheduled_email.priority,
            created_at=scheduled_email.created_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Email scheduling failed: {str(e)}")

@router.get("/scheduled")
async def get_scheduled_emails(
    limit: int = 20,
    offset: int = 0,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    token: str = Depends(security)
):
    """
    Get user's scheduled emails
    """
    try:
        # Verify authentication
        user_id = verify_token(token.credentials)
        
        # Build query
        query = db.query(ScheduledEmail).filter(ScheduledEmail.user_id == user_id)
        
        if status:
            query = query.filter(ScheduledEmail.status == status)
        
        # Get scheduled emails with pagination
        scheduled_emails = query.order_by(ScheduledEmail.scheduled_for.asc()).offset(offset).limit(limit).all()
        
        # Format response
        emails_list = []
        for email in scheduled_emails:
            emails_list.append({
                "id": email.id,
                "recipient": email.recipient_email,
                "subject": email.subject,
                "scheduled_for": email.scheduled_for,
                "status": email.status,
                "priority": email.priority,
                "attempts": email.attempts,
                "created_at": email.created_at
            })
        
        return {
            "scheduled_emails": emails_list,
            "total": len(emails_list),
            "offset": offset,
            "limit": limit
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve scheduled emails: {str(e)}")

@router.get("/sent")
async def get_sent_emails(
    limit: int = 20,
    offset: int = 0,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    token: str = Depends(security)
):
    """
    Get user's sent emails
    """
    try:
        # Verify authentication
        user_id = verify_token(token.credentials)
        
        # Build query
        query = db.query(SentEmail).filter(SentEmail.user_id == user_id)
        
        if status:
            query = query.filter(SentEmail.status == status)
        
        # Get sent emails with pagination
        sent_emails = query.order_by(SentEmail.sent_at.desc()).offset(offset).limit(limit).all()
        
        # Format response
        emails_list = []
        for email in sent_emails:
            emails_list.append({
                "id": email.id,
                "recipient": email.recipient_email,
                "subject": email.subject,
                "status": email.status,
                "provider": email.provider,
                "sent_at": email.sent_at,
                "is_reply": email.is_reply,
                "is_auto_reply": email.is_auto_reply,
                "message_id": email.message_id
            })
        
        return {
            "sent_emails": emails_list,
            "total": len(emails_list),
            "offset": offset,
            "limit": limit
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve sent emails: {str(e)}")

@router.get("/delivery-stats", response_model=DeliveryStatsResponse)
async def get_delivery_statistics(
    days: int = 30,
    db: Session = Depends(get_db),
    token: str = Depends(security)
):
    """
    Get email delivery statistics for the user
    """
    try:
        # Verify authentication
        user_id = verify_token(token.credentials)
        
        # Calculate date range
        start_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Query statistics
        sent_emails = db.query(SentEmail).filter(
            SentEmail.user_id == user_id,
            SentEmail.sent_at >= start_date
        ).all()
        
        total_sent = len(sent_emails)
        total_delivered = len([e for e in sent_emails if e.status in ['delivered', 'read']])
        total_opened = len([e for e in sent_emails if e.read_at is not None])
        total_bounced = len([e for e in sent_emails if e.status == 'bounced'])
        
        # Calculate rates
        delivery_rate = (total_delivered / total_sent * 100) if total_sent > 0 else 0
        open_rate = (total_opened / total_delivered * 100) if total_delivered > 0 else 0
        bounce_rate = (total_bounced / total_sent * 100) if total_sent > 0 else 0
        
        return DeliveryStatsResponse(
            total_sent=total_sent,
            total_delivered=total_delivered,
            total_opened=total_opened,
            total_bounced=total_bounced,
            delivery_rate=round(delivery_rate, 2),
            open_rate=round(open_rate, 2),
            bounce_rate=round(bounce_rate, 2)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve delivery statistics: {str(e)}")

@router.post("/cancel-scheduled/{email_id}")
async def cancel_scheduled_email(
    email_id: int,
    db: Session = Depends(get_db),
    token: str = Depends(security)
):
    """
    Cancel a scheduled email
    """
    try:
        # Verify authentication
        user_id = verify_token(token.credentials)
        
        # Get the scheduled email
        scheduled_email = db.query(ScheduledEmail).filter(
            ScheduledEmail.id == email_id,
            ScheduledEmail.user_id == user_id
        ).first()
        
        if not scheduled_email:
            raise HTTPException(status_code=404, detail="Scheduled email not found")
        
        if scheduled_email.status not in ['scheduled']:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel email with status: {scheduled_email.status}"
            )
        
        # Cancel the email
        scheduled_email.status = 'cancelled'
        scheduled_email.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        
        return {
            "message": "Scheduled email cancelled successfully",
            "email_id": email_id,
            "status": "cancelled"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel scheduled email: {str(e)}")

# Background task processing
async def process_scheduled_emails_task(db: Session):
    """
    Background task to process scheduled emails
    """
    try:
        # Get emails ready to send
        now = datetime.now(timezone.utc)
        ready_emails = db.query(ScheduledEmail).filter(
            ScheduledEmail.status == 'scheduled',
            ScheduledEmail.scheduled_for <= now,
            ScheduledEmail.attempts < ScheduledEmail.max_attempts
        ).order_by(ScheduledEmail.priority.asc(), ScheduledEmail.scheduled_for.asc()).limit(10).all()
        
        for scheduled_email in ready_emails:
            try:
                # Update status to sending
                scheduled_email.status = 'sending'
                scheduled_email.attempts += 1
                scheduled_email.last_attempt_at = now
                db.commit()
                
                # Attempt to send
                result = await email_sender.send_email(
                    scheduled_email.email_data,
                    scheduled_email.send_config
                )
                
                if result['status'] == 'sent':
                    # Create sent email record
                    sent_email = SentEmail(
                        user_id=scheduled_email.user_id,
                        reply_draft_id=scheduled_email.reply_draft_id,
                        recipient_email=scheduled_email.recipient_email,
                        sender_email=scheduled_email.sender_email,
                        subject=scheduled_email.subject,
                        body_plain=scheduled_email.body_plain,
                        body_html=scheduled_email.body_html,
                        provider=scheduled_email.send_config.get('provider', 'unknown'),
                        message_id=result.get('message_id'),
                        status='sent',
                        sent_at=now,
                        body_length=len(scheduled_email.body_plain or ''),
                        warnings=result.get('warnings', [])
                    )
                    
                    db.add(sent_email)
                    
                    # Update scheduled email
                    scheduled_email.status = 'sent'
                    scheduled_email.sent_email_id = sent_email.id
                    
                else:
                    # Handle failure
                    scheduled_email.error_message = result.get('error', 'Unknown error')
                    if scheduled_email.attempts >= scheduled_email.max_attempts:
                        scheduled_email.status = 'failed'
                    else:
                        scheduled_email.status = 'scheduled'  # Retry later
                
                db.commit()
                
            except Exception as e:
                # Handle individual email failure
                scheduled_email.status = 'failed'
                scheduled_email.error_message = str(e)
                db.commit()
        
    except Exception as e:
        # Log error but don't crash the background task
        print(f"Error processing scheduled emails: {str(e)}")

@router.post("/process-scheduled")
async def trigger_scheduled_processing(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    token: str = Depends(security)
):
    """
    Manually trigger processing of scheduled emails (for testing)
    """
    try:
        # Verify authentication
        verify_token(token.credentials)
        
        # Add background task
        background_tasks.add_task(process_scheduled_emails_task, db)
        
        return {
            "message": "Scheduled email processing triggered",
            "status": "processing"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to trigger processing: {str(e)}")

@router.post("/integration-test")
async def run_integration_test(
    token: str = Depends(security)
):
    """
    Run comprehensive Week 5 integration test
    """
    try:
        # Verify authentication
        verify_token(token.credentials)
        
        # Import and run integration test
        from app.core.integration import run_week5_integration_test
        
        result = await run_week5_integration_test()
        
        return {
            "integration_test_result": result,
            "status": "completed" if result.get("success") else "failed"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Integration test failed: {str(e)}")
