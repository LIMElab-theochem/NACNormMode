

from __future__ import annotations

import argparse
import math
import os
import re
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
MPL_CACHE_DIR = SCRIPT_DIR / ".mpl_cache"
FONTCONFIG_CACHE_DIR = SCRIPT_DIR / ".fontconfig_cache"


def find_venv_python() -> Path | None:
    candidates: list[Path] = []
    seen: set[str] = set()

    def add_candidate(path: Path) -> None:
        normalized = str(path.expanduser().absolute())
        if normalized in seen:
            return
        seen.add(normalized)
        candidates.append(Path(normalized))

    add_candidate(SCRIPT_DIR / ".venv" / "bin" / "python")

    # Allow copied scripts to reuse the main project environment.
    for root in (
        Path("/Users/ciro/Documents/NewProject"),
        Path("/Users/ciro/Documents/New project"),
    ):
        add_candidate(root / ".venv" / "bin" / "python")

    for base in (Path.cwd(), SCRIPT_DIR):
        for parent in (base, *base.parents):
            add_candidate(parent / ".venv" / "bin" / "python")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def ensure_project_venv() -> None:
    MPL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    FONTCONFIG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(MPL_CACHE_DIR))
    os.environ.setdefault("XDG_CACHE_HOME", str(FONTCONFIG_CACHE_DIR))
    if os.environ.get("NAC_FCHK_MATRIX_NO_REEXEC") == "1":
        return
    venv_python = find_venv_python()
    if venv_python is None:
        return
    current_prefix = Path(getattr(sys, "prefix", "")).resolve()
    target_prefix = venv_python.parent.parent.resolve()
    if current_prefix == target_prefix:
        return
    env = os.environ.copy()
    env["NAC_FCHK_MATRIX_NO_REEXEC"] = "1"
    os.execve(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]], env)


ensure_project_venv()


FCHK_NAME_RE = re.compile(r".*\.fchk$", re.IGNORECASE)
LOG_NAME_RE = re.compile(r".*\.log\d*$", re.IGNORECASE)
HEADER_RE = re.compile(r"Nonadiabatic Coup\.")
DATA_RE = re.compile(
    r"^\s*\d+\s+\d+\s+"
    r"([+-]?\d*\.?\d+(?:[DdEe][+-]?\d+)?)\s+"
    r"([+-]?\d*\.?\d+(?:[DdEe][+-]?\d+)?)\s+"
    r"([+-]?\d*\.?\d+(?:[DdEe][+-]?\d+)?)\s*$"
)
DASH_RE = re.compile(r"^\s*-+\s*$")

ELEMENTS = {
    1: "H",
    2: "He",
    3: "Li",
    4: "Be",
    5: "B",
    6: "C",
    7: "N",
    8: "O",
    9: "F",
    10: "Ne",
    11: "Na",
    12: "Mg",
    13: "Al",
    14: "Si",
    15: "P",
    16: "S",
    17: "Cl",
    18: "Ar",
}

SOLVENT_PATTERNS = [
    ("vacuum", ("vacuum", "vacuo")),
    ("dcm", ("dcm", "dichloromethane")),
    ("meth", ("meth", "methanol")),
    ("cyc", ("cyc", "cyclohexane")),
    ("water", ("water",)),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Costruisce la matrice L dai file .fchk, legge i NACME dai .log corrispondenti "
            "e trasforma il NAC cartesiano sui modi normali."
        )
    )
    parser.add_argument(
        "--fchk",
        help="File .fchk esplicito da usare per il pairing manuale.",
    )
    parser.add_argument(
        "--log",
        help="File .log esplicito da usare per il pairing manuale.",
    )
    parser.add_argument(
        "--plot-dir",
        help="Cartella dove salvare i grafici PNG/PDF. Default: <cartella_script>/nac_plots",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Uno o piu' file .fchk oppure cartelle che contengono .fchk e .log.",
    )
    return parser.parse_args()


def to_float(token: str) -> float:
    return float(token.replace("D", "E").replace("d", "e"))


def iter_paths(paths: list[str], predicate) -> list[Path]:
    files: list[Path] = []

    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Percorso non trovato: {path}")

        if path.is_file():
            if predicate(path):
                files.append(path)
            continue

        if path.is_dir():
            matches = sorted(child for child in path.iterdir() if child.is_file() and predicate(child))
            files.extend(matches)
            continue

        raise ValueError(f"Percorso non supportato: {path}")

    unique_files: list[Path] = []
    seen: set[Path] = set()
    for file_path in files:
        resolved = file_path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_files.append(file_path)
    return unique_files


def iter_fchk_files(paths: list[str]) -> list[Path]:
    return iter_paths(paths, lambda path: bool(FCHK_NAME_RE.match(path.name)))


def iter_log_files(paths: list[str]) -> list[Path]:
    parent_dirs = {Path(raw_path).expanduser().parent if Path(raw_path).expanduser().is_file() else Path(raw_path).expanduser()
                   for raw_path in paths}
    return iter_paths([str(parent) for parent in sorted(parent_dirs)], lambda path: bool(LOG_NAME_RE.match(path.name)))


def read_fchk_array(lines: list[str], start_index: int) -> tuple[list[float], int]:
    count = int(lines[start_index].split()[-1])
    values: list[float] = []
    cursor = start_index + 1
    while cursor < len(lines) and len(values) < count:
        values.extend(to_float(token) for token in lines[cursor].split())
        cursor += 1
    if len(values) < count:
        raise ValueError(f"Array incompleto nel file .fchk a partire dalla riga {start_index + 1}")
    return values[:count], cursor


def read_fchk_int_array(lines: list[str], start_index: int) -> tuple[list[int], int]:
    count = int(lines[start_index].split()[-1])
    values: list[int] = []
    cursor = start_index + 1
    while cursor < len(lines) and len(values) < count:
        values.extend(int(token) for token in lines[cursor].split())
        cursor += 1
    if len(values) < count:
        raise ValueError(f"Array intero incompleto nel file .fchk a partire dalla riga {start_index + 1}")
    return values[:count], cursor


