import os
import io
import json
from google import genai
from PIL import Image
from dotenv import load_dotenv

import PyPDF2
from docx import Document

from agents.retry import generate_content_with_retry

load_dotenv()

MODEL = "gemini-2.5-flash"

DOC_EXTRACTION_PROMPTS = {
    "material_cert": """Extract the following fields from this Material Certification Report and return as JSON:
{
  "cert_number": "",
  "material_spec": "",
  "heat_number": "",
  "material_grade": "",
  "supplier": "",
  "date": "",
  "remarks": ""
}
If a field is not found, leave it as empty string. Return only the JSON, no other text.""",

    "fabrication_submittal": """Extract the following fields from this Fabrication Submittal Package and return as JSON:
{
  "fabricator_name": "",
  "submittal_number": "",
  "date": "",
  "project_reference": "",
  "items_submitted": [],
  "remarks": ""
}
Return only the JSON, no other text.""",

    "fabrication_letter": """Extract the following fields from this Fabrication Letter and return as JSON:
{
  "fabricator_name": "",
  "date": "",
  "project_reference": "",
  "member_description": "",
  "material_spec": "",
  "remarks": ""
}
Return only the JSON, no other text.""",

    "cold_galv_letter": """Extract the following fields from this Cold Galvanization Letter and return as JSON:
{
  "applicator_name": "",
  "date": "",
  "product_name": "",
  "standard_met": "",
  "project_reference": "",
  "remarks": ""
}
Return only the JSON, no other text.""",

    "certificate": """Extract the following fields from this Certificate document and return as JSON:
{
  "certificate_type": "",
  "certificate_number": "",
  "issued_to": "",
  "issued_by": "",
  "date_issued": "",
  "expiry_date": "",
  "scope": "",
  "remarks": ""
}
Return only the JSON, no other text.""",

    "as_built_drawings": """Extract the following fields from this As-Built Drawing (Engineer of Record) and return as JSON:
{
  "drawing_number": "",
  "drawing_date": "",
  "site_name": "",
  "site_number": "",
  "tower_height": "",
  "modifications": [
    {"mod_id": "M1", "description": "", "elevation": "", "position": ""}
  ],
  "remarks": ""
}
Rules:
- "modifications" must list every structural modification shown on the drawing, in the order they appear.
- "position" is the specific level the modification occurs at — e.g. "Leg A", "Leg B", "Leg C", "Guy 1", "Guy 2", etc. Leave empty if the drawing doesn't tie the item to a specific leg/guy.
- "elevation" should be the elevation or elevation range shown for that item (e.g. "200.0'-180.0'").
- If a field is not found, leave it as empty string / empty list. Return only the JSON, no other text.""",

    "plumb_twist_report": """Extract the following fields from this Plumb & Twist Report and return as JSON:
{
  "report_date": "",
  "readings": [
    {"guy_or_leg": "", "elevation": "", "plumb_measured": "", "plumb_allowable": "",
     "twist_measured": "", "twist_allowable": "", "pass_fail": ""}
  ],
  "remarks": ""
}
Rules:
- "guy_or_leg" is the position each reading was taken at — e.g. "Guy 1", "Leg A".
- "pass_fail" should be "Pass", "Fail", or "" if not stated.
- If a field is not found, leave it as empty string / empty list. Return only the JSON, no other text.""",

    "tension_report": """Extract the following fields from this Guy Wire Tension Report and return as JSON:
{
  "report_date": "",
  "readings": [
    {"guy_or_leg": "", "elevation": "", "tension_measured": "", "tension_required": "", "pass_fail": ""}
  ],
  "remarks": ""
}
Rules:
- "guy_or_leg" is the position each reading was taken at — e.g. "Guy 1".
- "pass_fail" should be "Pass", "Fail", or "" if not stated.
- If a field is not found, leave it as empty string / empty list. Return only the JSON, no other text.""",
}


def _client():
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _file_ext(filename: str) -> str:
    return "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _read_pdf_text(file_bytes: bytes) -> str:
    reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
    return "".join(page.extract_text() or "" for page in reader.pages).strip()


def _read_docx_text(file_bytes: bytes) -> str:
    doc = Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


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
        return {"raw_extract": raw}


