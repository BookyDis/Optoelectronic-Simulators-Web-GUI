// Frontend logic for Quantum Well Simulator

let potentialChart = null;
let wavefunctionChart = null;
let boundStateChart = null;
let energyDiffChart = null;
let qclChart = null;
let structSweepEChart = null;
let structSweepDChart = null;
let structSweepFChart = null;
let currentResults = null;
let currentSweepParam = 'none'; // 'none' | 'width' | 'molar' 

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('simulatorForm').addEventListener('submit', handleSubmit);
    document.getElementById('material').addEventListener('change', loadMaterialInfo);

    const sweepKCheckbox = document.getElementById('sweepKCheckbox');
    if (sweepKCheckbox) sweepKCheckbox.addEventListener('change', toggleSweepKMode);

    const transitionBtn = document.getElementById('runTransitionBtn');
    if (transitionBtn) transitionBtn.addEventListener('click', runTransition);

    document.querySelectorAll('#sweepParamToggle .param-toggle-btn').forEach(btn => {
        btn.addEventListener('click', () => setSweepParamMode(btn.dataset.value));
    });

    const transitionStructureSweepBtn = document.getElementById('runTransitionStructureSweepBtn');
    if (transitionStructureSweepBtn) transitionStructureSweepBtn.addEventListener('click', runTransitionStructureSweep);


    // Inside DOMContentLoaded in app.js:
    document.getElementById('k_start').disabled = true;
    document.getElementById('k_end').disabled = true;
    document.getElementById('k_step').disabled = true;
});

// function for switching between Quantum Well simulator and Transition calculator  ────────────────────────────────────────────────────
function show(elementID) {
    const ele = document.getElementById(elementID);
    if (!ele) {
        alert("no such element");
        return;
    }

    const pages = document.getElementsByClassName('divSimulator');
    for (let i = 0; i < pages.length; i++) {
        pages[i].style.display = 'none';
    }

    ele.style.display = 'block';

    // --- Toggle page-specific controls ---
    const sweepKGroup = document.getElementById('sweepKGroup');
    const energyLevelDiffCard = document.getElementById('energyLevelDiffCard');
    const structureSweepCard = document.getElementById('structureSweepCard');
    const qwSubmitGroup = document.getElementById('qwSubmitGroup');
    const transitionSubmitGroup = document.getElementById('transitionSubmitGroup');
    const isTransition = elementID === 'Simulatortransition';

    if (sweepKGroup) sweepKGroup.classList.toggle('hidden', !isTransition);
    if (energyLevelDiffCard) energyLevelDiffCard.classList.toggle('hidden', !isTransition);
    if (structureSweepCard) structureSweepCard.classList.toggle('hidden', !isTransition);
    if (qwSubmitGroup) qwSubmitGroup.classList.toggle('hidden', isTransition);
    if (transitionSubmitGroup) transitionSubmitGroup.classList.toggle('hidden', !isTransition);

    // --- Highlight the active page-switch pill ---
    document.getElementById('qwPageBtn')?.classList.toggle('active', !isTransition);
    document.getElementById('transitionPageBtn')?.classList.toggle('active', isTransition);

}

// ── Sweep-K toggle: swap electric field single input <-> K start/end/step ──

function toggleSweepKMode() {
    const checked = document.getElementById('sweepKCheckbox').checked;

    const toggleLabel = document.getElementById('sweepKToggleLabel');
    if (toggleLabel) toggleLabel.classList.toggle('active', checked);

    document.getElementById('electricFieldSingleGroup').classList.toggle('hidden', checked);
    document.getElementById('electricFieldSweepGroup').classList.toggle('hidden', !checked);

    // Enable/disable inputs so hidden controls aren't validated
    document.getElementById('k_start').disabled = !checked;
    document.getElementById('k_end').disabled = !checked;
    document.getElementById('k_step').disabled = !checked;
}

// ── Structure-parameter sweep mode (Sweep Well Width / Sweep Molar Content) ──
const SWEEP_PARAM_PRESETS = {
    width: { start: 50, end: 150, step: 10 },
    molar: { start: 0.00, end: 0.50, step: 0.10 },
};

