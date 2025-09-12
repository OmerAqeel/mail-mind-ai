from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone
import asyncio
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.database import Email, EmailReplyDraft
from app.agents.auto_reply import EmailAutoReply, ReplyType, SafetyLevel
from app.auth import verify_token

router = APIRouter()
security = HTTPBearer()

# Initialize auto-reply agent
auto_reply_agent = EmailAutoReply()

# Request/Response Models
class ReplyGenerationRequest(BaseModel):
    email_id: int = Field(..., description="ID of the email to reply to")
    use_ai_replies: bool = Field(True, description="Whether to use AI-generated replies")
    tone_style: str = Field("professional", description="Tone style: professional, casual, formal")
    custom_instructions: Optional[str] = Field(None, description="Custom instructions for reply generation")

class ToneProfileRequest(BaseModel):
    tone_style: str = Field("professional", description="Default tone style")
    formality_level: str = Field("medium", description="Formality level: low, medium, high")
    typical_length: str = Field("concise", description="Typical reply length: brief, concise, detailed")
    signature_style: str = Field("formal", description="Signature style: formal, casual, minimal")

class AwayMessageRequest(BaseModel):
    start_date: str = Field(..., description="Start date for away message (YYYY-MM-DD)")
    end_date: str = Field(..., description="End date for away message (YYYY-MM-DD)")
    contact_info: Optional[str] = Field(None, description="Alternative contact information")
    tone_style: str = Field("professional", description="Tone style for away message")

class ReplyApprovalRequest(BaseModel):
    reply_draft_id: int = Field(..., description="ID of the reply draft to approve")
    approved: bool = Field(..., description="Whether the reply is approved")
    modifications: Optional[str] = Field(None, description="User modifications to the reply")
    schedule_send: Optional[datetime] = Field(None, description="Schedule send time (optional)")

class BatchReplyRequest(BaseModel):
    email_ids: List[int] = Field(..., description="List of email IDs to generate replies for")
    use_ai_replies: bool = Field(True, description="Whether to use AI-generated replies")
    tone_style: str = Field("professional", description="Default tone style for all replies")

# Response Models
class ReplyDraftResponse(BaseModel):
    id: int
    email_id: int
    reply_content: str
    reply_type: str
    generation_method: str
    safety_level: str
    requires_approval: bool
    status: str
    generated_at: datetime
    safety_risks: List[str]
    context_summary: Dict[str, Any]

class AwayMessageResponse(BaseModel):
    id: int
    away_message: str
    active_from: str
    active_until: str
    tone_style: str
    is_active: bool
    created_at: datetime

class ReplyStatsResponse(BaseModel):
    total_drafts_generated: int
    total_sent: int
    safety_blocks: int
    ai_generated: int
    template_based: int
    approval_rate: float
    avg_generation_time: float

