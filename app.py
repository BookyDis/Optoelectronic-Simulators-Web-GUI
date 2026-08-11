import os, tempfile, traceback
import numpy as np
from flask import Flask, request, jsonify, send_from_directory

from src import ConstAndScales
from src.Material            import Material
from src.Composition         import Composition
from src.Grid                import Grid
from src.Solvers_FDM         import Parabolic_FDM, Kane_FDM, Taylor_FDM
from src.Solvers_TMM         import Parabolic_TMM, Taylor_TMM, Kane_TMM, Ekenberg_TMM
from src.TransitionCalculator import TransitionCalculator

app = Flask(__name__, static_folder='static', static_url_path='')

# ── Helpers ───────────────────────────────────────────────────────────────────

def select_solver(solver_method, subband_model, grid, num_states):
    mapping = {
        ("FDM","parabolic"): Parabolic_FDM, ("FDM","kane"): Kane_FDM,
        ("FDM","taylor"):    Taylor_FDM,
        ("TMM","parabolic"): Parabolic_TMM, ("TMM","kane"): Kane_TMM,
        ("TMM","taylor"):    Taylor_TMM,    ("TMM","14kp"): Ekenberg_TMM,
    }
    cls = mapping.get((solver_method, subband_model))
    return cls(grid, num_states) if cls else None

def build_grid_and_solve(params):
    material_system = params.get('material')
    solver_method   = params.get('solver')
    subband_model   = params.get('subband_model')
    raw_layers      = params.get('layer_structure', '')
    electric_field  = float(params.get('electric_field', 0.0))
    grid_spacing    = float(params.get('grid_spacing', 1.0))
    num_states      = int(params.get('num_states', 4))
    padding         = float(params.get('padding', 0.0))

    if not (material_system and solver_method and subband_model):
        raise ValueError("Missing required parameters: material, solver, or subband_model.")
    if padding < 0:
        raise ValueError("padding must be >= 0.")

    tokens = raw_layers.strip().split()
    if len(tokens) % 2 != 0:
        raise ValueError("layer_structure must be pairs of Width (Å) and Molar fraction.")
    layer_profile = [[float(tokens[i]), float(tokens[i+1])] for i in range(0, len(tokens), 2)]

    pad_each_side = padding / 2.0
    if pad_each_side > 0:
        layer_profile = (
            [[pad_each_side, layer_profile[0][1]]] +
            [list(l) for l in layer_profile] +
            [[pad_each_side, layer_profile[-1][1]]]
        )

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        for w, x in layer_profile:
            f.write(f"{w} {x}\n")
        tmp = f.name
    try:
        composition = Composition.from_file(tmp)
        grid        = Grid(composition, grid_spacing, material_system)
        grid.set_K(electric_field)
        solver = select_solver(solver_method, subband_model, grid, num_states)
        if solver is None:
            raise ValueError(f"Invalid combination: {solver_method} + {subband_model}")
        energies, wavefunctions = solver.get_wavefunctions()
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

    npad = int(padding / grid_spacing / 2) + 1 if padding > 0 else 0

    return grid, energies, wavefunctions, material_system, solver_method, subband_model, num_states, npad

def _lst(v): return v.tolist() if hasattr(v,'tolist') else list(v)
def _safe(v): return v.item() if hasattr(v,'item') else v

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def home(): return send_from_directory('static', 'index.html')

