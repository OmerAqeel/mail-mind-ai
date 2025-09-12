"""
Email-related background tasks
"""
from celery import current_task
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
import logging

from app.core.celery_app import celery_app
from app.db.database import get_db
from app.models.database import ScheduledEmail, SentEmail, EmailDeliveryEvent
from app.agents.email_sender import EmailSender

# Setup logging
logger = logging.getLogger(__name__)

# Initialize email sender
email_sender = EmailSender()

@celery_app.task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 60})
def send_scheduled_email(self, scheduled_email_id: int) -> Dict[str, Any]:
    """
    Send a single scheduled email
    
    Args:
        scheduled_email_id: ID of the scheduled email to send
        
    Returns:
        Dict with sending result
    """
    db = next(get_db())
    
    try:
        # Get the scheduled email
        scheduled_email = db.query(ScheduledEmail).filter(
            ScheduledEmail.id == scheduled_email_id,
            ScheduledEmail.status == 'scheduled'
        ).first()
        
        if not scheduled_email:
            logger.warning(f"Scheduled email {scheduled_email_id} not found or not in scheduled status")
            return {
                "success": False,
                "error": "Scheduled email not found or not schedulable",
                "email_id": scheduled_email_id
            }
        
        # Check if it's time to send
        now = datetime.now(timezone.utc)
        if scheduled_email.scheduled_for > now:
            logger.info(f"Scheduled email {scheduled_email_id} not yet due for sending")
            return {
                "success": False,
                "error": "Email not yet due for sending",
                "email_id": scheduled_email_id,
                "scheduled_for": scheduled_email.scheduled_for.isoformat()
            }
        
        # Update status to sending
        scheduled_email.status = 'sending'
        scheduled_email.attempts += 1
        scheduled_email.last_attempt_at = now
        db.commit()
        
        logger.info(f"Attempting to send scheduled email {scheduled_email_id}")
        
        # Attempt to send the email (Celery tasks are synchronous)
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                email_sender.send_email(
                    scheduled_email.email_data,
                    scheduled_email.send_config
                )
            )
        finally:
            loop.close()
        
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
            scheduled_email.sent_at = now
            
            db.commit()
            
            logger.info(f"Successfully sent scheduled email {scheduled_email_id}")
            
            return {
                "success": True,
                "email_id": scheduled_email_id,
                "sent_email_id": sent_email.id,
                "message_id": result.get('message_id'),
                "sent_at": now.isoformat()
            }
            
        else:
            # Handle sending failure
            error_message = result.get('error', 'Unknown sending error')
            scheduled_email.error_message = error_message
            
            if scheduled_email.attempts >= scheduled_email.max_attempts:
                scheduled_email.status = 'failed'
                logger.error(f"Scheduled email {scheduled_email_id} failed after {scheduled_email.attempts} attempts: {error_message}")
            else:
                scheduled_email.status = 'scheduled'  # Retry later
                logger.warning(f"Scheduled email {scheduled_email_id} failed attempt {scheduled_email.attempts}: {error_message}")
            
            db.commit()
            
            return {
                "success": False,
                "email_id": scheduled_email_id,
                "error": error_message,
                "attempts": scheduled_email.attempts,
                "will_retry": scheduled_email.attempts < scheduled_email.max_attempts
            }
            
    except Exception as e:
        # Handle task failure
        logger.error(f"Error processing scheduled email {scheduled_email_id}: {str(e)}")
        
        # Update scheduled email status
        if 'scheduled_email' in locals():
            scheduled_email.status = 'failed'
            scheduled_email.error_message = str(e)
            db.commit()
        
        # Re-raise for Celery retry mechanism
        raise self.retry(exc=e, countdown=60, max_retries=3)
        
    finally:
        db.close()

