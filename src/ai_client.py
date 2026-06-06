"""
Thin OpenAI wrapper with:
  - disk caching (diskcache) so identical prompts never hit the API twice
  - automatic cost logging to the CRM
  - retry on transient failures (tenacity)
"""

import hashlib
import json
import logging
from typing import Optional

import diskcache
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import (
    OPENAI_API_KEY,
    MODEL_DEFAULT,
    MODEL_QUALITY,
    CACHE_DIR,
)
from src.crm.database import log_cost

log = logging.getLogger(__name__)

_client = OpenAI(api_key=OPENAI_API_KEY)
_cache = diskcache.Cache(str(CACHE_DIR))


def _cache_key(model: str, messages: list, **kwargs) -> str:
    raw = json.dumps({"model": model, "messages": messages, **kwargs}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def chat(
    messages: list[dict],
    model: str = MODEL_DEFAULT,
    max_tokens: int = 300,
    temperature: float = 0.3,
    operation: str = "generic",
    use_cache: bool = True,
) -> str:
    """
    Call OpenAI chat completion with disk caching.

    Returns the assistant message string.
    """
    key = _cache_key(model, messages, max_tokens=max_tokens, temperature=temperature)

    if use_cache and key in _cache:
        log.debug("Cache HIT for operation=%s", operation)
        log_cost(operation, model, 0, 0, cached=True)
        return _cache[key]

    log.debug("Cache MISS — calling %s for operation=%s", model, operation)
    response = _client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    content = response.choices[0].message.content.strip()

    # Log cost
    usage = response.usage
    log_cost(operation, model, usage.prompt_tokens, usage.completion_tokens)

    if use_cache:
        _cache[key] = content

    return content


def score_prompt(system: str, user: str, **kwargs) -> str:
    """Convenience wrapper — always uses cheap model for scoring."""
    return chat(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        model=MODEL_DEFAULT,
        max_tokens=150,
        operation="score_lead",
        **kwargs,
    )


def draft_email(system: str, user: str, high_quality: bool = False) -> str:
    """Draft an outreach email. Uses gpt-4o only if high_quality=True."""
    model = MODEL_QUALITY if high_quality else MODEL_DEFAULT
    return chat(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        model=model,
        max_tokens=400,
        temperature=0.6,
        operation="draft_email",
        use_cache=False,   # emails should be unique
    )
