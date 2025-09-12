import smtplib
import ssl
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Union
import json
import asyncio
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import base64
import logging
from enum import Enum

class EmailProvider(Enum):
    GMAIL_API = "gmail_api"
    SMTP_GMAIL = "smtp_gmail"
    SMTP_OUTLOOK = "smtp_outlook"
    SMTP_CUSTOM = "smtp_custom"

class EmailStatus(Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    BOUNCED = "bounced"
    SPAM = "spam"
    RETRY = "retry"

class EmailSender:
    """
    Privacy-first email sending agent with multiple provider support and delivery tracking
    """
    
    def __init__(self):
        # Gmail API settings
        self.gmail_scopes = [
            'https://www.googleapis.com/auth/gmail.send',
            'https://www.googleapis.com/auth/gmail.modify'
        ]
        
        # SMTP settings
        self.smtp_configs = {
            EmailProvider.SMTP_GMAIL: {
                'host': 'smtp.gmail.com',
                'port': 587,
                'use_tls': True
            },
            EmailProvider.SMTP_OUTLOOK: {
                'host': 'smtp-mail.outlook.com',
                'port': 587,
                'use_tls': True
            }
        }
        
        # Rate limiting
        self.max_emails_per_minute = 100  # Conservative limit
        self.max_emails_per_hour = 1000
        self.max_retries = 3
        self.retry_delays = [30, 300, 900]  # 30s, 5m, 15m
        
        # Initialize logger
        self.logger = logging.getLogger(__name__)
    
    def validate_email_data(self, email_data: Dict) -> Dict:
        """
        Validate email data before sending
        """
        validation_result = {
            'is_valid': True,
            'errors': [],
            'warnings': []
        }
        
        # Required fields
        required_fields = ['to', 'subject', 'body']
        for field in required_fields:
            if not email_data.get(field):
                validation_result['is_valid'] = False
                validation_result['errors'].append(f"Missing required field: {field}")
        
        # Email format validation
        import re
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        
        # Validate recipient email
        to_email = email_data.get('to', '')
        if to_email and not re.match(email_regex, to_email):
            validation_result['is_valid'] = False
            validation_result['errors'].append(f"Invalid recipient email format: {to_email}")
        
        # Validate sender email if provided
        from_email = email_data.get('from', '')
        if from_email and not re.match(email_regex, from_email):
            validation_result['is_valid'] = False
            validation_result['errors'].append(f"Invalid sender email format: {from_email}")
        
        # Check email length limits
        subject = email_data.get('subject', '')
        if len(subject) > 998:  # RFC 5322 limit
            validation_result['warnings'].append("Subject line exceeds recommended length")
        
        body = email_data.get('body', '')
        if len(body) > 50000:  # 50KB limit
            validation_result['warnings'].append("Email body is very large")
        
        # Check for potential spam indicators
        spam_keywords = ['urgent action required', 'click here now', 'limited time offer', 'act now']
        subject_lower = subject.lower()
        body_lower = body.lower()
        
        spam_score = 0
        for keyword in spam_keywords:
            if keyword in subject_lower or keyword in body_lower:
                spam_score += 1
        
        if spam_score > 2:
            validation_result['warnings'].append("Email content may trigger spam filters")
        
        return validation_result
    
    async def send_via_gmail_api(self, email_data: Dict, credentials: Credentials) -> Dict:
        """
        Send email using Gmail API
        """
        try:
            service = build('gmail', 'v1', credentials=credentials)
            
            # Create message
            message = MIMEMultipart()
            message['to'] = email_data['to']
            message['from'] = email_data.get('from', credentials.token_uri)  # Use authenticated user
            message['subject'] = email_data['subject']
            
            # Add reply-to if specified
            if email_data.get('reply_to'):
                message['Reply-To'] = email_data['reply_to']
            
            # Add in-reply-to for threading
            if email_data.get('in_reply_to'):
                message['In-Reply-To'] = email_data['in_reply_to']
                message['References'] = email_data['in_reply_to']
            
            # Add body
            if email_data.get('html_body'):
                message.attach(MIMEText(email_data['html_body'], 'html'))
            else:
                message.attach(MIMEText(email_data['body'], 'plain'))
            
            # Add attachments if any
            if email_data.get('attachments'):
                for attachment in email_data['attachments']:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment['content'])
                    encoders.encode_base64(part)
                    part.add_header(
                        'Content-Disposition',
                        f'attachment; filename= {attachment["filename"]}'
                    )
                    message.attach(part)
            
            # Convert to raw message
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            
            # Send message
            send_result = service.users().messages().send(
                userId='me',
                body={'raw': raw_message}
            ).execute()
            
            return {
                'status': 'sent',
                'message_id': send_result['id'],
                'provider': EmailProvider.GMAIL_API.value,
                'sent_at': datetime.now(timezone.utc).isoformat(),
                'thread_id': send_result.get('threadId')
            }
            
        except HttpError as e:
            error_details = json.loads(e.content.decode('utf-8'))
            return {
                'status': 'failed',
                'error': f"Gmail API error: {error_details.get('error', {}).get('message', str(e))}",
                'error_code': e.resp.status,
                'provider': EmailProvider.GMAIL_API.value
            }
        except Exception as e:
            return {
                'status': 'failed',
                'error': f"Unexpected error: {str(e)}",
                'provider': EmailProvider.GMAIL_API.value
            }
    
    async def send_via_smtp(self, email_data: Dict, provider: EmailProvider, smtp_credentials: Dict) -> Dict:
        """
        Send email using SMTP
        """
        try:
            config = self.smtp_configs.get(provider)
            if not config:
                return {
                    'status': 'failed',
                    'error': f"Unsupported SMTP provider: {provider}",
                    'provider': provider.value
                }
            
            # Create message
            message = MIMEMultipart()
            message['From'] = smtp_credentials.get('email')
            message['To'] = email_data['to']
            message['Subject'] = email_data['subject']
            
            # Add reply-to if specified
            if email_data.get('reply_to'):
                message['Reply-To'] = email_data['reply_to']
            
            # Add in-reply-to for threading
            if email_data.get('in_reply_to'):
                message['In-Reply-To'] = email_data['in_reply_to']
                message['References'] = email_data['in_reply_to']
            
            # Add body
            if email_data.get('html_body'):
                message.attach(MIMEText(email_data['html_body'], 'html'))
            else:
                message.attach(MIMEText(email_data['body'], 'plain'))
            
            # Add attachments if any
            if email_data.get('attachments'):
                for attachment in email_data['attachments']:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment['content'])
                    encoders.encode_base64(part)
                    part.add_header(
                        'Content-Disposition',
                        f'attachment; filename= {attachment["filename"]}'
                    )
                    message.attach(part)
            
            # Create SMTP connection
            server = smtplib.SMTP(config['host'], config['port'])
            
            if config.get('use_tls'):
                context = ssl.create_default_context()
                server.starttls(context=context)
            
            # Login
            server.login(smtp_credentials['email'], smtp_credentials['password'])
            
            # Send email
            text = message.as_string()
            server.sendmail(smtp_credentials['email'], email_data['to'], text)
            server.quit()
            
            return {
                'status': 'sent',
                'message_id': f"smtp_{datetime.now(timezone.utc).timestamp()}",
                'provider': provider.value,
                'sent_at': datetime.now(timezone.utc).isoformat()
            }
            
        except smtplib.SMTPAuthenticationError as e:
            return {
                'status': 'failed',
                'error': f"SMTP authentication failed: {str(e)}",
                'error_code': 'auth_error',
                'provider': provider.value
            }
        except smtplib.SMTPRecipientsRefused as e:
            return {
                'status': 'failed',
                'error': f"Recipient refused: {str(e)}",
                'error_code': 'recipient_refused',
                'provider': provider.value
            }
        except smtplib.SMTPException as e:
            return {
                'status': 'failed',
                'error': f"SMTP error: {str(e)}",
                'error_code': 'smtp_error',
                'provider': provider.value
            }
        except Exception as e:
            return {
                'status': 'failed',
                'error': f"Unexpected error: {str(e)}",
                'provider': provider.value
            }
    
    async def send_email(self, email_data: Dict, send_config: Dict) -> Dict:
        """
        Main method to send an email using the specified provider
        """
        try:
            # Validate email data
            validation = self.validate_email_data(email_data)
            if not validation['is_valid']:
                return {
                    'status': 'failed',
                    'error': 'Validation failed',
                    'validation_errors': validation['errors'],
                    'warnings': validation.get('warnings', [])
                }
            
            # Get provider
            provider = EmailProvider(send_config.get('provider', EmailProvider.GMAIL_API.value))
            
            # Add metadata
            send_metadata = {
                'provider': provider.value,
                'attempt': send_config.get('attempt', 1),
                'sent_from_system': True,
                'user_id': send_config.get('user_id'),
                'original_draft_id': send_config.get('draft_id')
            }
            
            # Send based on provider
            if provider == EmailProvider.GMAIL_API:
                credentials = send_config.get('credentials')
                if not credentials:
                    # Demo mode - simulate successful send
                    return {
                        'status': 'sent',
                        'message_id': f'demo_gmail_{datetime.now(timezone.utc).timestamp()}',
                        'provider': provider.value,
                        'sent_at': datetime.now(timezone.utc).isoformat(),
                        'demo_mode': True,
                        **send_metadata
                    }
                result = await self.send_via_gmail_api(email_data, credentials)
            
            else:  # SMTP providers
                smtp_credentials = send_config.get('smtp_credentials')
                if not smtp_credentials:
                    # Demo mode - simulate successful send
                    return {
                        'status': 'sent',
                        'message_id': f'demo_smtp_{datetime.now(timezone.utc).timestamp()}',
                        'provider': provider.value,
                        'sent_at': datetime.now(timezone.utc).isoformat(),
                        'demo_mode': True,
                        **send_metadata
                    }
                result = await self.send_via_smtp(email_data, provider, smtp_credentials)
            
            # Add metadata to result
            result.update(send_metadata)
            
            # Add warnings if any
            if validation.get('warnings'):
                result['warnings'] = validation['warnings']
            
            return result
            
        except Exception as e:
            return {
                'status': 'failed',
                'error': f"Email sending failed: {str(e)}",
                'sent_at': datetime.now(timezone.utc).isoformat()
            }
    
    def create_reply_email(self, original_email: Dict, reply_content: str, include_original: bool = True) -> Dict:
        """
        Create a properly formatted reply email
        """
        # Extract original details
        original_subject = original_email.get('subject', '')
        original_from = original_email.get('sender', original_email.get('from', ''))
        original_message_id = original_email.get('message_id', original_email.get('gmail_id'))
        
        # Create reply subject
        reply_subject = original_subject
        if not reply_subject.startswith('Re: '):
            reply_subject = f"Re: {reply_subject}"
        
        # Create reply body
        reply_body = reply_content
        
        if include_original:
            original_date = original_email.get('received_at', datetime.now(timezone.utc).isoformat())
            original_body = original_email.get('body', original_email.get('body_plain', ''))
            
            reply_body += f"\n\n---\nOn {original_date}, {original_from} wrote:\n"
            # Indent original message
            original_lines = original_body.split('\n')
            indented_original = '\n'.join(f"> {line}" for line in original_lines)
            reply_body += indented_original
        
        reply_email = {
            'to': original_from,
            'subject': reply_subject,
            'body': reply_body,
            'in_reply_to': original_message_id,
            'references': original_message_id
        }
        
        return reply_email
    
    def schedule_email(self, email_data: Dict, send_at: datetime, send_config: Dict) -> Dict:
        """
        Schedule an email for future sending
        """
        try:
            # Validate schedule time
            now = datetime.now(timezone.utc)
            if send_at <= now:
                return {
                    'status': 'failed',
                    'error': 'Scheduled time must be in the future'
                }
            
            # Validate email before scheduling
            validation = self.validate_email_data(email_data)
            if not validation['is_valid']:
                return {
                    'status': 'failed',
                    'error': 'Email validation failed',
                    'validation_errors': validation['errors']
                }
            
            schedule_data = {
                'status': 'scheduled',
                'scheduled_for': send_at.isoformat(),
                'email_data': email_data,
                'send_config': send_config,
                'created_at': now.isoformat(),
                'attempts': 0
            }
            
            if validation.get('warnings'):
                schedule_data['warnings'] = validation['warnings']
            
            return schedule_data
            
        except Exception as e:
            return {
                'status': 'failed',
                'error': f"Email scheduling failed: {str(e)}"
            }
    
    async def process_scheduled_emails(self, scheduled_emails: List[Dict]) -> List[Dict]:
        """
        Process a batch of scheduled emails that are ready to send
        """
        results = []
        now = datetime.now(timezone.utc)
        
        for scheduled_email in scheduled_emails:
            try:
                # Check if it's time to send
                send_time = datetime.fromisoformat(scheduled_email['scheduled_for'].replace('Z', '+00:00'))
                if send_time > now:
                    continue  # Not yet time
                
                # Attempt to send
                result = await self.send_email(
                    scheduled_email['email_data'],
                    scheduled_email['send_config']
                )
                
                # Update scheduling info
                result['was_scheduled'] = True
                result['original_schedule_time'] = scheduled_email['scheduled_for']
                result['schedule_id'] = scheduled_email.get('id')
                
                results.append(result)
                
            except Exception as e:
                error_result = {
                    'status': 'failed',
                    'error': f"Scheduled email processing failed: {str(e)}",
                    'schedule_id': scheduled_email.get('id'),
                    'was_scheduled': True
                }
                results.append(error_result)
        
        return results
    
    def get_delivery_status(self, message_id: str, provider: EmailProvider, credentials: Dict = None) -> Dict:
        """
        Get delivery status for a sent email (placeholder for future implementation)
        """
        # This would integrate with provider APIs to check delivery status
        # For now, return basic status
        return {
            'message_id': message_id,
            'status': EmailStatus.SENT.value,
            'provider': provider.value,
            'last_checked': datetime.now(timezone.utc).isoformat(),
            'delivery_details': {
                'delivered': None,
                'opened': None,
                'clicked': None,
                'bounced': False,
                'spam': False
            }
        }
    
    def create_email_summary(self, email_data: Dict, send_result: Dict) -> Dict:
        """
        Create a summary of the email sending operation
        """
        return {
            'recipient': email_data.get('to'),
            'subject': email_data.get('subject'),
            'status': send_result.get('status'),
            'provider': send_result.get('provider'),
            'message_id': send_result.get('message_id'),
            'sent_at': send_result.get('sent_at'),
            'error': send_result.get('error'),
            'warnings': send_result.get('warnings', []),
            'body_length': len(email_data.get('body', '')),
            'has_attachments': bool(email_data.get('attachments')),
            'is_reply': bool(email_data.get('in_reply_to'))
        }
