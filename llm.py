"""Shared LLM completion layer for scorer, cover letter and CV tailoring.

Primary provider is Groq (llama-3.3-70b-versatile, free tier). When Groq hits
its rate limit (or keeps failing to connect), the call falls back to Anthropic
Claude Haiku, so a busy run doesn't stall or bury jobs. The fallback only
activates when ANTHROPIC_API_KEY is configured; without it, behaviour is the
old one (retry, then give up).

All three consumers use the same entry point:

    text = await chat(prompt, max_tokens=512, temperature=0.2)

Raises LLMUnavailable when every provider failed, so callers can distinguish
"model said something" from "no model was reachable".
"""
import asyncio
import time
from functools import lru_cache
from typing import NamedTuple, Optional

from groq import AsyncGroq, RateLimitError, APIConnectionError, APIStatusError

from config.settings import get_settings
from db.models import SessionLocal, LLMCall

GROQ_MODEL = "openai/gpt-oss-120b"
CLAUDE_FALLBACK_MODEL = "claude-haiku-4-5"

_MAX_GROQ_RETRIES = 2          # short: on rate limit we'd rather switch provider
_BASE_BACKOFF_SECONDS = 4


class LLMUnavailable(Exception):
    """No provider could complete the request (transient; retry next run)."""


class _Completion(NamedTuple):
    text: str
    served_model: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None


def _record_call(provider: str, model: str, context: str, started: float, *,
                 completion: Optional[_Completion] = None,
                 error: Optional[Exception] = None) -> None:
    """Persist one attempt for /log. Telemetry must never break a real call,
    so any DB problem is swallowed."""
    try:
        db = SessionLocal()
        try:
            db.add(LLMCall(
                provider=provider, model=model, context=context,
                ok=error is None,
                latency_ms=int((time.monotonic() - started) * 1000),
                served_model=completion.served_model if completion else None,
                prompt_tokens=completion.prompt_tokens if completion else None,
                completion_tokens=completion.completion_tokens if completion else None,
                output_chars=len(completion.text or "") if completion else None,
                error=(f"{type(error).__name__}: {error}"[:500] if error else None),
            ))
            db.commit()
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001
        print(f"[llm] could not record call telemetry: {e}")


@lru_cache(maxsize=1)
def _groq() -> AsyncGroq:
    return AsyncGroq(api_key=get_settings().groq_api_key)


@lru_cache(maxsize=1)
def _anthropic():
    """Lazy import so the project still runs without the anthropic package
    when no fallback key is configured."""
    from anthropic import AsyncAnthropic
    return AsyncAnthropic(api_key=get_settings().anthropic_api_key)


def _fallback_enabled() -> bool:
    return bool(get_settings().anthropic_api_key)


async def _chat_groq(prompt: str, max_tokens: int, temperature: float) -> _Completion:
    resp = await _groq().chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    usage = getattr(resp, "usage", None)
    return _Completion(
        text=resp.choices[0].message.content,
        served_model=getattr(resp, "model", None),
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        completion_tokens=getattr(usage, "completion_tokens", None),
    )


async def _chat_claude(prompt: str, max_tokens: int, temperature: float) -> _Completion:
    resp = await _anthropic().messages.create(
        model=CLAUDE_FALLBACK_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = getattr(resp, "usage", None)
    return _Completion(
        text="".join(block.text for block in resp.content if block.type == "text"),
        served_model=getattr(resp, "model", None),
        prompt_tokens=getattr(usage, "input_tokens", None),
        completion_tokens=getattr(usage, "output_tokens", None),
    )


async def chat(prompt: str, max_tokens: int = 512, temperature: float = 0.2,
               context: str = "llm") -> str:
    """Complete `prompt`, preferring Groq, falling back to Claude Haiku.

    Fallback triggers on Groq rate limits and on repeated connection
    failures. Non-transient Groq errors (4xx other than 429) also try the
    fallback once before giving up, since the request itself may still be
    servable elsewhere.
    """
    last_error: Optional[Exception] = None

    for attempt in range(1, _MAX_GROQ_RETRIES + 1):
        started = time.monotonic()
        try:
            completion = await _chat_groq(prompt, max_tokens, temperature)
            _record_call("groq", GROQ_MODEL, context, started, completion=completion)
            return completion.text
        except RateLimitError as e:
            _record_call("groq", GROQ_MODEL, context, started, error=e)
            last_error = e
            print(f"[{context}] Groq rate limit hit (attempt {attempt}/{_MAX_GROQ_RETRIES})")
            if _fallback_enabled():
                break  # don't wait out the limit; switch provider now
            wait = _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
            print(f"[{context}] No fallback configured, backing off {wait}s")
            await asyncio.sleep(wait)
        except APIConnectionError as e:
            _record_call("groq", GROQ_MODEL, context, started, error=e)
            last_error = e
            wait = _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
            print(f"[{context}] Groq connection error (attempt {attempt}), retrying in {wait}s")
            await asyncio.sleep(wait)
        except APIStatusError as e:
            _record_call("groq", GROQ_MODEL, context, started, error=e)
            last_error = e
            print(f"[{context}] Groq API error {e.status_code}: {e}")
            break

    if _fallback_enabled():
        started = time.monotonic()
        try:
            print(f"[{context}] Falling back to Claude ({CLAUDE_FALLBACK_MODEL})")
            completion = await _chat_claude(prompt, max_tokens, temperature)
            _record_call("anthropic", CLAUDE_FALLBACK_MODEL, context, started,
                         completion=completion)
            return completion.text
        except Exception as e:
            _record_call("anthropic", CLAUDE_FALLBACK_MODEL, context, started, error=e)
            last_error = e
            print(f"[{context}] Claude fallback also failed: {e}")

    raise LLMUnavailable(str(last_error))