def read_fchk_scalar_int(line: str) -> int:
    return int(line.split()[-1])


def parse_fchk(fchk_path: Path) -> dict[str, object]:
    with fchk_path.open("r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()

    data: dict[str, object] = {}
    idx = 0
    while idx < len(lines):
        line = lines[idx]

        if line.startswith("Number of atoms"):
            data["n_atoms"] = read_fchk_scalar_int(line)
            idx += 1
            continue

        if line.startswith("Atomic numbers"):
            data["atomic_numbers"], idx = read_fchk_int_array(lines, idx)
            continue

        if line.startswith("Real atomic weights"):
            data["real_atomic_weights"], idx = read_fchk_array(lines, idx)
            continue

        if line.startswith("Current cartesian coordinates"):
            data["current_cartesian_coordinates"], idx = read_fchk_array(lines, idx)
            continue

        if line.startswith("Number of Normal Modes"):
            data["n_modes"] = read_fchk_scalar_int(line)
            idx += 1
            continue

        if line.startswith("Vib-AtMass"):
            data["vib_at_mass"], idx = read_fchk_array(lines, idx)
            continue

        if line.startswith("Vib-E2"):
            data["vib_e2"], idx = read_fchk_array(lines, idx)
            continue

        if line.startswith("Vib-Modes"):
            data["vib_modes"], idx = read_fchk_array(lines, idx)
            continue

        idx += 1

    required = ["n_atoms", "atomic_numbers", "n_modes", "vib_e2", "vib_modes"]
    missing = [field for field in required if field not in data]
    if missing:
        if any(field in missing for field in ("n_modes", "vib_e2", "vib_modes")):
            raise ValueError(
                f"Campi mancanti in {fchk_path}: {', '.join(missing)}. "
                "Questo file non sembra un .fchk di frequenze: manca la sezione vibrazionale "
                "(Number of Normal Modes / Vib-E2 / Vib-Modes). Usa il .fchk prodotto dal job freq=HPModes."
            )
        raise ValueError(f"Campi mancanti in {fchk_path}: {', '.join(missing)}")

    if "vib_at_mass" not in data:
        if "real_atomic_weights" not in data:
            raise ValueError(f"Nessuna massa atomica trovata in {fchk_path}")
        data["vib_at_mass"] = data["real_atomic_weights"]

    return data


def parse_last_nac_block_from_log(log_path: Path) -> list[float]:
    last_block: list[float] = []
    current_block: list[float] = []
    inside_block = False
    saw_data = False

    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if HEADER_RE.search(line):
                inside_block = True
                saw_data = False
                current_block = []
                continue

            if not inside_block:
                continue

            match = DATA_RE.match(line)
            if match:
                current_block.extend(to_float(value) for value in match.groups())
                saw_data = True
                continue

            if saw_data and DASH_RE.match(line):
                last_block = current_block[:]
                inside_block = False

    if inside_block and saw_data:
        last_block = current_block[:]

    if not last_block:
        raise ValueError(f"Nessun blocco 'Nonadiabatic Coup.' trovato in {log_path}")

    return last_block


def parse_last_standard_orientation_from_log(log_path: Path) -> tuple[list[int], list[float]]:
    atomic_numbers: list[int] = []
    coordinates: list[float] = []

    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()

    start_index = None
    for index, line in enumerate(lines):
        if "Standard orientation:" in line:
            start_index = index

    if start_index is None:
        raise ValueError(f"Nessun blocco 'Standard orientation' trovato in {log_path}")

    for line in lines[start_index + 5 :]:
        if DASH_RE.match(line):
            break
        parts = line.split()
        if len(parts) < 6:
            continue
        atomic_numbers.append(int(parts[1]))
        coordinates.extend(float(value) for value in parts[3:6])

    if not atomic_numbers:
        raise ValueError(f"Blocco 'Standard orientation' vuoto in {log_path}")

    return atomic_numbers, coordinates


def classify_file(path: Path) -> tuple[str, str]:
    lower_name = path.stem.lower()

    method = "none"
    if "vem" in lower_name:
        method = "vem"
    elif "_lr" in lower_name or lower_name.startswith("lr_") or "lr_" in lower_name:
        method = "lr"

    solvent = "unknown"
    for label, patterns in SOLVENT_PATTERNS:
        if any(pattern in lower_name for pattern in patterns):
            solvent = label
            break

    return method, solvent


def molecule_label(path: Path) -> str:
    stem = path.stem
    tokens = stem.split("_")
    return tokens[0].lower() if tokens else stem.lower()


def stem_label(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", path.stem)


def classify_pair_key(path: Path) -> tuple[str, str, str]:
    method, solvent = classify_file(path)
    return molecule_label(path), method, solvent


def detect_solvent_from_text(text: str) -> str:
    lower_text = text.lower()
    compact_text = re.sub(r"\s+", "", lower_text)

    match = re.search(r"solvent=([a-z]+)", compact_text)
    if not match:
        return "vacuum"

    solvent_token = match.group(1)
    if solvent_token.startswith("dichloromethane") or solvent_token.startswith("dcm"):
        return "dcm"
    if solvent_token.startswith("methanol") or solvent_token.startswith("meth"):
        return "meth"
    if solvent_token.startswith("cyclohexane") or solvent_token.startswith("cyc"):
        return "cyc"
    if solvent_token.startswith("water"):
        return "water"
    return "vacuum"


def detect_solvent_from_log(log_path: Path) -> str:
    return detect_solvent_from_text(log_path.read_text(encoding="utf-8", errors="replace"))


def detect_solvent_from_fchk(fchk_path: Path) -> str:
    return detect_solvent_from_text(fchk_path.read_text(encoding="utf-8", errors="replace"))


def split_modes(flat_modes: list[float], n_atoms: int, n_modes: int) -> list[list[float]]:
    coords_per_mode = 3 * n_atoms
    expected = coords_per_mode * n_modes
    if len(flat_modes) < expected:
        raise ValueError("Array Vib-Modes troppo corto per il numero di atomi e modi")
    return [flat_modes[offset : offset + coords_per_mode] for offset in range(0, expected, coords_per_mode)]


def extract_frequencies_and_reduced_masses(vib_e2: list[float], n_modes: int) -> tuple[list[float], list[float]]:
    if len(vib_e2) < 2 * n_modes:
        raise ValueError("Array Vib-E2 troppo corto per contenere frequenze e masse ridotte")
    frequencies = vib_e2[:n_modes]
    reduced_masses = vib_e2[n_modes : 2 * n_modes]
    return frequencies, reduced_masses


def atom_symbol(atomic_number: int) -> str:
    return ELEMENTS.get(atomic_number, f"Z{atomic_number}")


def dot(vec_a: list[float], vec_b: list[float]) -> float:
    return sum(a * b for a, b in zip(vec_a, vec_b))


def norm(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values))


def repeat_masses_per_coordinate(masses: list[float]) -> list[float]:
    coord_masses: list[float] = []
    for mass in masses:
        coord_masses.extend([mass, mass, mass])
    return coord_masses


def mass_weighted_norm(values: list[float], coord_masses: list[float]) -> float:
    return math.sqrt(sum(value * value / mass for value, mass in zip(values, coord_masses)))


def gram_matrix(columns: list[list[float]]) -> list[list[float]]:
    return [[dot(column_i, column_j) for column_j in columns] for column_i in columns]


def build_l_columns(
    cartesian_modes: list[list[float]],
    reduced_masses: list[float],
    coord_masses: list[float],
) -> list[list[float]]:
    # Gaussian's Vib-Modes in the fchk are normalized Cartesian displacements c_i.
    # The orthonormal mass-weighted normal modes are L_i = M^{1/2} c_i / sqrt(mu_i).
    l_columns: list[list[float]] = []
    for mode, reduced_mass in zip(cartesian_modes, reduced_masses):
        sqrt_mu = math.sqrt(reduced_mass)
        l_columns.append(
            [
                math.sqrt(coord_mass) * component / sqrt_mu
                for coord_mass, component in zip(coord_masses, mode)
            ]
        )
    return l_columns


def build_atom_mode_matrix_q(
    nac_cart: list[float],
    l_columns: list[list[float]],
    coord_masses: list[float],
    n_atoms: int,
) -> list[list[float]]:
    matrix = [[0.0 for _ in range(len(l_columns))] for _ in range(n_atoms)]
    for mode_index, l_column in enumerate(l_columns):
        for atom_index in range(n_atoms):
            start = 3 * atom_index
            contribution = 0.0
            for offset in range(3):
                idx = start + offset
                contribution += l_column[idx] * nac_cart[idx] / math.sqrt(coord_masses[idx])
            matrix[atom_index][mode_index] = contribution
    return matrix


def max_deviation_from_identity(columns: list[list[float]]) -> float:
    max_deviation = 0.0
    for row_index, column_i in enumerate(columns):
        for col_index, column_j in enumerate(columns):
            value = dot(column_i, column_j)
            target = 1.0 if row_index == col_index else 0.0
            max_deviation = max(max_deviation, abs(value - target))
    return max_deviation


def max_deviation_from_mass_relation(
    cartesian_modes: list[list[float]],
    coord_masses: list[float],
    reduced_masses: list[float],
) -> float:
    max_deviation = 0.0
    for mode, reduced_mass in zip(cartesian_modes, reduced_masses):
        value = sum(component * component * mass for component, mass in zip(mode, coord_masses))
        max_deviation = max(max_deviation, abs(value - reduced_mass))
    return max_deviation


def pairwise_distances(coords: list[float]) -> list[float]:
    distances: list[float] = []
    n_atoms = len(coords) // 3
    for i in range(n_atoms):
        xi, yi, zi = coords[3 * i : 3 * i + 3]
        for j in range(i + 1, n_atoms):
            xj, yj, zj = coords[3 * j : 3 * j + 3]
            dx = xi - xj
            dy = yi - yj
            dz = zi - zj
            distances.append(math.sqrt(dx * dx + dy * dy + dz * dz))
    return distances


def bohr_to_angstrom(coords_bohr: list[float]) -> list[float]:
    factor = 0.52917721092
    return [value * factor for value in coords_bohr]


def max_geometry_distance_deviation(fchk_coords_bohr: list[float], log_coords_ang: list[float]) -> float:
    fchk_distances = pairwise_distances(bohr_to_angstrom(fchk_coords_bohr))
    log_distances = pairwise_distances(log_coords_ang)
    return max(abs(distance_fchk - distance_log) for distance_fchk, distance_log in zip(fchk_distances, log_distances))


def transpose(matrix: list[list[float]]) -> list[list[float]]:
    if not matrix:
        return []
    return [list(column) for column in zip(*matrix)]


def format_float(value: float) -> str:
    return f"{value:.12f}"


def svg_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def interpolate_color(value: float, min_value: float, max_value: float) -> str:
    if max_value <= min_value:
        return "#f7f4ee"
    span = max(abs(min_value), abs(max_value))
    if span == 0.0:
        return "#f7f4ee"
    normalized = max(-1.0, min(1.0, value / span))
    if normalized >= 0.0:
        red = int(round(196 + (247 - 196) * (1.0 - normalized)))
        green = int(round(95 + (244 - 95) * (1.0 - normalized)))
        blue = int(round(88 + (238 - 88) * (1.0 - normalized)))
    else:
        normalized = abs(normalized)
        red = int(round(106 + (241 - 106) * (1.0 - normalized)))
        green = int(round(145 + (244 - 145) * (1.0 - normalized)))
        blue = int(round(173 + (238 - 173) * (1.0 - normalized)))
    return f"#{red:02x}{green:02x}{blue:02x}"


def write_mod_spectrum_svg(
    output_path: Path,
    frequencies: list[float],
    values: list[float],
    title: str,
    y_label: str,
) -> None:
    width = 1100
    height = 680
    left = 100
    right = 40
    top = 90
    bottom = 110
    plot_width = width - left - right
    plot_height = height - top - bottom
    min_freq = min(frequencies)
    max_freq = max(frequencies)
    max_value = max(values) if values else 1.0
    if max_value == 0.0:
        max_value = 1.0
    if max_freq == min_freq:
        max_freq = min_freq + 1.0

    peak_threshold = 0.12 * max_value
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<defs>",
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">',
        '<stop offset="0%" stop-color="#fcfbf7"/>',
        '<stop offset="100%" stop-color="#f5f1e8"/>',
        "</linearGradient>",
        '<filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">',
        '<feDropShadow dx="0" dy="6" stdDeviation="10" flood-color="#7c6f6420"/>',
        "</filter>",
        "</defs>",
        '<rect width="100%" height="100%" fill="url(#bg)"/>',
        f'<rect x="{left-18}" y="{top-18}" width="{plot_width+36}" height="{plot_height+36}" rx="22" fill="#fffdf8" stroke="#e7dece" stroke-width="1.5" filter="url(#shadow)"/>',
        f'<text x="{width/2:.1f}" y="44" text-anchor="middle" font-family="Avenir Next, Helvetica Neue, Helvetica, Arial, sans-serif" font-size="24" font-weight="600" fill="#2f3a45">{svg_escape(title)}</text>',
        f'<text x="{width/2:.1f}" y="68" text-anchor="middle" font-family="Avenir Next, Helvetica Neue, Helvetica, Arial, sans-serif" font-size="13" fill="#6b7280">Projected NAC intensity in the normal-mode basis</text>',
        f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" stroke="#4b5563" stroke-width="1.6"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#4b5563" stroke-width="1.6"/>',
    ]

    for tick in range(6):
        y_value = max_value * tick / 5.0
        y = top + plot_height - plot_height * tick / 5.0
        lines.append(f'<line x1="{left-8}" y1="{y:.2f}" x2="{left}" y2="{y:.2f}" stroke="#4b5563" stroke-width="1"/>')
        lines.append(f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_width}" y2="{y:.2f}" stroke="#e8e1d5" stroke-width="1"/>')
        lines.append(
            f'<text x="{left-14}" y="{y+4:.2f}" text-anchor="end" font-family="Avenir Next, Helvetica Neue, Helvetica, Arial, sans-serif" font-size="12" fill="#4b5563">{y_value:.3g}</text>'
        )

    for tick in range(6):
        freq = min_freq + (max_freq - min_freq) * tick / 5.0
        x = left + plot_width * tick / 5.0
        lines.append(f'<line x1="{x:.2f}" y1="{top + plot_height}" x2="{x:.2f}" y2="{top + plot_height + 8}" stroke="#4b5563" stroke-width="1"/>')
        lines.append(
            f'<text x="{x:.2f}" y="{top + plot_height + 28}" text-anchor="middle" font-family="Avenir Next, Helvetica Neue, Helvetica, Arial, sans-serif" font-size="12" fill="#4b5563">{freq:.0f}</text>'
        )

    lines.append(
        f'<text x="{width/2:.1f}" y="{height-28}" text-anchor="middle" font-family="Avenir Next, Helvetica Neue, Helvetica, Arial, sans-serif" font-size="16" fill="#2f3a45">Frequency (cm^-1)</text>'
    )
    lines.append(
        f'<text x="28" y="{height/2:.1f}" transform="rotate(-90 28 {height/2:.1f})" text-anchor="middle" font-family="Avenir Next, Helvetica Neue, Helvetica, Arial, sans-serif" font-size="16" fill="#2f3a45">{svg_escape(y_label)}</text>'
    )

    accent = "#d97757"
    accent_soft = "#f0c7b1"
    for index, (freq, value) in enumerate(zip(frequencies, values), start=1):
        x = left + (freq - min_freq) / (max_freq - min_freq) * plot_width
        y = top + plot_height - value / max_value * plot_height
        lines.append(f'<line x1="{x:.2f}" y1="{top + plot_height}" x2="{x:.2f}" y2="{y:.2f}" stroke="{accent_soft}" stroke-width="5" stroke-linecap="round"/>')
        lines.append(f'<line x1="{x:.2f}" y1="{top + plot_height}" x2="{x:.2f}" y2="{y:.2f}" stroke="{accent}" stroke-width="2.2" stroke-linecap="round"/>')
        lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="6.6" fill="#fffaf5" stroke="{accent}" stroke-width="2.2"/>')
        lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2.2" fill="{accent}"/>')
        lines.append(
            f'<text x="{x:.2f}" y="{top + plot_height + 48:.2f}" text-anchor="middle" font-family="Avenir Next, Helvetica Neue, Helvetica, Arial, sans-serif" font-size="11" fill="#6b7280">m{index}</text>'
        )
        if value >= peak_threshold:
            lines.append(
                f'<text x="{x:.2f}" y="{y - 14:.2f}" text-anchor="middle" font-family="Avenir Next, Helvetica Neue, Helvetica, Arial, sans-serif" font-size="11.5" font-weight="600" fill="#8b5e4b">{value:.2e}</text>'
            )

    lines.append("</svg>")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def write_heatmap_svg(
    output_path: Path,
    matrix: list[list[float]],
    row_labels: list[str],
    frequencies: list[float],
    title: str,
) -> None:
    n_rows = len(matrix)
    n_cols = len(matrix[0]) if matrix else 0
    cell_w = 104
    cell_h = 48
    left = 170
    top = 150
    width = left + max(n_cols * cell_w, 1) + 90
    height = top + max(n_rows * cell_h, 1) + 140
    values = [value for row in matrix for value in row]
    min_value = min(values) if values else -1.0
    max_value = max(values) if values else 1.0

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<defs>",
        '<linearGradient id="heatbg" x1="0" y1="0" x2="1" y2="1">',
        '<stop offset="0%" stop-color="#fdfbf7"/>',
        '<stop offset="100%" stop-color="#f3efe7"/>',
        "</linearGradient>",
        '<filter id="panelshadow" x="-20%" y="-20%" width="140%" height="140%">',
        '<feDropShadow dx="0" dy="6" stdDeviation="10" flood-color="#7c6f6420"/>',
        "</filter>",
        "</defs>",
        '<rect width="100%" height="100%" fill="url(#heatbg)"/>',
        f'<rect x="{left-20}" y="{top-48}" width="{max(n_cols * cell_w, 1)+40}" height="{max(n_rows * cell_h, 1)+92}" rx="22" fill="#fffdf8" stroke="#e7dece" stroke-width="1.5" filter="url(#panelshadow)"/>',
        f'<text x="{width/2:.1f}" y="40" text-anchor="middle" font-family="Avenir Next, Helvetica Neue, Helvetica, Arial, sans-serif" font-size="24" font-weight="600" fill="#2f3a45">{svg_escape(title)}</text>',
        f'<text x="{width/2:.1f}" y="68" text-anchor="middle" font-family="Avenir Next, Helvetica Neue, Helvetica, Arial, sans-serif" font-size="13" fill="#6b7280">Signed atom-resolved NAC contributions in the normal-mode basis</text>',
    ]

    for col_index, frequency in enumerate(frequencies):
        x = left + col_index * cell_w + cell_w / 2
        lines.append(
            f'<text x="{x:.2f}" y="{top - 36}" text-anchor="middle" font-family="Avenir Next, Helvetica Neue, Helvetica, Arial, sans-serif" font-size="12.5" font-weight="600" fill="#2f3a45">m{col_index + 1}</text>'
        )
        lines.append(
            f'<text x="{x:.2f}" y="{top - 14}" text-anchor="middle" font-family="Avenir Next, Helvetica Neue, Helvetica, Arial, sans-serif" font-size="11.5" fill="#6b7280">{frequency:.0f}</text>'
        )

    for row_index, (row_label, row_values) in enumerate(zip(row_labels, matrix)):
        y = top + row_index * cell_h
        lines.append(
            f'<text x="{left - 16}" y="{y + cell_h/2 + 5:.2f}" text-anchor="end" font-family="Avenir Next, Helvetica Neue, Helvetica, Arial, sans-serif" font-size="13" font-weight="600" fill="#374151">{svg_escape(row_label)}</text>'
        )
        for col_index, value in enumerate(row_values):
            x = left + col_index * cell_w
            fill = interpolate_color(value, min_value, max_value)
            lines.append(f'<rect x="{x}" y="{y}" width="{cell_w}" height="{cell_h}" rx="10" fill="{fill}" stroke="#fffaf4" stroke-width="1.5"/>')
            lines.append(
                f'<text x="{x + cell_w/2:.2f}" y="{y + cell_h/2 + 4:.2f}" text-anchor="middle" font-family="Avenir Next, Helvetica Neue, Helvetica, Arial, sans-serif" font-size="11.5" fill="#24303d">{value:.2e}</text>'
            )

    legend_x = left
    legend_y = top + n_rows * cell_h + 46
    legend_w = min(360, n_cols * cell_w)
    steps = 64
    for step in range(steps):
        value = min_value + (max_value - min_value) * step / max(steps - 1, 1)
        x = legend_x + legend_w * step / steps
        lines.append(
            f'<rect x="{x:.2f}" y="{legend_y}" width="{legend_w/steps + 1:.2f}" height="16" fill="{interpolate_color(value, min_value, max_value)}" stroke="none"/>'
        )
    lines.append(f'<rect x="{legend_x}" y="{legend_y}" width="{legend_w}" height="16" rx="8" fill="none" stroke="#6b7280" stroke-width="1"/>')
    lines.append(
        f'<text x="{legend_x + legend_w/2:.2f}" y="{legend_y - 10}" text-anchor="middle" font-family="Avenir Next, Helvetica Neue, Helvetica, Arial, sans-serif" font-size="12" fill="#6b7280">Negative contribution          Positive contribution</text>'
    )
    lines.append(
        f'<text x="{legend_x}" y="{legend_y + 36}" text-anchor="start" font-family="Avenir Next, Helvetica Neue, Helvetica, Arial, sans-serif" font-size="12" fill="#4b5563">{min_value:.2e}</text>'
    )
    lines.append(
        f'<text x="{legend_x + legend_w/2:.2f}" y="{legend_y + 36}" text-anchor="middle" font-family="Avenir Next, Helvetica Neue, Helvetica, Arial, sans-serif" font-size="12" fill="#4b5563">0</text>'
    )
    lines.append(
        f'<text x="{legend_x + legend_w:.2f}" y="{legend_y + 36}" text-anchor="end" font-family="Avenir Next, Helvetica Neue, Helvetica, Arial, sans-serif" font-size="12" fill="#4b5563">{max_value:.2e}</text>'
    )
    lines.append("</svg>")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def setup_matplotlib_style() -> tuple[object, object]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns

    sns.set_theme(
        context="paper",
        style="whitegrid",
        font="DejaVu Sans",
        rc={
            "axes.facecolor": "#fbf8f2",
            "figure.facecolor": "#f6f1e8",
            "grid.color": "#ddd3c5",
            "axes.edgecolor": "#6b655f",
            "axes.labelcolor": "#2e3440",
            "xtick.color": "#4b5563",
            "ytick.color": "#4b5563",
            "axes.titleweight": "semibold",
            "axes.titlesize": 14,
            "axes.labelsize": 11,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
        },
    )
    return plt, sns


