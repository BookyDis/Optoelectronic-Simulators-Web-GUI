#   This module is an addition to the software requested by the supervisor
#   AbsorptionCalculator.py
#   
#   Computes the intersubband absorption coefficient α(ħω) for a quantum well
#   heterostructure given pre-computed energies and wavefunctions.
#
#   Formula (Lorentzian lineshape, SI units throughout):
#
#       α(ħω) = (e² / (ε₀ n_r c m₀ L_eff))
#               × Σ_{i<j}  ΔN_ij  × f_ij
#               × (Γ_ij / 2π) / [(ħω − E_ij)² + (Γ_ij/2)²]
#
#   where:
#       ΔN_ij  = N_i − N_j          population inversion  [m⁻²]
#       f_ij                         dimensionless oscillator strength
#       Γ_ij                         FWHM linewidth        [J]
#       E_ij   = E_j − E_i          transition energy     [J]
#       L_eff                        effective well length  [m]
#
#   Sign convention: α > 0 means absorption, α < 0 means gain.
#
#   Usage
#   -----
#   from src.AbsorptionCalculator import AbsorptionCalculator
#
#   populations = {1: 5e14, 2: 1e14}          # state index (1-based) → sheet density [m⁻²]
#   linewidths  = {(1,2): 10.0, (1,3): 15.0}  # (i,j) pair (1-based)  → FWHM [meV]
#
#   calc = AbsorptionCalculator(grid, energies, psis, material)
#   hbar_omega, alpha = calc.get_spectrum(populations, linewidths)
#   pairs, values     = calc.get_transition_table(populations, linewidths)
#

import numpy as np
from src import ConstAndScales
from src.TransitionCalculator import TransitionCalculator


# Physical constants not yet in ConstAndScales
_EPS0 = 8.854187817e-12     # Permittivity of free space  [F/m]
_C    = 2.99792458e8        # Speed of light              [m/s]


