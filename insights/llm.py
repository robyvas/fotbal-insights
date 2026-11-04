"""The only file that talks to a model. To change provider, reimplement `complete`.

Responses are cached on disk, so rerunning does not spend free-tier quota.
"""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request

from .config import LLM_CACHE_DIR, LLM_MODEL, ROOT

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
RETRYABLE = {429, 500, 503}
MAX_ATTEMPTS = 6


class LLMError(RuntimeError):
    """This one answer failed. The card can fall back to the plain verified fact."""


class LLMConfigError(RuntimeError):
    """Wrong key or model. Every call would fail, so stop instead of silently writing no AI text."""


def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    env_file = ROOT / ".env"
    if not key and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        raise LLMError("GEMINI_API_KEY not found in the environment or .env")
    return key


def _retry_delay(body: str, attempt: int) -> float:
    match = re.search(r'"retryDelay":\s*"(\d+)', body)
    return float(match.group(1)) + 1 if match else min(5 * 2**attempt, 60)


def _call(system: str, prompt: str, schema: dict) -> str:
    payload = json.dumps({
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "responseMimeType": "application/json",
            "responseSchema": schema,
        },
    }).encode()
    request = urllib.request.Request(
        API_URL.format(model=LLM_MODEL), data=payload,
        headers={"Content-Type": "application/json", "x-goog-api-key": _api_key()},
    )
    for attempt in range(MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.load(response)
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as error:
            body = error.read().decode(errors="replace")
            if error.code in (401, 403, 404):
                raise LLMConfigError(f"HTTP {error.code}: {body[:300]}") from error
            if error.code not in RETRYABLE or attempt == MAX_ATTEMPTS - 1:
                raise LLMError(f"HTTP {error.code}: {body[:300]}") from error
            time.sleep(_retry_delay(body, attempt))
        except (KeyError, IndexError) as error:
            # A blocked or empty answer. The caller falls back to the plain verified fact.
            raise LLMError(f"unexpected response shape: {error!r}") from error
        except OSError as error:  # URLError, timeouts and dropped connections
            if attempt == MAX_ATTEMPTS - 1:
                raise LLMError(f"network error: {error}") from error
            time.sleep(min(5 * 2**attempt, 60))
    raise LLMError("no attempts made")


def complete(system: str, prompt: str, schema: dict) -> dict:
    """Return the model's JSON answer, from the cache when the same request was made before."""
    LLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(json.dumps([LLM_MODEL, system, prompt, schema]).encode()).hexdigest()
    path = LLM_CACHE_DIR / f"{digest}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    text = _call(system, prompt, schema)
    try:
        answer = json.loads(text)
    except json.JSONDecodeError as error:
        raise LLMError(f"model returned invalid JSON: {error}") from error
    path.write_text(json.dumps(answer, ensure_ascii=False), encoding="utf-8")
    return answer
