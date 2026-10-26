from typing import Protocol

import httpx

from vaultroute_rag.generation.schemas import ModelResult, ModelUsage


class ModelProviderError(RuntimeError):
    """Raised when an external model provider cannot return an answer."""


class TextModelProvider(Protocol):
    provider_name: str
    model_name: str

    @property
    def available(self) -> bool: ...

    async def generate(self, system_prompt: str, user_prompt: str) -> ModelResult: ...


class GroqChatProvider:
    provider_name = "groq"

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        model_name: str,
        timeout_seconds: float,
        max_output_tokens: int,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._base_url = base_url.rstrip("/")
        self.model_name = model_name
        self._timeout = timeout_seconds
        self._max_output_tokens = max_output_tokens

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    async def generate(self, system_prompt: str, user_prompt: str) -> ModelResult:
        if not self.available:
            raise ModelProviderError("Groq API key is not configured")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self.model_name,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.1,
                        "max_tokens": self._max_output_tokens,
                        "n": 1,
                    },
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelProviderError("Groq generation request failed") from exc

        usage = data.get("usage") or {}
        return ModelResult(
            text=str(data["choices"][0]["message"]["content"]).strip(),
            provider=self.provider_name,
            model=str(data.get("model") or self.model_name),
            usage=ModelUsage(
                input_tokens=int(usage.get("prompt_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or 0),
                total_tokens=int(usage.get("total_tokens") or 0),
            ),
        )


class OpenAIResponsesProvider:
    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        model_name: str,
        timeout_seconds: float,
        max_output_tokens: int,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._base_url = base_url.rstrip("/")
        self.model_name = model_name
        self._timeout = timeout_seconds
        self._max_output_tokens = max_output_tokens

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    async def generate(self, system_prompt: str, user_prompt: str) -> ModelResult:
        if not self.available:
            raise ModelProviderError("OpenAI API key is not configured")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/responses",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self.model_name,
                        "instructions": system_prompt,
                        "input": user_prompt,
                        "max_output_tokens": self._max_output_tokens,
                        "store": False,
                    },
                )
                response.raise_for_status()
                data = response.json()
                text = self._output_text(data)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise ModelProviderError("OpenAI generation request failed") from exc

        usage = data.get("usage") or {}
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        return ModelResult(
            text=text,
            provider=self.provider_name,
            model=str(data.get("model") or self.model_name),
            usage=ModelUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=int(usage.get("total_tokens") or input_tokens + output_tokens),
            ),
        )

    @staticmethod
    def _output_text(data: dict) -> str:
        texts: list[str] = []
        for item in data.get("output") or []:
            if item.get("type") != "message":
                continue
            for content in item.get("content") or []:
                if content.get("type") == "output_text" and content.get("text"):
                    texts.append(str(content["text"]))
        text = "\n".join(texts).strip()
        if not text:
            raise ValueError("OpenAI response contained no output text")
        return text
