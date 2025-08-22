import re
import os
from typing import Dict, List, Optional
from openai import OpenAI
from datetime import datetime
import json

class EmailClassifier:
    """
    Privacy-first email classifier that uses local rules + OpenAI API
    """
    
    def __init__(self):
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        # Categories we classify into
        self.categories = [
            "JOB",
            "OPPORTUNITY", 
            "MARKETING",
            "PERSONAL",
            "SPAM",
            "IMPORTANT"
        ]
        
        # Local classification rules (privacy-first)
        self.local_rules = {
            "JOB": [
                "job", "position", "role", "hiring", "career", "apply", "interview",
                "recruit", "vacancy", "employment", "candidate"
            ],
            "MARKETING": [
                "sale", "discount", "offer", "deal", "promotion", "limited time",
                "unsubscribe", "newsletter", "marketing", "%", "buy now"
            ],
            "SPAM": [
                "click here", "urgent", "act now", "congratulations", "winner",
                "free money", "nigerian prince", "inheritance"
            ]
        }
    
    def redact_pii(self, text: str) -> str:
        """
        Remove personally identifiable information from text
        """
        if not text:
            return ""
        
        # Email addresses
        text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]', text)
        
        # Phone numbers (various formats)
        phone_patterns = [
            r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',  # 123-456-7890, 123.456.7890, 1234567890
            r'\b\(\d{3}\)\s?\d{3}[-.]?\d{4}\b',  # (123) 456-7890
            r'\b\+\d{1,3}[-.\s]?\d{3,4}[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b'  # International
        ]
        for pattern in phone_patterns:
            text = re.sub(pattern, '[PHONE]', text)
        
        # URLs
        text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '[URL]', text)
        
        # Credit card numbers (basic pattern)
        text = re.sub(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b', '[CARD]', text)
        
        # Social Security Numbers
        text = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '[SSN]', text)
        
        # Common name patterns (titles + potential names)
        text = re.sub(r'\b(Mr|Mrs|Ms|Dr|Prof)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b', '[NAME]', text)
        
        # Addresses (basic street patterns)
        text = re.sub(r'\b\d+\s+[A-Za-z\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln)\b', '[ADDRESS]', text)
        
        return text
    
    def extract_keywords(self, text: str) -> List[str]:
        """
        Extract meaningful keywords from email text
        """
        if not text:
            return []
        
        # Clean text - remove HTML tags, extra whitespace
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Convert to lowercase for processing
        text_lower = text.lower()
        
        # Define keyword categories
        urgency_keywords = [
            'urgent', 'asap', 'immediate', 'emergency', 'critical', 'deadline',
            'rush', 'priority', 'time-sensitive', 'expedite'
        ]
        
        financial_keywords = [
            'invoice', 'payment', 'bill', 'receipt', 'refund', 'transaction',
            'purchase', 'order', 'subscription', 'charge', 'fee', 'cost',
            'price', 'amount', 'total', 'balance', 'account'
        ]
        
        meeting_keywords = [
            'meeting', 'call', 'appointment', 'schedule', 'calendar',
            'conference', 'zoom', 'teams', 'webinar', 'discussion'
        ]
        
        work_keywords = [
            'project', 'task', 'deliverable', 'milestone', 'report',
            'presentation', 'document', 'proposal', 'contract', 'agreement'
        ]
        
        personal_keywords = [
            'family', 'friend', 'personal', 'vacation', 'holiday',
            'birthday', 'anniversary', 'celebration', 'party'
        ]
        
        support_keywords = [
            'support', 'help', 'issue', 'problem', 'error', 'bug',
            'ticket', 'question', 'inquiry', 'assistance'
        ]
        
        # Combine all keyword categories
        all_keywords = {
            'urgency': urgency_keywords,
            'financial': financial_keywords,
            'meeting': meeting_keywords,
            'work': work_keywords,
            'personal': personal_keywords,
            'support': support_keywords
        }
        
        found_keywords = []
        
        # Extract keywords by category
        for category, keywords in all_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    found_keywords.append(f"{category}:{keyword}")
        
        # Extract action words (verbs)
        action_words = [
            'review', 'approve', 'submit', 'send', 'update', 'complete',
            'schedule', 'confirm', 'cancel', 'reschedule', 'follow-up',
            'discuss', 'decide', 'implement', 'prepare', 'deliver'
        ]
        
        for action in action_words:
            if action in text_lower:
                found_keywords.append(f"action:{action}")
        
        # Extract question indicators
        if '?' in text or any(q in text_lower for q in ['what', 'when', 'where', 'who', 'why', 'how']):
            found_keywords.append('type:question')
        
        # Extract time references
        time_patterns = [
            r'\b(today|tomorrow|yesterday)\b',
            r'\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
            r'\b(january|february|march|april|may|june|july|august|september|october|november|december)\b',
            r'\b\d{1,2}:\d{2}\s?(am|pm)?\b',
            r'\b\d{1,2}/\d{1,2}/\d{2,4}\b'
        ]
        
        for pattern in time_patterns:
            if re.search(pattern, text_lower):
                found_keywords.append('has_time_reference')
                break
        
        return list(set(found_keywords))  # Remove duplicates
    
    def classify_locally(self, keywords: List[str], sender: str, subject: str) -> Optional[Dict]:
        """
        Classify email using local rules before sending to OpenAI
        Returns classification if confident, None if needs AI assistance
        """
        if not keywords:
            return None
        
        # Convert keywords to sets for easier matching
        keyword_strings = [kw.split(':')[-1] if ':' in kw else kw for kw in keywords]
        keyword_set = set(keyword_strings)
        
        # High confidence rules based on keywords
        
        # 1. Spam/Promotional detection
        spam_indicators = {
            'urgent', 'limited time', 'act now', 'free', 'winner', 'congratulations',
            'claim', 'prize', 'offer', 'discount', 'sale', 'deal'
        }
        if len(keyword_set.intersection(spam_indicators)) >= 2:
            return {
                'category': 'spam',
                'priority': 'low',
                'confidence': 0.9,
                'reasoning': 'Multiple spam indicators detected'
            }
        
        # 2. Financial/Billing emails
        financial_indicators = {'invoice', 'payment', 'bill', 'receipt', 'transaction', 'refund'}
        if keyword_set.intersection(financial_indicators):
            priority = 'high' if 'urgent' in keyword_set else 'medium'
            return {
                'category': 'financial',
                'priority': priority,
                'confidence': 0.85,
                'reasoning': 'Financial keywords detected'
            }
        
        # 3. Meeting/Calendar emails
        meeting_indicators = {'meeting', 'call', 'appointment', 'schedule', 'calendar', 'conference'}
        if keyword_set.intersection(meeting_indicators):
            priority = 'high' if any(kw in keywords for kw in ['urgency:', 'has_time_reference']) else 'medium'
            return {
                'category': 'meetings',
                'priority': priority,
                'confidence': 0.8,
                'reasoning': 'Meeting/calendar keywords detected'
            }
        
        # 4. Support/Technical emails
        support_indicators = {'support', 'help', 'issue', 'problem', 'error', 'bug', 'ticket'}
        if keyword_set.intersection(support_indicators):
            priority = 'high' if 'urgent' in keyword_set else 'medium'
            return {
                'category': 'support',
                'priority': priority,
                'confidence': 0.8,
                'reasoning': 'Support/technical keywords detected'
            }
        
        # 5. Work/Project emails
        work_indicators = {'project', 'task', 'deliverable', 'milestone', 'report', 'proposal'}
        if keyword_set.intersection(work_indicators):
            priority = 'medium'
            if 'urgency:' in [kw.split(':')[0] for kw in keywords if ':' in kw]:
                priority = 'high'
            return {
                'category': 'work',
                'priority': priority,
                'confidence': 0.75,
                'reasoning': 'Work/project keywords detected'
            }
        
        # 6. Personal emails
        personal_indicators = {'family', 'friend', 'personal', 'vacation', 'birthday', 'party'}
        if keyword_set.intersection(personal_indicators):
            return {
                'category': 'personal',
                'priority': 'low',
                'confidence': 0.7,
                'reasoning': 'Personal keywords detected'
            }
        
        # 7. Sender-based rules (common patterns)
        sender_lower = sender.lower()
        
        # Known service patterns
        if any(service in sender_lower for service in ['noreply', 'no-reply', 'notification', 'support']):
            if keyword_set.intersection(financial_indicators):
                return {
                    'category': 'financial',
                    'priority': 'medium',
                    'confidence': 0.8,
                    'reasoning': 'Service notification with financial content'
                }
            else:
                return {
                    'category': 'notifications',
                    'priority': 'low',
                    'confidence': 0.75,
                    'reasoning': 'Automated service notification'
                }
        
        # 8. Subject-based high-confidence rules
        subject_lower = subject.lower()
        
        if any(word in subject_lower for word in ['unsubscribe', 'newsletter', 'promotion']):
            return {
                'category': 'promotional',
                'priority': 'low',
                'confidence': 0.85,
                'reasoning': 'Promotional content in subject'
            }
        
        if any(word in subject_lower for word in ['urgent', 'asap', 'immediate']):
            return {
                'category': 'urgent',
                'priority': 'high',
                'confidence': 0.8,
                'reasoning': 'Urgent markers in subject'
            }
        
        # 9. Action-required emails
        action_keywords = [kw for kw in keywords if kw.startswith('action:')]
        if len(action_keywords) >= 2 or 'type:question' in keywords:
            return {
                'category': 'action_required',
                'priority': 'medium',
                'confidence': 0.75,
                'reasoning': 'Multiple action items or questions detected'
            }
        
        # If no high-confidence local classification, return None for AI processing
        return None
    
    async def classify_with_openai(self, redacted_content: str, keywords: List[str]) -> Dict:
        """
        Use OpenAI to classify emails when local rules aren't sufficient
        """
        try:
            # Create a structured prompt for classification
            keyword_summary = ", ".join(keywords[:10])  # Limit keywords to avoid token overflow
            
            prompt = f"""
            Classify this email based on the following criteria:

            Email Content (PII removed): {redacted_content[:1000]}
            Extracted Keywords: {keyword_summary}

            Please classify this email into one of these categories:
            - work: Professional/business communications
            - personal: Personal communications from friends/family
            - financial: Bills, invoices, payments, banking
            - promotional: Marketing, advertisements, newsletters
            - support: Customer service, technical support
            - meetings: Calendar invites, meeting requests
            - notifications: Automated system notifications
            - action_required: Emails requiring immediate response/action
            - spam: Unwanted or suspicious emails
            - other: Doesn't fit other categories

            Priority levels:
            - high: Requires immediate attention
            - medium: Important but not urgent
            - low: Can be handled later

            Respond in this exact JSON format:
            {{
                "category": "category_name",
                "priority": "priority_level",
                "confidence": 0.0-1.0,
                "reasoning": "brief explanation"
            }}
            """

            response = await self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are an email classification assistant. Always respond with valid JSON in the exact format requested."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=200,
                temperature=0.1  # Low temperature for consistent classification
            )

            # Parse OpenAI response
            response_text = response.choices[0].message.content.strip()
            
            # Try to extract JSON from response
            try:
                import json
                # Remove any markdown code blocks if present
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0]
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0]
                
                result = json.loads(response_text)
                
                # Validate required fields
                required_fields = ['category', 'priority', 'confidence', 'reasoning']
                if all(field in result for field in required_fields):
                    return result
                else:
                    raise ValueError("Missing required fields in OpenAI response")
                    
            except (json.JSONDecodeError, ValueError) as e:
                # Fallback classification if JSON parsing fails
                return {
                    'category': 'other',
                    'priority': 'medium',
                    'confidence': 0.3,
                    'reasoning': f'OpenAI response parsing failed: {str(e)}'
                }

        except Exception as e:
            # Fallback classification if OpenAI fails
            return {
                'category': 'other',
                'priority': 'medium',
                'confidence': 0.2,
                'reasoning': f'OpenAI classification failed: {str(e)}'
            }
    
    async def classify_email(self, email_data: Dict) -> Dict:
        """
        Main classification method - privacy-first approach
        """
        subject = email_data.get('subject', '')
        body = email_data.get('body', '')
        sender = email_data.get('sender', '')
        
        # Step 1: Extract keywords for analysis
        full_content = f"{subject} {body}"
        keywords = self.extract_keywords(full_content)
        
        # Step 2: Try local classification first (privacy-first)
        local_result = self.classify_locally(keywords, sender, subject)
        
        if local_result and local_result.get('confidence', 0) >= 0.7:
            local_result['method'] = 'local_rules'
            local_result['privacy_protected'] = True
            return local_result
        
        # Step 3: If local classification isn't confident enough, use OpenAI
        redacted_content = self.redact_pii(full_content)
        
        openai_result = await self.classify_with_openai(redacted_content, keywords)
        openai_result['method'] = 'openai_api'
        openai_result['privacy_protected'] = True
        
        # Step 4: Combine local insights with OpenAI result if available
        if local_result:
            # If we have a local result but low confidence, 
            # we can use it to validate or adjust OpenAI result
            if local_result['category'] == openai_result['category']:
                openai_result['confidence'] = min(1.0, openai_result['confidence'] + 0.1)
                openai_result['reasoning'] += ' (confirmed by local rules)'
        
        return openai_result
