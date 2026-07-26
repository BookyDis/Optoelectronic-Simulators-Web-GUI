# further addition as requested by the supervisor
#
#   SegregationCalculator.py
#
#   Models dopant/alloy segregation at heterointerfaces during MBE growth.
#   Segregation causes the intended sharp alloy step x(z) to become a
#   smoothed, asymmetric exponential profile — one side of each interface
#   is smeared with a characteristic length λ (the segregation length).
#
#   Two standard models are provided:
#
#   1. Exponential (Muraki) model  [most widely used for MBE]
#      At a rising interface (well→barrier, x going up):
#          x_seg(z) = x_nominal + (x_before - x_nominal) · exp(-(z - z_if) / λ)
#      At a falling interface (barrier→well, x going down):
#          x_seg(z) = x_nominal + (x_before - x_nominal) · exp(-(z - z_if) / λ)
#      where z_if is the position of the nominal interface and λ [Å] is the
#      segregation length for that species.
#
#   2. Complementary-error-function (Gaussian diffusion) model
#      Appropriate when interdiffusion (not surface segregation) dominates:
#          x_seg(z) = x_nominal · erfc((z - z_if) / (√2 · σ))
#      where σ [Å] is the interface width parameter (≈ diffusion length).
#
#   Usage
#   -----
#   from src.SegregationModel import SegregationModel
#   from src.Composition import Composition
#
#   C     = Composition.from_array([[200, 0.3], [150, 0.0], [200, 0.3]])
#   model = SegregationModel(C, dz=1.0)
#
#   # Exponential segregation, λ = 20 Å
#   x_seg = model.apply_exponential(lam=20.0)
#
#   # Gaussian/erfc diffusion, σ = 10 Å
#   x_erf = model.apply_erfc(sigma=10.0)
#
#   # Build a modified Composition object to drop into Grid
#   C_seg = model.to_composition(x_seg)
#

import numpy as np
from scipy.special import erfc
from src.Composition import Composition
from src import ConstAndScales


