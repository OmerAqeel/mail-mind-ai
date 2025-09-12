from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Float, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import json

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    google_id = Column(String, unique=True, index=True)
    access_token_encrypted = Column(Text)  # Encrypted OAuth token
    refresh_token_encrypted = Column(Text)  # Encrypted refresh token
    total_messages = Column(Integer, default=0)
    last_sync = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    is_active = Column(Boolean, default=True)
    
    # Relationships
    emails = relationship("Email", back_populates="user")
    settings = relationship("UserSettings", back_populates="user", uselist=False)

class UserSettings(Base):
    __tablename__ = "user_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    use_local_llm = Column(Boolean, default=False)
    auto_reply_enabled = Column(Boolean, default=False)
    redact_pii = Column(Boolean, default=True)
    encrypt_emails = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="settings")

class Email(Base):
    __tablename__ = "emails"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    gmail_id = Column(String, unique=True, index=True, nullable=False)  # Gmail message ID
    thread_id = Column(String, index=True)
    subject = Column(Text)
    sender_email = Column(String, index=True)
    sender_name = Column(String)
    recipient_email = Column(String)
    body_plain = Column(Text)
    body_html = Column(Text)
    snippet = Column(Text)  # Gmail snippet
    received_at = Column(DateTime(timezone=True))
    is_read = Column(Boolean, default=False)
    is_important = Column(Boolean, default=False)
    raw_json = Column(Text)  # Store full Gmail API response
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True))
    
    # Relationships
    user = relationship("User", back_populates="emails")
    labels = relationship("EmailLabel", back_populates="email")
    summary = relationship("EmailSummary", back_populates="email", uselist=False)
    actions = relationship("EmailAction", back_populates="email")

class EmailLabel(Base):
    __tablename__ = "email_labels"
    
    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(Integer, ForeignKey("emails.id"), nullable=False)
    name = Column(String, nullable=False)  # JOB, OPPORTUNITY, MARKETING, etc.
    confidence = Column(Float)  # AI confidence score
    created_by_agent = Column(String)  # Which agent created this label
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    email = relationship("Email", back_populates="labels")

class EmailSummary(Base):
    __tablename__ = "email_summaries"
    
    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(Integer, ForeignKey("emails.id"), unique=True, nullable=False)
    summary_text = Column(Text)  # Bullet points summary
    tldr = Column(Text)  # One-line TL;DR
    key_points = Column(JSON)  # JSON array of key points
    priority_score = Column(Float)  # Urgency score (0-1)
    priority_level = Column(String)  # LOW, MEDIUM, HIGH
    generated_by_agent = Column(String)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    email = relationship("Email", back_populates="summary")

class EmailAction(Base):
    __tablename__ = "email_actions"
    
    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(Integer, ForeignKey("emails.id"), nullable=False)
    agent_name = Column(String, nullable=False)  # classifier, summarizer, auto_reply
    action_type = Column(String, nullable=False)  # classify, summarize, draft_reply, send_reply
    status = Column(String, default="pending")  # pending, completed, failed
    result_data = Column(Text)  # JSON result from agent
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    
    # Relationships
    email = relationship("Email", back_populates="actions")

class EmailReplyDraft(Base):
    __tablename__ = "email_reply_drafts"
    
    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(Integer, ForeignKey("emails.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    reply_content = Column(Text, nullable=False)
    reply_type = Column(String)  # acknowledgment, meeting_response, etc.
    generation_method = Column(String)  # ai_generated, template_based
    safety_level = Column(String)  # safe, review_required, high_risk, blocked
    safety_score = Column(Float)
    safety_risks = Column(JSON)  # JSON array of risk descriptions
    requires_approval = Column(Boolean, default=True)
    status = Column(String, default="draft")  # draft, approved, rejected, sent, scheduled
    context_analysis = Column(JSON)  # JSON context from analysis
    tone_profile = Column(JSON)  # JSON tone profile used
    estimated_send_time = Column(DateTime(timezone=True))
    scheduled_send_time = Column(DateTime(timezone=True))
    user_approved = Column(Boolean, default=False)
    approved_at = Column(DateTime(timezone=True))
    modified_by_user = Column(Boolean, default=False)
    custom_instructions = Column(Text)
    validation_errors = Column(JSON)  # JSON array of validation errors
    is_superseded = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    email = relationship("Email")
    user = relationship("User")

class AwayMessage(Base):
    __tablename__ = "away_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message_content = Column(Text, nullable=False)
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    contact_info = Column(String)
    tone_style = Column(String, default="professional")
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    activated_at = Column(DateTime(timezone=True))
    deactivated_at = Column(DateTime(timezone=True))
    
    # Relationships
    user = relationship("User")
