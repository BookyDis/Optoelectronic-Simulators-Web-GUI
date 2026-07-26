# further addition as requested by the supervisor
#
#   DiffusionCalculator.py
#
#   Solves the 1D steady-state carrier drift-diffusion equation across the
#   heterostructure grid, yielding spatially-resolved subband populations.
#
#   Governing equation (∂N/∂t = 0 at steady state):
#
#       D_i · d²N_i/dz² - N_i/τ_i + G_i(z) = 0
#
#   where:
#       N_i(z)  carrier density profile for subband i  [m⁻³]
#       D_i     diffusion coefficient                   [m²/s]
#       τ_i     intersubband/intrasubband lifetime      [s]
#       G_i(z)  volumetric generation/pump rate         [m⁻³ s⁻¹]
#
#   Spatial discretisation: central-difference FDM on the existing Grid z-axis.
#   Boundary conditions: zero-flux Neumann (dN/dz = 0) at both ends.
#   Linear system: A · N = G, solved via sparse direct solver.
#
#   Usage
#   -----
#   from src.DiffusionCalculator import DiffusionCalculator
#
#   diff = DiffusionCalculator(grid, n_states=3)
#   diff.set_properties(subband=1, D=1e-3, tau=1e-12)
#   diff.set_properties(subband=2, D=0.8e-3, tau=5e-13)
#
#   # Uniform generation across the whole structure:
#   G = {1: np.ones(grid.get_nz()) * 1e24,
#        2: np.zeros(grid.get_nz())}
#
#   steady = diff.solve_steady_state(G)
#   sheets = diff.get_sheet_densities(steady)   # → {1: N1_m2, 2: N2_m2}
#

import numpy as np
from scipy.sparse import diags
from scipy.sparse.linalg import spsolve


