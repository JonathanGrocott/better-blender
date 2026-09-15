"""Report external dependencies without opening or changing the document."""

import glob
from pathlib import Path

import bpy


def paths():
    return sorted(set(bpy.utils.blend_paths(absolute=True, packed=True)))


def inspect(filepaths=None):
    references = paths() if filepaths is None else filepaths
    missing = []
    patterns = []
    for raw in references:
        if not raw:
            continue
        path = Path(raw).expanduser()
        if "<UDIM>" in raw or "<UVTILE>" in raw:
            pattern = raw.replace("<UDIM>", "[0-9][0-9][0-9][0-9]").replace("<UVTILE>", "u*_v*")
            patterns.append(raw)
            if not glob.glob(pattern):
                missing.append(raw)
        elif not path.exists():
            missing.append(raw)
    return {
        "checked": len(references),
        "missing": missing,
        "patterns": patterns,
        "complete": not missing,
        "scope": "External references; sequence frames and caches need separate checks",
    }


def require_available(filepaths=None):
    report = inspect(filepaths)
    if report["missing"]:
        raise ValueError(
            "Missing external assets: "
            + ", ".join(report["missing"][:10])
            + ". Use check_assets for the full report."
        )
    return report
