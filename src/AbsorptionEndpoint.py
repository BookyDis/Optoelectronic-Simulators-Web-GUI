# further addition as requested by the supervisor

@app.route('/api/absorption', methods=['POST'])
def absorption():
    """
    Compute the intersubband absorption spectrum.

    Expected JSON body
    ------------------
    {
        // --- structure (same as /api/simulate) ---
        "material":       "AlGaAs",
        "solver":         "FDM",
        "subband_model":  "parabolic",
        "layer_structure": "200 0.15 200 0.0 200 0.15",
        "electric_field": 0.0,
        "grid_spacing":   1.0,
        "num_states":     4,

        // --- absorption-specific ---
        "populations": {          // sheet density [m⁻²] per subband (1-based)
            "1": 5e14,
            "2": 1e14
        },
        "linewidths": {           // FWHM [meV] per transition pair (1-based, i < j)
            "1,2": 10.0,
            "1,3": 15.0
        },
        "energy_range_meV": [0, 200],   // optional, auto-set if omitted
        "n_points": 2000                 // optional
    }

    Returns
    -------
    {
        "status": "success",
        "spectrum": {
            "hbar_omega_meV": [...],
            "alpha_cm":       [...],
        },
        "transitions": [
            {
                "pair":           [i, j],
                "E_ij_meV":       float,
                "f_ij":           float,
                "d_ij_nm":        float,
                "gamma_meV":      float | null,
                "dN_m2":          float,
                "peak_alpha_cm":  float | null
            },
            ...
        ]
    }
    """
    try:
        params = request.json

        # ---- re-run the solver (same logic as /api/simulate) ----
        material_system = params.get('material')
        solver_method   = params.get('solver')
        subband_model   = params.get('subband_model')
        raw_layers      = params.get('layer_structure', '')
        electric_field  = float(params.get('electric_field', 0.0))
        grid_spacing    = float(params.get('grid_spacing', 1.0))
        num_states      = int(params.get('num_states', 4))

        tokens = raw_layers.strip().split()
        if len(tokens) % 2 != 0:
            return jsonify({"status": "error",
                            "message": "layer_structure must be pairs of Width and Molar."}), 400

        layer_profile = [[float(tokens[k]), float(tokens[k+1])]
                         for k in range(0, len(tokens), 2)]

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
                return jsonify({"status": "error",
                                "message": f"Invalid combination: {solver_method} + {subband_model}"}), 400

            energies, wavefunctions = solver.get_wavefunctions()
        finally:
            if os.path.exists(layer_file):
                os.unlink(layer_file)

        # ---- parse absorption-specific inputs ----
        # populations: JSON keys are strings, convert to int
        pop_raw     = params.get('populations', {})
        populations = {int(k): float(v) for k, v in pop_raw.items()}

        # linewidths: keys like "1,2" → tuple (1, 2)
        lw_raw      = params.get('linewidths', {})
        linewidths  = {}
        for k, v in lw_raw.items():
            parts = k.split(',')
            if len(parts) == 2:
                linewidths[(int(parts[0]), int(parts[1]))] = float(v)

        energy_range = params.get('energy_range_meV', None)
        if energy_range is not None:
            energy_range = tuple(energy_range)
        n_points = int(params.get('n_points', 2000))

        # ---- run absorption calculator ----
        material = Material(material_system)
        calc     = AbsorptionCalculator(grid, energies, wavefunctions, material)

        hw_meV, alpha_cm = calc.get_spectrum(
            populations, linewidths,
            energy_range_meV=energy_range,
            n_points=n_points
        )

        _, records = calc.get_transition_table(populations, linewidths)

        # Serialise
        def _safe(v):
            if v is None:
                return None
            if hasattr(v, 'item'):
                return v.item()
            return v

        transitions_out = []
        for r in records:
            transitions_out.append({
                "pair"          : list(r["pair"]),
                "E_ij_meV"      : _safe(r["E_ij_meV"]),
                "f_ij"          : _safe(r["f_ij"]),
                "d_ij_nm"       : _safe(r["d_ij_nm"]),
                "gamma_meV"     : _safe(r["gamma_meV"]),
                "dN_m2"         : _safe(r["dN_m2"]),
                "peak_alpha_cm" : _safe(r["peak_alpha_cm"]),
            })

        return jsonify({
            "status": "success",
            "spectrum": {
                "hbar_omega_meV": hw_meV.tolist(),
                "alpha_cm":       alpha_cm.tolist(),
            },
            "transitions": transitions_out
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Absorption error: {str(e)}"}), 500