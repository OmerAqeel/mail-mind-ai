import re
import os
from typing import Dict, List, Optional, Tuple
from openai import OpenAI
from datetime import datetime
import json
from .classifier import EmailClassifier

class EmailSummarizer:
    """
    Privacy-first email summarizer that creates bullet points, TL;DR, and priority scores
    """
    
    def __init__(self):
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.classifier = EmailClassifier()  # Reuse classification logic
        
        # Content length thresholds
        self.min_summary_length = 100  # Don't summarize very short emails
        self.max_content_length = 2000  # Truncate very long emails for processing
        
        # Priority keywords for local scoring
        self.urgency_indicators = {
            'critical': 5,
            'urgent': 4,
            'asap': 4,
            'immediate': 4,
            'emergency': 5,
            'deadline': 3,
            'time-sensitive': 3,
            'priority': 2,
            'important': 2
        }
        
        self.sender_importance = {
            'boss': 4,
            'manager': 4,
            'ceo': 5,
            'director': 4,
            'hr': 3,
            'support': 1,
            'noreply': 0,
            'no-reply': 0
        }
    
    def extract_email_content(self, subject: str, body: str) -> Dict[str, str]:
        """
        Extract and clean email content for summarization
        """
        # Clean HTML if present
        if body and '<' in body and '>' in body:
            # Basic HTML tag removal
            clean_body = re.sub(r'<[^>]+>', '', body)
            clean_body = re.sub(r'&[a-zA-Z]+;', '', clean_body)  # Remove HTML entities
        else:
            clean_body = body or ""
        
        # Remove excessive whitespace and newlines
        clean_body = re.sub(r'\n\s*\n', '\n\n', clean_body)
        clean_body = re.sub(r'[ \t]+', ' ', clean_body)
        clean_body = clean_body.strip()
        
        # Remove email signatures (common patterns)
        signature_patterns = [
            r'--\s*\n.*',  # Standard signature delimiter
            r'Best regards,.*',
            r'Sincerely,.*',
            r'Thanks,.*',
            r'Sent from my.*',
            r'This email was sent.*',
            r'Confidentiality notice.*'
        ]
        
        for pattern in signature_patterns:
            clean_body = re.sub(pattern, '', clean_body, flags=re.DOTALL | re.IGNORECASE)
        
        # Extract key information
        word_count = len(clean_body.split())
        char_count = len(clean_body)
        
        # Truncate if too long for processing
        if char_count > self.max_content_length:
            clean_body = clean_body[:self.max_content_length] + "..."
        
        return {
            'subject': subject or "",
            'body': clean_body,
            'word_count': word_count,
            'char_count': char_count,
            'needs_summary': word_count > 50  # Only summarize substantial emails
        }
    
    def calculate_priority_score(self, subject: str, body: str, sender: str, keywords: List[str] = None) -> Dict[str, any]:
        """
        Calculate email priority score using local rules
        """
        score = 0.0
        reasoning = []
        
        # Get keywords if not provided
        if keywords is None:
            keywords = self.classifier.extract_keywords(f"{subject} {body}")
        
        # Extract keyword values for easier processing
        keyword_strings = [kw.split(':')[-1] if ':' in kw else kw for kw in keywords]
        keyword_set = set(keyword_strings)
        
        # 1. Urgency keywords in subject (higher weight)
        subject_lower = subject.lower()
        for word, weight in self.urgency_indicators.items():
            if word in subject_lower:
                score += weight * 0.3  # 30% weight for subject urgency
                reasoning.append(f"'{word}' in subject")
        
        # 2. Urgency keywords in body (lower weight)
        body_lower = body.lower()
        for word, weight in self.urgency_indicators.items():
            if word in body_lower:
                score += weight * 0.1  # 10% weight for body urgency
                reasoning.append(f"'{word}' in content")
        
        # 3. Sender importance
        sender_lower = sender.lower()
        for role, weight in self.sender_importance.items():
            if role in sender_lower:
                score += weight * 0.2  # 20% weight for sender
                reasoning.append(f"sender contains '{role}'")
        
        # 4. Time sensitivity
        if 'has_time_reference' in keywords:
            score += 1.5
            reasoning.append("contains time references")
        
        # 5. Action required
        action_keywords = [kw for kw in keywords if kw.startswith('action:')]
        if len(action_keywords) >= 2:
            score += 2.0
            reasoning.append("multiple action items required")
        elif action_keywords:
            score += 1.0
            reasoning.append("action required")
        
        # 6. Question indicators
        if 'type:question' in keywords:
            score += 1.5
            reasoning.append("contains questions")
        
        # 7. Financial/billing priority
        financial_keywords = {'invoice', 'payment', 'bill', 'transaction', 'refund'}
        if keyword_set.intersection(financial_keywords):
            score += 2.0
            reasoning.append("financial/billing content")
        
        # 8. Meeting/scheduling priority
        meeting_keywords = {'meeting', 'call', 'appointment', 'schedule', 'conference'}
        if keyword_set.intersection(meeting_keywords):
            score += 1.5
            reasoning.append("meeting/scheduling content")
        
        # 9. Support/issue priority
        if any(kw in keyword_set for kw in ['issue', 'problem', 'error', 'bug']):
            score += 1.0
            reasoning.append("support/issue content")
        
        # 10. Promotional/spam penalty
        spam_indicators = {'unsubscribe', 'promotion', 'sale', 'offer', 'deal'}
        if keyword_set.intersection(spam_indicators):
            score -= 2.0
            reasoning.append("promotional/marketing content (low priority)")
        
        # Normalize score to 0-10 range
        normalized_score = min(10.0, max(0.0, score))
        
        # Convert to priority levels
        if normalized_score >= 7.0:
            priority_level = "high"
        elif normalized_score >= 4.0:
            priority_level = "medium"
        else:
            priority_level = "low"
        
        return {
            'priority_score': round(normalized_score, 2),
            'priority_level': priority_level,
            'reasoning': reasoning,
            'confidence': min(1.0, normalized_score / 10.0)
        }
    
    def generate_local_summary(self, content: Dict[str, str]) -> Optional[Dict[str, str]]:
        """
        Generate basic summary using local rules (privacy-first approach)
        """
        subject = content['subject']
        body = content['body']
        
        if not content['needs_summary']:
            return {
                'bullet_points': [subject] if subject else ["Short email - no summary needed"],
                'tldr': subject or "Brief message",
                'method': 'local_rules',
                'confidence': 0.9
            }
        
        # Extract first few sentences for basic summary
        sentences = re.split(r'[.!?]+', body)
        meaningful_sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
        
        if len(meaningful_sentences) == 0:
            return None
        
        # Create basic bullet points (first 3 sentences)
        bullet_points = meaningful_sentences[:3]
        
        # Create TL;DR (first sentence or subject)
        tldr = meaningful_sentences[0] if meaningful_sentences else subject
        
        # Only return if we have decent content
        if len(' '.join(bullet_points)) < 50:
            return None
        
        return {
            'bullet_points': bullet_points,
            'tldr': tldr,
            'method': 'local_rules',
            'confidence': 0.6  # Lower confidence for local summaries
        }
    
    async def generate_ai_summary(self, content: Dict[str, str], keywords: List[str] = None) -> Dict[str, str]:
        """
        Generate detailed summary using OpenAI with privacy protection
        """
        try:
            # Redact PII before sending to OpenAI
            subject_redacted = self.classifier.redact_pii(content['subject'])
            body_redacted = self.classifier.redact_pii(content['body'])
            
            # Prepare keyword context
            keyword_context = ""
            if keywords:
                keyword_summary = ", ".join(keywords[:8])  # Limit keywords
                keyword_context = f"\nKey themes: {keyword_summary}"
            
            prompt = f"""
            Summarize this email effectively and professionally:

            Subject: {subject_redacted}
            Content (PII removed): {body_redacted[:1500]}{keyword_context}

            Provide a summary in this exact JSON format:
            {{
                "bullet_points": ["First key point", "Second key point", "Third key point"],
                "tldr": "One-line summary of the main message",
                "key_actions": ["Action 1", "Action 2"] or [],
                "sentiment": "neutral|positive|negative|urgent",
                "estimated_read_time": "1-2 minutes"
            }}

            Guidelines:
            - Bullet points should be 10-15 words each
            - TL;DR should be one clear sentence
            - Focus on actionable information
            - Maintain professional tone
            - If no actions needed, return empty key_actions array
            """

            response = await self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a professional email summarization assistant. Always respond with valid JSON in the exact format requested."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=300,
                temperature=0.1
            )

            # Parse response
            response_text = response.choices[0].message.content.strip()
            
            try:
                # Clean up JSON response
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0]
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0]
                
                result = json.loads(response_text)
                
                # Validate required fields
                required_fields = ['bullet_points', 'tldr']
                if all(field in result for field in required_fields):
                    result['method'] = 'openai_api'
                    result['confidence'] = 0.85
                    return result
                else:
                    raise ValueError("Missing required fields in OpenAI response")
                    
            except (json.JSONDecodeError, ValueError):
                # Fallback to simple extraction
                return {
                    'bullet_points': [f"Email about: {subject_redacted}"],
                    'tldr': subject_redacted or "Email communication",
                    'method': 'openai_api_fallback',
                    'confidence': 0.3
                }

        except Exception as e:
            # Return basic fallback summary
            return {
                'bullet_points': [f"Email from sender: {content['subject']}"],
                'tldr': content['subject'] or "Email message",
                'method': 'ai_fallback',
                'confidence': 0.2,
                'error': str(e)
            }
    
    async def summarize_email(self, email_data: Dict) -> Dict:
        """
        Main summarization method - privacy-first approach
        """
        subject = email_data.get('subject', '')
        body = email_data.get('body', '')
        sender = email_data.get('sender', '')
        
        # Step 1: Extract and clean content
        content = self.extract_email_content(subject, body)
        
        # Step 2: Calculate priority score
        keywords = self.classifier.extract_keywords(f"{subject} {body}")
        priority_info = self.calculate_priority_score(subject, body, sender, keywords)
        
        # Step 3: Try local summarization first
        local_summary = self.generate_local_summary(content)
        
        # Step 4: Use AI if local summary isn't sufficient or for complex emails
        if not local_summary or content['word_count'] > 200:
            ai_summary = await self.generate_ai_summary(content, keywords)
            
            # Combine local priority info with AI summary
            result = {
                **ai_summary,
                **priority_info,
                'word_count': content['word_count'],
                'privacy_protected': True,
                'generated_at': datetime.utcnow().isoformat()
            }
        else:
            # Use local summary with priority info
            result = {
                **local_summary,
                **priority_info,
                'word_count': content['word_count'],
                'privacy_protected': True,
                'generated_at': datetime.utcnow().isoformat()
            }
        
        return result
    
    async def summarize_thread(self, emails: List[Dict]) -> Dict:
        """
        Summarize an entire email thread
        """
        if not emails:
            return {'error': 'No emails provided'}
        
        if len(emails) == 1:
            return await self.summarize_email(emails[0])
        
        # For multiple emails, create thread summary
        thread_content = ""
        participants = set()
        latest_priority = 0
        
        for email in emails:
            thread_content += f"From {email.get('sender', 'Unknown')}: {email.get('subject', '')} - {email.get('body', '')[:200]}... "
            participants.add(email.get('sender', 'Unknown'))
            
            # Get priority of individual emails
            email_summary = await self.summarize_email(email)
            if email_summary.get('priority_score', 0) > latest_priority:
                latest_priority = email_summary.get('priority_score', 0)
        
        # Summarize the entire thread
        thread_data = {
            'subject': f"Thread: {emails[0].get('subject', 'No subject')}",
            'body': thread_content,
            'sender': f"Thread with {', '.join(list(participants)[:3])}"
        }
        
        summary = await self.summarize_email(thread_data)
        summary['thread_participants'] = list(participants)
        summary['email_count'] = len(emails)
        summary['thread_priority_score'] = latest_priority
        
        return summary
