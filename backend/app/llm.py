from __future__ import annotations
import asyncio, json
from typing import Type, TypeVar
from openai import AsyncAzureOpenAI, RateLimitError, APIError
from pydantic import BaseModel, ValidationError
from .settings import settings
from .logging import log

T = TypeVar("T", bound=BaseModel)

class LLMParseError(Exception): ...
class LLMError(Exception): ...

class LLM:
    def __init__(self) -> None:
        self.client = AsyncAzureOpenAI(
            api_key=settings.azure_openai_api_key,
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
        )
        self.deployment = settings.azure_openai_deployment_name
        self._cost_tokens = 0

    @property
    def cost_tokens(self) -> int: return self._cost_tokens

    async def _chat_raw(self, messages: list[dict], *, json_mode: bool = False,
                        temperature: float = 0.0, max_tokens: int = 2000) -> str:
        backoff = 1.0
        for attempt in range(5):
            try:
                resp = await self.client.chat.completions.create(
                    model=self.deployment,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"} if json_mode else None,
                )
                if resp.usage: self._cost_tokens += resp.usage.total_tokens
                return resp.choices[0].message.content or ""
            except RateLimitError as e:
                retry_after = getattr(e, "retry_after", None) or backoff
                log.warning("llm.rate_limited", retry_after=retry_after)
                await asyncio.sleep(retry_after); backoff *= 2
            except APIError as e:
                if attempt == 4: raise LLMError(str(e)) from e
                await asyncio.sleep(backoff); backoff *= 2
        raise LLMError("exhausted retries")

    async def chat(self, messages: list[dict], **kw) -> str:
        return await self._chat_raw(messages, **kw)

    async def vision_chat(self, *, system: str, user_text: str,
                          image_b64_png: str, max_tokens: int = 4000,
                          temperature: float = 0.0) -> str:
        backoff = 1.0
        for attempt in range(5):
            try:
                resp = await self.client.chat.completions.create(
                    model=self.deployment,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": [
                            {"type": "text", "text": user_text},
                            {"type": "image_url",
                             "image_url": {"url": f"data:image/png;base64,{image_b64_png}"}},
                        ]},
                    ],
                )
                if resp.usage: self._cost_tokens += resp.usage.total_tokens
                return resp.choices[0].message.content or ""
            except RateLimitError as e:
                retry_after = getattr(e, "retry_after", None) or backoff
                log.warning("llm.vision.rate_limited", retry_after=retry_after)
                await asyncio.sleep(retry_after); backoff *= 2
            except APIError as e:
                if attempt == 4: raise LLMError(str(e)) from e
                await asyncio.sleep(backoff); backoff *= 2
        raise LLMError("vision_chat exhausted retries")

    async def vision_batch(self, *, pages: list[tuple[int, str]],
                           system: str, max_tokens: int = 12000,
                           temperature: float = 0.0) -> str:
        """Send multiple page images in one API call.
        pages = [(page_no, b64_png), ...]. Returns raw response string (caller parses JSON).
        """
        content: list[dict] = []
        for page_no, b64 in pages:
            content.append({"type": "text", "text": f"Page {page_no}:"})
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"}})
        backoff = 1.0
        for attempt in range(5):
            try:
                resp = await self.client.chat.completions.create(
                    model=self.deployment,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": content},
                    ],
                )
                if resp.usage: self._cost_tokens += resp.usage.total_tokens
                return resp.choices[0].message.content or ""
            except RateLimitError as e:
                retry_after = getattr(e, "retry_after", None) or backoff
                log.warning("llm.vision_batch.rate_limited", retry_after=retry_after)
                await asyncio.sleep(retry_after); backoff *= 2
            except APIError as e:
                if attempt == 4: raise LLMError(str(e)) from e
                await asyncio.sleep(backoff); backoff *= 2
        raise LLMError("vision_batch exhausted retries")

    async def structured(self, *, messages: list[dict], schema: Type[T],
                         temperature: float = 0.0, max_tokens: int = 2000) -> T:
        schema_hint = json.dumps(schema.model_json_schema())
        sys = {"role": "system", "content":
               f"Return ONLY valid JSON matching this schema:\n{schema_hint}"}
        msgs = [sys, *messages]
        raw = await self._chat_raw(msgs, json_mode=True,
                                   temperature=temperature, max_tokens=max_tokens)
        try:
            return schema.model_validate_json(raw)
        except (ValidationError, ValueError) as e:
            err = str(e)[:500]
            msgs2 = [*msgs, {"role": "assistant", "content": raw},
                     {"role": "user", "content":
                      f"That output failed validation: {err}. Return ONLY valid JSON matching the schema."}]
            raw2 = await self._chat_raw(msgs2, json_mode=True,
                                        temperature=temperature, max_tokens=max_tokens)
            try:
                return schema.model_validate_json(raw2)
            except (ValidationError, ValueError) as e2:
                raise LLMParseError(f"structured output failed twice: {e2}") from e2

llm = LLM()
