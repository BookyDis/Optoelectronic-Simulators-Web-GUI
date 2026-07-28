import os, tempfile, traceback
import numpy as np
from flask import Flask, request, jsonify, send_from_directory

from src import ConstAndScales
from src.Material            import Material
from src.Composition         import Composition
from src.Grid                import Grid
from src.Solvers_FDM         import Parabolic_FDM, Kane_FDM, Taylor_FDM
from src.Solvers_TMM         import Parabolic_TMM, Taylor_TMM, Kane_TMM, Ekenberg_TMM
from src.AbsorptionCalculator import AbsorptionCalculator
from src.DiffusionCalculator  import DiffusionCalculator
from src.SegregationCalculator     import SegregationCalculator
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

    if not (material_system and solver_method and subband_model):
        raise ValueError("Missing required parameters: material, solver, or subband_model.")

    tokens = raw_layers.strip().split()
    if len(tokens) % 2 != 0:
        raise ValueError("layer_structure must be pairs of Width (Å) and Molar fraction.")
    layer_profile = [[float(tokens[i]), float(tokens[i+1])] for i in range(0, len(tokens), 2)]

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

    return grid, energies, wavefunctions, material_system, solver_method, subband_model, num_states

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
        grid, energies, wfs, mat, solver, model, n = build_grid_and_solve(params)
        return jsonify({
            "status":  "success",
            "message": f"Completed {solver} ({model}) — {len(energies)} states found.",
            "results": {
                "energies":      [e/ConstAndScales.E for e in energies[:n]],
                "wavefunctions": [_lst(wf) for wf in wfs[:n]],
                "z_grid":        _lst(grid.get_z()/ConstAndScales.ANGSTROM),
                "potential":     _lst(grid.get_bandstructure_potential()/ConstAndScales.E),
                "material": mat, "solver_method": solver, "subband_model": model,
            }
        })
    except ValueError as e: return jsonify({"status":"error","message":str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status":"error","message":str(e)}), 500

# ── /api/absorption ───────────────────────────────────────────────────────────
@app.route('/api/absorption', methods=['POST'])
def absorption():
    try:
        params = request.json
        grid, energies, wfs, mat, *_ = build_grid_and_solve(params)

        populations = {int(k): float(v) for k,v in params.get('populations',{}).items()}
        linewidths  = {}
        for k,v in params.get('linewidths',{}).items():
            a,b = k.split(','); linewidths[(int(a),int(b))] = float(v)

        er = params.get('energy_range_meV')
        if er: er = tuple(er)

        calc = AbsorptionCalculator(grid, energies, wfs, Material(mat))
        hw_meV, alpha_cm = calc.get_spectrum(populations, linewidths,
                                             energy_range_meV=er,
                                             n_points=int(params.get('n_points',2000)))
        _, records = calc.get_transition_table(populations, linewidths)

        return jsonify({
            "status": "success",
            "spectrum": {"hbar_omega_meV": hw_meV.tolist(), "alpha_cm": alpha_cm.tolist()},
            "transitions": [{
                "pair":_lst(r["pair"]), "E_ij_meV":_safe(r["E_ij_meV"]),
                "f_ij":_safe(r["f_ij"]), "d_ij_nm":_safe(r["d_ij_nm"]),
                "gamma_meV":_safe(r["gamma_meV"]), "dN_m2":_safe(r["dN_m2"]),
                "peak_alpha_cm":_safe(r["peak_alpha_cm"]),
            } for r in records],
        })
    except ValueError as e: return jsonify({"status":"error","message":str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status":"error","message":str(e)}), 500

# ── /api/diffusion ────────────────────────────────────────────────────────────
@app.route('/api/diffusion', methods=['POST'])
def diffusion():
    """
    Steady-state 1-D carrier diffusion.

    Expected extra params (beyond standard structure params):
        transport_properties : {"1": [D_m2s, tau_s], "2": [...], ...}
        generation           : {"1": G_uniform_m3s, "2": ...}
    """
    try:
        params = request.json
        grid, energies, wfs, *_ = build_grid_and_solve(params)

        nst  = len(energies)
        diff = DiffusionCalculator(grid, nst)
        nz   = grid.get_nz()

        # Set transport properties
        tp = params.get('transport_properties', {})
        for sb_str, vals in tp.items():
            sb = int(sb_str)
            if 1 <= sb <= nst and len(vals) == 2:
                diff.set_properties(subband=sb, D=float(vals[0]), tau=float(vals[1]))

        # Build spatially-resolved generation profiles.
        #
        # NOTE: a spatially *uniform* generation rate G(z)=G0 combined with
        # zero-flux (Neumann) boundaries has an exact steady-state analytic
        # solution N(z) = G0*tau -- a perfectly flat line, since a constant
        # already satisfies dN/dz=0 everywhere. That produced the "flat
        # line" bug. Physically, carriers are photogenerated in proportion
        # to where the pumped subband's wavefunction actually lives, so we
        # weight the user-supplied rate (interpreted as an areal generation
        # rate, m^-2 s^-1) by the normalised probability density |psi_i(z)|^2
        # (m^-1, since the integral of |psi|^2 dz = 1) of that subband's
        # eigenstate:
        #
        #   G_i(z) = G_i_input * |psi_i(z)|^2   ->  [m^-2 s^-1]*[m^-1] = [m^-3 s^-1]
        #
        # This preserves the total generation rate (integral of G_i(z) dz
        # = G_i_input) while localising it spatially, giving a physically
        # meaningful, non-flat steady-state carrier profile peaked in the
        # well(s) rather than a flat line.
        gen_raw    = params.get('generation', {})
        generation = {}
        for k, v in gen_raw.items():
            sb = int(k)
            if 1 <= sb <= len(wfs):
                psi = np.asarray(wfs[sb - 1], dtype=np.float64)
                generation[sb] = float(v) * (psi ** 2)
            else:
                generation[sb] = np.zeros(nz)

        spatial = diff.solve_steady_state(generation)
        sheets  = diff.get_sheet_densities(spatial)
        peaks   = diff.get_peak_densities(spatial)

        z_A = _lst(grid.get_z() / ConstAndScales.ANGSTROM)

        return jsonify({
            "status": "success",
            "z_grid": z_A,
            "spatial_populations": {str(sb): _lst(N_z) for sb,N_z in spatial.items()},
            "sheet_densities":     {str(sb): float(v)  for sb,v  in sheets.items()},
            "peak_densities":      {str(sb): float(v)  for sb,v  in peaks.items()},
        })
    except ValueError as e: return jsonify({"status":"error","message":str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status":"error","message":str(e)}), 500

# ── /api/segregation ──────────────────────────────────────────────────────────
@app.route('/api/segregation', methods=['POST'])
def segregation():
    try:
        params       = request.json
        raw_layers   = params.get('layer_structure','')
        grid_spacing = float(params.get('grid_spacing', 1.0))
        model_type   = params.get('model_type', 'exponential')
        param_value  = float(params.get('param_value', 10.0))
        asymmetric   = bool(params.get('asymmetric', True))

        tokens = raw_layers.strip().split()
        if len(tokens) % 2 != 0:
            raise ValueError("layer_structure must be pairs.")
        layer_profile = [[float(tokens[i]),float(tokens[i+1])] for i in range(0,len(tokens),2)]

        composition = Composition.from_array(layer_profile)
        seg = SegregationCalculator(composition, dz=grid_spacing)

        if model_type == 'erfc':
            x_smeared = seg.apply_erfc(sigma=param_value)
        else:
            x_smeared = seg.apply_exponential(lam=param_value, asymmetric=asymmetric)

        return jsonify({
            "status":    "success",
            "z":         seg.get_z().tolist(),
            "x_nominal": seg.get_nominal_profile().tolist(),
            "x_smeared": x_smeared.tolist(),
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

        return jsonify({
            "status": "success",
            "transition": {
                "state_i":    i,
                "state_j":    j,
                "E_ij_meV":   _safe(e_ij / ConstAndScales.meV),
                "d_ij_A":     _safe(d_ij),
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

            k_out.append(float(K))
            e_out.append(_safe(e_ij / ConstAndScales.meV))
            d_out.append(_safe(d_ij))
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
                "d_ij_A":    d_out,
                "f_ij":      f_out,
            }
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