function setSweepParamMode(mode) {
    currentSweepParam = mode;

    document.querySelectorAll('#sweepParamToggle .param-toggle-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.value === mode);
    });

    const isSweeping = mode !== 'none';
    const rangeGroup = document.getElementById('structureSweepRangeGroup');
    const rangeLabel = document.getElementById('structureSweepRangeLabel');
    const subLabel = document.getElementById('structureSweepSubLabel');

    if (rangeGroup) rangeGroup.classList.toggle('hidden', !isSweeping);
    if (rangeLabel) rangeLabel.textContent = mode === 'molar' ? 'Set ranges for height' : 'Set ranges for width';
    if (subLabel) subLabel.textContent = mode === 'molar' ? 'Height:' : 'Width:';

    if (isSweeping && SWEEP_PARAM_PRESETS[mode]) {
        document.getElementById('sweepParamStart').value = SWEEP_PARAM_PRESETS[mode].start;
        document.getElementById('sweepParamEnd').value = SWEEP_PARAM_PRESETS[mode].end;
        document.getElementById('sweepParamStep').value = SWEEP_PARAM_PRESETS[mode].step;
    }

    
    document.getElementById('transitionStructureSweepControls')?.classList.toggle('hidden', !isSweeping);
    document.getElementById('transitionSingleControls')?.classList.toggle('hidden', isSweeping);

    if (!isSweeping) {
        document.getElementById('transitionStructureSweepCharts')?.classList.add('hidden');
    }
}

async function runTransitionStructureSweep() {
    clearTransitionMessages();

    const state_i = parseInt(document.getElementById('state_i').value, 10);
    const state_j = parseInt(document.getElementById('state_j').value, 10);
    if (!state_i || !state_j || state_i === state_j) {
        showTransitionMessage('Choose two different state indices for i and j.', 'error');
        return;
    }

    const sweep_start = parseFloat(document.getElementById('sweepParamStart').value);
    const sweep_end = parseFloat(document.getElementById('sweepParamEnd').value);
    const sweep_step = parseFloat(document.getElementById('sweepParamStep').value);
    if (isNaN(sweep_start) || isNaN(sweep_end) || isNaN(sweep_step) || sweep_step <= 0 || sweep_end < sweep_start) {
        showTransitionMessage('Check the sweep range: End must be ≥ Start, and Step must be > 0.', 'error');
        return;
    }

    // "Sweep K?" is an optional modifier: ticked -> re-run the structure
    const sweepKCheckbox = document.getElementById('sweepKCheckbox');
    const sweep_k = !!(sweepKCheckbox && sweepKCheckbox.checked);

    const payload = {
        ...getTransitionStructurePayload(),
        state_i, state_j,
        sweep_param: currentSweepParam,
        sweep_start, sweep_end, sweep_step,
        sweep_k,
    };

    if (sweep_k) {
        const k_start = parseFloat(document.getElementById('k_start').value);
        const k_end = parseFloat(document.getElementById('k_end').value);
        const k_step = parseFloat(document.getElementById('k_step').value);
        if (isNaN(k_start) || isNaN(k_end) || isNaN(k_step) || k_step <= 0 || k_end < k_start) {
            showTransitionMessage('Check the K sweep range: K end must be ≥ K start, and K step must be > 0.', 'error');
            return;
        }
        payload.k_start = k_start;
        payload.k_end = k_end;
        payload.k_step = k_step;
    } else {
        payload.electric_field = document.getElementById('electric_field').value;
    }

    setSpinnerActive('transitionStructureSweepSpinner', true);
    document.getElementById('transitionStructureSweepLoadingLabel').classList.remove('hidden');
    document.getElementById('runTransitionStructureSweepBtn').disabled = true;

    try {
        const response = await fetch('/api/transition-structure-sweep', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) {
            const text = await response.text();
            throw new Error(`Server error ${response.status}: ${text.slice(0, 200)}`);
        }
        const data = await response.json();

        if (data.status === 'success') {
            displayTransitionStructureSweepCharts(data.series, data.state_i, data.state_j, data.sweep_param, data.sweep_k);
            const nLines = data.series.length;
            const nPoints = data.series.reduce((sum, s) => sum + s.x_vals.length, 0);
            showTransitionMessage(
                sweep_k
                    ? `Sweep completed — ${nLines} K value(s), ${nPoints} points total.`
                    : `Sweep completed — ${nPoints} points.`,
                'success'
            );
        } else {
            showTransitionMessage(data.message, 'error');
        }
    } catch (err) {
        showTransitionMessage(`Error: ${err.message}`, 'error');
        console.error('Structure sweep error:', err);
    } finally {
        setSpinnerActive('transitionStructureSweepSpinner', false);
        document.getElementById('transitionStructureSweepLoadingLabel').classList.add('hidden');
        document.getElementById('runTransitionStructureSweepBtn').disabled = false;
    }
}

