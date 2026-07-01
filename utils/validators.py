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

REQUIRED_CERTS_MIN = 1


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

    tower_type    = data.get("tower_type", "Self Support")
    modifications = data.get("modifications", [])
    photos        = data.get("photos", {})
    documents     = data.get("documents", {})
    certificates  = data.get("certificates", [])

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

    if len(certificates) < REQUIRED_CERTS_MIN:
        missing["certificates"].append("At least one certificate is required")

    return missing


def _get_positions(tower_type: str, num_guys: int = 3) -> list:
    if tower_type == "Self Support":
        return ["Leg A", "Leg B", "Leg C"]
    elif tower_type == "Guyed":
        return [f"Guy {i+1}" for i in range(num_guys)]
    return []
