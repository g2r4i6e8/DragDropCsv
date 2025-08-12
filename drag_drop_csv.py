import os
import gzip
import tempfile
import csv
import re
import time
import json
import chardet
from qgis.PyQt.QtCore import QMimeData, Qt, QObject, QSettings, QVariant
from qgis.PyQt.QtWidgets import QMessageBox, QCheckBox
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsWkbTypes, QgsCoordinateReferenceSystem,
    QgsFeature, QgsField, QgsFields, QgsGeometry, QgsCoordinateTransform
)
from qgis.gui import QgsLayerTreeView
from .csv_settings_dialog import CsvSettingsDialog
from urllib.parse import quote

# Debug flag - set to True to enable debug printing
DEBUG = False

def debug_print(*args, **kwargs):
    """Print debug messages only when DEBUG is True"""
    if DEBUG:
        print(*args, **kwargs)

def detect_field_type(values):
    """Detect the appropriate field type based on sample values"""
    if not values:
        return QVariant.String
    
    # Remove empty values
    non_empty_values = [v for v in values if v and str(v).strip()]
    if not non_empty_values:
        return QVariant.String
    
    # Check if all values are integers
    try:
        for val in non_empty_values:
            int(val)
        return QVariant.Int
    except (ValueError, TypeError):
        pass
    
    # Check if all values are doubles/floats
    try:
        for val in non_empty_values:
            float(val)
        return QVariant.Double
    except (ValueError, TypeError):
        pass
    
    # Check if all values are dates (simple check)
    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    if all(date_pattern.match(str(val)) for val in non_empty_values):
        return QVariant.Date
    
    # Check if all values are datetime (simple check)
    datetime_pattern = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')
    if all(datetime_pattern.match(str(val)) for val in non_empty_values):
        return QVariant.DateTime
    
    # Default to string
    return QVariant.String

def normalize_wkt(wkt_text):
    """Normalize WKT strings to improve parser compatibility.

    Fixes common non-standard forms such as "LINESTRING((...))" or
    "POINT((...))" by removing the redundant pair of parentheses. Also
    preserves dimensionality tokens (Z, M, ZM) when present.
    """
    if not wkt_text:
        return wkt_text

    text = str(wkt_text).strip()

    # Strip surrounding quotes if present
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1].strip()

    # Handle EWKT prefix like SRID=4326;WKT
    if text.upper().startswith('SRID='):
        semi = text.find(';')
        if semi != -1:
            text = text[semi+1:].strip()

    # Patterns to collapse double parentheses for LINESTRING and POINT
    line_pattern = re.compile(r"^\s*LINESTRING(\s+(?:Z|M|ZM))?\s*\(\(\s*(.*?)\s*\)\)\s*$", re.IGNORECASE)
    point_pattern = re.compile(r"^\s*POINT(\s+(?:Z|M|ZM))?\s*\(\(\s*(.*?)\s*\)\)\s*$", re.IGNORECASE)

    match_line = line_pattern.match(text)
    if match_line:
        dim = match_line.group(1) or ""
        inner = match_line.group(2)
        return f"LINESTRING{dim} ({inner})"

    match_point = point_pattern.match(text)
    if match_point:
        dim = match_point.group(1) or ""
        inner = match_point.group(2)
        return f"POINT{dim} ({inner})"

    return text

