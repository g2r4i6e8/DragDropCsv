# Drag and Drop CSV

A QGIS plugin that lets you drag and drop `.csv` and `.csv.gz` files directly into QGIS. Data opens as an editable in-memory vector layer.

## Features

- Drag and drop support for `.csv` and `.csv.gz` files (map canvas or main window)
- Automatic gzip decompression
- Configurable delimiter, encoding, and coordinate reference system
- Smart field type detection (strings, integers, doubles, dates, datetimes)
- Multiple geometry modes:
  - **No geometry** — attribute table only
  - **WKT Geometry** — mixed geometry types split into separate layers
  - **Point (X/Y columns)** — point layer from coordinate columns
  - **H3 Index** — polygon layer from H3 cell ids (optional, requires `h3` package)
- Automatic column detection (WKT → X/Y → H3 → no geometry)
- WKT normalization for common non-standard formats
- CRS reprojection to the current project CRS when needed
- Remembers last import settings

## Installation

### From QGIS Plugin Manager

1. Open QGIS
2. Go to **Plugins → Manage and Install Plugins**
3. Search for **Drag and Drop CSV**
4. Click **Install Plugin**

### Manual Installation

1. Download the plugin zip file
2. Open QGIS
3. Go to **Plugins → Manage and Install Plugins**
4. Click **Install from ZIP**
5. Select the downloaded zip file

### Optional: H3 support

H3 geometry mode is available only when the `h3` Python package is installed in the QGIS Python environment.

**OSGeo4W / QGIS on Windows** (run from OSGeo4W Shell or QGIS Python console):

```bash
python -m pip install h3
```

Without `h3`, the plugin works normally — the H3 option simply does not appear in the import dialog.

## Usage

1. Drag a `.csv` or `.csv.gz` file into the QGIS map window or main window
2. Configure import settings in the dialog:
   - **Delimiter** — comma, semicolon, tab, or pipe
   - **Encoding** — UTF-8, ASCII, UTF-16, Windows-1251, ISO-8859-1
   - **Geometry type** — see table below
   - **CRS** — choose via the standard QGIS CRS dialog (fixed to WGS84 for H3)
3. Click **OK** — the layer is added to the project and the map zooms to its extent

## Geometry types

| Mode | Column(s) | Output | Notes |
|------|-----------|--------|-------|
| No geometry | — | Attribute table | |
| WKT Geometry | `wkt`, `geometry`, `geom`, … | One layer per geometry type | Mixed Point/Line/Polygon supported |
| Point (X/Y) | `x`/`y`, `lon`/`lat`, … | Point layer | |
| H3 Index | `h3_id`, `h3_index`, `h3`, … | Polygon layer | Hex (`891fb467533ffff`) or int64 (`617550903940743167`) |

### H3 specifics

- H3 cells are always interpreted in **EPSG:4326 (WGS84)**
- The CRS selector is disabled in H3 mode
- Geometries are reprojected to the project CRS after import
- Invalid H3 values are skipped (row is not loaded)
- The `h3_id` column is kept as a regular attribute field

## Test files

The `test_files/` folder contains sample CSVs for manual testing:

| File | Purpose |
|------|---------|
| `points_comma_xy_utf8.csv` | Point layer from X/Y columns |
| `point_comma_wkt_utf8.csv` | WKT geometry |
| `paris_mixed_wkt_utf8.csv` | Mixed WKT geometry types |
| `paris_mixed_wkt_utf8.csv.gz` | Gzipped WKT sample |
| `paris_h3_utf8.csv` | H3 polygons in Paris (hex + int64) |
| `points_semicolon_xy_utf8.csv` | Semicolon delimiter |
| `points_tab_xy_utf8.csv` | Tab delimiter |
| `points_pipe_xy_utf8.csv` | Pipe delimiter |

## Requirements

- QGIS 3.0 or later
- Python 3.x
- `chardet` (bundled with the plugin workflow)
- `h3` ≥ 3.7.0 — **optional**, only for H3 Index geometry

## Support

For issues and feature requests, visit the [GitHub repository](https://github.com/g2r4i6e8/DragDropCsv).

## License

This plugin is licensed under the GNU General Public License v3.0.
