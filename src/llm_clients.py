import os
import time
from typing import Any, Dict

import requests


class LLMGenerationError(RuntimeError):
    pass


class BaseLLMClient:
    """
    Abstract interface for LLM clients.
    Allows swapping providers without touching evaluation code.
    """

    provider_name = "LLM"

    def __init__(
        self,
        *,
        timeout_s: float = 60.0,
        max_retries: int = 3,
        retry_backoff_s: float = 1.0,
    ):
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.retry_backoff_s = retry_backoff_s

    def generate(self, prompt: str) -> Dict[str, Any]:
        raise NotImplementedError

    def _http_error_message(self, response: requests.Response) -> str:
        try:
            details = response.json()
        except ValueError:
            details = response.text[:500]
        return f"{self.provider_name} API request failed with status {response.status_code}: {details}"

    def _post_json(
        self,
        *,
        endpoint: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout_s,
                )
                if not response.ok:
                    raise LLMGenerationError(self._http_error_message(response))
                return response.json()
            except (requests.RequestException, LLMGenerationError, ValueError) as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
                time.sleep(self.retry_backoff_s * (2 ** (attempt - 1)))

        raise LLMGenerationError(
            f"{self.provider_name} generation failed after {self.max_retries} attempts: {last_error}"
        )


class OpenAIClient(BaseLLMClient):
    """
    Minimal OpenAI REST client.

    Uses the chat completions endpoint.
    Designed intentionally lightweight so the repo has minimal dependencies.
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        timeout_s: float = 60.0,
        max_retries: int = 3,
        retry_backoff_s: float = 1.0,
    ):
        super().__init__(
            timeout_s=timeout_s,
            max_retries=max_retries,
            retry_backoff_s=retry_backoff_s,
        )
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")

        self.model = model
        self.endpoint = "https://api.openai.com/v1/chat/completions"
        self.provider_name = "OpenAI"

    def _extract_answer_text(self, data: Dict[str, Any]) -> str:
        try:
            answer_text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMGenerationError(
                f"OpenAI response was missing the assistant message content for model '{self.model}'."
            ) from exc

        if not isinstance(answer_text, str) or not answer_text.strip():
            raise LLMGenerationError(f"OpenAI returned an empty assistant message for model '{self.model}'.")

        return answer_text

    def generate(self, prompt: str) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a careful clinical decision-support assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }

        data = self._post_json(endpoint=self.endpoint, headers=headers, payload=payload)
        answer_text = self._extract_answer_text(data)

        return {
            "answer_text": answer_text,
            "raw_response": data,
            **completion_metadata("openai", data),
        }


class AnthropicClient(BaseLLMClient):
    """
    Minimal Anthropic REST client using the Messages API.
    """

    def __init__(
        self,
        model: str = "claude-3-5-sonnet-latest",
        timeout_s: float = 60.0,
        max_retries: int = 3,
        retry_backoff_s: float = 1.0,
        max_tokens: int = 1024,
    ):
        super().__init__(
            timeout_s=timeout_s,
            max_retries=max_retries,
            retry_backoff_s=retry_backoff_s,
        )
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")

        self.model = model
        self.max_tokens = max_tokens
        self.endpoint = "https://api.anthropic.com/v1/messages"
        self.provider_name = "Anthropic"

    def _extract_answer_text(self, data: Dict[str, Any]) -> str:
        try:
            content = data["content"]
        except KeyError as exc:
            raise LLMGenerationError(
                f"Anthropic response was missing the content list for model '{self.model}'."
            ) from exc

        if not isinstance(content, list):
            raise LLMGenerationError(f"Anthropic returned a non-list content payload for model '{self.model}'.")

        text_blocks = [block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"]
        answer_text = "".join(text_blocks).strip()
        if not answer_text:
            raise LLMGenerationError(f"Anthropic returned an empty assistant message for model '{self.model}'.")
        return answer_text

    def generate(self, prompt: str) -> Dict[str, Any]:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": 0.2,
            "system": "You are a careful clinical decision-support assistant.",
            "messages": [{"role": "user", "content": prompt}],
        }

        data = self._post_json(endpoint=self.endpoint, headers=headers, payload=payload)
        answer_text = self._extract_answer_text(data)

        return {
            "answer_text": answer_text,
            "raw_response": data,
            **completion_metadata("anthropic", data),
        }


class GeminiClient(BaseLLMClient):
    """
    Minimal Gemini REST client using the generateContent endpoint.
    """

    def __init__(
        self,
        model: str = "gemini-1.5-pro",
        timeout_s: float = 60.0,
        max_retries: int = 3,
        retry_backoff_s: float = 1.0,
    ):
        super().__init__(
            timeout_s=timeout_s,
            max_retries=max_retries,
            retry_backoff_s=retry_backoff_s,
        )
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY environment variable not set")

        self.model = model
        self.endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            f"?key={self.api_key}"
        )
        self.provider_name = "Gemini"

    def _extract_answer_text(self, data: Dict[str, Any]) -> str:
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMGenerationError(
                f"Gemini response was missing text parts for model '{self.model}'."
            ) from exc

        if not isinstance(parts, list):
            raise LLMGenerationError(f"Gemini returned a non-list parts payload for model '{self.model}'.")

        answer_text = "".join(
            part.get("text", "")
            for part in parts
            if isinstance(part, dict) and isinstance(part.get("text", ""), str)
        ).strip()
        if not answer_text:
            raise LLMGenerationError(f"Gemini returned an empty assistant message for model '{self.model}'.")
        return answer_text

    def generate(self, prompt: str) -> Dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
        }
        payload = {
            "systemInstruction": {
                "parts": [{"text": "You are a careful clinical decision-support assistant."}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {"temperature": 0.2},
        }

        data = self._post_json(endpoint=self.endpoint, headers=headers, payload=payload)
        answer_text = self._extract_answer_text(data)

        return {
            "answer_text": answer_text,
            "raw_response": data,
            **completion_metadata("gemini", data),
        }


class MockClient(BaseLLMClient):
    """
    Used when running tests without API access.
    Produces deterministic dummy outputs.
    """

    def __init__(self):
        super().__init__()

    def generate(self, prompt: str) -> Dict[str, Any]:
        dummy_answer = """
