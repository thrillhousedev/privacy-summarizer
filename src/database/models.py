"""Database models for Privacy Summarizer."""

from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
    Index,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Group(Base):
    """Signal group chat - minimal metadata only."""

    __tablename__ = "groups"

    id = Column(Integer, primary_key=True)
    group_id = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    messages = relationship("Message", back_populates="group", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Group(id={self.group_id}, name={self.name})>"


class Message(Base):
    """Temporarily stored message for summarization.

    Messages are stored only until summarized, then purged based on retention policy.
    No user names or profiles are stored - only UUIDs for deduplication.
    """

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    signal_timestamp = Column(BigInteger, nullable=False)  # Signal's timestamp_ms
    sender_uuid = Column(String(255), nullable=False)  # For deduplication only, not displayed
    group_id = Column(String(255), ForeignKey("groups.group_id"), nullable=False, index=True)
    content = Column(Text, nullable=True)  # Encrypted via SQLCipher
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    group = relationship("Group", back_populates="messages")
    reactions = relationship("Reaction", back_populates="message", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('signal_timestamp', 'sender_uuid', 'group_id', name='uq_message_identity'),
        Index('idx_message_group_timestamp', 'group_id', 'signal_timestamp'),
        Index('idx_message_received_at', 'received_at'),
    )

    def __repr__(self):
        return f"<Message(id={self.id}, group={self.group_id}, timestamp={self.signal_timestamp})>"


class Reaction(Base):
    """Reaction to a message - for engagement metrics.

    Reactions enable summaries like "12 messages received reactions" without
    revealing who reacted. Purged with parent messages (cascade delete).
    """

    __tablename__ = "reactions"

    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    emoji = Column(String(50), nullable=False)  # The reaction emoji
    reactor_uuid = Column(String(255), nullable=False)  # For deduplication only
    timestamp = Column(BigInteger, nullable=False)  # Signal's timestamp_ms

    # Relationships
    message = relationship("Message", back_populates="reactions")

    __table_args__ = (
        UniqueConstraint('message_id', 'reactor_uuid', name='uq_reaction_identity'),
    )

    def __repr__(self):
        return f"<Reaction(id={self.id}, emoji={self.emoji}, message_id={self.message_id})>"


class ScheduledSummary(Base):
    """Scheduled summary job configuration for posting summaries from one group to another."""

    __tablename__ = "scheduled_summaries"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    source_group_id = Column(Integer, ForeignKey("groups.id"), nullable=False, index=True)
    target_group_id = Column(Integer, ForeignKey("groups.id"), nullable=False, index=True)
    schedule_times = Column(JSON, nullable=False)  # Array of time strings: ["08:00", "20:00"]
    timezone = Column(String(50), default="UTC", nullable=False)  # IANA timezone (e.g., "America/Chicago")
    summary_period_hours = Column(Integer, default=24)  # How many hours to look back for summary
    schedule_type = Column(String(20), default="daily", nullable=False)  # "daily" or "weekly"
    schedule_day_of_week = Column(Integer)  # 0-6 for weekly schedules (0=Monday, 6=Sunday), NULL for daily
    retention_hours = Column(Integer, default=48, nullable=False)  # Per-schedule message retention period
    detail_mode = Column(Boolean, default=True, nullable=False)  # True = detailed (default), False = simple
    enabled = Column(Boolean, default=True, nullable=False)
    last_run = Column(DateTime)  # Last execution timestamp
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    source_group = relationship("Group", foreign_keys=[source_group_id])
    target_group = relationship("Group", foreign_keys=[target_group_id])
    summary_runs = relationship("SummaryRun", back_populates="schedule", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_enabled_schedules", "enabled"),
    )

    def __repr__(self):
        return f"<ScheduledSummary(name={self.name}, source={self.source_group_id}, target={self.target_group_id}, enabled={self.enabled})>"


class SummaryRun(Base):
    """Record of a summary execution - tracks execution metadata for monitoring.

    Summary text is NOT stored - summaries are generated, posted, and discarded.
    Only execution metadata is retained for debugging and monitoring.
    """

    __tablename__ = "summary_runs"

    id = Column(Integer, primary_key=True)
    schedule_id = Column(Integer, ForeignKey("scheduled_summaries.id", ondelete="CASCADE"), nullable=False, index=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    message_count = Column(Integer, default=0)  # Number of messages summarized
    oldest_message_time = Column(DateTime, nullable=True)  # Time window start
    newest_message_time = Column(DateTime, nullable=True)  # Time window end
    status = Column(String(20), default="pending", nullable=False)  # pending, completed, failed
    error_message = Column(Text, nullable=True)  # Error details if failed

    # Relationships
    schedule = relationship("ScheduledSummary", back_populates="summary_runs")

    __table_args__ = (
        Index('idx_summary_run_schedule_started', 'schedule_id', 'started_at'),
        Index('idx_summary_run_status', 'status'),
    )

    def __repr__(self):
        return f"<SummaryRun(id={self.id}, schedule={self.schedule_id}, status={self.status}, messages={self.message_count})>"


class DMConversation(Base):
    """Direct message conversation storage for AI chat.

    Stores both user messages and assistant responses for context continuity.
    Auto-purged based on retention policy (default 48 hours).
    """

    __tablename__ = "dm_conversations"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(100), nullable=False, index=True)  # User's Signal UUID or phone number
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)  # Message content (encrypted via SQLCipher)
    signal_timestamp = Column(BigInteger, nullable=True)  # Original Signal timestamp (for user messages)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('idx_dm_user_created', 'user_id', 'created_at'),
        Index('idx_dm_created_at', 'created_at'),
    )

    def __repr__(self):
        return f"<DMConversation(id={self.id}, user={self.user_id[:8]}..., role={self.role})>"