// Distinct colours so each K line is visually distinguishable when Sweep K
// is on. Falls back to the first colour when there's just a single line.
const SWEEP_LINE_COLORS = [
    'rgb(102,126,234)', 'rgb(237,100,166)', 'rgb(56,178,172)', 'rgb(237,137,54)',
    'rgb(72,187,120)', 'rgb(159,122,234)', 'rgb(245,101,101)', 'rgb(66,153,225)',
    'rgb(214,158,46)', 'rgb(129,140,248)',
];

function displayTransitionStructureSweepCharts(series, i, j, sweepParam, sweepK) {
    const xLabel = sweepParam === 'molar' ? 'Molar Content' : 'Width [Å]';
    const xTitle = sweepParam === 'molar' ? 'Molar Content' : 'Well Width';

    const eTitleEl = document.getElementById('structSweepEChartTitle');
    const dTitleEl = document.getElementById('structSweepDChartTitle');
    const fTitleEl = document.getElementById('structSweepFChartTitle');
    if (eTitleEl) eTitleEl.textContent = `Energy difference vs ${xTitle}`;
    if (dTitleEl) dTitleEl.textContent = `Dipole Moments vs ${xTitle}`;
    if (fTitleEl) fTitleEl.textContent = `Oscillator Strength vs ${xTitle}`;

    
    const makeDatasets = (key) => series.map((s, idx) => ({
        label: s.k_kVcm !== undefined ? `K = ${s.k_kVcm.toFixed(1)}` : 'Electric Field',
        data: s.x_vals.map((x, pidx) => ({ x: x, y: Math.abs(s[key][pidx]) })),
        borderColor: SWEEP_LINE_COLORS[idx % SWEEP_LINE_COLORS.length],
        borderWidth: 2, 
        pointRadius: 3, 
        tension: 0, 
        fill: false,
    }));

    const eCtx = document.getElementById('structSweepEChart').getContext('2d');
    if (structSweepEChart) structSweepEChart.destroy();
    structSweepEChart = new Chart(eCtx, {
        type: 'line',
        data: { datasets: makeDatasets('E_ij_meV') },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: true },
                title: { display: true, text: `Energy difference vs ${xTitle}` },
                zoom: getZoomOptions('xy'),
            },
            scales: {
                x: { type: 'linear', title: { display: true, text: xLabel } },
                y: { title: { display: true, text: 'Energy [meV]' } },
            },
        },
    });

    const dCtx = document.getElementById('structSweepDChart').getContext('2d');
    if (structSweepDChart) structSweepDChart.destroy();
    structSweepDChart = new Chart(dCtx, {
        type: 'line',
        data: { datasets: makeDatasets('d_ij_nm') },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: true },
                title: { display: true, text: `Dipole Moments vs ${xTitle}` },
                zoom: getZoomOptions('xy'),
            },
            scales: {
                x: { type: 'linear', title: { display: true, text: xLabel } },
                y: { title: { display: true, text: 'Dipole Moment [e nm]' } },
            },
        },
    });

    const fCtx = document.getElementById('structSweepFChart').getContext('2d');
    if (structSweepFChart) structSweepFChart.destroy();
    structSweepFChart = new Chart(fCtx, {
        type: 'line',
        data: { datasets: makeDatasets('f_ij') },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: true },
                title: { display: true, text: `Oscillator Strength vs ${xTitle}` },
                zoom: getZoomOptions('xy'),
            },
            scales: {
                x: { type: 'linear', title: { display: true, text: xLabel } },
                y: { title: { display: true, text: 'Oscillator Strength' } },
            },
        },
    });

    document.getElementById('transitionStructureSweepCharts').classList.remove('hidden');
}
// Function to add a new empty row to the grid
function addRow() {
    const tbody = document.getElementById('layerTableBody');
    const row = document.createElement('tr');

    row.innerHTML = `
    <td><input type="number" step="any" class="thickness" placeholder="200" required></td>
    <td><input type="number" step="any" class="alloy" placeholder="0.15" required></td>
    <td><button type="button" class="remove-btn" onclick="removeRow(this)">✕</button></td>
  `;

    tbody.appendChild(row);
}

