from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QComboBox, QDialogButtonBox,
    QPushButton, QGroupBox, QHBoxLayout
)
from qgis.core import QgsCoordinateReferenceSystem
from qgis.gui import QgsProjectionSelectionDialog

from .h3_utils import H3_CRS

class CsvSettingsDialog(QDialog):
    def __init__(self, parent=None, h3_available=False):
        super().__init__(parent)
        self.h3_available = h3_available
        self.setWindowTitle("CSV Import Settings")
        
        layout = QVBoxLayout()
        
        # Delimiter selection
        layout.addWidget(QLabel("Delimiter:"))
        self.delimiter_combo = QComboBox()
        self.delimiter_combo.addItems(["Comma (,)", "Semicolon (;)", "Tab", "Pipe (|)"])
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
        geometry_types = [
            "No geometry",
            "WKT Geometry",
            "Point (X/Y columns)",
        ]
        if self.h3_available:
            geometry_types.append("H3 Index")
        self.geometry_combo.addItems(geometry_types)
        self.geometry_combo.setCurrentIndex(0)
        layout.addWidget(self.geometry_combo)
        
        # WKT column selection
        self.wkt_column_label = QLabel("WKT Column:")
        self.wkt_column_combo = QComboBox()
        layout.addWidget(self.wkt_column_label)
        layout.addWidget(self.wkt_column_combo)
        self.wkt_column_label.setVisible(False)
        self.wkt_column_combo.setVisible(False)

        # H3 column selection
        self.h3_column_label = QLabel("H3 Column:")
        self.h3_column_combo = QComboBox()
        layout.addWidget(self.h3_column_label)
        layout.addWidget(self.h3_column_combo)
        self.h3_column_label.setVisible(False)
        self.h3_column_combo.setVisible(False)
        
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
        
        # Coordinate System selection (Current CRS + Choose CRS button)
        self.selected_crs = QgsCoordinateReferenceSystem("EPSG:4326")

        self.crs_group = QGroupBox("Coordinate Reference System")
        crs_layout = QVBoxLayout()

        current_layout = QHBoxLayout()
        current_layout.addWidget(QLabel("Current CRS:"))
        self.crs_display_label = QLabel(self.selected_crs.authid())
        current_layout.addWidget(self.crs_display_label)
        current_layout.addStretch(1)
        crs_layout.addLayout(current_layout)

        self.choose_crs_button = QPushButton("Choose CRS")
        self.choose_crs_button.clicked.connect(self.open_crs_chooser)
        crs_layout.addWidget(self.choose_crs_button)

        self.crs_group.setLayout(crs_layout)
        layout.addWidget(self.crs_group)
        
        # Connect signals
        self.geometry_combo.currentTextChanged.connect(self.update_geometry_options)
        self.delimiter_combo.currentTextChanged.connect(self.on_delimiter_changed)
        
        # Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)
        
        self.setLayout(layout)
        
        # Store original columns
        self.original_columns = []
    
    def on_delimiter_changed(self, delimiter_text):
        """Handle delimiter changes by reparsing columns"""
        if not self.original_columns:
            return
            
        # Get the new delimiter
        new_delimiter = self.get_delimiter()
        
        # Reparse the first line with the new delimiter
        first_line = self.original_columns[0]
        if isinstance(first_line, str):
            # If it's a string, split it with the new delimiter
            columns = [col.strip('"\'') for col in first_line.split(new_delimiter)]
        else:
            # If it's already a list, join and resplit
            columns = [col.strip('"\'') for col in new_delimiter.join(first_line).split(new_delimiter)]
            
        # Update the column lists
        self.set_columns(columns)
    
    def update_geometry_options(self, text):
        """Show/hide column options based on geometry type"""
        show_xy = "X/Y columns" in text
        show_wkt = "WKT" in text
        show_h3 = "H3" in text
        
        self.x_column_label.setVisible(show_xy)
        self.x_column_combo.setVisible(show_xy)
        self.y_column_label.setVisible(show_xy)
        self.y_column_combo.setVisible(show_xy)
        
        self.wkt_column_label.setVisible(show_wkt)
        self.wkt_column_combo.setVisible(show_wkt)

        self.h3_column_label.setVisible(show_h3)
        self.h3_column_combo.setVisible(show_h3)

        # H3 geometry is always WGS84; lock CRS selection in that mode
        if show_h3:
            self.set_crs(H3_CRS)
            self.choose_crs_button.setEnabled(False)
        else:
            self.choose_crs_button.setEnabled(True)
    
    def get_delimiter(self):
        """Return the selected delimiter character"""
        text = self.delimiter_combo.currentText()
        if text == "Comma (,)": return ","
        if text == "Semicolon (;)": return ";"
        if text == "Tab": return "\t"
        if text == "Pipe (|)": return "|"
        return ","
    
    def get_encoding(self):
        """Return the selected encoding"""
        return self.encoding_combo.currentText()
    
    def get_crs(self):
        """Return the selected CRS as auth id (e.g., EPSG:4326)"""
        if "H3" in self.geometry_combo.currentText():
            return H3_CRS
        if getattr(self, 'selected_crs', None) and self.selected_crs.isValid():
            return self.selected_crs.authid()
        return "EPSG:4326"

    def set_crs(self, crs_authid):
        """Set the current CRS by auth id and update display"""
        crs = QgsCoordinateReferenceSystem(crs_authid)
        if not crs.isValid():
            crs = QgsCoordinateReferenceSystem("EPSG:4326")
        self.selected_crs = crs
        self.crs_display_label.setText(self.selected_crs.authid())

    def open_crs_chooser(self):
        """Open standard QGIS CRS selection dialog"""
        dlg = QgsProjectionSelectionDialog(self)
        if getattr(self, 'selected_crs', None) and self.selected_crs.isValid():
            dlg.setCrs(self.selected_crs)
        if dlg.exec():
            chosen = dlg.crs()
            if chosen and chosen.isValid():
                self.selected_crs = chosen
                self.crs_display_label.setText(self.selected_crs.authid())
    
    def get_geometry_type(self):
        """Return the selected geometry type"""
        return self.geometry_combo.currentText()
    
    def set_columns(self, columns):
        """Set available columns for X/Y/WKT/H3 selection"""
        # Store original columns for delimiter changes
        self.original_columns = columns
        
        self.x_column_combo.clear()
        self.y_column_combo.clear()
        self.wkt_column_combo.clear()
        self.h3_column_combo.clear()
        
        # Clean column names (remove quotes if present)
        cleaned_columns = [col.strip('"\'') for col in columns]
        
        self.x_column_combo.addItems(cleaned_columns)
        self.y_column_combo.addItems(cleaned_columns)
        self.wkt_column_combo.addItems(cleaned_columns)
        self.h3_column_combo.addItems(cleaned_columns)
        
        # Try to automatically detect columns
        x_cols = []
        y_cols = []
        wkt_cols = []
        h3_cols = []
        
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

            # Check for H3 index columns
            if (
                col_lower in ('h3', 'h3_id', 'h3_index', 'h3_cell', 'hex_id', 'cell_id')
                or any(token in col_lower for token in ('h3_id', 'h3_index', 'h3_cell'))
            ):
                h3_cols.append(col)
        
        # Set geometry type and columns based on detection (WKT > X/Y > H3)
        if wkt_cols:
            for i in range(self.geometry_combo.count()):
                if "WKT Geometry" in self.geometry_combo.itemText(i):
                    self.geometry_combo.setCurrentIndex(i)
                    self.wkt_column_combo.setCurrentText(wkt_cols[0])
                    break
        elif x_cols and y_cols:
            for i in range(self.geometry_combo.count()):
                if "X/Y columns" in self.geometry_combo.itemText(i):
                    self.geometry_combo.setCurrentIndex(i)
                    self.x_column_combo.setCurrentText(x_cols[0])
                    self.y_column_combo.setCurrentText(y_cols[0])
                    break
        elif h3_cols and self.h3_available:
            for i in range(self.geometry_combo.count()):
                if "H3 Index" in self.geometry_combo.itemText(i):
                    self.geometry_combo.setCurrentIndex(i)
                    self.h3_column_combo.setCurrentText(h3_cols[0])
                    break
        else:
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

    def get_h3_column(self):
        return self.h3_column_combo.currentText()
