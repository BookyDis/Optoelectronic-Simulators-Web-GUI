// Frontend logic for Quantum Well Simulator

let potentialChart    = null;
let wavefunctionChart = null;
let boundStateChart   = null;
let energyDiffChart   = null;
let qclChart          = null;
let absorptionChart   = null;
let diffusionChart    = null;
let segregationChart  = null;
let currentResults    = null;

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('simulatorForm').addEventListener('submit', handleSubmit);
    document.getElementById('material').addEventListener('change', loadMaterialInfo);

    const diffBtn = document.getElementById('runDiffusionBtn');
    if (diffBtn) diffBtn.addEventListener('click', runDiffusion);

    const segBtn = document.getElementById('runSegregationBtn');
    if (segBtn) segBtn.addEventListener('click', runSegregation);
});

// function for switching between Quantum Well simulator and Transition calculator
function show(elementID) {
// find the requested page and alert if it's not found
  const ele = document.getElementById(elementID);
  if (!ele) {
    alert("no such element");
    return;
  }

  // get all pages, loop through them and hide them
  const pages = document.getElementsByClassName('divSimulator');
  for (let i = 0; i < pages.length; i++) {
    pages[i].style.display = 'none';
  }

  // then show the requested page
  ele.style.display = 'block';
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

// ── Download function

function downloadChart(canvasId, filename) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    // Draw onto a white-background offscreen canvas so the PNG isn't transparent
    const offscreen = document.createElement('canvas');
    offscreen.width  = canvas.width;
    offscreen.height = canvas.height;
    const octx = offscreen.getContext('2d');
    octx.fillStyle = '#ffffff';
    octx.fillRect(0, 0, offscreen.width, offscreen.height);
    octx.drawImage(canvas, 0, 0);

    const link = document.createElement('a');
    link.download = `${filename}.png`;
    link.href     = offscreen.toDataURL('image/png');
    link.click();
}

// ── Main simulation submit ────────────────────────────────────────────────────

