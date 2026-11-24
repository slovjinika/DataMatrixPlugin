# Copyright (c) 2026 slovjinika
# Licensed under the MIT License. See LICENSE file in the extension root for details.

import io
import json
import os
import sys
import tempfile
import traceback
import uno
import unohelper
from com.sun.star.awt import Point, Size, XActionListener
from com.sun.star.beans import PropertyValue
from com.sun.star.frame import XDispatch, XDispatchProvider
from com.sun.star.lang import XServiceInfo

IMPLEMENTATION_NAME = "com.slovjinika.libreoffice.datamatrix.HandlerImpl"
SERVICE_NAMES = ("com.sun.star.frame.ProtocolHandler",)
PROTOCOL_NAME = "vnd.slovjinika.datamatrix:"
DM_META_PREFIX = "DATAMATRIX_META::"
DM_LEGACY_PREFIX = "DATAMATRIX::"
DEFAULT_SIZE_MM = 20.0

# DataMatrix ECC200 square symbol sizes:
# (rows, cols, data_codewords, ec_codewords, rs_blocks)
_ECC200_SIZES = [
    (10, 10, 3, 5, 1),
    (12, 12, 5, 7, 1),
    (14, 14, 8, 10, 1),
    (16, 16, 12, 12, 1),
    (18, 18, 18, 14, 1),
    (20, 20, 22, 18, 1),
    (22, 22, 30, 20, 1),
    (24, 24, 36, 24, 1),
    (26, 26, 44, 28, 1),
    (32, 32, 62, 36, 1),
    (36, 36, 86, 42, 1),
    (40, 40, 114, 48, 1),
    (44, 44, 144, 56, 1),
]


def _gf_mul(a: int, b: int, poly: int = 0x12D) -> int:
    """Multiply two numbers in GF(256) with polynomial x^8 + x^5 + x^3 + x^2 + 1 (0x12D)."""
    res = 0
    while b:
        if b & 1:
            res ^= a
        b >>= 1
        a <<= 1
        if a & 0x100:
            a ^= poly
    return res & 0xFF


def _rs_encode(data_cw: list[int], ec_count: int) -> list[int]:
    """Compute Reed-Solomon error correction codewords over GF(256)."""
    poly = [1]
    for i in range(1, ec_count + 1):
        exp_val = 1
        for _ in range(i):
            exp_val = _gf_mul(exp_val, 2)
        next_poly = [0] * (len(poly) + 1)
        for idx, coeff in enumerate(poly):
            next_poly[idx] ^= coeff
            next_poly[idx + 1] ^= _gf_mul(coeff, exp_val)
        poly = next_poly

    gen = poly[1:]
    ec = [0] * ec_count
    for cw in data_cw:
        factor = cw ^ ec[0]
        ec = ec[1:] + [0]
        for j, g in enumerate(gen):
            ec[j] ^= _gf_mul(factor, g)
    return ec


def _encode_ascii_codewords(text: str, capacity: int) -> list[int]:
    """Encode text in ECC200 ASCII mode (with 2-digit packing) and pad to capacity."""
    cws: list[int] = []
    i = 0
    n = len(text)

    while i < n and len(cws) < capacity:
        # Pack two consecutive ASCII digits into a single codeword: 130 + dd + 1 -> 130 + d1*10 + d2
        if text[i].isdigit() and (i + 1) < n and text[i + 1].isdigit():
            d1 = int(text[i])
            d2 = int(text[i + 1])
            cws.append(130 + d1 * 10 + d2)
            i += 2
            continue

        b = ord(text[i]) & 0xFF
        if b <= 127:
            cws.append(b + 1)
        else:
            cws.append(235)
            if len(cws) < capacity:
                cws.append(((b - 128) + 1) & 0xFF)
        i += 1

    if len(cws) < capacity:
        cws.append(129)  # ASCII pad codeword

    while len(cws) < capacity:
        idx = len(cws) + 1
        pseudo_random = ((149 * idx) % 253) + 1
        temp = 129 + pseudo_random
        if temp > 254:
            temp -= 254
        cws.append(temp)

    return cws[:capacity]


def _encoded_codeword_length(text: str) -> int:
    """Estimate number of ECC200 ASCII codewords needed for text."""
    count = 0
    i = 0
    n = len(text)
    while i < n:
        if text[i].isdigit() and (i + 1) < n and text[i + 1].isdigit():
            count += 1
            i += 2
        else:
            b = ord(text[i]) & 0xFF
            count += 1 if b <= 127 else 2
            i += 1
    return count


