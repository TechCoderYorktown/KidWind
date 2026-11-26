"""Interactive airfoil-slab generator.

Run with:  python airfoil_slicer_gui.py
Requires: numpy, shapely, trimesh, matplotlib, and mapbox_earcut (already used by
the original generator).  It accepts validated Selig-style .dat and .txt airfoil files.
"""
from __future__ import annotations

import ast
import json
import math
import re
import warnings
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
import trimesh
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


LENGTH_UNITS = {"mm": 0.001, "cm": 0.01, "m": 1.0, "in": 0.0254}
ANGLE_UNITS = {"deg": 1.0, "rad": 180 / math.pi}


def read_airfoil(path: str) -> Polygon:
    """Parse a Selig-style .dat/.txt file and reject inputs that are not airfoils."""
    if Path(path).suffix.lower() not in {".dat", ".txt"}:
        raise ValueError("Choose an airfoil coordinate file with a .dat or .txt extension.")
    rows = []
    for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        tokens = line.replace(",", " ").split()
        if len(tokens) != 2:
            continue
        try:
            rows.append((float(tokens[0]), float(tokens[1])))
        except ValueError:
            continue  # header / comments are allowed
    if len(rows) < 12:
        raise ValueError("A valid airfoil .dat needs at least 12 coordinate rows.")
    pts = np.asarray(rows, dtype=float)
    if not np.all(np.isfinite(pts)):
        raise ValueError("The coordinate file contains non-finite values.")
    xspan = np.ptp(pts[:, 0])
    yspan = np.ptp(pts[:, 1])
    if xspan <= 1e-8 or yspan <= 1e-8 or yspan > 1.5 * xspan:
        raise ValueError("These coordinates do not describe a usable airfoil outline.")
    # Reject common Lednicer count-line layouts rather than silently making a bad blade.
    if pts[0, 0] > 1.5 and pts[0, 1] > 1.5:
        raise ValueError("Lednicer format is not supported. Convert it to Selig .dat format first.")
    keep = np.r_[True, np.any(np.abs(np.diff(pts, axis=0)) > 1e-10, axis=1)]
    pts = pts[keep]
    pts[:, 0] -= pts[:, 0].min()
    pts /= np.ptp(pts[:, 0])
    poly = Polygon(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if isinstance(poly, MultiPolygon):
        poly = max(poly.geoms, key=lambda p: p.area)
    if poly.is_empty or poly.area <= 1e-6 or not poly.is_valid:
        raise ValueError("The coordinates cannot form one valid, closed airfoil polygon.")
    return poly


def vertical_span(poly: Polygon, x: float) -> tuple[float, float]:
    _, ymin, _, ymax = poly.bounds
    hit = poly.intersection(LineString([(x, ymin - 1), (x, ymax + 1)]))
    if hit.is_empty:
        raise ValueError("The spar location lies outside this airfoil.")
    _, lo, _, hi = hit.bounds
    if hi - lo <= 0:
        raise ValueError("The airfoil has no usable thickness at the spar location.")
    return lo, hi


def safe_formula(expression: str, x: float) -> float:
    """Evaluate a small numerical expression using only x and math functions."""
    allowed = {name: getattr(math, name) for name in ("sin", "cos", "tan", "sqrt", "log", "exp", "pi")}
    allowed["x"] = x
    tree = ast.parse(expression, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
                                 ast.Name, ast.Load, ast.Call, ast.Add, ast.Sub, ast.Mult, ast.Div,
                                 ast.Pow, ast.USub, ast.UAdd, ast.Mod)):
            raise ValueError("Only numbers, x, + - * / **, and basic math functions are allowed.")
        if isinstance(node, ast.Name) and node.id not in allowed:
            raise ValueError(f"'{node.id}' is not allowed in a formula.")
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in allowed):
            raise ValueError("That function is not allowed in a formula.")
    value = float(eval(compile(tree, "<formula>", "eval"), {"__builtins__": {}}, allowed))
    if not math.isfinite(value):
        raise ValueError("The formula produced a non-finite value.")
    return value


def layout_shapes_on_plane(shapes: list[Polygon], spacing: float) -> list[Polygon]:
    """Place shapes side by side along X without changing their original geometry."""
    laid_out = []
    next_x = 0.0
    for shape in shapes:
        min_x = shape.bounds[0]
        placed = affinity.translate(shape, xoff=next_x - min_x)
        laid_out.append(placed)
        next_x = max(placed.bounds[2], next_x) + spacing
    return laid_out