def save_figure(fig, base_path: Path) -> tuple[Path, Path]:
    png_path = base_path.with_suffix(".png")
    pdf_path = base_path.with_suffix(".pdf")
    fig.savefig(png_path, dpi=320, bbox_inches="tight", facecolor=fig.get_facecolor())
    fig.savefig(pdf_path, bbox_inches="tight", facecolor=fig.get_facecolor())
    return png_path, pdf_path


def write_mod_spectrum_plot(
    base_path: Path,
    frequencies: list[float],
    values: list[float],
    title: str,
    y_label: str,
    fill_color: str,
    line_color: str,
) -> tuple[Path, Path]:
    plt, _ = setup_matplotlib_style()

    fig, ax = plt.subplots(figsize=(8.8, 5.4))
    fig.patch.set_facecolor("#f6f1e8")
    ax.set_facecolor("#fbf8f2")

    markerline, stemlines, baseline = ax.stem(frequencies, values, basefmt=" ")
    plt.setp(stemlines, color=line_color, linewidth=2.1, alpha=0.95)
    plt.setp(markerline, marker="o", markersize=7.5, markeredgewidth=1.8, markeredgecolor=line_color, markerfacecolor=fill_color)

    for freq, value in zip(frequencies, values):
        ax.scatter(freq, value, s=88, color=fill_color, edgecolor=line_color, linewidth=1.2, zorder=3)

    if values:
        cutoff = 0.12 * max(values)
        for index, (freq, value) in enumerate(zip(frequencies, values), start=1):
            if value >= cutoff:
                ax.annotate(
                    f"m{index}\n{value:.2e}",
                    xy=(freq, value),
                    xytext=(0, 10),
                    textcoords="offset points",
                    ha="center",
                    va="bottom",
                    fontsize=8.5,
                    color="#7a4d3b",
                    bbox={"boxstyle": "round,pad=0.22", "fc": "#fff8f2", "ec": "#e7c7b6", "lw": 0.8},
                )

    ax.set_title(title, pad=14, color="#2e3440")
    ax.set_xlabel("Frequency (cm$^{-1}$)")
    ax.set_ylabel(y_label)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", linestyle="-", linewidth=0.8, alpha=0.65)
    ax.grid(axis="x", visible=False)

    return_paths = save_figure(fig, base_path)
    plt.close(fig)
    return return_paths