def _place_ecc200_matrix(rows: int, cols: int, codewords: list[int]) -> list[list[int]]:
    """Place ECC200 codewords into a (rows x cols) bit matrix including finder/timing borders."""
    inner_r = rows - 2
    inner_c = cols - 2
    grid = [[0] * inner_c for _ in range(inner_r)]
    visited = [[False] * inner_c for _ in range(inner_r)]

    def module(r: int, c: int, cw_idx: int, bit_idx: int):
        r_mod = r % inner_r
        c_mod = c % inner_c
        if r_mod < 0:
            r_mod += inner_r
        if c_mod < 0:
            c_mod += inner_c
        if not visited[r_mod][c_mod]:
            bit = (codewords[cw_idx] >> (8 - bit_idx)) & 1
            grid[r_mod][c_mod] = bit
            visited[r_mod][c_mod] = True

    def utah(r: int, c: int, cw_idx: int):
        module(r - 2, c - 2, cw_idx, 1)
        module(r - 2, c - 1, cw_idx, 2)
        module(r - 1, c - 2, cw_idx, 3)
        module(r - 1, c - 1, cw_idx, 4)
        module(r - 1, c, cw_idx, 5)
        module(r, c - 2, cw_idx, 6)
        module(r, c - 1, cw_idx, 7)
        module(r, c, cw_idx, 8)

    def corner1(cw_idx: int):
        module(inner_r - 1, 0, cw_idx, 1)
        module(inner_r - 1, 1, cw_idx, 2)
        module(inner_r - 1, 2, cw_idx, 3)
        module(0, inner_c - 2, cw_idx, 4)
        module(0, inner_c - 1, cw_idx, 5)
        module(1, inner_c - 1, cw_idx, 6)
        module(2, inner_c - 1, cw_idx, 7)
        module(3, inner_c - 1, cw_idx, 8)

    def corner2(cw_idx: int):
        module(inner_r - 3, 0, cw_idx, 1)
        module(inner_r - 2, 0, cw_idx, 2)
        module(inner_r - 1, 0, cw_idx, 3)
        module(0, inner_c - 4, cw_idx, 4)
        module(0, inner_c - 3, cw_idx, 5)
        module(0, inner_c - 2, cw_idx, 6)
        module(0, inner_c - 1, cw_idx, 7)
        module(1, inner_c - 1, cw_idx, 8)

    def corner3(cw_idx: int):
        module(inner_r - 3, 0, cw_idx, 1)
        module(inner_r - 2, 0, cw_idx, 2)
        module(inner_r - 1, 0, cw_idx, 3)
        module(0, inner_c - 2, cw_idx, 4)
        module(0, inner_c - 1, cw_idx, 5)
        module(1, inner_c - 1, cw_idx, 6)
        module(2, inner_c - 1, cw_idx, 7)
        module(3, inner_c - 1, cw_idx, 8)

    def corner4(cw_idx: int):
        module(inner_r - 1, 0, cw_idx, 1)
        module(inner_r - 1, inner_c - 1, cw_idx, 2)
        module(0, inner_c - 3, cw_idx, 3)
        module(0, inner_c - 2, cw_idx, 4)
        module(0, inner_c - 1, cw_idx, 5)
        module(1, inner_c - 3, cw_idx, 6)
        module(1, inner_c - 2, cw_idx, 7)
        module(1, inner_c - 1, cw_idx, 8)

    r, c, cw_idx = 4, 0, 0
    total_cw = len(codewords)
    while cw_idx < total_cw:
        if r == inner_r and c == 0 and cw_idx < total_cw:
            corner1(cw_idx)
            cw_idx += 1
        if r == inner_r - 2 and c == 0 and (inner_c % 4) != 0 and cw_idx < total_cw:
            corner2(cw_idx)
            cw_idx += 1
        if r == inner_r - 2 and c == 0 and (inner_c % 8) == 4 and cw_idx < total_cw:
            corner3(cw_idx)
            cw_idx += 1
        if r == inner_r + 4 and c == 2 and (inner_c % 8) == 0 and cw_idx < total_cw:
            corner4(cw_idx)
            cw_idx += 1

        while True:
            if r < inner_r and c >= 0 and not visited[r][c] and cw_idx < total_cw:
                utah(r, c, cw_idx)
                cw_idx += 1
            r -= 2
            c += 2
            if not (r >= 0 and c < inner_c):
                break
        r += 1
        c += 3

        while True:
            if r >= 0 and c < inner_c and not visited[r][c] and cw_idx < total_cw:
                utah(r, c, cw_idx)
                cw_idx += 1
            r += 2
            c -= 2
            if not (r < inner_r and c >= 0):
                break
        r += 3
        c += 1

        if not (r < inner_r or c < inner_c):
            break

    for ir in range(inner_r):
        for ic in range(inner_c):
            if not visited[ir][ic]:
                grid[ir][ic] = 1

    full = [[0] * cols for _ in range(rows)]
    for x in range(cols):
        full[rows - 1][x] = 1
        full[0][x] = 1 if (x % 2 == 0) else 0
    for y in range(rows):
        full[y][0] = 1
        full[y][cols - 1] = 1 if (y % 2 == 1) else 0

    for ir in range(inner_r):
        for ic in range(inner_c):
            full[ir + 1][ic + 1] = grid[ir][ic]

    return full