class DragDropCsv(QObject):
    def __init__(self, iface):
        super().__init__()
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.project = QgsProject.instance()
        self.layer_tree_view = iface.layerTreeView()
        self.main_window = iface.mainWindow()
        self.temp_files = []  # Keep track of temporary files
        self.settings = QSettings()
        
    def initGui(self):
        """Add the drag and drop handler when plugin is enabled"""
        self.layer_tree_view.viewport().installEventFilter(self)
        self.main_window.installEventFilter(self)
        
    def unload(self):
        """Remove event filter when plugin is disabled"""
        self.layer_tree_view.viewport().removeEventFilter(self)
        self.main_window.removeEventFilter(self)
        # Clean up any remaining temporary files
        self.cleanup_temp_files()
        
    def cleanup_temp_files(self):
        """Clean up temporary files with retries"""
        for temp_file in self.temp_files:
            if os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                    debug_print(f"Cleaned up temporary file: {temp_file}")
                except Exception as e:
                    debug_print(f"Warning: Could not delete temporary file {temp_file}: {str(e)}")
        self.temp_files = []
        
    def save_settings(self, settings_dict):
        """Save settings to QGIS settings"""
        self.settings.setValue('drag_drop_csv/last_settings', json.dumps(settings_dict))
        
    def load_settings(self):
        """Load settings from QGIS settings"""
        settings_str = self.settings.value('drag_drop_csv/last_settings')
        if settings_str:
            return json.loads(settings_str)
        return None
        
    def eventFilter(self, obj, event):
        """Handle drag and drop events"""
        if event.type() == event.Drop:
            # Check if the drop is on the main window or layer tree view
            if obj == self.main_window:
                return self.handle_main_window_drop(event)
            elif obj == self.layer_tree_view.viewport():
                return self.handle_drop_event(event)
        return super().eventFilter(obj, event)
        
    def handle_main_window_drop(self, event):
        """Process drop events for the main QGIS window"""
        mime_data = event.mimeData()
        
        if mime_data.hasUrls():
            for url in mime_data.urls():
                file_path = url.toLocalFile()
                if file_path and (file_path.lower().endswith('.csv.gz') or file_path.lower().endswith('.csv')):
                    try:
                        debug_print(f"Processing file dropped on main window: {file_path}")
                        if file_path.lower().endswith('.csv.gz'):
                            self.process_gzipped_csv(file_path)
                        else:
                            self.process_csv(file_path)
                        event.accept()
                        return True
                    except Exception as e:
                        debug_print(f"Error processing file {file_path}: {str(e)}")
                        QMessageBox.warning(
                            self.iface.mainWindow(),
                            "Error loading CSV",
                            f"Could not load {file_path}: {str(e)}"
                        )
                        event.ignore()
                        return False
        return False
        
    def handle_drop_event(self, event):
        """Process drop events for .csv.gz and .csv files"""
        mime_data = event.mimeData()
        
        if mime_data.hasUrls():
            for url in mime_data.urls():
                file_path = url.toLocalFile()
                if file_path and (file_path.lower().endswith('.csv.gz') or file_path.lower().endswith('.csv')):
                    try:
                        debug_print(f"Processing file: {file_path}")
                        if file_path.lower().endswith('.csv.gz'):
                            self.process_gzipped_csv(file_path)
                        else:
                            self.process_csv(file_path)
                        event.accept()
                        return True
                    except Exception as e:
                        debug_print(f"Error processing file {file_path}: {str(e)}")
                        QMessageBox.warning(
                            self.iface.mainWindow(),
                            "Error loading CSV",
                            f"Could not load {file_path}: {str(e)}"
                        )
                        event.ignore()
                        return False
        return False
        
    def detect_encoding(self, file_path):
        """Try to detect file encoding using chardet"""
        debug_print("Detecting file encoding...")
        try:
            # Read a sample of the file for detection
            with open(file_path, 'rb') as f:
                raw_data = f.read(10000)  # Read first 10KB for detection
            
            # Detect encoding
            result = chardet.detect(raw_data)
            detected_encoding = result['encoding']
            confidence = result['confidence']
            
            debug_print(f"Detected encoding: {detected_encoding} with confidence: {confidence}")
            
            # If confidence is low, try some common encodings
            if confidence < 0.7:
                debug_print("Low confidence in detection, trying common encodings...")
                common_encodings = ['utf-8', 'windows-1251', 'cp1251', 'ascii', 'iso-8859-1']
                for encoding in common_encodings:
                    try:
                        with open(file_path, 'r', encoding=encoding) as f:
                            f.readline()
                        debug_print(f"Successfully tested with {encoding}")
                        return encoding
                    except UnicodeDecodeError:
                        continue
            
            # If we have a detected encoding, verify it works
            if detected_encoding:
                try:
                    with open(file_path, 'r', encoding=detected_encoding) as f:
                        f.readline()
                    return detected_encoding
                except UnicodeDecodeError:
                    debug_print(f"Detected encoding {detected_encoding} failed verification")
            
            # Fallback to utf-8 if all else fails
            debug_print("Using fallback encoding: utf-8")
            return 'utf-8'
            
        except Exception as e:
            debug_print(f"Error during encoding detection: {str(e)}")
            return 'utf-8'  # Default to UTF-8 if detection fails
        
    def validate_csv(self, file_path, encoding, delimiter):
        """Validate CSV file and return column names"""
        debug_print(f"Validating CSV file with encoding={encoding}, delimiter={delimiter}")
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                # Read first line to check if file is not empty
                first_line = f.readline().strip()
                if not first_line:
                    raise Exception("File is empty")
                debug_print(f"First line: {first_line}")
                
                # Try to parse the first line
                reader = csv.reader([first_line], delimiter=delimiter)
                columns = next(reader)
                
                if not columns:
                    raise Exception("No columns found in CSV")
                
                # Clean column names
                columns = [col.strip('"\'') for col in columns]
                debug_print(f"Found columns: {columns}")
                
                # Read a few more lines to validate data
                f.seek(0)
                reader = csv.reader(f, delimiter=delimiter)
                next(reader)  # Skip header
                
                for i, row in enumerate(reader):
                    if i >= 5:  # Check first 5 rows
                        break
                    if len(row) != len(columns):
                        debug_print(f"Row {i+2}: {row}")
                        debug_print(f"Expected {len(columns)} columns, got {len(row)}")
                        raise Exception(f"Row {i+2} has {len(row)} columns, expected {len(columns)}")
                    debug_print(f"Row {i+2} validated: {row}")
                
                return columns
                
        except Exception as e:
            debug_print(f"CSV validation failed: {str(e)}")
            raise Exception(f"CSV validation failed: {str(e)}")
    
    def create_layer_uri(self, file_path, delimiter, encoding, geometry_type, x_col=None, y_col=None, wkt_col=None, crs=None):
        """Create and validate layer URI"""
        debug_print("Creating layer URI...")
        
        # Convert Windows path to URL format
        file_path = file_path.replace('\\', '/')
        if not file_path.startswith('/'):
            file_path = '/' + file_path
            
        # Handle special delimiters
        if delimiter == '\t':
            delimiter_str = '\\t'
        else:
            delimiter_str = delimiter
            
        # Build base URI with QGIS-specific format
        uri = f"file://{file_path}?type=csv&delimiter={delimiter_str}&encoding={encoding}&detectTypes=yes"
        
        # Add geometry settings
        if geometry_type == "No geometry":
            uri += "&geometryType=none"
        elif geometry_type == "WKT":
            uri += f"&wktField={wkt_col}"
        elif "X/Y columns" in geometry_type:
            uri += f"&xField={x_col}&yField={y_col}"
        
        # Add CRS
        if crs:
            uri += f"&crs={crs}"
            
        debug_print(f"Created URI: {uri}")
        
        # Validate URI by creating a test layer
        test_layer = QgsVectorLayer(uri, "test", "delimitedtext")
        if not test_layer.isValid():
            debug_print(f"URI validation failed. Layer error: {test_layer.error().message()}")
            raise Exception(f"Invalid layer URI: {test_layer.error().message()}")
            
        return uri
        
    def create_editable_layer(self, source_layer, layer_name):
        """Create an editable memory layer from a source layer"""
        debug_print("Creating editable memory layer...")
        
        # Get source layer properties
        data_provider = source_layer.dataProvider()
        geometry_type = QgsWkbTypes.displayString(data_provider.wkbType())
        crs = data_provider.sourceCrs().authid()
        source_fields = data_provider.fields()
        
        # Create memory layer
        memory_layer = QgsVectorLayer(
            f"{geometry_type}?crs={crs}",
            layer_name,
            "memory"
        )
        
        if not memory_layer.isValid():
            raise Exception(f"Failed to create memory layer: {memory_layer.error().message()}")
        
        # Start editing
        memory_layer.startEditing()
        
        # Add fields with proper types
        memory_fields = QgsFields()
        for field in source_fields:
            memory_fields.append(QgsField(field.name(), field.type()))
        
        memory_layer.dataProvider().addAttributes(memory_fields)
        memory_layer.updateFields()
        
        # Copy features
        features = list(source_layer.getFeatures())
        memory_layer.addFeatures(features)
        
        # Commit changes
        memory_layer.commitChanges()
        
        return memory_layer

    def process_wkt_geometries(self, file_path, delimiter, encoding, wkt_col, crs, base_layer_name):
        """Process WKT geometries and create separate layers for each geometry type"""
        debug_print("Processing WKT geometries...")
        
        # Dictionary to store features by geometry type
        geometry_features = {}
        
        # First pass: collect data for field type detection
        field_data = {}
        
        # Read the CSV file for data collection
        with open(file_path, 'r', encoding=encoding) as f:
            reader = csv.DictReader(f, delimiter=delimiter)

            # Normalize column name comparison (handle quotes and case)
            wkt_col_norm = (wkt_col or '').strip().strip("'\"").lower()
            # Get field names excluding the WKT column
            field_names = [
                col for col in (reader.fieldnames or [])
                if (col or '').strip().strip("'\"").lower() != wkt_col_norm
            ]
            
            # Initialize field data collection
            for field_name in field_names:
                field_data[field_name] = []
            
            # Collect sample data for field type detection
            for row in reader:
                if not row:
                    continue
                # Case-insensitive value access snapshot for robustness
                row_lower = { (k or '').lower(): v for k, v in row.items() }
                for field_name in field_names:
                    val = row.get(field_name)
                    if val is None:
                        val = row_lower.get((field_name or '').lower())
                    field_data[field_name].append(val)
        
        # Second pass: process features
        with open(file_path, 'r', encoding=encoding) as f:
            reader = csv.DictReader(f, delimiter=delimiter)

            # Prepare normalized access keys
            wkt_col_norm = (wkt_col or '').strip().strip("'\"").lower()
            
            for row in reader:
                if not row:
                    continue
                row_lower = { (k or '').lower(): v for k, v in row.items() }
                wkt = row.get(wkt_col)
                if wkt is None:
                    wkt = row_lower.get(wkt_col_norm)
                if not wkt:
                    continue
                    
                # Create feature without geometry first
                feature = QgsFeature()
                
                # Add attributes
                attrs = []
                for f_name in field_names:
                    val = row.get(f_name)
                    if val is None:
                        val = row_lower.get((f_name or '').lower())
                    attrs.append(val)
                feature.setAttributes(attrs)
                
                # Try to create geometry from WKT (with normalization for non-standard forms)
                try:
                    normalized_wkt = normalize_wkt(wkt)
                    geometry = QgsGeometry.fromWkt(normalized_wkt)
                    if not geometry.isNull():
                        feature.setGeometry(geometry)
                        
                        # Get precise WKB type name (e.g., LineString, Polygon)
                        type_name = QgsWkbTypes.displayString(geometry.wkbType())
                        
                        # Add feature to appropriate geometry type list
                        if type_name not in geometry_features:
                            geometry_features[type_name] = []
                        geometry_features[type_name].append(feature)
                except Exception as e:
                    debug_print(f"Error processing WKT: {wkt}, Error: {str(e)}")
                    continue
        
        # Create layers for each geometry type
        created_layers = []
        for geom_type, features in geometry_features.items():
            if not features:
                continue
                
            # Create layer name - only add geometry type suffix if there are multiple types
            layer_name = base_layer_name if len(geometry_features) == 1 else f"{base_layer_name}_{geom_type}"
            
            # Map geometry type to QGIS-compatible string
            geom_type_map = {
                'Point': 'Point',
                'Line': 'LineString',
                'LineString': 'LineString',
                'Polygon': 'Polygon',
                'MultiPoint': 'MultiPoint',
                'MultiLineString': 'MultiLineString',
                'MultiPolygon': 'MultiPolygon'
            }
            qgis_geom_type = geom_type_map.get(geom_type, geom_type)
            
            # Determine CRS for the layer. If the project CRS differs from the
            # source CRS, transform geometries to the project CRS so the layer
            # aligns in the current project without relying on on-the-fly transform.
            source_crs = QgsCoordinateReferenceSystem(crs)
            project_crs = self.project.crs()

            target_authid = crs
            if project_crs.isValid() and source_crs.isValid() and project_crs != source_crs:
                try:
                    transformer = QgsCoordinateTransform(source_crs, project_crs, self.project)
                    for feature in features:
                        geom = feature.geometry()
                        if geom and not geom.isNull():
                            geom.transform(transformer)
                            feature.setGeometry(geom)
                    target_authid = project_crs.authid()
                except Exception as transform_error:
                    debug_print(f"CRS transform failed, keeping source CRS: {transform_error}")

            # Create memory layer in the decided CRS
            memory_layer = QgsVectorLayer(
                f"{qgis_geom_type}?crs={target_authid}",
                layer_name,
                "memory"
            )
            
            if not memory_layer.isValid():
                debug_print(f"Failed to create layer for {geom_type}")
                continue
            
            # Add fields
            fields = QgsFields()
            for field_name in field_names:
                # Detect field type based on collected data
                field_type = detect_field_type(field_data[field_name])
                fields.append(QgsField(field_name, field_type))
            provider = memory_layer.dataProvider()
            provider.addAttributes(fields)
            memory_layer.updateFields()

            # Bind features to layer fields to ensure attributes match schema
            layer_fields = memory_layer.fields()
            prepared_features = []
            for f in features:
                f.setFields(layer_fields, initAttributes=True)
                # Ensure attribute count matches
                attrs = f.attributes()
                if len(attrs) != layer_fields.count():
                    # Resize/pad attributes if necessary
                    padded = list(attrs)[: layer_fields.count()]
                    if len(padded) < layer_fields.count():
                        padded.extend([None] * (layer_fields.count() - len(padded)))
                    f.setAttributes(padded)
                prepared_features.append(f)

            # Add features
            provider.addFeatures(prepared_features)
            memory_layer.updateExtents()
            
            # Add layer to project
            self.project.addMapLayer(memory_layer)
            created_layers.append(memory_layer)
            
            debug_print(f"Created layer {layer_name} with {len(features)} features")
        
        # Fallback: if nothing was created (e.g., due to unexpected WKT), try using
        # QGIS delimited text provider directly with wktField to leverage its parser.
        if not created_layers:
            try:
                uri = self.create_layer_uri(
                    file_path=file_path,
                    delimiter=delimiter,
                    encoding=encoding,
                    geometry_type="WKT",
                    wkt_col=wkt_col,
                    crs=crs,
                )
                fallback_layer_name = base_layer_name
                source_layer = QgsVectorLayer(uri, fallback_layer_name, "delimitedtext")
                if source_layer.isValid() and source_layer.featureCount() > 0:
                    # Optionally reproject to project CRS for consistent behavior
                    project_crs = self.project.crs()
                    if project_crs.isValid() and source_layer.crs().isValid() and project_crs != source_layer.crs():
                        # Create editable memory layer and transform features
                        mem = self.create_editable_layer(source_layer, fallback_layer_name)
                        # Transform geometry in-place to project CRS
                        try:
                            transform = QgsCoordinateTransform(mem.crs(), project_crs, self.project)
                            mem.startEditing()
                            for feature in mem.getFeatures():
                                geom = feature.geometry()
                                if geom and not geom.isNull():
                                    geom.transform(transform)
                                    mem.dataProvider().changeGeometryValues({feature.id(): geom})
                            mem.commitChanges()
                            mem.setCrs(project_crs)
                        except Exception as e:
                            debug_print(f"Fallback CRS transform failed: {e}")
                        self.project.addMapLayer(mem)
                        created_layers.append(mem)
                    else:
                        # Add as-is
                        self.project.addMapLayer(source_layer)
                        created_layers.append(source_layer)
            except Exception as e:
                debug_print(f"Fallback to delimited text provider failed: {e}")

        return created_layers

    def process_csv(self, file_path):
        """Process a regular CSV file"""
        debug_print(f"Starting to process CSV file: {file_path}")
        
        try:
            # Detect encoding
            encoding = self.detect_encoding(file_path)
            
            # Show settings dialog
            debug_print("Opening settings dialog...")
            dialog = CsvSettingsDialog(self.iface.mainWindow())
            
            # Load previous settings if available
            last_settings = self.load_settings()
            if last_settings:
                # Set delimiter first
                dialog.delimiter_combo.setCurrentText(last_settings.get('delimiter', 'Comma (,)'))
                # Parse columns with the saved delimiter
                delimiter = dialog.get_delimiter()
                with open(file_path, 'r', encoding=encoding) as f:
                    reader = csv.reader(f, delimiter=delimiter)
                    try:
                        columns = next(reader)
                    except StopIteration:
                        raise Exception("File is empty")
            else:
                # Use default comma delimiter for initial parsing
                with open(file_path, 'r', encoding=encoding) as f:
                    reader = csv.reader(f)
                    try:
                        columns = next(reader)
                    except StopIteration:
                        raise Exception("File is empty")
            
            # Set columns in dialog
            dialog.set_columns(columns)
            
            # Convert encoding name to match dialog options
            encoding_map = {
                'utf-8': 'UTF-8',
                'utf-16': 'UTF-16',
                'windows-1251': 'Windows-1251',
                'cp1251': 'Windows-1251',
                'ascii': 'ASCII',
                'iso-8859-1': 'ISO-8859-1'
            }
            dialog_encoding = encoding_map.get(encoding.lower(), 'UTF-8')
            dialog.encoding_combo.setCurrentText(dialog_encoding)
            
            # Add "Remember settings" checkbox
            remember_settings = QCheckBox("Remember these settings for next time")
            remember_settings.setChecked(True)  # Set checkbox to checked by default
            dialog.layout().insertWidget(dialog.layout().count() - 1, remember_settings)
            
            # Load previous settings if available
            last_settings = self.load_settings()
            if last_settings:
                dialog.geometry_combo.setCurrentText(last_settings.get('geometry_type', 'No geometry'))
                dialog.set_crs(last_settings.get('crs', 'EPSG:4326'))
            
            if not dialog.exec_():
                debug_print("User canceled the operation")
                return  # User canceled
            
            # Get user settings
            settings = {
                'delimiter': dialog.delimiter_combo.currentText(),
                'encoding': dialog.encoding_combo.currentText(),
                'geometry_type': dialog.geometry_combo.currentText(),
                'crs': dialog.get_crs()
            }
            
            # Save settings if requested
            if remember_settings.isChecked():
                self.save_settings(settings)
            else:
                default_settings = {
                    'delimiter': 'Comma (,)',
                    'encoding': 'UTF-8',
                    'geometry_type': 'X/Y columns',
                    'crs': 'EPSG:4326'
                }
                self.save_settings(default_settings)
            
            delimiter = dialog.get_delimiter()
            geometry_type = dialog.get_geometry_type()
            encoding = dialog.get_encoding().lower()
            crs = dialog.get_crs()
            
            # Validate CSV with selected settings
            columns = self.validate_csv(file_path, encoding, delimiter)
            
            # Create layer name from filename
            layer_name = os.path.splitext(os.path.basename(file_path))[0]
            
            if "WKT" in geometry_type:
                # Process WKT geometries and create separate layers
                created_layers = self.process_wkt_geometries(
                    file_path,
                    delimiter,
                    encoding,
                    dialog.get_wkt_column(),
                    crs,
                    layer_name
                )
                
                if created_layers:
                    # Zoom to the extent of all created layers
                    combined_extent = None
                    for layer in created_layers:
                        if layer.wkbType() != QgsWkbTypes.NoGeometry:
                            if combined_extent is None:
                                combined_extent = layer.extent()
                            else:
                                combined_extent.combineExtentWith(layer.extent())
                    
                    if combined_extent:
                        # Transform the extent to the canvas CRS
                        canvas_crs = self.canvas.mapSettings().destinationCrs()
                        if canvas_crs != created_layers[0].crs():
                            transform = QgsCoordinateTransform(created_layers[0].crs(), canvas_crs, self.project)
                            combined_extent = transform.transformBoundingBox(combined_extent)
                        # Set the canvas extent
                        self.canvas.setExtent(combined_extent)
                        self.canvas.refresh()
            else:
                # Create URI with proper path handling
                uri = self.create_layer_uri(
                    file_path,
                    delimiter,
                    encoding,
                    geometry_type,
                    x_col=dialog.get_x_column() if "X/Y columns" in geometry_type else None,
                    y_col=dialog.get_y_column() if "X/Y columns" in geometry_type else None,
                    wkt_col=dialog.get_wkt_column() if "WKT" in geometry_type else None,
                    crs=crs
                )
                
                # Create the source vector layer
                debug_print("Creating source vector layer...")
                source_layer = QgsVectorLayer(uri, layer_name, "delimitedtext")
                
                if not source_layer.isValid():
                    raise Exception(f"Failed to create valid layer from CSV: {source_layer.error().message()}")
                debug_print("Source layer created successfully")
                
                # Create editable memory layer
                memory_layer = self.create_editable_layer(source_layer, layer_name)
                
                # Add layer to project
                debug_print("Adding layer to project...")
                self.project.addMapLayer(memory_layer)
                
                # Zoom to layer extent if it has geometry
                if memory_layer.wkbType() != QgsWkbTypes.NoGeometry:
                    debug_print("Zooming to layer extent...")
                    # Get the layer's extent in its source CRS
                    layer_extent = memory_layer.extent()
                    # Transform the extent to the canvas CRS
                    canvas_crs = self.canvas.mapSettings().destinationCrs()
                    if canvas_crs != memory_layer.crs():
                        transform = QgsCoordinateTransform(memory_layer.crs(), canvas_crs, self.project)
                        layer_extent = transform.transformBoundingBox(layer_extent)
                    # Set the canvas extent
                    self.canvas.setExtent(layer_extent)
                    self.canvas.refresh()
            
            debug_print("File processing completed successfully")
            self.iface.mainWindow().statusBar().showMessage("Layer(s) loaded successfully", 3000)
            
        except Exception as e:
            debug_print(f"Error during processing: {str(e)}")
            raise Exception(f"Error processing CSV file: {str(e)}")
        
    def process_gzipped_csv(self, file_path):
        """Extract and load a gzipped CSV file with user settings"""
        debug_print(f"Starting to process file: {file_path}")
        
        # Create a temporary file for the extracted CSV
        temp_dir = tempfile.gettempdir()
        base_name = os.path.splitext(os.path.basename(file_path))[0]  # Remove .gz
        temp_csv_path = os.path.join(temp_dir, base_name)
        debug_print(f"Temporary file path: {temp_csv_path}")
        
        try:
            # Extract the gzipped file
            debug_print("Extracting gzipped file...")
            with gzip.open(file_path, 'rb') as gz_file:
                with open(temp_csv_path, 'wb') as out_file:
                    out_file.write(gz_file.read())
            debug_print("File extracted successfully")
            
            # Add to temporary files list
            self.temp_files.append(temp_csv_path)
            
            # Process the extracted CSV file
            self.process_csv(temp_csv_path)
            
        except Exception as e:
            debug_print(f"Error during processing: {str(e)}")
            self.cleanup_temp_files()
            raise Exception(f"Error processing CSV.GZ file: {str(e)}")