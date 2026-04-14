import base64
import json
import logging
import re
import time
from typing import Any

import httpx
from django.conf import settings


logger = logging.getLogger(__name__)
PROVISIONAL_SCREENSHOT_SCORE = 50


class AIRateLimitError(Exception):
    pass


class AIModelNotFoundError(Exception):
    pass


def _clamp_score(value: Any, fallback: int = 0) -> int:
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        return fallback
    return max(0, min(100, score))


def _safe_json(content: str) -> dict[str, Any]:
    if not content:
        return {}
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}


def _is_rate_limited_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        return exc.response.status_code == 429
    lowered = str(exc).lower()
    return "429" in lowered or "too many requests" in lowered or "rate limit" in lowered


def _provider_error_message(exc: Exception) -> str:
    if _is_rate_limited_error(exc):
        return "AI provider is temporarily rate-limited. Please retry shortly."
    if isinstance(exc, AIModelNotFoundError):
        return "Configured Gemini model is not available. Please update GEMINI model settings."
    if isinstance(exc, httpx.TimeoutException):
        return "AI provider timeout. Please retry."
    return "AI provider request failed. Please retry later."


def _http_status_code(exc: Exception) -> int | None:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        return exc.response.status_code
    return None


def _retry_delay_seconds(exc: Exception, attempt: int) -> float:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        retry_after = exc.response.headers.get("Retry-After")
        if retry_after:
            try:
                parsed = float(retry_after)
                if parsed > 0:
                    return min(parsed, 15.0)
            except ValueError:
                pass
    # Exponential backoff with upper bound.
    return min(float(2 ** attempt), 10.0)


