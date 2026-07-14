"""Claude API access. All prompting for the pipeline funnels through these
helpers: plain text, schema-constrained JSON (structured outputs), and a
vision variant used for reference-video format extraction."""

import json
from typing import Any

import anthropic

from ..config import require, settings


def _client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=require("anthropic"))


THINKING = {"type": "adaptive"}


async def complete_text(system: str, user: str, max_tokens: int = 8192) -> str:
    client = _client()
    response = await client.messages.create(
        model=settings.claude_model,
        max_tokens=max_tokens,
        thinking=THINKING,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in response.content if b.type == "text")


async def complete_json(system: str, user: str, schema: dict, max_tokens: int = 16000) -> Any:
    """Schema-constrained JSON via structured outputs."""
    client = _client()
    response = await client.messages.create(
        model=settings.claude_model,
        max_tokens=max_tokens,
        thinking=THINKING,
        system=system,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": user}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


async def complete_json_with_images(
    system: str, user: str, images: list[bytes], schema: dict, media_type: str = "image/jpeg", max_tokens: int = 16000
) -> Any:
    """Vision + structured outputs — used for reference-video frame analysis."""
    import base64

    client = _client()
    content: list[dict] = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": base64.standard_b64encode(img).decode()},
        }
        for img in images
    ]
    content.append({"type": "text", "text": user})
    response = await client.messages.create(
        model=settings.claude_model,
        max_tokens=max_tokens,
        thinking=THINKING,
        system=system,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": content}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)
