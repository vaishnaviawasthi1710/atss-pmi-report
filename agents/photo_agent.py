import os
import io
import json
from google import genai
from PIL import Image
from dotenv import load_dotenv

from agents.retry import generate_content_with_retry

load_dotenv()

MODEL = "gemini-2.5-flash"


def _client():
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _parse_json_response(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return {}


def analyze_photo(image_bytes: bytes, mime_type: str, context: dict) -> dict:
    """
    Single Gemini vision call that both (1) writes a professional structural
    engineer caption for the photo, and (2) — only when the photo is tied to
    a specific modification — flags whether what's visible looks consistent
    with that modification's stated description. This is AI-suggests-only:
    the flag is surfaced to the engineer as a warning, never used to reject
    or auto-edit anything.

    context keys:
        mod_id        : "M1"
        mod_desc      : "Adding redundant diagonal bracing..."
        elevation     : "200.0'-180.0'"
        position      : "Leg A" | "Guy 1" | "" etc.
        tower_type    : "Self Support" | "Guyed" | "Monopole"
        photo_purpose : "modification" | "overall" | "measurement" |
                        "structure_condition" | "finish" | "guys" |
                        "concrete_foundations" | "guyed_mast_anchors" | "coax"
        fallback_caption: non-AI default caption to fall back to on error

    Returns: {"caption": str, "flag": str}  — flag is "" when consistent
    (or when there's no modification to check against).
    """
    position_str = context.get("position", "")
    mod_desc     = context.get("mod_desc", "")
    elevation    = context.get("elevation", "")
    mod_id       = context.get("mod_id", "")
    purpose      = context.get("photo_purpose", "modification")

    if purpose == "overall":
        task = (
            "This is an overall tower view photo. Describe what is visible — "
            "tower type, general condition, and completed modification work visible on the structure. "
            "There is no specific modification to check this photo against."
        )
    elif purpose == "measurement":
        task = (
            "This is a field measurement/verification photo. Describe the member being measured, "
            "the dimension shown, and how it relates to the installed structural work. "
            "There is no specific modification to check this photo against."
        )
    elif purpose == "tension_gauge":
        task = (
            "This photo documents tension gauge readings at a guy wire anchor point. "
            "Describe the gauge instrument, the reading visible, the anchor point or turnbuckle hardware, "
            "and any relevant observations about the guy wire tension verification process. "
            "There is no specific modification to check this photo against."
        )
    else:
        task = (
            f"This photo is submitted as documentation of {mod_id}: \"{mod_desc}\" at elevation "
            f"{elevation}" + (f", {position_str}" if position_str else "") + ". "
            "Describe the installed structural member(s), connection type, fasteners/welds visible, "
            "and whether the installation appears consistent with standard structural practice. "
            "Then judge whether what is actually visible in the photo is consistent with that stated "
            "modification (e.g. member orientation, type of connection, hardware) — flag it if the "
            "photo appears to show something different (e.g. a horizontal member when the modification "
            "describes diagonal bracing)."
        )

    prompt = (
        "You are a licensed structural engineer writing photo documentation for a "
        "Post Modification Close-Out Report.\n\n"
        f"Context: {task}\n\n"
        "Return ONLY valid JSON (no markdown fences, no explanation) in exactly this shape:\n"
        '{"caption": "1-2 sentence professional caption, technical structural terminology, '
        'do not start with \'This photo shows\', do not mention engineer name or company", '
        '"flag": "empty string if consistent or not applicable; otherwise a short specific note '
        'on what looks inconsistent with the stated modification"}'
    )

    img = Image.open(io.BytesIO(image_bytes))
    client = _client()
    response = generate_content_with_retry(
        client,
        model=MODEL,
        contents=[prompt, img],
    )
    result = _parse_json_response(response.text)
    caption = (result.get("caption") or "").strip() or context.get("fallback_caption", "Site photograph.")
    flag = (result.get("flag") or "").strip()
    return {"caption": caption, "flag": flag}