def filename_note(value: str) -> str:
    """Make optional filename text safe on Windows and other common filesystems."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")


class AirfoilSlicer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Airfoil Slicer")
        self.geometry("1440x900")
        self.minsize(1050, 650)
        self.airfoil: Polygon | None = None
        self.airfoil_source_name = ""
        self.current_project_path: Path | None = None
        self.last_shapes: list[Polygon] = []
        self._vars()
        self._build()
        self.update_fields()

    def _vars(self):
        self.file_var = tk.StringVar()
        self.count = tk.IntVar(value=9)
        self.chord_mode = tk.StringVar(value="Manual list")
        self.chord_formula = tk.StringVar(value="150 - 5*(x-1)")
        self.thickness_mode = tk.StringVar(value="Proportional to chord")
        self.thickness_custom_mode = tk.StringVar(value="Manual list")
        self.thickness_formula = tk.StringVar()
        self.twist_mode = tk.StringVar(value="Manual list")
        self.twist_formula = tk.StringVar(value="2*(x-1)")
        self.spar_type = tk.StringVar(value="Round")
        self.spar_x = tk.StringVar(value="25")
        self.spar_size = tk.StringVar(value="6.35")
        self.tolerance = tk.StringVar(value="0.25")
        self.le_size = tk.StringVar(value="0")
        self.te_size = tk.StringVar(value="0")
        self.slab = tk.StringVar(value="3")
        self.spacing = tk.StringVar(value="12")
        self.output_dir = tk.StringVar(value=str(Path.cwd() / "airfoil_stls"))
        self.filename_note = tk.StringVar()
        self.status = tk.StringVar(value="Choose a valid Selig-format .dat or .txt airfoil file.")
        self.chord_vars: list[tk.StringVar] = []
        self.thickness_vars: list[tk.StringVar] = []
        self.twist_vars: list[tk.StringVar] = []
        self.chord_unit_vars: list[tk.StringVar] = []
        self.thickness_unit_vars: list[tk.StringVar] = []
        self.twist_unit_vars: list[tk.StringVar] = []
        self.chord_formula_unit = tk.StringVar(value="mm")
        self.thickness_formula_unit = tk.StringVar(value="mm")
        self.twist_formula_unit = tk.StringVar(value="deg")

    def field(self, parent, label, var, units=tuple(LENGTH_UNITS), width=9):
        row = ttk.Frame(parent)
        ttk.Label(row, text=label, width=22).pack(side="left")
        ttk.Entry(row, textvariable=var, width=width).pack(side="left", padx=(0, 5))
        unit = ttk.Combobox(row, values=units, width=5, state="readonly")
        unit.set(units[0])
        unit.pack(side="left")
        row.unit = unit
        row.pack(fill="x", pady=2)
        return row

    def _build(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Header.TLabel", font=("Segoe UI", 11, "bold"))
        outer = ttk.Panedwindow(self, orient="horizontal")
        outer.pack(fill="both", expand=True, padx=8, pady=8)
        left = ttk.Frame(outer, padding=4); right = ttk.Frame(outer, padding=8)
        outer.add(left, weight=4); outer.add(right, weight=2)
        self.figure = Figure(facecolor="#20252b")
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, left)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        ttk.Label(left, text="Live blade layout — inner / largest airfoil is #1", style="Header.TLabel").pack(anchor="w")
        ttk.Label(left, textvariable=self.status, foreground="#287a45", wraplength=750).pack(anchor="w", pady=(3, 0))

        canvas = tk.Canvas(right, highlightthickness=0)
        scroll = ttk.Scrollbar(right, orient="vertical", command=canvas.yview)
        self.controls = ttk.Frame(canvas)
        self.controls.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        self.control_window = canvas.create_window((0, 0), window=self.controls, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True); scroll.pack(side="right", fill="y")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(self.control_window, width=e.width))

        self.section_file()
        self.section_layout()
        self.section_spar()
        self.section_edges()
        self.section_output()
        buttons = ttk.Frame(self.controls); buttons.pack(fill="x", pady=10)
        ttk.Button(buttons, text="Update preview", command=self.preview).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(buttons, text="Export STL slabs", command=self.export).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Label(self.controls, text="Limits: 1–20 airfoils. Dimensions are converted internally to meters.", wraplength=370).pack(fill="x", pady=(0, 12))
        self.draw_empty()

    def group(self, title):
        f = ttk.LabelFrame(self.controls, text=title, padding=7); f.pack(fill="x", pady=4)
        return f

    def section_file(self):
        f = self.group("Airfoil source (.dat or coordinate .txt)")
        row = ttk.Frame(f); row.pack(fill="x")
        ttk.Entry(row, textvariable=self.file_var).pack(side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(row, text="Browse…", command=self.choose_file).pack(side="right")
        project_buttons = ttk.Frame(f); project_buttons.pack(fill="x", pady=(5, 0))
        ttk.Button(project_buttons, text="Load project…", command=self.load_project).pack(side="left", expand=True, fill="x", padx=(0, 2))
        ttk.Button(project_buttons, text="Save project…", command=self.save_project).pack(side="left", expand=True, fill="x", padx=(2, 0))

    def section_layout(self):
        f = self.group("Airfoil count, chord, thickness & twist")
        r = ttk.Frame(f); r.pack(fill="x", pady=2)
        ttk.Label(r, text="Airfoils (largest is #1)", width=22).pack(side="left")
        ttk.Spinbox(r, from_=1, to=20, textvariable=self.count, width=7, command=self.update_fields).pack(side="left")
        ttk.Label(r, text=" sections").pack(side="left")
        for label, var, choices in [
            ("Chord lengths", self.chord_mode, ("Manual list", "Function of x")),
            ("Thickness scaling", self.thickness_mode, ("Proportional to chord", "Custom")),
            ("Twist sequence", self.twist_mode, ("Manual list", "Function of x")),
        ]:
            r = ttk.Frame(f); r.pack(fill="x", pady=2)
            ttk.Label(r, text=label, width=22).pack(side="left")
            ttk.Combobox(r, textvariable=var, values=choices, state="readonly", width=22).pack(side="left")
            var.trace_add("write", lambda *_: self.update_fields())
        self.chord_holder = ttk.Frame(f); self.chord_holder.pack(fill="x", pady=(4, 1))
        self.thickness_holder = ttk.Frame(f); self.thickness_holder.pack(fill="x", pady=(4, 1))
        self.twist_holder = ttk.Frame(f); self.twist_holder.pack(fill="x", pady=(4, 1))
        self.thickness_custom_mode.trace_add("write", lambda *_: self.update_fields())

    def section_spar(self):
        f = self.group("Center spar")
        r = ttk.Frame(f); r.pack(fill="x", pady=2)
        ttk.Label(r, text="Profile", width=22).pack(side="left")
        ttk.Radiobutton(r, text="Round", variable=self.spar_type, value="Round", command=self.update_fields).pack(side="left")
        ttk.Radiobutton(r, text="Square", variable=self.spar_type, value="Square", command=self.update_fields).pack(side="left")
        r = self.field(f, "Spar location", self.spar_x, ("% chord",)); r.unit.set("% chord")
        self.spar_size_row = self.field(f, "Diameter", self.spar_size)
        self.tolerance_row = self.field(f, "Print tolerance", self.tolerance)
        ttk.Label(f, text="Square holes stay axis-aligned while the airfoil twists.", wraplength=360).pack(anchor="w", pady=(2, 0))

    def section_edges(self):
        f = self.group("Leading / trailing edge circle cutouts")
        self.le_row = self.field(f, "Leading-edge diameter", self.le_size)
        self.te_row = self.field(f, "Trailing-edge diameter", self.te_size)
        self.slab_row = self.field(f, "Slab thickness", self.slab)
        self.spacing_row = self.field(f, "Airfoil spacing", self.spacing)
        ttk.Label(f, text="Use 0 to leave an edge uncut.", wraplength=360).pack(anchor="w")

    def section_output(self):
        f = self.group("Export")
        row = ttk.Frame(f); row.pack(fill="x")
        ttk.Entry(row, textvariable=self.output_dir).pack(side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(row, text="Folder…", command=self.choose_folder).pack(side="right")
        ttk.Label(f, text="Filename note (optional)").pack(anchor="w", pady=(5, 0))
        ttk.Entry(f, textvariable=self.filename_note).pack(fill="x")

    def choose_file(self):
        path = filedialog.askopenfilename(title="Choose airfoil coordinates", filetypes=[("Airfoil coordinates", "*.dat *.txt"), ("DAT files", "*.dat"), ("Text coordinate files", "*.txt")])
        if not path: return
        try:
            self.airfoil = read_airfoil(path)
            self.airfoil_source_name = Path(path).name
            self.file_var.set(path); self.status.set(f"Validated airfoil: {Path(path).name}")
            self.preview()
        except Exception as exc:
            self.airfoil = None; messagebox.showerror("Invalid airfoil file", str(exc))

    def project_data(self):
        if self.airfoil is None:
            raise ValueError("Choose and validate an airfoil before saving a project.")
        count = max(1, min(20, int(self.count.get() or 1)))
        return {
            "format": "airfoil-slicer-project",
            "version": 1,
            "airfoil": {
                "name": self.airfoil_source_name or "airfoil.dat",
                "coordinates": [[float(x), float(y)] for x, y in self.airfoil.exterior.coords],
            },
            "settings": {
                "count": count,
                "chord_mode": self.chord_mode.get(),
                "chord_formula": self.chord_formula.get(),
                "chord_formula_unit": self.chord_formula_unit.get(),
                "chord_values": [var.get() for var in self.chord_vars[:count]],
                "chord_units": [self.chord_unit_vars[i].get() if i < len(self.chord_unit_vars) else "mm"
                                for i in range(count)],
                "thickness_mode": self.thickness_mode.get(),
                "thickness_custom_mode": self.thickness_custom_mode.get(),
                "thickness_formula": self.thickness_formula.get(),
                "thickness_formula_unit": self.thickness_formula_unit.get(),
                "thickness_values": [var.get() for var in self.thickness_vars[:count]],
                "thickness_units": [self.thickness_unit_vars[i].get() if i < len(self.thickness_unit_vars) else "mm"
                                    for i in range(count)],
                "twist_mode": self.twist_mode.get(),
                "twist_formula": self.twist_formula.get(),
                "twist_formula_unit": self.twist_formula_unit.get(),
                "twist_values": [var.get() for var in self.twist_vars[:count]],
                "twist_units": [self.twist_unit_vars[i].get() if i < len(self.twist_unit_vars) else "deg"
                                for i in range(count)],
                "spar_type": self.spar_type.get(),
                "spar_x": self.spar_x.get(),
                "spar_size": self.spar_size.get(),
                "spar_size_unit": self.spar_size_row.unit.get(),
                "tolerance": self.tolerance.get(),
                "tolerance_unit": self.tolerance_row.unit.get(),
                "le_size": self.le_size.get(),
                "le_unit": self.le_row.unit.get(),
                "te_size": self.te_size.get(),
                "te_unit": self.te_row.unit.get(),
                "slab": self.slab.get(),
                "slab_unit": self.slab_row.unit.get(),
                "spacing": self.spacing.get(),
                "spacing_unit": self.spacing_row.unit.get(),
                "output_dir": self.output_dir.get(),
                "filename_note": self.filename_note.get(),
            },
        }

    def read_project(self, path: str | Path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("format") != "airfoil-slicer-project" or data.get("version") != 1:
            raise ValueError("This is not a supported Airfoil Slicer project file.")
        airfoil_data = data.get("airfoil")
        settings = data.get("settings")
        if not isinstance(airfoil_data, dict) or not isinstance(settings, dict):
            raise ValueError("The project is missing its airfoil or settings.")
        name = airfoil_data.get("name")
        coordinates = airfoil_data.get("coordinates")
        if not isinstance(name, str) or not name or Path(name).name != name:
            raise ValueError("The project contains an invalid airfoil name.")
        if not isinstance(coordinates, list) or len(coordinates) < 4:
            raise ValueError("The project does not contain valid airfoil coordinates.")
        try:
            points = [(float(point[0]), float(point[1])) for point in coordinates
                      if isinstance(point, list) and len(point) == 2]
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("The project contains invalid airfoil coordinates.") from exc
        if len(points) != len(coordinates) or not all(math.isfinite(value) for point in points for value in point):
            raise ValueError("The project contains invalid airfoil coordinates.")
        airfoil = Polygon(points)
        if not airfoil.is_valid or airfoil.is_empty or airfoil.area <= 1e-6:
            raise ValueError("The embedded airfoil outline is not a valid polygon.")

        count = settings.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 20:
            raise ValueError("The project airfoil count must be between 1 and 20.")
        string_fields = (
            "chord_mode", "chord_formula", "chord_formula_unit",
            "thickness_mode", "thickness_custom_mode", "thickness_formula",
            "thickness_formula_unit", "twist_mode", "twist_formula",
            "twist_formula_unit", "spar_type", "spar_x", "spar_size",
            "spar_size_unit", "tolerance", "tolerance_unit", "le_size",
            "le_unit", "te_size", "te_unit", "slab", "slab_unit", "spacing",
            "spacing_unit", "output_dir", "filename_note",
        )
        if any(not isinstance(settings.get(key), str) for key in string_fields):
            raise ValueError("The project contains missing or invalid settings.")
        if settings["chord_mode"] not in ("Manual list", "Function of x"):
            raise ValueError("The project has an unsupported chord mode.")
        if settings["thickness_mode"] not in ("Proportional to chord", "Custom"):
            raise ValueError("The project has an unsupported thickness mode.")
        if settings["thickness_custom_mode"] not in ("Manual list", "Function of x"):
            raise ValueError("The project has an unsupported custom thickness mode.")
        if settings["twist_mode"] not in ("Manual list", "Function of x") or settings["spar_type"] not in ("Round", "Square"):
            raise ValueError("The project contains an unsupported setting.")
        for key in ("chord_formula_unit", "thickness_formula_unit", "spar_size_unit",
                    "tolerance_unit", "le_unit", "te_unit", "slab_unit", "spacing_unit"):
            if settings[key] not in LENGTH_UNITS:
                raise ValueError(f"The project contains an unsupported unit for {key}.")
        for key in ("twist_formula_unit",):
            if settings[key] not in ANGLE_UNITS:
                raise ValueError(f"The project contains an unsupported unit for {key}.")
        for key in ("chord_values", "chord_units", "thickness_values", "thickness_units",
                    "twist_values", "twist_units"):
            values = settings.get(key)
            if not isinstance(values, list) or len(values) != count or any(not isinstance(value, str) for value in values):
                raise ValueError(f"The project contains invalid per-airfoil values for {key}.")
        for key in ("chord_units", "thickness_units"):
            if any(unit not in LENGTH_UNITS for unit in settings[key]):
                raise ValueError(f"The project contains an unsupported unit for {key}.")
        if any(unit not in ANGLE_UNITS for unit in settings["twist_units"]):
            raise ValueError("The project contains an unsupported unit for twist values.")
        return airfoil, name, settings

    def save_project(self):
        try:
            initial_name = self.current_project_path.name if self.current_project_path else "airfoil_project.airfoilproj"
            path = filedialog.asksaveasfilename(
                title="Save Airfoil Slicer project",
                defaultextension=".airfoilproj",
                initialfile=initial_name,
                filetypes=[("Airfoil Slicer project", "*.airfoilproj"), ("JSON files", "*.json")],
            )
            if not path:
                return
            Path(path).write_text(json.dumps(self.project_data(), indent=2), encoding="utf-8")
            self.current_project_path = Path(path)
            self.status.set(f"Project saved: {path}")
        except (OSError, TypeError, ValueError) as exc:
            self.status.set(f"Project save failed: {exc}")
            messagebox.showerror("Cannot save project", str(exc))

    def load_project(self):
        path = filedialog.askopenfilename(
            title="Load Airfoil Slicer project",
            filetypes=[("Airfoil Slicer project", "*.airfoilproj"), ("JSON files", "*.json")],
        )
        if not path:
            return
        try:
            airfoil, name, settings = self.read_project(path)
            self.count.set(settings["count"])
            self.chord_mode.set(settings["chord_mode"])
            self.chord_formula.set(settings["chord_formula"])
            self.chord_formula_unit.set(settings["chord_formula_unit"])
            self.thickness_mode.set(settings["thickness_mode"])
            self.thickness_custom_mode.set(settings["thickness_custom_mode"])
            self.thickness_formula.set(settings["thickness_formula"])
            self.thickness_formula_unit.set(settings["thickness_formula_unit"])
            self.twist_mode.set(settings["twist_mode"])
            self.twist_formula.set(settings["twist_formula"])
            self.twist_formula_unit.set(settings["twist_formula_unit"])
            self.spar_type.set(settings["spar_type"])
            self.spar_x.set(settings["spar_x"])
            self.spar_size.set(settings["spar_size"])
            self.tolerance.set(settings["tolerance"])
            self.le_size.set(settings["le_size"])
            self.te_size.set(settings["te_size"])
            self.slab.set(settings["slab"])
            self.spacing.set(settings["spacing"])
            self.output_dir.set(settings["output_dir"])
            self.filename_note.set(settings["filename_note"])
            self.spar_size_row.unit.set(settings["spar_size_unit"])
            self.tolerance_row.unit.set(settings["tolerance_unit"])
            self.le_row.unit.set(settings["le_unit"])
            self.te_row.unit.set(settings["te_unit"])
            self.slab_row.unit.set(settings["slab_unit"])
            self.spacing_row.unit.set(settings["spacing_unit"])
            self.update_fields()
            for variables, values in (
                (self.chord_vars, settings["chord_values"]),
                (self.thickness_vars, settings["thickness_values"]),
                (self.twist_vars, settings["twist_values"]),
                (self.chord_unit_vars, settings["chord_units"]),
                (self.thickness_unit_vars, settings["thickness_units"]),
                (self.twist_unit_vars, settings["twist_units"]),
            ):
                for variable, value in zip(variables, values):
                    variable.set(value)
            self.airfoil = airfoil
            self.airfoil_source_name = name
            self.file_var.set(f"Embedded airfoil: {name}")
            self.current_project_path = Path(path)
            self.status.set(f"Project loaded: {Path(path).name}")
            self.preview()
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self.status.set(f"Project load failed: {exc}")
            messagebox.showerror("Cannot load project", str(exc))

    def choose_folder(self):
        path = filedialog.askdirectory(title="Choose output folder")
        if path: self.output_dir.set(path)

    def update_fields(self):
        n = max(1, min(20, int(self.count.get() or 1)))
        self.count.set(n)
        for holder in (self.chord_holder, self.thickness_holder, self.twist_holder):
            for child in holder.winfo_children():
                child.destroy()
        while len(self.chord_vars) < n: self.chord_vars.append(tk.StringVar(value=str(150 - 5 * len(self.chord_vars))))
        while len(self.thickness_vars) < n: self.thickness_vars.append(tk.StringVar(value=""))
        while len(self.twist_vars) < n: self.twist_vars.append(tk.StringVar(value=str(2 * len(self.twist_vars))))
        while len(self.chord_unit_vars) < n: self.chord_unit_vars.append(tk.StringVar(value="mm"))
        while len(self.thickness_unit_vars) < n: self.thickness_unit_vars.append(tk.StringVar(value="mm"))
        while len(self.twist_unit_vars) < n: self.twist_unit_vars.append(tk.StringVar(value="deg"))
        if self.chord_mode.get() == "Function of x":
            ttk.Label(self.chord_holder, text="Chord formula; x = airfoil index (1 is largest)").pack(anchor="w")
            r = ttk.Frame(self.chord_holder); r.pack(fill="x"); ttk.Entry(r, textvariable=self.chord_formula).pack(side="left", fill="x", expand=True); ttk.Combobox(r, textvariable=self.chord_formula_unit, values=tuple(LENGTH_UNITS), width=5, state="readonly").pack(side="left", padx=(4, 0))
        else:
            ttk.Label(self.chord_holder, text="Chord per airfoil").pack(anchor="w")
            for i in range(n): self._mini(self.chord_holder, f"#{i+1}", self.chord_vars[i], self.chord_unit_vars[i], tuple(LENGTH_UNITS))
        if self.thickness_mode.get() == "Proportional to chord":
            ttk.Label(self.thickness_holder, text="Y thickness follows the chord scale.").pack(anchor="w")
        else:
            ttk.Label(self.thickness_holder, text="Custom maximum Y thickness").pack(anchor="w")
            r = ttk.Frame(self.thickness_holder); r.pack(fill="x")
            ttk.Combobox(r, textvariable=self.thickness_custom_mode, values=("Manual list", "Function of x"), width=15, state="readonly").pack(side="left")
            if self.thickness_custom_mode.get() == "Function of x":
                ttk.Label(r, text="Formula").pack(side="left", padx=(6, 2))
                ttk.Entry(r, textvariable=self.thickness_formula).pack(side="left", fill="x", expand=True)
                ttk.Combobox(r, textvariable=self.thickness_formula_unit, values=tuple(LENGTH_UNITS), width=5, state="readonly").pack(side="left", padx=(4, 0))
            else:
                for i in range(n): self._mini(self.thickness_holder, f"#{i+1}", self.thickness_vars[i], self.thickness_unit_vars[i], tuple(LENGTH_UNITS))
        if self.twist_mode.get() == "Function of x":
            ttk.Label(self.twist_holder, text="Twist formula; x = airfoil index (1 is largest)").pack(anchor="w")
            r = ttk.Frame(self.twist_holder); r.pack(fill="x"); ttk.Entry(r, textvariable=self.twist_formula).pack(side="left", fill="x", expand=True); ttk.Combobox(r, textvariable=self.twist_formula_unit, values=tuple(ANGLE_UNITS), width=5, state="readonly").pack(side="left", padx=(4, 0))
        else:
            ttk.Label(self.twist_holder, text="Twist per airfoil").pack(anchor="w")
            for i in range(n): self._mini(self.twist_holder, f"#{i+1}", self.twist_vars[i], self.twist_unit_vars[i], tuple(ANGLE_UNITS))
        if self.spar_type.get() == "Square": self.spar_size_row.winfo_children()[0].configure(text="Square side")
        else: self.spar_size_row.winfo_children()[0].configure(text="Diameter")

    def _mini(self, parent, label, var, unit_var, units):
        r = ttk.Frame(parent); r.pack(fill="x", pady=1)
        ttk.Label(r, text=label, width=4).pack(side="left"); ttk.Entry(r, textvariable=var, width=10).pack(side="left"); ttk.Combobox(r, textvariable=unit_var, values=units, width=5, state="readonly").pack(side="left", padx=(4, 0))

    @staticmethod
    def number(value, label):
        try: value = float(value)
        except ValueError: raise ValueError(f"{label} must be a number.")
        if not math.isfinite(value): raise ValueError(f"{label} must be finite.")
        return value

    def dim(self, value, row, label, allow_zero=False):
        result = self.number(value, label) * LENGTH_UNITS[row.unit.get()]
        if result < 0 or (result == 0 and not allow_zero): raise ValueError(f"{label} must be positive.")
        return result

    def inputs(self):
        if not self.airfoil: raise ValueError("Choose and validate an airfoil .dat file first.")
        n = self.count.get()
        if not 1 <= n <= 20: raise ValueError("Airfoil count must be between 1 and 20.")
        if self.chord_mode.get() == "Function of x":
            chords = [safe_formula(self.chord_formula.get(), i + 1) * LENGTH_UNITS[self.chord_formula_unit.get()] for i in range(n)]
        else:
            chords = [self.number(v.get(), f"Chord #{i+1}") * LENGTH_UNITS[self.chord_unit_vars[i].get()] for i, v in enumerate(self.chord_vars[:n])]
        if self.twist_mode.get() == "Function of x":
            twists = [safe_formula(self.twist_formula.get(), i + 1) * ANGLE_UNITS[self.twist_formula_unit.get()] for i in range(n)]
        else:
            twists = [self.number(v.get(), f"Twist #{i+1}") * ANGLE_UNITS[self.twist_unit_vars[i].get()] for i, v in enumerate(self.twist_vars[:n])]
        chords = np.asarray(chords)
        if np.any(chords <= 0): raise ValueError("Every chord length must be positive.")
        source_y_span = self.airfoil.bounds[3] - self.airfoil.bounds[1]
        if self.thickness_mode.get() == "Custom":
            if self.thickness_custom_mode.get() == "Function of x":
                thicknesses = [safe_formula(self.thickness_formula.get(), i + 1) * LENGTH_UNITS[self.thickness_formula_unit.get()] for i in range(n)]
            else:
                thicknesses = [self.number(v.get(), f"Thickness #{i+1}") * LENGTH_UNITS[self.thickness_unit_vars[i].get()] for i, v in enumerate(self.thickness_vars[:n])]
        else:
            thicknesses = [chord * source_y_span for chord in chords]
        thicknesses = np.asarray(thicknesses)
        if np.any(thicknesses <= 0): raise ValueError("Every airfoil thickness must be positive.")
        xfrac = self.number(self.spar_x.get(), "Spar location") / 100
        if not 0.02 <= xfrac <= 0.98: raise ValueError("Spar location must be between 2% and 98% chord.")
        return chords, thicknesses, np.asarray(twists), dict(xfrac=xfrac, spar=self.dim(self.spar_size.get(), self.spar_size_row, "Spar size"), clearance=self.dim(self.tolerance.get(), self.tolerance_row, "Tolerance", True), le=self.dim(self.le_size.get(), self.le_row, "Leading-edge cutout", True), te=self.dim(self.te_size.get(), self.te_row, "Trailing-edge cutout", True), slab=self.dim(self.slab.get(), self.slab_row, "Slab thickness"), spacing=self.dim(self.spacing.get(), self.spacing_row, "Airfoil spacing"))

    def shape(self, chord, y_thickness, twist, p):
        source_y_span = self.airfoil.bounds[3] - self.airfoil.bounds[1]
        poly = affinity.scale(self.airfoil, xfact=chord, yfact=y_thickness / source_y_span, origin=(0, 0))
        minx, _, maxx, _ = poly.bounds; hx = minx + p["xfrac"] * chord; y0, y1 = vertical_span(poly, hx); hy = (y0 + y1) / 2
        outer = poly
        cuts = []
        if p["le"]:
            y0, y1 = vertical_span(poly, minx + p["le"] / 2); cuts.append(Point(minx, (y0+y1)/2).buffer(p["le"] / 2, quad_segs=24))
        if p["te"]:
            y0, y1 = vertical_span(poly, maxx - p["te"] / 2); cuts.append(Point(maxx, (y0+y1)/2).buffer(p["te"] / 2, quad_segs=24))
        if cuts: poly = poly.difference(unary_union(cuts))
        poly = affinity.translate(affinity.rotate(poly, twist, origin=(hx, hy)), -hx, -hy)
        outer = affinity.translate(affinity.rotate(outer, twist, origin=(hx, hy)), -hx, -hy)
        size = p["spar"] + p["clearance"]
        hole = Point(0, 0).buffer(size / 2, quad_segs=32) if self.spar_type.get() == "Round" else box(-size/2, -size/2, size/2, size/2)
        if not outer.contains(hole): raise ValueError(f"Spar hole does not fit inside the {chord*1000:.1f} mm airfoil.")
        result = poly.difference(hole)
        if isinstance(result, MultiPolygon): result = max(result.geoms, key=lambda g: g.area)
        if result.is_empty: raise ValueError("A cutout removed the entire airfoil.")
        return result

    def preview(self):
        try:
            self.last_shapes = []
            chords, thicknesses, twists, p = self.inputs()
            self.last_shapes = [self.shape(c, y, t, p) for c, y, t in zip(chords, thicknesses, twists)]
            self.ax.clear(); self.ax.set_facecolor("#20252b")
            for i, shape in enumerate(layout_shapes_on_plane(self.last_shapes, p["spacing"])):
                x, y = shape.exterior.xy; self.ax.plot(x, y, color="#5ec8ff", linewidth=1.7)
                for ring in shape.interiors:
                    x, y = ring.xy; self.ax.plot(x, y, color="#ffad4d", linewidth=1.2)
                minx, _, maxx, maxy = shape.bounds
                self.ax.text((minx + maxx) / 2, maxy + p["spacing"] * 0.2,
                             f"#{i+1}", color="white", size=8, ha="center")
            self.ax.set_xlabel("Chord / layout (m)", color="white"); self.ax.set_ylabel("Thickness (m)", color="white")
            self.ax.tick_params(colors="white"); self.ax.set_aspect("equal", adjustable="datalim")
            self.figure.tight_layout(); self.canvas.draw_idle()
            self.status.set(f"Preview updated: {len(self.last_shapes)} validated airfoil slabs.")
        except Exception as exc:
            self.status.set(f"Preview needs attention: {exc}"); messagebox.showerror("Cannot render preview", str(exc))

    def draw_empty(self):
        self.ax.set_facecolor("#20252b"); self.ax.text(.16, .5, "Select a validated .dat airfoil\nthen update the preview", transform=self.ax.transAxes, color="white", fontsize=14); self.ax.set_axis_off(); self.canvas.draw_idle()

    def export(self):
        try:
            self.preview()
            if not self.last_shapes: return
            chords, _, _, p = self.inputs(); out = Path(self.output_dir.get()); out.mkdir(parents=True, exist_ok=True)
            base = Path(self.airfoil_source_name).stem
            note = filename_note(self.filename_note.get())
            used_names = set()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                for i, (shape, chord) in enumerate(zip(self.last_shapes, chords), 1):
                    mesh = trimesh.creation.extrude_polygon(shape, height=p["slab"], engine="earcut")
                    mesh.apply_scale(1000)  # output STL is millimeters for slicers
                    thickness = (shape.bounds[3] - shape.bounds[1]) * 1000
                    parts = [base, f"{chord * 1000:.2f}mm", f"{thickness:.2f}mm"]
                    if note:
                        parts.append(note)
                    filename = "_".join(parts)
                    if filename in used_names:
                        filename = f"{filename}_{i:02d}"
                    used_names.add(filename)
                    mesh.export(out / f"{filename}.stl")
            self.status.set(f"Exported {len(self.last_shapes)} STL slabs to {out}")
            messagebox.showinfo("Export complete", f"Wrote {len(self.last_shapes)} STL slabs to:\n{out}")
        except Exception as exc:
            self.status.set(f"Export failed: {exc}"); messagebox.showerror("Export failed", str(exc))


if __name__ == "__main__":
    AirfoilSlicer().mainloop()