def write_heatmap_plot(
    base_path: Path,
    matrix: list[list[float]],
    row_labels: list[str],
    mode_labels: list[str],
    title: str,
) -> tuple[Path, Path]:
    plt, sns = setup_matplotlib_style()
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap

    data = np.array(matrix, dtype=float)
    vmax = float(np.max(np.abs(data))) if data.size else 1.0
    if vmax == 0.0:
        vmax = 1.0
    cmap = LinearSegmentedColormap.from_list(
        "nac_pastel_div",
        ["#6e95b1", "#dbe6ef", "#faf7f2", "#f3d4c6", "#cd7c64"],
        N=256,
    )

    fig_w = max(7.4, 1.25 * len(mode_labels) + 3.5)
    fig_h = max(3.8, 0.72 * len(row_labels) + 2.8)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor("#f6f1e8")
    ax.set_facecolor("#fbf8f2")

    sns.heatmap(
        data,
        ax=ax,
        cmap=cmap,
        center=0.0,
        vmin=-vmax,
        vmax=vmax,
        linewidths=1.2,
        linecolor="#fffaf3",
        annot=True,
        fmt=".2e",
        annot_kws={"fontsize": 8.5, "color": "#24303d"},
        cbar_kws={"shrink": 0.82, "pad": 0.03, "label": "M[a,m]"},
        xticklabels=mode_labels,
        yticklabels=row_labels,
    )

    ax.set_title(title, pad=14, color="#2e3440")
    ax.set_xlabel("Normal modes")
    ax.set_ylabel("Atoms")
    ax.tick_params(axis="x", rotation=0)
    ax.tick_params(axis="y", rotation=0)

    return_paths = save_figure(fig, base_path)
    plt.close(fig)
    return return_paths


