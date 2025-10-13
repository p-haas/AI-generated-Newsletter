"""Helpers for interacting with the Gemini API (google-genai)."""

import os
from typing import Any, Optional, Union, Sequence
from functools import lru_cache

from google import genai
from google.genai import types as gtypes

from .settings import GEMINI_FLASH_MODEL, GEMINI_API_KEY

try:
    # Optional import: only used if caller passes a Pydantic schema
    from pydantic import BaseModel  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    BaseModel = object  # type: ignore


def _coerce_to_schema(schema: Any, data: Any) -> Any:
    """Coerce raw data into the provided response schema when possible.

    - If `data` is already a Pydantic BaseModel, return it unchanged.
    - If `schema` is a Pydantic model class and `data` is a dict, instantiate it.
    - Otherwise, return data unchanged.
    """
    # If data is already the right type, return it
    if hasattr(data, '__class__') and hasattr(schema, '__name__'):
        if data.__class__.__name__ == schema.__name__:
            return data
    
    # Try to instantiate the schema with the data if it's a dict
    if isinstance(data, dict):
        try:
            # Check if schema has a callable constructor (Pydantic model)
            if callable(schema) and hasattr(schema, '__fields__'):
                return schema(**data)
        except Exception as e:
            # Log but don't fail - return the dict
            print(f"⚠️ Schema coercion failed for {getattr(schema, '__name__', schema)}: {e}")
    
    return data


def _get_api_key() -> str:
    """Resolve API key with fallback order: settings → GOOGLE_API_KEY → GEMINI_API_KEY env."""
    api_key = (
        GEMINI_API_KEY or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    )
    if not api_key:
        raise RuntimeError(
            "Missing API key: define GEMINI_API_KEY in settings, "
            "or set GOOGLE_API_KEY / GEMINI_API_KEY in environment"
        )
    return api_key


@lru_cache(maxsize=1)
def get_gemini_client() -> genai.Client:
    """Create and cache a single client instance.

    - Uses API key from settings/env.
    - You can pin API version here if desired.
    """
    api_key = _get_api_key()

    # Optional: pin stable API version
    # http_opts = gtypes.HttpOptions(api_version="v1")
    # return genai.Client(api_key=api_key, http_options=http_opts)

    return genai.Client(api_key=api_key)


def call_gemini_sdk(
    prompt: Any,
    model: str = GEMINI_FLASH_MODEL,
    *,
    temperature: float = 0.1,
    max_output_tokens: Optional[int] = None,
    system_instruction: Optional[Union[str, Sequence[Any]]] = None,
    response_schema: Optional[Any] = None,  # Pydantic, Schema, or dict
    return_parsed: bool = False,
    tools: Optional[Sequence[Any]] = None,  # for function/tool calling
    safety_settings: Optional[Sequence[gtypes.SafetySetting]] = None,
    top_p: Optional[float] = None,
    top_k: Optional[int] = None,
    stop_sequences: Optional[Sequence[str]] = None,
    candidate_count: Optional[int] = None,
) -> Any:
    """Call Gemini via Google GenAI SDK with optional structured outputs & tools."""
    client = get_gemini_client()

    cfg: dict = {"temperature": temperature}
    if max_output_tokens is not None:
        cfg["max_output_tokens"] = max_output_tokens
    if top_p is not None:
        cfg["top_p"] = top_p
    if top_k is not None:
        cfg["top_k"] = top_k
    if stop_sequences:
        cfg["stop_sequences"] = list(stop_sequences)
    if candidate_count is not None:
        cfg["candidate_count"] = candidate_count
    if system_instruction is not None:
        cfg["system_instruction"] = system_instruction
    if tools:
        cfg["tools"] = list(tools)
    if safety_settings:
        cfg["safety_settings"] = list(safety_settings)
    if response_schema is not None:
        cfg["response_mime_type"] = "application/json"
        cfg["response_schema"] = response_schema

    config = gtypes.GenerateContentConfig(**cfg)

    try:
        resp = client.models.generate_content(
            model=model,
            contents=prompt,  # str | list[str|Part|Content] is fine
            config=config,
        )

        # If caller wants parsed and we requested structured output, return it.
        if return_parsed and (response_schema is not None):
            if getattr(resp, "parsed", None) is not None:
                return _coerce_to_schema(response_schema, resp.parsed)
            else:
                # Fallback: try to parse the text response if parsed is None
                if hasattr(resp, "text") and resp.text:
                    try:
                        import json
                        raw = json.loads(resp.text.strip())
                        return _coerce_to_schema(response_schema, raw)
                    except (json.JSONDecodeError, AttributeError):
                        # If JSON parsing fails, raise an error to indicate the failure
                        raise RuntimeError("Failed to parse structured response - response.parsed is None or missing and text is not valid JSON")

        # Prefer the SDK's text aggregator
        if hasattr(resp, "text") and resp.text:
            return resp.text.strip()

        return resp.candidates  # fallback: expose raw candidates

    except Exception as e:
        raise RuntimeError(f"Gemini SDK call failed: {e}") from e
