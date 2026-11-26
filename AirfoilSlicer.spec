# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_dynamic_libs

tcl_root = Path(sys.prefix) / 'tcl'

datas = [
    (str(tcl_root / 'tcl8.6'), '_tcl_data'),
    (str(tcl_root / 'tk8.6'), '_tk_data'),
    # PyInstaller's Tk collection skips this startup script on this Python build.
    (str(tcl_root / 'tcl8.6' / 'init.tcl'), '_tcl_data'),
]
binaries = []
datas += collect_data_files('matplotlib')
binaries += collect_dynamic_libs('shapely')


a = Analysis(
    ['airfoil_slicer_gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=['matplotlib.backends.backend_tkagg'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PySide6', 'tensorflow', 'torch', 'IPython', 'pandas', 'xarray', 'dask', 'boto3', 'botocore', 'numba', 'pyarrow', 'tables', 'openpyxl', 'h5py', 'netCDF4', 'statsmodels', 'sklearn'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AirfoilSlicer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AirfoilSlicer',
)
