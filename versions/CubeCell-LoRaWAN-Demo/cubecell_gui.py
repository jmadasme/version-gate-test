#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CubeCell LoRaWAN — Panel de Control (Escritorio)
================================================
GUI de escritorio estilo RAF para operar el nodo **Heltec CubeCell HTCC-AB01**
(LoRaWAN · OTAA Clase A · AU915 sub-banda 2) conectado por USB (CP2102, 9600 8N1).

Recibe y envía datos hacia/desde el gateway LoRaWAN (p. ej. Milesight UG56):

  - **Terminal en vivo**: log coloreado del monitor serial (banner, join,
    heartbeat cada 30 s, downlinks, respuestas de uplink).
  - **Uplink manual**: escribe HEX (+ Enter) o activa modo ASCII; se envía por
    LoRaWAN puerto 1.
  - **Downlinks**: cada `[DOWNLINK] XX XX -> "texto"` se lista en su tarjeta.
  - **Indicadores**: sesión (JOINED/RESTAURADA), radio, heartbeats, uplinks,
    downlinks, bytes RX/TX.
  - **Comando ERASE**: borra la sesión persistida en flash y reinicia el nodo.

Requisitos:
    pip install PyQt6 pyserial

Uso:
    python3 cubecell_gui.py
"""

import sys
import time
import re
import threading

import serial
import serial.tools.list_ports

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QFrame, QSizePolicy, QMessageBox,
    QLineEdit, QPlainTextEdit, QCheckBox, QListWidget, QListWidgetItem,
    QScrollArea,
)

BAUD = 9600
MAX_PAYLOAD = 51  # bytes, igual al firmware

# Marca de la demo (sin referencia técnica a LoRaWAN en el título)
APP_ACRONYM = "RAF"
APP_FULL = "Red Autogestionada Fractal"

# ----------------------------------------------------------------------
# Colores del tema (oscuro premium, consistente con espnow_gui/valvulas_gui)
# ----------------------------------------------------------------------
BG        = "#0d1117"
BG_HEADER = "#161b22"
CARD      = "#1c2128"
CARD_HI   = "#232a33"
BORDER    = "#30363d"
ACCENT    = "#2dd4bf"
ACCENT_DK = "#14b8a6"
TEXT      = "#e6edf3"
MUTED     = "#8b949e"
GREEN     = "#3fb950"
RED       = "#f85149"
YELLOW    = "#d29922"
BLUE      = "#58a6ff"
PURPLE    = "#bc8cff"

# ----------------------------------------------------------------------
# Expresiones del protocolo serial del firmware
# ----------------------------------------------------------------------
RE_DOWNLINK  = re.compile(r"\[DOWNLINK\]\s+((?:[0-9A-F]{2}\s+)+)->\s*\"([^\"]*)\"")
RE_SENDING   = re.compile(r">>\s*Enviando:\s+((?:[0-9A-F]{2}\s+)+)")
RE_OK_DL     = re.compile(r"-> OK \+ downlink \((\d+) bytes\)")
RE_ERROR     = re.compile(r"-> ERROR (-?\d+) \(([^)]+)\)")


def apply_style(app: QApplication):
    app.setStyleSheet(f"""
        QMainWindow, QWidget {{ background-color: {BG}; color: {TEXT};
                                font-family: 'Segoe UI', 'Ubuntu', 'DejaVu Sans', 'Noto Color Emoji'; }}
        QLabel {{ background: transparent; }}
        #header {{ background-color: {BG_HEADER}; border-bottom: 1px solid {BORDER}; }}
        #appTitle {{ font-size: 20px; font-weight: 700; color: {TEXT}; }}
        #appSub {{ font-size: 11px; color: {MUTED}; }}
        QComboBox, QLineEdit {{
            background-color: {CARD}; color: {TEXT}; border: 1px solid {BORDER};
            border-radius: 6px; padding: 6px 10px; min-height: 18px;
        }}
        QComboBox::drop-down {{ border: none; width: 20px; }}
        QComboBox QAbstractItemView {{
            background-color: {CARD}; color: {TEXT};
            border: 1px solid {BORDER}; selection-background-color: {ACCENT_DK};
        }}
        QPushButton {{
            background-color: {CARD}; color: {TEXT}; border: 1px solid {BORDER};
            border-radius: 6px; padding: 7px 14px; font-weight: 600;
        }}
        QPushButton:hover {{ background-color: {CARD_HI}; border-color: {ACCENT_DK}; }}
        QPushButton:pressed {{ background-color: {ACCENT_DK}; }}
        QPushButton#primary {{
            background-color: {ACCENT}; color: #06251f; border: none; font-weight: 700;
        }}
        QPushButton#primary:hover {{ background-color: {ACCENT_DK}; }}
        QPushButton#danger {{ color: {RED}; }}
        QPushButton#chip {{
            background-color: #161b22; color: {MUTED}; border: 1px solid {BORDER};
            border-radius: 12px; padding: 3px 10px; font-size: 11px; font-weight: 600;
        }}
        QPushButton#chip:hover {{ color: {ACCENT}; border-color: {ACCENT_DK}; }}
        QFrame#card {{
            background-color: {CARD}; border: 1px solid {BORDER}; border-radius: 10px;
        }}
        QPlainTextEdit, QListWidget {{
            background-color: #0a0e13; color: {TEXT};
            border: 1px solid {BORDER}; border-radius: 8px;
            font-family: 'DejaVu Sans Mono', 'Consolas', monospace; font-size: 12px;
            padding: 8px;
        }}
        QCheckBox {{ color: {MUTED}; }}
        QCheckBox::indicator {{ width: 16px; height: 16px; }}
    """)


# ----------------------------------------------------------------------
# Hilo lector del puerto serie (no bloquea la UI)
# ----------------------------------------------------------------------
class SerialReader(QThread):
    line_received = pyqtSignal(str)

    def __init__(self, ser, parent=None):
        super().__init__(parent)
        self.ser = ser
        self._running = True

    def run(self):
        buf = bytearray()
        while self._running:
            try:
                ch = self.ser.read(1)      # timeout de 0.2 s en el puerto
            except Exception:
                break
            if not ch:
                continue
            buf += ch
            if ch in (b"\n", b"\r"):
                if len(buf) > 1 or buf not in (b"\n", b"\r"):
                    self.line_received.emit(
                        bytes(buf).decode("utf-8", errors="replace")
                        .rstrip("\r\n"))
                buf.clear()
            elif buf == b"> ":                 # prompt "> " sin newline (solo si es exacto)
                self.line_received.emit("> ")
                buf.clear()

    def stop(self):
        self._running = False
        self.wait(2000)


def detect_ports():
    """Devuelve [(device, description)] de puertos serie USB visibles."""
    out = []
    try:
        for p in serial.tools.list_ports.comports():
            dev = p.device or ""
            if "ttyUSB" in dev or "ttyACM" in dev or "usb" in dev.lower():
                desc = p.description or dev
                out.append((dev, desc))
    except Exception:
        pass
    # Orden estable: ttyUSBx primero, luego ttyACMx
    return sorted(out, key=lambda x: (x[0][:7] != "/dev/tty", x[0]))


def probe_cubecell(device, timeout=1.2):
    """Detecta si `device` es el CubeCell (firmware LoRaWAN demo).

    Envía una línea no-HEX ('x\\n'): el firmware responde
    "?? Error: escribe hex valido" + prompt. Es inofensivo (no genera
    uplink LoRaWAN ni borra nada). Devuelve True/False.
    """
    try:
        s = serial.Serial(device, BAUD, timeout=timeout)
    except Exception:
        return False
    try:
        time.sleep(0.15)
        s.reset_input_buffer()
        s.write(b"x\n")
        s.flush()
        end = time.time() + timeout
        out = b""
        while time.time() < end:
            d = s.read(256)
            if d:
                out += d
    except Exception:
        s.close()
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass
    return b"Error: escribe hex valido" in out


# ----------------------------------------------------------------------
# Tarjeta pequeña con título (helper)
# ----------------------------------------------------------------------
def card(title, emoji=""):
    frame = QFrame()
    frame.setObjectName("card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(14, 10, 14, 12)
    lay.setSpacing(8)
    head = QLabel(f"{emoji} {title}" if emoji else title)
    head.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {ACCENT};")
    lay.addWidget(head)
    return frame, lay


# ----------------------------------------------------------------------
# Ventana principal
# ----------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_ACRONYM} · Panel de Control")
        self.resize(1060, 680)

        self.ser = None
        self.reader = None
        self._write_lock = threading.Lock()
        self._rx_bytes = 0
        self._tx_bytes = 0
        self._hb_count = 0
        self._ul_count = 0
        self._dl_count = 0
        self._connect_time = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Header ----
        header = QFrame()
        header.setObjectName("header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 14, 20, 14)
        tb = QVBoxLayout()
        tb.setSpacing(2)
        t = QLabel(f"{APP_ACRONYM} — Panel de Control")
        t.setObjectName("appTitle")
        s = QLabel(f"{APP_FULL} · Nodo de radio · 9600 8N1")
        s.setObjectName("appSub")
        tb.addWidget(t)
        tb.addWidget(s)
        hl.addLayout(tb)
        hl.addStretch()
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(f"color: {RED}; font-size: 14px;")
        self.status_text = QLabel("Desconectado")
        self.status_text.setStyleSheet(f"font-weight: 600; color: {MUTED};")
        hl.addWidget(self.status_dot)
        hl.addWidget(self.status_text)
        root.addWidget(header)

        # ---- Cuerpo ----
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(12)
        root.addWidget(body)

        # Fila de conexión
        conn = QHBoxLayout()
        conn.setSpacing(8)
        conn.addWidget(QLabel("Puerto:"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(220)
        self.refresh_ports()
        conn.addWidget(self.port_combo)
        self.btn_scan = QPushButton("⟳")
        self.btn_scan.setToolTip("Re-escanear puertos")
        self.btn_scan.clicked.connect(self.refresh_ports)
        conn.addWidget(self.btn_scan)
        baud_lbl = QLabel("9600 8N1")
        baud_lbl.setStyleSheet(f"font-weight: 700; color: {MUTED};")
        conn.addWidget(baud_lbl)
        conn.addStretch()
        self.btn_erase = QPushButton("🧨 ERASE")
        self.btn_erase.setObjectName("danger")
        self.btn_erase.setToolTip("Borrar sesión persistida y reiniciar el nodo")
        self.btn_erase.clicked.connect(self.do_erase)
        conn.addWidget(self.btn_erase)
        self.btn_connect = QPushButton("Conectar")
        self.btn_connect.setObjectName("primary")
        self.btn_connect.clicked.connect(self.toggle_connection)
        conn.addWidget(self.btn_connect)
        bl.addLayout(conn)

        # Zona principal: terminal (izq) + panel lateral (der)
        main = QHBoxLayout()
        main.setSpacing(12)
        bl.addLayout(main, stretch=1)

        # --- Terminal ---
        term_frame, term_lay = card("Terminal serial")
        self.terminal = QPlainTextEdit()
        self.terminal.setReadOnly(True)
        self.terminal.setMaximumBlockCount(3000)
        self.terminal.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("DejaVu Sans Mono", 11)
        self.terminal.setFont(font)
        term_lay.addWidget(self.terminal)
        term_btns = QHBoxLayout()
        self.lbl_term_status = QLabel("esperando conexión…")
        self.lbl_term_status.setStyleSheet(f"font-size: 11px; color: {MUTED};")
        term_btns.addWidget(self.lbl_term_status)
        term_btns.addStretch()
        btn_clear = QPushButton("Borrar log")
        btn_clear.clicked.connect(lambda: self.terminal.clear())
        term_btns.addWidget(btn_clear)
        term_lay.addLayout(term_btns)
        main.addWidget(term_frame, stretch=1)

        # --- Panel lateral ---
        side = QVBoxLayout()
        side.setSpacing(12)
        main.addLayout(side)

        # Uplink card
        ul_frame, ul_lay = card("Uplink (enviar por radio)", "📡")
        self.hex_input = QLineEdit()
        self.hex_input.setPlaceholderText("HEX, ej: DE AD BE EF  o  DEADBEEF")
        self.hex_input.returnPressed.connect(self.send_uplink)
        ul_lay.addWidget(self.hex_input)
        ascii_row = QHBoxLayout()
        self.ascii_mode = QCheckBox("Modo ASCII (texto → HEX)")
        self.ascii_mode.toggled.connect(self._toggle_ascii)
        ascii_row.addWidget(self.ascii_mode)
        ascii_row.addStretch()
        ul_lay.addLayout(ascii_row)
        self.btn_send = QPushButton("Enviar")
        self.btn_send.setObjectName("primary")
        self.btn_send.clicked.connect(self.send_uplink)
        ul_lay.addWidget(self.btn_send)
        chips = QHBoxLayout()
        for ex in ("DE AD BE EF", "HOLA", "OK"):
            b = QPushButton(ex)
            b.setObjectName("chip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, e=ex: self._fill_example(e))
            chips.addWidget(b)
        ul_lay.addLayout(chips)
        side.addWidget(ul_frame)

        # Downlink card
        dl_frame, dl_lay = card("Downlinks recibidos", "📥")
        self.dl_list = QListWidget()
        self.dl_list.setMaximumHeight(150)
        dl_lay.addWidget(self.dl_list)
        side.addWidget(dl_frame)

        # Estado card
        st_frame, st_lay = card("Estado", "📊")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        def add_stat(row, col, label):
            lab = QLabel(label)
            lab.setStyleSheet(f"font-size: 11px; color: {MUTED};")
            val = QLabel("—")
            val.setStyleSheet(f"font-size: 14px; font-weight: 800; color: {TEXT};")
            grid.addWidget(lab, row, col)
            grid.addWidget(val, row, col + 1)
            return val
        self.st_session   = add_stat(0, 0, "Sesión")
        self.st_radio     = add_stat(0, 2, "Radio")
        self.st_heartbeat = add_stat(1, 0, "Heartbeats")
        self.st_uplinks   = add_stat(1, 2, "Uplinks")
        self.st_downlinks = add_stat(2, 0, "Downlinks")
        self.st_rx        = add_stat(2, 2, "Bytes RX")
        st_lay.addLayout(grid)
        side.addWidget(st_frame)
        side.addStretch()

        # Temporizador de UI (última actividad)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._update_time)
        self._timer.start()

    # ------------------------------------------------------------------
    # Puertos / conexión
    # ------------------------------------------------------------------
    def refresh_ports(self):
        current = self.port_combo.currentText()
        self.port_combo.clear()
        ports = detect_ports()
        if not ports:
            self.port_combo.addItem("(sin puertos USB)")
            return
        for dev, desc in ports:
            self.port_combo.addItem(f"{dev}  ·  {desc}", dev)
        # Auto-detectar el CubeCell: probar con una sonda inofensiva
        # (solo si hay pocos puertos, para no ralentizar la UI)
        if len(ports) <= 4:
            for dev, _ in ports:
                if probe_cubecell(dev):
                    idx = self.port_combo.findData(dev)
                    if idx >= 0:
                        self.port_combo.setCurrentIndex(idx)
                    if hasattr(self, "lbl_term_status"):
                        self.lbl_term_status.setText(
                            f"Nodo detectado en {dev} · pulsa Conectar")
                    return
        # Re-seleccionar el puerto anterior si sigue existiendo
        idx = self.port_combo.findText(current[:12], Qt.MatchFlag.MatchStartsWith) \
            if current else -1
        if idx >= 0:
            self.port_combo.setCurrentIndex(idx)

    def toggle_connection(self):
        if self.ser is not None:
            self.disconnect_serial()
        else:
            self.connect_serial()

    def connect_serial(self):
        if self.port_combo.count() == 0:
            QMessageBox.warning(self, "Sin puertos",
                                "No se detectaron puertos USB serie. Conecta el nodo.")
            return
        port = self.port_combo.currentData()
        if not port:
            QMessageBox.warning(self, "Puerto inválido", "Selecciona un puerto válido.")
            return
        try:
            self.ser = serial.Serial(port, BAUD, timeout=0.2, write_timeout=2)
        except Exception as e:
            QMessageBox.critical(self, "Error de conexión",
                                 f"No se pudo abrir {port}:\n{e}\n\n"
                                 "¿Está el nodo conectado? ¿El puerto está ocupado por "
                                 "otra aplicación (monitor serial, arduino-cli)?")
            self.ser = None
            return

        self.reader = SerialReader(self.ser)
        self.reader.line_received.connect(self.on_line)
        self.reader.start()

        self._rx_bytes = 0
        self._tx_bytes = 0
        self._hb_count = 0
        self._ul_count = 0
        self._dl_count = 0
        self._connect_time = time.time()
        self.dl_list.clear()
        self.append_log(f"--- Conectado a {port} @ {BAUD} 8N1 "
                        f"({time.strftime('%H:%M:%S')}) ---", MUTED)
        self.set_status(True, port)

    def disconnect_serial(self):
        if self.reader:
            self.reader.stop()
            self.reader = None
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
        self.append_log(f"--- Desconectado ({time.strftime('%H:%M:%S')}) ---", MUTED)
        self.set_status(False, None)

    def set_status(self, connected, port):
        if connected:
            self.status_dot.setStyleSheet(f"color: {GREEN}; font-size: 14px;")
            self.status_text.setText(f"Conectado · {port}")
            self.status_text.setStyleSheet(f"font-weight: 600; color: {GREEN};")
            self.btn_connect.setText("Desconectar")
            self.btn_connect.setObjectName("danger")
            self.btn_connect.style().unpolish(self.btn_connect)
            self.btn_connect.style().polish(self.btn_connect)
            self.lbl_term_status.setText("en línea")
        else:
            self.status_dot.setStyleSheet(f"color: {RED}; font-size: 14px;")
            self.status_text.setText("Desconectado")
            self.status_text.setStyleSheet(f"font-weight: 600; color: {MUTED};")
            self.btn_connect.setText("Conectar")
            self.btn_connect.setObjectName("primary")
            self.btn_connect.style().unpolish(self.btn_connect)
            self.btn_connect.style().polish(self.btn_connect)
            self.lbl_term_status.setText("esperando conexión…")

    # ------------------------------------------------------------------
    # Escritura serial
    # ------------------------------------------------------------------
    def _write(self, raw: bytes):
        if self.ser is None:
            QMessageBox.warning(self, "Sin conexión", "Conéctate al puerto serial primero.")
            return False
        with self._write_lock:
            try:
                n = self.ser.write(raw)
                self.ser.flush()
            except Exception as e:
                QMessageBox.critical(self, "Error de escritura", str(e))
                return False
        self._tx_bytes += n
        self.st_rx.setText(f"{self._rx_bytes}")
        return True

    # ------------------------------------------------------------------
    # Uplink
    # ------------------------------------------------------------------
    def _toggle_ascii(self, enabled):
        if enabled:
            self.hex_input.setPlaceholderText("Texto ASCII, ej: HOLA MUNDO")
        else:
            self.hex_input.setPlaceholderText("HEX, ej: DE AD BE EF  o  DEADBEEF")

    def _fill_example(self, ex):
        self.ascii_mode.setChecked(False)
        self.hex_input.setText(ex)

    def send_uplink(self):
        text = self.hex_input.text().strip()
        if not text:
            self.append_log("[GUI] Escribe datos antes de enviar.", YELLOW)
            return
        if self.ascii_mode.isChecked():
            try:
                raw = text.encode("latin-1")
            except UnicodeEncodeError:
                self.append_log("[GUI] Modo ASCII: solo caracteres 0–255.", RED)
                return
            hex_str = " ".join(f"{b:02X}" for b in raw)
        else:
            cleaned = re.sub(r"[^0-9A-Fa-f]", "", text)
            if not cleaned or len(cleaned) % 2 != 0:
                self.append_log(
                    "[GUI] HEX inválido. Usa pares de dígitos, ej: DE AD BE EF", RED)
                return
            try:
                raw = bytes.fromhex(cleaned)
            except ValueError:
                self.append_log("[GUI] Formato hexadecimal incorrecto.", RED)
                return
            hex_str = " ".join(f"{b:02X}" for b in raw)

        if len(raw) == 0:
            return
        if len(raw) > MAX_PAYLOAD:
            self.append_log(f"[GUI] Payload demasiado largo: máx {MAX_PAYLOAD} bytes "
                            f"(recibidos {len(raw)}).", RED)
            return
        if self.ser is None:
            self.append_log("[GUI] Sin conexión serial. Conéctate primero.", RED)
            self.set_status(False, None)
            return

        prefix = "ASCII" if self.ascii_mode.isChecked() else "HEX"
        # Log local (el firmware además hace su eco ">> Enviando: ...")
        self.append_log(f"[GUI] Enviando ({prefix}): {hex_str}", ACCENT)
        self._write(hex_str.encode("utf-8") + b"\n")
        self._ul_count += 1       # se ajusta con el eco real del firmware
        self._update_stats()

    # ------------------------------------------------------------------
    # ERASE
    # ------------------------------------------------------------------
    def do_erase(self):
        ret = QMessageBox.question(
            self, "Confirmar ERASE",
            "¿Borrar la sesión persistida y reiniciar el nodo?\n\n"
            "Útil si reiniciaste el gateway/NS y hay conflicto de JoinNonce.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret == QMessageBox.StandardButton.Yes:
            self.append_log("[GUI] Enviando comando ERASE…", RED)
            self._write(b"ERASE\n")

    # ------------------------------------------------------------------
    # Procesamiento de líneas serial (terminal + parsing)
    # ------------------------------------------------------------------
    def on_line(self, line: str):
        self._rx_bytes += len(line.encode("utf-8", errors="replace"))
        self._classify(line)

    def _classify(self, line: str):
        color = TEXT
        bold = False

        if line.startswith(">> Enviando:"):
            color, bold = ACCENT, True
            m = RE_SENDING.search(line)
            if m:
                self._ul_count += 1
        elif line.startswith("[DOWNLINK]"):
            color, bold = GREEN, True
            self._dl_count += 1
            m = RE_DOWNLINK.search(line)
            if m:
                hex_part = m.group(1).strip()
                ascii_txt = m.group(2)
                ts = time.strftime("%H:%M:%S")
                self.dl_list.insertItem(0, QListWidgetItem(f"{ts}  {hex_part}  →  \"{ascii_txt}\""))
        elif "[HEARTBEAT]" in line:
            color, bold = BLUE, False
            self._hb_count += 1
        elif RE_ERROR.search(line):
            color, bold = RED, True
        elif RE_OK_DL.search(line) or line.startswith("-> OK"):
            color, bold = GREEN, False
        elif "+++ JOINED +++" in line or "SESION RESTAURADA" in line:
            color, bold = GREEN, True
        elif "Join FAILED" in line or "ERROR" in line or "FAILED" in line or "Fallo" in line:
            color, bold = RED, True
        elif "Radio OK" in line or "Node OK" in line:
            color, bold = GREEN, False
        elif line == "> " or line == ">":
            color = MUTED
        elif "Heartbeat" in line or "Modo manual" in line or "Comando ERASE" in line:
            color = MUTED

        self.append_log(line, color, bold=bold)

        # Estado
        if "+++ JOINED +++" in line:
            self.st_session.setText("JOINED ✓")
            self.st_session.setStyleSheet(f"font-size: 14px; font-weight: 800; color: {GREEN};")
        elif "SESION RESTAURADA" in line:
            self.st_session.setText("RESTAURADA")
            self.st_session.setStyleSheet(f"font-size: 14px; font-weight: 800; color: {BLUE};")
        elif "Join FAILED" in line or "NO_JOIN_ACCEPT" in line:
            self.st_session.setText("SIN JOIN")
            self.st_session.setStyleSheet(f"font-size: 14px; font-weight: 800; color: {RED};")
        elif "Radio OK" in line:
            self.st_radio.setText("OK ✓")
            self.st_radio.setStyleSheet(f"font-size: 14px; font-weight: 800; color: {GREEN};")
        elif "Radio init FAILED" in line:
            self.st_radio.setText("FALLO")
            self.st_radio.setStyleSheet(f"font-size: 14px; font-weight: 800; color: {RED};")

        self._update_stats()
        self.lbl_term_status.setText(
            f"RX {self._rx_bytes} B · TX {self._tx_bytes} B · "
            f"{time.strftime('%H:%M:%S')}")

    def _update_stats(self):
        self.st_heartbeat.setText(f"{self._hb_count}")
        self.st_uplinks.setText(f"{self._ul_count}")
        self.st_downlinks.setText(f"{self._dl_count}")
        self.st_rx.setText(f"{self._rx_bytes}")

    def _update_time(self):
        if self._connect_time:
            secs = int(time.time() - self._connect_time)
            self.lbl_term_status.setText(
                f"en línea {secs}s · RX {self._rx_bytes} B · TX {self._tx_bytes} B")

    # ------------------------------------------------------------------
    # Log con color
    # ------------------------------------------------------------------
    def append_log(self, text: str, color: str = TEXT, bold: bool = False):
        weight = "bold" if bold else "normal"
        self.terminal.appendHtml(
            f'<span style="color:{color}; font-weight:{weight};">'
            f'{text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")}'
            f'</span>')
        sb = self.terminal.verticalScrollBar()
        sb.setValue(sb.maximum())

    def closeEvent(self, event):
        self.disconnect_serial()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_ACRONYM)
    apply_style(app)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()