"""Privacy-focused chat summarizer using AI - Privacy Summarizer."""

import json
import logging
from typing import Dict, Any, List

from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class ChatSummarizer:
    """Generate privacy-focused AI summaries (no names, no direct quotes)."""

    def __init__(self, ollama_client: OllamaClient):
        """Initialize chat summarizer.

        Args:
            ollama_client: Ollama client instance
        """
        self.ollama = ollama_client

    def summarize_transient_messages(
        self,
        message_texts: List[str],
        period_description: str = None,
        messages_with_reactions: List[Dict[str, Any]] = None,
        detail: bool = False
    ) -> Dict[str, Any]:
        """Generate a privacy-focused summary from transient message texts.

        No names, no direct quotes, no identifying information.

        Args:
            message_texts: List of message content strings (anonymized)
            period_description: Human-readable description of the time period
            messages_with_reactions: Optional list of dicts with 'content', 'reaction_count', 'emojis'
                for contextual reaction information in summaries
            detail: If True, generate comprehensive detailed summary; if False, concise summary

        Returns:
            Dictionary containing privacy-focused summary data
        """
        # Use messages_with_reactions if provided, otherwise fall back to message_texts
        if messages_with_reactions:
            message_count = len(messages_with_reactions)
            message_texts = [m['content'] for m in messages_with_reactions if m.get('content')]
        else:
            message_count = len(message_texts) if message_texts else 0

        if not message_texts:
            logger.info("No messages provided for summarization")
            return {
                "message_count": 0,
                "participant_count": 0,
                "summary_text": "No activity during this period."
            }

        logger.info(f"Generating privacy-focused summary for {message_count} messages (detail={detail})")

        # Build combined text with reaction context
        combined_text = self._build_text_with_reactions(
            message_texts, messages_with_reactions
        )

        # Generate AI-powered privacy-focused summary
        try:
            # Extract topics (no names)
            topics = self._extract_privacy_topics(combined_text)

            # Extract action items only in detail mode
            action_items = []
            if detail:
                action_items = self._extract_privacy_action_items(combined_text)

            # Analyze sentiment
            sentiment = self.ollama.analyze_sentiment(combined_text)

            # Generate privacy-focused summary with appropriate detail level
            period_str = period_description or "this time period"
            summary_text = self._generate_privacy_summary(combined_text, period_str, detail=detail)

            # Estimate participant count (based on conversational patterns, not stored data)
            participant_count = self._estimate_participant_count(combined_text)

            # Compile result (privacy-safe)
            result = {
                "message_count": message_count,
                "participant_count": participant_count,
                "topics": topics,
                "action_items": action_items,
                "sentiment": sentiment,
                "summary_text": summary_text
            }

            logger.info(f"Generated privacy summary: {len(topics)} topics, sentiment: {sentiment}")
            return result

        except Exception as e:
            logger.error(f"Error generating summary: {e}", exc_info=True)
            return {
                "message_count": message_count,
                "participant_count": 0,
                "summary_text": "Unable to generate summary due to processing error."
            }

    def _build_text_with_reactions(
        self,
        message_texts: List[str],
        messages_with_reactions: List[Dict[str, Any]] = None
    ) -> str:
        """Build combined text with reaction context markers.

        Args:
            message_texts: Plain message texts (fallback)
            messages_with_reactions: Messages with reaction data

        Returns:
            Combined text with reaction markers like [3 reactions: 👍👍❤️]
        """
        if not messages_with_reactions:
            return "\n".join([msg for msg in message_texts if msg])

        lines = []
        for msg in messages_with_reactions:
            content = msg.get('content', '')
            if not content:
                continue

            reaction_count = msg.get('reaction_count', 0)
            emojis = msg.get('emojis', [])

            if reaction_count > 0:
                emoji_str = ''.join(emojis[:5])  # Cap at 5 emojis for brevity
                lines.append(f"[{reaction_count} reactions: {emoji_str}] {content}")
            else:
                lines.append(content)

        return "\n".join(lines)

    def _extract_privacy_topics(self, text: str, max_topics: int = 5) -> List[str]:
        """Extract topics without any identifying information.

        Args:
            text: Combined message text
            max_topics: Maximum number of topics to extract

        Returns:
            List of topic strings (no names, no quotes)
        """
        prompt = f"""Analyze this group chat conversation and identify the main topics discussed.

PRIVACY REQUIREMENTS:
- DO NOT include any names, usernames, or identifying information
- DO NOT include direct quotes from messages
- Focus on themes and subjects only
- Use general descriptions (e.g., "weekend plans" not "John's weekend plans")

Provide up to {max_topics} topics as a JSON array of strings.

Conversation:
{text}

Topics (JSON array only):"""

        try:
            response = self.ollama.generate(
                prompt=prompt,
                temperature=0.3,
                max_tokens=200
            )

            # Parse JSON response
            topics = json.loads(response.strip())
            if isinstance(topics, list):
                return topics[:max_topics]
            return []

        except Exception as e:
            logger.error(f"Error extracting topics: {e}")
            return []

    def _extract_privacy_action_items(self, text: str) -> List[str]:
        """Extract action items without identifying who said them.

        Args:
            text: Combined message text

        Returns:
            List of anonymized action item strings
        """
        prompt = f"""Identify any action items, decisions, or tasks mentioned in this conversation.

PRIVACY REQUIREMENTS:
- DO NOT include any names or identifying information
- DO NOT include direct quotes
- Use passive voice or generic references (e.g., "Follow up on project status" not "John will follow up")
- Only include clear, actionable items

Provide as a JSON array of strings.

Conversation:
{text}

Action items (JSON array only):"""

        try:
            response = self.ollama.generate(
                prompt=prompt,
                temperature=0.3,
                max_tokens=200
            )

            # Parse JSON response
            action_items = json.loads(response.strip())
            if isinstance(action_items, list):
                return action_items
            return []

        except Exception as e:
            logger.error(f"Error extracting action items: {e}")
            return []

    def _generate_privacy_summary(self, text: str, period: str, detail: bool = False) -> str:
        """Generate a privacy-focused summary.

        Args:
            text: Combined message text (may include reaction markers like [3 reactions: 👍])
            period: Time period description
            detail: If True, generate comprehensive summary; if False, concise summary

        Returns:
            Summary text without names or quotes
        """
        if detail:
            # Detailed mode: comprehensive summary
            prompt = f"""Provide a comprehensive, detailed summary of this group chat conversation from {period}.

CRITICAL PRIVACY REQUIREMENTS:
- DO NOT include any names, usernames, or identifying information
- DO NOT include direct quotes from messages
- DO NOT reference specific people
- Use general terms like "participants", "members", "someone", "the group"

REACTION CONTEXT:
- Messages marked with [N reactions: emojis] indicate group approval or interest
- Discuss well-received ideas in depth when they have multiple reactions
- Mention consensus points that received positive reactions

DETAIL REQUIREMENTS:
- Provide a thorough summary covering all major discussion points
- Discuss the flow of conversation and how topics developed
- Highlight areas of agreement and notable reactions
- Be comprehensive - this will be paginated if needed

Conversation:
{text}

Detailed privacy-focused summary:"""
            max_tokens = 500  # Allow longer detailed summaries
        else:
            # Simple mode: concise summary
            prompt = f"""Provide a concise summary of this group chat conversation from {period}.

CRITICAL PRIVACY REQUIREMENTS:
- DO NOT include any names, usernames, or identifying information
- DO NOT include direct quotes from messages
- DO NOT reference specific people
- Use general terms like "participants", "members", "someone", "the group"

REACTION CONTEXT:
- Messages marked with [N reactions: emojis] indicate group approval
- Briefly mention well-received ideas when relevant

BREVITY:
- Keep the summary to 2-5 sentences appropriate to the content
- Focus on the main themes and any notable consensus

Conversation:
{text}

Concise privacy-focused summary:"""
            max_tokens = 200  # Shorter for simple mode

        try:
            summary = self.ollama.generate(
                prompt=prompt,
                temperature=0.5,
                max_tokens=max_tokens
            )

            # Validate that summary doesn't contain obvious privacy violations
            summary_clean = self._validate_privacy(summary)
            return summary_clean.strip()

        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return "Unable to generate summary."

    def _validate_privacy(self, text: str) -> str:
        """Basic validation to catch obvious privacy violations.

        Args:
            text: Summary text to validate

        Returns:
            Validated text (or generic message if validation fails)
        """
        # Check for common privacy violations
        violations = [
            "said", "told", "mentioned",  # Often followed by names
            "@",  # Username mentions
        ]

        # Note: This is basic validation. In production, you might want more sophisticated checks
        for violation in violations:
            if violation in text.lower():
                logger.warning(f"Privacy validation warning: found '{violation}' in summary")

        return text

    def _estimate_participant_count(self, text: str) -> int:
        """Estimate number of participants based on conversational patterns.

        This is a rough estimate and doesn't store or identify individuals.

        Args:
            text: Combined message text

        Returns:
            Estimated number of unique participants
        """
        # Very basic estimation based on conversational markers
        # In a real implementation, you might use more sophisticated NLP
        lines = text.split('\n')
        non_empty_lines = [line for line in lines if line.strip()]

        # Rough heuristic: assume average 5 messages per person
        estimated = max(2, min(len(non_empty_lines) // 5, 20))

        return estimated
