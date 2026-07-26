# further addition as requested by the supervisor
#
#   AbsorptionCalculator.py
#
#   Computes the intersubband absorption coefficient α(ħω).
#
#   Formula (Lorentzian lineshape, SI units throughout):
#
#       α(ħω) = (e² / (ε₀ n_r c m₀ L_eff))
#               × Σ_{i<j}  ΔN_ij × f_ij
#               × (Γ_ij / 2π) / [(ħω − E_ij)² + (Γ_ij/2)²]
#
#   Unit chain for f_ij (dimensionless):
#       z          [m]  — from grid.get_z()
#       psi        [m⁻½] — normalised so ∫|ψ|² dz = 1
#       d_ij = ∫ψ_i z ψ_j dz   [m]
#       f_ij = (2 m₀ / ħ²) × E_ij [J] × |d_ij|² [m²]   → dimensionless ✓
#
#   Sign convention: α > 0 absorption, α < 0 gain.
#

import numpy as np
from src import ConstAndScales
from src.TransitionCalculator import TransitionCalculator

_EPS0 = 8.854187817e-12     # [F/m]
_C    = 2.99792458e8        # [m/s]


class AbsorptionCalculator:
    """
    Intersubband absorption coefficient calculator.

    Parameters
    ----------
    grid     : Grid       — provides z-axis and L_eff
    energies : np.ndarray — bound-state energies [J], shape (nstates,)
    psis     : list       — normalised wavefunctions, each shape (nz,)
    material : Material   — used for refractive index material.nr
    """

    def __init__(self, grid, energies, psis, material):
        self.G        = grid
        self.energies = np.asarray(energies, dtype=np.float64)
        self.psis     = psis
        self.nr       = material.nr

        z_si = grid.get_z()                     # [m]
        self.L_eff = float(z_si[-1] - z_si[0]) # [m]

        # Pre-compute pairwise quantities; all in SI
        self._pairs = []
        self._E_ij  = {}   # transition energy            [J]
        self._f_ij  = {}   # oscillator strength          [dimensionless]
        self._d_ij  = {}   # dipole matrix element        [m]

        nst = len(self.energies)
        for i in range(1, nst + 1):
            for j in range(i + 1, nst + 1):
                # --- energy difference E_j - E_i  (> 0 since j > i) ---
                E_ij = self._energy_diff(j, i)   # [J]
                if E_ij is None or E_ij <= 0:
                    continue

                # --- dipole matrix element in metres ---
                d_ij = self._dipole_SI(z_si, j, i)   # [m]
                if d_ij is None:
                    continue

                # --- oscillator strength (dimensionless) ---
                # f = (2 m₀ / ħ²) × E_ij × |d_ij|²
                f_ij = (2.0 * ConstAndScales.m0 / ConstAndScales.HBAR**2) * E_ij * d_ij**2

                self._pairs.append((i, j))
                self._E_ij[(i, j)] = E_ij
                self._f_ij[(i, j)] = f_ij
                self._d_ij[(i, j)] = d_ij

    # ------------------------------------------------------------------
    # Internal helpers — unit-explicit
    # ------------------------------------------------------------------

    def _energy_diff(self, i, j):
        """E_i - E_j [J]; returns None if index out of range."""
        if max(i, j) > len(self.energies):
            return None
        return float(self.energies[i - 1] - self.energies[j - 1])

    def _dipole_SI(self, z_si, i, j):
        """
        ∫ ψ_i(z) · z · ψ_j(z) dz  [m]

        z_si and psis must both be in SI (metres / m⁻½).
        Uses np.trapezoid for accuracy.
        """
        if max(i, j) > len(self.psis):
            return None
        psi_i = np.asarray(self.psis[i - 1], dtype=np.float64)
        psi_j = np.asarray(self.psis[j - 1], dtype=np.float64)
        integrand = psi_i * z_si * psi_j
        return abs(np.trapezoid(integrand, z_si))   # [m]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_spectrum(self, populations, linewidths,
                     energy_range_meV=None, n_points=2000):
        """
        Compute α(ħω) [cm⁻¹] over a photon-energy range.

        Parameters
        ----------
        populations     : dict  {state (1-based): N_i [m⁻²]}
        linewidths      : dict  {(i,j) or (j,i): Γ FWHM [meV]}
        energy_range_meV: (E_min, E_max) in meV, or None to auto-detect
        n_points        : int, resolution of the energy axis

        Returns
        -------
        hw_meV   : np.ndarray [meV]
        alpha_cm : np.ndarray [cm⁻¹]   positive = absorption, negative = gain
        """
        if not self._pairs:
            raise RuntimeError("No valid transitions found.")

        # Energy axis
        if energy_range_meV is None:
            E_vals_meV = [v / ConstAndScales.meV for v in self._E_ij.values()]
            pad = 30.0
            energy_range_meV = (max(0.0, min(E_vals_meV) - pad),
                                 max(E_vals_meV) + pad)

        hw_meV = np.linspace(energy_range_meV[0], energy_range_meV[1], n_points)
        hw_J   = hw_meV * ConstAndScales.meV

        alpha  = np.zeros(n_points, dtype=np.float64)

        # prefactor: e² / (ε₀ n_r c m₀ L_eff)   [m / (kg·s)]  × [m⁻²] → [m⁻¹]
        prefactor = (ConstAndScales.E**2
                     / (_EPS0 * self.nr * _C * ConstAndScales.m0 * self.L_eff))

        for (i, j) in self._pairs:
            lw_meV = linewidths.get((i, j)) or linewidths.get((j, i))
            if lw_meV is None:
                continue

            Gamma_J = lw_meV * ConstAndScales.meV      # [J]
            E_ij_J  = self._E_ij[(i, j)]               # [J]
            f_ij    = self._f_ij[(i, j)]               # dimensionless

            N_i = float(populations.get(i, 0.0))
            N_j = float(populations.get(j, 0.0))
            dN  = N_i - N_j                            # [m⁻²]

            # Lorentzian: L(x) = (Γ/2π) / (x² + (Γ/2)²)
            x       = hw_J - E_ij_J
            lorentz = (Gamma_J / (2.0 * np.pi)) / (x**2 + (Gamma_J / 2.0)**2)

            alpha  += prefactor * dN * f_ij * lorentz  # [m⁻¹]

        return hw_meV, alpha * 1e-2   # → [cm⁻¹]

    def get_transition_table(self, populations, linewidths):
        """
        Summary table of all detected transitions.

        Returns
        -------
        pairs   : list of (i, j)
        records : list of dict with keys:
                  pair, E_ij_meV, f_ij, d_ij_nm, gamma_meV, dN_m2, peak_alpha_cm
        """
        prefactor = (ConstAndScales.E**2
                     / (_EPS0 * self.nr * _C * ConstAndScales.m0 * self.L_eff))

        records = []
        for (i, j) in self._pairs:
            lw_meV   = linewidths.get((i, j)) or linewidths.get((j, i))
            E_ij_meV = self._E_ij[(i, j)] / ConstAndScales.meV
            f_ij     = self._f_ij[(i, j)]
            d_ij_nm  = self._d_ij[(i, j)] / 1e-9       # m → nm

            N_i = float(populations.get(i, 0.0))
            N_j = float(populations.get(j, 0.0))
            dN  = N_i - N_j

            if lw_meV is not None:
                Gamma_J      = lw_meV * ConstAndScales.meV
                lorentz_peak = 2.0 / (np.pi * Gamma_J)  # peak of L at line centre
                peak = prefactor * dN * f_ij * lorentz_peak * 1e-2
            else:
                peak = None

            records.append({
                "pair"          : (i, j),
                "E_ij_meV"      : E_ij_meV,
                "f_ij"          : f_ij,
                "d_ij_nm"       : d_ij_nm,
                "gamma_meV"     : lw_meV,
                "dN_m2"         : dN,
                "peak_alpha_cm" : peak,
            })

        return self._pairs, records

    def get_pairs(self):
        """Return all detected transition pairs as 1-based (i, j) tuples."""
        return list(self._pairs)