class DiffusionCalculator:
    """
    Spatially-resolved 1D steady-state carrier diffusion solver.

    Parameters
    ----------
    grid     : Grid  — provides the z-axis in SI [m]
    n_states : int   — number of subbands to track (1-based indexing)
    """

    def __init__(self, grid, n_states):
        self.grid     = grid
        self.z        = np.asarray(grid.get_z(), dtype=np.float64)  # [m]
        self.nz       = len(self.z)
        self.n_states = n_states

        # Transport parameters; index 0 unused (1-based subband indexing)
        self._D   = np.zeros(n_states + 1, dtype=np.float64)        # [m²/s]
        self._tau = np.full(n_states + 1, np.inf, dtype=np.float64) # [s]

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_properties(self, subband, D, tau):
        """
        Set transport parameters for a specific subband.

        Parameters
        ----------
        subband : int    1-based subband index.
        D       : float  Diffusion coefficient [m²/s].
        tau     : float  Lifetime [s].  Use np.inf for no recombination.
        """
        if not (1 <= subband <= self.n_states):
            raise ValueError(
                f"Subband {subband} out of range (1–{self.n_states}).")
        self._D[subband]   = float(D)
        self._tau[subband] = float(tau)

    # ------------------------------------------------------------------
    # Internal matrix builder
    # ------------------------------------------------------------------

    def _build_matrix(self, subband):
        """
        Build the sparse FDM matrix A for:

            D · d²N/dz² - N/τ = -G(z)

        Rearranged to  A · N = G  where all terms on the LHS are moved
        so that A has the diffusion operator with the correct sign.

        Central differences on a non-uniform grid:

            d²N/dz²|_k ≈ [ N_{k-1}/(dz_l·dz_m)
                           - N_k · 2/(dz_l·dz_r)       ← BUG FIX: was wrong sign
                           + N_{k+1}/(dz_r·dz_m) ]
                           where dz_m = (dz_l + dz_r)/2 ... simplified below

        Matrix sign convention:  A[k,*] encodes  -(D·∇² - 1/τ)·N  so that
        A·N = G with G ≥ 0 and N ≥ 0.
        """
        D_val   = self._D[subband]
        tau_val = self._tau[subband]

        nz = self.nz
        main_diag  = np.zeros(nz)
        upper_diag = np.zeros(nz - 1)
        lower_diag = np.zeros(nz - 1)

        # ── Interior nodes (central difference) ──────────────────────
        for k in range(1, nz - 1):
            dz_l = self.z[k]     - self.z[k - 1]   # left spacing
            dz_r = self.z[k + 1] - self.z[k]       # right spacing

            # Coefficients for second-derivative approximation
            c_l =  D_val * 2.0 / (dz_l * (dz_l + dz_r))
            c_r =  D_val * 2.0 / (dz_r * (dz_l + dz_r))
            c_c = -(c_l + c_r)  # always negative

            # A encodes  -(D∇² - 1/τ):
            #   -D∇²N + N/τ = G
            # So:
            #   main    = -c_c + 1/τ  (positive, diagonal dominant)
            #   off-diag= -c_l, -c_r  (negative, physically couples neighbours)
            lower_diag[k - 1] = -c_l
            upper_diag[k]     = -c_r
            recomb = (1.0 / tau_val) if not np.isinf(tau_val) else 0.0
            main_diag[k]      = -c_c + recomb

        # ── Boundary conditions: zero-flux Neumann ────────────────────
        # dN/dz = 0  →  N[0] = N[1]  and  N[-1] = N[-2]
        # Encoded as:  N[0] - N[1] = 0  (row 0)
        #              N[-1] - N[-2] = 0 (row nz-1)
        main_diag[0]       =  1.0
        upper_diag[0]      = -1.0          # upper_diag[0] → A[0, 1]

        main_diag[-1]      =  1.0
        lower_diag[-1]     = -1.0          # lower_diag[-1] → A[nz-1, nz-2]

        return diags(
            [lower_diag, main_diag, upper_diag],
            offsets=[-1, 0, 1],
            format='csr'
        )

    # ------------------------------------------------------------------
    # Solvers
    # ------------------------------------------------------------------

    def solve_steady_state(self, generation_profiles):
        """
        Solve for the steady-state spatial carrier density profile of each subband.

        Parameters
        ----------
        generation_profiles : dict  {subband (1-based): np.ndarray shape (nz,) [m⁻³ s⁻¹]}
            Volumetric generation / pumping rate.  Missing subbands default to zero.

        Returns
        -------
        spatial_populations : dict  {subband: np.ndarray shape (nz,) [m⁻³]}
            Steady-state carrier concentration profiles.  Enforced ≥ 0.
        """
        results = {}

        for sb in range(1, self.n_states + 1):
            G_profile = np.asarray(
                generation_profiles.get(sb, np.zeros(self.nz)),
                dtype=np.float64
            )

            # Trivial case: nothing to do
            if self._D[sb] == 0.0 and np.all(G_profile == 0.0):
                results[sb] = np.zeros(self.nz)
                continue

            A   = self._build_matrix(sb)
            rhs = G_profile.copy()

            # Enforce Neumann BC on RHS (boundary rows have no source)
            rhs[0]  = 0.0
            rhs[-1] = 0.0

            sol = spsolve(A, rhs)
            results[sb] = np.maximum(sol, 0.0)   # physical: N ≥ 0

        return results

    def solve_time_dependent(self, generation_profiles, initial_populations,
                              t_end, n_steps=500):
        """
        Crank-Nicolson time integration of the diffusion-recombination equation.

        Parameters
        ----------
        generation_profiles  : dict  {subband: np.ndarray (nz,) [m⁻³ s⁻¹]}
        initial_populations  : dict  {subband: np.ndarray (nz,) [m⁻³]}
            Initial carrier density profiles (e.g. all zeros, or thermal).
        t_end   : float  End time [s].
        n_steps : int    Number of time steps.

        Returns
        -------
        t_axis  : np.ndarray shape (n_steps+1,)  time points [s]
        history : dict  {subband: np.ndarray shape (n_steps+1, nz) [m⁻³]}
        """
        dt     = t_end / n_steps
        t_axis = np.linspace(0.0, t_end, n_steps + 1)
        history = {}

        for sb in range(1, self.n_states + 1):
            G   = np.asarray(generation_profiles.get(sb, np.zeros(self.nz)),
                              dtype=np.float64)
            N   = np.asarray(initial_populations.get(sb, np.zeros(self.nz)),
                              dtype=np.float64).copy()
            A   = self._build_matrix(sb)           # -(D∇² - 1/τ) operator
            I   = diags(np.ones(self.nz), format='csr')

            # Crank-Nicolson: (I + dt/2·A)·N^{n+1} = (I - dt/2·A)·N^n + dt·G
            lhs = I + 0.5 * dt * A
            rhs_const = G.copy()
            rhs_const[0]  = 0.0
            rhs_const[-1] = 0.0

            snap = np.empty((n_steps + 1, self.nz))
            snap[0] = N

            for step in range(n_steps):
                rhs = (I - 0.5 * dt * A).dot(N) + dt * rhs_const
                rhs[0]  = 0.0   # re-impose Neumann BC on RHS
                rhs[-1] = 0.0
                N = np.maximum(spsolve(lhs, rhs), 0.0)
                snap[step + 1] = N

            history[sb] = snap

        return t_axis, history

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    def get_sheet_densities(self, spatial_populations):
        """
        Integrate spatial carrier profiles to get 2D sheet densities.

        Parameters
        ----------
        spatial_populations : dict  {subband: np.ndarray (nz,) [m⁻³]}

        Returns
        -------
        sheet_densities : dict  {subband: float [m⁻²]}
        """
        return {
            sb: float(np.trapezoid(N_z, self.z))
            for sb, N_z in spatial_populations.items()
        }

    def get_peak_densities(self, spatial_populations):
        """
        Return the peak volumetric carrier density per subband.

        Returns
        -------
        dict  {subband: float [m⁻³]}
        """
        return {sb: float(np.max(N_z))
                for sb, N_z in spatial_populations.items()}