Recommendation:
Insufficient information to provide a definitive recommendation.

Rationale:
- The provided context is limited. [CTX1]

Uncertainty & Escalation:
Further clinical evaluation is recommended.

Do-not-do:
- Do not initiate treatment without clinician review.
"""

        return {
            "answer_text": dummy_answer.strip(),
            "raw_response": {"mock": True},
            "generation_status": "complete",
            "finish_reason": "mock",
        }


def completion_metadata(provider: str, data: Dict[str, Any]) -> Dict[str, str]:
    """Normalize terminal status; unknown termination is never presumed complete."""
    try:
        if provider == "openai":
            reason = data["choices"][0].get("finish_reason")
            complete = reason == "stop"
        elif provider == "anthropic":
            reason = data.get("stop_reason")
            complete = reason in {"end_turn", "stop_sequence"}
        elif provider == "gemini":
            reason = data["candidates"][0].get("finishReason")
            complete = reason == "STOP"
        elif provider == "mock" and data == {"mock": True}:
            reason, complete = "mock", True
        else:
            raise ValueError(f"Unsupported provider or mock payload: {provider}")
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Malformed {provider} completion payload") from exc
    return {"generation_status": "complete" if complete else "incomplete",
            "finish_reason": str(reason or "unknown")}


def validate_generation_payload(row: Dict[str, Any]) -> Dict[str, str]:
    """Bind cached/scored text and normalized status to the retained response payload."""
    provider = row.get("provider", "")
    data = row.get("raw_response")
    if not isinstance(data, dict):
        raise ValueError("Missing or malformed raw_response")
    metadata = completion_metadata(provider, data)
    if provider == "mock":
        text = MockClient().generate("")["answer_text"]
    else:
        cls = {"openai": OpenAIClient, "anthropic": AnthropicClient, "gemini": GeminiClient}[provider]
        client = cls.__new__(cls)  # Pure extraction; never initialize credentials or perform I/O.
        client.model = str(row.get("model_id", "unknown"))
        try:
            text = client._extract_answer_text(data)
        except LLMGenerationError as exc:
            raise ValueError(f"Invalid raw_response for {row.get('case_id')}: {exc}") from exc
    if not isinstance(row.get("answer_text"), str) or row["answer_text"] != text:
        raise ValueError(f"answer_text contradicts raw_response for {row.get('case_id')}")
    for key, value in metadata.items():
        if key in row and row[key] != value:
            raise ValueError(f"{key} contradicts raw_response for {row.get('case_id')}")
    return metadata