//  Heterostructure grid function helper ────────────────────────────────────────────────────

// Function to remove a row
function removeRow(button) {
    const row = button.closest('tr');
    // Optional: keep at least one row
    if (document.querySelectorAll('#layerTableBody tr').length > 1) {
        row.remove();
    }
}

// Function to collect table data into your original format ("200 0.15 200 0.0 ...")
function getSequenceString() {
    const rows = document.querySelectorAll('#layerTableBody tr');
    const pairs = [];

    rows.forEach(row => {
        const thickness = row.querySelector('.thickness').value;
        const alloy = row.querySelector('.alloy').value;
        if (thickness !== "" && alloy !== "") {
            pairs.push(`${thickness} ${alloy}`);
        }
    });

    return pairs.join(' ');
}

// ── Download function  ────────────────────────────────────────────────────

function downloadChart(canvasId, filename) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    // Draw onto a white-background offscreen canvas so the PNG isn't transparent
    const offscreen = document.createElement('canvas');
    offscreen.width = canvas.width;
    offscreen.height = canvas.height;
    const octx = offscreen.getContext('2d');
    octx.fillStyle = '#ffffff';
    octx.fillRect(0, 0, offscreen.width, offscreen.height);
    octx.drawImage(canvas, 0, 0);

    const link = document.createElement('a');
    link.download = `${filename}.png`;
    link.href = offscreen.toDataURL('image/png');
    link.click();
}

// ── Main simulation submit ────────────────────────────────────────────────────

// Helper to extract table row values into a space-separated string
function getLayerStructureString() {
    const rows = document.querySelectorAll('#layerTableBody tr');
    const tokens = [];

    rows.forEach(row => {
        const thickness = row.querySelector('.thickness')?.value.trim();
        const alloy = row.querySelector('.alloy')?.value.trim();

        if (thickness && alloy) {
            tokens.push(thickness, alloy);
        }
    });

    return tokens.join(' ');
}

async function handleSubmit(e) {
    e.preventDefault();
    clearMessages();
    showLoadingSpinner(true);

    const formData = {
        material: document.getElementById('material').value,
        solver: document.getElementById('solver').value,
        subband_model: document.getElementById('subband_model').value,
        layer_structure: getLayerStructureString(),
        electric_field: document.getElementById('electric_field').value,
        grid_spacing: document.getElementById('grid_spacing').value,
        num_states: document.getElementById('num_states').value,
        padding: document.getElementById('padding').value,
    };

    try {
        const response = await fetch('/api/simulate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData),
        });

        if (!response.ok) {
            const text = await response.text();
            throw new Error(`Server error ${response.status}: ${text.slice(0, 120)}`);
        }

        const data = await response.json();

        if (data.status === 'success') {
            currentResults = data.results;
            displayResults(data);
            showSuccessMessage(data.message);
            document.getElementById('energyLevelsSection')
                ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } else {
            showErrorMessage(data.message || 'Simulation failed');
        }
    } catch (err) {
        showErrorMessage(`Error: ${err.message}`);
        console.error('Submission error:', err);
    } finally {
        showLoadingSpinner(false);
    }
}


// ── Display all results ───────────────────────────────────────────────────────

