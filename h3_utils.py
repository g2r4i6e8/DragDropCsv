"""Optional H3 support with v4/v3 API compatibility."""

import re

from qgis.core import QgsGeometry, QgsPointXY

# H3 cells are always defined in WGS84
H3_CRS = "EPSG:4326"

H3_AVAILABLE = False
H3_IMPORT_ERROR = None
_h3 = None

try:
    import h3 as _h3
    H3_AVAILABLE = True
except ImportError as exc:
    H3_IMPORT_ERROR = str(exc)


def is_h3_available():
    """Return True when the optional h3 package is installed."""
    return H3_AVAILABLE


def get_h3_install_message():
    """Return user-facing instructions for installing the h3 package."""
    return (
        "The 'h3' package is required for H3 Index geometry.\n\n"
        "Install it in the QGIS Python environment:\n"
        "  python -m pip install h3"
    )


def _uses_v4_api():
    """Detect h3-py v4 API (cell_to_boundary) vs legacy v3 names."""
    return hasattr(_h3, "cell_to_boundary")


def _strip_cell_text(raw_value):
    """Normalize a raw CSV cell value to a stripped string."""
    if raw_value is None:
        return ""
    text = str(raw_value).strip()
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        text = text[1:-1].strip()
    return text


def parse_h3_cell(raw_value):
    """Parse H3 cell id from CSV value.

    Supports:
    - hex strings like "8928308280fffff"
    - int64 values like 1234567890123456789 (as int or decimal string)
    """
    text = _strip_cell_text(raw_value)
    if not text:
        return None

    hex_pattern = re.compile(r"^[0-9a-fA-F]+$")
    if not hex_pattern.match(text):
        return None

    # Hex index when letters are present (e.g. 8928308280fffff)
    if any(ch in "abcdefABCDEF" for ch in text):
        return text.lower()

    # Pure digits are treated as int64 cell index
    try:
        return int(text)
    except (ValueError, OverflowError):
        return None


def _to_api_cell(cell):
    """Convert parsed cell id to the format expected by installed h3 API."""
    if cell is None:
        return None
    try:
        if _uses_v4_api():
            # h3-py v4 accepts hex strings; int64 must be converted first
            if isinstance(cell, int):
                return _h3.int_to_str(cell)
            return str(cell).lower()
        # h3-py v3 uses integer indexes; hex strings must be converted first
        if isinstance(cell, str):
            if hasattr(_h3, "string_to_h3"):
                return _h3.string_to_h3(cell)
            return _h3.str_to_int(cell)
        return cell
    except Exception:
        return None


def is_valid_h3_cell(cell):
    """Validate parsed H3 cell using installed h3 API."""
    if not H3_AVAILABLE or cell is None:
        return False
    api_cell = _to_api_cell(cell)
    if api_cell is None:
        return False
    try:
        if _uses_v4_api():
            return bool(_h3.is_valid_cell(api_cell))
        return bool(_h3.h3_is_valid(api_cell))
    except Exception:
        return False


def h3_cell_to_boundary(cell):
    """Return polygon boundary as list of (lat, lon) tuples."""
    if not H3_AVAILABLE or cell is None:
        return None
    api_cell = _to_api_cell(cell)
    if api_cell is None:
        return None
    try:
        if _uses_v4_api():
            boundary = _h3.cell_to_boundary(api_cell)
        else:
            boundary = _h3.h3_to_geo_boundary(api_cell, geo_json=False)
        return list(boundary) if boundary else None
    except Exception:
        return None


def h3_cell_to_qgs_geometry(cell):
    """Build a QgsGeometry polygon from an H3 cell id."""
    boundary = h3_cell_to_boundary(cell)
    if not boundary:
        return None

    # h3 returns (lat, lon); QGIS expects (x=lon, y=lat)
    ring = [QgsPointXY(lon, lat) for lat, lon in boundary]
    if not ring:
        return None

    if ring[0] != ring[-1]:
        ring.append(ring[0])

    geometry = QgsGeometry.fromPolygonXY([ring])
    if geometry.isNull():
        return None
    return geometry