def _generate_datamatrix_matrix(text: str) -> list[list[int]]:
    """Select the smallest square ECC200 symbol fitting the encoded codewords."""
    needed = _encoded_codeword_length(text)
    for rows, cols, data_cw_count, ec_cw_count, _ in _ECC200_SIZES:
        if needed <= data_cw_count:
            data_cw = _encode_ascii_codewords(text, data_cw_count)
            ec_cw = _rs_encode(data_cw, ec_cw_count)
            return _place_ecc200_matrix(rows, cols, data_cw + ec_cw)

    rows, cols, data_cw_count, ec_cw_count, _ = _ECC200_SIZES[-1]
    data_cw = _encode_ascii_codewords(text, data_cw_count)
    ec_cw = _rs_encode(data_cw, ec_cw_count)
    return _place_ecc200_matrix(rows, cols, data_cw + ec_cw)


def render_datamatrix_png_bytes(text: str) -> bytes:
    """Render a compact transparent DataMatrix barcode with a 1-module quiet zone."""
    from PIL import Image

    matrix = _generate_datamatrix_matrix(text)
    rows = len(matrix)
    cols = len(matrix[0]) if rows else 1
    quiet = 1
    total_w = cols + quiet * 2
    total_h = rows + quiet * 2

    base_img = Image.new("RGBA", (total_w, total_h), (255, 255, 255, 0))
    pixels = base_img.load()
    for r in range(rows):
        for c in range(cols):
            if matrix[r][c]:
                pixels[c + quiet, r + quiet] = (0, 0, 0, 255)

    scale = max(12, 240 // max(1, max(total_w, total_h)))
    img = base_img.resize(
        (total_w * scale, total_h * scale),
        resample=Image.Resampling.NEAREST,
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _load_graphic_from_png_bytes(ctx, png_bytes: bytes):
    """Load an XGraphic safely via a temporary file URL."""
    provider = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.graphic.GraphicProvider", ctx
    )
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(png_bytes)
            tmp_path = tmp.name
        file_url = uno.systemPathToFileUrl(os.path.abspath(tmp_path))
        graphic = provider.queryGraphic(
            (PropertyValue(Name="URL", Value=file_url),)
        )
        if graphic is None:
            raise RuntimeError("Failed to load graphic object from PNG file.")
        return graphic
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _parse_metadata(description: str, fallback_size_mm: float = DEFAULT_SIZE_MM):
    """Parse stored DataMatrix text from a shape Description."""
    desc = description or ""
    if desc.startswith(DM_META_PREFIX):
        raw = desc[len(DM_META_PREFIX) :]
        try:
            data = json.loads(raw)
            return {"text": str(data.get("text", "")), "size_mm": fallback_size_mm}
        except Exception:
            pass
    if desc.startswith(DM_LEGACY_PREFIX):
        return {"text": desc[len(DM_LEGACY_PREFIX) :], "size_mm": fallback_size_mm}
    return None


def _format_metadata(text: str) -> str:
    """Serialize DataMatrix text into a JSON-backed description string."""
    return f"{DM_META_PREFIX}{json.dumps({'text': text}, ensure_ascii=False)}"


class _DialogActionListener(unohelper.Base, XActionListener):
    def __init__(self, dialog, state):
        super().__init__()
        self.dialog = dialog
        self.state = state

    def actionPerformed(self, event):
        cmd = getattr(event, "ActionCommand", "")
        if cmd == "OK":
            edit_ctrl = self.dialog.getControl("EditText")
            if edit_ctrl is not None:
                self.state["text"] = edit_ctrl.getText()
            self.state["accepted"] = True
            self.dialog.endExecute()
        elif cmd == "CANCEL":
            self.state["accepted"] = False
            self.dialog.endExecute()


def show_datamatrix_dialog(ctx, title: str, initial_text: str):
    """Display a minimal dialog with only a text field."""
    smgr = ctx.ServiceManager
    dp = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", ctx)
    dp.Width = 240
    dp.Height = 76
    dp.Title = title

    lbl_text = dp.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    lbl_text.PositionX = 10
    lbl_text.PositionY = 12
    lbl_text.Width = 40
    lbl_text.Height = 14
    lbl_text.Label = "Data:"
    dp.insertByName("LblText", lbl_text)

    edit_text = dp.createInstance("com.sun.star.awt.UnoControlEditModel")
    edit_text.PositionX = 52
    edit_text.PositionY = 10
    edit_text.Width = 178
    edit_text.Height = 16
    edit_text.Text = initial_text
    dp.insertByName("EditText", edit_text)

    ok_btn = dp.createInstance("com.sun.star.awt.UnoControlButtonModel")
    ok_btn.PositionX = 122
    ok_btn.PositionY = 44
    ok_btn.Width = 50
    ok_btn.Height = 18
    ok_btn.Label = "OK"
    ok_btn.DefaultButton = True
    dp.insertByName("BtnOK", ok_btn)

    cancel_btn = dp.createInstance("com.sun.star.awt.UnoControlButtonModel")
    cancel_btn.PositionX = 178
    cancel_btn.PositionY = 44
    cancel_btn.Width = 52
    cancel_btn.Height = 18
    cancel_btn.Label = "Cancel"
    dp.insertByName("BtnCancel", cancel_btn)

    dialog = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", ctx)
    dialog.setModel(dp)

    state = {"accepted": False, "text": initial_text}
    listener = _DialogActionListener(dialog, state)

    c_ok = dialog.getControl("BtnOK")
    c_ok.setActionCommand("OK")
    c_ok.addActionListener(listener)

    c_cancel = dialog.getControl("BtnCancel")
    c_cancel.setActionCommand("CANCEL")
    c_cancel.addActionListener(listener)

    toolkit = smgr.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
    dialog.createPeer(toolkit, None)
    try:
        dialog.execute()
    finally:
        c_ok.removeActionListener(listener)
        c_cancel.removeActionListener(listener)
        dialog.dispose()

    if not state["accepted"]:
        return None
    return state["text"]


def get_selected_datamatrix_shape(doc):
    """Return (shape, metadata_dict) for the selected DataMatrix graphic, or (None, None)."""
    try:
        sel = doc.getCurrentSelection()
    except Exception:
        return None, None
    if sel is None:
        return None, None

    candidates = []
    try:
        if sel.supportsService("com.sun.star.drawing.GraphicObjectShape") or sel.supportsService(
            "com.sun.star.text.TextGraphicObject"
        ):
            candidates.append(sel)
        elif hasattr(sel, "getCount"):
            for i in range(sel.getCount()):
                item = sel.getByIndex(i)
                if item.supportsService(
                    "com.sun.star.drawing.GraphicObjectShape"
                ) or item.supportsService("com.sun.star.text.TextGraphicObject"):
                    candidates.append(item)
    except Exception:
        return None, None

    for shape in candidates:
        desc = getattr(shape, "Description", "") or ""
        current_mm = DEFAULT_SIZE_MM
        try:
            current_mm = float(shape.Size.Width) / 100.0
        except Exception:
            pass
        meta = _parse_metadata(desc, fallback_size_mm=current_mm)
        if meta is not None:
            return shape, meta
    return None, None


def _shape_size_from_mm(size_mm: float) -> Size:
    """Convert square size in mm (1 mm = 100 UNO units) into a Size struct."""
    width_100mm = max(100, int(round(size_mm * 100.0)))
    return Size(width_100mm, width_100mm)


def insert_or_update_datamatrix(ctx, doc, text: str, existing_shape=None):
    """Insert a new plain DataMatrix graphic or update an existing one."""
    png_bytes = render_datamatrix_png_bytes(text)
    graphic = _load_graphic_from_png_bytes(ctx, png_bytes)
    meta_desc = _format_metadata(text)

    if existing_shape is not None:
        current_mm = DEFAULT_SIZE_MM
        try:
            current_mm = float(existing_shape.Size.Width) / 100.0
        except Exception:
            pass
        existing_shape.Graphic = graphic
        existing_shape.Size = _shape_size_from_mm(current_mm)
        existing_shape.Description = meta_desc
        return

    shape_size = _shape_size_from_mm(DEFAULT_SIZE_MM)
    if doc.supportsService("com.sun.star.text.TextDocument"):
        obj = doc.createInstance("com.sun.star.text.TextGraphicObject")
        controller = doc.getCurrentController()
        vc = controller.getViewCursor() if controller is not None else None
        target_text = vc.getText() if (vc is not None and hasattr(vc, "getText")) else doc.Text
        anchor = vc.getEnd() if (vc is not None and hasattr(vc, "getEnd")) else target_text.getStart()
        target_text.insertTextContent(anchor, obj, False)
        obj.Graphic = graphic
        obj.Size = shape_size
        obj.Description = meta_desc
    elif hasattr(doc, "getDrawPages"):
        controller = doc.getCurrentController()
        if doc.supportsService("com.sun.star.sheet.SpreadsheetDocument"):
            page = controller.getActiveSheet().DrawPage
        else:
            page = controller.getCurrentPage()
        shape = doc.createInstance("com.sun.star.drawing.GraphicObjectShape")
        page.add(shape)
        shape.Position = Point(2000, 2000)
        shape.Size = shape_size
        shape.Graphic = graphic
        shape.Description = meta_desc


class DataMatrixDispatch(unohelper.Base, XDispatch):
    def __init__(self, ctx, frame):
        super().__init__()
        self.ctx = ctx
        self.frame = frame

    def dispatch(self, url, args):
        try:
            controller = self.frame.getController() if self.frame is not None else None
            if controller is None:
                return
            doc = controller.getModel()
            if doc is None:
                return

            existing_shape, meta = get_selected_datamatrix_shape(doc)
            is_edit = existing_shape is not None
            title = "Edit DataMatrix" if is_edit else "Insert DataMatrix"
            init_text = meta["text"] if meta else ""

            text = show_datamatrix_dialog(
                self.ctx,
                title=title,
                initial_text=init_text,
            )
            if text is None or text == "":
                return

            insert_or_update_datamatrix(
                self.ctx,
                doc,
                text=text,
                existing_shape=existing_shape,
            )
        except Exception as exc:
            print(f"[DataMatrix] dispatch error: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

    def addStatusListener(self, listener, url):
        pass

    def removeStatusListener(self, listener, url):
        pass


class DataMatrixProtocolHandler(unohelper.Base, XDispatchProvider, XServiceInfo):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    def _get_active_frame(self):
        try:
            desktop = self.ctx.getByName("/singletons/com.sun.star.frame.theDesktop")
            frame = desktop.getCurrentFrame()
            if frame is not None:
                return frame
            return desktop.getActiveFrame()
        except Exception:
            return None

    def queryDispatch(self, url, target_frame_name, search_flags):
        complete_url = getattr(url, "Complete", "") or ""
        proto = (getattr(url, "Protocol", "") or "").rstrip(":")
        expected_proto = PROTOCOL_NAME.rstrip(":")
        if proto == expected_proto or complete_url.startswith(PROTOCOL_NAME):
            frame = self._get_active_frame()
            if frame is not None:
                return DataMatrixDispatch(self.ctx, frame)
        return None

    def queryDispatches(self, requests):
        return tuple(
            self.queryDispatch(r.FeatureURL, r.FrameName, r.SearchFlags)
            for r in requests
        )

    def getImplementationName(self):
        return IMPLEMENTATION_NAME

    def supportsService(self, name):
        return name in SERVICE_NAMES

    def getSupportedServiceNames(self):
        return SERVICE_NAMES


g_ImplementationHelper = unohelper.ImplementationHelper()
g_ImplementationHelper.addImplementation(
    DataMatrixProtocolHandler,
    IMPLEMENTATION_NAME,
    SERVICE_NAMES,
)