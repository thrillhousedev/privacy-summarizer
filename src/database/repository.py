"""Database repository for CRUD operations - Privacy Summarizer."""

import os
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import sessionmaker, Session, joinedload
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .models import Base, Group, Message, Reaction, ScheduledSummary, SummaryRun, DMConversation, DMSettings, GroupSettings, UserOptOut


class DatabaseRepository:
    """Repository pattern for database operations with encryption."""

    def __init__(self, db_path: str, encryption_key: str = None):
        """Initialize the database connection with encryption.

        Args:
            db_path: Path to SQLite database file
            encryption_key: Encryption key for database (required for Privacy Summarizer)

        Raises:
            ValueError: If encryption_key is not provided
        """
        self.db_path = db_path

        # Require encryption key for Privacy Summarizer
        if not encryption_key:
            encryption_key = os.getenv('ENCRYPTION_KEY')

        if not encryption_key:
            raise ValueError(
                "ENCRYPTION_KEY environment variable is required for Privacy Summarizer. "
                "Set it in your .env file or pass it directly."
            )

        # Validate encryption key strength (minimum 16 bytes / 128 bits)
        if len(encryption_key) < 16:
            raise ValueError(
                "ENCRYPTION_KEY must be at least 16 characters (128 bits) for secure encryption. "
                "Generate a strong key with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )

        self.encryption_key = encryption_key

        # Try to use SQLCipher for encryption if available
        try:
            import pysqlcipher3.dbapi2 as sqlcipher

            # Create a wrapper class to handle create_function compatibility
            # pysqlcipher3 doesn't support the 'deterministic' kwarg that SQLAlchemy uses
            class ConnectionWrapper:
                """Wrapper around pysqlcipher3 connection to handle API differences."""

                def __init__(self, conn):
                    self._conn = conn

                def create_function(self, name, num_params, func, deterministic=False):
                    # Ignore deterministic parameter - pysqlcipher3 doesn't support it
                    return self._conn.create_function(name, num_params, func)

                def __getattr__(self, name):
                    return getattr(self._conn, name)

            # Connection creator that wraps connections
            key = self.encryption_key

            def connection_creator():
                conn = sqlcipher.connect(db_path, check_same_thread=False)
                # Set encryption key immediately using parameterized approach
                # SQLCipher PRAGMA key requires the key in quotes, so we escape any quotes in the key
                cursor = conn.cursor()
                escaped_key = key.replace("'", "''")
                cursor.execute(f"PRAGMA key = '{escaped_key}'")
                cursor.close()
                return ConnectionWrapper(conn)

            self.engine = create_engine(
                "sqlite://",  # URL is ignored when using creator
                creator=connection_creator,
                echo=False
            )

            self._use_sqlcipher = True
        except ImportError:
            # Fall back to regular SQLite (for development/testing)
            # In production, this should fail to ensure encryption
            self.engine = create_engine(
                f"sqlite:///{db_path}",
                echo=False,
                connect_args={'check_same_thread': False}
            )
            self._use_sqlcipher = False
            print("WARNING: SQLCipher not available. Database is NOT encrypted!")
            print("Install pysqlcipher3 for encryption: pip install pysqlcipher3")

        self.Session = sessionmaker(bind=self.engine)
        self._create_tables()
        self._run_migrations()

    def _create_tables(self):
        """Create all tables if they don't exist."""
        Base.metadata.create_all(self.engine)

    def _run_migrations(self):
        """Run any necessary database migrations."""
        import logging
        logger = logging.getLogger(__name__)

        with self.engine.connect() as conn:
            # Migration: Rename phone_number to user_id in dm_conversations
            try:
                # Check if old column exists
                result = conn.execute(text("PRAGMA table_info(dm_conversations)"))
                columns = [row[1] for row in result.fetchall()]

                if 'phone_number' in columns and 'user_id' not in columns:
                    logger.info("Running migration: dm_conversations phone_number -> user_id")
                    # SQLite/SQLCipher doesn't support ALTER COLUMN RENAME directly
                    # We need to recreate the table
                    conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS dm_conversations_new (
                            id INTEGER PRIMARY KEY,
                            user_id VARCHAR(100) NOT NULL,
                            role VARCHAR(20) NOT NULL,
                            content TEXT NOT NULL,
                            signal_timestamp BIGINT,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                        )
                    """))
                    conn.execute(text("""
                        INSERT INTO dm_conversations_new (id, user_id, role, content, signal_timestamp, created_at)
                        SELECT id, phone_number, role, content, signal_timestamp, created_at
                        FROM dm_conversations
                    """))
                    conn.execute(text("DROP TABLE dm_conversations"))
                    conn.execute(text("ALTER TABLE dm_conversations_new RENAME TO dm_conversations"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_dm_user_created ON dm_conversations(user_id, created_at)"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_dm_created_at ON dm_conversations(created_at)"))
                    conn.commit()
                    logger.info("Migration completed: dm_conversations")
            except Exception as e:
                logger.debug(f"dm_conversations migration skipped or failed: {e}")

            # Migration: Rename phone_number to user_id in dm_settings
            try:
                result = conn.execute(text("PRAGMA table_info(dm_settings)"))
                columns = [row[1] for row in result.fetchall()]

                if 'phone_number' in columns and 'user_id' not in columns:
                    logger.info("Running migration: dm_settings phone_number -> user_id")
                    conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS dm_settings_new (
                            id INTEGER PRIMARY KEY,
                            user_id VARCHAR(100) NOT NULL UNIQUE,
                            retention_hours INTEGER DEFAULT 48 NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                        )
                    """))
                    conn.execute(text("""
                        INSERT INTO dm_settings_new (id, user_id, retention_hours, created_at, updated_at)
                        SELECT id, phone_number, retention_hours, created_at, updated_at
                        FROM dm_settings
                    """))
                    conn.execute(text("DROP TABLE dm_settings"))
                    conn.execute(text("ALTER TABLE dm_settings_new RENAME TO dm_settings"))
                    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_dm_settings_user_id ON dm_settings(user_id)"))
                    conn.commit()
                    logger.info("Migration completed: dm_settings")
            except Exception as e:
                logger.debug(f"dm_settings migration skipped or failed: {e}")

            # Migration: Create group_settings table if it doesn't exist
            try:
                result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='group_settings'"))
                if not result.fetchone():
                    logger.info("Creating group_settings table")
                    conn.execute(text("""
                        CREATE TABLE group_settings (
                            id INTEGER PRIMARY KEY,
                            group_id VARCHAR(255) NOT NULL UNIQUE,
                            retention_hours INTEGER DEFAULT 48 NOT NULL,
                            source VARCHAR(20) DEFAULT 'signal' NOT NULL,
                            power_mode VARCHAR(20) DEFAULT 'admins' NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                        )
                    """))
                    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_group_settings_group_id ON group_settings(group_id)"))
                    conn.commit()
                    logger.info("Created group_settings table")
            except Exception as e:
                logger.debug(f"group_settings table creation skipped or failed: {e}")

            # Migration: Add power_mode column to group_settings if it doesn't exist
            try:
                result = conn.execute(text("PRAGMA table_info(group_settings)"))
                columns = [row[1] for row in result.fetchall()]

                if 'power_mode' not in columns:
                    logger.info("Adding power_mode column to group_settings")
                    conn.execute(text("ALTER TABLE group_settings ADD COLUMN power_mode VARCHAR(20) DEFAULT 'admins' NOT NULL"))
                    conn.commit()
                    logger.info("Added power_mode column to group_settings")
            except Exception as e:
                logger.debug(f"power_mode column migration skipped or failed: {e}")

            # Migration: Add detail_mode column to scheduled_summaries if it doesn't exist
            try:
                result = conn.execute(text("PRAGMA table_info(scheduled_summaries)"))
                columns = [row[1] for row in result.fetchall()]

                if 'detail_mode' not in columns:
                    logger.info("Adding detail_mode column to scheduled_summaries")
                    conn.execute(text("ALTER TABLE scheduled_summaries ADD COLUMN detail_mode BOOLEAN DEFAULT 1 NOT NULL"))
                    conn.commit()
                    logger.info("Added detail_mode column to scheduled_summaries")
            except Exception as e:
                logger.debug(f"detail_mode column migration skipped or failed: {e}")

            # Migration: Add purge_on_summary column to group_settings if it doesn't exist
            try:
                result = conn.execute(text("PRAGMA table_info(group_settings)"))
                columns = [row[1] for row in result.fetchall()]

                if 'purge_on_summary' not in columns:
                    logger.info("Adding purge_on_summary column to group_settings")
                    conn.execute(text("ALTER TABLE group_settings ADD COLUMN purge_on_summary BOOLEAN DEFAULT 1 NOT NULL"))
                    conn.commit()
                    logger.info("Added purge_on_summary column to group_settings")
            except Exception as e:
                logger.debug(f"purge_on_summary column migration skipped or failed: {e}")

            # Migration: Create user_opt_outs table if it doesn't exist
            try:
                result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='user_opt_outs'"))
                if not result.fetchone():
                    logger.info("Creating user_opt_outs table")
                    conn.execute(text("""
                        CREATE TABLE user_opt_outs (
                            id INTEGER PRIMARY KEY,
                            group_id VARCHAR(255) NOT NULL,
                            sender_uuid VARCHAR(255) NOT NULL,
                            opted_out BOOLEAN DEFAULT 1 NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                            CONSTRAINT uq_user_opt_out UNIQUE (group_id, sender_uuid)
                        )
                    """))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_user_opt_outs_group_id ON user_opt_outs(group_id)"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_user_opt_outs_sender_uuid ON user_opt_outs(sender_uuid)"))
                    conn.commit()
                    logger.info("Created user_opt_outs table")
            except Exception as e:
                logger.debug(f"user_opt_outs table creation skipped or failed: {e}")

    def get_session(self) -> Session:
        """Get a new database session."""
        return self.Session()

    # Group operations
    def create_group(self, group_id: str, name: str, description: str = None) -> Group:
        """Create or update a group."""
        with self.get_session() as session:
            group = session.query(Group).filter_by(group_id=group_id).first()
            if group:
                group.name = name
                group.description = description
                group.updated_at = datetime.utcnow()
            else:
                group = Group(group_id=group_id, name=name, description=description)
                session.add(group)
            session.commit()
            session.refresh(group)
            return group

    def get_group_by_id(self, group_id: str) -> Optional[Group]:
        """Get a group by its Signal group ID."""
        with self.get_session() as session:
            return session.query(Group).filter_by(group_id=group_id).first()

    def get_all_groups(self) -> List[Group]:
        """Get all groups."""
        with self.get_session() as session:
            return session.query(Group).all()

    # Scheduled Summary operations
    def create_scheduled_summary(
        self,
        name: str,
        source_group_id: int,
        target_group_id: int,
        schedule_times: List[str],
        timezone: str = "UTC",
        summary_period_hours: int = 24,
        schedule_type: str = "daily",
        schedule_day_of_week: int = None,
        retention_hours: int = 48,
        detail_mode: bool = True,
        enabled: bool = True
    ) -> ScheduledSummary:
        """Create a new scheduled summary.

        Args:
            name: Display name for this scheduled summary
            source_group_id: Database ID of source group to summarize
            target_group_id: Database ID of target group to post summaries
            schedule_times: List of times in HH:MM format (e.g., ["08:00", "20:00"])
            timezone: IANA timezone name (e.g., "America/Chicago")
            summary_period_hours: How many hours to look back for summary
            schedule_type: "daily" or "weekly"
            schedule_day_of_week: 0-6 for weekly schedules (0=Monday, 6=Sunday), None for daily
            retention_hours: How long to retain messages for this schedule (default 48h)
            detail_mode: True for detailed summaries (default), False for simple
            enabled: Whether this schedule is active

        Returns:
            The created ScheduledSummary object
        """
        with self.get_session() as session:
            scheduled_summary = ScheduledSummary(
                name=name,
                source_group_id=source_group_id,
                target_group_id=target_group_id,
                schedule_times=schedule_times,
                timezone=timezone,
                summary_period_hours=summary_period_hours,
                schedule_type=schedule_type,
                schedule_day_of_week=schedule_day_of_week,
                retention_hours=retention_hours,
                detail_mode=detail_mode,
                enabled=enabled
            )
            session.add(scheduled_summary)
            session.commit()
            session.refresh(scheduled_summary)
            return scheduled_summary

    def get_all_scheduled_summaries(self) -> List[ScheduledSummary]:
        """Get all scheduled summaries.

        Returns:
            List of all ScheduledSummary objects
        """
        with self.get_session() as session:
            return (
                session.query(ScheduledSummary)
                .options(
                    joinedload(ScheduledSummary.source_group),
                    joinedload(ScheduledSummary.target_group)
                )
                .all()
            )

    def get_enabled_scheduled_summaries(self) -> List[ScheduledSummary]:
        """Get all enabled scheduled summaries.

        Returns:
            List of enabled ScheduledSummary objects
        """
        with self.get_session() as session:
            return (
                session.query(ScheduledSummary)
                .filter(ScheduledSummary.enabled == True)
                .options(
                    joinedload(ScheduledSummary.source_group),
                    joinedload(ScheduledSummary.target_group)
                )
                .all()
            )

    def get_scheduled_summary_by_id(self, schedule_id: int) -> Optional[ScheduledSummary]:
        """Get a scheduled summary by ID.

        Args:
            schedule_id: Database ID of the scheduled summary

        Returns:
            ScheduledSummary object or None if not found
        """
        with self.get_session() as session:
            return (
                session.query(ScheduledSummary)
                .filter(ScheduledSummary.id == schedule_id)
                .options(
                    joinedload(ScheduledSummary.source_group),
                    joinedload(ScheduledSummary.target_group)
                )
                .first()
            )

    def get_scheduled_summary_by_name(self, name: str) -> Optional[ScheduledSummary]:
        """Get a scheduled summary by name.

        Args:
            name: Name of the scheduled summary

        Returns:
            ScheduledSummary object or None if not found
        """
        with self.get_session() as session:
            return (
                session.query(ScheduledSummary)
                .filter(ScheduledSummary.name == name)
                .options(
                    joinedload(ScheduledSummary.source_group),
                    joinedload(ScheduledSummary.target_group)
                )
                .first()
            )

    def update_scheduled_summary(
        self,
        schedule_id: int,
        **kwargs
    ) -> Optional[ScheduledSummary]:
        """Update a scheduled summary.

        Args:
            schedule_id: Database ID of the scheduled summary
            **kwargs: Fields to update (schedule_times, timezone, enabled, etc.)

        Returns:
            Updated ScheduledSummary object or None if not found
        """
        with self.get_session() as session:
            scheduled_summary = session.query(ScheduledSummary).filter(
                ScheduledSummary.id == schedule_id
            ).first()

            if not scheduled_summary:
                return None

            # Update allowed fields
            for key, value in kwargs.items():
                if hasattr(scheduled_summary, key):
                    setattr(scheduled_summary, key, value)

            scheduled_summary.updated_at = datetime.utcnow()
            session.commit()
            session.refresh(scheduled_summary)
            return scheduled_summary

    def update_scheduled_summary_last_run(
        self,
        schedule_id: int,
        last_run: datetime
    ) -> None:
        """Update the last_run timestamp for a scheduled summary.

        Args:
            schedule_id: Database ID of the scheduled summary
            last_run: Timestamp of the last execution
        """
        with self.get_session() as session:
            scheduled_summary = session.query(ScheduledSummary).filter(
                ScheduledSummary.id == schedule_id
            ).first()

            if scheduled_summary:
                scheduled_summary.last_run = last_run
                session.commit()

    def delete_scheduled_summary(self, schedule_id: int) -> bool:
        """Delete a scheduled summary.

        Args:
            schedule_id: Database ID of the scheduled summary

        Returns:
            True if deleted, False if not found
        """
        with self.get_session() as session:
            scheduled_summary = session.query(ScheduledSummary).filter(
                ScheduledSummary.id == schedule_id
            ).first()

            if not scheduled_summary:
                return False

            session.delete(scheduled_summary)
            session.commit()
            return True

    # Message operations (temporary storage for summarization)
    def store_message(
        self,
        signal_timestamp: int,
        sender_uuid: str,
        group_id: str,
        content: str = None
    ) -> Tuple[Message, bool]:
        """Store a message, returning (message, is_new).

        Uses upsert to handle duplicates gracefully.

        Args:
            signal_timestamp: Signal's timestamp_ms
            sender_uuid: Sender's UUID (for deduplication only)
            group_id: Signal group ID
            content: Message text content

        Returns:
            Tuple of (Message object, True if new / False if existing)
        """
        with self.get_session() as session:
            # Check if message already exists
            existing = session.query(Message).filter(
                Message.signal_timestamp == signal_timestamp,
                Message.sender_uuid == sender_uuid,
                Message.group_id == group_id
            ).first()

            if existing:
                return existing, False

            # Create new message
            message = Message(
                signal_timestamp=signal_timestamp,
                sender_uuid=sender_uuid,
                group_id=group_id,
                content=content
            )
            session.add(message)
            session.commit()
            session.refresh(message)
            return message, True

    def store_messages_batch(self, messages: List[Dict[str, Any]]) -> int:
        """Store multiple messages in batch, returning count of new messages.

        Args:
            messages: List of dicts with keys: signal_timestamp, sender_uuid, group_id, content

        Returns:
            Number of new messages stored (excludes duplicates)
        """
        new_count = 0
        with self.get_session() as session:
            for msg_data in messages:
                # Check for existing
                existing = session.query(Message).filter(
                    Message.signal_timestamp == msg_data['signal_timestamp'],
                    Message.sender_uuid == msg_data['sender_uuid'],
                    Message.group_id == msg_data['group_id']
                ).first()

                if not existing:
                    message = Message(
                        signal_timestamp=msg_data['signal_timestamp'],
                        sender_uuid=msg_data['sender_uuid'],
                        group_id=msg_data['group_id'],
                        content=msg_data.get('content')
                    )
                    session.add(message)
                    new_count += 1

            session.commit()
        return new_count

    def get_messages_for_group(
        self,
        group_id: str,
        since: datetime = None,
        until: datetime = None
    ) -> List[Message]:
        """Get messages for a group within optional time window.

        Args:
            group_id: Signal group ID
            since: Start of time window (inclusive)
            until: End of time window (inclusive)

        Returns:
            List of Message objects ordered by timestamp
        """
        with self.get_session() as session:
            query = session.query(Message).filter(Message.group_id == group_id)

            if since:
                # Convert datetime to milliseconds timestamp
                since_ms = int(since.timestamp() * 1000)
                query = query.filter(Message.signal_timestamp >= since_ms)

            if until:
                until_ms = int(until.timestamp() * 1000)
                query = query.filter(Message.signal_timestamp <= until_ms)

            return query.order_by(Message.signal_timestamp.asc()).all()

    def get_messages_with_reactions_for_group(
        self,
        group_id: str,
        since: datetime = None,
        until: datetime = None
    ) -> List[Dict[str, Any]]:
        """Get messages for a group with their reaction data.

        Returns messages annotated with reaction counts and emojis for AI context.

        Args:
            group_id: Signal group ID
            since: Start of time window (inclusive)
            until: End of time window (inclusive)

        Returns:
            List of dicts with:
            - content: str (message text)
            - reaction_count: int (total reactions)
            - emojis: list[str] (individual emojis, e.g., ["👍", "👍", "❤️"])
        """
        with self.get_session() as session:
            query = session.query(Message).filter(
                Message.group_id == group_id
            ).options(joinedload(Message.reactions))

            if since:
                since_ms = int(since.timestamp() * 1000)
                query = query.filter(Message.signal_timestamp >= since_ms)

            if until:
                until_ms = int(until.timestamp() * 1000)
                query = query.filter(Message.signal_timestamp <= until_ms)

            messages = query.order_by(Message.signal_timestamp.asc()).all()

            result = []
            for msg in messages:
                if not msg.content:
                    continue

                # Collect all reaction emojis for this message
                emojis = [r.emoji for r in msg.reactions]

                result.append({
                    'content': msg.content,
                    'reaction_count': len(emojis),
                    'emojis': emojis
                })

            return result

    def get_message_count_by_group(self) -> Dict[str, int]:
        """Get pending message counts per group.

        Returns:
            Dict mapping group_id to message count
        """
        with self.get_session() as session:
            results = session.query(
                Message.group_id,
                func.count(Message.id).label('count')
            ).group_by(Message.group_id).all()

            return {row.group_id: row.count for row in results}

    def get_pending_stats(self) -> Dict[str, Any]:
        """Get statistics about pending messages (for UI).

        Returns:
            Dict with total_messages, messages_by_group, oldest_message, newest_message
        """
        with self.get_session() as session:
            total = session.query(func.count(Message.id)).scalar() or 0

            by_group = session.query(
                Message.group_id,
                func.count(Message.id).label('count')
            ).group_by(Message.group_id).all()

            oldest = session.query(func.min(Message.received_at)).scalar()
            newest = session.query(func.max(Message.received_at)).scalar()

            return {
                'total_messages': total,
                'messages_by_group': {row.group_id: row.count for row in by_group},
                'oldest_message': oldest,
                'newest_message': newest
            }

    def purge_messages_for_group(self, group_id: str, before: datetime) -> int:
        """Delete messages for a group older than specified time.

        Args:
            group_id: Signal group ID
            before: Delete messages with received_at before this time

        Returns:
            Number of messages deleted
        """
        with self.get_session() as session:
            count = session.query(Message).filter(
                Message.group_id == group_id,
                Message.received_at < before
            ).delete(synchronize_session=False)
            session.commit()
            return count

    def purge_messages_older_than(self, hours: int) -> int:
        """Delete all messages older than specified hours.

        Args:
            hours: Delete messages older than this many hours

        Returns:
            Number of messages deleted
        """
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        with self.get_session() as session:
            count = session.query(Message).filter(
                Message.received_at < cutoff
            ).delete(synchronize_session=False)
            session.commit()
            return count

    def purge_all_messages(self) -> int:
        """Delete all messages (for testing/reset).

        Returns:
            Number of messages deleted
        """
        with self.get_session() as session:
            count = session.query(Message).delete(synchronize_session=False)
            session.commit()
            return count

    def purge_all_messages_for_group(self, group_id: str) -> int:
        """Delete all messages for a specific group.

        Args:
            group_id: Signal group ID

        Returns:
            Number of messages deleted
        """
        with self.get_session() as session:
            count = session.query(Message).filter(
                Message.group_id == group_id
            ).delete(synchronize_session=False)
            session.commit()
            return count

    # Reaction operations
    def store_reaction(
        self,
        message_id: int,
        emoji: str,
        reactor_uuid: str,
        timestamp: int
    ) -> Tuple[Reaction, bool]:
        """Store a reaction, returning (reaction, is_new).

        Args:
            message_id: Database ID of the message
            emoji: Reaction emoji
            reactor_uuid: UUID of reactor (for deduplication)
            timestamp: Signal's timestamp_ms

        Returns:
            Tuple of (Reaction object, True if new / False if existing)
        """
        with self.get_session() as session:
            existing = session.query(Reaction).filter(
                Reaction.message_id == message_id,
                Reaction.reactor_uuid == reactor_uuid
            ).first()

            if existing:
                # Update emoji if different
                if existing.emoji != emoji:
                    existing.emoji = emoji
                    existing.timestamp = timestamp
                    session.commit()
                    session.refresh(existing)
                return existing, False

            reaction = Reaction(
                message_id=message_id,
                emoji=emoji,
                reactor_uuid=reactor_uuid,
                timestamp=timestamp
            )
            session.add(reaction)
            session.commit()
            session.refresh(reaction)
            return reaction, True

    def get_reaction_stats_for_group(self, group_id: str) -> Dict[str, Any]:
        """Get reaction statistics for a group's messages.

        Args:
            group_id: Signal group ID

        Returns:
            Dict with total_reactions, messages_with_reactions, emoji_counts
        """
        with self.get_session() as session:
            # Get messages for this group
            message_ids = session.query(Message.id).filter(
                Message.group_id == group_id
            ).subquery()

            total = session.query(func.count(Reaction.id)).filter(
                Reaction.message_id.in_(message_ids)
            ).scalar() or 0

            messages_with = session.query(
                func.count(func.distinct(Reaction.message_id))
            ).filter(
                Reaction.message_id.in_(message_ids)
            ).scalar() or 0

            emoji_counts = session.query(
                Reaction.emoji,
                func.count(Reaction.id).label('count')
            ).filter(
                Reaction.message_id.in_(message_ids)
            ).group_by(Reaction.emoji).all()

            return {
                'total_reactions': total,
                'messages_with_reactions': messages_with,
                'emoji_counts': {row.emoji: row.count for row in emoji_counts}
            }

    # SummaryRun operations
    def create_summary_run(
        self,
        schedule_id: int,
        status: str = "pending"
    ) -> SummaryRun:
        """Create a new summary run record.

        Args:
            schedule_id: Database ID of the scheduled summary
            status: Initial status (default: pending)

        Returns:
            Created SummaryRun object
        """
        with self.get_session() as session:
            run = SummaryRun(
                schedule_id=schedule_id,
                status=status,
                started_at=datetime.utcnow()
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            return run

    def update_summary_run(
        self,
        run_id: int,
        **kwargs
    ) -> Optional[SummaryRun]:
        """Update a summary run record.

        Args:
            run_id: Database ID of the summary run
            **kwargs: Fields to update

        Returns:
            Updated SummaryRun or None if not found
        """
        with self.get_session() as session:
            run = session.query(SummaryRun).filter(SummaryRun.id == run_id).first()

            if not run:
                return None

            for key, value in kwargs.items():
                if hasattr(run, key):
                    setattr(run, key, value)

            session.commit()
            session.refresh(run)
            return run

    def complete_summary_run(
        self,
        run_id: int,
        message_count: int,
        oldest_message_time: datetime,
        newest_message_time: datetime,
        summary_text: str
    ) -> Optional[SummaryRun]:
        """Mark a summary run as completed with results.

        Args:
            run_id: Database ID of the summary run
            message_count: Number of messages summarized
            oldest_message_time: Start of time window
            newest_message_time: End of time window
            summary_text: Generated summary text

        Returns:
            Updated SummaryRun or None if not found
        """
        return self.update_summary_run(
            run_id,
            status="completed",
            completed_at=datetime.utcnow(),
            message_count=message_count,
            oldest_message_time=oldest_message_time,
            newest_message_time=newest_message_time,
            summary_text=summary_text
        )

    def fail_summary_run(self, run_id: int, error_message: str) -> Optional[SummaryRun]:
        """Mark a summary run as failed.

        Args:
            run_id: Database ID of the summary run
            error_message: Error details

        Returns:
            Updated SummaryRun or None if not found
        """
        return self.update_summary_run(
            run_id,
            status="failed",
            completed_at=datetime.utcnow(),
            error_message=error_message
        )

    def get_summary_runs_for_schedule(
        self,
        schedule_id: int,
        limit: int = 10
    ) -> List[SummaryRun]:
        """Get recent summary runs for a schedule.

        Args:
            schedule_id: Database ID of the scheduled summary
            limit: Maximum number of runs to return

        Returns:
            List of SummaryRun objects, most recent first
        """
        with self.get_session() as session:
            return session.query(SummaryRun).filter(
                SummaryRun.schedule_id == schedule_id
            ).order_by(SummaryRun.started_at.desc()).limit(limit).all()

    def get_recent_summary_runs(self, limit: int = 20) -> List[SummaryRun]:
        """Get recent summary runs across all schedules.

        Args:
            limit: Maximum number of runs to return

        Returns:
            List of SummaryRun objects with schedule info, most recent first
        """
        with self.get_session() as session:
            return session.query(SummaryRun).options(
                joinedload(SummaryRun.schedule)
            ).order_by(SummaryRun.started_at.desc()).limit(limit).all()

    def purge_old_summary_runs(self) -> int:
        """Purge summary runs that exceed their retention period.

        Each SummaryRun has its own retention_hours field.

        Returns:
            Number of summary runs deleted
        """
        with self.get_session() as session:
            now = datetime.utcnow()
            # Find runs where completed_at + retention_hours < now
            runs_to_delete = session.query(SummaryRun).filter(
                SummaryRun.completed_at.isnot(None)
            ).all()

            count = 0
            for run in runs_to_delete:
                cutoff = run.completed_at + timedelta(hours=run.retention_hours)
                if now > cutoff:
                    session.delete(run)
                    count += 1

            session.commit()
            return count

    # DM Conversation operations
    def store_dm_message(
        self,
        user_id: str,
        role: str,
        content: str,
        signal_timestamp: int = None
    ) -> DMConversation:
        """Store a DM conversation message.

        Args:
            user_id: User's Signal UUID or phone number
            role: "user" or "assistant"
            content: Message content
            signal_timestamp: Signal's timestamp_ms (for user messages)

        Returns:
            Created DMConversation object
        """
        with self.get_session() as session:
            dm = DMConversation(
                user_id=user_id,
                role=role,
                content=content,
                signal_timestamp=signal_timestamp
            )
            session.add(dm)
            session.commit()
            session.refresh(dm)
            return dm

    def get_dm_history(self, user_id: str) -> List[DMConversation]:
        """Get all DM history for a user.

        Ollama client handles truncation via max_input_tokens if needed.

        Args:
            user_id: User's Signal UUID or phone number

        Returns:
            List of DMConversation objects ordered by created_at
        """
        with self.get_session() as session:
            return session.query(DMConversation).filter(
                DMConversation.user_id == user_id
            ).order_by(DMConversation.created_at.asc()).all()

    def get_dm_message_count(self, user_id: str) -> int:
        """Get count of DM messages for a user.

        Args:
            user_id: User's Signal UUID or phone number

        Returns:
            Number of messages in conversation
        """
        with self.get_session() as session:
            return session.query(func.count(DMConversation.id)).filter(
                DMConversation.user_id == user_id
            ).scalar() or 0

    def purge_dm_messages(self, user_id: str) -> int:
        """Purge all DM messages for a user.

        Used after !summary or !!!purge commands.

        Args:
            user_id: User's Signal UUID or phone number

        Returns:
            Number of messages deleted
        """
        with self.get_session() as session:
            count = session.query(DMConversation).filter(
                DMConversation.user_id == user_id
            ).delete(synchronize_session=False)
            session.commit()
            return count

    def purge_expired_dm_messages(self, before: datetime) -> int:
        """Purge DM messages older than specified time.

        Args:
            before: Delete messages created before this time

        Returns:
            Number of messages deleted
        """
        with self.get_session() as session:
            count = session.query(DMConversation).filter(
                DMConversation.created_at < before
            ).delete(synchronize_session=False)
            session.commit()
            return count

    def get_dm_stats(self) -> Dict[str, Any]:
        """Get statistics about DM conversations.

        Returns:
            Dict with total_messages, unique_users, oldest_message, newest_message
        """
        with self.get_session() as session:
            total = session.query(func.count(DMConversation.id)).scalar() or 0
            users = session.query(
                func.count(func.distinct(DMConversation.user_id))
            ).scalar() or 0
            oldest = session.query(func.min(DMConversation.created_at)).scalar()
            newest = session.query(func.max(DMConversation.created_at)).scalar()

            return {
                'total_messages': total,
                'unique_users': users,
                'oldest_message': oldest,
                'newest_message': newest
            }

    def get_dm_retention_hours(self, user_id: str) -> int:
        """Get user's DM retention preference.

        Args:
            user_id: User's Signal UUID or phone number

        Returns:
            Retention hours (default 48 if not set)
        """
        with self.get_session() as session:
            settings = session.query(DMSettings).filter(
                DMSettings.user_id == user_id
            ).first()
            return settings.retention_hours if settings else 48

    def set_dm_retention_hours(self, user_id: str, hours: int) -> None:
        """Set user's DM retention preference.

        Args:
            user_id: User's Signal UUID or phone number
            hours: Retention hours (1-168)
        """
        with self.get_session() as session:
            settings = session.query(DMSettings).filter(
                DMSettings.user_id == user_id
            ).first()

            if settings:
                settings.retention_hours = hours
                settings.updated_at = datetime.utcnow()
            else:
                settings = DMSettings(
                    user_id=user_id,
                    retention_hours=hours
                )
                session.add(settings)

            session.commit()

    def get_all_dm_retention_settings(self) -> Dict[str, int]:
        """Get all user retention settings for the purge job.

        Returns:
            Dict mapping user_id -> retention_hours
        """
        with self.get_session() as session:
            settings = session.query(DMSettings).all()
            return {s.user_id: s.retention_hours for s in settings}

    def get_dm_user_ids(self) -> List[str]:
        """Get all unique user IDs with DM messages.

        Returns:
            List of user IDs (UUIDs or phone numbers)
        """
        with self.get_session() as session:
            results = session.query(
                func.distinct(DMConversation.user_id)
            ).all()
            return [r[0] for r in results]

    def purge_dm_messages_for_user(self, user_id: str, before: datetime) -> int:
        """Purge DM messages for a specific user older than cutoff.

        Args:
            user_id: User's Signal UUID or phone number
            before: Delete messages older than this datetime

        Returns:
            Number of messages deleted
        """
        with self.get_session() as session:
            count = session.query(DMConversation).filter(
                DMConversation.user_id == user_id,
                DMConversation.created_at < before
            ).delete()
            session.commit()
            return count

    # Group Settings operations

    def get_group_retention_hours(self, group_id: str) -> int:
        """Get group's retention preference.

        Args:
            group_id: Signal group ID

        Returns:
            Retention hours (default 48 if not set)
        """
        with self.get_session() as session:
            settings = session.query(GroupSettings).filter(
                GroupSettings.group_id == group_id
            ).first()
            return settings.retention_hours if settings else 48

    def set_group_retention_hours(self, group_id: str, hours: int, source: str = "command") -> None:
        """Set group's retention preference.

        Args:
            group_id: Signal group ID
            hours: Retention hours (1-168)
            source: Source of setting ("signal" or "command")
        """
        with self.get_session() as session:
            settings = session.query(GroupSettings).filter(
                GroupSettings.group_id == group_id
            ).first()

            if settings:
                settings.retention_hours = hours
                settings.source = source
                settings.updated_at = datetime.utcnow()
            else:
                settings = GroupSettings(
                    group_id=group_id,
                    retention_hours=hours,
                    source=source
                )
                session.add(settings)

            session.commit()

    def get_group_settings(self, group_id: str) -> Optional[GroupSettings]:
        """Get full group settings record.

        Args:
            group_id: Signal group ID

        Returns:
            GroupSettings object or None if not set
        """
        with self.get_session() as session:
            settings = session.query(GroupSettings).filter(
                GroupSettings.group_id == group_id
            ).first()
            if settings:
                session.expunge(settings)  # Detach cleanly to avoid DetachedInstanceError
            return settings

    def get_all_group_retention_settings(self) -> Dict[str, int]:
        """Get all group retention settings for the purge job.

        Returns:
            Dict mapping group_id -> retention_hours
        """
        with self.get_session() as session:
            settings = session.query(GroupSettings).all()
            return {s.group_id: s.retention_hours for s in settings}

    def get_group_power_mode(self, group_id: str) -> str:
        """Get the power mode for a group (who can run config commands).

        Args:
            group_id: Signal group ID

        Returns:
            Power mode string: "admins" (default) or "everyone"
        """
        with self.get_session() as session:
            settings = session.query(GroupSettings).filter(
                GroupSettings.group_id == group_id
            ).first()
            if settings:
                return settings.power_mode
            return "admins"  # Default

    def set_group_power_mode(self, group_id: str, mode: str) -> None:
        """Set the power mode for a group.

        Args:
            group_id: Signal group ID
            mode: "admins" or "everyone"
        """
        if mode not in ("admins", "everyone"):
            raise ValueError(f"Invalid power mode: {mode}. Must be 'admins' or 'everyone'")

        with self.get_session() as session:
            settings = session.query(GroupSettings).filter(
                GroupSettings.group_id == group_id
            ).first()

            if settings:
                settings.power_mode = mode
                settings.updated_at = datetime.utcnow()
            else:
                # Create new settings with default retention
                settings = GroupSettings(
                    group_id=group_id,
                    retention_hours=48,
                    source="signal",
                    power_mode=mode
                )
                session.add(settings)

            session.commit()

    def get_group_purge_on_summary(self, group_id: str) -> bool:
        """Get whether to purge messages after on-demand summary.

        Args:
            group_id: Signal group ID

        Returns:
            True if messages should be purged after !summary (default), False otherwise
        """
        with self.get_session() as session:
            settings = session.query(GroupSettings).filter(
                GroupSettings.group_id == group_id
            ).first()
            if settings:
                return getattr(settings, 'purge_on_summary', True)
            return True  # Default: purge after summary

    def set_group_purge_on_summary(self, group_id: str, purge: bool) -> None:
        """Set whether to purge messages after on-demand summary.

        Args:
            group_id: Signal group ID
            purge: True to purge after !summary, False to keep until retention expires
        """
        with self.get_session() as session:
            settings = session.query(GroupSettings).filter(
                GroupSettings.group_id == group_id
            ).first()

            if settings:
                settings.purge_on_summary = purge
                settings.updated_at = datetime.utcnow()
            else:
                # Create new settings with default retention
                settings = GroupSettings(
                    group_id=group_id,
                    retention_hours=48,
                    source="signal",
                    power_mode="admins",
                    purge_on_summary=purge
                )
                session.add(settings)

            session.commit()

    # User Opt-Out operations

    def is_user_opted_out(self, group_id: str, sender_uuid: str) -> bool:
        """Check if a user has opted out of message collection for a group.

        Args:
            group_id: Signal group ID
            sender_uuid: User's Signal UUID

        Returns:
            True if user has opted out (messages NOT collected), False otherwise
        """
        with self.get_session() as session:
            opt_out = session.query(UserOptOut).filter(
                UserOptOut.group_id == group_id,
                UserOptOut.sender_uuid == sender_uuid
            ).first()

            if opt_out:
                return opt_out.opted_out
            return False  # Default: opted in (messages collected)

    def set_user_opt_out(self, group_id: str, sender_uuid: str, opted_out: bool) -> None:
        """Set a user's opt-out status for a group.

        Args:
            group_id: Signal group ID
            sender_uuid: User's Signal UUID
            opted_out: True to opt out (stop collecting), False to opt in
        """
        with self.get_session() as session:
            existing = session.query(UserOptOut).filter(
                UserOptOut.group_id == group_id,
                UserOptOut.sender_uuid == sender_uuid
            ).first()

            if existing:
                existing.opted_out = opted_out
                existing.updated_at = datetime.utcnow()
            else:
                opt_out_record = UserOptOut(
                    group_id=group_id,
                    sender_uuid=sender_uuid,
                    opted_out=opted_out
                )
                session.add(opt_out_record)

            session.commit()

    def delete_user_messages_in_group(self, group_id: str, sender_uuid: str) -> int:
        """Delete all messages from a specific user in a specific group.

        Used when user opts out to immediately purge their data.

        Args:
            group_id: Signal group ID
            sender_uuid: User's Signal UUID

        Returns:
            Number of messages deleted
        """
        with self.get_session() as session:
            count = session.query(Message).filter(
                Message.group_id == group_id,
                Message.sender_uuid == sender_uuid
            ).delete(synchronize_session=False)
            session.commit()
            return count

    # Schedule command operations

    def get_schedules_for_group(self, group_id: str) -> List[ScheduledSummary]:
        """Get all schedules where this group is the source.

        Args:
            group_id: Signal group ID (not database ID)

        Returns:
            List of ScheduledSummary objects for this source group
        """
        with self.get_session() as session:
            group = session.query(Group).filter_by(group_id=group_id).first()
            if not group:
                return []
            return (
                session.query(ScheduledSummary)
                .filter_by(source_group_id=group.id)
                .options(
                    joinedload(ScheduledSummary.source_group),
                    joinedload(ScheduledSummary.target_group)
                )
                .all()
            )

    def find_group_by_name_or_hash(self, identifier: str) -> Tuple[Optional[Group], Optional[str]]:
        """Find group by name or hash identifier.

        Args:
            identifier: Group name or hash (e.g., "#A3F2")

        Returns:
            Tuple of (Group or None, error_message or None)
        """
        from src.utils.message_utils import anonymize_group_id

        with self.get_session() as session:
            groups = session.query(Group).all()

            # Check if identifier is a hash (starts with #)
            if identifier.startswith('#'):
                identifier_upper = identifier.upper()
                for g in groups:
                    if anonymize_group_id(g.group_id) == identifier_upper:
                        return (g, None)
                return (None, f"No group found with hash {identifier}")

            # Find by name
            matches = [g for g in groups if g.name == identifier]
            if len(matches) == 0:
                return (None, f"No group found named '{identifier}'")
            if len(matches) > 1:
                hashes = [anonymize_group_id(g.group_id) for g in matches]
                return (None, f"Multiple groups named '{identifier}'. Use hash: {', '.join(hashes)}")
            return (matches[0], None)
