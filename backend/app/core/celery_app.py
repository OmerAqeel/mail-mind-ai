"""
Celery configuration for background task processing
"""
from celery import Celery
from celery.schedules import crontab
import os

# Initialize Celery app
celery_app = Celery(
    "mail_mind_ai",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    include=[
        "app.tasks.email_tasks",
        "app.tasks.scheduler_tasks"
    ]
)

# Celery configuration
celery_app.conf.update(
    # Task serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    
    # Task routing
    task_routes={
        "app.tasks.email_tasks.send_scheduled_email": {"queue": "emails"},
        "app.tasks.email_tasks.process_delivery_webhook": {"queue": "webhooks"},
        "app.tasks.scheduler_tasks.process_scheduled_emails": {"queue": "scheduler"},
    },
    
    # Task execution
    task_always_eager=False,
    task_eager_propagates=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    worker_disable_rate_limits=False,
    
    # Task time limits
    task_soft_time_limit=300,  # 5 minutes
    task_time_limit=600,  # 10 minutes
    
    # Result backend settings
    result_expires=3600,  # 1 hour
    result_persistent=False,
    
    # Beat schedule for periodic tasks
    beat_schedule={
        "process-scheduled-emails": {
            "task": "app.tasks.scheduler_tasks.process_scheduled_emails",
            "schedule": crontab(minute="*/2"),  # Every 2 minutes
        },
        "cleanup-old-tasks": {
            "task": "app.tasks.scheduler_tasks.cleanup_old_tasks",
            "schedule": crontab(hour=2, minute=0),  # Daily at 2 AM
        },
        "update-delivery-stats": {
            "task": "app.tasks.scheduler_tasks.update_delivery_statistics",
            "schedule": crontab(minute="*/15"),  # Every 15 minutes
        },
    },
    
    # Worker settings
    worker_max_tasks_per_child=1000,
    worker_max_memory_per_child=200000,  # 200MB
    
    # Retry settings
    task_default_retry_delay=60,  # 1 minute
    task_max_retries=3,
)

# Celery signals for monitoring
@celery_app.task(bind=True)
def debug_task(self):
    """Debug task for testing Celery setup"""
    print(f"Request: {self.request!r}")
