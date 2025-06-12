from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QComboBox, QDialogButtonBox,
    QLineEdit, QGroupBox, QHBoxLayout, QRadioButton, QButtonGroup
)
from qgis.core import QgsCoordinateReferenceSystem

class CsvSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CSV Import Settings")
        
        layout = QVBoxLayout()
        
        # Delimiter selection
        layout.addWidget(QLabel("Delimiter:"))
        self.delimiter_combo = QComboBox()
        self.delimiter_combo.addItems(["Comma (,)", "Semicolon (;)", "Tab", "Space", "Pipe (|)"])
        self.delimiter_combo.setCurrentIndex(0)
        layout.addWidget(self.delimiter_combo)
        
        # Encoding selection
        layout.addWidget(QLabel("File encoding:"))
        self.encoding_combo = QComboBox()
        self.encoding_combo.addItems(["UTF-8", "ASCII", "UTF-16", "Windows-1251", "ISO-8859-1"])
        self.encoding_combo.setCurrentIndex(0)
        layout.addWidget(self.encoding_combo)
        
        # Geometry selection
        layout.addWidget(QLabel("Geometry type:"))
        self.geometry_combo = QComboBox()
        self.geometry_combo.addItems([
            "No geometry", 
            "WKT Geometry", 
            "Point (X/Y columns)"
        ])
        self.geometry_combo.setCurrentIndex(0)
        layout.addWidget(self.geometry_combo)
        
        # WKT column selection
        self.wkt_column_label = QLabel("WKT Column:")
        self.wkt_column_combo = QComboBox()
        layout.addWidget(self.wkt_column_label)
        layout.addWidget(self.wkt_column_combo)
        self.wkt_column_label.setVisible(False)
        self.wkt_column_combo.setVisible(False)
        
        # X/Y column names
        self.x_column_label = QLabel("X Column:")
        self.x_column_combo = QComboBox()
        self.y_column_label = QLabel("Y Column:")
        self.y_column_combo = QComboBox()
        
        layout.addWidget(self.x_column_label)
        layout.addWidget(self.x_column_combo)
        layout.addWidget(self.y_column_label)
        layout.addWidget(self.y_column_combo)
        
        self.x_column_label.setVisible(False)
        self.x_column_combo.setVisible(False)
        self.y_column_label.setVisible(False)
        self.y_column_combo.setVisible(False)
        
        # Coordinate System selection
        crs_group = QGroupBox("Coordinate Reference System")
        crs_layout = QVBoxLayout()
        
        self.crs_4326_radio = QRadioButton("EPSG:4326 (WGS 84)")
        self.crs_custom_radio = QRadioButton("Custom")
        self.crs_4326_radio.setChecked(True)
        
        crs_layout.addWidget(self.crs_4326_radio)
        crs_layout.addWidget(self.crs_custom_radio)
        
        # Custom CRS input
        custom_crs_layout = QHBoxLayout()
        self.custom_crs_input = QLineEdit()
        self.custom_crs_input.setPlaceholderText("Enter EPSG code (e.g., 4326)")
        self.custom_crs_input.setEnabled(False)
        custom_crs_layout.addWidget(QLabel("EPSG:"))
        custom_crs_layout.addWidget(self.custom_crs_input)
        crs_layout.addLayout(custom_crs_layout)
        
        crs_group.setLayout(crs_layout)
        layout.addWidget(crs_group)
        
        # Connect signals
        self.geometry_combo.currentTextChanged.connect(self.update_geometry_options)
        self.crs_4326_radio.toggled.connect(lambda: self.custom_crs_input.setEnabled(not self.crs_4326_radio.isChecked()))
        
        # Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)
        
        self.setLayout(layout)
    
    def update_geometry_options(self, text):
        """Show/hide column options based on geometry selection"""
        show_xy = "X/Y columns" in text
        show_wkt = "WKT" in text
        
        self.x_column_label.setVisible(show_xy)
        self.x_column_combo.setVisible(show_xy)
        self.y_column_label.setVisible(show_xy)
        self.y_column_combo.setVisible(show_xy)
        
        self.wkt_column_label.setVisible(show_wkt)
        self.wkt_column_combo.setVisible(show_wkt)
    
    def get_delimiter(self):
        """Return the selected delimiter character"""
        text = self.delimiter_combo.currentText()
        if text == "Comma (,)": return ","
        if text == "Semicolon (;)": return ";"
        if text == "Tab": return "\t"
        if text == "Space": return " "
        if text == "Pipe (|)": return "|"
        return ","
    
    def get_encoding(self):
        """Return the selected encoding"""
        return self.encoding_combo.currentText()
    
    def get_crs(self):
        """Return the selected CRS"""
        if self.crs_4326_radio.isChecked():
            return "EPSG:4326"
        else:
            epsg = self.custom_crs_input.text().strip()
            if epsg:
                return f"EPSG:{epsg}"
            return "EPSG:4326"  # Default to WGS84 if invalid input
    
    def get_geometry_type(self):
        """Return the selected geometry type"""
        return self.geometry_combo.currentText()
    
    def set_columns(self, columns):
        """Set available columns for X/Y/WKT selection"""
        self.x_column_combo.clear()
        self.y_column_combo.clear()
        self.wkt_column_combo.clear()
        
        # Clean column names (remove quotes if present)
        cleaned_columns = [col.strip('"\'') for col in columns]
        
        self.x_column_combo.addItems(cleaned_columns)
        self.y_column_combo.addItems(cleaned_columns)
        self.wkt_column_combo.addItems(cleaned_columns)
        
        # Try to automatically detect columns
        x_cols = []
        y_cols = []
        wkt_cols = []
        
        for col in cleaned_columns:
            col_lower = col.lower()
            
            # Check for X/Y coordinate columns
            if any(x in col_lower for x in ['x', 'longitude', 'lon', 'lng', 'easting']):
                x_cols.append(col)
            elif any(x in col_lower for x in ['y', 'latitude', 'lat', 'northing']):
                y_cols.append(col)
            
            # Check for WKT/geometry columns
            if any(x in col_lower for x in ['wkt', 'geometry', 'geom', 'shape', 'the_geom']):
                wkt_cols.append(col)
        
        # Set geometry type and columns based on detection
        if wkt_cols:
            # Prefer WKT if available
            for i in range(self.geometry_combo.count()):
                if "WKT Geometry" in self.geometry_combo.itemText(i):
                    self.geometry_combo.setCurrentIndex(i)
                    self.wkt_column_combo.setCurrentText(wkt_cols[0])
                    break
        elif x_cols and y_cols:
            # Use X/Y if no WKT but coordinates found
            for i in range(self.geometry_combo.count()):
                if "X/Y columns" in self.geometry_combo.itemText(i):
                    self.geometry_combo.setCurrentIndex(i)
                    self.x_column_combo.setCurrentText(x_cols[0])
                    self.y_column_combo.setCurrentText(y_cols[0])
                    break
        else:
            # Default to no geometry if nothing detected
            for i in range(self.geometry_combo.count()):
                if "No geometry" in self.geometry_combo.itemText(i):
                    self.geometry_combo.setCurrentIndex(i)
                    break
    
    def get_x_column(self):
        return self.x_column_combo.currentText()
    
    def get_y_column(self):
        return self.y_column_combo.currentText()
        
    def get_wkt_column(self):
        return self.wkt_column_combo.currentText()