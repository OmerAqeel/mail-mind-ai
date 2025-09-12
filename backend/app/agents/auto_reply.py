import re
import os
from typing import Dict, List, Optional, Tuple
from openai import OpenAI
from datetime import datetime, timedelta, timezone
import json
from .classifier import EmailClassifier
from .summarizer import EmailSummarizer
from enum import Enum

class ReplyType(Enum):
    ACKNOWLEDGMENT = "acknowledgment"
    MEETING_RESPONSE = "meeting_response"
    INFORMATION_REQUEST = "information_request"
    DECLINE = "decline"
    AWAY_MESSAGE = "away_message"
    CUSTOM = "custom"

class SafetyLevel(Enum):
    SAFE = "safe"
    REVIEW_REQUIRED = "review_required"
    HIGH_RISK = "high_risk"
    BLOCKED = "blocked"

class EmailAutoReply:
    """
    Privacy-first AI auto-reply agent with safety mechanisms and tone preservation
    """
    
    def __init__(self):
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.classifier = EmailClassifier()
        self.summarizer = EmailSummarizer()
        
        # Safety settings
        self.max_reply_length = 500  # Maximum characters for safety
        self.require_approval = True  # Always require user approval
        self.send_delay_minutes = 5  # Minimum delay before sending
        
        # Tone templates for different scenarios
        self.reply_templates = {
            ReplyType.ACKNOWLEDGMENT: {
                "professional": "Thank you for your email. I have received your message and will review it shortly. I'll get back to you with a response within [TIMEFRAME].",
                "casual": "Thanks for reaching out! Got your message and will take a look. Will get back to you soon.",
                "formal": "Thank you for your correspondence. I acknowledge receipt of your message dated [DATE] and will provide a response at my earliest convenience."
            },
            ReplyType.AWAY_MESSAGE: {
                "professional": "Thank you for your email. I am currently out of office and will return on [DATE]. For urgent matters, please contact [CONTACT]. I will respond to your email upon my return.",
                "casual": "Hey! I'm currently away and will be back on [DATE]. Will catch up on emails when I return. If it's urgent, try [CONTACT].",
                "formal": "I am currently out of office from [START_DATE] to [END_DATE]. Your email is important to me and I will respond promptly upon my return. For immediate assistance, please contact [CONTACT]."
            },
            ReplyType.MEETING_RESPONSE: {
                "accept": "Thank you for the meeting invitation. I confirm my attendance for [TIME] on [DATE]. Looking forward to the discussion.",
                "decline": "Thank you for the invitation. Unfortunately, I won't be able to attend the meeting on [DATE] due to a scheduling conflict. Could we reschedule?",
                "tentative": "Thank you for the meeting invitation. I have it marked as tentative for [TIME] on [DATE]. I'll confirm my attendance by [CONFIRM_DATE]."
            }
        }
        
        # Risk indicators for safety filtering
        self.high_risk_keywords = [
            'legal', 'lawsuit', 'court', 'attorney', 'confidential', 'classified',
            'contract', 'agreement', 'financial', 'investment', 'money transfer',
            'urgent payment', 'immediate action', 'deadline today'
        ]
        
        # Prohibited response types
        self.blocked_keywords = [
            'offensive', 'inappropriate', 'discriminatory', 'harassment',
            'personal information', 'password', 'social security', 'credit card'
        ]
    
    async def analyze_email_context(self, email_data: Dict) -> Dict:
        """
        Analyze email context using classification and summarization
        """
        try:
            # Get classification
            classification = await self.classifier.classify_email(email_data)
            
            # Get summary and priority
            summary = await self.summarizer.summarize_email(email_data)
            
            # Extract key context information
            context = {
                'category': classification.get('category', 'other'),
                'priority': summary.get('priority_level', 'medium'),
                'confidence': min(classification.get('confidence', 0), summary.get('confidence', 0)),
                'keywords': self.classifier.extract_keywords(f"{email_data.get('subject', '')} {email_data.get('body', '')}"),
                'tldr': summary.get('tldr', ''),
                'urgency_score': summary.get('priority_score', 0),
                'has_questions': 'type:question' in summary.get('reasoning', []),
                'has_meeting': 'meeting' in classification.get('category', '').lower(),
                'has_deadline': 'has_time_reference' in summary.get('reasoning', [])
            }
            
            return context
            
        except Exception as e:
            return {
                'category': 'other',
                'priority': 'medium',
                'confidence': 0.1,
                'error': str(e)
            }
    
    def detect_reply_type(self, email_data: Dict, context: Dict) -> ReplyType:
        """
        Detect what type of reply is most appropriate
        """
        subject = email_data.get('subject', '').lower()
        body = email_data.get('body', '').lower()
        category = context.get('category', 'other')
        
        # Meeting invitations
        if 'meeting' in category or any(word in subject for word in ['meeting', 'invitation', 'calendar', 'schedule']):
            return ReplyType.MEETING_RESPONSE
        
        # Information requests
        if context.get('has_questions') or any(word in body for word in ['please provide', 'can you', 'could you', 'information', 'details']):
            return ReplyType.INFORMATION_REQUEST
        
        # Acknowledgment for most other emails
        return ReplyType.ACKNOWLEDGMENT
    
    def assess_safety_level(self, email_data: Dict, context: Dict, reply_content: str) -> Dict:
        """
        Assess safety level of the proposed reply
        """
        safety_score = 0
        risks = []
        
        email_content = f"{email_data.get('subject', '')} {email_data.get('body', '')}".lower()
        reply_lower = reply_content.lower()
        
        # Check for high-risk keywords in original email
        for keyword in self.high_risk_keywords:
            if keyword in email_content:
                safety_score += 3
                risks.append(f"High-risk keyword detected: {keyword}")
        
        # Check for blocked content in reply
        for keyword in self.blocked_keywords:
            if keyword in reply_lower:
                safety_score += 10
                risks.append(f"Blocked keyword in reply: {keyword}")
        
        # Check reply length
        if len(reply_content) > self.max_reply_length:
            safety_score += 2
            risks.append("Reply exceeds maximum length")
        
        # Check for personal information patterns
        if re.search(r'\b\d{3}-\d{2}-\d{4}\b', reply_content):  # SSN pattern
            safety_score += 10
            risks.append("Potential personal information detected")
        
        # Check urgency and pressure
        if context.get('priority') == 'high' and context.get('urgency_score', 0) > 8:
            safety_score += 2
            risks.append("High urgency email - review recommended")
        
        # Determine safety level
        if safety_score >= 10:
            level = SafetyLevel.BLOCKED
        elif safety_score >= 6:
            level = SafetyLevel.HIGH_RISK
        elif safety_score >= 3:
            level = SafetyLevel.REVIEW_REQUIRED
        else:
            level = SafetyLevel.SAFE
        
        return {
            'safety_level': level.value,
            'safety_score': safety_score,
            'risks': risks,
            'requires_review': level in [SafetyLevel.REVIEW_REQUIRED, SafetyLevel.HIGH_RISK],
            'blocked': level == SafetyLevel.BLOCKED
        }
    
    def detect_user_tone(self, sample_emails: List[str] = None) -> Dict:
        """
        Analyze user's writing tone from sample emails (placeholder for future enhancement)
        """
        # For now, return default professional tone
        # In future, this could analyze user's sent emails to learn their style
        return {
            'tone_style': 'professional',
            'formality_level': 'medium',
            'typical_length': 'concise',
            'common_phrases': ['Thank you', 'Best regards', 'I appreciate'],
            'signature_style': 'formal'
        }
    
    def generate_template_reply(self, reply_type: ReplyType, tone_style: str = 'professional', context: Dict = None) -> str:
        """
        Generate a reply using predefined templates
        """
        if reply_type not in self.reply_templates:
            return self.reply_templates[ReplyType.ACKNOWLEDGMENT][tone_style]
        
        template = self.reply_templates[reply_type].get(tone_style, 
                    list(self.reply_templates[reply_type].values())[0])
        
        # Basic template variable replacement
        replacements = {
            '[TIMEFRAME]': '24-48 hours',
            '[DATE]': (datetime.now() + timedelta(days=1)).strftime('%B %d'),
            '[TIME]': '2:00 PM',
            '[CONTACT]': 'support@company.com',
            '[START_DATE]': datetime.now().strftime('%B %d'),
            '[END_DATE]': (datetime.now() + timedelta(days=3)).strftime('%B %d'),
            '[CONFIRM_DATE]': (datetime.now() + timedelta(days=1)).strftime('%B %d')
        }
        
        for placeholder, value in replacements.items():
            template = template.replace(placeholder, value)
        
        return template
    
    async def generate_ai_reply(self, email_data: Dict, context: Dict, tone_profile: Dict) -> str:
        """
        Generate AI-powered reply using OpenAI with context awareness
        """
        try:
            # Redact PII from original email
            subject_redacted = self.classifier.redact_pii(email_data.get('subject', ''))
            body_redacted = self.classifier.redact_pii(email_data.get('body', ''))
            
            # Prepare context for AI
            context_summary = f"""
            Email Category: {context.get('category', 'general')}
            Priority: {context.get('priority', 'medium')}
            Summary: {context.get('tldr', 'Email communication')}
            Has Questions: {context.get('has_questions', False)}
            Meeting Related: {context.get('has_meeting', False)}
            """
            
            prompt = f"""
            You are drafting a professional email reply. Follow these guidelines:

            ORIGINAL EMAIL:
            Subject: {subject_redacted}
            Content: {body_redacted[:800]}

            CONTEXT:
            {context_summary}

            TONE REQUIREMENTS:
            - Style: {tone_profile.get('tone_style', 'professional')}
            - Length: {tone_profile.get('typical_length', 'concise')} (max 200 words)
            - Formality: {tone_profile.get('formality_level', 'medium')}

            REQUIREMENTS:
            - Be helpful and professional
            - Address any questions appropriately
            - Keep it concise and clear
            - Include appropriate closing
            - NO personal information or commitments
            - NO financial or legal advice
            - NO inappropriate content

            Generate a reply that acknowledges the email and provides an appropriate response:
            """

            response = await self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a professional email assistant. Generate appropriate, safe, and helpful email replies. Always maintain professional boundaries and never include personal information."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=250,
                temperature=0.3  # Lower temperature for more consistent, professional responses
            )

            reply_content = response.choices[0].message.content.strip()
            
            # Clean up the response
            reply_content = reply_content.replace('"', '').strip()
            
            return reply_content

        except Exception as e:
            # Fallback to template reply
            return self.generate_template_reply(ReplyType.ACKNOWLEDGMENT, tone_profile.get('tone_style', 'professional'))
    
    async def generate_reply_draft(self, email_data: Dict, user_preferences: Dict = None) -> Dict:
        """
        Main method to generate a reply draft with safety checks
        """
        try:
            # Step 1: Analyze email context
            context = await self.analyze_email_context(email_data)
            
            # Step 2: Detect appropriate reply type
            reply_type = self.detect_reply_type(email_data, context)
            
            # Step 3: Get user tone profile (or use defaults)
            tone_profile = user_preferences.get('tone_profile', {}) if user_preferences else {}
            if not tone_profile:
                tone_profile = self.detect_user_tone()
            
            # Step 4: Generate reply content
            use_ai = user_preferences.get('use_ai_replies', True) if user_preferences else True
            
            if use_ai and context.get('confidence', 0) > 0.3:
                reply_content = await self.generate_ai_reply(email_data, context, tone_profile)
                generation_method = 'ai_generated'
            else:
                reply_content = self.generate_template_reply(reply_type, tone_profile.get('tone_style', 'professional'), context)
                generation_method = 'template_based'
            
            # Step 5: Safety assessment
            safety_assessment = self.assess_safety_level(email_data, context, reply_content)
            
            # Step 6: Prepare result
            result = {
                'reply_content': reply_content,
                'reply_type': reply_type.value,
                'generation_method': generation_method,
                'safety_assessment': safety_assessment,
                'context_analysis': context,
                'tone_profile': tone_profile,
                'requires_approval': True,  # Always require approval for safety
                'estimated_send_time': (datetime.now(timezone.utc) + timedelta(minutes=self.send_delay_minutes)).isoformat(),
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'privacy_protected': True
            }
            
            # Add safety warnings if needed
            if safety_assessment['blocked']:
                result['status'] = 'blocked'
                result['message'] = 'Reply blocked due to safety concerns'
            elif safety_assessment['requires_review']:
                result['status'] = 'review_required'
                result['message'] = 'Reply requires manual review before sending'
            else:
                result['status'] = 'ready_for_approval'
                result['message'] = 'Reply ready for user approval'
            
            return result
            
        except Exception as e:
            return {
                'error': f"Reply generation failed: {str(e)}",
                'status': 'error',
                'generated_at': datetime.now(timezone.utc).isoformat()
            }
    
    async def create_away_message(self, start_date: str, end_date: str, contact_info: str = None, tone_style: str = 'professional') -> Dict:
        """
        Create an automated away message
        """
        try:
            template = self.reply_templates[ReplyType.AWAY_MESSAGE][tone_style]
            
            # Replace template variables
            away_message = template.replace('[START_DATE]', start_date)
            away_message = away_message.replace('[END_DATE]', end_date)
            if contact_info:
                away_message = away_message.replace('[CONTACT]', contact_info)
            else:
                away_message = away_message.replace('. For immediate assistance, please contact [CONTACT]', '')
            
            return {
                'away_message': away_message,
                'active_from': start_date,
                'active_until': end_date,
                'tone_style': tone_style,
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'status': 'ready_for_activation'
            }
            
        except Exception as e:
            return {
                'error': f"Away message creation failed: {str(e)}",
                'status': 'error'
            }
    
    def validate_reply_before_send(self, reply_data: Dict) -> Dict:
        """
        Final validation before sending a reply
        """
        validation_result = {
            'is_valid': True,
            'errors': [],
            'warnings': []
        }
        
        # Check if reply exists
        if not reply_data.get('reply_content'):
            validation_result['is_valid'] = False
            validation_result['errors'].append("No reply content provided")
        
        # Check safety status
        if reply_data.get('safety_assessment', {}).get('blocked'):
            validation_result['is_valid'] = False
            validation_result['errors'].append("Reply is blocked due to safety concerns")
        
        # Check approval requirement
        if reply_data.get('requires_approval') and not reply_data.get('user_approved'):
            validation_result['is_valid'] = False
            validation_result['errors'].append("User approval required but not provided")
        
        # Check send delay
        estimated_send_time = reply_data.get('estimated_send_time')
        if estimated_send_time:
            send_time = datetime.fromisoformat(estimated_send_time.replace('Z', '+00:00'))
            if datetime.now(timezone.utc) < send_time:
                validation_result['warnings'].append(f"Recommended send delay not yet met ({send_time})")
        
        return validation_result
