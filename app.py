import os
import tempfile
import traceback

from flask import Flask, request, jsonify, send_from_directory

from src import ConstAndScales
from src.Material import Material
from src.Composition import Composition
from src.Grid import Grid
from src.Solvers_FDM import Parabolic_FDM, Kane_FDM, Taylor_FDM
from src.Solvers_TMM import Parabolic_TMM, Taylor_TMM, Kane_TMM, Ekenberg_TMM
from src.AbsorptionCalculator import AbsorptionCalculator

app = Flask(__name__, static_folder='static', static_url_path='')


# ── Helpers ───────────────────────────────────────────────────────────────────

def select_solver(solver_method, subband_model, grid, num_states):
    if solver_method == "FDM":
        if subband_model == "parabolic": return Parabolic_FDM(grid, num_states)
        if subband_model == "kane":      return Kane_FDM(grid, num_states)
        if subband_model == "taylor":    return Taylor_FDM(grid, num_states)
    elif solver_method == "TMM":
        if subband_model == "parabolic": return Parabolic_TMM(grid, num_states)
        if subband_model == "kane":      return Kane_TMM(grid, num_states)
        if subband_model == "taylor":    return Taylor_TMM(grid, num_states)
        if subband_model == "14kp":      return Ekenberg_TMM(grid, num_states)
    return None


def build_grid_and_solve(params):
    """Shared setup: parse params → Grid → solver → (energies, wavefunctions, grid)."""
    material_system = params.get('material')
    solver_method   = params.get('solver')
    subband_model   = params.get('subband_model')
    raw_layers      = params.get('layer_structure', '')
    electric_field  = float(params.get('electric_field', 0.0))
    grid_spacing    = float(params.get('grid_spacing', 1.0))
    num_states      = int(params.get('num_states', 4))

    if not material_system or not solver_method or not subband_model:
        raise ValueError("Missing required parameters: material, solver, or subband_model.")

    tokens = raw_layers.strip().split()
    if len(tokens) % 2 != 0:
        raise ValueError("layer_structure must be pairs of Width (Å) and Molar fraction.")

    layer_profile = [[float(tokens[i]), float(tokens[i + 1])]
                     for i in range(0, len(tokens), 2)]

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        for width, molar in layer_profile:
            f.write(f"{width} {molar}\n")
        layer_file = f.name

    try:
        composition = Composition.from_file(layer_file)
        grid        = Grid(composition, grid_spacing, material_system)
        grid.set_K(electric_field)

        solver = select_solver(solver_method, subband_model, grid, num_states)
        if solver is None:
            raise ValueError(f"Invalid combination: {solver_method} + {subband_model}")

        energies, wavefunctions = solver.get_wavefunctions()
    finally:
        if os.path.exists(layer_file):
            os.unlink(layer_file)

    return grid, energies, wavefunctions, material_system, solver_method, subband_model, num_states


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def home():
    return send_from_directory('static', 'index.html')


@app.route('/api/simulate', methods=['POST'])
def simulate():
    try:
        params = request.json
        grid, energies, wavefunctions, material_system, solver_method, subband_model, num_states = \
            build_grid_and_solve(params)

        energies_eV = energies / ConstAndScales.E
        energies_list = energies_eV.tolist() if hasattr(energies_eV, 'tolist') else list(energies_eV)

        wavefunctions_list = []
        for wf in wavefunctions:
            wavefunctions_list.append(wf.tolist() if hasattr(wf, 'tolist') else list(wf))

        z_points = (grid.get_z() / ConstAndScales.ANGSTROM).tolist()
        potential = (grid.get_bandstructure_potential() / ConstAndScales.E).tolist()

        return jsonify({
            "status": "success",
            "message": f"Successfully completed {solver_method} calculation ({subband_model} model)",
            "results": {
                "energies":      energies_list[:num_states],
                "wavefunctions": wavefunctions_list[:num_states],
                "z_grid":        z_points,
                "potential":     potential,
                "field_applied": float(params.get('electric_field', 0.0)),
                "material":      material_system,
                "solver_method": solver_method,
                "subband_model": subband_model,
            }
        })

    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Execution error: {str(e)}"}), 500


@app.route('/api/absorption', methods=['POST'])
def absorption():
    try:
        params = request.json
        grid, energies, wavefunctions, material_system, _, _, _ = \
            build_grid_and_solve(params)

        # Parse populations: JSON keys are strings → int
        pop_raw     = params.get('populations', {})
        populations = {int(k): float(v) for k, v in pop_raw.items()}

        # Parse linewidths: keys "i,j" → (int, int)
        lw_raw     = params.get('linewidths', {})
        linewidths = {}
        for k, v in lw_raw.items():
            parts = k.split(',')
            if len(parts) == 2:
                linewidths[(int(parts[0]), int(parts[1]))] = float(v)

        energy_range = params.get('energy_range_meV')
        if energy_range is not None:
            energy_range = tuple(energy_range)
        n_points = int(params.get('n_points', 2000))

        material = Material(material_system)
        calc     = AbsorptionCalculator(grid, energies, wavefunctions, material)

        hw_meV, alpha_cm = calc.get_spectrum(
            populations, linewidths,
            energy_range_meV=energy_range,
            n_points=n_points,
        )

        _, records = calc.get_transition_table(populations, linewidths)

        def _safe(v):
            if v is None: return None
            return v.item() if hasattr(v, 'item') else v

        transitions_out = [{
            "pair":           list(r["pair"]),
            "E_ij_meV":       _safe(r["E_ij_meV"]),
            "f_ij":           _safe(r["f_ij"]),
            "d_ij_nm":        _safe(r["d_ij_nm"]),
            "gamma_meV":      _safe(r["gamma_meV"]),
            "dN_m2":          _safe(r["dN_m2"]),
            "peak_alpha_cm":  _safe(r["peak_alpha_cm"]),
        } for r in records]

        return jsonify({
            "status": "success",
            "spectrum": {
                "hbar_omega_meV": hw_meV.tolist(),
                "alpha_cm":       alpha_cm.tolist(),
            },
            "transitions": transitions_out,
        })

    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Absorption error: {str(e)}"}), 500


@app.route('/api/material-info', methods=['GET'])
def material_info():
    material_name = request.args.get('material')
    if not material_name:
        return jsonify({"status": "error", "message": "Material name required"}), 400
    try:
        m = Material(material_name)
        return jsonify({
            "status":   "success",
            "material": material_name,
            "band_gap":        {"well": m.Eg.well, "barrier": m.Eg.barr},
            "effective_mass":  {"well": m.m.well,  "barrier": m.m.barr},
            "kane_parameter":  {"well": m.P.well,  "barrier": m.P.barr},
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error: {str(e)}"}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)