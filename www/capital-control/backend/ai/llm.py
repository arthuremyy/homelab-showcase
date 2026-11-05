"""
Client LLM unifié — Claude (API Anthropic directe) avec fallback Gemini.

Priorité : ANTHROPIC_API_KEY défini → Claude (ANTHROPIC_MODEL, défaut Sonnet 5).
Sinon, ou si Claude échoue après retries → Gemini 2.5 Flash (GEMINI_API_KEY).
Toutes les réponses sont demandées en JSON.
"""
import asyncio
import json
import logging

import httpx

from config import settings

logger = logging.getLogger("capital.llm")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models"
    "/gemini-2.5-flash:generateContent"
)

RETRYABLE = {429, 500, 502, 503, 529}


def parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    start, end = text.find("{"), text.rfind("}") + 1
    if start >= 0 and end > start:
        return json.loads(text[start:end])
    raise ValueError(f"Pas de JSON dans la réponse : {text[:300]}")


async def _anthropic(prompt: str, timeout: float, retries: int = 3) -> str:
    """Appel direct à l'API Messages Anthropic.
    Pas de `temperature` (Sonnet 5 rejette les valeurs non-défaut) — le thinking
    adaptatif est activé par défaut, rien à configurer.
    """
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY manquante.")
    last_exc = None
    for attempt in range(retries):
        if attempt > 0:
            await asyncio.sleep(5 * attempt)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    ANTHROPIC_URL,
                    headers={
                        "x-api-key": settings.anthropic_api_key,
                        "anthropic-version": ANTHROPIC_VERSION,
                        "content-type": "application/json",
                    },
                    json={
                        "model": settings.anthropic_model,
                        "max_tokens": 16000,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                if resp.status_code in RETRYABLE:
                    last_exc = RuntimeError(f"Anthropic HTTP {resp.status_code}: {resp.text[:200]}")
                    logger.warning(str(last_exc))
                    continue
                resp.raise_for_status()
                data = resp.json()
                if data.get("stop_reason") == "refusal":
                    raise RuntimeError(f"Anthropic refusal: {data.get('stop_details')}")
                text_parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
                if not text_parts:
                    raise RuntimeError("Anthropic: aucun bloc texte dans la réponse")
                return "".join(text_parts)
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last_exc = e
            logger.warning(f"Anthropic réseau: {e}")
    raise last_exc or RuntimeError("Anthropic: échec inconnu")


async def _gemini(prompt: str, timeout: float, retries: int = 3) -> str:
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY manquante.")
    last_exc = None
    for attempt in range(retries):
        if attempt > 0:
            await asyncio.sleep(5 * attempt)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    GEMINI_URL,
                    headers={"x-goog-api-key": settings.gemini_api_key},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "temperature": 0.2,
                            "maxOutputTokens": 8192,
                            "responseMimeType": "application/json",
                        },
                    },
                )
                if resp.status_code in RETRYABLE:
                    last_exc = RuntimeError(f"Gemini HTTP {resp.status_code}")
                    logger.warning(str(last_exc))
                    continue
                if resp.status_code >= 400:
                    # Pas de raise_for_status : son message reprendrait l'URL complète.
                    raise RuntimeError(f"Gemini HTTP {resp.status_code}")
                return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last_exc = e
    raise last_exc or RuntimeError("Gemini: échec inconnu")


async def ask_json(prompt: str, timeout: float = 120.0) -> tuple[dict, str]:
    """Retourne (json_parsé, nom_du_modèle). Claude d'abord si configuré, sinon Gemini."""
    if settings.anthropic_api_key:
        try:
            text = await _anthropic(prompt, timeout)
            return parse_json(text), settings.anthropic_model
        except Exception as e:
            logger.error(f"Anthropic KO ({e}) — fallback Gemini")
    text = await _gemini(prompt, timeout)
    return parse_json(text), "gemini-2.5-flash"
