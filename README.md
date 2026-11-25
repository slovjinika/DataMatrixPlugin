![DataMatrix Generator for LibreOffice](image.png)

# DataMatrix Generator for LibreOffice

A lightweight, self-contained LibreOffice extension (`com.slovjinika.libreoffice.datamatrix`) that generates and inserts borderless, transparent-background **DataMatrix (ECC200)** barcodes directly into **Writer**, **Calc**, and **Draw**.

🖨️ [A4 sticker sheet generator](https://github.com/slovjinika/QR2A4)

## Features

* **Self-Contained ECC200 Encoder:** Built-in pure Python Reed-Solomon and ECC200 placement engine—no external CLI tools (`dmtxwrite`) or C-libraries (`libdmtx`) required.
* **Extended ASCII & Pad Byte Compliance:** Supports extended ASCII characters (`128–255`) and standard ECC200 ASCII pad/pseudo-random codewords (`129` + `253`-modulus pseudo-random fill).
* **Smart Density Packing:** Automatically uses ECC200 ASCII 2-digit packing to select the smallest possible square symbol (e.g., `10×10` for short numeric strings).
* **Custom HEX & Alpha Colors:** Customize module foreground and background colors using `#RGB`, `#RRGGBB`, or `#RRGGBBAA` hex codes (including transparent, semi-transparent, or solid fills).
* **Configurable Quiet Zone:** Adjust the margin around the barcode from `0` to `20` modules (defaulting to `1` module) directly in the dialog.
* **Crisp Scaling & Aspect Preservation:** Renders sharp nearest-neighbor PNG barcodes (`scale >= 12`) and preserves a selected shape's current square dimensions (`mm`) when editing.
* **In-Place Editing:** Select an existing DataMatrix barcode in your document and run the command again to edit its encoded text, colors, and quiet zone while keeping its size.
* **Metadata Persistence & Legacy Support:** Stores encoded data, colors, and quiet zone settings in JSON metadata (`DATAMATRIX_META::`), while remaining compatible with legacy `DATAMATRIX::` shapes.
* **Cross-Document Support:** Works in Writer text documents (`TextGraphicObject`) as well as Calc spreadsheets and Draw/Impress pages (`GraphicObjectShape`).
* **Minimalist Workflow & Safe Fallbacks:** Integrates into the menu and toolbar via a single dialog for data, HEX colors, and quiet zone, safely falling back to defaults on invalid HEX or out-of-range quiet zone inputs.

## Requirements

* **LibreOffice** 7.0 or newer (Writer, Calc, or Draw)
* **Pillow (`PIL`)** available in LibreOffice's Python environment (pre-installed on most Linux distributions; on Windows/macOS, ensure `Pillow` is installed in the bundled Python if not already present)

## Installation

### Option 1: Via Extension Manager (GUI)

1. Download the latest `slovjinika-datamatrix.oxt` from the [releases](https://github.com/slovjinika/DataMatrixPlugin/releases/) page.
2. Open LibreOffice and go to **Tools → Extension Manager...** (`Ctrl+Alt+E`).
3. Click **Add...**, select `slovjinika-datamatrix.oxt`, and accept the license.
4. Restart LibreOffice.

### Option 2: Via Command Line (`unopkg`)

```bash
unopkg add slovjinika-datamatrix.oxt

```

## Usage

1. Open a document in **Writer**, **Calc**, or **Draw**.
2. Go to **Insert → Insert/Edit DataMatrix** (or click the **Insert/Edit DataMatrix** toolbar button).
3. Enter the text or numeric string you want to encode and click **OK**.
4. To edit an existing barcode, click on the inserted DataMatrix image to select it and trigger **Insert/Edit DataMatrix** again.

## Building from Source

To package the extension `.oxt` archive from the repository root:

```bash
zip -r slovjinika-datamatrix.oxt \
  META-INF \
  description.xml \
  description_en.txt \
  LICENSE \
  Addons.xcu \
  ProtocolHandler.xcu \
  datamatrix_tool.py

```

```bash
pkill -f soffice.bin || true
zip -r ../slovjinika-datamatrix.oxt META-INF description.xml description_en.txt LICENSE Addons.xcu ProtocolHandler.xcu datamatrix_tool.py
unopkg remove com.slovjinika.libreoffice.datamatrix || true
unopkg add ../slovjinika-datamatrix.oxt
```


### Installing Pillow for LibreOffice's Bundled Python

On many Linux distributions, `Pillow` is already available in the system Python used by LibreOffice. On **Windows** and **macOS**, LibreOffice ships with its own embedded Python runtime, so `Pillow` must be installed directly into it.

#### Windows (PowerShell)
1. Completely close LibreOffice (make sure no `soffice.bin` processes are still running).
2. Open **PowerShell** and run (adjust the path if LibreOffice is installed in a custom location):

```powershell
& "C:\Program Files\LibreOffice\program\python.exe" -m pip install --upgrade pip Pillow

```

#### macOS (Terminal)

1. Completely quit LibreOffice (`Cmd + Q`).
2. Open **Terminal** and run:

```bash
/Applications/LibreOffice.app/Contents/Frameworks/LibreOfficePython.framework/Versions/Current/bin/python3 -m pip install Pillow

```

#### Verify Installation

Restart LibreOffice and confirm that `Pillow` imports cleanly:

```powershell
# Windows (PowerShell)
& "C:\Program Files\LibreOffice\program\python.exe" -c "import PIL; print(PIL.__version__)"

```

```bash
# macOS (Terminal)
/Applications/LibreOffice.app/Contents/Frameworks/LibreOfficePython.framework/Versions/Current/bin/python3 -c "import PIL; print(PIL.__version__)"

```

> **Note:** If you hit permission errors on Windows, run PowerShell **as Administrator** or add `--user` to the install command. If `pip` is not yet bootstrapped in LibreOffice's Python environment, run `-m ensurepip` first before `pip install Pillow`.


## License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.