class DMSettings(Base):
    """Per-user DM settings including retention preferences.

    Stores user-configurable settings for DM conversations.
    """

    __tablename__ = "dm_settings"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(100), nullable=False, unique=True, index=True)  # User's Signal UUID or phone number
    retention_hours = Column(Integer, default=48, nullable=False)  # User's retention preference
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<DMSettings(user={self.user_id[:8]}..., retention={self.retention_hours}h)>"


class GroupSettings(Base):
    """Per-group settings including retention and permission preferences.

    Stores group-configurable settings for message retention and command permissions.
    Can be set via Signal's disappearing messages or !retention command.

    source values:
    - "signal": Auto-follows Signal's disappearing message setting
    - "command": Fixed by user via !retention [hours] command

    power_mode values:
    - "admins": Only room admins can run configuration commands (default)
    - "everyone": All room members can run configuration commands

    purge_on_summary values:
    - True (default): Purge messages immediately after !summary command
    - False: Keep messages until retention period expires
    """

    __tablename__ = "group_settings"

    id = Column(Integer, primary_key=True)
    group_id = Column(String(255), nullable=False, unique=True, index=True)  # Signal group ID
    retention_hours = Column(Integer, default=48, nullable=False)  # Retention preference in hours
    source = Column(String(20), default="signal", nullable=False)  # "signal" or "command"
    power_mode = Column(String(20), default="admins", nullable=False)  # "admins" or "everyone"
    purge_on_summary = Column(Boolean, default=True, nullable=False)  # True = purge after !summary
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<GroupSettings(group={self.group_id[:20]}..., retention={self.retention_hours}h, power={self.power_mode})>"


class UserOptOut(Base):
    """Per-user per-group opt-out for message collection.

    When opted_out=True, messages from this user in this group are NOT stored.
    Users control their own data - no admin permission needed.
    Default is opted-in (no record = messages collected).
    """

    __tablename__ = "user_opt_outs"

    id = Column(Integer, primary_key=True)
    group_id = Column(String(255), nullable=False, index=True)
    sender_uuid = Column(String(255), nullable=False, index=True)
    opted_out = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint('group_id', 'sender_uuid', name='uq_user_opt_out'),
    )

    def __repr__(self):
        return f"<UserOptOut(group={self.group_id[:20]}..., user={self.sender_uuid[:8]}..., opted_out={self.opted_out})>"