def print_report(
    fchk_path: Path,
    log_path: Path,
    atomic_numbers: list[int],
    frequencies: list[float],
    reduced_masses: list[float],
    nac_cart: list[float],
    coord_masses: list[float],
    cartesian_modes: list[list[float]],
    l_columns: list[list[float]],
    atom_mode_matrix_q: list[list[float]],
    geometry_distance_deviation: float | None,
    plot_dir: Path,
) -> None:
    mode_columns = transpose(atom_mode_matrix_q)
    sum_atom_nac_q = [sum(column) for column in mode_columns]
    abs_nac_q = [norm(column) for column in mode_columns]
    abs_nac_q_sq = [value * value for value in abs_nac_q]
    total_mode_norm_q = norm(sum_atom_nac_q)
    matrix_frobenius_norm_q = math.sqrt(sum(value * value for row in atom_mode_matrix_q for value in row))
    cart_norm = norm(nac_cart)
    cart_massweighted_norm = mass_weighted_norm(nac_cart, coord_masses)
    residual_nonvib_sq = max(cart_massweighted_norm * cart_massweighted_norm - total_mode_norm_q * total_mode_norm_q, 0.0)
    residual_nonvib_norm = math.sqrt(residual_nonvib_sq)
    ctci_deviation = max_deviation_from_identity(cartesian_modes)
    ctmci_mu_deviation = max_deviation_from_mass_relation(cartesian_modes, coord_masses, reduced_masses)
    ltli_deviation = max_deviation_from_identity(l_columns)
    method, solvent = classify_file(fchk_path)
    molecule = molecule_label(fchk_path).upper()
    prefix = f"{stem_label(fchk_path)}__{stem_label(log_path)}"
    row_labels = [f"{atom_index}:{atom_symbol(atomic_number)}" for atom_index, atomic_number in enumerate(atomic_numbers, start=1)]
    mode_labels = [f"m{idx + 1}\n{freq:.0f}" for idx, freq in enumerate(frequencies)]
    ranked_modes = sorted(
        [
            (mode_index, frequency, reduced_mass, summed_q, abs_q, abs_q_sq)
            for mode_index, (frequency, reduced_mass, summed_q, abs_q, abs_q_sq) in enumerate(
                zip(frequencies, reduced_masses, sum_atom_nac_q, abs_nac_q, abs_nac_q_sq),
                start=1,
            )
        ],
        key=lambda item: item[5],
        reverse=True,
    )
    top_modes_count = min(5, len(ranked_modes))
    summed_abs_sq = sum(abs_nac_q_sq)

    spectrum_abs_png, spectrum_abs_pdf = write_mod_spectrum_plot(
        plot_dir / f"{prefix}_spectrum_abs_nac_q",
        frequencies,
        abs_nac_q,
        f"{molecule} projected NAC spectrum ({method.upper()} {solvent})",
        "abs_NAC_Q(m)",
        "#f3c8b5",
        "#c46f52",
    )
    spectrum_sq_png, spectrum_sq_pdf = write_mod_spectrum_plot(
        plot_dir / f"{prefix}_spectrum_abs_nac_q_sq",
        frequencies,
        abs_nac_q_sq,
        f"{molecule} projected NAC intensity ({method.upper()} {solvent})",
        "|d_Q(m)|^2",
        "#c9d9e8",
        "#6a8eab",
    )
    heatmap_png, heatmap_pdf = write_heatmap_plot(
        plot_dir / f"{prefix}_heatmap_atom_mode",
        atom_mode_matrix_q,
        row_labels,
        mode_labels,
        f"{molecule} atom-mode NAC map ({method.upper()} {solvent})",
    )

    print(f"Pair: metodo={method.upper()} solvente={solvent}")
    print("  risultati_chiave:")
    print(f"    atomi={len(atomic_numbers)}  modi={len(frequencies)}")
    print(f"    norma_cartesiana={format_float(cart_norm)}")
    print(f"    norma_cartesiana_massweighted={format_float(cart_massweighted_norm)}")
    print(f"    norma_totale_modi_Q={format_float(total_mode_norm_q)}")
    print(f"    residuo_nonvib_massweighted={format_float(residual_nonvib_norm)}")
    print(f"    norma_frobenius_matrice_Q={format_float(matrix_frobenius_norm_q)}")
    print(f"    max_dev_CtC_I={ctci_deviation:.12e}")
    print(f"    max_dev_CtMC_mu={ctmci_mu_deviation:.12e}")
    print(f"    max_dev_LtL_I={ltli_deviation:.12e}")
    if geometry_distance_deviation is not None:
        print(f"    max_dev_geom_fchk_log_ang={geometry_distance_deviation:.12e}")

    print(f"  top_{top_modes_count}_modi_dominanti (ordinati per |NAC_Q|^2):")
    print("    rank  mode      freq_cm-1        mu_amu        abs_NAC_Q       |NAC_Q|^2     contrib_%")
    cumulative_pct = 0.0
    for rank, (mode_index, frequency, reduced_mass, _summed_q, abs_q, abs_q_sq) in enumerate(
        ranked_modes[:top_modes_count],
        start=1,
    ):
        contribution_pct = (100.0 * abs_q_sq / summed_abs_sq) if summed_abs_sq > 0.0 else 0.0
        cumulative_pct += contribution_pct
        print(
            "    "
            f"{rank:>4d}"
            f"{mode_index:>6d}"
            f"{frequency:>15.4f}"
            f"{reduced_mass:>14.6f}"
            f"{abs_q:>16.12f}"
            f"{abs_q_sq:>16.12f}"
            f"{contribution_pct:>12.3f}"
        )
    print(f"    copertura_top_{top_modes_count}_percent={cumulative_pct:.3f}")

    print(f"  fchk={fchk_path}")
    print(f"  log ={log_path}")
    print(f"  plot_spectrum_abs_png={spectrum_abs_png}")
    print(f"  plot_spectrum_abs_pdf={spectrum_abs_pdf}")
    print(f"  plot_spectrum_sq_png={spectrum_sq_png}")
    print(f"  plot_spectrum_sq_pdf={spectrum_sq_pdf}")
    print(f"  plot_heatmap_png={heatmap_png}")
    print(f"  plot_heatmap_pdf={heatmap_pdf}")

    header = ["atom"] + [f"m{mode_index + 1}" for mode_index in range(len(frequencies))]
    print("  riepilogo modi completo:")
    print("    mode      freq_cm-1        mu_amu   sum_atom_NAC_Q         abs_NAC_Q")
    for mode_index, (frequency, reduced_mass, summed_q, abs_q) in enumerate(
        zip(frequencies, reduced_masses, sum_atom_nac_q, abs_nac_q),
        start=1,
    ):
        print(
            "    "
            f"{mode_index:>4d}"
            f"{frequency:>15.4f}"
            f"{reduced_mass:>15.6f}"
            f"{summed_q:>17.12f}"
            f"{abs_q:>17.12f}"
        )

    print("  matrice NAC_Q atomica (righe = atomi, colonne = modi):")
    print("    " + "".join(f"{label:>18s}" for label in header))
    for atom_index, row in enumerate(atom_mode_matrix_q, start=1):
        label = f"{atom_index}:{atom_symbol(atomic_numbers[atom_index - 1])}"
        print("    " + f"{label:>18s}" + "".join(f"{value:>18.12f}" for value in row))
    print()