function displayResults(data) {
    const r = data.results;
    displayEnergyLevels(r.energies);
    displayPotentialChart(r.z_grid, r.potential, r.wavefunctions, r.energies);
    displayWavefunctionChart(r.z_grid, r.wavefunctions, r.energies);
    displayBoundStateEnergies(r.energies);
    displayEnergyDifferences(r.energies);
    displayTwoQCLPeriods(r.z_grid, r.potential, r.wavefunctions, r.energies);
    document.getElementById('energyLevelsSection').classList.remove('hidden');
    document.getElementById('chartsSection').classList.remove('hidden');
}

// ── Energy table ──────────────────────────────────────────────────────────────

function displayEnergyLevels(energies) {
    const tbody = document.getElementById('energyTableBody');
    tbody.innerHTML = '';
    energies.forEach((E, i) => {
        const row = document.createElement('tr');
        row.innerHTML = `<td>${i + 1}</td><td>${E.toFixed(6)}</td><td>${(E * 1000).toFixed(3)}</td>`;
        tbody.appendChild(row);
    });
}

// ── Bandstructure + |ψ|² overlay ─────────────────────────────────────────────
function displayPotentialChart(zGrid, potential, wavefunctions, energies) {
    const ctx = document.getElementById('potentialChart').getContext('2d');
    if (typeof potentialChart !== 'undefined' && potentialChart) {
        potentialChart.destroy();
    }

    const wfColors = ['rgb(54,162,235)', 'rgb(255,99,132)', 'rgb(75,192,192)', 'rgb(255,206,86)', 'rgb(153,102,255)'];
    const WF_SCALE = 1000;

    const datasets = [{
        label: 'V(z)',
        data: zGrid.map((z, i) => ({ x: z, y: potential[i] * 1000 })),
        borderColor: 'rgb(100,149,237)', backgroundColor: 'rgba(100,149,237,0.1)',
        borderWidth: 3, pointRadius: 0, tension: 0, fill: true,
    }];

    wavefunctions.forEach((wf, idx) => {
        const E_meV = energies[idx] * 1000;
        datasets.push({
            label: `E${idx + 1} = ${E_meV.toFixed(2)} meV`,
            data: zGrid.map((z, i) => ({ x: z, y: WF_SCALE * wf[i] * wf[i] + E_meV })),
            borderColor: wfColors[idx % wfColors.length],
            borderWidth: 2, pointRadius: 0, tension: 0.3, fill: false,
        });
    });

    potentialChart = new Chart(ctx, {
        type: 'line',
        data: { datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: true },
                title: { display: true, text: 'Bandstructure Potential Profile' },
                zoom: getZoomOptions('xy')
            },
            scales: {
                x: { type: 'linear', title: { display: true, text: 'Position z (Å)' } },
                y: { title: { display: true, text: 'Energy (meV)' } },
            },
        },
    });
}

// ── Wavefunction amplitudes ───────────────────────────────────────────────────

function displayWavefunctionChart(zGrid, wavefunctions, energies) {
    const ctx = document.getElementById('wavefunctionChart').getContext('2d');
    if (wavefunctionChart) wavefunctionChart.destroy();

    const colors = ['rgb(255,99,132)', 'rgb(54,162,235)', 'rgb(75,192,192)', 'rgb(255,206,86)'];

    const datasets = wavefunctions.map((wf, idx) => ({
        label: `ψ${idx + 1}  (E = ${(energies[idx] * 1000).toFixed(2)} meV)`,
        data: Array.from(wf),
        borderColor: colors[idx % colors.length],
        backgroundColor: colors[idx % colors.length].replace('rgb', 'rgba').replace(')', ',0.1)'),
        tension: 0.3, borderWidth: 2, pointRadius: 0,
    }));

    wavefunctionChart = new Chart(ctx, {
        type: 'line',
        data: { labels: zGrid.map(z => z.toFixed(2)), datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { 
            legend: { display: true }, 
            title: { display: true, text: 'Quantum Well Wavefunctions' } ,
            zoom: getZoomOptions('xy')
        },
            scales: {
                x: { title: { display: true, text: 'Position z (Å)' } },
                y: { title: { display: true, text: 'Wavefunction Amplitude' } },
            },
        },
    });
}

// ── Bound state stem plot ─────────────────────────────────────────────────────