@router.post("/generate-reply", response_model=ReplyDraftResponse)
async def generate_reply_draft(
    request: ReplyGenerationRequest,
    db: Session = Depends(get_db),
    token: str = Depends(security)
):
    """
    Generate an AI-powered reply draft for a specific email with safety checks
    """
    try:
        # Verify authentication
        user_id = verify_token(token.credentials)
        
        # Get the email
        email = db.query(Email).filter(Email.id == request.email_id, Email.user_id == user_id).first()
        if not email:
            raise HTTPException(status_code=404, detail="Email not found")
        
        # Check if reply already exists and is recent
        existing_draft = db.query(EmailReplyDraft).filter(
            EmailReplyDraft.email_id == request.email_id,
            EmailReplyDraft.created_at > datetime.now(timezone.utc) - timedelta(hours=1)
        ).first()
        
        if existing_draft and not existing_draft.is_superseded:
            return ReplyDraftResponse(
                id=existing_draft.id,
                email_id=existing_draft.email_id,
                reply_content=existing_draft.reply_content,
                reply_type=existing_draft.reply_type,
                generation_method=existing_draft.generation_method,
                safety_level=existing_draft.safety_level,
                requires_approval=existing_draft.requires_approval,
                status=existing_draft.status,
                generated_at=existing_draft.created_at,
                safety_risks=existing_draft.safety_risks if isinstance(existing_draft.safety_risks, list) else [],
                context_summary=existing_draft.context_analysis if isinstance(existing_draft.context_analysis, dict) else {}
            )
        
        # Prepare email data
        email_data = {
            'id': email.id,
            'subject': email.subject or '',
            'body': email.body_plain or email.body_html or '',
            'sender': email.sender_email or '',
            'recipient': email.recipient_email or '',
            'received_at': email.received_at.isoformat() if email.received_at else None
        }
        
        # Prepare user preferences
        user_preferences = {
            'use_ai_replies': request.use_ai_replies,
            'tone_profile': {
                'tone_style': request.tone_style,
                'formality_level': 'medium',
                'typical_length': 'concise'
            }
        }
        
        # Generate reply draft
        reply_result = await auto_reply_agent.generate_reply_draft(email_data, user_preferences)
        
        if 'error' in reply_result:
            raise HTTPException(status_code=500, detail=reply_result['error'])
        
        # Mark existing drafts as superseded
        if existing_draft:
            existing_draft.is_superseded = True
            db.commit()
        
        # Save reply draft to database
        reply_draft = EmailReplyDraft(
            email_id=email.id,
            user_id=user_id,
            reply_content=reply_result['reply_content'],
            reply_type=reply_result['reply_type'],
            generation_method=reply_result['generation_method'],
            safety_level=reply_result['safety_assessment']['safety_level'],
            safety_score=reply_result['safety_assessment']['safety_score'],
            safety_risks=reply_result['safety_assessment']['risks'],
            requires_approval=reply_result['requires_approval'],
            status=reply_result['status'],
            context_analysis=reply_result['context_analysis'],
            tone_profile=reply_result['tone_profile'],
            estimated_send_time=datetime.fromisoformat(reply_result['estimated_send_time']) if reply_result.get('estimated_send_time') else None,
            custom_instructions=request.custom_instructions
        )
        
        db.add(reply_draft)
        db.commit()
        db.refresh(reply_draft)
        
        return ReplyDraftResponse(
            id=reply_draft.id,
            email_id=reply_draft.email_id,
            reply_content=reply_draft.reply_content,
            reply_type=reply_draft.reply_type,
            generation_method=reply_draft.generation_method,
            safety_level=reply_draft.safety_level,
            requires_approval=reply_draft.requires_approval,
            status=reply_draft.status,
            generated_at=reply_draft.created_at,
            safety_risks=reply_draft.safety_risks if isinstance(reply_draft.safety_risks, list) else [],
            context_summary=reply_draft.context_analysis if isinstance(reply_draft.context_analysis, dict) else {}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reply generation failed: {str(e)}")

@router.post("/approve-reply")
async def approve_reply_draft(
    request: ReplyApprovalRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    token: str = Depends(security)
):
    """
    Approve or reject a reply draft with optional modifications
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
        
        if reply_draft.status in ['sent', 'blocked']:
            raise HTTPException(status_code=400, detail=f"Cannot modify reply with status: {reply_draft.status}")
        
        # Update reply draft
        reply_draft.user_approved = request.approved
        reply_draft.approved_at = datetime.now(timezone.utc) if request.approved else None
        
        if request.modifications:
            reply_draft.reply_content = request.modifications
            reply_draft.modified_by_user = True
        
        if request.schedule_send:
            reply_draft.scheduled_send_time = request.schedule_send
        
        if request.approved:
            reply_draft.status = 'approved'
            
            # Final safety validation
            validation_result = auto_reply_agent.validate_reply_before_send({
                'reply_content': reply_draft.reply_content,
                'safety_assessment': {'blocked': reply_draft.safety_level == 'blocked'},
                'requires_approval': reply_draft.requires_approval,
                'user_approved': request.approved,
                'estimated_send_time': reply_draft.estimated_send_time.isoformat() if reply_draft.estimated_send_time else None
            })
            
            if not validation_result['is_valid']:
                reply_draft.status = 'validation_failed'
                reply_draft.validation_errors = validation_result['errors']
                db.commit()
                raise HTTPException(status_code=400, detail=f"Validation failed: {validation_result['errors']}")
            
            # Schedule for sending (background task would handle actual sending)
            if request.schedule_send:
                reply_draft.status = 'scheduled'
                background_tasks.add_task(schedule_reply_send, reply_draft.id)
            else:
                reply_draft.status = 'ready_to_send'
                
        else:
            reply_draft.status = 'rejected'
        
        db.commit()
        
        return {
            "message": f"Reply draft {'approved' if request.approved else 'rejected'} successfully",
            "status": reply_draft.status,
            "reply_id": reply_draft.id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reply approval failed: {str(e)}")

@router.post("/create-away-message", response_model=AwayMessageResponse)
async def create_away_message(
    request: AwayMessageRequest,
    db: Session = Depends(get_db),
    token: str = Depends(security)
):
    """
    Create an automated away message for a specified date range
    """
    try:
        # Verify authentication
        user_id = verify_token(token.credentials)
        
        # Generate away message
        away_result = await auto_reply_agent.create_away_message(
            start_date=request.start_date,
            end_date=request.end_date,
            contact_info=request.contact_info,
            tone_style=request.tone_style
        )
        
        if 'error' in away_result:
            raise HTTPException(status_code=500, detail=away_result['error'])
        
        # Save away message to database (would need AwayMessage model)
        # For now, return the generated message
        return AwayMessageResponse(
            id=1,  # Placeholder
            away_message=away_result['away_message'],
            active_from=away_result['active_from'],
            active_until=away_result['active_until'],
            tone_style=away_result['tone_style'],
            is_active=False,  # Would be activated separately
            created_at=datetime.now()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Away message creation failed: {str(e)}")

@router.post("/batch-generate-replies")
async def batch_generate_replies(
    request: BatchReplyRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    token: str = Depends(security)
):
    """
    Generate reply drafts for multiple emails in batch
    """
    try:
        # Verify authentication
        user_id = verify_token(token.credentials)
        
        # Validate email IDs exist
        emails = db.query(Email).filter(
            Email.id.in_(request.email_ids),
            Email.user_id == user_id
        ).all()
        
        if len(emails) != len(request.email_ids):
            raise HTTPException(status_code=404, detail="Some emails not found")
        
        # Limit batch size for safety
        if len(request.email_ids) > 10:
            raise HTTPException(status_code=400, detail="Batch size limited to 10 emails")
        
        # Start batch processing in background
        task_id = f"batch_{user_id}_{datetime.now().timestamp()}"
        background_tasks.add_task(
            process_batch_replies,
            request.email_ids,
            user_id,
            request.use_ai_replies,
            request.tone_style,
            task_id
        )
        
        return {
            "message": f"Batch reply generation started for {len(request.email_ids)} emails",
            "task_id": task_id,
            "email_count": len(request.email_ids),
            "estimated_completion": (datetime.now() + timedelta(minutes=len(request.email_ids))).isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch processing failed: {str(e)}")

@router.get("/reply-drafts")
async def get_user_reply_drafts(
    limit: int = 20,
    offset: int = 0,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    token: str = Depends(security)
):
    """
    Get user's reply drafts with optional filtering
    """
    try:
        # Verify authentication
        user_id = verify_token(token.credentials)
        
        # Build query
        query = db.query(EmailReplyDraft).filter(EmailReplyDraft.user_id == user_id)
        
        if status:
            query = query.filter(EmailReplyDraft.status == status)
        
        # Get drafts with pagination
        drafts = query.order_by(EmailReplyDraft.created_at.desc()).offset(offset).limit(limit).all()
        
        # Format response
        draft_list = []
        for draft in drafts:
            draft_list.append({
                "id": draft.id,
                "email_id": draft.email_id,
                "reply_content": draft.reply_content[:200] + "..." if len(draft.reply_content) > 200 else draft.reply_content,
                "reply_type": draft.reply_type,
                "safety_level": draft.safety_level,
                "status": draft.status,
                "requires_approval": draft.requires_approval,
                "created_at": draft.created_at,
                "approved_at": draft.approved_at
            })
        
        return {
            "drafts": draft_list,
            "total": len(draft_list),
            "offset": offset,
            "limit": limit
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve drafts: {str(e)}")

@router.get("/reply-stats", response_model=ReplyStatsResponse)
async def get_reply_statistics(
    days: int = 30,
    db: Session = Depends(get_db),
    token: str = Depends(security)
):
    """
    Get auto-reply statistics for the user
    """
    try:
        # Verify authentication
        user_id = verify_token(token.credentials)
        
        # Calculate date range
        start_date = datetime.now() - timedelta(days=days)
        
        # Query statistics
        drafts = db.query(EmailReplyDraft).filter(
            EmailReplyDraft.user_id == user_id,
            EmailReplyDraft.created_at >= start_date
        ).all()
        
        total_drafts = len(drafts)
        total_sent = len([d for d in drafts if d.status == 'sent'])
        safety_blocks = len([d for d in drafts if d.safety_level == 'blocked'])
        ai_generated = len([d for d in drafts if d.generation_method == 'ai_generated'])
        template_based = len([d for d in drafts if d.generation_method == 'template_based'])
        approved_count = len([d for d in drafts if d.user_approved])
        
        approval_rate = (approved_count / total_drafts * 100) if total_drafts > 0 else 0
        
        return ReplyStatsResponse(
            total_drafts_generated=total_drafts,
            total_sent=total_sent,
            safety_blocks=safety_blocks,
            ai_generated=ai_generated,
            template_based=template_based,
            approval_rate=round(approval_rate, 2),
            avg_generation_time=2.5  # Placeholder
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve statistics: {str(e)}")

# Background task functions
async def process_batch_replies(email_ids: List[int], user_id: int, use_ai: bool, tone_style: str, task_id: str):
    """
    Background task to process batch reply generation
    """
    # This would be implemented with a proper task queue in production
    # For now, it's a placeholder for the background processing logic
    pass

async def schedule_reply_send(reply_draft_id: int):
    """
    Background task to handle scheduled reply sending
    """
    # This would implement the actual email sending logic
    # Including final safety checks and SMTP integration
    pass

# Template management endpoints
@router.get("/reply-templates")
async def get_reply_templates(
    reply_type: Optional[str] = None,
    token: str = Depends(security)
):
    """
    Get available reply templates
    """
    try:
        # Verify authentication
        verify_token(token.credentials)
        
        templates = auto_reply_agent.reply_templates
        
        if reply_type:
            if reply_type in [rt.value for rt in ReplyType]:
                return {reply_type: templates.get(ReplyType(reply_type), {})}
            else:
                raise HTTPException(status_code=400, detail="Invalid reply type")
        
        # Convert enum keys to strings for JSON serialization
        formatted_templates = {}
        for rt, template_dict in templates.items():
            formatted_templates[rt.value] = template_dict
        
        return {"templates": formatted_templates}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve templates: {str(e)}")