def warn_missing_pairs(fchk_files: list[Path], log_files: list[Path]) -> None:
    fchk_keys = {classify_pair_key(path) for path in fchk_files}
    log_keys = {classify_pair_key(path) for path in log_files if "freq" not in path.name.lower()}
    missing_fchk_keys = sorted(key for key in log_keys if key not in fchk_keys and key[1] != "unknown")
    for molecule, method, solvent in missing_fchk_keys:
        print(
            f"Nessun .fchk trovato per molecola={molecule} metodo={method.upper()} solvente={solvent}; quel NAC log non puo' essere trasformato.",
            file=sys.stderr,
        )


def warn_ambiguous_pairs(logs_by_key: dict[tuple[str, str, str], list[Path]]) -> None:
    for key, candidates in sorted(logs_by_key.items()):
        if len(candidates) > 1:
            molecule, method, solvent = key
            names = ", ".join(path.name for path in sorted(candidates))
            print(
                f"Più log NAC candidati per molecola={molecule} metodo={method.upper()} solvente={solvent}: {names}",
                file=sys.stderr,
            )


def validate_solvent_consistency(path: Path, kind: str) -> tuple[str, str]:
    name_method, name_solvent = classify_file(path)
    content_solvent = detect_solvent_from_fchk(path) if kind == "fchk" else detect_solvent_from_log(path)
    if name_solvent != "unknown" and content_solvent != name_solvent:
        raise ValueError(
            f"Solvente incoerente nel {kind}: nome file={name_solvent}, contenuto={content_solvent} ({path}). "
            f"Passa esplicitamente --fchk e --log dopo aver verificato i file."
        )
    return name_method, content_solvent if name_solvent == "unknown" else name_solvent


