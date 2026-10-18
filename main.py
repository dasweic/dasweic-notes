#!/usr/bin/env python3
"""
Dasweic Notes — secure, offline cosmic canvas.
Single-file desktop application for Windows and Linux.

Required: PySide6, cryptography
Optional: Pillow (extra image format support), PySide6-Addons (Qt multimedia is
normally installed with PySide6; playback availability depends on system codecs),
PySide6-QtAds is NOT required. Native drag-and-drop is built into Qt.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import struct
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

try:
    from PySide6.QtCore import Qt, QPointF, QRectF, QSize, QTimer, Signal, QObject, QUrl, QEvent
    from PySide6.QtGui import (
        QAction, QColor, QBrush, QPen, QFont, QPainter, QPainterPath,
        QPolygonF, QKeySequence, QShortcut, QPixmap, QImageReader, QImage, QTransform, QGuiApplication
    )
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QDialog, QVBoxLayout, QHBoxLayout,
        QFormLayout, QLabel, QPushButton, QLineEdit, QMessageBox, QFileDialog,
        QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsTextItem,
        QGraphicsRectItem, QGraphicsEllipseItem, QGraphicsLineItem,
        QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsPolygonItem,
        QToolBar, QStatusBar, QColorDialog, QSpinBox, QComboBox, QTextEdit,
        QCheckBox, QInputDialog, QProgressDialog, QMenu, QSplitter, QFrame,
        QFontComboBox, QSlider, QScrollArea, QGraphicsEffect, QPlainTextEdit, QDialogButtonBox, QSplashScreen
    )
except ImportError as exc:
    print("Dasweic Notes needs PySide6. Install it with: python -m pip install PySide6 cryptography")
    raise

# Optional Qt playback/viewer modules. Install PySide6-Addons if these are missing.
try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PySide6.QtMultimediaWidgets import QVideoWidget
    MEDIA_AVAILABLE = True
except ImportError:
    QMediaPlayer = QAudioOutput = QVideoWidget = None
    MEDIA_AVAILABLE = False

# Recording APIs are optional and vary by the installed Qt Multimedia backend.
try:
    from PySide6.QtMultimedia import (
        QMediaDevices, QAudioInput, QCamera, QMediaCaptureSession, QMediaRecorder, QMediaFormat
    )
    try:
        from PySide6.QtMultimedia import QScreenCapture
    except ImportError:
        QScreenCapture = None
    CAPTURE_AVAILABLE = True
except ImportError:
    QMediaDevices = QAudioInput = QCamera = QMediaCaptureSession = QMediaRecorder = QMediaFormat = None
    QScreenCapture = None
    CAPTURE_AVAILABLE = False

try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
    PDF_AVAILABLE = True
except ImportError:
    QPdfDocument = QPdfView = None
    PDF_AVAILABLE = False

# Optional fallback PDF renderer. This keeps PDF viewing available on systems where
# QtPdf modules are not bundled with the installed PySide6 distribution.
try:
    import fitz  # PyMuPDF
    FITZ_AVAILABLE = True
except ImportError:
    fitz = None
    FITZ_AVAILABLE = False

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import hashes, hmac as crypto_hmac
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
except ImportError:
    print("Dasweic Notes needs cryptography. Install it with: python -m pip install cryptography")
    raise

APP_NAME = "Dasweic Notes"
APP_VERSION = 1
EXTENSION = ".dasweic"
MAGIC = b"DASWEIC1"
CHUNK = 1024 * 1024
CONFIG_DIR = Path.home() / ".dasweic_notes"
CONFIG_FILE = CONFIG_DIR / "settings.json"
DEFAULT_PASSWORD = "djsar"

BG = "#080b13"
PANEL = "#111827"
PANEL2 = "#151e30"
BORDER = "#28344b"
TEXT = "#e5edf8"
MUTED = "#9ba9c1"
CYAN = "#71d9e8"
VIOLET = "#b7a2ff"
ACCENT = "#83d9e8"


def derive_key(password: str, salt: bytes, length: int = 64) -> bytes:
    """PBKDF2-HMAC-SHA256 key derivation; first half encrypts, second authenticates."""
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=length, salt=salt, iterations=600_000)
    return kdf.derive(password.encode("utf-8"))


def stream_encrypt(src: Path, dst: Path, password: str, progress_callback=None) -> None:
    """Authenticated encrypt-then-MAC file container; plaintext is processed in chunks."""
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(16)
    key = derive_key(password, salt)
    enc_key, mac_key = key[:32], key[32:]
    header = MAGIC + salt + nonce
    encryptor = Cipher(algorithms.AES(enc_key), modes.CTR(nonce)).encryptor()
    mac = crypto_hmac.HMAC(mac_key, hashes.SHA256())
    mac.update(header)
    total = max(1, src.stat().st_size)
    processed = 0
    with src.open("rb") as fin, dst.open("wb") as fout:
        fout.write(header)
        while True:
            block = fin.read(CHUNK)
            if not block:
                break
            encrypted = encryptor.update(block)
            fout.write(encrypted)
            mac.update(encrypted)
            processed += len(block)
            if progress_callback:
                progress_callback(min(95, 45 + int(processed * 50 / total)), "Encrypting and securing project…")
        fout.write(encryptor.finalize())
        fout.write(mac.finalize())


def stream_decrypt(src: Path, dst: Path, password: str, progress_callback=None) -> None:
    """Authenticate the complete container before writing any decrypted bytes."""
    size = src.stat().st_size
    if size < len(MAGIC) + 16 + 16 + 32:
        raise ValueError("This file is too short to be a valid .dasweic project.")
    with src.open("rb") as f:
        header = f.read(40)
        if header[:8] != MAGIC:
            raise ValueError("This is not a supported Dasweic Notes project.")
        salt, nonce = header[8:24], header[24:40]
        key = derive_key(password, salt)
        enc_key, mac_key = key[:32], key[32:]
        encrypted_len = size - 40 - 32
        f.seek(size - 32)
        supplied_tag = f.read(32)
        f.seek(0)
        mac = crypto_hmac.HMAC(mac_key, hashes.SHA256())
        remaining = size - 32
        authenticated = 0
        while remaining:
            block = f.read(min(CHUNK, remaining))
            if not block:
                raise ValueError("Project ended unexpectedly.")
            mac.update(block)
            remaining -= len(block)
            authenticated += len(block)
            if progress_callback:
                progress_callback(min(45, int(authenticated * 45 / max(1, size - 32))), "Verifying project integrity…")
        try:
            mac.verify(supplied_tag)
        except Exception as exc:
            raise ValueError("Wrong project password or the project has been damaged/tampered with.") from exc
        f.seek(40)
        decryptor = Cipher(algorithms.AES(enc_key), modes.CTR(nonce)).decryptor()
        with dst.open("wb") as out:
            remaining = encrypted_len
            decrypted = 0
            while remaining:
                block = f.read(min(CHUNK, remaining))
                if not block:
                    raise ValueError("Project ended unexpectedly.")
                out.write(decryptor.update(block))
                remaining -= len(block)
                decrypted += len(block)
                if progress_callback:
                    progress_callback(45 + min(35, int(decrypted * 35 / max(1, encrypted_len))), "Decrypting project data…")
            out.write(decryptor.finalize())


def password_verifier(password: str, salt: str | None = None) -> dict:
    raw_salt = bytes.fromhex(salt) if salt else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), raw_salt, 600_000)
    return {"salt": raw_salt.hex(), "verifier": digest.hex(), "iterations": 600_000}


def verify_password(password: str, record: dict) -> bool:
    try:
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(record["salt"]),
                                     int(record.get("iterations", 600_000))).hex()
        return hmac.compare_digest(actual, record["verifier"])
    except (KeyError, ValueError, TypeError):
        return False


def load_auth() -> dict:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text("utf-8"))
            if isinstance(data.get("auth"), dict):
                return data
        except (OSError, ValueError):
            pass
    data = {"auth": password_verifier(DEFAULT_PASSWORD), "autosave": False}
    save_auth(data)
    return data


def save_auth(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, CONFIG_FILE)


def styled_button(text: str, primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setMinimumHeight(34)
    if primary:
        b.setStyleSheet("QPushButton{background:#246879;color:#f5fcff;border:1px solid #4aa8b7;border-radius:10px;padding:7px 14px;font-weight:600} QPushButton:hover{background:#2d7d8e} QPushButton:pressed{background:#174b59}")
    else:
        b.setStyleSheet("QPushButton{background:#172236;color:#dce8f8;border:1px solid #33415b;border-radius:10px;padding:7px 12px} QPushButton:hover{background:#22324a;border-color:#6b9cae} QPushButton:focus{border:1px solid #83d9e8}")
    return b


class PasswordDialog(QDialog):
    def __init__(self, title: str, prompt: str, parent=None, confirm=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(390)
        layout = QVBoxLayout(self)
        heading = QLabel(title)
        heading.setObjectName("dialogTitle")
        layout.addWidget(heading)
        layout.addWidget(QLabel(prompt))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Password")
        self.password.setMinimumHeight(40)
        layout.addWidget(self.password)
        self.confirm = None
        if confirm:
            self.confirm = QLineEdit()
            self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
            self.confirm.setPlaceholderText("Confirm password")
            self.confirm.setMinimumHeight(40)
            layout.addWidget(self.confirm)
        row = QHBoxLayout()
        row.addStretch()
        cancel = styled_button("Cancel")
        ok = styled_button("Continue", True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        layout.addLayout(row)
        self.password.returnPressed.connect(self._accept)
        self.setStyleSheet(DIALOG_STYLE)

    def _accept(self):
        if not self.password.text():
            QMessageBox.warning(self, APP_NAME, "Enter a password to continue.")
            return
        if self.confirm is not None and self.password.text() != self.confirm.text():
            QMessageBox.warning(self, APP_NAME, "The passwords do not match.")
            return
        self.accept()

    def value(self) -> str:
        return self.password.text()


DIALOG_STYLE = f"""
QDialog {{ background:{PANEL}; color:{TEXT}; }}
QLabel {{ color:{TEXT}; }}
QLabel#dialogTitle {{ font-size:20px; font-weight:700; color:#dffaff; padding:5px 0; }}
QLineEdit,QTextEdit,QComboBox,QSpinBox {{ background:#0b1220; color:{TEXT}; border:1px solid #33415b; border-radius:9px; padding:8px; selection-background-color:#286777; }}
QLineEdit:focus,QTextEdit:focus,QComboBox:focus {{ border:1px solid {CYAN}; }}
"""


class TextDialog(QDialog):
    def __init__(self, parent=None, data: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Text on canvas")
        self.resize(650, 520)
        data = data or {}
        layout = QVBoxLayout(self)
        title = QLabel("Create a note" if not data else "Edit note")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        self.editor = QTextEdit()
        self.editor.setAcceptRichText(False)
        self.editor.setPlaceholderText("Write your thoughts…\n\nMultiple paragraphs and Unicode are supported.")
        self.editor.setPlainText(data.get("text", ""))
        layout.addWidget(self.editor, 1)
        form = QHBoxLayout()
        self.font = QFontComboBox()
        self.font.setCurrentFont(QFont(data.get("font", "Noto Sans")))
        self.size = QSpinBox()
        self.size.setRange(7, 96)
        self.size.setValue(int(data.get("size", 18)))
        self.color = QColor(data.get("color", "#e5edf8"))
        self.color_btn = styled_button("Text color")
        self.color_btn.clicked.connect(self.pick_color)
        self.bold = QCheckBox("Bold"); self.bold.setChecked(bool(data.get("bold", False)))
        self.italic = QCheckBox("Italic"); self.italic.setChecked(bool(data.get("italic", False)))
        self.underline = QCheckBox("Underline"); self.underline.setChecked(bool(data.get("underline", False)))
        self.strike = QCheckBox("Strike"); self.strike.setChecked(bool(data.get("strike", False)))
        self.align = QComboBox(); self.align.addItems(["Left", "Center", "Right"])
        self.align.setCurrentText(data.get("align", "Left"))
        form.addWidget(self.font, 2); form.addWidget(self.size); form.addWidget(self.color_btn)
        layout.addLayout(form)
        flags = QHBoxLayout()
        for w in (self.bold, self.italic, self.underline, self.strike, self.align):
            flags.addWidget(w)
        layout.addLayout(flags)
        buttons = QHBoxLayout(); buttons.addStretch()
        cancel = styled_button("Cancel"); add = styled_button("Add to canvas", True)
        cancel.clicked.connect(self.reject); add.clicked.connect(self.accept)
        buttons.addWidget(cancel); buttons.addWidget(add); layout.addLayout(buttons)
        self.setStyleSheet(DIALOG_STYLE + f"QCheckBox{{color:{TEXT};padding:4px}}")
        self.editor.setFocus()

    def pick_color(self):
        c = QColorDialog.getColor(self.color, self, "Choose text color")
        if c.isValid():
            self.color = c

    def result_data(self):
        return {"text": self.editor.toPlainText(), "font": self.font.currentFont().family(),
                "size": self.size.value(), "color": self.color.name(), "bold": self.bold.isChecked(),
                "italic": self.italic.isChecked(), "underline": self.underline.isChecked(),
                "strike": self.strike.isChecked(), "align": self.align.currentText()}


class InvertColorsEffect(QGraphicsEffect):
    """Invert rendered widget pixels while preserving alpha, useful for PDF night mode."""
    def draw(self, painter):
        result = self.sourcePixmap(Qt.CoordinateSystem.LogicalCoordinates,
                                   QGraphicsEffect.PadToEffectiveBoundingRect)
        if isinstance(result, tuple):
            pixmap, offset = result
        else:
            pixmap, offset = result, QPointF(0, 0)
        if pixmap.isNull():
            return
        image = pixmap.toImage()
        image.invertPixels(QImage.InvertMode.InvertRgb)
        painter.drawImage(offset, image)


class FallbackPdfViewer(QWidget):
    """PDF reader fallback powered by PyMuPDF when QtPdf is unavailable."""
    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path
        self.document = fitz.open(path)
        self.page_index = 0
        self.zoom = 1.25
        self.inverted = False
        self._base_image = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        controls = QHBoxLayout()
        self.prev_button = styled_button("‹ Previous")
        self.next_button = styled_button("Next ›")
        self.page_label = QLabel()
        self.page_label.setStyleSheet(f"color:{MUTED};padding:4px 8px;")
        self.zoom_out_button = styled_button("−")
        self.zoom_in_button = styled_button("+")
        self.fit_button = styled_button("Fit width")
        self.invert_check = QCheckBox("Invert colors / Night mode")
        controls.addWidget(self.prev_button)
        controls.addWidget(self.next_button)
        controls.addWidget(self.page_label)
        controls.addStretch()
        controls.addWidget(self.invert_check)
        controls.addWidget(self.zoom_out_button)
        controls.addWidget(self.zoom_in_button)
        controls.addWidget(self.fit_button)
        layout.addLayout(controls)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.scroll.setStyleSheet(f"QScrollArea{{background:#202637;border:1px solid {BORDER};border-radius:10px}}")
        self.page_image = QLabel()
        self.page_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_image.setStyleSheet("background:white;border:0;padding:8px")
        self.scroll.setWidget(self.page_image)
        layout.addWidget(self.scroll, 1)

        self.prev_button.clicked.connect(lambda: self.show_page(self.page_index - 1))
        self.next_button.clicked.connect(lambda: self.show_page(self.page_index + 1))
        self.zoom_out_button.clicked.connect(lambda: self.set_zoom(self.zoom / 1.2))
        self.zoom_in_button.clicked.connect(lambda: self.set_zoom(self.zoom * 1.2))
        self.fit_button.clicked.connect(self.fit_width)
        self.invert_check.toggled.connect(self.toggle_invert)
        self.show_page(0)

    def show_page(self, index):
        if not self.document: return
        self.page_index = max(0, min(len(self.document) - 1, int(index)))
        page = self.document.load_page(self.page_index)
        pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom), alpha=False)
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        if self.inverted:
            image.invertPixels(QImage.InvertMode.InvertRgb)
        self._base_image = QPixmap.fromImage(image)
        self.page_image.setPixmap(self._base_image)
        self.page_image.resize(self._base_image.size())
        self.page_label.setText(f"Page {self.page_index + 1} / {len(self.document)}  ·  {round(self.zoom * 100)}%")
        self.prev_button.setEnabled(self.page_index > 0)
        self.next_button.setEnabled(self.page_index < len(self.document) - 1)

    def set_zoom(self, value):
        self.zoom = max(0.35, min(4.0, float(value)))
        self.show_page(self.page_index)

    def fit_width(self):
        if not self.document: return
        page = self.document.load_page(self.page_index)
        available = max(320, self.scroll.viewport().width() - 32)
        self.zoom = max(0.35, min(4.0, available / max(1, page.rect.width)))
        self.show_page(self.page_index)

    def toggle_invert(self, enabled):
        self.inverted = bool(enabled)
        self.show_page(self.page_index)

    def closeEvent(self, event):
        try:
            self.document.close()
        except Exception:
            pass
        super().closeEvent(event)


class AttachmentViewer(QDialog):
    """Polished in-app PDF, video and audio viewer/player."""
    VIDEO_EXTS = {".mp4", ".webm", ".avi", ".mkv", ".mov", ".m4v", ".mpeg", ".mpg", ".3gp", ".ogv"}
    AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".wma", ".aiff"}

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.player = None
        self.audio_output = None
        self.video_widget = None
        self._seeking = False
        self.setWindowTitle(f"Dasweic Notes · {self.path.name}")
        self.resize(1120, 760)
        self.setMinimumSize(680, 460)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        header = QHBoxLayout()
        title_col = QVBoxLayout()
        heading = QLabel(self.path.name)
        heading.setStyleSheet(f"font-size:17px;font-weight:700;color:{TEXT};")
        heading.setWordWrap(True)
        subtitle = QLabel("DASWEIC MEDIA PLAYER  ·  OFFLINE PLAYBACK")
        subtitle.setStyleSheet(f"font-size:10px;letter-spacing:1px;color:{MUTED};")
        title_col.addWidget(heading)
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)
        self.status_label = QLabel("READY")
        self.status_label.setStyleSheet(f"color:{CYAN};font-size:10px;font-weight:700;padding:6px 10px;border:1px solid {BORDER};border-radius:8px;")
        header.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        suffix = self.path.suffix.lower()
        if suffix == ".pdf":
            if FITZ_AVAILABLE:
                try:
                    self.fallback_pdf = FallbackPdfViewer(str(self.path), self)
                    root.addWidget(self.fallback_pdf, 1)
                    self.status_label.setText("PDF READY")
                except Exception as exc:
                    root.addWidget(self._notice("Could not open this PDF.", f"The file may be damaged or unsupported.\n\n{exc}"), 1)
            elif not PDF_AVAILABLE:
                root.addWidget(self._notice("PDF viewer modules are unavailable.", "Install with: python -m pip install --upgrade PySide6 PySide6-Addons pymupdf"), 1)
            else:
                self.pdf_document = QPdfDocument(self)
                status = self.pdf_document.load(str(self.path))
                if status != QPdfDocument.Status.Ready:
                    root.addWidget(self._notice("Could not open this PDF. It may be damaged, password-protected, or unsupported."), 1)
                else:
                    self.pdf_view = QPdfView(self)
                    self.pdf_view.setDocument(self.pdf_document)
                    self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
                    self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
                    root.addWidget(self.pdf_view, 1)
                    pdf_controls = QHBoxLayout()
                    pdf_controls.addWidget(QLabel("PDF DOCUMENT"))
                    pdf_controls.addStretch()
                    self.invert_pdf = QCheckBox("Invert colors / Night mode")
                    self.invert_pdf.setToolTip("Toggle dark-page reading mode; text and page colors are inverted.")
                    self.pdf_invert_effect = InvertColorsEffect(self.pdf_view)
                    self.invert_pdf.toggled.connect(self._toggle_pdf_invert)
                    pdf_controls.addWidget(self.invert_pdf)
                    zoom_out = styled_button("−")
                    zoom_in = styled_button("+")
                    fit = styled_button("Fit width")
                    zoom_out.setToolTip("Zoom out")
                    zoom_in.setToolTip("Zoom in")
                    zoom_out.clicked.connect(lambda: self.pdf_view.setZoomFactor(max(0.25, self.pdf_view.zoomFactor() / 1.2)))
                    zoom_in.clicked.connect(lambda: self.pdf_view.setZoomFactor(min(5.0, self.pdf_view.zoomFactor() * 1.2)))
                    fit.clicked.connect(lambda: self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth))
                    pdf_controls.addWidget(zoom_out); pdf_controls.addWidget(zoom_in); pdf_controls.addWidget(fit)
                    root.addLayout(pdf_controls)
        elif suffix in self.VIDEO_EXTS | self.AUDIO_EXTS:
            if not MEDIA_AVAILABLE:
                root.addWidget(self._notice("Qt Multimedia is unavailable, so audio/video playback cannot start.", "Install with: python -m pip install --upgrade PySide6 PySide6-Addons"), 1)
            else:
                self.player = QMediaPlayer(self)
                self.audio_output = QAudioOutput(self)
                self.player.setAudioOutput(self.audio_output)
                if suffix in self.VIDEO_EXTS:
                    self.video_widget = QVideoWidget(self)
                    self.video_widget.setMinimumHeight(220)
                    self.video_widget.setStyleSheet("background:#03060b;border:1px solid #26334a;border-radius:12px;")
                    self.player.setVideoOutput(self.video_widget)
                    root.addWidget(self.video_widget, 1)
                    self.video_widget.installEventFilter(self)
                else:
                    visual = QFrame()
                    visual.setMinimumHeight(180)
                    visual.setStyleSheet(f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {PANEL2},stop:1 #080d18);border:1px solid {BORDER};border-radius:14px;")
                    visual_layout = QVBoxLayout(visual)
                    glyph = QLabel("♫")
                    glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    glyph.setStyleSheet(f"font-size:68px;color:{CYAN};border:0;background:transparent;")
                    audio_name = QLabel(self.path.name)
                    audio_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    audio_name.setWordWrap(True)
                    audio_name.setStyleSheet(f"font-size:15px;font-weight:600;color:{TEXT};border:0;background:transparent;")
                    visual_layout.addStretch(); visual_layout.addWidget(glyph); visual_layout.addWidget(audio_name); visual_layout.addStretch()
                    root.addWidget(visual, 1)

                self.position = QSlider(Qt.Orientation.Horizontal)
                self.position.setRange(0, 0)
                self.position.setToolTip("Seek: drag or click anywhere on the timeline")
                root.addWidget(self.position)
                time_row = QHBoxLayout()
                self.current_time = QLabel("00:00")
                self.total_time = QLabel("00:00")
                for label in (self.current_time, self.total_time):
                    label.setStyleSheet(f"color:{MUTED};font-size:11px;font-variant-numeric:tabular-nums;")
                time_row.addWidget(self.current_time); time_row.addStretch(); time_row.addWidget(self.total_time)
                root.addLayout(time_row)

                controls = QHBoxLayout()
                controls.setSpacing(8)
                self.back_button = styled_button("−10s")
                self.play_button = styled_button("▶  Play", True)
                self.forward_button = styled_button("+10s")
                self.stop_button = styled_button("■  Stop")
                self.back_button.setToolTip("Seek backward 10 seconds (Left arrow)")
                self.play_button.setToolTip("Play/Pause (Space)")
                self.forward_button.setToolTip("Seek forward 10 seconds (Right arrow)")
                self.stop_button.setToolTip("Stop playback and return to start")
                controls.addWidget(self.back_button); controls.addWidget(self.play_button); controls.addWidget(self.forward_button); controls.addWidget(self.stop_button)
                controls.addStretch()
                self.mute_button = styled_button("🔊")
                self.mute_button.setToolTip("Mute/unmute (M)")
                self.volume = QSlider(Qt.Orientation.Horizontal)
                self.volume.setRange(0, 100); self.volume.setValue(80); self.volume.setFixedWidth(100)
                self.volume.setToolTip("Volume")
                controls.addWidget(self.mute_button); controls.addWidget(self.volume)
                controls.addWidget(QLabel("Speed"))
                self.speed = QComboBox()
                for rate in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0):
                    self.speed.addItem(f"{rate:g}×", rate)
                self.speed.setCurrentIndex(3)
                self.speed.setToolTip("Playback speed")
                self.speed.setFixedWidth(76)
                controls.addWidget(self.speed)
                if self.video_widget:
                    self.fullscreen_button = styled_button("⛶")
                    self.fullscreen_button.setToolTip("Toggle video fullscreen (F)")
                    controls.addWidget(self.fullscreen_button)
                    self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
                root.addLayout(controls)

                self.message_label = QLabel("Tip: Space play/pause · ←/→ seek 5s · ↑/↓ volume · M mute · F fullscreen")
                self.message_label.setWordWrap(True)
                self.message_label.setStyleSheet(f"color:{MUTED};font-size:10px;padding:4px 2px;")
                root.addWidget(self.message_label)

                self.play_button.clicked.connect(self.toggle_play)
                self.back_button.clicked.connect(lambda: self.seek_relative(-10000))
                self.forward_button.clicked.connect(lambda: self.seek_relative(10000))
                self.stop_button.clicked.connect(self.stop_playback)
                self.position.sliderPressed.connect(self._begin_seek)
                self.position.sliderReleased.connect(self._finish_seek)
                self.position.sliderMoved.connect(self._preview_position)
                self.volume.valueChanged.connect(self.set_volume)
                self.mute_button.clicked.connect(self.toggle_mute)
                self.speed.currentIndexChanged.connect(self.set_speed)
                self.player.durationChanged.connect(self.duration_changed)
                self.player.positionChanged.connect(self.position_changed)
                self.player.playbackStateChanged.connect(self.playback_state_changed)
                self.player.mediaStatusChanged.connect(self.media_status_changed)
                self.player.errorOccurred.connect(self.media_error)
                self.player.setSource(QUrl.fromLocalFile(str(self.path.resolve())))
                self.audio_output.setVolume(0.8)
                self.player.setPlaybackRate(1.0)
                self.player.play()
        else:
            root.addWidget(self._notice("This file type has no built-in viewer."), 1)

        footer = QHBoxLayout()
        footer.addStretch()
        close = styled_button("Close player")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        root.addLayout(footer)
        self.setStyleSheet(DIALOG_STYLE + f"QLabel{{color:{TEXT}}} QSlider::groove:horizontal{{height:5px;background:#28344b;border-radius:2px}} QSlider::sub-page:horizontal{{background:{CYAN};border-radius:2px}} QSlider::handle:horizontal{{background:#f3fcff;border:2px solid {CYAN};width:12px;margin:-5px 0;border-radius:7px}} QComboBox{{background:{PANEL2};color:{TEXT};border:1px solid {BORDER};border-radius:8px;padding:6px}}")

        # Dialog-local keyboard controls work while the player window is focused.
        self._shortcuts = []
        if self.player is not None:
            self._bind_shortcut(Qt.Key.Key_Space, self.toggle_play)
            self._bind_shortcut(Qt.Key.Key_Left, lambda: self.seek_relative(-5000))
            self._bind_shortcut(Qt.Key.Key_Right, lambda: self.seek_relative(5000))
            self._bind_shortcut(Qt.Key.Key_Up, lambda: self.volume.setValue(min(100, self.volume.value() + 5)))
            self._bind_shortcut(Qt.Key.Key_Down, lambda: self.volume.setValue(max(0, self.volume.value() - 5)))
            self._bind_shortcut("M", self.toggle_mute)
            if self.video_widget:
                self._bind_shortcut("F", self.toggle_fullscreen)

    def _toggle_pdf_invert(self, enabled):
        if not hasattr(self, "pdf_view"):
            return
        if enabled:
            self.pdf_view.setGraphicsEffect(self.pdf_invert_effect)
            self.status_label.setText("NIGHT MODE ON")
        else:
            self.pdf_view.setGraphicsEffect(None)
            self.status_label.setText("READY")

    def _bind_shortcut(self, key, callback):
        shortcut = QShortcut(QKeySequence(key), self)
        shortcut.activated.connect(callback)
        self._shortcuts.append(shortcut)

    def _notice(self, heading, detail=""):
        frame = QFrame()
        frame.setStyleSheet(f"background:{PANEL2};border:1px solid {BORDER};border-radius:12px;")
        lay = QVBoxLayout(frame)
        h = QLabel(heading); h.setWordWrap(True); h.setStyleSheet(f"font-size:16px;font-weight:600;color:{TEXT};border:0;")
        lay.addStretch(); lay.addWidget(h, 0, Qt.AlignmentFlag.AlignCenter)
        if detail:
            d = QLabel(detail); d.setWordWrap(True); d.setAlignment(Qt.AlignmentFlag.AlignCenter); d.setStyleSheet(f"color:{MUTED};border:0;")
            lay.addWidget(d)
        lay.addStretch()
        return frame

    def toggle_play(self):
        if not self.player:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def stop_playback(self):
        if self.player:
            self.player.stop()
            self.player.setPosition(0)

    def playback_state_changed(self, state):
        if not self.player:
            return
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setText("❚❚  Pause" if playing else "▶  Play")
        self.status_label.setText("PLAYING" if playing else "PAUSED" if state == QMediaPlayer.PlaybackState.PausedState else "READY")

    def duration_changed(self, duration):
        self.position.setRange(0, max(0, duration))
        self.total_time.setText(self._fmt(duration))

    def position_changed(self, position):
        if not self.position.isSliderDown():
            self.position.setValue(position)
        self.current_time.setText(self._fmt(position))

    def _fmt(self, ms):
        seconds = max(0, int(ms / 1000))
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"

    def _begin_seek(self):
        self._seeking = True

    def _preview_position(self, position):
        self.current_time.setText(self._fmt(position))

    def _finish_seek(self):
        if self.player:
            self.player.setPosition(self.position.value())
        self._seeking = False

    def seek_relative(self, delta_ms):
        if self.player:
            self.player.setPosition(max(0, min(self.player.duration(), self.player.position() + delta_ms)))

    def set_volume(self, value):
        if self.audio_output:
            self.audio_output.setVolume(value / 100.0)
            self.mute_button.setText("🔇" if value == 0 else "🔈" if value < 35 else "🔉" if value < 70 else "🔊")

    def toggle_mute(self):
        if not self.audio_output:
            return
        if self.audio_output.isMuted():
            self.audio_output.setMuted(False)
            self.mute_button.setText("🔊")
        else:
            self.audio_output.setMuted(True)
            self.mute_button.setText("🔇")

    def set_speed(self, index):
        if self.player and index >= 0:
            self.player.setPlaybackRate(float(self.speed.itemData(index)))

    def media_status_changed(self, status):
        if not hasattr(self, "status_label"):
            return
        if status == QMediaPlayer.MediaStatus.LoadingMedia:
            self.status_label.setText("LOADING")
        elif status == QMediaPlayer.MediaStatus.LoadedMedia:
            self.status_label.setText("READY")
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.status_label.setText("ENDED")
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.status_label.setText("UNSUPPORTED")

    def media_error(self, error, error_string):
        if error_string:
            self.status_label.setText("PLAYBACK ERROR")
            self.message_label.setText(f"Playback error: {error_string}. Codec support depends on your OS and Qt Multimedia backend.")

    def toggle_fullscreen(self):
        if not self.video_widget:
            return
        if self.isFullScreen():
            self.showNormal()
            self.video_widget.setParent(self)
        else:
            self.showFullScreen()

    def eventFilter(self, watched, event):
        if watched is self.video_widget and event.type() == QEvent.Type.MouseButtonDblClick:
            self.toggle_fullscreen()
            return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event):
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())
        super().closeEvent(event)


class CanvasItem(QGraphicsItem):
    """Logical item wrapper for non-text canvas objects and attachment cards."""
    def __init__(self, kind: str, data: dict, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.data = data
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setPos(float(data.get("x", 0)), float(data.get("y", 0)))
        self.w = float(data.get("w", 240))
        self.h = float(data.get("h", 130))
        self.stroke = QColor(data.get("stroke", CYAN))
        self.fill = QColor(data.get("fill", "#142033"))
        self.width = float(data.get("width", 3))
        self.points = [QPointF(float(p[0]), float(p[1])) for p in data.get("points", [])]
        self.pixmap = QPixmap()
        path = data.get("path")
        if kind == "image" and path and Path(path).exists():
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            image = reader.read()
            if not image.isNull():
                self.pixmap = QPixmap.fromImage(image)
                # Preserve saved/resized preview dimensions exactly. If no dimensions
                # were saved, fit the full-resolution image into a sensible preview box.
                if not data.get("w") or not data.get("h"):
                    iw, ih = float(self.pixmap.width()), float(self.pixmap.height())
                    scale = min(420.0 / max(iw, 1.0), 300.0 / max(ih, 1.0), 1.0)
                    self.w, self.h = iw * scale, ih * scale
        self.setZValue(float(data.get("z", 1)))

    def boundingRect(self):
        pad = max(12, self.width + 6)
        if self.kind == "stroke" and self.points:
            r = QRectF(self.points[0], self.points[0])
            for p in self.points[1:]:
                r = r.united(QRectF(p, p))
            return r.adjusted(-pad, -pad, pad, pad)
        return QRectF(0, 0, self.w, self.h).adjusted(-pad, -pad, pad, pad)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(self.stroke, self.width, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        if self.kind == "highlighter":
            c = QColor(self.stroke); c.setAlpha(90); pen.setColor(c); pen.setWidthF(max(8, self.width * 4))
        painter.setPen(pen)
        if self.kind == "stroke" or self.kind == "highlighter":
            if len(self.points) == 1:
                painter.drawPoint(self.points[0])
            elif len(self.points) > 1:
                path = QPainterPath(self.points[0])
                for p in self.points[1:]: path.lineTo(p)
                painter.drawPath(path)
        elif self.kind == "line":
            painter.drawLine(QPointF(0, 0), QPointF(self.w, self.h))
        elif self.kind == "arrow":
            painter.drawLine(QPointF(0, 0), QPointF(self.w, self.h))
            angle = __import__("math").atan2(self.h, self.w)
            length = 15
            p1 = QPointF(self.w - length * __import__("math").cos(angle - .45),
                         self.h - length * __import__("math").sin(angle - .45))
            p2 = QPointF(self.w - length * __import__("math").cos(angle + .45),
                         self.h - length * __import__("math").sin(angle + .45))
            painter.drawLine(QPointF(self.w, self.h), p1); painter.drawLine(QPointF(self.w, self.h), p2)
        elif self.kind in ("rect", "roundrect", "ellipse"):
            painter.setBrush(QBrush(self.fill))
            rect = QRectF(0, 0, self.w, self.h)
            if self.kind == "rect": painter.drawRect(rect)
            elif self.kind == "roundrect": painter.drawRoundedRect(rect, 15, 15)
            else: painter.drawEllipse(rect)
        elif self.kind == "image" and not self.pixmap.isNull():
            painter.setPen(QPen(QColor(BORDER), 1))
            painter.drawRoundedRect(QRectF(0, 0, self.w, self.h), 8, 8)
            painter.drawPixmap(QRectF(0, 0, self.w, self.h), self.pixmap, QRectF(self.pixmap.rect()))
        elif self.kind in ("file", "image", "audio", "video", "pdf", "link"):
            painter.setBrush(QBrush(QColor("#121e30")))
            painter.setPen(QPen(QColor(BORDER), 1))
            painter.drawRoundedRect(QRectF(0, 0, self.w, self.h), 12, 12)
            icon = {"file": "▤", "image": "▧", "audio": "♫", "video": "▶", "pdf": "PDF", "link": "↗"}.get(self.kind, "▤")
            painter.setPen(QColor(CYAN)); painter.setFont(QFont("Noto Sans", 20, QFont.Weight.Bold))
            painter.drawText(QRectF(14, 10, 44, 38), Qt.AlignmentFlag.AlignCenter, icon)
            painter.setPen(QColor(TEXT)); painter.setFont(QFont("Noto Sans", 10, QFont.Weight.DemiBold))
            name = self.data.get("name", self.data.get("url", "Attachment"))
            painter.drawText(QRectF(15, 52, self.w - 30, 30), Qt.AlignmentFlag.AlignLeft, name[:70])
            painter.setPen(QColor(MUTED)); painter.setFont(QFont("Noto Sans", 9))
            painter.drawText(QRectF(15, 83, self.w - 30, 25),
                             Qt.AlignmentFlag.AlignLeft, self.data.get("details", self.data.get("mime", "Local attachment")))
        if self.isSelected():
            painter.setPen(QPen(QColor(CYAN), 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.boundingRect().adjusted(2, 2, -2, -2), 8, 8)
            if self.kind == "image":
                # Visible bottom-right resize grip.
                painter.setPen(QPen(QColor("#07111d"), 1))
                painter.setBrush(QBrush(QColor(CYAN)))
                painter.drawRoundedRect(QRectF(self.w - 7, self.h - 7, 14, 14), 3, 3)


class NoteTextItem(QGraphicsTextItem):
    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.data = data
        self.setPlainText(data.get("text", ""))
        font = QFont(data.get("font", "Noto Sans"), int(data.get("size", 18)))
        font.setBold(bool(data.get("bold", False)))
        font.setItalic(bool(data.get("italic", False)))
        font.setUnderline(bool(data.get("underline", False)))
        font.setStrikeOut(bool(data.get("strike", False)))
        self.setFont(font)
        self.setDefaultTextColor(QColor(data.get("color", TEXT)))
        self.setTextWidth(float(data.get("w", 320)))
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setPos(float(data.get("x", 0)), float(data.get("y", 0)))
        self.setZValue(float(data.get("z", 1)))
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.document().setDocumentMargin(8)

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        if self.isSelected():
            painter.save()
            painter.setPen(QPen(QColor(CYAN), 1))
            painter.setBrush(QBrush(QColor(CYAN)))
            rect = self.boundingRect()
            painter.drawRoundedRect(QRectF(rect.right() - 7, rect.bottom() - 7, 14, 14), 3, 3)
            painter.restore()

    def to_data(self):
        d = dict(self.data)
        d.update({"type": "text", "text": self.toPlainText(), "x": self.pos().x(), "y": self.pos().y(),
                  "w": self.textWidth(), "z": self.zValue()})
        return d


class CanvasView(QGraphicsView):
    status = Signal(str)
    itemDropped = Signal(list, QPointF)
    toolChanged = Signal(str)
    itemResized = Signal(object)
    attachmentActivated = Signal(str)
    attachmentContextMenu = Signal(str, object)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.tool = "select"
        self.stroke_color = QColor(CYAN)
        self.fill_color = QColor("#17243a")
        self.stroke_width = 3
        self._panning = False
        self._drawing = False
        self._start = QPointF()
        self._last = QPointF()
        self._preview = None
        self._pan_start = None
        self._space_down = False
        self._resizing_item = None
        self._resize_origin = QPointF()
        self._resize_start_size = (0.0, 0.0)
        self._resize_aspect = 1.0
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.grabGesture(Qt.GestureType.PinchGesture)
        self.viewport().grabGesture(Qt.GestureType.PinchGesture)
        self.setAcceptDrops(True)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setBackgroundBrush(QBrush(QColor(BG)))
        self.setStyleSheet(f"QGraphicsView{{border:0;background:{BG};}}")
        # Start at the top-left instead of centering the workspace around the origin.
        self.setSceneRect(0, 0, 1000000, 1000000)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_tool(self, tool):
        self.tool = tool
        self.toolChanged.emit(tool)
        self.setCursor(Qt.CursorShape.CrossCursor if tool not in ("select", "text") else Qt.CursorShape.ArrowCursor)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag if tool == "select" else QGraphicsView.DragMode.NoDrag)

    def wheelEvent(self, event):
        # Ctrl + wheel and touchpad pinch/zoom wheel events zoom around the pointer.
        pixel = event.pixelDelta().y()
        angle = event.angleDelta().y()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = pixel if pixel else angle / 4.0
            factor = 1.0015 ** delta if delta else (1.15 if angle > 0 else 1 / 1.15)
            self._apply_zoom(factor, event.position().toPoint())
            event.accept()
            return
        # Some Linux/Windows touchpads report pinch as pixel deltas with Ctrl.
        super().wheelEvent(event)

    def _apply_zoom(self, factor, anchor=None):
        current = self.transform().m11()
        target = max(0.12, min(5.0, current * factor))
        factor = target / current if current else 1.0
        if abs(factor - 1.0) < 0.0001:
            return
        if anchor is not None:
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
            # Keep zoom anchored to the touchpad/mouse position.
            self.scale(factor, factor)
        else:
            self.scale(factor, factor)
        self.status.emit(f"Zoom {self.transform().m11()*100:.0f}%")

    def _handle_pinch_gesture(self, event):
        gesture = event.gesture(Qt.GestureType.PinchGesture)
        if gesture is None:
            return False
        current_scale = gesture.scaleFactor()
        previous_scale = gesture.lastScaleFactor()
        change = current_scale / previous_scale if previous_scale > 0 else current_scale
        if change and change > 0:
            self._apply_zoom(change, self.viewport().rect().center())
        event.accept()
        return True

    def _handle_native_zoom(self, event):
        # Many Linux touchpads expose a two-finger pinch as a native zoom gesture
        # rather than a Qt PinchGesture or Ctrl+wheel event.
        if event.type() != QEvent.Type.NativeGesture:
            return False
        if event.gestureType() != Qt.NativeGestureType.ZoomNativeGesture:
            return False
        value = float(event.value())
        factor = 1.0 + value
        if factor > 0:
            self._apply_zoom(factor, self.viewport().rect().center())
        event.accept()
        return True

    def event(self, event):
        if event.type() == QEvent.Type.Gesture and self._handle_pinch_gesture(event):
            return True
        if self._handle_native_zoom(event):
            return True
        return super().event(event)

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.Gesture and self._handle_pinch_gesture(event):
            return True
        if self._handle_native_zoom(event):
            return True
        return super().viewportEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._space_down = True
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._space_down = False
            if not self._panning:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def mousePressEvent(self, event):
        # Drag the bottom-right grip of a selected image or text box to resize it.
        if event.button() == Qt.MouseButton.LeftButton and self.tool == "select":
            view_pos = event.position().toPoint()
            scene_pos = self.mapToScene(view_pos)
            for candidate in reversed(self.scene().selectedItems()):
                if isinstance(candidate, CanvasItem) and candidate.kind == "image":
                    grip = candidate.mapToScene(QPointF(candidate.w, candidate.h))
                    start_size = (candidate.w, candidate.h)
                elif isinstance(candidate, NoteTextItem):
                    rect = candidate.boundingRect()
                    grip = candidate.mapToScene(QPointF(rect.right(), rect.bottom()))
                    start_size = (candidate.textWidth(), rect.height())
                else:
                    continue
                grip_view = self.mapFromScene(grip)
                if (grip_view - view_pos).manhattanLength() <= 16:
                    self._resizing_item = candidate
                    self._resize_origin = scene_pos
                    self._resize_start_size = start_size
                    candidate._previous_size = start_size
                    self._resize_aspect = start_size[0] / start_size[1] if start_size[1] else 1.0
                    candidate.setSelected(True)
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                    event.accept()
                    return
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and self._space_down):
            self._panning = True; self._pan_start = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor); event.accept(); return
        pos = self.mapToScene(event.position().toPoint())
        self._start = pos; self._last = pos
        if event.button() == Qt.MouseButton.LeftButton and self.tool in ("pencil", "highlighter", "eraser"):
            self._drawing = True
            kind = "highlighter" if self.tool == "highlighter" else "stroke"
            color = QColor("#080b13") if self.tool == "eraser" else self.stroke_color
            item = CanvasItem(kind, {"x": pos.x(), "y": pos.y(), "points": [[0, 0]],
                                     "stroke": color.name(), "width": self.stroke_width * (3 if self.tool == "eraser" else 1)})
            item.setPos(pos); self.scene().addItem(item); self._preview = item
            event.accept(); return
        if event.button() == Qt.MouseButton.LeftButton and self.tool in ("line", "arrow", "rect", "roundrect", "ellipse"):
            self._drawing = True
            self._preview = CanvasItem(self.tool, {"x": pos.x(), "y": pos.y(), "w": 1, "h": 1,
                                                   "stroke": self.stroke_color.name(), "fill": self.fill_color.name(),
                                                   "width": self.stroke_width})
            self.scene().addItem(self._preview); event.accept(); return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = self.mapToScene(event.position().toPoint())
        self.status.emit(f"X {pos.x():.0f}  Y {pos.y():.0f}")
        if self._resizing_item is not None:
            item = self._resizing_item
            delta = pos - self._resize_origin
            new_w = max(40.0, self._resize_start_size[0] + delta.x())
            if isinstance(item, NoteTextItem):
                # Text items resize horizontally; their height follows wrapped content.
                item.setTextWidth(new_w)
                item.data["w"] = new_w
                item.update()
            else:
                new_h = max(30.0, self._resize_start_size[1] + delta.y())
                # Keep image proportions when Shift is held; otherwise free resize.
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    if abs(delta.x()) >= abs(delta.y()):
                        new_h = max(30.0, new_w / max(self._resize_aspect, 0.01))
                    else:
                        new_w = max(40.0, new_h * self._resize_aspect)
                item.prepareGeometryChange()
                item.w, item.h = new_w, new_h
                item.data["w"], item.data["h"] = new_w, new_h
                item.update()
            event.accept()
            return
        if self._panning and self._pan_start is not None:
            delta = event.position().toPoint() - self._pan_start
            self._pan_start = event.position().toPoint()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept(); return
        if self._drawing and self._preview is not None:
            if self.tool in ("pencil", "highlighter", "eraser"):
                p = pos - self._preview.pos()
                self._preview.prepareGeometryChange()
                self._preview.points.append(p); self._preview.update()
            else:
                self._preview.prepareGeometryChange()
                d = pos - self._start
                self._preview.w = d.x(); self._preview.h = d.y()
                self._preview.update()
            self._last = pos; event.accept(); return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing_item is not None:
            resized_item = self._resizing_item
            if isinstance(resized_item, NoteTextItem):
                resized_item.data["w"] = resized_item.textWidth()
                self.status.emit("Text box resized")
            else:
                resized_item.data["w"] = resized_item.w
                resized_item.data["h"] = resized_item.h
                self.status.emit("Image preview resized")
            resized_item.update()
            self._resizing_item = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.itemResized.emit(resized_item)
            event.accept()
            return
        if self._panning:
            self._panning = False; self.setCursor(Qt.CursorShape.ArrowCursor); event.accept(); return
        if self._drawing and self._preview is not None:
            if self.tool in ("line", "arrow", "rect", "roundrect", "ellipse"):
                d = self._last - self._start
                item = self._preview
                if d.x() < 0 or d.y() < 0:
                    # Normalize rectangle geometry while retaining line direction by using points for lines.
                    if item.kind in ("line", "arrow"):
                        item.setPos(self._start); item.w = d.x(); item.h = d.y()
                    else:
                        x, y = min(self._start.x(), self._last.x()), min(self._start.y(), self._last.y())
                        item.setPos(x, y); item.w = abs(d.x()); item.h = abs(d.y())
                if abs(item.w) < 3: item.w = 3
                if abs(item.h) < 3: item.h = 3
                item.update()
            self._preview = None; self._drawing = False
            self.set_tool("select"); event.accept(); return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        while item and not isinstance(item, (NoteTextItem, CanvasItem)):
            item = item.parentItem()
        if isinstance(item, CanvasItem) and item.data.get("path"):
            self.attachmentContextMenu.emit(str(item.data.get("path")), event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        while item and not isinstance(item, (NoteTextItem, CanvasItem)):
            item = item.parentItem()
        if isinstance(item, NoteTextItem):
            d = TextDialog(self, item.to_data())
            if d.exec():
                item.data.update(d.result_data())
                item.setPlainText(item.data["text"])
                f = QFont(item.data["font"], item.data["size"])
                f.setBold(item.data["bold"]); f.setItalic(item.data["italic"])
                f.setUnderline(item.data["underline"]); f.setStrikeOut(item.data["strike"])
                item.setFont(f); item.setDefaultTextColor(QColor(item.data["color"]))
                item.update()
            event.accept(); return
        if isinstance(item, CanvasItem) and item.kind in ("file", "audio", "video", "pdf", "image"):
            path = item.data.get("path")
            if path and Path(path).is_file():
                self.attachmentActivated.emit(str(path))
            event.accept(); return
        super().mouseDoubleClickEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: event.ignore()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.itemDropped.emit(paths, self.mapToScene(event.position().toPoint()))
            event.acceptProposedAction()
        else:
            event.ignore()


class TextAttachmentViewer(QDialog):
    """Read-only, non-executing text preview with a conservative size limit."""
    PREVIEW_LIMIT = 2 * 1024 * 1024

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.setWindowTitle(f"Dasweic Notes · {self.path.name}")
        self.resize(900, 680)
        layout = QVBoxLayout(self)
        heading = QLabel(self.path.name)
        heading.setStyleSheet(f"font-size:17px;font-weight:700;color:{TEXT};")
        layout.addWidget(heading)
        self.editor = QPlainTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setStyleSheet(f"background:#090e19;color:{TEXT};border:1px solid {BORDER};border-radius:10px;padding:10px;font-family:monospace;")
        layout.addWidget(self.editor, 1)
        try:
            size = self.path.stat().st_size
            with self.path.open("rb") as f:
                raw = f.read(self.PREVIEW_LIMIT + 1)
            truncated = len(raw) > self.PREVIEW_LIMIT
            raw = raw[:self.PREVIEW_LIMIT]
            try:
                content = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                content = raw.decode("utf-8", errors="replace")
            # Avoid treating likely binary data as readable text.
            if "\x00" in content[:8192]:
                raise ValueError("This file appears to contain binary data, not plain text.")
            self.editor.setPlainText(content)
            if truncated:
                self.editor.appendPlainText("\n\n[Preview truncated for safety. Export the file to inspect the complete contents.]")
            self.status = QLabel(f"{size:,} bytes · read-only preview")
        except (OSError, ValueError) as exc:
            self.editor.setPlainText(f"Unable to preview this text file.\n\n{exc}")
            self.status = QLabel("Preview unavailable")
        layout.addWidget(self.status)
        close = styled_button("Close", True)
        close.clicked.connect(self.accept)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        self.setStyleSheet(DIALOG_STYLE)


class CaptureDialog(QDialog):
    """Qt Multimedia recorder for audio, webcam+mic, or screen+optional mic.

    Real capture availability depends on the Qt build, OS permissions, devices, and codecs.
    A completed recording is only reported after QMediaRecorder signals StoppedState.
    """
    completed = Signal(str)

    def __init__(self, mode: str, output_path: Path, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.output_path = output_path
        self.session = None
        self.recorder = None
        self.audio_input = None
        self.camera = None
        self.screen_capture = None
        self.video_widget = None
        self.elapsed_ms = 0
        self.started_at = None
        self._paused_at = None
        self._cancelled = False
        self._reported = False
        self.setWindowTitle({"audio":"Audio recording", "camera":"Camera + microphone recording", "screen":"Screen recording"}.get(mode, "Recording"))
        self.resize(760, 560)
        root = QVBoxLayout(self)
        self.title_label = QLabel(self.windowTitle())
        self.title_label.setStyleSheet(f"font-size:18px;font-weight:700;color:{TEXT}")
        root.addWidget(self.title_label)
        self.status_label = QLabel("Preparing capture devices…")
        self.status_label.setStyleSheet(f"color:{CYAN};font-weight:600")
        root.addWidget(self.status_label)
        self.preview_label = QLabel("Audio capture" if mode == "audio" else "Camera preview will appear here" if mode == "camera" else "Screen capture selected")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(250)
        self.preview_label.setStyleSheet(f"background:#050912;border:1px solid {BORDER};border-radius:12px;color:{MUTED};padding:10px")
        root.addWidget(self.preview_label, 1)
        device_row = QHBoxLayout()
        device_row.addWidget(QLabel("Microphone"))
        self.mic_combo = QComboBox()
        self.mic_combo.addItem("System default microphone", None)
        if CAPTURE_AVAILABLE:
            try:
                for device in QMediaDevices.audioInputs():
                    self.mic_combo.addItem(device.description(), device)
            except Exception:
                pass
        device_row.addWidget(self.mic_combo, 2)
        if mode == "camera":
            device_row.addWidget(QLabel("Camera"))
            self.camera_combo = QComboBox()
            if CAPTURE_AVAILABLE:
                try:
                    for device in QMediaDevices.videoInputs():
                        self.camera_combo.addItem(device.description(), device)
                except Exception:
                    pass
            device_row.addWidget(self.camera_combo, 2)
        elif mode == "screen":
            device_row.addWidget(QLabel("Monitor"))
            self.screen_combo = QComboBox()
            for screen in QGuiApplication.screens():
                self.screen_combo.addItem(screen.name() or "Monitor", screen)
            device_row.addWidget(self.screen_combo, 2)
        root.addLayout(device_row)
        self.duration_label = QLabel("00:00")
        self.duration_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.duration_label.setStyleSheet(f"font-size:24px;font-weight:700;color:{CYAN};padding:6px")
        root.addWidget(self.duration_label)
        buttons = QHBoxLayout()
        self.start_button = styled_button("●  Start recording", True)
        self.pause_button = styled_button("Ⅱ  Pause")
        self.resume_button = styled_button("▶  Resume")
        self.stop_button = styled_button("■  Stop")
        self.cancel_button = styled_button("Cancel")
        for b in (self.start_button, self.pause_button, self.resume_button, self.stop_button, self.cancel_button): buttons.addWidget(b)
        root.addLayout(buttons)
        self.pause_button.setEnabled(False); self.resume_button.setEnabled(False); self.stop_button.setEnabled(False)
        self.start_button.clicked.connect(self.start_recording)
        self.pause_button.clicked.connect(self.pause_recording)
        self.resume_button.clicked.connect(self.resume_recording)
        self.stop_button.clicked.connect(self.stop_recording)
        self.cancel_button.clicked.connect(self.cancel_recording)
        self.clock = QTimer(self); self.clock.setInterval(200); self.clock.timeout.connect(self.update_duration)
        self.setStyleSheet(DIALOG_STYLE)
        if not CAPTURE_AVAILABLE:
            self.status_label.setText("Recording support is unavailable in this PySide6 installation.")
            self.start_button.setEnabled(False)
        elif mode == "camera" and self.camera_combo.count() == 0:
            self.status_label.setText("No camera devices were detected.")
            self.start_button.setEnabled(False)
        elif mode == "screen" and QScreenCapture is None:
            self.status_label.setText("This Qt build does not include screen capture support.")
            self.start_button.setEnabled(False)
        elif mode == "camera":
            # Open the camera before recording so the user can verify framing.
            try:
                self._prepare()
                self.status_label.setText("Camera preview ready · press Start when ready")
            except Exception as exc:
                self.status_label.setText("Camera preview unavailable")
                self.start_button.setEnabled(False)
                QMessageBox.warning(self, APP_NAME, f"Could not initialize camera preview. Check camera/microphone permissions and device availability.\n\n{exc}")

    def _prepare(self):
        self.session = QMediaCaptureSession(self)
        self.recorder = QMediaRecorder(self)
        self.session.setRecorder(self.recorder)
        mic = self.mic_combo.currentData()
        if mic is None:
            inputs = QMediaDevices.audioInputs()
            mic = inputs[0] if inputs else None
        if self.mode in ("audio", "camera") and mic is None:
            raise RuntimeError("No microphone was detected. Connect one and check operating-system microphone permissions.")
        if mic is not None:
            self.audio_input = QAudioInput(mic, self)
            self.session.setAudioInput(self.audio_input)
        if self.mode == "camera":
            device = self.camera_combo.currentData()
            if device is None:
                raise RuntimeError("No camera is selected.")
            self.camera = QCamera(device, self)
            self.session.setCamera(self.camera)
            from PySide6.QtMultimediaWidgets import QVideoWidget
            self.video_widget = QVideoWidget(self)
            self.video_widget.setMinimumHeight(250)
            self.session.setVideoOutput(self.video_widget)
            self.preview_label.hide()
            self.layout().insertWidget(2, self.video_widget, 1)
            self.camera.start()
        elif self.mode == "screen":
            self.screen_capture = QScreenCapture(self)
            screen = self.screen_combo.currentData()
            if screen is None:
                raise RuntimeError("No monitor is selected.")
            self.screen_capture.setScreen(screen)
            self.session.setScreenCapture(self.screen_capture)
            self.screen_capture.setActive(True)
        self.recorder.errorOccurred.connect(self._record_error)
        self.recorder.recorderStateChanged.connect(self._state_changed)
        # Prefer broadly supported formats; leave Qt's default if format selection is rejected.
        try:
            fmt = QMediaFormat()
            fmt.setFileFormat(QMediaFormat.FileFormat.MPEG4 if self.mode != "audio" else QMediaFormat.FileFormat.Mpeg4Audio)
            self.recorder.setMediaFormat(fmt)
        except Exception:
            pass
        self.recorder.setOutputLocation(QUrl.fromLocalFile(str(self.output_path.resolve())))

    def start_recording(self):
        try:
            if self.recorder is None:
                self._prepare()
            if self.mode in ("audio", "camera") and not QMediaDevices.audioInputs():
                raise RuntimeError("No microphone was detected. Connect a microphone and check OS permissions.")
            self.recorder.record()
            self.started_at = time.monotonic()
            self.clock.start()
            self.start_button.setEnabled(False); self.pause_button.setEnabled(True); self.stop_button.setEnabled(True)
            self.status_label.setText("● RECORDING")
        except Exception as exc:
            self._release()
            QMessageBox.warning(self, APP_NAME, f"Could not start recording. Check device permissions and Qt Multimedia codec support.\n\n{exc}")

    def pause_recording(self):
        if self.recorder:
            try:
                self.recorder.pause(); self._paused_at = time.monotonic()
                self.pause_button.setEnabled(False); self.resume_button.setEnabled(True)
                self.status_label.setText("PAUSED")
            except Exception as exc: QMessageBox.warning(self, APP_NAME, f"Pause is not supported by this backend.\n{exc}")

    def resume_recording(self):
        if self.recorder:
            try:
                self.recorder.record(); self._paused_at = None
                self.pause_button.setEnabled(True); self.resume_button.setEnabled(False)
                self.status_label.setText("● RECORDING")
            except Exception as exc: QMessageBox.warning(self, APP_NAME, f"Could not resume recording.\n{exc}")

    def update_duration(self):
        if self.recorder:
            duration = max(0, int(self.recorder.duration()))
            self.duration_label.setText(AttachmentViewer._fmt(duration))

    def _state_changed(self, state):
        if not CAPTURE_AVAILABLE: return
        if state == QMediaRecorder.RecorderState.StoppedState and not self._cancelled and self.started_at is not None:
            # Only report a completed recording after the backend has stopped/finalized the file.
            QTimer.singleShot(250, self._finalize_completed)

    def _finalize_completed(self):
        if self._reported or self._cancelled: return
        self._reported = True
        self.clock.stop(); self._release(keep_file=True)
        if self.output_path.is_file() and self.output_path.stat().st_size > 0:
            self.completed.emit(str(self.output_path))
            self.status_label.setText("Recording finalized")
            self.accept()
        else:
            QMessageBox.warning(self, APP_NAME, "The recorder stopped but did not produce a valid file.")

    def _record_error(self, error, error_string):
        self.status_label.setText("RECORDING ERROR")
        QMessageBox.warning(self, APP_NAME, f"Recording failed. Check device permissions and supported codecs.\n\n{error_string or error}")

    def stop_recording(self):
        if self.recorder:
            try:
                self.recorder.stop()
                self.status_label.setText("Finalizing recording…")
                self.start_button.setEnabled(False); self.pause_button.setEnabled(False); self.resume_button.setEnabled(False); self.stop_button.setEnabled(False)
                QTimer.singleShot(2500, self._finalize_completed)
            except Exception as exc:
                QMessageBox.warning(self, APP_NAME, f"Could not stop recording cleanly.\n{exc}")

    def cancel_recording(self):
        self._cancelled = True
        self.clock.stop()
        self._release()
        try: self.output_path.unlink(missing_ok=True)
        except OSError: pass
        self.reject()

    def _release(self, keep_file=False):
        try:
            if self.recorder is not None: self.recorder.stop()
        except Exception: pass
        try:
            if self.camera is not None: self.camera.stop()
        except Exception: pass
        try:
            if self.screen_capture is not None: self.screen_capture.setActive(False)
        except Exception: pass
        self.recorder = self.session = self.audio_input = self.camera = self.screen_capture = None

    def closeEvent(self, event):
        if self.started_at is not None and not self._reported and not self._cancelled:
            answer = QMessageBox.question(self, APP_NAME, "A recording may still be active. Cancel and discard it?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore(); return
            self.cancel_recording()
        else:
            self._release()
        event.accept()


class MainWindow(QMainWindow):
    def __init__(self, auth_data: dict):
        super().__init__()
        self.auth_data = auth_data
        self.project_path: Path | None = None
        self.dirty = False
        self.project_password: str | None = None
        self.objects: dict[str, QGraphicsItem] = {}
        self.undo_stack = []
        self.redo_stack = []
        self.temp_root = Path(tempfile.mkdtemp(prefix="dasweic-notes-"))
        self.autosave_enabled = bool(auth_data.get("autosave", False))
        self.setWindowTitle(APP_NAME)
        self.resize(1440, 900)
        self.setMinimumSize(900, 600)
        self.scene = QGraphicsScene(self)
        self.view = CanvasView(self.scene)
        self.view.status.connect(self.show_coordinates)
        self.view.itemDropped.connect(self.import_files)
        self.view.toolChanged.connect(self.update_tool_status)
        self.view.itemResized.connect(self.on_item_resized)
        self.view.attachmentActivated.connect(self.open_attachment)
        self.view.attachmentContextMenu.connect(self.attachment_context_menu)
        self.setCentralWidget(self.build_layout())
        self.build_actions()
        self.apply_style()
        self.statusBar().showMessage("Ready · Offline workspace")
        if self.autosave_enabled:
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.autosave)
            self.timer.start(60_000)
        self.set_tool("select")

    def build_layout(self):
        root = QWidget()
        layout = QVBoxLayout(root); layout.setContentsMargins(12, 10, 12, 8); layout.setSpacing(8)
        header = QHBoxLayout()
        logo = QLabel("✦")
        logo.setStyleSheet(f"color:{CYAN};font-size:27px;font-weight:800;padding:0 7px;")
        title_box = QVBoxLayout()
        title = QLabel("DASWEIC NOTES"); title.setStyleSheet("font-size:16px;font-weight:800;letter-spacing:2px;color:#eaf7ff")
        subtitle = QLabel("PRIVATE COSMIC WORKSPACE  ·  OFFLINE"); subtitle.setStyleSheet(f"font-size:9px;letter-spacing:1.3px;color:{MUTED}")
        title_box.addWidget(title); title_box.addWidget(subtitle)
        header.addWidget(logo); header.addLayout(title_box); header.addStretch()
        self.project_label = QLabel("Untitled canvas")
        self.project_label.setStyleSheet(f"color:{MUTED};padding:8px 12px;border:1px solid {BORDER};border-radius:10px;")
        header.addWidget(self.project_label)
        header.addWidget(styled_button("New", False))
        header.itemAt(header.count()-1).widget().clicked.connect(self.new_project)
        save_btn = styled_button("Save", True); save_btn.clicked.connect(self.save_project); header.addWidget(save_btn)
        layout.addLayout(header)
        toolbar = QHBoxLayout(); toolbar.setSpacing(6)
        for label, tool in [("Select","select"),("Text","text"),("Pencil","pencil"),("Highlight","highlighter"),
                            ("Eraser","eraser"),("Line","line"),("Arrow","arrow"),("Rectangle","rect"),
                            ("Rounded","roundrect"),("Ellipse","ellipse")]:
            b = styled_button(label)
            b.clicked.connect(lambda checked=False, t=tool: self.toolbar_action(t))
            toolbar.addWidget(b)
        toolbar.addStretch()
        zoomout = styled_button("−"); zoomout.clicked.connect(lambda: self.zoom(1/1.15)); toolbar.addWidget(zoomout)
        zoomin = styled_button("+"); zoomin.clicked.connect(lambda: self.zoom(1.15)); toolbar.addWidget(zoomin)
        reset = styled_button("100%"); reset.clicked.connect(self.reset_zoom); toolbar.addWidget(reset)
        layout.addLayout(toolbar)
        body = QHBoxLayout(); body.setSpacing(10)
        sidebar = QFrame(); sidebar.setObjectName("sidebar"); sidebar.setFixedWidth(205)
        side = QVBoxLayout(sidebar); side.setContentsMargins(12, 14, 12, 14); side.setSpacing(8)
        side.addWidget(self.section_label("CREATE"))
        for label, fn in [("＋  Add text", self.add_text), ("▧  Insert files", self.choose_files),
                          ("⇩  Export files", self.export_files),
                          ("↗  Add offline link", self.add_link), ("▱  Rectangle", lambda: self.set_tool("rect")),
                          ("✎  Freehand pencil", lambda: self.set_tool("pencil"))]:
            b = styled_button(label); b.clicked.connect(fn); side.addWidget(b)
        side.addWidget(self.section_label("CAPTURE"))
        for label, mode in [("●  Record audio", "audio"), ("▣  Camera + mic", "camera"), ("▤  Record screen", "screen")]:
            b = styled_button(label); b.clicked.connect(lambda checked=False, m=mode: self.start_capture(m)); side.addWidget(b)
        side.addWidget(self.section_label("STYLE"))
        color_btn = styled_button("Stroke color"); color_btn.clicked.connect(self.choose_stroke); side.addWidget(color_btn)
        fill_btn = styled_button("Shape fill"); fill_btn.clicked.connect(self.choose_fill); side.addWidget(fill_btn)
        side.addWidget(QLabel("Stroke width"))
        self.width_slider = QSlider(Qt.Orientation.Horizontal); self.width_slider.setRange(1, 18); self.width_slider.setValue(3)
        self.width_slider.valueChanged.connect(lambda v: setattr(self.view, "stroke_width", v)); side.addWidget(self.width_slider)
        side.addWidget(self.section_label("WORKSPACE"))
        for label, fn in [("Duplicate  Ctrl+D", self.duplicate_selected), ("Delete selection", self.delete_selected),
                          ("Bring to front", lambda: self.order_selected(True)), ("Send to back", lambda: self.order_selected(False)),
                          ("Undo  Ctrl+Z", self.undo), ("Redo  Ctrl+Y", self.redo)]:
            b = styled_button(label); b.clicked.connect(fn); side.addWidget(b)
        side.addStretch()
        self.autosave_check = QCheckBox("Enable local autosave")
        self.autosave_check.setChecked(self.autosave_enabled)
        self.autosave_check.toggled.connect(self.toggle_autosave); side.addWidget(self.autosave_check)
        change = styled_button("Change startup password"); change.clicked.connect(self.change_password); side.addWidget(change)
        body.addWidget(sidebar)
        self.view.setMinimumSize(500, 400)
        body.addWidget(self.view, 1)
        layout.addLayout(body, 1)
        return root

    def section_label(self, text):
        label = QLabel(text)
        label.setStyleSheet(f"font-size:10px;font-weight:800;letter-spacing:1.5px;color:{CYAN};padding:9px 2px 2px")
        return label

    def build_actions(self):
        shortcuts = [
            ("Ctrl+N", self.new_project), ("Ctrl+O", self.open_project), ("Ctrl+S", self.save_project),
            ("Ctrl+Shift+S", self.save_as), ("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo),
            ("Ctrl+A", self.select_all), ("Ctrl+C", self.copy_selected), ("Ctrl+X", self.cut_selected),
            ("Ctrl+V", self.paste_items), ("Ctrl+D", self.duplicate_selected),
            ("Delete", self.delete_selected), ("Backspace", self.delete_selected),
            ("Ctrl+Plus", lambda: self.zoom(1.15)), ("Ctrl+Equal", lambda: self.zoom(1.15)),
            ("Ctrl+Shift+Equal", lambda: self.zoom(1.15)),
            ("Ctrl+Minus", lambda: self.zoom(1/1.15)), ("Ctrl+0", self.reset_zoom),
            ("Escape", lambda: self.set_tool("select")), ("Ctrl+T", self.add_text),
        ]
        for seq, fn in shortcuts:
            a = QAction(self); a.setShortcut(QKeySequence(seq)); a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            a.triggered.connect(fn); self.addAction(a)
        file_menu = self.menuBar().addMenu("File")
        for label, fn in [("New canvas", self.new_project), ("Open project…", self.open_project),
                          ("Save", self.save_project), ("Save As…", self.save_as),
                          ("Export Files…", self.export_files), ("Exit", self.close)]:
            a = file_menu.addAction(label); a.triggered.connect(fn)
        capture_menu = self.menuBar().addMenu("Capture")
        for label, mode in [("Record audio…", "audio"), ("Record camera + microphone…", "camera"), ("Record screen…", "screen")]:
            a = capture_menu.addAction(label); a.triggered.connect(lambda checked=False, m=mode: self.start_capture(m))
        edit_menu = self.menuBar().addMenu("Edit")
        for label, fn in [("Undo", self.undo), ("Redo", self.redo), ("Select all", self.select_all),
                          ("Duplicate", self.duplicate_selected), ("Delete", self.delete_selected)]:
            a = edit_menu.addAction(label); a.triggered.connect(fn)
        view_menu = self.menuBar().addMenu("View")
        for label, fn in [("Zoom in", lambda: self.zoom(1.15)), ("Zoom out", lambda: self.zoom(1/1.15)),
                          ("Reset zoom", self.reset_zoom)]:
            a = view_menu.addAction(label); a.triggered.connect(fn)

    def apply_style(self):
        self.setStyleSheet(f"""
        QMainWindow,QWidget {{background:{BG};color:{TEXT};font-family:'Noto Sans','Segoe UI',sans-serif;font-size:12px;}}
        QFrame#sidebar {{background:{PANEL};border:1px solid {BORDER};border-radius:16px;}}
        QMenuBar {{background:{BG};color:{TEXT};padding:4px;}}
        QMenuBar::item:selected,QMenu::item:selected {{background:#203347;border-radius:5px;}}
        QMenu {{background:{PANEL};color:{TEXT};border:1px solid {BORDER};}}
        QStatusBar {{background:{PANEL};color:{MUTED};border:1px solid {BORDER};border-radius:8px;}}
        QCheckBox {{color:{MUTED};spacing:7px;}}
        QSlider::groove:horizontal {{height:5px;background:#273349;border-radius:2px;}}
        QSlider::handle:horizontal {{background:{CYAN};width:14px;margin:-5px 0;border-radius:7px;}}
        """)

    def toolbar_action(self, tool):
        if tool == "text": self.add_text()
        else: self.set_tool(tool)

    def set_tool(self, tool):
        self.view.set_tool(tool)
        self.statusBar().showMessage(f"Tool: {tool}")

    def update_tool_status(self, tool):
        self.statusBar().showMessage(f"Tool: {tool}")

    def show_coordinates(self, text):
        self.statusBar().showMessage(f"{text}    ·    {self.view.transform().m11()*100:.0f}% zoom")

    def on_item_resized(self, item):
        if isinstance(item, CanvasItem):
            item.data["w"] = item.w
            item.data["h"] = item.h
            self.record({"kind": "resize", "item": item,
                         "before": getattr(item, "_previous_size", (item.w, item.h)),
                         "after": (item.w, item.h)})

    def mark_dirty(self):
        self.dirty = True
        name = self.project_path.name if self.project_path else "Untitled canvas"
        self.project_label.setText("● " + name)

    def record(self, action):
        self.undo_stack.append(action)
        if len(self.undo_stack) > 200: self.undo_stack.pop(0)
        self.redo_stack.clear()
        self.mark_dirty()

    def add_item(self, item, action=True):
        self.scene.addItem(item)
        self.objects[str(uuid.uuid4())] = item
        if action: self.record({"kind": "add", "item": item})
        return item

    def add_text(self):
        d = TextDialog(self)
        if not d.exec(): return
        data = d.result_data()
        pos = self.view.mapToScene(self.view.viewport().rect().topLeft() + __import__("PySide6.QtCore", fromlist=["QPoint"]).QPoint(40, 40))
        data.update({"x": pos.x(), "y": pos.y(), "w": 320, "z": self.scene.items().__len__()+1})
        item = NoteTextItem(data)
        self.add_item(item)
        self.set_tool("select")

    def open_attachment(self, path):
        file_path = Path(path)
        if not file_path.is_file():
            QMessageBox.warning(self, APP_NAME, "This attachment could not be found at its saved location.")
            return
        suffix = file_path.suffix.lower()
        if suffix in {".txt", ".log", ".md", ".csv", ".json", ".yaml", ".yml", ".ini", ".py", ".html", ".css", ".js"}:
            viewer = TextAttachmentViewer(str(file_path), self)
            viewer.exec()
            return
        supported = AttachmentViewer.VIDEO_EXTS | AttachmentViewer.AUDIO_EXTS | {".pdf"}
        if suffix not in supported:
            QMessageBox.information(self, APP_NAME, "This file type does not have an in-app viewer yet.")
            return
        viewer = AttachmentViewer(str(file_path), self)
        viewer.exec()

    def start_capture(self, mode):
        if not CAPTURE_AVAILABLE:
            QMessageBox.warning(self, APP_NAME, "Recording needs a PySide6 build with Qt Multimedia capture APIs. Install/upgrade with: python -m pip install --upgrade PySide6 PySide6-Addons")
            return
        folder = self.temp_root / "recordings"
        folder.mkdir(parents=True, exist_ok=True)
        extension = ".m4a" if mode == "audio" else ".mp4"
        default_name = {"audio":"Audio recording", "camera":"Camera recording", "screen":"Screen recording"}.get(mode, "Recording")
        path, _ = QFileDialog.getSaveFileName(self, "Choose recording filename", str(folder / (default_name + extension)), "Audio/Video files (*%s)" % extension)
        if not path: return
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(extension)
        if target.exists():
            answer = QMessageBox.question(self, APP_NAME, f"Replace {target.name}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes: return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            dialog = CaptureDialog(mode, target, self)
            dialog.completed.connect(self._recording_completed)
            dialog.exec()
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"Could not initialize the recorder.\n\n{exc}")

    def _recording_completed(self, path):
        try:
            file_path = Path(path)
            if not file_path.is_file() or file_path.stat().st_size <= 0:
                raise OSError("The recording file is empty or missing.")
            self.import_files([str(file_path)], self.view.mapToScene(self.view.viewport().rect().center()))
            self.mark_dirty()
            self.statusBar().showMessage(f"Recording attached: {file_path.name}", 6000)
            QMessageBox.information(self, APP_NAME, f"Recording finalized and attached to the canvas:\n{file_path.name}")
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"The recording finished but could not be attached.\n\n{exc}")

    def attachment_context_menu(self, path, global_pos):
        file_path = Path(path)
        menu = QMenu(self)
        if file_path.is_file():
            menu.addAction("Open / Preview", lambda p=str(file_path): self.open_attachment(p))
            menu.addAction("Export / Save As…", lambda p=str(file_path): self.export_attachment(p))
            menu.addAction("Copy file path", lambda p=str(file_path): QApplication.clipboard().setText(p))
            menu.addAction("File information", lambda p=str(file_path): self.attachment_info(p))
        menu.addSeparator()
        menu.addAction("Remove attachment from canvas", lambda p=str(file_path): self.remove_attachment_by_path(p))
        menu.exec(global_pos)

    def export_attachment(self, path):
        source = Path(path)
        if not source.is_file():
            QMessageBox.warning(self, APP_NAME, "The attachment file is missing.")
            return
        target, _ = QFileDialog.getSaveFileName(self, "Export attachment", str(Path.home() / source.name), "All files (*)")
        if not target: return
        destination = Path(target)
        try:
            if source.resolve() == destination.resolve():
                QMessageBox.information(self, APP_NAME, "The selected destination is the original file.")
                return
        except OSError: pass
        if destination.exists():
            answer = QMessageBox.question(self, APP_NAME, f"Replace {destination.name}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes: return
        staged = destination.with_name(destination.name + ".exporting-" + secrets.token_hex(4))
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as fin, staged.open("wb") as fout:
                shutil.copyfileobj(fin, fout, CHUNK)
                fout.flush(); os.fsync(fout.fileno())
            if staged.stat().st_size != source.stat().st_size:
                raise OSError("The exported file size did not match the source.")
            os.replace(staged, destination)
            QMessageBox.information(self, APP_NAME, f"Attachment exported successfully:\n{destination}")
        except OSError as exc:
            try: staged.unlink(missing_ok=True)
            except OSError: pass
            QMessageBox.critical(self, APP_NAME, f"Export failed. The original project attachment was not removed.\n\n{exc}")

    def attachment_info(self, path):
        p = Path(path)
        try:
            st = p.stat()
            QMessageBox.information(self, APP_NAME, f"Name: {p.name}\nType: {p.suffix.lower() or 'unknown'}\nSize: {st.st_size:,} bytes\nModified: {time.ctime(st.st_mtime)}\nPath: {p}")
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not read file information.\n{exc}")

    def remove_attachment_by_path(self, path):
        matches = [item for item in self.scene.items() if isinstance(item, CanvasItem) and item.data.get("path") == path]
        if not matches: return
        answer = QMessageBox.question(self, APP_NAME, "Remove this attachment from the canvas? The source file will not be deleted.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes: return
        for item in matches:
            self.record({"kind":"delete", "item":item, "pos":item.pos()})
            self.scene.removeItem(item)
            for key, value in list(self.objects.items()):
                if value is item: self.objects.pop(key, None)
        self.mark_dirty()

    def choose_stroke(self):
        c = QColorDialog.getColor(self.view.stroke_color, self, "Stroke color")
        if c.isValid(): self.view.stroke_color = c

    def choose_fill(self):
        c = QColorDialog.getColor(self.view.fill_color, self, "Shape fill")
        if c.isValid(): self.view.fill_color = c

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Insert files", str(Path.home()), "All files (*)")
        if paths: self.import_files(paths, self.view.mapToScene(self.view.viewport().rect().topLeft() + __import__("PySide6.QtCore", fromlist=["QPoint"]).QPoint(40, 40)))

    def import_files(self, paths, position):
        x, y = position.x(), position.y()
        for i, raw in enumerate(paths):
            src = Path(raw)
            try:
                if not src.is_file(): continue
                suffix = src.suffix.lower()
                kind = "image" if suffix in (".png",".jpg",".jpeg",".gif",".bmp",".webp",".tif",".tiff") else (
                    "audio" if suffix in (".mp3",".wav",".flac",".ogg",".m4a",".aac") else (
                    "video" if suffix in (".mp4",".webm",".avi",".mkv",".mov",".m4v") else (
                    "pdf" if suffix == ".pdf" else "file")))
                size = src.stat().st_size
                details = f"{size:,} bytes · {suffix[1:].upper() if suffix else 'FILE'}"
                item_data = {"x": x+i*28, "y": y+i*28,
                             "path": str(src.resolve()), "name": src.name, "details": details,
                             "mime": suffix[1:].upper() if suffix else "File", "stroke": CYAN}
                if kind == "image":
                    reader = QImageReader(str(src))
                    reader.setAutoTransform(True)
                    image_size = reader.size()
                    if image_size.isValid() and image_size.width() > 0 and image_size.height() > 0:
                        scale = min(420.0 / image_size.width(), 300.0 / image_size.height(), 1.0)
                        item_data["w"] = image_size.width() * scale
                        item_data["h"] = image_size.height() * scale
                    else:
                        item_data["w"], item_data["h"] = 320, 220
                else:
                    item_data["w"], item_data["h"] = 260, 140
                item = CanvasItem(kind, item_data)
                self.add_item(item)
            except OSError as exc:
                QMessageBox.warning(self, APP_NAME, f"Could not insert {src.name}:\n{exc}")
        self.set_tool("select")

    def add_link(self):
        url, ok = QInputDialog.getText(self, "Add offline link", "Store a URL as plain text (it will not be opened or contacted):")
        if not ok or not url.strip(): return
        pos = self.view.mapToScene(self.view.viewport().rect().topLeft() + __import__("PySide6.QtCore", fromlist=["QPoint"]).QPoint(40, 40))
        item = CanvasItem("link", {"x": pos.x(), "y": pos.y(), "w": 260, "h": 112,
                                   "url": url.strip(), "name": url.strip(), "details": "Offline link · not opened",
                                   "stroke": CYAN})
        self.add_item(item)

    def selected(self):
        return self.scene.selectedItems()

    def delete_selected(self):
        items = self.selected()
        if not items: return
        for item in items:
            self.record({"kind": "delete", "item": item, "pos": item.pos()})
            self.scene.removeItem(item)
            for k, v in list(self.objects.items()):
                if v is item: self.objects.pop(k, None)

    def duplicate_selected(self):
        items = self.selected()
        for item in items:
            d = self.item_to_data(item)
            d["x"] = float(item.pos().x()) + 24; d["y"] = float(item.pos().y()) + 24
            new = self.data_to_item(d)
            self.add_item(new)
        self.mark_dirty()

    def select_all(self):
        for item in self.scene.items():
            if item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable:
                item.setSelected(True)

    def order_selected(self, front):
        for item in self.selected():
            item.setZValue(max([i.zValue() for i in self.scene.items()] + [0]) + 1 if front else
                           min([i.zValue() for i in self.scene.items()] + [0]) - 1)
        self.mark_dirty()

    def undo(self):
        if not self.undo_stack: return
        a = self.undo_stack.pop()
        if a["kind"] == "add":
            self.scene.removeItem(a["item"])
        elif a["kind"] == "delete":
            self.scene.addItem(a["item"]); a["item"].setPos(a["pos"])
        elif a["kind"] == "move":
            a["item"].setPos(a["before"])
        elif a["kind"] == "resize":
            a["item"].prepareGeometryChange()
            a["item"].w, a["item"].h = a["before"]
            a["item"].data["w"], a["item"].data["h"] = a["before"]
            a["item"].update()
        self.redo_stack.append(a); self.mark_dirty()

    def redo(self):
        if not self.redo_stack: return
        a = self.redo_stack.pop()
        if a["kind"] == "add": self.scene.addItem(a["item"])
        elif a["kind"] == "delete": self.scene.removeItem(a["item"])
        elif a["kind"] == "move": a["item"].setPos(a["after"])
        elif a["kind"] == "resize":
            a["item"].prepareGeometryChange()
            a["item"].w, a["item"].h = a["after"]
            a["item"].data["w"], a["item"].data["h"] = a["after"]
            a["item"].update()
        self.undo_stack.append(a); self.mark_dirty()

    def item_to_data(self, item):
        if isinstance(item, NoteTextItem):
            return item.to_data()
        if isinstance(item, CanvasItem):
            d = dict(item.data)
            d.update({"type": item.kind, "x": item.pos().x(), "y": item.pos().y(), "w": item.w, "h": item.h,
                      "stroke": item.stroke.name(), "fill": item.fill.name(), "width": item.width,
                      "points": [[p.x(), p.y()] for p in item.points], "z": item.zValue()})
            return d
        return {}

    def data_to_item(self, data):
        typ = data.get("type", "file")
        if typ == "text": return NoteTextItem(data)
        if typ in ("stroke", "highlighter", "line", "arrow", "rect", "roundrect", "ellipse",
                   "image", "file", "audio", "video", "pdf", "link"):
            return CanvasItem(typ, data)
        return CanvasItem("file", data)

    def copy_selected(self):
        data = [self.item_to_data(i) for i in self.selected()]
        QApplication.clipboard().setText(json.dumps(data, ensure_ascii=False))

    def cut_selected(self):
        self.copy_selected(); self.delete_selected()

    def paste_items(self):
        try:
            data = json.loads(QApplication.clipboard().text())
            if not isinstance(data, list): return
            for d in data:
                d["x"] = float(d.get("x", 0)) + 20; d["y"] = float(d.get("y", 0)) + 20
                if d.get("path") and not Path(d["path"]).exists():
                    d["path"] = None
                self.add_item(self.data_to_item(d))
        except (ValueError, TypeError, KeyError):
            # Non-app clipboard text is intentionally not auto-inserted as an object.
            pass

    def zoom(self, factor):
        self.view._apply_zoom(factor)
        self.show_coordinates("Canvas")

    def reset_zoom(self):
        self.view.resetTransform()
        self.show_coordinates("Canvas")

    def toggle_autosave(self, enabled):
        self.autosave_enabled = enabled
        self.auth_data["autosave"] = enabled
        save_auth(self.auth_data)
        if enabled:
            if not hasattr(self, "timer"):
                self.timer = QTimer(self); self.timer.timeout.connect(self.autosave)
            self.timer.start(60_000)
        elif hasattr(self, "timer"):
            self.timer.stop()

    def autosave(self):
        if not self.dirty: return
        # Recovery data is encrypted with the current project password when available.
        # If no project password is established, do not write plaintext recovery data.
        if not self.project_password:
            return
        recovery = CONFIG_DIR / "recovery.dasweic"
        try:
            self.write_project(recovery, self.project_password)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            self.statusBar().showMessage(f"Autosave failed: {exc}", 8000)

    def project_data(self):
        items = []
        for item in self.scene.items():
            if isinstance(item, (NoteTextItem, CanvasItem)):
                d = self.item_to_data(item)
                if d: items.append(d)
        return {"format": "dasweic-notes", "version": APP_VERSION, "created_by": APP_NAME,
                "saved_at": int(time.time()), "objects": items,
                "settings": {"autosave": self.autosave_enabled}}

    def write_project(self, destination: Path, password: str, progress_callback=None):
        """Package attachments, encrypt the archive, and report real save progress."""
        def report(value, message):
            if progress_callback:
                progress_callback(max(0, min(100, int(value))), message)

        destination.parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="dasweic-save-", dir=str(destination.parent)))
        archive = work / "payload.zip"
        encrypted = work / "encrypted.tmp"
        staged = destination.with_name(destination.name + ".tmp-" + secrets.token_hex(4))
        try:
            data = self.project_data()
            attachments = []
            total_bytes = 0
            for idx, obj in enumerate(data["objects"]):
                path = obj.get("path")
                if path and Path(path).is_file():
                    pth = Path(path)
                    arcname = f"attachments/{idx:08d}_{pth.name}"
                    attachments.append((obj, pth, arcname))
                    total_bytes += pth.stat().st_size
            processed = 0
            report(0, "Preparing your Dasweic project…")
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=3, allowZip64=True) as zf:
                # Keep the same manifest format used by the existing project loader.
                zf.writestr("manifest.json", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
                for obj, pth, arcname in attachments:
                    obj["attachment"] = arcname
                    obj.pop("path", None)
                    with pth.open("rb") as src, zf.open(arcname, "w") as dest:
                        while True:
                            block = src.read(CHUNK)
                            if not block:
                                break
                            dest.write(block)
                            processed += len(block)
                            if total_bytes:
                                report(int(processed * 45 / total_bytes), f"Adding attachments… {processed // (1024 * 1024)} MB")
                # Final manifest is authoritative; preserve the older manifest for compatibility.
                zf.writestr("manifest.final.json", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
            report(45, "Encrypting and securing project…")
            stream_encrypt(archive, encrypted, password, progress_callback=report)
            report(96, "Finishing save…")
            with encrypted.open("rb") as src, staged.open("wb") as out:
                shutil.copyfileobj(src, out, CHUNK)
            os.replace(staged, destination)
            report(100, "Save complete!")
        finally:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                pass
            shutil.rmtree(work, ignore_errors=True)

    def save_project(self):
        if not self.project_path:
            return self.save_as()
        password = self.project_password
        if not password:
            d = PasswordDialog("Encrypt project", "Choose a password for this .dasweic file.", self, confirm=True)
            if not d.exec(): return
            password = d.value()

        progress = QProgressDialog("Preparing your Dasweic project…", "", 0, 100, self)
        progress.setWindowTitle("Saving Dasweic Notes")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setCancelButton(None)
        progress.setMinimumWidth(430)
        progress.setStyleSheet(f"QProgressDialog{{background:{PANEL};color:{TEXT};border:1px solid {BORDER};border-radius:14px;padding:16px}} QLabel{{color:{TEXT};font-size:13px;padding:8px}} QProgressBar{{background:#080d18;border:1px solid {BORDER};border-radius:8px;height:16px;text-align:center;color:{TEXT}}} QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {CYAN},stop:1 {VIOLET});border-radius:7px}}")
        progress.show()
        QApplication.processEvents()
        def update_progress(value, message):
            progress.setLabelText(message)
            progress.setValue(value)
            QApplication.processEvents()
        try:
            self.write_project(self.project_path, password, progress_callback=update_progress)
            self.project_password = password
            self.dirty = False
            self.project_label.setText(self.project_path.name)
            progress.setLabelText("✓ Your project is safely saved and encrypted.")
            progress.setValue(100)
            QApplication.processEvents()
            QTimer.singleShot(900, progress.close)
            self.statusBar().showMessage("Project saved and encrypted", 5000)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            progress.close()
            QMessageBox.critical(self, APP_NAME, f"Save failed. The previous valid project was not intentionally replaced.\n\n{exc}")

    def save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Dasweic project", str(Path.home() / ("Untitled" + EXTENSION)),
                                              "Dasweic Notes project (*.dasweic)")
        if not path: return
        if not path.lower().endswith(EXTENSION): path += EXTENSION
        target = Path(path)
        if target.exists():
            answer = QMessageBox.question(self, APP_NAME, f"Replace {target.name}?",
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes: return
        d = PasswordDialog("Encrypt project", "Choose a password for this project. Keep it safe; it cannot be recovered.", self, confirm=True)
        if not d.exec(): return
        old_path, old_password = self.project_path, self.project_password
        self.project_path, self.project_password = target, d.value()
        self.save_project()
        if self.dirty:
            self.project_path, self.project_password = old_path, old_password

    def export_files(self):
        """Export all file attachments currently on the canvas after password confirmation."""
        if not self.project_path or not self.project_password:
            QMessageBox.information(
                self, APP_NAME,
                "Save this project as a password-protected .dasweic file first.\n\n"
                "Then use Export Files to enter the project password and export its attachments."
            )
            return

        password_dialog = PasswordDialog(
            "Export Files",
            "Enter this project's password to export all attached files.",
            self,
        )
        if not password_dialog.exec():
            return
        if not hmac.compare_digest(password_dialog.value(), self.project_password):
            QMessageBox.warning(self, APP_NAME, "Incorrect project password. No files were exported.")
            return

        folder = QFileDialog.getExistingDirectory(
            self, "Choose folder for exported files", str(Path.home())
        )
        if not folder:
            return

        destination = Path(folder)
        files = []
        seen_sources = set()
        for obj in self.project_data().get("objects", []):
            raw_path = obj.get("path")
            if not raw_path:
                continue
            source = Path(raw_path)
            try:
                if source.is_file():
                    resolved = str(source.resolve())
                    if resolved not in seen_sources:
                        seen_sources.add(resolved)
                        files.append(source)
            except OSError:
                continue

        if not files:
            QMessageBox.information(self, APP_NAME, "There are no attached files to export.")
            return

        progress = QProgressDialog("Preparing files for export…", "", 0, len(files), self)
        progress.setWindowTitle("Export Files · Dasweic Notes")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setCancelButton(None)
        progress.setMinimumWidth(430)
        progress.setStyleSheet(
            f"QProgressDialog{{background:{PANEL};color:{TEXT};border:1px solid {BORDER};"
            f"border-radius:14px;padding:16px}} QLabel{{color:{TEXT};font-size:13px;padding:8px}} "
            f"QProgressBar{{background:#080d18;border:1px solid {BORDER};border-radius:8px;"
            f"height:16px;text-align:center;color:{TEXT}}} QProgressBar::chunk{{background:"
            f"qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {CYAN},stop:1 {VIOLET});border-radius:7px}}"
        )
        progress.show()
        QApplication.processEvents()
        exported = 0
        errors = []
        used_names = set()
        try:
            for index, source in enumerate(files, start=1):
                progress.setLabelText(f"Exporting {source.name}… ({index}/{len(files)})")
                QApplication.processEvents()
                try:
                    candidate = source.name
                    stem, suffix = source.stem, source.suffix
                    serial = 2
                    while candidate.casefold() in used_names or (destination / candidate).exists():
                        candidate = f"{stem} ({serial}){suffix}"
                        serial += 1
                    used_names.add(candidate.casefold())
                    shutil.copy2(source, destination / candidate)
                    exported += 1
                except OSError as exc:
                    errors.append(f"{source.name}: {exc}")
                progress.setValue(index)
                QApplication.processEvents()
            progress.setLabelText(f"✓ Export complete · {exported} of {len(files)} file(s) exported.")
            progress.setValue(len(files))
            QApplication.processEvents()
            QTimer.singleShot(1000, progress.close)
        except Exception:
            progress.close()
            raise

        if errors:
            QMessageBox.warning(
                self, APP_NAME,
                f"Exported {exported} of {len(files)} file(s) to:\n{destination}\n\n"
                "Some files could not be copied:\n" + "\n".join(errors[:8])
            )
        else:
            QMessageBox.information(
                self, APP_NAME,
                f"Successfully exported {exported} file(s) to:\n{destination}"
            )
        self.statusBar().showMessage(f"Exported {exported} file(s)", 5000)

    def open_project(self):
        if not self.confirm_discard(): return
        path, _ = QFileDialog.getOpenFileName(self, "Open Dasweic project", str(Path.home()), "Dasweic Notes project (*.dasweic)")
        if not path: return
        d = PasswordDialog("Unlock project", "Enter the password used to encrypt this project.", self)
        if not d.exec(): return
        work = Path(tempfile.mkdtemp(prefix="dasweic-open-"))
        archive = work / "payload.zip"
        progress = QProgressDialog("Preparing to open project…", "", 0, 100, self)
        progress.setWindowTitle("Opening Dasweic Notes")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0); progress.setAutoClose(False); progress.setAutoReset(False)
        progress.setCancelButton(None); progress.setMinimumWidth(430)
        progress.setStyleSheet(f"QProgressDialog{{background:{PANEL};color:{TEXT};border:1px solid {BORDER};border-radius:14px;padding:16px}} QLabel{{color:{TEXT};font-size:13px;padding:8px}} QProgressBar{{background:#080d18;border:1px solid {BORDER};border-radius:8px;height:16px;text-align:center;color:{TEXT}}} QProgressBar::chunk{{background:{CYAN};border-radius:7px}}")
        progress.show(); QApplication.processEvents()
        def report(value, message):
            progress.setValue(max(0, min(100, int(value))))
            progress.setLabelText(message)
            QApplication.processEvents()
        try:
            report(0, "Reading and verifying encrypted project…")
            stream_decrypt(Path(path), archive, d.value(), progress_callback=report)
            report(82, "Reading project manifest…")
            with zipfile.ZipFile(archive, "r") as zf:
                names = zf.namelist()
                manifest_name = "manifest.final.json" if "manifest.final.json" in names else "manifest.json"
                if manifest_name not in names: raise ValueError("Project manifest is missing.")
                for name in names:
                    member = Path(name)
                    if member.is_absolute() or ".." in member.parts:
                        raise ValueError("Unsafe path found in project archive.")
                data = json.loads(zf.read(manifest_name).decode("utf-8"))
                if data.get("format") != "dasweic-notes" or data.get("version") != APP_VERSION:
                    raise ValueError("Unsupported project format or version.")
                if not isinstance(data.get("objects"), list): raise ValueError("Invalid project object list.")
                extraction = self.temp_root / uuid.uuid4().hex
                extraction.mkdir(parents=True, exist_ok=True)
                attachments = [(obj, obj.get("attachment")) for obj in data["objects"] if obj.get("attachment")]
                total = max(1, len(attachments)); copied = 0
                total_attachment_bytes = max(1, sum(zf.getinfo(name).file_size for _, name in attachments if name in names))
                restored_bytes = 0
                for obj, attachment in attachments:
                    if attachment not in names or not attachment.startswith("attachments/"):
                        raise ValueError("An attachment reference is invalid.")
                    out = extraction / Path(attachment).name
                    report(82 + int(restored_bytes * 12 / total_attachment_bytes), f"Restoring attachment {copied + 1} of {total}…")
                    with zf.open(attachment) as src, out.open("wb") as dst:
                        while True:
                            block = src.read(CHUNK)
                            if not block:
                                break
                            dst.write(block)
                            restored_bytes += len(block)
                            if restored_bytes % (8 * CHUNK) < CHUNK or restored_bytes >= total_attachment_bytes:
                                report(82 + int(restored_bytes * 12 / total_attachment_bytes), f"Restoring attachments… {restored_bytes // (1024 * 1024)} MB")
                    obj.pop("attachment", None)
                    obj["path"] = str(out)
                    copied += 1
                report(95, "Restoring canvas objects…")
                # Only mutate the visible workspace after all archive data has been validated.
                self.scene.clear(); self.objects.clear()
                for index, obj in enumerate(data["objects"]):
                    item = self.data_to_item(obj)
                    self.add_item(item, action=False)
                    if index % 100 == 0:
                        report(95 + int(4 * (index + 1) / max(1, len(data["objects"]))), "Restoring canvas objects…")
                self.undo_stack.clear(); self.redo_stack.clear()
            self.project_path = Path(path); self.project_password = d.value(); self.dirty = False
            self.project_label.setText(Path(path).name)
            report(100, "Project opened and authenticated.")
            self.statusBar().showMessage("Project opened and authenticated", 5000)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            QMessageBox.critical(self, APP_NAME, f"Could not open project.\n\n{exc}")
        finally:
            progress.close()
            shutil.rmtree(work, ignore_errors=True)

    def confirm_discard(self):
        if not self.dirty: return True
        answer = QMessageBox.question(self, APP_NAME, "This canvas has unsaved changes. Save before continuing?",
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                      QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Cancel: return False
        if answer == QMessageBox.StandardButton.Save:
            self.save_project()
            return not self.dirty
        return True

    def new_project(self):
        if not self.confirm_discard(): return
        self.scene.clear(); self.objects.clear(); self.undo_stack.clear(); self.redo_stack.clear()
        self.project_path = None; self.project_password = None; self.dirty = False
        self.project_label.setText("Untitled canvas"); self.reset_zoom()
        self.statusBar().showMessage("New canvas")

    def change_password(self):
        d = PasswordDialog("Change startup password", "Enter your current startup password.", self)
        if not d.exec(): return
        if not verify_password(d.value(), self.auth_data.get("auth", {})):
            QMessageBox.warning(self, APP_NAME, "Current password is incorrect."); return
        new = PasswordDialog("Set new password", "Choose a new startup password.", self, confirm=True)
        if not new.exec(): return
        if len(new.value()) < 8:
            QMessageBox.warning(self, APP_NAME, "Use at least 8 characters for a stronger password."); return
        self.auth_data["auth"] = password_verifier(new.value())
        save_auth(self.auth_data)
        QMessageBox.information(self, APP_NAME, "Startup password changed. This does not change passwords on existing project files.")

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("Add text", self.add_text)
        menu.addAction("Insert files", self.choose_files)
        menu.addSeparator()
        menu.addAction("Copy", self.copy_selected)
        menu.addAction("Cut", self.cut_selected)
        menu.addAction("Paste", self.paste_items)
        menu.addAction("Duplicate", self.duplicate_selected)
        menu.addAction("Delete", self.delete_selected)
        menu.exec(event.globalPos())

    def closeEvent(self, event):
        if self.confirm_discard():
            try: shutil.rmtree(self.temp_root, ignore_errors=True)
            except OSError: pass
            event.accept()
        else:
            event.ignore()


def authenticate() -> dict | None:
    data = load_auth()
    # The initial password is set only on first run. Config stores a salted verifier, never plaintext.
    while True:
        dialog = PasswordDialog("Welcome to Dasweic Notes", "Unlock your private offline workspace.")
        if not dialog.exec():
            return None
        if verify_password(dialog.value(), data["auth"]):
            return data
        QMessageBox.warning(None, APP_NAME, "Incorrect password. The workspace remains locked.")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Dasweic")
    app.setStyle("Fusion")
    # Compact native splash; no external assets or network resources are required.
    splash_pix = QPixmap(560, 220)
    splash_pix.fill(QColor(BG))
    painter = QPainter(splash_pix)
    painter.setPen(QColor(CYAN)); painter.setFont(QFont("Noto Sans", 22, QFont.Weight.Bold))
    painter.drawText(QRectF(24, 34, 512, 58), Qt.AlignmentFlag.AlignCenter, "✦  DASWEIC NOTES")
    painter.setPen(QColor(TEXT)); painter.setFont(QFont("Noto Sans", 10))
    painter.drawText(QRectF(24, 94, 512, 30), Qt.AlignmentFlag.AlignCenter, "Preparing your private offline workspace…")
    painter.setPen(QPen(QColor(BORDER), 1)); painter.drawRoundedRect(QRectF(70, 154, 420, 5), 2, 2)
    painter.setPen(QPen(QColor(CYAN), 3)); painter.drawLine(72, 156, 220, 156)
    painter.end()
    splash = QSplashScreen(splash_pix, Qt.WindowType.WindowStaysOnTopHint)
    splash.show(); app.processEvents()
    auth = authenticate()
    if auth is None:
        splash.close()
        return 0
    splash.showMessage("Loading canvas tools and local settings…", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, QColor(TEXT))
    app.processEvents()
    window = MainWindow(auth)
    window.show()
    splash.finish(window)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