class SegregationCalculator:
    """
    Interface-segregation / interdiffusion smearing of an alloy profile.

    Parameters
    ----------
    composition : Composition
        The ideal (sharp-interface) layer structure.
    dz : float
        Grid spacing [Å] — controls the resolution of the smeared profile.
    """

    def __init__(self, composition, dz=1.0):
        self.composition = composition
        self.dz          = float(dz)

        # Build the ideal step profile on a fine grid (same as Grid does)
        thicknesses = np.asarray(composition.get_layer_thickness(), dtype=np.float64)
        alloys      = np.asarray(composition.get_alloy_profile(),   dtype=np.float64)

        total_z = np.sum(thicknesses)
        self.z  = np.arange(0.0, total_z + dz, dz)   # [Å]
        self.nz = len(self.z)

        # Assign nominal alloy fraction at each grid point (step profile)
        self.x_nominal = np.empty(self.nz)
        layer     = 0
        cum_thick = thicknesses[0]
        for k in range(self.nz):
            if self.z[k] >= cum_thick and layer < len(thicknesses) - 1:
                layer    += 1
                cum_thick += thicknesses[layer]
            self.x_nominal[k] = alloys[layer]

        # Locate interface positions [Å] — where x_nominal changes
        self._interface_positions, self._interface_directions = \
            self._find_interfaces()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _find_interfaces(self):
        """
        Returns arrays of interface positions [Å] and their directions.
        direction > 0: x rises  (well→barrier, e.g. 0→0.3)
        direction < 0: x falls  (barrier→well, e.g. 0.3→0)
        """
        positions  = []
        directions = []
        for k in range(1, self.nz):
            dx = self.x_nominal[k] - self.x_nominal[k - 1]
            if abs(dx) > 1e-10:
                positions.append(self.z[k])   # [Å]
                directions.append(np.sign(dx))
        return np.asarray(positions), np.asarray(directions)

    # ------------------------------------------------------------------
    # Public models
    # ------------------------------------------------------------------

    def apply_exponential(self, lam, asymmetric=True):
        """
        Muraki exponential segregation model.

        Segregation smears the *leading* edge of each interface over a
        characteristic length λ [Å] in the growth direction (+z).

        For a rising interface (x: low→high) the tail leaks forward:
            x(z) = x_high - (x_high - x_low) · exp(-(z - z_if) / λ),  z > z_if

        For a falling interface (x: high→low) the tail leaks forward:
            x(z) = x_low  + (x_high - x_low) · exp(-(z - z_if) / λ),  z > z_if

        Parameters
        ----------
        lam         : float  Segregation length [Å].  Typical: 10–50 Å for MBE.
        asymmetric  : bool   If True (default), only the leading (post-interface)
                             edge is smeared (one-sided exponential), matching
                             physical MBE segregation.  If False, both sides are
                             smeared symmetrically.

        Returns
        -------
        x_seg : np.ndarray  shape (nz,)  Smeared alloy fraction profile.
        """
        if lam <= 0:
            return self.x_nominal.copy()

        x_seg = self.x_nominal.copy()

        for z_if, direction in zip(self._interface_positions,
                                   self._interface_directions):
            # Value just before and just after the interface
            k_if = np.searchsorted(self.z, z_if)
            x_before = self.x_nominal[max(k_if - 1, 0)]
            x_after  = self.x_nominal[min(k_if, self.nz - 1)]
            delta_x  = x_after - x_before   # signed step

            # Apply exponential tail on the post-interface side
            mask_post = self.z >= z_if
            x_seg[mask_post] -= delta_x * np.exp(
                -(self.z[mask_post] - z_if) / lam
            )

            if not asymmetric:
                # Symmetric: also smear pre-interface side
                mask_pre = self.z < z_if
                x_seg[mask_pre] += delta_x * np.exp(
                    -(z_if - self.z[mask_pre]) / lam
                )

        # Clamp to [0, 1] — numerical tails can slightly overshoot
        return np.clip(x_seg, 0.0, 1.0)

    def apply_erfc(self, sigma):
        """
        Complementary-error-function (Gaussian diffusion) interface model.

        Models thermal interdiffusion rather than surface segregation.
        Each interface is replaced by:

            x(z) = x_low + (x_high - x_low)/2 · erfc(-(z - z_if) / (√2 · σ))

        which is symmetric and appropriate for post-growth annealing or
        when growth-temperature diffusion dominates over surface segregation.

        Parameters
        ----------
        sigma : float  Interface width / diffusion length [Å].
                       Typical values: 5–30 Å.

        Returns
        -------
        x_erf : np.ndarray  shape (nz,)  Smeared alloy fraction profile.
        """
        if sigma <= 0:
            return self.x_nominal.copy()

        x_erf = np.zeros(self.nz)
        thicknesses = np.asarray(self.composition.get_layer_thickness())
        alloys      = np.asarray(self.composition.get_alloy_profile())

        # Reconstruct interface positions cleanly from layer boundaries
        cum = np.concatenate(([0.0], np.cumsum(thicknesses)))

        # Start from the first layer value, then accumulate erfc steps
        x_erf[:] = alloys[0]
        for seg in range(1, len(alloys)):
            z_if    = cum[seg]                    # interface position [Å]
            delta_x = alloys[seg] - alloys[seg - 1]

            # erfc argument: negative z means we're left of the interface
            arg = -(self.z - z_if) / (np.sqrt(2.0) * sigma)
            x_erf += delta_x * 0.5 * erfc(arg)

        return np.clip(x_erf, 0.0, 1.0)

    def apply_combined(self, lam, sigma):
        """
        Apply both exponential segregation AND erfc diffusion.

        In practice, MBE structures can have both surface-segregation
        (asymmetric, captured by `lam`) and some thermal interdiffusion
        (symmetric, captured by `sigma`).  The two effects are applied
        sequentially: erfc first, then exponential segregation on top.

        Parameters
        ----------
        lam   : float  Exponential segregation length [Å].
        sigma : float  Gaussian diffusion width [Å].

        Returns
        -------
        x_combined : np.ndarray  shape (nz,)
        """
        # Start from erfc-smoothed profile, then apply exponential segregation
        # We temporarily overwrite x_nominal to chain the two operations
        orig = self.x_nominal.copy()
        self.x_nominal = self.apply_erfc(sigma)
        self._interface_positions, self._interface_directions = \
            self._find_interfaces()
        x_combined = self.apply_exponential(lam)

        # Restore original
        self.x_nominal = orig
        self._interface_positions, self._interface_directions = \
            self._find_interfaces()
        return x_combined

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def to_composition(self, x_smeared):
        """
        Wrap a smeared alloy profile back into a Composition object that
        Grid can consume directly.

        The returned Composition has one layer per grid point (i.e. dz-thick
        layers), effectively making it a finely-sampled alloy profile rather
        than a block-layer structure.  Grid handles this naturally.

        Parameters
        ----------
        x_smeared : np.ndarray  shape (nz,)  Output of apply_* methods.

        Returns
        -------
        Composition
        """
        thicknesses = np.full(self.nz, self.dz)   # [Å], one layer per point
        return Composition(thicknesses.tolist(), x_smeared.tolist())

    def get_z(self):
        """Return the z-axis [Å] used by this model."""
        return self.z.copy()

    def get_nominal_profile(self):
        """Return the original sharp-interface alloy profile."""
        return self.x_nominal.copy()

    def compare_profiles(self, x_smeared, label="Smeared"):
        """
        Return a dict suitable for plotting both profiles together.

        Returns
        -------
        dict with keys 'z', 'x_nominal', 'x_smeared', 'label'
        """
        return {
            "z"         : self.z.tolist(),
            "x_nominal" : self.x_nominal.tolist(),
            "x_smeared" : x_smeared.tolist(),
            "label"     : label,
        }