function displayBoundStateEnergies(energies) {
    const ctx = document.getElementById('boundStateEnergiesChart').getContext('2d');
    if (boundStateChart) boundStateChart.destroy();

    const stemPoints = [], markerPoints = [];
    energies.forEach((E, i) => {
        stemPoints.push({ x: i + 1, y: 0 }, { x: i + 1, y: E * 1000 }, { x: i + 1, y: null });
        markerPoints.push({ x: i + 1, y: E * 1000 });
    });

    boundStateChart = new Chart(ctx, {
    type: 'line',
    data: {
        datasets: [
            { data: stemPoints, borderColor: 'rgb(70,90,230)', borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0, spanGaps: false },
            { type: 'scatter', data: markerPoints, pointStyle: 'circle', pointRadius: 8, pointBorderColor: 'rgb(70,90,230)', pointBackgroundColor: 'rgba(0,0,0,0)', pointBorderWidth: 2 },
        ]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false, 
        plugins: { 
            legend: { display: false }, 
            title: { display: true, text: 'Bound State Energies' },
            zoom: getZoomOptions('xy') 
        },
        scales: {
            x: { type: 'linear', title: { display: true, text: 'State #' } },
            y: { title: { display: true, text: 'E (meV)' }, beginAtZero: true },
        },
    },
});
}

// ── Energy differences (THz) ──────────────────────────────────────────────────

function displayEnergyDifferences(energies) {
    const ctx = document.getElementById('energyDifferencesChart').getContext('2d');
    if (energyDiffChart) energyDiffChart.destroy();

    if (energies.length < 2) return;

    const freqsTHz = [], tickLabels = [];
    for (let j = 0; j < energies.length - 1; j++) {
        freqsTHz.push((energies[j + 1] - energies[j]) * 1000 / 4.1356);
        tickLabels.push(`${j + 1}→${j + 2}`);
    }

    const stemPoints = [], markerPoints = [];
    freqsTHz.forEach((f, j) => {
        stemPoints.push({ x: j, y: 0 }, { x: j, y: f }, { x: j, y: null });
        markerPoints.push({ x: j, y: f });
    });

    energyDiffChart = new Chart(ctx, {
        type: 'line',
        data: {
            datasets: [
                { data: stemPoints, borderColor: 'rgb(220,53,69)', borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0, spanGaps: false },
                { type: 'scatter', data: markerPoints, pointStyle: 'circle', pointRadius: 8, pointBorderColor: 'rgb(220,53,69)', pointBackgroundColor: 'rgba(0,0,0,0)', pointBorderWidth: 2 },
            ]
        },
        options: {
            responsive: true,
            plugins: { legend: { display: false }, title: { display: true, text: 'Energy Differences' }, 
            maintainAspectRatio: false, 
            zoom: getZoomOptions('xy')
        },
            scales: {
                x: {
                    type: 'linear', title: { display: true, text: 'Transition' },
                    ticks: { stepSize: 1, callback: v => tickLabels[Math.round(v)] ?? '' }
                },
                y: { title: { display: true, text: 'f (THz)' } },
            },
        },
    });
}

// ── Two QCL periods ───────────────────────────────────────────────────────────

function displayTwoQCLPeriods(zGrid, potential, wavefunctions, energies) {
    const ctx = document.getElementById('qclPeriodsChart').getContext('2d');
    if (qclChart) qclChart.destroy();

    const n = zGrid.length;
    const Lper = zGrid[n - 1] - zGrid[0];
    const dropMeV = (potential[0] - potential[n - 1]) * 1000;
    const periodColors = ['rgb(54,162,235)', 'rgb(220,53,69)'];
    const wfColors = ['rgb(75,192,192)', 'rgb(255,159,64)', 'rgb(153,102,255)', 'rgb(255,206,86)'];
    const datasets = [];

    for (let p = 0; p < 2; p++) {
        const shift = (p - 1) * Lper;
        const off = dropMeV * (1 - p);
        datasets.push({
            label: p === 0 ? 'V(z)' : undefined,
            data: zGrid.map((z, i) => ({ x: z + shift, y: potential[i] * 1000 + off })),
            borderColor: periodColors[p], borderWidth: 3, pointRadius: 0, tension: 0, fill: false,
        });
        wavefunctions.forEach((wf, idx) => {
            datasets.push({
                label: p === 0 ? `E${idx + 1} = ${(energies[idx] * 1000).toFixed(2)} meV` : undefined,
                data: zGrid.map((z, i) => ({ x: z + shift, y: 1000 * wf[i] * wf[i] + energies[idx] * 1000 + off })),
                borderColor: wfColors[idx % wfColors.length],
                borderWidth: 2, pointRadius: 0, tension: 0.3, fill: false,
            });
        });
    }

    qclChart = new Chart(ctx, {
        type: 'line', data: { datasets },
        options: {
            responsive: true,
            plugins: { legend: { display: true }, title: { display: true, text: 'Two QCL Periods' },
            maintainAspectRatio: false, 
            zoom: getZoomOptions('xy')
        
        },
            scales: {
                x: { type: 'linear', title: { display: true, text: 'z (Å)' } },
                y: { title: { display: true, text: 'V (meV)' } },
            },
        },
    });
}


