from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from app.db.database import get_db
from app.models.database import User, Email, EmailLabel, EmailSummary
from app.agents.classifier import EmailClassifier
from app.agents.summarizer import EmailSummarizer
import json
from datetime import datetime
from typing import List, Optional
import base64
import email

router = APIRouter()

# Initialize AI agents
classifier = EmailClassifier()
summarizer = EmailSummarizer()

@router.post("/ingest")
async def ingest_emails(
    access_token: str,
    max_results: int = Query(default=10, le=100),
    auto_process: bool = Query(default=True, description="Automatically classify and summarize emails"),
    db: Session = Depends(get_db)
):
    """
    Ingest emails from Gmail API
    For now, requires manual access_token. Later we'll store tokens in DB.
    """
    try:
        # Create credentials from access token
        credentials = Credentials(token=access_token)
        
        # Build Gmail service
        service = build('gmail', 'v1', credentials=credentials)
        
        # Get user profile
        profile = service.users().getProfile(userId='me').execute()
        user_email = profile.get('emailAddress')
        
        # Check if user exists, create if not
        user = db.query(User).filter(User.email == user_email).first()
        if not user:
            user = User(
                email=user_email,
                total_messages=profile.get('messagesTotal', 0),
                access_token_encrypted=access_token  # TODO: Encrypt this
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        
        # Get list of messages
        results = service.users().messages().list(
            userId='me',
            maxResults=max_results,
            q='in:inbox'  # Only inbox messages for now
        ).execute()
        
        messages = results.get('messages', [])
        ingested_emails = []
        
        for msg in messages:
            message_id = msg['id']
            
            # Check if email already exists
            existing_email = db.query(Email).filter(
                Email.gmail_id == message_id,
                Email.user_id == user.id
            ).first()
            
            if existing_email:
                continue  # Skip if already ingested
            
            # Get full message details
            message = service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            
            # Parse email data
            email_data = parse_gmail_message(message)
            
            # Create email record
            email_record = Email(
                user_id=user.id,
                gmail_id=message_id,
                thread_id=message.get('threadId'),
                subject=email_data.get('subject'),
                sender_email=email_data.get('sender_email'),
                sender_name=email_data.get('sender_name'),
                recipient_email=email_data.get('recipient_email'),
                body_plain=email_data.get('body_plain'),
                body_html=email_data.get('body_html'),
                snippet=message.get('snippet'),
                received_at=datetime.fromtimestamp(int(message.get('internalDate', 0)) / 1000),
                raw_json=json.dumps(message),
                processed_at=datetime.utcnow()
            )
            
            db.add(email_record)
            db.flush()  # Get the email ID
            
            # Auto-process with AI agents if enabled
            processing_results = {}
            if auto_process:
                try:
                    # Classification
                    classification_data = {
                        "subject": email_data.get('subject', ''),
                        "body": email_data.get('body_plain', ''),
                        "sender": email_data.get('sender_email', '')
                    }
                    
                    classification_result = await classifier.classify_email(classification_data)
                    
                    # Store classification as label
                    email_label = EmailLabel(
                        email_id=email_record.id,
                        name=classification_result.get('category', 'other'),
                        confidence=classification_result.get('confidence', 0.0),
                        created_by_agent='classifier'
                    )
                    db.add(email_label)
                    
                    # Summarization
                    summarization_result = await summarizer.summarize_email(classification_data)
                    
                    # Store summary
                    email_summary = EmailSummary(
                        email_id=email_record.id,
                        summary_text='\n'.join(summarization_result.get('bullet_points', [])),
                        tldr=summarization_result.get('tldr', ''),
                        key_points=str(summarization_result.get('key_actions', [])),
                        priority_score=summarization_result.get('priority_score', 0.0),
                        priority_level=summarization_result.get('priority_level', 'medium'),
                        generated_by_agent='summarizer'
                    )
                    db.add(email_summary)
                    
                    processing_results = {
                        "classification": classification_result,
                        "summarization": summarization_result
                    }
                    
                except Exception as e:
                    processing_results = {"error": f"AI processing failed: {str(e)}"}
            
            ingested_emails.append({
                "gmail_id": message_id,
                "subject": email_data.get('subject'),
                "sender": email_data.get('sender_email'),
                "received_at": email_record.received_at.isoformat(),
                "ai_processing": processing_results if auto_process else "disabled"
            })
        
        db.commit()
        
        return {
            "message": f"Successfully ingested {len(ingested_emails)} emails",
            "user_email": user_email,
            "ingested_count": len(ingested_emails),
            "emails": ingested_emails
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ingest error: {str(e)}")

@router.get("/emails")
async def get_emails(
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
):
    """Get ingested emails from database"""
    emails = db.query(Email).offset(offset).limit(limit).all()
    
    return {
        "emails": [
            {
                "id": email.id,
                "gmail_id": email.gmail_id,
                "subject": email.subject,
                "sender_email": email.sender_email,
                "sender_name": email.sender_name,
                "snippet": email.snippet,
                "received_at": email.received_at.isoformat() if email.received_at else None,
                "processed_at": email.processed_at.isoformat() if email.processed_at else None
            }
            for email in emails
        ],
        "count": len(emails)
    }

def parse_gmail_message(message):
    """Parse Gmail API message to extract email data"""
    headers = {h['name']: h['value'] for h in message['payload'].get('headers', [])}
    
    subject = headers.get('Subject', '')
    sender = headers.get('From', '')
    recipient = headers.get('To', '')
    
    # Parse sender name and email
    sender_email = sender
    sender_name = sender
    if '<' in sender and '>' in sender:
        sender_name = sender.split('<')[0].strip().strip('"')
        sender_email = sender.split('<')[1].split('>')[0].strip()
    
    # Extract body
    body_plain = ""
    body_html = ""
    
    def extract_body(payload):
        nonlocal body_plain, body_html
        
        if payload.get('mimeType') == 'text/plain' and payload.get('body', {}).get('data'):
            body_plain = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
        elif payload.get('mimeType') == 'text/html' and payload.get('body', {}).get('data'):
            body_html = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
        
        # Recursively check parts
        for part in payload.get('parts', []):
            extract_body(part)
    
    extract_body(message['payload'])
    
    return {
        'subject': subject,
        'sender_email': sender_email,
        'sender_name': sender_name,
        'recipient_email': recipient,
        'body_plain': body_plain,
        'body_html': body_html
    }

# Test endpoint to create emails directly (for development/testing)
from pydantic import BaseModel

class CreateEmailRequest(BaseModel):
    gmail_id: str
    thread_id: str
    subject: str
    sender_email: str
    sender_name: str
    recipient_email: str
    body_plain: str
    body_html: Optional[str] = None
    snippet: Optional[str] = None
    received_at: Optional[str] = None

@router.post("/test-create")
async def create_test_email(
    request: CreateEmailRequest,
    db: Session = Depends(get_db)
):
    """
    Create a test email directly (for development/testing purposes)
    """
    try:
        # Create a test user if doesn't exist
        user = db.query(User).filter(User.email == request.recipient_email).first()
        if not user:
            user = User(
                email=request.recipient_email,
                total_messages=1
            )
            db.add(user)
            db.flush()
        
        # Parse received_at
        received_at = None
        if request.received_at:
            try:
                received_at = datetime.fromisoformat(request.received_at.replace('Z', '+00:00'))
            except:
                received_at = datetime.now()
        else:
            received_at = datetime.now()
        
        # Create email
        email_obj = Email(
            user_id=user.id,
            gmail_id=request.gmail_id,
            thread_id=request.thread_id,
            subject=request.subject,
            sender_email=request.sender_email,
            sender_name=request.sender_name,
            recipient_email=request.recipient_email,
            body_plain=request.body_plain,
            body_html=request.body_html,
            snippet=request.snippet or request.body_plain[:150],
            received_at=received_at
        )
        
        db.add(email_obj)
        db.commit()
        db.refresh(email_obj)
        
        return {
            "message": "Test email created successfully",
            "email_id": email_obj.id,
            "user_id": user.id
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create email: {str(e)}")