PREFILLED_REPORT_PROMPT = """You are extracting data from a pre-filled PMI Closeout Report Word document.
Extract ALL available fields and return them as JSON with exactly these keys:

{
  "report_date": "",
  "client": "",
  "site_name": "",
  "site_number": "",
  "carrier_name": "",
  "site_address": "",
  "gps_coords": "",
  "tower_type": "",
  "tower_height": "",
  "observation_date": "",
  "drawing_date": "",
  "drawing_sheets": "",
  "general_contractor": "",
  "gc_contact": "",
  "project_description": "",
  "modifications": [
    {"mod_id": "M1", "description": "", "elevation": ""}
  ],
  "deficiencies": "",
  "field_observations": {
    "Structural Member Verification": ["", ""],
    "Connection and Installation Verification": ["", ""],
    "Modification Installation": ["", ""],
    "Connection and Welding": ["", ""],
    "Alignment and Eccentricity": ["", ""],
    "Coating and Protection": ["", ""],
    "Interference Check": ["", ""],
    "Final Verification": ["", ""]
  }
}

Rules:
- Extract modifications from any list, table, or scope section you find
- For field_observations, extract the actual bullet points written under each section heading
- If a section has no specific content written, leave those as empty strings
- tower_type must be one of: "Self Support", "Guyed", "Monopole"
- Return ONLY valid JSON, no markdown, no explanation"""


def extract_prefilled_report(file_bytes: bytes, filename: str) -> dict:
    """
    Extract all project data from a pre-filled closeout report template.
    Returns a dict matching the app's session state structure.
    """
    client = _client()
    ext = _file_ext(filename)

    if ext in (".docx", ".doc"):
        doc_text = _read_docx_text(file_bytes)
        response = generate_content_with_retry(
            client,
            model=MODEL,
            contents=f"{PREFILLED_REPORT_PROMPT}\n\nDocument text:\n{doc_text}",
        )
    elif ext == ".pdf":
        doc_text = _read_pdf_text(file_bytes)
        if doc_text:
            response = generate_content_with_retry(
                client,
                model=MODEL,
                contents=f"{PREFILLED_REPORT_PROMPT}\n\nDocument text:\n{doc_text}",
            )
        else:
            try:
                import fitz
                pdf_doc = fitz.open(stream=file_bytes, filetype="pdf")
                img_bytes_list = []
                for i, page in enumerate(pdf_doc):
                    if i >= 4:
                        break
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                    img_bytes_list.append(pix.tobytes("png"))
                pdf_doc.close()
                from PIL import Image as PILImage
                imgs = [PILImage.open(io.BytesIO(b)) for b in img_bytes_list]
                response = generate_content_with_retry(
                    client, model=MODEL, contents=[PREFILLED_REPORT_PROMPT] + imgs
                )
            except Exception:
                return {"error": "Could not read PDF"}
    else:
        return {"error": f"Unsupported file type: {ext}"}

    return _parse_json_response(response.text)


def extract_document_fields(file_bytes: bytes, filename: str, doc_type: str) -> dict:
    """
    Extract relevant fields from an uploaded document using Gemini.
    doc_type: key from DOC_EXTRACTION_PROMPTS
    """
    client = _client()
    prompt = DOC_EXTRACTION_PROMPTS.get(doc_type, DOC_EXTRACTION_PROMPTS["certificate"])
    ext = _file_ext(filename)

    if ext == ".pdf":
        doc_text = _read_pdf_text(file_bytes)
        if doc_text:
            response = generate_content_with_retry(
                client,
                model=MODEL,
                contents=f"{prompt}\n\nDocument text:\n{doc_text}",
            )
        else:
            # Scanned/image-only PDF (common for as-built drawings) — no text
            # layer to read, so render pages to images for Gemini vision instead.
            import fitz
            pdf_doc = fitz.open(stream=file_bytes, filetype="pdf")
            imgs = []
            for i, page in enumerate(pdf_doc):
                if i >= 4:
                    break
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                imgs.append(Image.open(io.BytesIO(pix.tobytes("png"))))
            pdf_doc.close()
            response = generate_content_with_retry(client, model=MODEL, contents=[prompt] + imgs)

    elif ext in (".docx", ".doc"):
        doc_text = _read_docx_text(file_bytes)
        response = generate_content_with_retry(
            client,
            model=MODEL,
            contents=f"{prompt}\n\nDocument text:\n{doc_text}",
        )

    elif ext in (".jpg", ".jpeg", ".png"):
        img = Image.open(io.BytesIO(file_bytes))
        response = generate_content_with_retry(client, model=MODEL, contents=[prompt, img])

    else:
        return {"error": f"Unsupported file type: {ext}"}

    return _parse_json_response(response.text)