function renderTransitionTable(transitions) {
    const tbody = document.getElementById('transitionTableBody');
    tbody.innerHTML = '';
    transitions.forEach(t => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${t.pair[0]} → ${t.pair[1]}</td>
            <td>${t.E_ij_meV.toFixed(2)}</td>
            <td>${t.f_ij.toFixed(5)}</td>
            <td>${t.d_ij_nm.toFixed(3)}</td>
            <td>${t.gamma_meV !== null ? t.gamma_meV.toFixed(1) : '—'}</td>
            <td>${t.dN_m2.toExponential(2)}</td>
            <td>${t.peak_alpha_cm !== null ? t.peak_alpha_cm.toFixed(1) : '—'}</td>`;
        tbody.appendChild(row);
    });
    document.getElementById('transitionTableSection').classList.remove('hidden');
}



// ── Transition Calculator ────────────────────────────────────────────────────

function getTransitionStructurePayload() {
    return {
        material: document.getElementById('material').value,
        solver: document.getElementById('solver').value,
        subband_model: document.getElementById('subband_model').value,
        layer_structure: getLayerStructureString(),
        grid_spacing: document.getElementById('grid_spacing').value,
        num_states: document.getElementById('num_states').value,
        padding: document.getElementById('padding').value,
    };
}


async function runTransition() {
    const btn = document.getElementById('runTransitionBtn');
    if (!btn || btn.disabled) return;
}

function showTransitionMessage(msg, type) {
    const id = type === 'error' ? 'transitionError' : 'transitionSuccess';
    const el = document.getElementById(id);
    el.textContent = msg;
    el.classList.remove('hidden');
}

function clearTransitionMessages() {
    document.getElementById('transitionError').classList.add('hidden');
    document.getElementById('transitionSuccess').classList.add('hidden');
}

// ── Material info ─────────────────────────────────────────────────────────────

async function loadMaterialInfo(e) {
    const material = e.target.value;
    if (!material) { document.getElementById('materialInfoSection').classList.add('hidden'); return; }
    try {
        const response = await fetch(`/api/material-info?material=${material}`);
        if (!response.ok) return;
        const data = await response.json();
        if (data.status === 'success') {
            document.getElementById('info-bandgap-well').textContent = data.band_gap.well.toFixed(4) + ' eV';
            document.getElementById('info-bandgap-barrier').textContent = data.band_gap.barrier.toFixed(4) + ' eV';
            document.getElementById('info-mass-well').textContent = data.effective_mass.well.toFixed(4) + ' m₀';
            document.getElementById('info-mass-barrier').textContent = data.effective_mass.barrier.toFixed(4) + ' m₀';
            document.getElementById('info-kane-well').textContent = data.kane_parameter.well.toFixed(4) + ' eV·Å²';
            document.getElementById('info-kane-barrier').textContent = data.kane_parameter.barrier.toFixed(4) + ' eV·Å²';
            document.getElementById('materialInfoSection').classList.remove('hidden');
        }
    } catch (err) { console.error('Material info error:', err); }
}

// ── Utility helpers ───────────────────────────────────────────────────────────

function setSpinnerActive(id, show) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.toggle('hidden', !show);
}

function showAbsorptionMsg(msg, type) {
    const id = type === 'error' ? 'absorptionError' : 'absorptionSuccess';
    const el = document.getElementById(id);
    el.textContent = msg;
    el.classList.remove('hidden');
}

function showDiffusionMessage(msg, type) {
    const id = type === 'error' ? 'diffusionError' : 'diffusionSuccess';
    const el = document.getElementById(id);
    el.textContent = msg;
    el.classList.remove('hidden');
}

function clearDiffusionMessages() {
    document.getElementById('diffusionError').classList.add('hidden');
    document.getElementById('diffusionSuccess').classList.add('hidden');
}

function showSegregationMessage(msg, type) {
    const id = type === 'error' ? 'segregationError' : 'segregationSuccess';
    const el = document.getElementById(id);
    el.textContent = msg;
    el.classList.remove('hidden');
}

function clearSegregationMessages() {
    document.getElementById('segregationError').classList.add('hidden');
    document.getElementById('segregationSuccess').classList.add('hidden');
}

function showLoadingSpinner(show) {
    const spinner = document.getElementById('loadingSpinner');
    const label = document.getElementById('loadingLabel');
    const btn = document.getElementById('submitBtn');
    spinner.classList.toggle('hidden', !show);
    label.classList.toggle('hidden', !show);
    btn.disabled = show;
}

function showErrorMessage(msg) {
    const box = document.getElementById('errorMessage');
    box.textContent = msg; box.classList.remove('hidden');
}

function showSuccessMessage(msg) {
    const box = document.getElementById('successMessage');
    box.textContent = msg; box.classList.remove('hidden');
}

function clearMessages() {
    document.getElementById('errorMessage').classList.add('hidden');
    document.getElementById('successMessage').classList.add('hidden');
}

const resetZoomBtn = document.getElementById('resetZoomBtn');
if (resetZoomBtn) {
    resetZoomBtn.addEventListener('click', () => {
        if (potentialChart) {
            potentialChart.resetZoom();
        }
    });
}

function toggleFullScreen(elementId) {
    const card = document.getElementById(elementId);
    if (!card) {
        console.error(`Element with id "${elementId}" not found.`);
        return;
    }

    if (!document.fullscreenElement) {
        if (card.requestFullscreen) {
            card.requestFullscreen();
        } else if (card.webkitRequestFullscreen) { 
            card.webkitRequestFullscreen();
        } else if (card.msRequestFullscreen) { 
            card.msRequestFullscreen();
        }
    } else {
        if (document.exitFullscreen) {
            document.exitFullscreen();
        }
    }
}

/**  2. Modular Zoom Reset Finds the canvas within the button's parent card and resets its Chart.js zoom plugin state.*/
function resetChartZoom(buttonElement) {
    const card = buttonElement.closest('.chart-card');
    if (!card) return;

    const canvas = card.querySelector('canvas');
    if (!canvas) return;

    
    const chartInstance = Chart.getChart(canvas);
    if (chartInstance && typeof chartInstance.resetZoom === 'function') {
        chartInstance.resetZoom();
    }
}

/** 3. Modular Reusable Zoom Options Config Pass this into your Chart.js options.plugins.zoom block for instant zoom support. */
function getZoomOptions(mode = 'xy') {
    return {
        pan: {
            enabled: true,
            mode: mode,
            threshold: 0
        },
        zoom: {
            wheel: {
                enabled: true
            },
            pinch: {
                enabled: true
            },
            mode: mode
        }
    };
}

/** 4. Fullscreen State Sync & Automatic Chart Resizing Triggers Chart.js resize on ALL instances whenever native fullscreen toggles . */
document.addEventListener('fullscreenchange', () => {
    const activeFullscreen = document.fullscreenElement;

    
    document.querySelectorAll('.chart-card').forEach(card => {
        card.classList.remove('is-fullscreen');
    });

    
    if (activeFullscreen && activeFullscreen.classList.contains('chart-card')) {
        activeFullscreen.classList.add('is-fullscreen');
    }

    
    setTimeout(() => {
        Object.values(Chart.instances).forEach(chart => {
            chart.resize();
        });
    }, 100);
});