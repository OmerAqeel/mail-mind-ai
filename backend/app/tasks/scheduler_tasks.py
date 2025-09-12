"""
Scheduler and maintenance background tasks
"""
from celery import current_task
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import Dict, Any, List
import logging

from app.core.celery_app import celery_app
from app.db.database import get_db
from app.models.database import ScheduledEmail, SentEmail, EmailDeliveryEvent
from app.tasks.email_tasks import send_scheduled_email

# Setup logging
logger = logging.getLogger(__name__)

@celery_app.task(bind=True)
def process_scheduled_emails(self) -> Dict[str, Any]:
    """
    Periodic task to process scheduled emails that are due for sending
    
    Returns:
        Dict with processing results
    """
    db = next(get_db())
    processed_count = 0
    error_count = 0
    
    try:
        # Get emails ready to send
        now = datetime.now(timezone.utc)
        
        ready_emails = db.query(ScheduledEmail).filter(
            and_(
                ScheduledEmail.status == 'scheduled',
                ScheduledEmail.scheduled_for <= now,
                ScheduledEmail.attempts < ScheduledEmail.max_attempts
            )
        ).order_by(
            ScheduledEmail.priority.asc(),
            ScheduledEmail.scheduled_for.asc()
        ).limit(50).all()  # Process up to 50 emails per batch
        
        logger.info(f"Found {len(ready_emails)} emails ready for sending")
        
        for scheduled_email in ready_emails:
            try:
                # Queue individual email for sending
                task = send_scheduled_email.delay(scheduled_email.id)
                logger.info(f"Queued scheduled email {scheduled_email.id} for sending (task: {task.id})")
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Error queuing scheduled email {scheduled_email.id}: {str(e)}")
                error_count += 1
                
                # Mark as failed if we can't even queue it
                scheduled_email.status = 'failed'
                scheduled_email.error_message = f"Failed to queue: {str(e)}"
                scheduled_email.attempts += 1
                scheduled_email.last_attempt_at = now
        
        db.commit()
        
        return {
            "success": True,
            "processed_count": processed_count,
            "error_count": error_count,
            "total_found": len(ready_emails)
        }
        
    except Exception as e:
        logger.error(f"Error in process_scheduled_emails: {str(e)}")
        db.rollback()
        return {
            "success": False,
            "error": str(e),
            "processed_count": processed_count,
            "error_count": error_count
        }
        
    finally:
        db.close()

@celery_app.task(bind=True)
def cleanup_old_tasks(self) -> Dict[str, Any]:
    """
    Cleanup old completed/failed tasks and delivery events
    
    Returns:
        Dict with cleanup results
    """
    db = next(get_db())
    
    try:
        # Define cleanup thresholds
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)  # Keep 30 days
        
        # Cleanup old scheduled emails (completed/failed)
        old_scheduled = db.query(ScheduledEmail).filter(
            and_(
                ScheduledEmail.status.in_(['sent', 'failed', 'cancelled']),
                ScheduledEmail.created_at < cutoff_date
            )
        ).count()
        
        if old_scheduled > 0:
            db.query(ScheduledEmail).filter(
                and_(
                    ScheduledEmail.status.in_(['sent', 'failed', 'cancelled']),
                    ScheduledEmail.created_at < cutoff_date
                )
            ).delete()
            logger.info(f"Cleaned up {old_scheduled} old scheduled emails")
        
        # Cleanup old delivery events
        old_events = db.query(EmailDeliveryEvent).filter(
            EmailDeliveryEvent.event_timestamp < cutoff_date
        ).count()
        
        if old_events > 0:
            db.query(EmailDeliveryEvent).filter(
                EmailDeliveryEvent.event_timestamp < cutoff_date
            ).delete()
            logger.info(f"Cleaned up {old_events} old delivery events")
        
        # Update sent emails with very old data (compress details)
        very_old_date = datetime.now(timezone.utc) - timedelta(days=90)
        old_sent_emails = db.query(SentEmail).filter(
            and_(
                SentEmail.sent_at < very_old_date,
                SentEmail.body_plain.isnot(None)
            )
        ).all()
        
        archived_count = 0
        for sent_email in old_sent_emails:
            # Keep metadata but remove large text fields for very old emails
            sent_email.body_plain = f"[Archived - {len(sent_email.body_plain or '')} characters]"
            sent_email.body_html = None
            archived_count += 1
        
        if archived_count > 0:
            logger.info(f"Archived {archived_count} very old sent emails")
        
        db.commit()
        
        return {
            "success": True,
            "old_scheduled_cleaned": old_scheduled,
            "old_events_cleaned": old_events,
            "old_emails_archived": archived_count
        }
        
    except Exception as e:
        logger.error(f"Error in cleanup_old_tasks: {str(e)}")
        db.rollback()
        return {"success": False, "error": str(e)}
        
    finally:
        db.close()