def _extract_text_from_gemini_response(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates", [])
    if not candidates:
        return ""
    content = candidates[0].get("content", {})
    parts = content.get("parts", [])
    if not parts:
        return ""
    return str(parts[0].get("text", ""))


def _normalize_mistakes(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _heuristic_explanation_score(explanation: str) -> int:
    words = len(re.findall(r"\w+", explanation or ""))
    if words == 0:
        return 100
    return _clamp_score(30 + (words * 2), fallback=30)


def _base_result(explanation: str) -> dict[str, Any]:
    return {
        "ai_score": 0,
        "explanation_score": _heuristic_explanation_score(explanation.strip()),
        "link_score": 100,
        "ai_feedback": "",
        "ai_mistakes": "",
    }


def _gemini_generate_json(
    models: list[str],
    api_key: str,
    prompt: str,
    image_data: dict[str, str] | None = None,
) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [{"text": prompt}]
    if image_data is not None:
        parts.append(
            {
                "inline_data": {
                    "mime_type": image_data["mime_type"],
                    "data": image_data["data"],
                }
            }
        )

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    last_exc: Exception | None = None
    saw_rate_limit = False
    saw_model_not_found = False
    max_retries = max(1, int(getattr(settings, "GEMINI_MAX_RETRIES", 4)))

    with httpx.Client(timeout=90.0) as client:
        for model in models:
            if not model.strip():
                continue
            endpoint = (
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            )

            for attempt in range(max_retries):
                try:
                    response = client.post(endpoint, json=payload)
                    response.raise_for_status()
                    raw = response.json()
                    return _safe_json(_extract_text_from_gemini_response(raw))
                except httpx.TimeoutException as exc:
                    last_exc = exc
                    if attempt < max_retries - 1:
                        time.sleep(_retry_delay_seconds(exc, attempt))
                        continue
                    break
                except httpx.HTTPStatusError as exc:
                    last_exc = exc
                    status_code = exc.response.status_code if exc.response is not None else None
                    if status_code == 404:
                        saw_model_not_found = True
                        logger.warning("Gemini model not found: %s", model)
                        break
                    if _is_rate_limited_error(exc):
                        saw_rate_limit = True
                        if attempt < max_retries - 1:
                            time.sleep(_retry_delay_seconds(exc, attempt))
                            continue
                        break
                    raise

    if saw_rate_limit:
        raise AIRateLimitError("Gemini API is currently rate-limited.")
    if saw_model_not_found:
        raise AIModelNotFoundError("Configured Gemini model is not available.")
    if last_exc is not None:
        raise last_exc
    return {}


def _evaluate_with_gemini(experiment, screenshot_file, explanation: str) -> dict[str, Any]:
    result = _base_result(explanation)

    if not settings.GEMINI_API_KEY:
        result["ai_feedback"] = (
            "AI evaluation skipped. Set GEMINI_API_KEY (free-tier key from Google AI Studio) in .env."
        )
        result["ai_mistakes"] = "Gemini API key missing."
        return result

    image_bytes = screenshot_file.read()
    screenshot_file.seek(0)
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    image_mime = getattr(screenshot_file, "content_type", "image/png")

    explanation = (explanation or "").strip()
    combined_prompt = (
        "You are a strict virtual electronics lab evaluator. Analyze the submitted circuit image and student explanation. "
        "Evaluate component correctness, wiring logic, and explanation quality. "
        "Respond ONLY as JSON with keys: "
        "screenshot_score (0-100 integer), explanation_score (0-100 integer), "
        "feedback (short text), explanation_feedback (short text), mistakes (array of short strings).\n\n"
        f"Experiment Title: {experiment.title}\n"
        f"Aim: {experiment.aim}\n"
        f"Procedure: {experiment.procedure}\n"
        f"Expected Result: {experiment.expected_result}\n"
        f"Student Explanation: {explanation if explanation else 'No explanation submitted.'}\n"
    )

    models = [settings.GEMINI_VISION_MODEL]
    fallback_model = getattr(settings, "GEMINI_FALLBACK_MODEL", "").strip()
    if fallback_model and fallback_model not in models:
        models.append(fallback_model)

    try:
        combined_payload = _gemini_generate_json(
            models=models,
            api_key=settings.GEMINI_API_KEY,
            prompt=combined_prompt,
            image_data={"mime_type": image_mime, "data": image_b64},
        )
        screenshot_score_raw = combined_payload.get("screenshot_score", combined_payload.get("score"))
        result["ai_score"] = _clamp_score(screenshot_score_raw, fallback=0)
        result["ai_feedback"] = str(combined_payload.get("feedback", "")).strip() or "AI evaluation completed."
        result["ai_mistakes"] = _normalize_mistakes(combined_payload.get("mistakes", []))

        if explanation:
            result["explanation_score"] = _clamp_score(
                combined_payload.get("explanation_score"),
                fallback=_heuristic_explanation_score(explanation),
            )
            explanation_feedback = str(combined_payload.get("explanation_feedback", "")).strip()
            if explanation_feedback:
                result["ai_feedback"] = f"{result['ai_feedback']} Explanation: {explanation_feedback}".strip()
        else:
            result["explanation_score"] = 100
    except Exception as exc:
        logger.warning("Gemini screenshot evaluation failed: %s", exc)
        if _is_rate_limited_error(exc):
            result["ai_score"] = PROVISIONAL_SCREENSHOT_SCORE
            result["ai_feedback"] = (
                "Gemini rate limit reached. Screenshot got provisional score 50/100. "
                "Use admin re-evaluation later for final AI score."
            )
            result["ai_mistakes"] = "AI evaluation postponed due to temporary rate limit."
            if explanation:
                result["explanation_score"] = _heuristic_explanation_score(explanation)
                result["ai_feedback"] = (
                    f"{result['ai_feedback']} Explanation AI rate-limited; heuristic score applied."
                ).strip()
        elif isinstance(exc, AIModelNotFoundError):
            result["ai_score"] = PROVISIONAL_SCREENSHOT_SCORE
            if explanation:
                result["explanation_score"] = _heuristic_explanation_score(explanation)
            result["ai_feedback"] = (
                "Gemini model configuration is invalid. Provisional score applied. "
                "Set GEMINI_VISION_MODEL and GEMINI_FALLBACK_MODEL to available models, then re-evaluate."
            )
            result["ai_mistakes"] = "AI evaluation postponed due to model configuration issue."
        else:
            # Do not penalize students when provider/auth/network fails.
            result["ai_score"] = PROVISIONAL_SCREENSHOT_SCORE
            if explanation:
                result["explanation_score"] = _heuristic_explanation_score(explanation)

            status_code = _http_status_code(exc)
            if status_code in {401, 403}:
                result["ai_feedback"] = (
                    "Gemini authentication or quota issue detected. Provisional screenshot score 50/100 applied. "
                    "Please verify GEMINI_API_KEY/quota and re-evaluate from admin."
                )
                result["ai_mistakes"] = "AI evaluation postponed due to API key/quota issue."
            elif status_code and status_code >= 500:
                result["ai_feedback"] = (
                    "Gemini service is temporarily unavailable. Provisional screenshot score 50/100 applied. "
                    "Re-evaluate from admin later."
                )
                result["ai_mistakes"] = "AI evaluation postponed due to provider outage."
            else:
                result["ai_feedback"] = (
                    f"{_provider_error_message(exc)} Provisional screenshot score 50/100 applied. "
                    "Re-evaluate from admin later."
                )
                result["ai_mistakes"] = "AI evaluation postponed due to temporary provider issue."

    return result


def _evaluate_with_openai(experiment, screenshot_file, explanation: str) -> dict[str, Any]:
    result = _base_result(explanation)
    if not settings.OPENAI_API_KEY:
        result["ai_feedback"] = "OpenAI evaluation skipped because OPENAI_API_KEY is not configured."
        result["ai_mistakes"] = "OpenAI API key missing."
        return result

    from openai import OpenAI

    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    image_bytes = screenshot_file.read()
    screenshot_file.seek(0)
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    image_mime = getattr(screenshot_file, "content_type", "image/png")

    vision_prompt = (
        "You are a strict virtual electronics lab evaluator. "
        "Compare the student submission against expected experiment details and evaluate if components and wiring logic are correct. "
        "Respond as JSON with keys: score (0-100 integer), feedback (short text), mistakes (array of short strings).\n\n"
        f"Experiment Title: {experiment.title}\n"
        f"Aim: {experiment.aim}\n"
        f"Procedure: {experiment.procedure}\n"
        f"Expected Result: {experiment.expected_result}\n"
    )

    try:
        vision_response = client.chat.completions.create(
            model=settings.OPENAI_VISION_MODEL,
            response_format={"type": "json_object"},
            temperature=0.1,
            messages=[
                {
                    "role": "system",
                    "content": "Return strict JSON only. Keep feedback concise and practical.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": vision_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{image_mime};base64,{image_b64}",
                            },
                        },
                    ],
                },
            ],
        )
        vision_payload = _safe_json(vision_response.choices[0].message.content)
        result["ai_score"] = _clamp_score(vision_payload.get("score"), fallback=0)
        result["ai_feedback"] = str(vision_payload.get("feedback", "")).strip() or "AI completed evaluation."
        result["ai_mistakes"] = _normalize_mistakes(vision_payload.get("mistakes", []))
    except Exception as exc:
        logger.warning("OpenAI screenshot evaluation failed", exc_info=True)
        if _is_rate_limited_error(exc):
            result["ai_score"] = PROVISIONAL_SCREENSHOT_SCORE
            result["ai_feedback"] = (
                "OpenAI rate limit reached. Screenshot got provisional score 50/100. "
                "Use admin re-evaluation later for final AI score."
            )
            result["ai_mistakes"] = "AI evaluation postponed due to temporary rate limit."
        else:
            result["ai_score"] = PROVISIONAL_SCREENSHOT_SCORE
            status_code = _http_status_code(exc)
            if status_code in {401, 403}:
                result["ai_feedback"] = (
                    "OpenAI authentication or quota issue detected. Provisional screenshot score 50/100 applied. "
                    "Please verify OPENAI_API_KEY/quota and re-evaluate from admin."
                )
                result["ai_mistakes"] = "AI evaluation postponed due to API key/quota issue."
            else:
                result["ai_feedback"] = (
                    f"{_provider_error_message(exc)} Provisional screenshot score 50/100 applied. "
                    "Re-evaluate from admin later."
                )
                result["ai_mistakes"] = "AI evaluation postponed due to temporary provider issue."

    explanation = (explanation or "").strip()
    if explanation:
        explanation_prompt = (
            "Evaluate the quality of this explanation for the experiment. "
            "Return JSON with keys score (0-100 integer) and feedback (short text).\n\n"
            f"Experiment Title: {experiment.title}\n"
            f"Aim: {experiment.aim}\n"
            f"Expected Result: {experiment.expected_result}\n"
            f"Student Explanation: {explanation}\n"
        )
        try:
            text_response = client.chat.completions.create(
                model=settings.OPENAI_TEXT_MODEL,
                response_format={"type": "json_object"},
                temperature=0.1,
                messages=[
                    {
                        "role": "system",
                        "content": "Return strict JSON only.",
                    },
                    {
                        "role": "user",
                        "content": explanation_prompt,
                    },
                ],
            )
            text_payload = _safe_json(text_response.choices[0].message.content)
            result["explanation_score"] = _clamp_score(text_payload.get("score"), fallback=0)
            explanation_feedback = str(text_payload.get("feedback", "")).strip()
            if explanation_feedback:
                result["ai_feedback"] = f"{result['ai_feedback']} Explanation: {explanation_feedback}".strip()
        except Exception as exc:
            logger.warning("OpenAI explanation evaluation failed", exc_info=True)
            result["explanation_score"] = _heuristic_explanation_score(explanation)
            if _is_rate_limited_error(exc):
                result["ai_feedback"] = (
                    f"{result['ai_feedback']} Explanation AI rate-limited; heuristic score applied."
                ).strip()
            else:
                result["ai_feedback"] = (
                    f"{result['ai_feedback']} Explanation AI unavailable; heuristic score applied."
                ).strip()

    return result


def evaluate_submission_with_ai(experiment, screenshot_file, explanation: str) -> dict[str, Any]:
    provider = settings.AI_PROVIDER
    if provider == "gemini":
        return _evaluate_with_gemini(experiment, screenshot_file, explanation)
    if provider == "openai":
        return _evaluate_with_openai(experiment, screenshot_file, explanation)

    fallback = _base_result(explanation)
    fallback["ai_feedback"] = (
        f"Unknown AI_PROVIDER '{provider}'. Supported values are 'gemini' (free tier) and 'openai'."
    )
    fallback["ai_mistakes"] = "Invalid AI provider setting."
    return fallback