@celery_app.task(bind=True)
def process_delivery_webhook(self, webhook_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process email delivery webhook events
    
    Args:
        webhook_data: Webhook data from email provider
        
    Returns:
        Dict with processing result
    """
    db = next(get_db())
    
    try:
        message_id = webhook_data.get('message_id')
        event_type = webhook_data.get('event_type')  # delivered, opened, bounced, etc.
        timestamp = webhook_data.get('timestamp')
        provider = webhook_data.get('provider', 'unknown')
        
        if not message_id or not event_type:
            logger.warning("Invalid webhook data: missing message_id or event_type")
            return {"success": False, "error": "Invalid webhook data"}
        
        # Find the sent email
        sent_email = db.query(SentEmail).filter(
            SentEmail.message_id == message_id
        ).first()
        
        if not sent_email:
            logger.warning(f"Sent email not found for message_id: {message_id}")
            return {"success": False, "error": "Sent email not found"}
        
        # Create delivery event
        delivery_event = EmailDeliveryEvent(
            sent_email_id=sent_email.id,
            event_type=event_type,
            event_timestamp=datetime.fromisoformat(timestamp) if timestamp else datetime.now(timezone.utc),
            provider=provider,
            event_data=webhook_data
        )
        
        db.add(delivery_event)
        
        # Update sent email status based on event
        if event_type == 'delivered':
            sent_email.status = 'delivered'
            sent_email.delivered_at = delivery_event.event_timestamp
        elif event_type == 'opened':
            sent_email.read_at = delivery_event.event_timestamp
        elif event_type == 'bounced':
            sent_email.status = 'bounced'
            sent_email.bounce_reason = webhook_data.get('reason', 'Unknown bounce reason')
        elif event_type == 'failed':
            sent_email.status = 'failed'
            sent_email.error_message = webhook_data.get('reason', 'Delivery failed')
        
        db.commit()
        
        logger.info(f"Processed delivery event {event_type} for message {message_id}")
        
        return {
            "success": True,
            "event_type": event_type,
            "message_id": message_id,
            "sent_email_id": sent_email.id
        }
        
    except Exception as e:
        logger.error(f"Error processing delivery webhook: {str(e)}")
        db.rollback()
        return {"success": False, "error": str(e)}
        
    finally:
        db.close()

@celery_app.task(bind=True)
def send_reply_draft_email(self, reply_draft_id: int, send_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send an approved reply draft as a background task
    
    Args:
        reply_draft_id: ID of the reply draft to send
        send_config: Email sending configuration
        
    Returns:
        Dict with sending result
    """
    db = next(get_db())
    
    try:
        from app.models.database import EmailReplyDraft, Email
        
        # Get the reply draft
        reply_draft = db.query(EmailReplyDraft).filter(
            EmailReplyDraft.id == reply_draft_id,
            EmailReplyDraft.user_approved == True,
            EmailReplyDraft.status.in_(['approved', 'scheduled'])
        ).first()
        
        if not reply_draft:
            return {
                "success": False,
                "error": "Reply draft not found or not approved",
                "reply_draft_id": reply_draft_id
            }
        
        # Get the original email
        original_email = db.query(Email).filter(Email.id == reply_draft.email_id).first()
        if not original_email:
            return {
                "success": False,
                "error": "Original email not found",
                "reply_draft_id": reply_draft_id
            }
        
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
        
        # Update status to sending
        reply_draft.status = 'sending'
        db.commit()
        
        # Send the email (Celery tasks are synchronous)
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                email_sender.send_email(reply_email_data, send_config)
            )
        finally:
            loop.close()
        
        if result['status'] == 'sent':
            # Create sent email record
            sent_email = SentEmail(
                user_id=reply_draft.user_id,
                original_email_id=reply_draft.email_id,
                reply_draft_id=reply_draft.id,
                recipient_email=reply_email_data['to'],
                sender_email=send_config.get('sender_email', 'user@example.com'),
                subject=reply_email_data['subject'],
                body_plain=reply_email_data['body'],
                provider=send_config.get('provider', 'unknown'),
                message_id=result.get('message_id'),
                status='sent',
                sent_at=datetime.now(timezone.utc),
                is_reply=True,
                is_auto_reply=True,
                body_length=len(reply_email_data['body']),
                warnings=result.get('warnings', [])
            )
            
            db.add(sent_email)
            
            # Update reply draft
            reply_draft.status = 'sent'
            reply_draft.sent_at = datetime.now(timezone.utc)
            
            db.commit()
            
            logger.info(f"Successfully sent reply draft {reply_draft_id}")
            
            return {
                "success": True,
                "reply_draft_id": reply_draft_id,
                "sent_email_id": sent_email.id,
                "message_id": result.get('message_id')
            }
            
        else:
            # Handle failure
            reply_draft.status = 'failed'
            reply_draft.error_message = result.get('error', 'Unknown error')
            db.commit()
            
            return {
                "success": False,
                "reply_draft_id": reply_draft_id,
                "error": result.get('error', 'Unknown error')
            }
            
    except Exception as e:
        logger.error(f"Error sending reply draft {reply_draft_id}: {str(e)}")
        
        if 'reply_draft' in locals():
            reply_draft.status = 'failed'
            reply_draft.error_message = str(e)
            db.commit()
        
        raise self.retry(exc=e, countdown=60, max_retries=3)
        
    finally:
        db.close()