@celery_app.task(bind=True)
def update_delivery_statistics(self) -> Dict[str, Any]:
    """
    Update delivery statistics and handle stale emails
    
    Returns:
        Dict with update results
    """
    db = next(get_db())
    
    try:
        # Find emails that were sent but haven't received delivery confirmation
        stale_threshold = datetime.now(timezone.utc) - timedelta(hours=6)  # 6 hours
        
        stale_emails = db.query(SentEmail).filter(
            and_(
                SentEmail.status == 'sent',
                SentEmail.sent_at < stale_threshold,
                SentEmail.delivered_at.is_(None)
            )
        ).all()
        
        updated_count = 0
        for sent_email in stale_emails:
            # Mark as delivered if no bounce/failure after 6 hours
            sent_email.status = 'delivered'
            sent_email.delivered_at = sent_email.sent_at + timedelta(minutes=30)  # Estimate delivery
            updated_count += 1
        
        if updated_count > 0:
            logger.info(f"Updated {updated_count} stale emails to delivered status")
        
        # Find and handle failed deliveries
        failed_threshold = datetime.now(timezone.utc) - timedelta(hours=24)  # 24 hours
        
        failed_emails = db.query(SentEmail).filter(
            and_(
                SentEmail.status == 'sent',
                SentEmail.sent_at < failed_threshold,
                SentEmail.delivered_at.is_(None),
                SentEmail.bounce_reason.is_(None)
            )
        ).all()
        
        failed_count = 0
        for sent_email in failed_emails:
            # Mark as failed if no delivery after 24 hours
            sent_email.status = 'failed'
            sent_email.error_message = 'No delivery confirmation received within 24 hours'
            failed_count += 1
        
        if failed_count > 0:
            logger.info(f"Marked {failed_count} emails as failed due to no delivery confirmation")
        
        # Handle stuck scheduled emails
        stuck_threshold = datetime.now(timezone.utc) - timedelta(hours=1)
        
        stuck_emails = db.query(ScheduledEmail).filter(
            and_(
                ScheduledEmail.status == 'sending',
                ScheduledEmail.last_attempt_at < stuck_threshold
            )
        ).all()
        
        reset_count = 0
        for scheduled_email in stuck_emails:
            if scheduled_email.attempts < scheduled_email.max_attempts:
                # Reset to scheduled for retry
                scheduled_email.status = 'scheduled'
                reset_count += 1
            else:
                # Mark as failed
                scheduled_email.status = 'failed'
                scheduled_email.error_message = 'Stuck in sending status - exceeded retry attempts'
        
        if reset_count > 0:
            logger.info(f"Reset {reset_count} stuck scheduled emails for retry")
        
        db.commit()
        
        return {
            "success": True,
            "stale_emails_updated": updated_count,
            "failed_emails_marked": failed_count,
            "stuck_emails_reset": reset_count
        }
        
    except Exception as e:
        logger.error(f"Error in update_delivery_statistics: {str(e)}")
        db.rollback()
        return {"success": False, "error": str(e)}
        
    finally:
        db.close()

