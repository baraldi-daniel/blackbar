import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

MIN_W = 80
MIN_H = 50
RESIZE_MARGIN = 18
DUPLICATE_OFFSET = 24


@dataclass
class MaskInfo:
    mask_id: str
    shape: str
    color: str
    style: str = "Filled"


class MaskWindow(QWidget):
    def __init__(self, manager, info: MaskInfo, x: int, y: int, w: int = 220, h: int = 120):
        super().__init__(None)
        self.manager = manager
        self.info = info
        self.locked = False
        self.dragging = False
        self.resizing = False
        self.drag_offset = QPoint()
        self.start_global = QPoint()
        self.start_geometry = QRect()
        self.selected = False
        self.duplicate_on_drag = False
        self.duplicate_created = False

        self.setWindowTitle(info.mask_id)
        self.setWindowFlags(
            Qt.Window
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.resize(w, h)
        self.move(x, y)
        self.show()

    def mask_path(self):
        rect = self.rect().adjusted(2, 2, -2, -2)
        path = QPainterPath()
        if self.info.shape == "Rectangle":
            path.addRect(rect)
        elif self.info.shape == "Circle":
            path.addEllipse(rect)
        else:
            path.moveTo(rect.center().x(), rect.top())
            path.lineTo(rect.left(), rect.bottom())
            path.lineTo(rect.right(), rect.bottom())
            path.closeSubpath()
        return path

    def is_resize_zone(self, pos):
        return pos.x() >= self.width() - RESIZE_MARGIN and pos.y() >= self.height() - RESIZE_MARGIN

    def is_close_zone(self, pos):
        return (not self.locked) and pos.x() <= 28 and pos.y() <= 28

    def update_cursor(self, pos):
        if self.locked:
            self.setCursor(Qt.ArrowCursor)
        elif self.is_resize_zone(pos):
            self.setCursor(Qt.SizeFDiagCursor)
        else:
            self.setCursor(Qt.SizeAllCursor)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = event.position().toPoint()
        self.manager.select_mask(self.info.mask_id)

        if self.is_close_zone(pos):
            self.manager.delete_mask(self.info.mask_id)
            return

        if self.locked:
            return

        self.raise_()
        self.start_global = event.globalPosition().toPoint()
        self.start_geometry = self.geometry()
        self.duplicate_on_drag = bool(event.modifiers() & Qt.AltModifier)
        self.duplicate_created = False

        if self.is_resize_zone(pos):
            self.resizing = True
        else:
            self.dragging = True
            self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        self.update_cursor(pos)

        if self.locked:
            return

        if self.dragging:
            if self.duplicate_on_drag and not self.duplicate_created:
                clone = self.manager.duplicate_mask(self.info.mask_id, select_new=True)
                if clone:
                    clone.dragging = True
                    clone.drag_offset = self.drag_offset
                    clone.start_global = self.start_global
                    clone.start_geometry = clone.geometry()
                    clone.duplicate_on_drag = False
                    clone.raise_()
                    self.dragging = False
                    self.duplicate_created = True
                    clone.move(event.globalPosition().toPoint() - clone.drag_offset)
                    return
            self.move(event.globalPosition().toPoint() - self.drag_offset)
        elif self.resizing:
            delta = event.globalPosition().toPoint() - self.start_global
            new_w = max(MIN_W, self.start_geometry.width() + delta.x())
            new_h = max(MIN_H, self.start_geometry.height() + delta.y())
            self.resize(new_w, new_h)
            self.update()

    def mouseReleaseEvent(self, event):
        self.dragging = False
        self.resizing = False
        self.duplicate_on_drag = False
        self.duplicate_created = False

    def contextMenuEvent(self, event):
        if not self.locked:
            self.manager.delete_mask(self.info.mask_id)

    def set_locked(self, locked: bool):
        self.locked = locked
        self.update_cursor(QPoint(self.width() // 2, self.height() // 2))
        self.update()

    def set_color(self, color: str):
        self.info.color = color
        self.update()

    def set_shape(self, shape: str):
        self.info.shape = shape
        self.update()

    def set_style(self, style: str):
        self.info.style = style
        self.update()

    def set_selected(self, selected: bool):
        self.selected = selected
        self.update()

    def serialize(self):
        return {
            "shape": self.info.shape,
            "color": self.info.color,
            "style": self.info.style,
            "x": self.x(),
            "y": self.y(),
            "w": self.width(),
            "h": self.height(),
        }

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        path = self.mask_path()

        if self.info.style == "Filled":
            painter.fillPath(path, QColor(self.info.color))
        else:
            painter.fillPath(path, QColor(255, 255, 255, 1))
            painter.setPen(QPen(QColor(self.info.color), 4))
            painter.drawPath(path)

        if self.selected and not self.locked:
            painter.setPen(QPen(QColor(255, 255, 255, 180), 2, Qt.DashLine))
            painter.drawPath(path)

        if not self.locked:
            border = QPen(QColor(255, 255, 255, 150), 1)
            painter.setPen(border)
            painter.drawPath(path)
            painter.setPen(QPen(QColor("white"), 1))
            painter.drawText(10, 18, "✕")
            painter.drawText(self.width() - 18, self.height() - 6, "◢")


class ControlPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Privacy Masks & Highlights")
        self.resize(390, 650)
        
        # Determine the absolute path to the bundled icon
        self.load_window_icon()

        self.counter = 1
        self.locked = False
        self.masks: Dict[str, MaskWindow] = {}
        self.selected_id: Optional[str] = None
        self.updating_combo = False
        self.copied_mask_data: Optional[dict] = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("🛡️ Mask/Outline Settings"))

        combo_layout = QHBoxLayout()
        self.shape_combo = QComboBox()
        self.shape_combo.addItems(["Rectangle", "Circle", "Triangle"])
        
        self.style_combo = QComboBox()
        self.style_combo.addItems(["Filled", "Outline"])
        
        combo_layout.addWidget(self.shape_combo)
        combo_layout.addWidget(self.style_combo)
        layout.addLayout(combo_layout)

        # Labels translated to English
        self.new_btn = QPushButton("+ Create New Mask (Ctrl+N)")
        self.red_outline_btn = QPushButton("⭕ Quick Red Outline")
        
        self.duplicate_btn = QPushButton("⧉ Duplicate Selected (Ctrl+D)")
        self.copy_btn = QPushButton("📋 Copy Selected (Ctrl+C)")
        self.paste_btn = QPushButton("📌 Paste Mask (Ctrl+V)")
        self.color_btn = QPushButton("🎨 Change Color")
        self.lock_btn = QPushButton("🔓 UNLOCKED (Edit Mode) — Ctrl+L")
        self.front_btn = QPushButton("📌 Bring Controller Front")

        layout.addWidget(self.new_btn)
        layout.addWidget(self.red_outline_btn)
        layout.addWidget(self.duplicate_btn)
        layout.addWidget(self.copy_btn)
        layout.addWidget(self.paste_btn)
        layout.addWidget(self.color_btn)
        layout.addWidget(self.lock_btn)
        layout.addWidget(self.front_btn)

        self.listbox = QListWidget()
        layout.addWidget(self.listbox)

        row = QHBoxLayout()
        self.delete_btn = QPushButton("🗑️ Delete")
        self.clear_btn = QPushButton("❌ Clear All")
        row.addWidget(self.delete_btn)
        row.addWidget(self.clear_btn)
        layout.addLayout(row)

        hint = QLabel("Shortcuts: Ctrl+N new shape, Ctrl+D duplicate, Ctrl+C copy, Ctrl+V paste, Ctrl+L lock/unlock, Alt-drag to duplicate while dragging")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.new_btn.clicked.connect(self.add_mask)
        self.red_outline_btn.clicked.connect(self.add_red_outline)
        self.duplicate_btn.clicked.connect(self.duplicate_selected)
        self.copy_btn.clicked.connect(self.copy_selected)
        self.paste_btn.clicked.connect(self.paste_mask)
        self.color_btn.clicked.connect(self.change_color)
        self.lock_btn.clicked.connect(self.toggle_lock)
        self.front_btn.clicked.connect(self.bring_front)
        self.delete_btn.clicked.connect(self.delete_selected)
        self.clear_btn.clicked.connect(self.clear_all)
        
        self.listbox.currentItemChanged.connect(self.on_current_item_changed)
        self.shape_combo.currentTextChanged.connect(self.change_shape_of_selected)
        self.style_combo.currentTextChanged.connect(self.change_style_of_selected)

        self.duplicate_shortcut = QShortcut(QKeySequence("Ctrl+D"), self)
        self.duplicate_shortcut.setContext(Qt.ApplicationShortcut)
        self.duplicate_shortcut.activated.connect(self.duplicate_selected)

        self.lock_shortcut = QShortcut(QKeySequence("Ctrl+L"), self)
        self.lock_shortcut.setContext(Qt.ApplicationShortcut)
        self.lock_shortcut.activated.connect(self.toggle_lock)

        self.copy_shortcut = QShortcut(QKeySequence("Ctrl+C"), self)
        self.copy_shortcut.setContext(Qt.ApplicationShortcut)
        self.copy_shortcut.activated.connect(self.copy_selected)

        self.paste_shortcut = QShortcut(QKeySequence("Ctrl+V"), self)
        self.paste_shortcut.setContext(Qt.ApplicationShortcut)
        self.paste_shortcut.activated.connect(self.paste_mask)

        self.new_shortcut = QShortcut(QKeySequence("Ctrl+N"), self)
        self.new_shortcut.setContext(Qt.ApplicationShortcut)
        self.new_shortcut.activated.connect(self.add_mask)

    def load_window_icon(self):
        """Locates the absolute path to the icon inside the packaged directory."""
        # This resolves the dynamic path to the bundled icon image file
        package_dir = Path(__file__).parent.resolve()
        icon_path = package_dir / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def bring_front(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def next_mask_id(self):
        mask_id = f"Shape {self.counter}"
        self.counter += 1
        return mask_id

    def create_mask_from_data(self, data: dict, select_new: bool = True):
        mask_id = self.next_mask_id()
        style = data.get("style", "Filled")
        info = MaskInfo(mask_id=mask_id, shape=data["shape"], color=data["color"], style=style)
        mask = MaskWindow(self, info, data["x"], data["y"], data["w"], data["h"])
        mask.set_locked(self.locked)
        self.masks[mask_id] = mask
        self.refresh_list()
        if select_new:
            self.select_mask(mask_id)
        return mask

    def add_mask(self):
        # Creates a Filled Black Rectangle
        base_offset = len(self.masks) * 28
        data = {
            "shape": "Rectangle",
            "color": "#000000",
            "style": "Filled",
            "x": 260 + base_offset,
            "y": 150 + base_offset,
            "w": 220,
            "h": 120,
        }
        self.create_mask_from_data(data, select_new=True)

    def add_red_outline(self):
        # Creates an Outlined Red Rectangle
        base_offset = len(self.masks) * 28
        data = {
            "shape": "Rectangle",
            "color": "#FF0000",
            "style": "Outline",
            "x": 260 + base_offset,
            "y": 150 + base_offset,
            "w": 220,
            "h": 120,
        }
        self.create_mask_from_data(data, select_new=True)

    def duplicate_mask(self, source_id: str, select_new: bool = True):
        source = self.masks.get(source_id)
        if not source:
            return None
        data = source.serialize()
        data["x"] += DUPLICATE_OFFSET
        data["y"] += DUPLICATE_OFFSET
        return self.create_mask_from_data(data, select_new=select_new)

    def duplicate_selected(self):
        mask = self.current_mask()
        if mask:
            self.duplicate_mask(mask.info.mask_id, select_new=True)

    def copy_selected(self):
        mask = self.current_mask()
        if not mask:
            return
        self.copied_mask_data = mask.serialize()
        QApplication.clipboard().setText(json.dumps(self.copied_mask_data))

    def paste_mask(self):
        data = None
        text = QApplication.clipboard().text().strip()
        if text:
            try:
                parsed = json.loads(text)
                if all(k in parsed for k in ("shape", "color", "x", "y", "w", "h")):
                    data = parsed
            except Exception:
                data = None
        if data is None:
            data = self.copied_mask_data
        if not data:
            return
        new_data = dict(data)
        new_data["x"] += DUPLICATE_OFFSET
        new_data["y"] += DUPLICATE_OFFSET
        self.create_mask_from_data(new_data, select_new=True)

    def refresh_list(self):
        self.listbox.blockSignals(True)
        self.listbox.clear()
        for mask_id, mask in self.masks.items():
            item = QListWidgetItem(f"{mask_id} [{mask.info.shape} - {mask.info.style}]")
            item.setData(Qt.UserRole, mask_id)
            self.listbox.addItem(item)
        self.restore_selection()
        self.listbox.blockSignals(False)

    def restore_selection(self):
        if not self.selected_id:
            return
        for i in range(self.listbox.count()):
            item = self.listbox.item(i)
            if item.data(Qt.UserRole) == self.selected_id:
                self.listbox.setCurrentItem(item)
                break

    def select_mask(self, mask_id: str):
        if mask_id not in self.masks:
            return
        self.selected_id = mask_id
        for mid, mask in self.masks.items():
            mask.set_selected(mid == mask_id)
        self.restore_selection()
        self.sync_combos_from_selected()

    def on_current_item_changed(self, current, previous):
        if current:
            mask_id = current.data(Qt.UserRole)
            if mask_id in self.masks:
                self.select_mask(mask_id)

    def sync_combos_from_selected(self):
        mask = self.current_mask()
        if not mask:
            return
        self.updating_combo = True
        self.shape_combo.setCurrentText(mask.info.shape)
        self.style_combo.setCurrentText(mask.info.style)
        self.updating_combo = False

    def current_mask(self):
        if self.selected_id and self.selected_id in self.masks:
            return self.masks[self.selected_id]
        return None

    def change_color(self):
        mask = self.current_mask()
        if not mask:
            return
        color = QColorDialog.getColor(QColor(mask.info.color), self, "Choose color")
        if color.isValid():
            mask.set_color(color.name())

    def change_shape_of_selected(self, shape: str):
        if self.updating_combo:
            return
        mask = self.current_mask()
        if not mask:
            return
        mask.set_shape(shape)
        self.refresh_list()
        self.select_mask(mask.info.mask_id)

    def change_style_of_selected(self, style: str):
        if self.updating_combo:
            return
        mask = self.current_mask()
        if not mask:
            return
        mask.set_style(style)
        self.refresh_list()
        self.select_mask(mask.info.mask_id)

    def toggle_lock(self):
        self.locked = not self.locked
        self.lock_btn.setText("🔒 LOCKED (Print Ready) — Ctrl+L" if self.locked else "🔓 UNLOCKED (Edit Mode) — Ctrl+L")
        for mask in self.masks.values():
            mask.set_locked(self.locked)

    def delete_selected(self):
        mask = self.current_mask()
        if mask:
            self.delete_mask(mask.info.mask_id)

    def delete_mask(self, mask_id: str):
        mask = self.masks.pop(mask_id, None)
        if mask:
            mask.close()
        if self.selected_id == mask_id:
            self.selected_id = None
        for remaining in self.masks.values():
            remaining.set_selected(False)
        self.refresh_list()

    def clear_all(self):
        for mask_id in list(self.masks.keys()):
            self.delete_mask(mask_id)


def main():
    """Execution entry point used by the command line interface."""
    app = QApplication(sys.argv)
    panel = ControlPanel()
    panel.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()