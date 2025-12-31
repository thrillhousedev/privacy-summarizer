"""Ollama API client for local AI model inference."""

import logging
import requests
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class OllamaException(Exception):
    """Exception raised for Ollama API errors."""
    pass


class OllamaClient:
    """Client for interacting with Ollama API."""

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "dolphin-mistral:7b",
        max_input_tokens: int = 28000
    ):
        """Initialize Ollama client.

        Args:
            host: Ollama API host URL
            model: Model name to use for inference
            max_input_tokens: Maximum input tokens to send (to avoid overloading)
        """
        self.host = host.rstrip("/")
        self.model = model
        self.api_url = f"{self.host}/api"
        self.max_input_tokens = max_input_tokens

    def _estimate_tokens(self, text: str) -> int:
        """Estimate the number of tokens in text.

        Uses a simple heuristic: 1 token ≈ 4 characters on average.

        Args:
            text: Text to estimate

        Returns:
            Estimated token count
        """
        return len(text) // 4

    def _truncate_to_tokens(self, text: str, max_tokens: int = None) -> str:
        """Truncate text to fit within token limit.

        Args:
            text: Text to truncate
            max_tokens: Maximum tokens (defaults to self.max_input_tokens)

        Returns:
            Truncated text
        """
        if max_tokens is None:
            max_tokens = self.max_input_tokens

        estimated_tokens = self._estimate_tokens(text)

        if estimated_tokens <= max_tokens:
            return text

        # Truncate to character limit (tokens * 4)
        char_limit = max_tokens * 4
        truncated = text[:char_limit]

        logger.warning(
            f"Text truncated from ~{estimated_tokens} tokens to {max_tokens} tokens "
            f"to avoid overloading Ollama"
        )

        return truncated

    def is_available(self) -> bool:
        """Check if Ollama is available and responding.

        Returns:
            True if Ollama is available, False otherwise
        """
        try:
            response = requests.get(f"{self.host}/", timeout=5)
            return response.status_code == 200
        except requests.RequestException as e:
            logger.warning(f"Ollama not available: {e}")
            return False

    def list_models(self) -> List[Dict[str, Any]]:
        """List available models.

        Returns:
            List of model information dictionaries

        Raises:
            OllamaException: If API request fails
        """
        try:
            response = requests.get(f"{self.api_url}/tags", timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("models", [])
        except requests.RequestException as e:
            raise OllamaException(f"Failed to list models: {e}")

    def pull_model(self, model: str = None) -> bool:
        """Pull/download a model if not already available.

        Args:
            model: Model name to pull (defaults to instance model)

        Returns:
            True if successful, False otherwise
        """
        model = model or self.model

        try:
            logger.info(f"Pulling model: {model}")
            response = requests.post(
                f"{self.api_url}/pull",
                json={"name": model},
                timeout=300  # 5 minutes for model download
            )
            response.raise_for_status()
            logger.info(f"Model {model} pulled successfully")
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to pull model {model}: {e}")
            return False

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> str:
        """Generate text using the model.

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt for context
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens to generate

        Returns:
            Generated text response

        Raises:
            OllamaException: If generation fails
        """
        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                }
            }

            if system_prompt:
                payload["system"] = system_prompt

            if max_tokens:
                payload["options"]["num_predict"] = max_tokens

            logger.debug(f"Generating with model {self.model}...")

            response = requests.post(
                f"{self.api_url}/generate",
                json=payload,
                timeout=120
            )
            response.raise_for_status()

            data = response.json()
            return data.get("response", "")

        except requests.RequestException as e:
            raise OllamaException(f"Generation failed: {e}")

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> str:
        """Chat with the model using conversation history.

        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Returns:
            Generated response

        Raises:
            OllamaException: If chat fails
        """
        try:
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                }
            }

            if max_tokens:
                payload["options"]["num_predict"] = max_tokens

            logger.debug(f"Chatting with model {self.model}...")

            response = requests.post(
                f"{self.api_url}/chat",
                json=payload,
                timeout=240
            )
            response.raise_for_status()

            data = response.json()
            message = data.get("message", {})
            return message.get("content", "")

        except requests.RequestException as e:
            raise OllamaException(f"Chat failed: {e}")

    def summarize_text(
        self,
        text: str,
        max_length: int = 500,
        focus: Optional[str] = None
    ) -> str:
        """Summarize a given text.

        Args:
            text: Text to summarize
            max_length: Maximum length of summary in words
            focus: Optional focus area for the summary

        Returns:
            Summary text
        """
        # Truncate text to avoid overloading
        truncated_text = self._truncate_to_tokens(text)

        focus_instruction = f" Focus particularly on {focus}." if focus else ""

        prompt = f"""Summarize the following text concisely in no more than {max_length} words.{focus_instruction}

Text:
{truncated_text}

Summary:"""

        return self.generate(
            prompt=prompt,
            temperature=0.3,  # Lower temperature for more focused summaries
            max_tokens=max_length * 2  # Rough token estimate
        )

    def analyze_sentiment(self, text: str) -> str:
        """Analyze the sentiment of text.

        Args:
            text: Text to analyze

        Returns:
            Sentiment classification (positive, negative, neutral, mixed)
        """
        # Truncate text to avoid overloading
        truncated_text = self._truncate_to_tokens(text)

        prompt = f"""Analyze the overall sentiment of the following text. Respond with only one word: positive, negative, neutral, or mixed.

Text:
{truncated_text}

Sentiment:"""

        sentiment = self.generate(
            prompt=prompt,
            temperature=0.1,  # Very low temperature for consistent classification
            max_tokens=10
        ).strip().lower()

        # Validate response
        valid_sentiments = ["positive", "negative", "neutral", "mixed"]
        for valid in valid_sentiments:
            if valid in sentiment:
                return valid

        return "neutral"  # Default if unclear

    def extract_topics(self, text: str, max_topics: int = 5) -> List[str]:
        """Extract main topics from text.

        Args:
            text: Text to analyze
            max_topics: Maximum number of topics to extract

        Returns:
            List of topic strings
        """
        # Truncate text to avoid overloading
        truncated_text = self._truncate_to_tokens(text)

        prompt = f"""Extract the top {max_topics} main topics or themes from the following text.
List only the topics, one per line, without numbering or explanation.

Text:
{truncated_text}

Topics:"""

        response = self.generate(
            prompt=prompt,
            temperature=0.3,
            max_tokens=200
        )

        # Parse topics from response
        topics = [
            line.strip().lstrip("- •*0123456789.)").strip()
            for line in response.split("\n")
            if line.strip()
        ]

        return [t for t in topics if t][:max_topics]

    def extract_action_items(self, text: str) -> List[str]:
        """Extract action items or decisions from text.

        Args:
            text: Text to analyze

        Returns:
            List of action items
        """
        # Truncate text to avoid overloading
        truncated_text = self._truncate_to_tokens(text)

        prompt = f"""Extract any action items, tasks, decisions, or commitments mentioned in the following text.
List them one per line without numbering. If none are found, respond with "None".

Text:
{truncated_text}

Action Items:"""

        response = self.generate(
            prompt=prompt,
            temperature=0.3,
            max_tokens=300
        )

        if "none" in response.lower() and len(response) < 20:
            return []

        # Parse action items from response
        items = [
            line.strip().lstrip("- •*0123456789.)").strip()
            for line in response.split("\n")
            if line.strip()
        ]

        return [item for item in items if item and len(item) > 5]

    def compare_messages_for_contradictions(
        self,
        messages_by_group: Dict[str, List[str]]
    ) -> List[Dict[str, Any]]:
        """Compare messages across groups to detect contradictions.

        Args:
            messages_by_group: Dictionary mapping group names to lists of messages

        Returns:
            List of contradiction dictionaries with:
                - groups: List of group names involved
                - contradiction: Description of the contradiction
                - excerpts: Relevant message excerpts
                - confidence: Confidence score (0.0 to 1.0)
        """
        if len(messages_by_group) < 2:
            return []

        # Build comparison text
        comparison_parts = []
        for group_name, messages in messages_by_group.items():
            messages_text = "\n".join(messages[:10])  # Limit to first 10 messages per group
            comparison_parts.append(f"--- {group_name} ---\n{messages_text}")

        comparison_text = "\n\n".join(comparison_parts)

        # Truncate to avoid overloading
        truncated_text = self._truncate_to_tokens(comparison_text, max_tokens=6000)

        prompt = f"""Analyze the following messages from different group chats sent by the same person on the same day.

Identify any CLEAR and SIGNIFICANT contradictions where the person:
- States conflicting facts or positions
- Makes incompatible claims or promises
- Presents different intentions or plans
- Tells different stories about the same events

Only flag contradictions that are obvious and meaningful. Ignore:
- Minor differences in tone or enthusiasm
- Natural variation in how topics are discussed
- Different levels of detail

For each contradiction found, provide:
1. Groups involved (comma-separated)
2. What the contradiction is (1-2 sentences)
3. Brief excerpts showing the contradiction
4. Confidence level (HIGH, MEDIUM, LOW)

If NO significant contradictions are found, respond with "NONE".

Messages by group:
{truncated_text}

Analysis:"""

        response = self.generate(
            prompt=prompt,
            temperature=0.2,  # Low temperature for consistent analysis
            max_tokens=800
        )

        # Parse response
        if "NONE" in response.upper() or len(response.strip()) < 20:
            return []

        contradictions = []

        # Simple parsing - look for patterns
        # This is a heuristic parser; the AI response may vary
        lines = response.split("\n")
        current_contradiction = {}

        for line in lines:
            line = line.strip()
            if not line:
                if current_contradiction:
                    # Finalize current contradiction
                    if "contradiction" in current_contradiction:
                        contradictions.append(current_contradiction)
                    current_contradiction = {}
                continue

            # Try to parse structured data
            lower_line = line.lower()

            if "groups:" in lower_line or "group involved" in lower_line:
                groups_str = line.split(":", 1)[1].strip()
                current_contradiction["groups"] = [g.strip() for g in groups_str.split(",")]
            elif "contradiction:" in lower_line or "what:" in lower_line:
                current_contradiction["contradiction"] = line.split(":", 1)[1].strip()
            elif "excerpt" in lower_line or "quote" in lower_line:
                current_contradiction["excerpts"] = line.split(":", 1)[1].strip()
            elif "confidence:" in lower_line:
                confidence_str = line.split(":", 1)[1].strip().upper()
                if "HIGH" in confidence_str:
                    current_contradiction["confidence"] = 0.9
                elif "MEDIUM" in confidence_str:
                    current_contradiction["confidence"] = 0.7
                else:
                    current_contradiction["confidence"] = 0.5
            else:
                # If we don't have a contradiction yet, this might be it
                if not current_contradiction.get("contradiction") and len(line) > 20:
                    current_contradiction["contradiction"] = line

        # Add last contradiction if exists
        if current_contradiction and "contradiction" in current_contradiction:
            contradictions.append(current_contradiction)

        # Filter to high-confidence only (>0.7)
        return [c for c in contradictions if c.get("confidence", 0) >= 0.7]
