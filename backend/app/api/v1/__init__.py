from fastapi import APIRouter

from . import emails, classify, summarize, auto_reply, email_sending, webhooks

api_router = APIRouter()

# Include all API endpoint routers
api_router.include_router(
    emails.router,
    prefix="/emails",
    tags=["Email Management"]
)

api_router.include_router(
    classify.router,
    prefix="/classification",
    tags=["Email Classification"]
)

api_router.include_router(
    summarize.router,
    prefix="/summarization", 
    tags=["Email Summarization"]
)

api_router.include_router(
    auto_reply.router,
    prefix="/auto-reply",
    tags=["Auto Reply"]
)

api_router.include_router(
    email_sending.router,
    prefix="/sending",
    tags=["Email Sending"]
)

api_router.include_router(
    webhooks.router,
    prefix="/webhooks",
    tags=["Delivery Tracking"]
)
