# Airfoil Slicer

Open `dist\AirfoilSlicer\AirfoilSlicer.exe` to run the Windows app. To share it,
send `dist\AirfoilSlicer-Portable.zip`; the recipient should extract the complete
folder and run `AirfoilSlicer.exe` from inside it. The app and its support files
stay together, so startup does not depend on a build-machine path or temporary
folder. Do not send the EXE by itself.

You can also run the source version from this folder:

```powershell
python airfoil_slicer_gui.py
```

Use **Save project…** and **Load project…** to preserve and restore a setup.
Project files embed the validated airfoil outline, so they do not depend on the
original coordinate file remaining in the same location.

Choose a Selig-format airfoil `.dat` file or a coordinate `.txt` file. The app rejects
profiles that cannot be made into one valid airfoil outline. Set 1–20 airfoils,
then use either individual values or a formula where `x` is the airfoil index and
the innermost/largest airfoil is `x = 1`. Formulas support parentheses and normal
arithmetic, for example `5.5-0.35*(x-1)`.
Thickness follows chord scaling by default. Choose `Custom` to set each airfoil's
maximum Y thickness manually or with a formula of `x`, using the selected length
units.

The preview lays out the airfoils side by side on one plane. `Export STL slabs`
writes one millimeter STL per airfoil into the selected output folder, ready to open
in a slicer. Filenames include the source airfoil name, chord length, maximum Y
thickness (both in mm), and optional filename note.