# ── /api/simulate ─────────────────────────────────────────────────────────────
@app.route('/api/simulate', methods=['POST'])
def simulate():
    try:
        params = request.json
        grid, energies, wfs, mat, solver, model, n, npad = build_grid_and_solve(params)

        z_out = grid.get_z() / ConstAndScales.ANGSTROM
        V_out = grid.get_bandstructure_potential() / ConstAndScales.E
        wfs_out = [np.asarray(wf) for wf in wfs[:n]]

        if npad > 0:
            
            z_out = z_out[npad:-npad] - z_out[npad]
            V_out = V_out[npad:-npad]
            wfs_out = [wf[npad:-npad] for wf in wfs_out]

        return jsonify({
            "status":  "success",
            "message": f"Completed {solver} ({model}) — {len(energies)} states found.",
            "results": {
                "energies":      [e/ConstAndScales.E for e in energies[:n]],
                "wavefunctions": [_lst(wf) for wf in wfs_out],
                "z_grid":        _lst(z_out),
                "potential":     _lst(V_out),
                "material": mat, "solver_method": solver, "subband_model": model,
            }
        })
    except ValueError as e: return jsonify({"status":"error","message":str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status":"error","message":str(e)}), 500


# ── /api/transition ───────────────────────────────────────────────────────────
@app.route('/api/transition', methods=['POST'])
def transition():
    """
    Compute a single transition (energy difference, dipole moment, and
    oscillator strength) between two subbands at one electric field value.

    Expected extra params (beyond standard structure params):
        state_i : int  lower state (1-based), default 1
        state_j : int  upper state (1-based), default 2
    """
    try:
        params = request.json
        grid, energies, wfs, *_ = build_grid_and_solve(params)

        i = int(params.get('state_i', 1))
        j = int(params.get('state_j', 2))
        if i < 1 or j < 1 or i > len(energies) or j > len(energies):
            raise ValueError(f"State indices must be within 1..{len(energies)} "
                              f"(only {len(energies)} bound states found).")

        z = grid.get_z()
        tc = TransitionCalculator()
        e_ij, d_ij, f_ij = tc.calculate(z, energies, wfs, i, j)

        if e_ij is None or d_ij is None or f_ij is None:
            raise ValueError("Could not compute transition for the requested states.")

        e_ij = abs(e_ij)
        f_ij = abs(f_ij)

        return jsonify({
            "status": "success",
            "transition": {
                "state_i":    i,
                "state_j":    j,
                "E_ij_meV":   _safe(e_ij / ConstAndScales.meV),
                "d_ij_nm":    _safe(d_ij / 10.0),   # Å → nm
                "f_ij":       _safe(f_ij),
                "electric_field": float(params.get('electric_field', 0.0)),
            }
        })
    except ValueError as e: return jsonify({"status":"error","message":str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status":"error","message":str(e)}), 500

# ── /api/transition-sweep ───────────────────────────────────────────────────────
@app.route('/api/transition-sweep', methods=['POST'])
def transition_sweep():
    """
    Sweep the electric field (K) and compute the transition quantities at
    each point.

    Expected extra params (beyond standard structure params, electric_field
    is ignored in favour of the sweep range):
        state_i : int    lower state (1-based), default 1
        state_j : int    upper state (1-based), default 2
        k_start : float  sweep start [kV/cm]
        k_end   : float  sweep end   [kV/cm]
        k_step  : float  sweep step  [kV/cm], must be > 0
    """
    try:
        params = dict(request.json or {})

        i = int(params.get('state_i', 1))
        j = int(params.get('state_j', 2))
        k_start = float(params.get('k_start', 0.0))
        k_end   = float(params.get('k_end', 0.0))
        k_step  = float(params.get('k_step', 1.0))

        if k_step <= 0:
            raise ValueError("k_step must be greater than 0.")
        if k_end < k_start:
            raise ValueError("k_end must be greater than or equal to k_start.")

        k_values = np.arange(k_start, k_end + k_step/2.0, k_step)
        if len(k_values) == 0:
            raise ValueError("Sweep range produced no points.")
        if len(k_values) > 200:
            raise ValueError(f"Sweep would run {len(k_values)} points — "
                              f"please use a coarser k_step (max 200 points).")

        tc = TransitionCalculator()
        k_out, e_out, d_out, f_out = [], [], [], []

        for K in k_values:
            sweep_params = dict(params)
            sweep_params['electric_field'] = float(K)
            grid, energies, wfs, *_ = build_grid_and_solve(sweep_params)

            if i > len(energies) or j > len(energies):
                continue

            z = grid.get_z()
            e_ij, d_ij, f_ij = tc.calculate(z, energies, wfs, i, j)
            if e_ij is None or d_ij is None or f_ij is None:
                continue
            e_ij = abs(e_ij)
            f_ij = abs(f_ij)

            k_out.append(float(K))
            e_out.append(_safe(e_ij / ConstAndScales.meV))
            d_out.append(_safe(d_ij / 10.0))   # Å → nm
            f_out.append(_safe(f_ij))

        if not k_out:
            raise ValueError("No valid transitions found across the sweep range "
                              "— try fewer target states or a different range.")

        return jsonify({
            "status": "success",
            "state_i": i, "state_j": j,
            "sweep": {
                "k_kVcm":    k_out,
                "E_ij_meV":  e_out,
                "d_ij_nm":   d_out,
                "f_ij":      f_out,
            }
        })
    except ValueError as e: return jsonify({"status":"error","message":str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status":"error","message":str(e)}), 500


# ── /api/transition-structure-sweep ─────────────────────────────────────────────
@app.route('/api/transition-structure-sweep', methods=['POST'])
def transition_structure_sweep():
    """
    Sweep a structural composition parameter — well width or barrier molar
    content — and compute the transition quantities at each point.

    A structure sweep parameter is always required. The electric field is
    either held fixed at a single value, or itself swept — in which case the
    structure sweep is repeated once per K value, and the response contains
    one series per K value so the frontend can overlay one line per K on the
    same plot.

    Layers with the lowest alloy fraction in `layer_structure` are treated
    as the well(s); layers with the highest alloy fraction are treated as
    the barrier(s).

    """
    try:
        params = dict(request.json or {})

        i = int(params.get('state_i', 1))
        j = int(params.get('state_j', 2))
        sweep_param = params.get('sweep_param', 'width')
        if sweep_param not in ('width', 'molar'):
            raise ValueError("sweep_param must be 'width' or 'molar'.")

        sweep_start = float(params.get('sweep_start', 0.0))
        sweep_end   = float(params.get('sweep_end', 0.0))
        sweep_step  = float(params.get('sweep_step', 1.0))

        if sweep_step <= 0:
            raise ValueError("sweep_step must be greater than 0.")
        if sweep_end < sweep_start:
            raise ValueError("sweep_end must be greater than or equal to sweep_start.")

        raw_layers = params.get('layer_structure', '')
        tokens = raw_layers.strip().split()
        if len(tokens) % 2 != 0 or len(tokens) < 4:
            raise ValueError("layer_structure must be pairs of Width (Å) and Molar fraction, "
                              "with at least two layers.")
        base_layers = [[float(tokens[k]), float(tokens[k + 1])] for k in range(0, len(tokens), 2)]

        alloys = [layer[1] for layer in base_layers]
        min_alloy, max_alloy = min(alloys), max(alloys)
        if abs(max_alloy - min_alloy) < 1e-12:
            raise ValueError("Cannot identify distinct well/barrier layers "
                              "(all alloy fractions are equal) — structure sweep needs both.")

        well_idx    = [k for k, a in enumerate(alloys) if abs(a - min_alloy) < 1e-9]
        barrier_idx = [k for k, a in enumerate(alloys) if abs(a - max_alloy) < 1e-9]

        sweep_values = np.arange(sweep_start, sweep_end + sweep_step / 2.0, sweep_step)
        if len(sweep_values) == 0:
            raise ValueError("Sweep range produced no points.")
        if len(sweep_values) > 200:
            raise ValueError(f"Sweep would run {len(sweep_values)} points — "
                              f"please use a coarser step (max 200 points).")

        # ── Electric field: either a single fixed value, or a swept range ──
        sweep_k = bool(params.get('sweep_k', False))
        if sweep_k:
            k_start = float(params.get('k_start', 0.0))
            k_end   = float(params.get('k_end', 0.0))
            k_step  = float(params.get('k_step', 1.0))
            if k_step <= 0:
                raise ValueError("k_step must be greater than 0.")
            if k_end < k_start:
                raise ValueError("k_end must be greater than or equal to k_start.")
            k_values = np.arange(k_start, k_end + k_step / 2.0, k_step)
            if len(k_values) == 0:
                raise ValueError("K sweep range produced no points.")
            if len(k_values) > 50:
                raise ValueError(f"K sweep would run {len(k_values)} values — "
                                  f"please use a coarser K step (max 50 values).")
        else:
            k_values = np.array([float(params.get('electric_field', 0.0))])

        total_runs = len(k_values) * len(sweep_values)
        if total_runs > 600:
            raise ValueError(f"This sweep would run {total_runs} simulations "
                              f"(K values × structure points) — please use coarser "
                              f"steps (max 600 combined points).")

        tc = TransitionCalculator()
        series = []

        for K in k_values:
            x_out, e_out, d_out, f_out = [], [], [], []

            for val in sweep_values:
                layers = [list(l) for l in base_layers]
                if sweep_param == 'width':
                    for k in well_idx:
                        layers[k][0] = float(val)
                else:  # 'molar'
                    for k in barrier_idx:
                        layers[k][1] = float(val)

                layer_str = ' '.join(f"{w} {x}" for w, x in layers)
                sweep_params = dict(params)
                sweep_params['layer_structure'] = layer_str
                sweep_params['electric_field']  = float(K)

                grid, energies, wfs, *_ = build_grid_and_solve(sweep_params)

                if i > len(energies) or j > len(energies):
                    continue

                z = grid.get_z()
                e_ij, d_ij, f_ij = tc.calculate(z, energies, wfs, i, j)
                if e_ij is None or d_ij is None or f_ij is None:
                    continue
                e_ij = abs(e_ij)
                f_ij = abs(f_ij)

                x_out.append(float(val))
                e_out.append(_safe(e_ij / ConstAndScales.meV))
                d_out.append(_safe(d_ij / 10.0))   # Å → nm
                f_out.append(_safe(f_ij))

            if x_out:
                series.append({
                    "k_kVcm":   float(K),
                    "x_vals":   x_out,
                    "E_ij_meV": e_out,
                    "d_ij_nm":  d_out,
                    "f_ij":     f_out,
                })

        if not series:
            raise ValueError("No valid transitions found across the sweep range "
                              "— try fewer target states or a different range.")

        return jsonify({
            "status": "success",
            "sweep_param": sweep_param,
            "sweep_k": sweep_k,
            "state_i": i, "state_j": j,
            "series": series,
        })
    except ValueError as e: return jsonify({"status":"error","message":str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status":"error","message":str(e)}), 500


# ── /api/material-info ────────────────────────────────────────────────────────
@app.route('/api/material-info', methods=['GET'])
def material_info():
    name = request.args.get('material')
    if not name: return jsonify({"status":"error","message":"material required"}), 400
    try:
        m = Material(name)
        return jsonify({"status":"success","material":name,
            "band_gap":       {"well":m.Eg.well,"barrier":m.Eg.barr},
            "effective_mass": {"well":m.m.well, "barrier":m.m.barr},
            "kane_parameter": {"well":m.P.well, "barrier":m.P.barr}})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)