def resolve_pairs(
    args: argparse.Namespace,
    fchk_files: list[Path],
    log_files: list[Path],
) -> list[tuple[Path, Path]]:
    if args.fchk or args.log:
        if not (args.fchk and args.log):
            raise ValueError("Devi specificare sia --fchk sia --log per un pairing manuale.")
        return [(Path(args.fchk).expanduser(), Path(args.log).expanduser())]

    logs_by_key: dict[tuple[str, str, str], list[Path]] = {}
    for log_path in log_files:
        if "freq" in log_path.name.lower():
            continue
        logs_by_key.setdefault(classify_pair_key(log_path), []).append(log_path)

    warn_missing_pairs(fchk_files, log_files)

    pairs: list[tuple[Path, Path]] = []
    ambiguous = False
    for fchk_path in fchk_files:
        key = classify_pair_key(fchk_path)
        candidates = logs_by_key.get(key, [])
        if not candidates:
            molecule, method, solvent = key
            print(
                f"Nessun log NAC corrispondente per molecola={molecule} metodo={method.upper()} solvente={solvent} ({fchk_path})",
                file=sys.stderr,
            )
            continue
        if len(candidates) > 1:
            ambiguous = True
            molecule, method, solvent = key
            names = ", ".join(path.name for path in sorted(candidates))
            print(
                f"Pairing ambiguo per molecola={molecule} metodo={method.upper()} solvente={solvent}: {names}. "
                f"Rilancia con --fchk <file> --log <file>.",
                file=sys.stderr,
            )
            continue
        pairs.append((fchk_path, candidates[0]))

    if ambiguous and not pairs:
        raise ValueError("Pairing automatico ambiguo. Specifica esplicitamente --fchk e --log.")

    return pairs


