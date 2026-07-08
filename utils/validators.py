"""
Checks for missing photos and documents; returns a structured missing-items dict.
"""

DOCS_BY_TOWER = {
    "Self Support": [
        ("as_built_drawings",     "As-Built Drawings"),
        ("material_cert",         "Material Certification Report"),
        ("fabrication_submittal", "Fabrication Submittal Package"),
        ("fabrication_letter",    "Fabrication Letter"),
        ("cold_galv_letter",      "Cold Galvanization Letter"),
    ],
    "Guyed": [
        ("as_built_drawings",     "As-Built Drawings (EOR)"),
        ("material_cert",         "Material Certification Report"),
        ("packing_slips",         "Packing Slips"),
        ("tension_report",        "Tension Report"),
        ("plumb_twist_report",    "Plumb & Twist Report"),
        ("fabrication_submittal", "Fabrication Submittal Package"),
        ("cold_galv_letter",      "Cold Galvanization Letter"),
    ],
    "Monopole": [
        ("as_built_drawings",     "As-Built Drawings"),
        ("material_cert",         "Material Certification Report"),
        ("fabrication_submittal", "Fabrication Submittal Package"),
        ("fabrication_letter",    "Fabrication Letter"),
        ("cold_galv_letter",      "Cold Galvanization Letter"),
    ],
}

REQUIRED_DOCS = DOCS_BY_TOWER["Self Support"]   # backward-compat alias

SPECIAL_PHOTOS_BY_TOWER = {
    "Self Support": [
        "Overall Tower View",
        "Field Measurements",
    ],
    "Guyed": [
        "Tension Gauge Photos",
        "Overall Tower View",
    ],
    "Monopole": [
        "Overall Tower View",
        "Field Measurements",
    ],
}

REQUIRED_EXTRA_DOCS_MIN = 1


def get_required_docs(tower_type: str) -> list:
    return DOCS_BY_TOWER.get(tower_type, DOCS_BY_TOWER["Self Support"])


def get_special_photos(tower_type: str) -> list:
    return SPECIAL_PHOTOS_BY_TOWER.get(tower_type, SPECIAL_PHOTOS_BY_TOWER["Self Support"])


def check_missing_items(data: dict) -> dict:
    """
    Returns:
        {
          "photos":       [...label strings...],
          "documents":    [...label strings...],
          "certificates": [...label strings...],
        }
    """
    missing = {"photos": [], "documents": [], "certificates": []}

    tower_type      = data.get("tower_type", "Self Support")
    modifications   = data.get("modifications", [])
    photos          = data.get("photos", {})
    documents       = data.get("documents", {})
    extra_documents = data.get("extra_documents", [])

    positions = _get_positions(tower_type, data.get("num_guys", 3))

    for mod in modifications:
        mid = mod["mod_id"]
        if positions:
            for pos in positions:
                if not photos.get((mid, pos)):
                    missing["photos"].append(f"{mid} – {pos}")
        else:
            if not photos.get((mid, "")):
                missing["photos"].append(mid)

    for label in get_special_photos(tower_type):
        if not photos.get(("special", label)):
            missing["photos"].append(label)

    for doc_key, doc_label in get_required_docs(tower_type):
        if not documents.get(doc_key):
            missing["documents"].append(doc_label)

    valid_extra_docs = [e for e in extra_documents if e.get("name", "").strip() and e.get("files")]
    if len(valid_extra_docs) < REQUIRED_EXTRA_DOCS_MIN:
        missing["certificates"].append("At least one certificate / extra document is required (name it and attach a file)")

    return missing


def _cross_check_positions(doc_extractions: dict, reading_doc_key: str, doc_label: str) -> list:
    """
    Compares positions (Leg X / Guy N) mentioned in the As-Built Drawing's
    extracted modifications against positions mentioned in `reading_doc_key`'s
    extracted `readings` (each with a `guy_or_leg` field). Returns a list of
    human-readable mismatch strings — v1 is a position-presence check, not
    numeric tolerance validation. Returns [] if either document hasn't been
    extracted yet, or if both agree.

    doc_extractions: st.session_state._doc_extractions, i.e. {(doc_key, sig): extracted_dict}
    """
    as_built_positions = set()
    reading_positions = set()

    for (doc_key, _sig), extracted in doc_extractions.items():
        if not isinstance(extracted, dict):
            continue
        if doc_key == "as_built_drawings":
            for m in extracted.get("modifications") or []:
                pos = (m.get("position") or "").strip()
                if pos:
                    as_built_positions.add(pos)
        elif doc_key == reading_doc_key:
            for r in extracted.get("readings") or []:
                pos = (r.get("guy_or_leg") or "").strip()
                if pos:
                    reading_positions.add(pos)

    if not as_built_positions or not reading_positions:
        return []

    mismatches = []
    only_in_reading = reading_positions - as_built_positions
    only_in_drawing = as_built_positions - reading_positions
    if only_in_reading:
        mismatches.append(
            f"{doc_label} references {', '.join(sorted(only_in_reading))}, "
            f"which the As-Built Drawing does not mention."
        )
    if only_in_drawing:
        mismatches.append(
            f"As-Built Drawing references {', '.join(sorted(only_in_drawing))} "
            f"with no matching {doc_label} reading."
        )
    return mismatches


def cross_check_plumb_twist(doc_extractions: dict) -> list:
    return _cross_check_positions(doc_extractions, "plumb_twist_report", "Plumb & Twist Report")


def cross_check_tension(doc_extractions: dict) -> list:
    return _cross_check_positions(doc_extractions, "tension_report", "Tension Report")


def _get_positions(tower_type: str, num_guys: int = 3) -> list:
    if tower_type == "Self Support":
        return ["Leg A", "Leg B", "Leg C"]
    elif tower_type == "Guyed":
        return [f"Guy {i+1}" for i in range(num_guys)]
    return []
