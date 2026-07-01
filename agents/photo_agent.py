import os
import io
from google import genai
from google.genai import types
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

MODEL = "gemini-2.0-flash"


def _client():
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def analyze_photo(image_bytes: bytes, mime_type: str, context: dict) -> str:
    """
    Analyze a site photo and return a structural engineer style caption.

    context keys:
        mod_id        : "M1"
        mod_desc      : "Adding redundant diagonal bracing..."
        elevation     : "200.0'-180.0'"
        position      : "Leg A" | "Guy 1" | "" etc.
        tower_type    : "Self Support" | "Guyed" | "Monopole"
        photo_purpose : "modification" | "overall" | "measurement" |
                        "structure_condition" | "finish" | "guys" |
                        "concrete_foundations" | "guyed_mast_anchors" | "coax"
    """
    position_str = context.get("position", "")
    mod_desc     = context.get("mod_desc", "")
    elevation    = context.get("elevation", "")
    mod_id       = context.get("mod_id", "")
    purpose      = context.get("photo_purpose", "modification")

    if purpose == "overall":
        task = (
            "This is an overall tower view photo. Describe what is visible — "
            "tower type, general condition, and completed modification work visible on the structure."
        )
    elif purpose == "measurement":
        task = (
            "This is a field measurement/verification photo. Describe the member being measured, "
            "the dimension shown, and how it relates to the installed structural work."
        )
    elif purpose == "tension_gauge":
        task = (
            "This photo documents tension gauge readings at a guy wire anchor point. "
            "Describe the gauge instrument, the reading visible, the anchor point or turnbuckle hardware, "
            "and any relevant observations about the guy wire tension verification process."
        )
    else:
        task = (
            f"This photo documents {mod_id}: {mod_desc} at elevation {elevation}"
            + (f", {position_str}" if position_str else "") + ". "
            "Describe the installed structural member(s), connection type, fasteners/welds visible, "
            "and whether the installation appears consistent with standard structural practice."
        )

    prompt = (
        "You are a licensed structural engineer writing photo captions for a "
        "Post Modification Close-Out Report. "
        "Write a concise, professional caption (1-2 sentences) for the following site photograph. "
        "Use technical structural terminology. Do not mention the engineer's name or company. "
        "Do not start with 'This photo shows' — state the observation directly.\n\n"
        f"Context: {task}"
    )

    img = Image.open(io.BytesIO(image_bytes))
    client = _client()
    response = client.models.generate_content(
        model=MODEL,
        contents=[prompt, img],
    )
    return response.text.strip()
