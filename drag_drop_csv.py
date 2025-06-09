import os
import gzip
import tempfile
import csv
import re
import time
import json
from qgis.PyQt.QtCore import QMimeData, Qt, QObject, QSettings
from qgis.PyQt.QtWidgets import QMessageBox, QCheckBox
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsWkbTypes, QgsCoordinateReferenceSystem,
    QgsFeature, QgsField, QgsFields, QgsGeometry
)
from qgis.gui import QgsLayerTreeView
from .csv_settings_dialog import CsvSettingsDialog


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
                    print(f"Cleaned up temporary file: {temp_file}")
                except Exception as e:
                    print(f"Warning: Could not delete temporary file {temp_file}: {str(e)}")
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
                        print(f"Processing file dropped on main window: {file_path}")
                        if file_path.lower().endswith('.csv.gz'):
                            self.process_gzipped_csv(file_path)
                        else:
                            self.process_csv(file_path)
                        event.accept()
                        return True
                    except Exception as e:
                        print(f"Error processing file {file_path}: {str(e)}")
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
                        print(f"Processing file: {file_path}")
                        if file_path.lower().endswith('.csv.gz'):
                            self.process_gzipped_csv(file_path)
                        else:
                            self.process_csv(file_path)
                        event.accept()
                        return True
                    except Exception as e:
                        print(f"Error processing file {file_path}: {str(e)}")
                        QMessageBox.warning(
                            self.iface.mainWindow(),
                            "Error loading CSV",
                            f"Could not load {file_path}: {str(e)}"
                        )
                        event.ignore()
                        return False
        return False
        
    def detect_encoding(self, file_path):
        """Try to detect file encoding"""
        print("Detecting file encoding...")
        encodings = ['utf-8', 'ascii', 'utf-16', 'windows-1251', 'iso-8859-1']
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    f.readline()
                print(f"Detected encoding: {encoding}")
                return encoding
            except UnicodeDecodeError:
                print(f"Failed to decode with {encoding}")
                continue
        print("Using default encoding: utf-8")
        return 'utf-8'  # Default to UTF-8 if detection fails
        
    def validate_csv(self, file_path, encoding, delimiter):
        """Validate CSV file and return column names"""
        print(f"Validating CSV file with encoding={encoding}, delimiter={delimiter}")
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                # Read first line to check if file is not empty
                first_line = f.readline().strip()
                if not first_line:
                    raise Exception("File is empty")
                print(f"First line: {first_line}")
                
                # Try to parse the first line
                reader = csv.reader([first_line], delimiter=delimiter)
                columns = next(reader)
                
                if not columns:
                    raise Exception("No columns found in CSV")
                
                # Clean column names
                columns = [col.strip('"\'') for col in columns]
                print(f"Found columns: {columns}")
                
                # Read a few more lines to validate data
                f.seek(0)
                reader = csv.reader(f, delimiter=delimiter)
                next(reader)  # Skip header
                
                for i, row in enumerate(reader):
                    if i >= 5:  # Check first 5 rows
                        break
                    if len(row) != len(columns):
                        print(f"Row {i+2}: {row}")
                        print(f"Expected {len(columns)} columns, got {len(row)}")
                        raise Exception(f"Row {i+2} has {len(row)} columns, expected {len(columns)}")
                    print(f"Row {i+2} validated: {row}")
                
                return columns
                
        except Exception as e:
            print(f"CSV validation failed: {str(e)}")
            raise Exception(f"CSV validation failed: {str(e)}")
    
    def create_layer_uri(self, file_path, delimiter, encoding, geometry_type, x_col=None, y_col=None, wkt_col=None, crs=None):
        """Create and validate layer URI"""
        print("Creating layer URI...")
        
        # Convert Windows path to URL format
        file_path = file_path.replace('\\', '/')
        if not file_path.startswith('/'):
            file_path = '/' + file_path
            
        # Build base URI
        uri = f"file://{file_path}?delimiter={delimiter}&encoding={encoding}&detectTypes=yes"
        
        # Add geometry settings
        if geometry_type == "No geometry":
            uri += "&wktField="
        elif "WKT" in geometry_type:
            wkt_type = geometry_type.split()[0].lower()
            uri += f"&wktField={wkt_col}&geometryType={wkt_type}"
        elif "X/Y columns" in geometry_type:
            uri += f"&xField={x_col}&yField={y_col}"
        
        # Add CRS
        if crs:
            uri += f"&crs={crs}"
            
        print(f"Created URI: {uri}")
        
        # Validate URI by creating a test layer
        test_layer = QgsVectorLayer(uri, "test", "delimitedtext")
        if not test_layer.isValid():
            print(f"URI validation failed. Layer error: {test_layer.error().message()}")
            raise Exception(f"Invalid layer URI: {test_layer.error().message()}")
            
        return uri
        
    def create_editable_layer(self, source_layer, layer_name):
        """Create an editable memory layer from a source layer"""
        print("Creating editable memory layer...")
        
        # Get source layer properties
        data_provider = source_layer.dataProvider()
        geometry_type = QgsWkbTypes.displayString(data_provider.wkbType())
        crs = data_provider.sourceCrs().authid()
        fields = data_provider.fields().toList()
        
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
        
        # Add fields
        memory_layer.dataProvider().addAttributes(fields)
        memory_layer.updateFields()
        
        # Copy features
        features = list(source_layer.getFeatures())
        memory_layer.addFeatures(features)
        
        # Commit changes
        memory_layer.commitChanges()
        
        return memory_layer

    def process_csv(self, file_path):
        """Process a regular CSV file"""
        print(f"Starting to process CSV file: {file_path}")
        
        try:
            # Detect encoding
            encoding = self.detect_encoding(file_path)
            
            # Read the CSV to get column names
            print("Reading CSV headers...")
            with open(file_path, 'r', encoding=encoding) as f:
                reader = csv.reader(f)
                try:
                    columns = next(reader)
                except StopIteration:
                    raise Exception("File is empty")
            
            # Show settings dialog
            print("Opening settings dialog...")
            dialog = CsvSettingsDialog(self.iface.mainWindow())
            dialog.set_columns(columns)
            dialog.encoding_combo.setCurrentText(encoding.upper())
            
            # Add "Remember settings" checkbox
            remember_settings = QCheckBox("Remember these settings for next time")
            dialog.layout().insertWidget(dialog.layout().count() - 1, remember_settings)
            
            # Load previous settings if available
            last_settings = self.load_settings()
            if last_settings:
                dialog.delimiter_combo.setCurrentText(last_settings.get('delimiter', 'Comma (,)'))
                dialog.encoding_combo.setCurrentText(last_settings.get('encoding', 'UTF-8'))
                dialog.geometry_combo.setCurrentText(last_settings.get('geometry_type', 'No geometry'))
                if last_settings.get('crs') == 'EPSG:4326':
                    dialog.crs_4326_radio.setChecked(True)
                else:
                    dialog.crs_custom_radio.setChecked(True)
                    dialog.custom_crs_input.setText(last_settings.get('crs', '').replace('EPSG:', ''))
            
            if not dialog.exec_():
                print("User canceled the operation")
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
            
            delimiter = dialog.get_delimiter()
            geometry_type = dialog.get_geometry_type()
            encoding = dialog.get_encoding().lower()
            crs = dialog.get_crs()
            
            # Validate CSV with selected settings
            columns = self.validate_csv(file_path, encoding, delimiter)
            
            # Create layer name from filename
            layer_name = os.path.splitext(os.path.basename(file_path))[0]
            
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
            print("Creating source vector layer...")
            source_layer = QgsVectorLayer(uri, layer_name, "delimitedtext")
            
            if not source_layer.isValid():
                raise Exception(f"Failed to create valid layer from CSV: {source_layer.error().message()}")
            print("Source layer created successfully")
            
            # Create editable memory layer
            memory_layer = self.create_editable_layer(source_layer, layer_name)
            
            # Add layer to project
            print("Adding layer to project...")
            self.project.addMapLayer(memory_layer)
            
            # Zoom to layer extent if it has geometry
            if memory_layer.wkbType() != QgsWkbTypes.NoGeometry:
                print("Zooming to layer extent...")
                self.canvas.setExtent(memory_layer.extent())
                self.canvas.refresh()
            
            print("File processing completed successfully")
            self.iface.mainWindow().statusBar().showMessage("Layer loaded successfully", 3000)
            
        except Exception as e:
            print(f"Error during processing: {str(e)}")
            raise Exception(f"Error processing CSV file: {str(e)}")
        
    def process_gzipped_csv(self, file_path):
        """Extract and load a gzipped CSV file with user settings"""
        print(f"Starting to process file: {file_path}")
        
        # Create a temporary file for the extracted CSV
        temp_dir = tempfile.gettempdir()
        base_name = os.path.splitext(os.path.basename(file_path))[0]  # Remove .gz
        temp_csv_path = os.path.join(temp_dir, base_name)
        print(f"Temporary file path: {temp_csv_path}")
        
        try:
            # Extract the gzipped file
            print("Extracting gzipped file...")
            with gzip.open(file_path, 'rb') as gz_file:
                with open(temp_csv_path, 'wb') as out_file:
                    out_file.write(gz_file.read())
            print("File extracted successfully")
            
            # Add to temporary files list
            self.temp_files.append(temp_csv_path)
            
            # Process the extracted CSV file
            self.process_csv(temp_csv_path)
            
        except Exception as e:
            print(f"Error during processing: {str(e)}")
            self.cleanup_temp_files()
            raise Exception(f"Error processing CSV.GZ file: {str(e)}")