class AbsorptionCalculator:
    """
    Intersubband absorption coefficient calculator.

    Parameters
    ----------
    grid : Grid
        The Grid object used for the solved structure (provides z, L_eff, n_r).
    energies : np.ndarray
        Bound-state energies in SI units [J], shape (nstates,).
    psis : list of np.ndarray
        Normalised wavefunctions, each shape (nz,).
    material : Material
        Material object — used only for the refractive index ``material.nr``.
    """

    def __init__(self, grid, energies, psis, material):
        self.G        = grid
        self.energies = np.asarray(energies, dtype=np.float64)
        self.psis     = psis
        self.nr       = material.nr

        self._tc      = TransitionCalculator()

        # Effective length: full well extent in metres
        z = grid.get_z()
        self.L_eff = float(z[-1] - z[0])   # [m]

        # Pre-compute all pairwise transition quantities (upper > lower, i.e. j > i)
        self._pairs = []    # list of (i, j) 1-based
        self._E_ij  = {}    # [J]
        self._f_ij  = {}    # dimensionless
        self._d_ij  = {}    # [nm] for display

        nst = len(self.energies)
        z_si = grid.get_z()

        for i in range(1, nst + 1):
            for j in range(i + 1, nst + 1):
                E_ij = self._tc.get_energy_diff(self.energies, j, i)   # E_j − E_i > 0
                f_ij = self._tc.get_oscillator_strength(z_si, self.energies, self.psis, j, i)
                d_ij = self._tc.get_dipole(z_si, self.psis, j, i)      # [Å] from TC

                if E_ij is None or f_ij is None or d_ij is None:
                    continue
                if E_ij <= 0:
                    continue

                self._pairs.append((i, j))
                self._E_ij[(i, j)] = E_ij
                self._f_ij[(i, j)] = f_ij
                self._d_ij[(i, j)] = d_ij   # [Å], TC already divides by ANGSTROM

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_spectrum(self, populations, linewidths,
                     energy_range_meV=None, n_points=2000):
        """
        Compute α(ħω) over a range of photon energies.

        Parameters
        ----------
        populations : dict  {state_index (1-based): sheet_density [m⁻²]}
            Sheet carrier density per subband.  Missing states default to 0.
        linewidths : dict  {(i, j): FWHM_meV}
            Per-transition FWHM linewidth in meV.  Pairs are 1-based, with
            i < j (lower → upper).  A scalar default_linewidth_meV can be
            supplied for any missing pair via the ``default_linewidth_meV``
            keyword, otherwise missing pairs are skipped.
        energy_range_meV : tuple (E_min, E_max) or None
            Photon energy axis range in meV.  Defaults to spanning all
            transition energies with ±30 meV padding.
        n_points : int
            Number of points on the photon energy axis.

        Returns
        -------
        hbar_omega_meV : np.ndarray  shape (n_points,)
            Photon energy axis [meV].
        alpha_cm : np.ndarray  shape (n_points,)
            Absorption coefficient [cm⁻¹].  Positive = absorption, negative = gain.
        """
        if not self._pairs:
            raise RuntimeError("No valid transitions found — check energies/wavefunctions.")

        # Build photon energy axis
        if energy_range_meV is None:
            E_vals_meV = [v / ConstAndScales.meV for v in self._E_ij.values()]
            pad = 30.0
            energy_range_meV = (max(0.0, min(E_vals_meV) - pad),
                                 max(E_vals_meV) + pad)

        hw_meV = np.linspace(energy_range_meV[0], energy_range_meV[1], n_points)
        hw_J   = hw_meV * ConstAndScales.meV   # [J]

        alpha = np.zeros(n_points, dtype=np.float64)

        prefactor = (ConstAndScales.E**2
                     / (_EPS0 * self.nr * _C * ConstAndScales.m0 * self.L_eff))

        for (i, j) in self._pairs:
            lw_meV = linewidths.get((i, j)) or linewidths.get((j, i))
            if lw_meV is None:
                continue                         # skip transitions with no linewidth

            Gamma_J  = lw_meV * ConstAndScales.meV     # FWHM [J]
            E_ij_J   = self._E_ij[(i, j)]               # transition energy [J]
            f_ij     = self._f_ij[(i, j)]

            N_i = float(populations.get(i, 0.0))
            N_j = float(populations.get(j, 0.0))
            dN  = N_i - N_j                             # population inversion [m⁻²]

            # Lorentzian lineshape: L(x) = (Γ/2π) / (x² + (Γ/2)²)
            x        = hw_J - E_ij_J
            lorentz  = (Gamma_J / (2.0 * np.pi)) / (x**2 + (Gamma_J / 2.0)**2)

            alpha   += prefactor * dN * f_ij * lorentz

        # Convert m⁻¹ → cm⁻¹
        alpha_cm = alpha * 1e-2

        return hw_meV, alpha_cm

    def get_transition_table(self, populations, linewidths):
        """
        Return a summary table of all transitions with their key quantities.

        Returns
        -------
        pairs : list of (i, j)
        records : list of dict, each containing:
            'pair'           : (i, j)
            'E_ij_meV'       : transition energy [meV]
            'f_ij'           : oscillator strength (dimensionless)
            'd_ij_nm'        : dipole matrix element [nm]
            'gamma_meV'      : FWHM linewidth [meV]  (None if not supplied)
            'dN_m2'          : population inversion N_i − N_j [m⁻²]
            'peak_alpha_cm'  : peak α at line centre [cm⁻¹] (None if Γ missing)
        """
        records = []
        prefactor = (ConstAndScales.E**2
                     / (_EPS0 * self.nr * _C * ConstAndScales.m0 * self.L_eff))

        for (i, j) in self._pairs:
            lw_meV = linewidths.get((i, j)) or linewidths.get((j, i))
            E_ij_meV = self._E_ij[(i, j)] / ConstAndScales.meV
            f_ij     = self._f_ij[(i, j)]
            d_ij_nm  = self._d_ij[(i, j)] * ConstAndScales.ANGSTROM / 1e-9   # Å → nm

            N_i = float(populations.get(i, 0.0))
            N_j = float(populations.get(j, 0.0))
            dN  = N_i - N_j

            if lw_meV is not None:
                Gamma_J  = lw_meV * ConstAndScales.meV
                # Peak of Lorentzian at line centre: L(0) = 2/(π Γ)
                lorentz_peak = 2.0 / (np.pi * Gamma_J)
                peak = prefactor * dN * f_ij * lorentz_peak * 1e-2   # cm⁻¹
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
        """Return all detected transition pairs (1-based tuples)."""
        return list(self._pairs)