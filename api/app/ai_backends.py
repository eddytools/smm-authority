"""OpenAI, Gemini and OpenAI-compatible models (Groq, Together, OpenRouter, Mistral, DeepSeek, Ollama, vLLM...).

These vendors don't share a structured-output API, so every call uses the lowest common denominator that all of them
support: plain text in, a JSON object out. The JSON Schema of the result goes into the prompt, the vendor's "JSON mode" is
switched on where one exists, and the reply is validated with the same pydantic models the Anthropic path uses. If the reply
isn't usable it is asked for once more with the error; after that the call fails with a clear message. Nothing is posted or
saved from a reply that didn't validate.

NOT VERIFIED AGAINST THE LIVE APIS: the build environment had no keys and no route to these hosts. Request and response shapes
are written from the vendors' documented REST formats as I remember them and are tested against canned responses. Make one
real call per vendor you use (the Admin page's "Test the AI connection" button does exactly that) before relying on it."""

import json
import re
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from app.ai import AIError, LLMTasks
from app.http import HttpResponse, http_request

TIMEOUT = 120.0
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S | re.I)


@dataclass
class RawReply:
    text: str
    input_tokens: int
    output_tokens: int
    finish: str  # "stop" | "length" | "refused"


def _detail(resp: HttpResponse) -> str:
    data = resp.json()
    if isinstance(data, dict):
        err = data.get("error", data)
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"][:200]
        if isinstance(err, str):
            return err[:200]
    return (resp.body or b"")[:120].decode(errors="replace").strip()


def raise_for_status(resp: HttpResponse, vendor: str) -> None:
    if resp.status < 400:
        return
    if resp.status in (401, 403):
        raise AIError(503, f"AI is misconfigured on this server ({vendor} rejected the credentials).")
    if resp.status == 429:
        raise AIError(503, "The AI service is busy or rate-limited. Try again in a minute.")
    if resp.status >= 500:
        raise AIError(502, f"The AI service returned an error ({resp.status}).")
    # 400/404 are usually a wrong model name or an unsupported option: say what the vendor said
    raise AIError(502, f"{vendor} rejected the request ({resp.status}): {_detail(resp)}")


def _count(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


class OpenAIBackend:
    """POST {base_url}/chat/completions: OpenAI itself and anything that speaks the same protocol."""

    vendor = "The AI service"

    def __init__(self, api_key: str | None, base_url: str, model: str, token_param: str | None = None, http=http_request):
        self.api_key, self.base_url, self.model, self.http = api_key, base_url.rstrip("/"), model, http
        # OpenAI's newer models want max_completion_tokens; most compatible servers only know max_tokens
        self.token_param = token_param or ("max_completion_tokens" if self.base_url.startswith("https://api.openai.com") else "max_tokens")

    def generate(self, system: str, user: str, max_tokens: int) -> RawReply:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            self.token_param: max_tokens,
        }
        try:
            resp = self.http("POST", f"{self.base_url}/chat/completions", headers=headers, json_body=body, timeout=TIMEOUT)
        except OSError:
            raise AIError(502, "Could not reach the AI service.")
        raise_for_status(resp, self.vendor)
        data = resp.json()
        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError):
            raise AIError(502, "The AI response could not be read. Try again.")
        if not isinstance(message, dict) or not isinstance(choice, dict):
            raise AIError(502, "The AI response could not be read. Try again.")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        tokens = (_count(usage.get("prompt_tokens")), _count(usage.get("completion_tokens")))
        finish = choice.get("finish_reason")
        if message.get("refusal") or finish == "content_filter":
            return RawReply("", *tokens, "refused")
        text = message.get("content")
        return RawReply(text if isinstance(text, str) else "", *tokens, "length" if finish == "length" else "stop")


class GeminiBackend:
    """POST {base_url}/models/{model}:generateContent (Google AI Studio / Gemini API)."""

    vendor = "Gemini"

    def __init__(self, api_key: str, base_url: str, model: str, http=http_request):
        self.api_key, self.base_url, self.http = api_key, base_url.rstrip("/"), http
        self.model = model.removeprefix("models/")

    def generate(self, system: str, user: str, max_tokens: int) -> RawReply:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": max_tokens},
        }
        try:
            resp = self.http("POST", f"{self.base_url}/models/{self.model}:generateContent", headers={"x-goog-api-key": self.api_key}, json_body=body, timeout=TIMEOUT)
        except OSError:
            raise AIError(502, "Could not reach the AI service.")
        raise_for_status(resp, self.vendor)
        data = resp.json()
        if not isinstance(data, dict):
            raise AIError(502, "The AI response could not be read. Try again.")
        usage = data.get("usageMetadata") if isinstance(data.get("usageMetadata"), dict) else {}
        tokens = (_count(usage.get("promptTokenCount")), _count(usage.get("candidatesTokenCount")))
        feedback = data.get("promptFeedback")
        if isinstance(feedback, dict) and feedback.get("blockReason"):
            return RawReply("", *tokens, "refused")
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
            raise AIError(502, "The AI response could not be read. Try again.")
        cand = candidates[0]
        reason = cand.get("finishReason")
        parts = (cand.get("content") or {}).get("parts") if isinstance(cand.get("content"), dict) else None
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str) and not p.get("thought")) if isinstance(parts, list) else ""
        if reason in ("SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION") and not text.strip():
            return RawReply("", *tokens, "refused")
        return RawReply(text, *tokens, "length" if reason == "MAX_TOKENS" else "stop")


def _instruction(output_format: type[BaseModel]) -> str:
    schema = json.dumps(output_format.model_json_schema(), separators=(",", ":"))
    return (
        "\n\nReply with ONLY one JSON object (no prose, no code fences) that conforms to this JSON Schema. "
        "Use exactly these field names and include every required field:\n" + schema
    )


def parse_json_reply(text: str, output_format: type[BaseModel]) -> BaseModel:
    text = text.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    if not text.startswith("{") and "{" in text and "}" in text:  # a stray sentence around the object
        text = text[text.index("{") : text.rindex("}") + 1]
    return output_format.model_validate_json(text)


class JsonLLMProvider(LLMTasks):
    def __init__(self, name: str, backend, model: str):
        self.name, self.backend, self.model = name, backend, model

    def _complete(self, system: str, payload: dict, output_format: type[BaseModel], max_tokens: int = 6000):
        system = system + _instruction(output_format)
        user = f"<data>\n{payload}\n</data>"
        tokens_in = tokens_out = 0
        problem = ""
        for attempt in range(2):
            prompt = user if attempt == 0 else f"{user}\n\nYour previous reply could not be used ({problem}). Reply again with only the corrected JSON object."
            reply = self.backend.generate(system, prompt, max_tokens)
            tokens_in, tokens_out = tokens_in + reply.input_tokens, tokens_out + reply.output_tokens
            if reply.finish == "refused":
                raise AIError(502, "The AI declined to produce a result for this input.")
            if reply.finish == "length":
                problem = "it was cut off: keep it shorter"
                if attempt == 1:
                    raise AIError(502, "The AI's reply was cut off before it finished. Try again, or use a model with a larger output limit.")
                continue
            try:
                return parse_json_reply(reply.text, output_format), tokens_in, tokens_out
            except (ValidationError, ValueError) as exc:
                problem = (str(exc).splitlines() or ["invalid JSON"])[0][:160]
        raise AIError(502, "The AI response could not be read. Try again.")
