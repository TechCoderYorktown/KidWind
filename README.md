# KidWind Airfoil Slicer

THS Windbreakers supplemental material: a Windows desktop app for turning
Selig-format airfoil coordinate files into printable STL slabs.

## Work from source

The maintained application is `airfoil_slicer_gui.py`. The PyInstaller recipe is
`AirfoilSlicer.spec`; bundled executables and intermediate build products are
generated files and are not needed to edit or rebuild the app.

Requirements: Windows, Python 3.10 or newer, and a Python installation that
includes Tcl/Tk.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python airfoil_slicer_gui.py
```

## Build and share the Windows app

From the activated environment, run:

```powershell
pyinstaller --noconfirm --clean AirfoilSlicer.spec
Compress-Archive -Path .\dist\AirfoilSlicer\* -DestinationPath .\dist\AirfoilSlicer-Portable.zip -Force
```

The executable is `dist\AirfoilSlicer\AirfoilSlicer.exe`. Share the complete
`AirfoilSlicer-Portable.zip`, not the executable by itself. Recipients should
extract the archive and run `AirfoilSlicer.exe` alongside its `_internal` folder.

## Use the app

Choose a Selig-format airfoil `.dat` or coordinate `.txt` file. The app rejects
profiles that cannot be made into one valid airfoil outline. Set 1–20 airfoils,
then enter individual values or formulas where `x` is the airfoil index and the
innermost/largest airfoil is `x = 1`. Formulas support parentheses and normal
arithmetic, for example `5.5-0.35*(x-1)`.

Thickness follows chord scaling by default. Choose **Custom** to set each
airfoil's maximum Y thickness manually or with a formula using `x`. The preview
lays out the airfoils side by side on one plane. **Export STL slabs** writes one
millimeter STL per airfoil into the selected output folder, ready to open in a
slicer. Filenames include the source airfoil name, chord length, maximum Y
thickness (both in mm), and optional filename note.

Use **Save project…** and **Load project…** to preserve and restore a setup.
Project files embed the validated airfoil outline, so they do not depend on the
original coordinate file remaining in the same location.
