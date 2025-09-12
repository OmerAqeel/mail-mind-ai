"""
Webhook handlers for email delivery tracking
"""
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta
import hmac
import hashlib
import json
import logging

from app.tasks.email_tasks import process_delivery_webhook
from app.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

# Webhook payload models
class DeliveryWebhookPayload(BaseModel):
    message_id: str = Field(..., description="Unique message identifier")
    event_type: str = Field(..., description="Event type: delivered, opened, bounced, failed, etc.")
    timestamp: str = Field(..., description="Event timestamp in ISO format")
    recipient: str = Field(..., description="Recipient email address")
    provider: str = Field(..., description="Email provider: gmail_api, smtp_gmail, etc.")
    reason: Optional[str] = Field(None, description="Reason for bounce/failure")
    user_agent: Optional[str] = Field(None, description="User agent for open events")
    ip_address: Optional[str] = Field(None, description="IP address for open events")
    additional_data: Optional[Dict[str, Any]] = Field(None, description="Additional provider-specific data")

class BatchWebhookPayload(BaseModel):
    events: List[DeliveryWebhookPayload] = Field(..., description="List of delivery events")
    batch_id: str = Field(..., description="Batch identifier")

def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verify webhook signature for security
    
    Args:
        payload: Raw webhook payload
        signature: Signature from webhook headers
        secret: Webhook secret key
        
    Returns:
        True if signature is valid
    """
    if not secret:
        logger.warning("No webhook secret configured - skipping signature verification")
        return True
    
    try:
        # Create expected signature
        expected_signature = hmac.new(
            secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        # Compare signatures (constant time comparison)
        return hmac.compare_digest(f"sha256={expected_signature}", signature)
        
    except Exception as e:
        logger.error(f"Error verifying webhook signature: {str(e)}")
        return False

@router.post("/delivery/gmail")
async def handle_gmail_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: DeliveryWebhookPayload
):
    """
    Handle Gmail delivery webhooks
    """
    try:
        # Get raw payload for signature verification
        raw_payload = await request.body()
        signature = request.headers.get("X-Gmail-Signature", "")
        
        # Verify signature if configured
        webhook_secret = getattr(settings, "GMAIL_WEBHOOK_SECRET", None)
        if webhook_secret and not verify_webhook_signature(raw_payload, signature, webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        
        # Add provider information
        webhook_data = payload.dict()
        webhook_data["provider"] = "gmail_api"
        webhook_data["raw_headers"] = dict(request.headers)
        
        # Queue for background processing
        background_tasks.add_task(
            process_delivery_webhook.delay,
            webhook_data
        )
        
        logger.info(f"Queued Gmail webhook processing for message {payload.message_id}, event: {payload.event_type}")
        
        return JSONResponse(
            status_code=200,
            content={"status": "accepted", "message_id": payload.message_id}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error handling Gmail webhook: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/delivery/smtp")
async def handle_smtp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: DeliveryWebhookPayload
):
    """
    Handle SMTP provider webhooks (SendGrid, Mailgun, etc.)
    """
    try:
        # Get raw payload for signature verification
        raw_payload = await request.body()
        signature = request.headers.get("X-SMTP-Signature", "")
        
        # Verify signature if configured
        webhook_secret = getattr(settings, "SMTP_WEBHOOK_SECRET", None)
        if webhook_secret and not verify_webhook_signature(raw_payload, signature, webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        
        # Add provider information
        webhook_data = payload.dict()
        webhook_data["provider"] = "smtp"
        webhook_data["raw_headers"] = dict(request.headers)
        
        # Queue for background processing
        background_tasks.add_task(
            process_delivery_webhook.delay,
            webhook_data
        )
        
        logger.info(f"Queued SMTP webhook processing for message {payload.message_id}, event: {payload.event_type}")
        
        return JSONResponse(
            status_code=200,
            content={"status": "accepted", "message_id": payload.message_id}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error handling SMTP webhook: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/delivery/batch")
async def handle_batch_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: BatchWebhookPayload
):
    """
    Handle batch delivery webhooks for multiple events
    """
    try:
        # Get raw payload for signature verification
        raw_payload = await request.body()
        signature = request.headers.get("X-Batch-Signature", "")
        
        # Verify signature if configured
        webhook_secret = getattr(settings, "BATCH_WEBHOOK_SECRET", None)
        if webhook_secret and not verify_webhook_signature(raw_payload, signature, webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        
        # Process each event in the batch
        processed_count = 0
        for event in payload.events:
            try:
                webhook_data = event.dict()
                webhook_data["batch_id"] = payload.batch_id
                webhook_data["raw_headers"] = dict(request.headers)
                
                # Queue for background processing
                background_tasks.add_task(
                    process_delivery_webhook.delay,
                    webhook_data
                )
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Error processing batch event {event.message_id}: {str(e)}")
        
        logger.info(f"Queued {processed_count}/{len(payload.events)} batch webhook events for processing")
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "accepted",
                "batch_id": payload.batch_id,
                "processed_count": processed_count,
                "total_events": len(payload.events)
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error handling batch webhook: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/delivery/sendgrid")
async def handle_sendgrid_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Handle SendGrid-specific webhook format
    """
    try:
        # SendGrid sends events as JSON array
        raw_payload = await request.body()
        signature = request.headers.get("X-Twilio-Email-Event-Webhook-Signature", "")
        
        # Verify signature if configured
        webhook_secret = getattr(settings, "SENDGRID_WEBHOOK_SECRET", None)
        if webhook_secret and not verify_webhook_signature(raw_payload, signature, webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        
        # Parse SendGrid event format
        events = json.loads(raw_payload)
        processed_count = 0
        
        for event in events:
            try:
                # Convert SendGrid format to our standard format
                webhook_data = {
                    "message_id": event.get("sg_message_id") or event.get("smtp-id"),
                    "event_type": event.get("event"),
                    "timestamp": datetime.fromtimestamp(event.get("timestamp", 0), tz=timezone.utc).isoformat(),
                    "recipient": event.get("email"),
                    "provider": "sendgrid",
                    "reason": event.get("reason"),
                    "user_agent": event.get("useragent"),
                    "ip_address": event.get("ip"),
                    "additional_data": event,
                    "raw_headers": dict(request.headers)
                }
                
                # Queue for background processing
                background_tasks.add_task(
                    process_delivery_webhook.delay,
                    webhook_data
                )
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Error processing SendGrid event: {str(e)}")
        
        logger.info(f"Queued {processed_count}/{len(events)} SendGrid webhook events for processing")
        
        return JSONResponse(
            status_code=200,
            content={"status": "accepted", "processed_count": processed_count}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error handling SendGrid webhook: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/delivery/mailgun")
async def handle_mailgun_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Handle Mailgun-specific webhook format
    """
    try:
        # Mailgun sends form data
        form_data = await request.form()
        signature = request.headers.get("X-Mailgun-Signature-2", "")
        
        # Verify signature if configured
        webhook_secret = getattr(settings, "MAILGUN_WEBHOOK_SECRET", None)
        if webhook_secret:
            # Mailgun signature verification logic would go here
            pass
        
        # Parse Mailgun event format
        event_data = dict(form_data)
        
        # Convert Mailgun format to our standard format
        webhook_data = {
            "message_id": event_data.get("Message-Id", "").strip("<>"),
            "event_type": event_data.get("event"),
            "timestamp": event_data.get("timestamp"),
            "recipient": event_data.get("recipient"),
            "provider": "mailgun",
            "reason": event_data.get("reason") or event_data.get("description"),
            "additional_data": event_data,
            "raw_headers": dict(request.headers)
        }
        
        # Queue for background processing
        background_tasks.add_task(
            process_delivery_webhook.delay,
            webhook_data
        )
        
        logger.info(f"Queued Mailgun webhook processing for message {webhook_data['message_id']}, event: {webhook_data['event_type']}")
        
        return JSONResponse(
            status_code=200,
            content={"status": "accepted", "message_id": webhook_data["message_id"]}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error handling Mailgun webhook: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/delivery/test")
async def test_webhook_processing():
    """
    Test endpoint to verify webhook processing is working
    """
    try:
        # Create a test webhook payload
        test_payload = {
            "message_id": f"test_{datetime.now(timezone.utc).timestamp()}",
            "event_type": "delivered",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "recipient": "test@example.com",
            "provider": "test",
            "additional_data": {"test": True}
        }
        
        # Queue for background processing
        task = process_delivery_webhook.delay(test_payload)
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "test_webhook_queued",
                "task_id": task.id,
                "payload": test_payload
            }
        )
        
    except Exception as e:
        logger.error(f"Error in test webhook: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/delivery/stats")
async def get_webhook_stats():
    """
    Get statistics about webhook processing
    """
    try:
        from app.db.database import get_db
        from app.models.database import EmailDeliveryEvent, SentEmail
        from sqlalchemy import func
        
        db = next(get_db())
        
        # Get recent webhook statistics
        recent_events = db.query(
            EmailDeliveryEvent.event_type,
            func.count(EmailDeliveryEvent.id).label('count')
        ).filter(
            EmailDeliveryEvent.event_timestamp >= datetime.now(timezone.utc) - timedelta(hours=24)
        ).group_by(EmailDeliveryEvent.event_type).all()
        
        # Get provider statistics
        provider_stats = db.query(
            EmailDeliveryEvent.provider,
            func.count(EmailDeliveryEvent.id).label('count')
        ).filter(
            EmailDeliveryEvent.event_timestamp >= datetime.now(timezone.utc) - timedelta(hours=24)
        ).group_by(EmailDeliveryEvent.provider).all()
        
        # Format response
        event_stats = {event.event_type: event.count for event in recent_events}
        provider_counts = {provider.provider: provider.count for provider in provider_stats}
        
        return JSONResponse(
            status_code=200,
            content={
                "period": "last_24_hours",
                "event_types": event_stats,
                "providers": provider_counts,
                "total_events": sum(event_stats.values()),
                "generated_at": datetime.now(timezone.utc).isoformat()
            }
        )
        
    except Exception as e:
        logger.error(f"Error getting webhook stats: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