def main() -> int:
    args = parse_args()

    if not args.paths and not (args.fchk and args.log):
        print("Specifica almeno una cartella/file oppure la coppia --fchk/--log.", file=sys.stderr)
        return 1

    try:
        fchk_files = iter_fchk_files(args.paths)
        log_files = iter_log_files(args.paths)
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    if not fchk_files:
        if not (args.fchk and args.log):
            print("Nessun file .fchk trovato.", file=sys.stderr)
            return 1

    success_count = 0
    plot_dir = Path(args.plot_dir).expanduser() if args.plot_dir else Path(__file__).resolve().parent / "nac_plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    try:
        pairs = resolve_pairs(args, fchk_files, log_files)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    for fchk_path, log_path in pairs:
        if not fchk_path.exists():
            print(f"File .fchk non trovato: {fchk_path}", file=sys.stderr)
            continue
        if not log_path.exists():
            print(f"File .log non trovato: {log_path}", file=sys.stderr)
            continue

        try:
            fchk_method, fchk_solvent = validate_solvent_consistency(fchk_path, "fchk")
            log_method, log_solvent = validate_solvent_consistency(log_path, "log")
            data = parse_fchk(fchk_path)
            n_atoms = int(data["n_atoms"])
            n_modes = int(data["n_modes"])
            atomic_numbers = list(data["atomic_numbers"])
            vib_at_mass = list(data["vib_at_mass"])
            current_cartesian_coordinates = list(data["current_cartesian_coordinates"])
            frequencies, reduced_masses = extract_frequencies_and_reduced_masses(list(data["vib_e2"]), n_modes)
            cartesian_modes = split_modes(list(data["vib_modes"]), n_atoms, n_modes)
            nac_cart = parse_last_nac_block_from_log(log_path)
            log_atomic_numbers, log_coordinates = parse_last_standard_orientation_from_log(log_path)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            continue

        if molecule_label(fchk_path) != molecule_label(log_path):
            print(
                f"Molecola incoerente tra fchk e log: {fchk_path.name} vs {log_path.name}. "
                f"Passa esplicitamente la coppia corretta con --fchk e --log.",
                file=sys.stderr,
            )
            continue
#        if fchk_method != log_method:
#            print(
#                f"Metodo incoerente tra fchk e log: {fchk_method} vs {log_method} ({fchk_path.name}, {log_path.name}). "
#                f"Passa esplicitamente la coppia corretta con --fchk e --log.",
#                file=sys.stderr,
#            )
#            continue
        if fchk_solvent != log_solvent:
            print(
                f"Solvente incoerente tra fchk e log: {fchk_solvent} vs {log_solvent} ({fchk_path.name}, {log_path.name}). "
                f"Passa esplicitamente la coppia corretta con --fchk e --log.",
                file=sys.stderr,
            )
            continue

        if len(nac_cart) != 3 * n_atoms:
            print(f"Lunghezza NAC incompatibile con il numero di atomi in {log_path}", file=sys.stderr)
            continue
        if atomic_numbers != log_atomic_numbers:
            print(f"Numeri atomici diversi tra {fchk_path} e {log_path}", file=sys.stderr)
            continue

        coord_masses = repeat_masses_per_coordinate(vib_at_mass)
        l_columns = build_l_columns(cartesian_modes, reduced_masses, coord_masses)
        atom_mode_matrix_q = build_atom_mode_matrix_q(nac_cart, l_columns, coord_masses, n_atoms)
        geometry_distance_deviation = max_geometry_distance_deviation(current_cartesian_coordinates, log_coordinates)
        print_report(
            fchk_path,
            log_path,
            atomic_numbers,
            frequencies,
            reduced_masses,
            nac_cart,
            coord_masses,
            cartesian_modes,
            l_columns,
            atom_mode_matrix_q,
            geometry_distance_deviation,
            plot_dir,
        )
        success_count += 1

    return 0 if success_count else 1


if __name__ == "__main__":
    raise SystemExit(main())