async function handleSubmit(e) {
    e.preventDefault();
    clearMessages();
    showLoadingSpinner(true);

    const formData = {
        material:        document.getElementById('material').value,
        solver:          document.getElementById('solver').value,
        subband_model:   document.getElementById('subband_model').value,
        layer_structure: document.getElementById('layer_structure').value,
        electric_field:  document.getElementById('electric_field').value,
        grid_spacing:    document.getElementById('grid_spacing').value,
        num_states:      document.getElementById('num_states').value,
    };

    try {
        const response = await fetch('/api/simulate', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(formData),
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
                .scrollIntoView({ behavior: 'smooth', block: 'start' });
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
    if (potentialChart) potentialChart.destroy();

    const wfColors = ['rgb(54,162,235)','rgb(255,99,132)','rgb(75,192,192)','rgb(255,206,86)','rgb(153,102,255)'];
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
        type: 'line', data: { datasets },
        options: {
            responsive: true,
            plugins: { legend: { display: true }, title: { display: true, text: 'Bandstructure Potential Profile' } },
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

    const colors = ['rgb(255,99,132)','rgb(54,162,235)','rgb(75,192,192)','rgb(255,206,86)'];

    const datasets = wavefunctions.map((wf, idx) => ({
        label: `ψ${idx + 1}  (E = ${(energies[idx] * 1000).toFixed(2)} meV)`,
        data: Array.from(wf),
        borderColor: colors[idx % colors.length],
        backgroundColor: colors[idx % colors.length].replace('rgb','rgba').replace(')',',0.1)'),
        tension: 0.3, borderWidth: 2, pointRadius: 0,
    }));

    wavefunctionChart = new Chart(ctx, {
        type: 'line',
        data: { labels: zGrid.map(z => z.toFixed(2)), datasets },
        options: {
            responsive: true,
            plugins: { legend: { display: true }, title: { display: true, text: 'Quantum Well Wavefunctions' } },
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
        data: { datasets: [
            { data: stemPoints, borderColor: 'rgb(70,90,230)', borderDash: [6,4], borderWidth: 1.5, pointRadius: 0, spanGaps: false },
            { type: 'scatter', data: markerPoints, pointStyle: 'circle', pointRadius: 8, pointBorderColor: 'rgb(70,90,230)', pointBackgroundColor: 'rgba(0,0,0,0)', pointBorderWidth: 2 },
        ]},
        options: {
            responsive: true,
            plugins: { legend: { display: false }, title: { display: true, text: 'Bound State Energies' } },
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
        data: { datasets: [
            { data: stemPoints, borderColor: 'rgb(220,53,69)', borderDash: [6,4], borderWidth: 1.5, pointRadius: 0, spanGaps: false },
            { type: 'scatter', data: markerPoints, pointStyle: 'circle', pointRadius: 8, pointBorderColor: 'rgb(220,53,69)', pointBackgroundColor: 'rgba(0,0,0,0)', pointBorderWidth: 2 },
        ]},
        options: {
            responsive: true,
            plugins: { legend: { display: false }, title: { display: true, text: 'Energy Differences' } },
            scales: {
                x: { type: 'linear', title: { display: true, text: 'Transition' },
                     ticks: { stepSize: 1, callback: v => tickLabels[Math.round(v)] ?? '' } },
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
    const wfColors = ['rgb(75,192,192)','rgb(255,159,64)','rgb(153,102,255)','rgb(255,206,86)'];
    const datasets = [];

    for (let p = 0; p < 2; p++) {
        const shift = (p - 1) * Lper;
        const off   = dropMeV * (1 - p);
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
            plugins: { legend: { display: true }, title: { display: true, text: 'Two QCL Periods' } },
            scales: {
                x: { type: 'linear', title: { display: true, text: 'z (Å)' } },
                y: { title: { display: true, text: 'V (meV)' } },
            },
        },
    });
}

// ── Absorption spectrum ───────────────────────────────────────────────────────

async function runAbsorption() {
    if (!currentResults) {
        showAbsorptionMsg('Run a simulation first before computing absorption.', 'error');
        return;
    }

    document.getElementById('absorptionError').classList.add('hidden');
    document.getElementById('absorptionSuccess').classList.add('hidden');
    setSpinnerActive('absorptionSpinner', true);

    // Parse populations — each line must be "state density"
    const populations = {};
    document.getElementById('absorptionPopulations').value
        .trim().split('\n')
        .forEach(line => {
            const p = line.trim().split(/\s+/);
            if (p.length === 2) populations[p[0]] = parseFloat(p[1]);
        });

    // Parse linewidths — each line must be "i j meV"
    const linewidths = {};
    document.getElementById('absorptionLinewidths').value
        .trim().split('\n')
        .forEach(line => {
            const p = line.trim().split(/\s+/);
            if (p.length === 3) linewidths[`${p[0]},${p[1]}`] = parseFloat(p[2]);
        });

    // Validate we got something
    if (Object.keys(populations).length === 0) {
        showAbsorptionMsg('No valid populations found. Check format: one "state density" per line.', 'error');
        setSpinnerActive('absorptionSpinner', false);
        return;
    }
    if (Object.keys(linewidths).length === 0) {
        showAbsorptionMsg('No valid linewidths found. Check format: one "i j meV" per line.', 'error');
        setSpinnerActive('absorptionSpinner', false);
        return;
    }

    const eMin = document.getElementById('absEnergyMin').value;
    const eMax = document.getElementById('absEnergyMax').value;

    const payload = {
        material:        document.getElementById('material').value,
        solver:          document.getElementById('solver').value,
        subband_model:   document.getElementById('subband_model').value,
        layer_structure: document.getElementById('layer_structure').value,
        electric_field:  document.getElementById('electric_field').value,
        grid_spacing:    document.getElementById('grid_spacing').value,
        num_states:      document.getElementById('num_states').value,
        populations,
        linewidths,
        energy_range_meV: (eMin && eMax) ? [parseFloat(eMin), parseFloat(eMax)] : null,
        n_points: 2000,
    };

    try {
        const response = await fetch('/api/absorption', {
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
            renderAbsorptionChart(data.spectrum);
            renderTransitionTable(data.transitions);
            showAbsorptionMsg('Absorption spectrum computed successfully.', 'success');
        } else {
            showAbsorptionMsg(data.message, 'error');
        }
    } catch (err) {
        showAbsorptionMsg(`Request failed: ${err.message}`, 'error');
        console.error('Absorption error:', err);
    } finally {
        setSpinnerActive('absorptionSpinner', false);
    }
}

function renderAbsorptionChart(spectrum) {
    const ctx = document.getElementById('absorptionChart').getContext('2d');
    if (absorptionChart) absorptionChart.destroy();

    absorptionChart = new Chart(ctx, {
        type: 'line',
        data: { datasets: [
            {
                label: 'α(ħω) [cm⁻¹]',
                data: spectrum.hbar_omega_meV.map((e, i) => ({ x: e, y: spectrum.alpha_cm[i] })),
                borderColor: 'rgb(118,75,162)', backgroundColor: 'rgba(118,75,162,0.07)',
                borderWidth: 2, pointRadius: 0, tension: 0.3, fill: true,
            },
            {
                label: 'α = 0',
                data: spectrum.hbar_omega_meV.map(e => ({ x: e, y: 0 })),
                borderColor: 'rgba(0,0,0,0.18)', borderDash: [5,4], borderWidth: 1, pointRadius: 0, fill: false,
            },
        ]},
        options: {
            responsive: true,
            plugins: {
                legend: { display: true },
                title: { display: true, text: 'Intersubband Absorption Coefficient' },
                tooltip: { callbacks: { label: c => `α = ${c.parsed.y.toFixed(2)} cm⁻¹  @  ${c.parsed.x.toFixed(2)} meV` } },
            },
            scales: {
                x: { type: 'linear', title: { display: true, text: 'ħω (meV)' } },
                y: { title: { display: true, text: 'α (cm⁻¹)' } },
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
            <td>${t.gamma_meV     !== null ? t.gamma_meV.toFixed(1)     : '—'}</td>
            <td>${t.dN_m2.toExponential(2)}</td>
            <td>${t.peak_alpha_cm !== null ? t.peak_alpha_cm.toFixed(1) : '—'}</td>`;
        tbody.appendChild(row);
    });
    document.getElementById('transitionTableSection').classList.remove('hidden');
}

// ── Diffusion ─────────────────────────────────────────────────────────────────

async function runDiffusion() {
    if (!currentResults) {
        showDiffusionMessage('Run a simulation first to initialise the solver grid.', 'error');
        return;
    }
    clearDiffusionMessages();
    setSpinnerActive('diffusionSpinner', true);

    // Parse transport: "state D tau" per line
    const transport_properties = {};
    document.getElementById('diffTransport').value.trim().split('\n').forEach(line => {
        const p = line.trim().split(/\s+/);
        if (p.length === 3) transport_properties[p[0]] = [parseFloat(p[1]), parseFloat(p[2])];
    });

    // Parse generation: "state G" per line
    const generation = {};
    document.getElementById('diffGeneration').value.trim().split('\n').forEach(line => {
        const p = line.trim().split(/\s+/);
        if (p.length === 2) generation[p[0]] = parseFloat(p[1]);
    });

    const payload = {
        material:             document.getElementById('material').value,
        solver:               document.getElementById('solver').value,
        subband_model:        document.getElementById('subband_model').value,
        layer_structure:      document.getElementById('layer_structure').value,
        electric_field:       document.getElementById('electric_field').value,
        grid_spacing:         document.getElementById('grid_spacing').value,
        num_states:           document.getElementById('num_states').value,
        transport_properties, // key the backend now expects
        generation,
    };

    try {
        const response = await fetch('/api/diffusion', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) {
            const text = await response.text();
            throw new Error(`HTTP error ${response.status}: ${text.slice(0,200)}`);
        }
        const data = await response.json();

        if (data.status === 'success') {
            displayDiffusionChart(data.z_grid, data.spatial_populations);
            renderDiffusionSheetTable(data.sheet_densities, data.peak_densities);
            showDiffusionMessage('Steady-state diffusion solved successfully.', 'success');
        } else {
            showDiffusionMessage(data.message, 'error');
        }
    } catch (err) {
        showDiffusionMessage(`Error: ${err.message}`, 'error');
        console.error('Diffusion error:', err);
    } finally {
        setSpinnerActive('diffusionSpinner', false);
    }
}

function displayDiffusionChart(zGrid, spatialPops) {
    const ctx = document.getElementById('diffusionChart').getContext('2d');
    if (diffusionChart) diffusionChart.destroy();

    const colors = ['rgb(255,99,132)','rgb(54,162,235)','rgb(75,192,192)','rgb(153,102,255)'];
    const datasets = Object.keys(spatialPops).map((sb, idx) => ({
        label: `Subband ${sb}`,
        data: zGrid.map((z, i) => ({ x: z, y: spatialPops[sb][i] })),
        borderColor: colors[idx % colors.length],
        borderWidth: 2, pointRadius: 0, tension: 0.3, fill: false,
    }));

    diffusionChart = new Chart(ctx, {
        type: 'line', data: { datasets },
        options: {
            responsive: true,
            plugins: { title: { display: true, text: 'Steady-State Carrier Density Profiles' } },
            scales: {
                x: { type: 'linear', title: { display: true, text: 'z (Å)' } },
                y: { title: { display: true, text: 'N(z) (m⁻³)' } },
            },
        },
    });
}

function renderDiffusionSheetTable(sheets, peaks) {
    const tbody = document.getElementById('diffusionTableBody');
    tbody.innerHTML = '';
    Object.keys(sheets).forEach(sb => {
        const row = document.createElement('tr');
        row.innerHTML = `<td>${sb}</td>
            <td>${(+sheets[sb]).toExponential(4)}</td>
            <td>${peaks && peaks[sb] !== undefined ? (+peaks[sb]).toExponential(4) : '—'}</td>`;
        tbody.appendChild(row);
    });
    document.getElementById('diffusionTableSection').classList.remove('hidden');
}

// ── Segregation ───────────────────────────────────────────────────────────────

async function runSegregation() {
    clearSegregationMessages();
    setSpinnerActive('segregationSpinner', true);

    const payload = {
        layer_structure: document.getElementById('layer_structure').value,
        grid_spacing:    document.getElementById('grid_spacing').value,
        model_type:      document.getElementById('segModelType').value,
        param_value:     parseFloat(document.getElementById('segParamValue').value),
        asymmetric:      document.getElementById('segAsymmetric').value === 'true',
    };

    try {
        const response = await fetch('/api/segregation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) throw new Error(`HTTP error ${response.status}`);
        const data = await response.json();

        if (data.status === 'success') {
            displaySegregationChart(data.z, data.x_nominal, data.x_smeared);
            showSegregationMessage('Segregation profile calculated.', 'success');
        } else {
            showSegregationMessage(data.message, 'error');
        }
    } catch (err) {
        showSegregationMessage(`Error: ${err.message}`, 'error');
    } finally {
        setSpinnerActive('segregationSpinner', false);
    }
}

function displaySegregationChart(z, xNominal, xSmeared) {
    const ctx = document.getElementById('segregationChart').getContext('2d');
    if (segregationChart) segregationChart.destroy();

    segregationChart = new Chart(ctx, {
        type: 'line',
        data: { datasets: [
            {
                label: 'Nominal (sharp)',
                data: z.map((v, i) => ({ x: v, y: xNominal[i] })),
                borderColor: 'rgb(120,120,120)', borderDash: [5,5],
                borderWidth: 2, pointRadius: 0, tension: 0, fill: false,
            },
            {
                label: 'Smeared',
                data: z.map((v, i) => ({ x: v, y: xSmeared[i] })),
                borderColor: 'rgb(118,75,162)',
                borderWidth: 3, pointRadius: 0, tension: 0.1, fill: false,
            },
        ]},
        options: {
            responsive: true,
            plugins: { title: { display: true, text: 'Interface Segregation / Smearing' } },
            scales: {
                x: { type: 'linear', title: { display: true, text: 'z (Å)' } },
                y: { title: { display: true, text: 'Alloy fraction x' }, min: 0, max: 1 },
            },
        },
    });
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
            document.getElementById('info-bandgap-well').textContent     = data.band_gap.well.toFixed(4)           + ' eV';
            document.getElementById('info-bandgap-barrier').textContent  = data.band_gap.barrier.toFixed(4)        + ' eV';
            document.getElementById('info-mass-well').textContent        = data.effective_mass.well.toFixed(4)     + ' m₀';
            document.getElementById('info-mass-barrier').textContent     = data.effective_mass.barrier.toFixed(4)  + ' m₀';
            document.getElementById('info-kane-well').textContent        = data.kane_parameter.well.toFixed(4)     + ' eV·Å²';
            document.getElementById('info-kane-barrier').textContent     = data.kane_parameter.barrier.toFixed(4)  + ' eV·Å²';
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
    const label   = document.getElementById('loadingLabel');
    const btn     = document.getElementById('submitBtn');
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