@celery_app.task(bind=True)
def retry_failed_emails(self, max_retries: int = 50) -> Dict[str, Any]:
    """
    Retry failed scheduled emails that are eligible for retry
    
    Args:
        max_retries: Maximum number of emails to retry in this batch
        
    Returns:
        Dict with retry results
    """
    db = next(get_db())
    
    try:
        # Find failed emails eligible for retry
        retry_threshold = datetime.now(timezone.utc) - timedelta(hours=2)  # Wait 2 hours before retry
        
        retry_emails = db.query(ScheduledEmail).filter(
            and_(
                ScheduledEmail.status == 'failed',
                ScheduledEmail.attempts < ScheduledEmail.max_attempts,
                or_(
                    ScheduledEmail.last_attempt_at < retry_threshold,
                    ScheduledEmail.last_attempt_at.is_(None)
                )
            )
        ).order_by(ScheduledEmail.priority.asc()).limit(max_retries).all()
        
        retried_count = 0
        for scheduled_email in retry_emails:
            # Reset status for retry
            scheduled_email.status = 'scheduled'
            scheduled_email.error_message = None
            retried_count += 1
            
            logger.info(f"Reset scheduled email {scheduled_email.id} for retry (attempt {scheduled_email.attempts + 1})")
        
        db.commit()
        
        return {
            "success": True,
            "emails_retried": retried_count,
            "total_eligible": len(retry_emails)
        }
        
    except Exception as e:
        logger.error(f"Error in retry_failed_emails: {str(e)}")
        db.rollback()
        return {"success": False, "error": str(e)}
        
    finally:
        db.close()

@celery_app.task(bind=True)
def generate_delivery_report(self, user_id: int, days: int = 7) -> Dict[str, Any]:
    """
    Generate comprehensive delivery report for a user
    
    Args:
        user_id: User ID to generate report for
        days: Number of days to include in report
        
    Returns:
        Dict with delivery report data
    """
    db = next(get_db())
    
    try:
        # Calculate date range
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)
        
        # Get sent emails in date range
        sent_emails = db.query(SentEmail).filter(
            and_(
                SentEmail.user_id == user_id,
                SentEmail.sent_at >= start_date,
                SentEmail.sent_at <= end_date
            )
        ).all()
        
        # Calculate statistics
        total_sent = len(sent_emails)
        delivered = len([e for e in sent_emails if e.status == 'delivered'])
        opened = len([e for e in sent_emails if e.read_at is not None])
        bounced = len([e for e in sent_emails if e.status == 'bounced'])
        failed = len([e for e in sent_emails if e.status == 'failed'])
        
        # Provider breakdown
        provider_stats = {}
        for email in sent_emails:
            provider = email.provider or 'unknown'
            if provider not in provider_stats:
                provider_stats[provider] = {'sent': 0, 'delivered': 0, 'failed': 0}
            
            provider_stats[provider]['sent'] += 1
            if email.status == 'delivered':
                provider_stats[provider]['delivered'] += 1
            elif email.status in ['bounced', 'failed']:
                provider_stats[provider]['failed'] += 1
        
        # Daily breakdown
        daily_stats = {}
        for email in sent_emails:
            day = email.sent_at.date().isoformat()
            if day not in daily_stats:
                daily_stats[day] = {'sent': 0, 'delivered': 0}
            
            daily_stats[day]['sent'] += 1
            if email.status == 'delivered':
                daily_stats[day]['delivered'] += 1
        
        report = {
            "user_id": user_id,
            "period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "days": days
            },
            "summary": {
                "total_sent": total_sent,
                "delivered": delivered,
                "opened": opened,
                "bounced": bounced,
                "failed": failed,
                "delivery_rate": (delivered / total_sent * 100) if total_sent > 0 else 0,
                "open_rate": (opened / delivered * 100) if delivered > 0 else 0,
                "bounce_rate": (bounced / total_sent * 100) if total_sent > 0 else 0
            },
            "provider_breakdown": provider_stats,
            "daily_breakdown": daily_stats,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
        
        return {
            "success": True,
            "report": report
        }
        
    except Exception as e:
        logger.error(f"Error generating delivery report for user {user_id}: {str(e)}")
        return {"success": False, "error": str(e)}
        
    finally:
        db.close()
