// JSON configuration for default values
const defaultConfig = {
    "startingAge": 65,
    "capital": 500000,
    "positiveYearMin": 1.0,
    "positiveYearLikely": 14.0,
    "positiveYearMax": 55.0,
    "probDownNormal": 30,
    "probDownBounce": 15,
    "probDownDeep": 5,
    "deepSnapbackMult": 1.2,
    "negativeYearBest": -1,
    "negativeYearLikely": -7,
    "negativeYearWorst": -50,
    "taxRate": 15.0,
    "inflation": 3.0,
    "monthlyIncome": 4000,
    "additionalIncome": 1000,
    "additionalIncomeStartAge": 67,
    "incomeDecayRate": 1.5,
    "decayFlattenYears": 10,
    "guardrailThreshold": 20,
    "guardrailCut": 10,
    "years": 30
};

// Guess the currency based on the user's locale
function guessUserCurrency() {
    const locale = navigator.language || 'en-US';
    try {
        // Extract region using Intl.Locale if available, fallback to string splitting
        const region = (window.Intl && Intl.Locale) ? new Intl.Locale(locale).region : locale.split('-')[1]?.toUpperCase();
        if (!region) return 'USD';
        
        const regionCurrencies = {
            'US': 'USD', 'GB': 'GBP', 'CA': 'CAD', 'AU': 'AUD', 'NZ': 'NZD',
            'DE': 'EUR', 'FR': 'EUR', 'IT': 'EUR', 'ES': 'EUR', 'NL': 'EUR',
            'AT': 'EUR', 'BE': 'EUR', 'PT': 'EUR', 'IE': 'EUR', 'FI': 'EUR', 'GR': 'EUR',
            'JP': 'JPY', 'CN': 'CNY', 'IN': 'INR', 'CH': 'CHF', 'SE': 'SEK',
            'NO': 'NOK', 'DK': 'DKK', 'ZA': 'ZAR', 'BR': 'BRL', 'MX': 'MXN',
            'SG': 'SGD', 'HK': 'HKD', 'KR': 'KRW'
        };
        return regionCurrencies[region] || 'USD';
    } catch (e) {
        return 'USD';
    }
}

const userLocale = navigator.language || 'en-US';
const userCurrency = guessUserCurrency();

// Formatter for currency display
const currencyFormatter = new Intl.NumberFormat(userLocale, {
    style: 'currency',
    currency: userCurrency,
    maximumFractionDigits: 0
});

// Extract the symbol to update UI text dynamically
const symbolPart = currencyFormatter.formatToParts(0).find(p => p.type === 'currency');
const displaySymbol = symbolPart ? symbolPart.value : '$';

// Populate the form with default values on load
document.addEventListener('DOMContentLoaded', () => {
    // Update UI labels with the locale currency symbol
    document.querySelectorAll('.currency-symbol').forEach(el => {
        el.textContent = displaySymbol;
    });

    document.getElementById('startingAge').value = defaultConfig.startingAge;
    document.getElementById('capital').value = defaultConfig.capital;
    document.getElementById('positiveYearMin').value = defaultConfig.positiveYearMin;
    document.getElementById('positiveYearLikely').value = defaultConfig.positiveYearLikely;
    document.getElementById('positiveYearMax').value = defaultConfig.positiveYearMax;
    document.getElementById('probDownNormal').value = defaultConfig.probDownNormal;
    document.getElementById('probDownBounce').value = defaultConfig.probDownBounce;
    document.getElementById('probDownDeep').value = defaultConfig.probDownDeep;
    document.getElementById('deepSnapbackMult').value = defaultConfig.deepSnapbackMult;
    document.getElementById('negativeYearBest').value = defaultConfig.negativeYearBest;
    document.getElementById('negativeYearLikely').value = defaultConfig.negativeYearLikely;
    document.getElementById('negativeYearWorst').value = defaultConfig.negativeYearWorst;
    document.getElementById('taxRate').value = defaultConfig.taxRate;
    document.getElementById('inflation').value = defaultConfig.inflation;
    document.getElementById('monthlyIncome').value = defaultConfig.monthlyIncome;
    document.getElementById('additionalIncome').value = defaultConfig.additionalIncome;
    document.getElementById('additionalIncomeStartAge').value = defaultConfig.additionalIncomeStartAge;
    document.getElementById('incomeDecayRate').value = defaultConfig.incomeDecayRate;
    document.getElementById('decayFlattenYears').value = defaultConfig.decayFlattenYears;
    document.getElementById('guardrailThreshold').value = defaultConfig.guardrailThreshold;
    document.getElementById('guardrailCut').value = defaultConfig.guardrailCut;
    document.getElementById('years').value = defaultConfig.years;

    updateScenarioDropdown();
    document.getElementById('saveScenarioBtn').addEventListener('click', saveScenario);
    document.getElementById('loadScenarioBtn').addEventListener('click', loadScenario);
    document.getElementById('deleteScenarioBtn').addEventListener('click', deleteScenario);
    document.getElementById('percentileSelect').addEventListener('change', updateTableDisplay);

    document.querySelectorAll('.percentile-toggle').forEach(cb => {
        cb.addEventListener('change', (e) => {
            if (!burndownChart) return;
            const p = parseInt(e.target.value);
            const percentilesToPlot = [90, 80, 70, 60, 50, 40, 30, 20, 10];
            const datasetIndex = percentilesToPlot.indexOf(p);
            if (datasetIndex !== -1) {
                burndownChart.data.datasets[datasetIndex].hidden = !e.target.checked;
                burndownChart.update();
            }
        });
    });

    // Automatically calculate projection on load
    calculateProjection();
});

const STORAGE_KEY = 'burndown_scenarios';

function getSavedScenarios() {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved ? JSON.parse(saved) : {};
}

function saveScenario() {
    const name = document.getElementById('scenarioName').value.trim();
    if (!name) return alert('Please enter a scenario name.');

    const scenarios = getSavedScenarios();
    scenarios[name] = {
        startingAge: document.getElementById('startingAge').value,
        capital: document.getElementById('capital').value,
        positiveYearMin: document.getElementById('positiveYearMin').value,
        positiveYearLikely: document.getElementById('positiveYearLikely').value,
        positiveYearMax: document.getElementById('positiveYearMax').value,
        probDownNormal: document.getElementById('probDownNormal').value,
        probDownBounce: document.getElementById('probDownBounce').value,
        probDownDeep: document.getElementById('probDownDeep').value,
        deepSnapbackMult: document.getElementById('deepSnapbackMult').value,
        negativeYearBest: document.getElementById('negativeYearBest').value,
        negativeYearLikely: document.getElementById('negativeYearLikely').value,
        negativeYearWorst: document.getElementById('negativeYearWorst').value,
        taxRate: document.getElementById('taxRate').value,
        inflation: document.getElementById('inflation').value,
        monthlyIncome: document.getElementById('monthlyIncome').value,
        additionalIncome: document.getElementById('additionalIncome').value,
        additionalIncomeStartAge: document.getElementById('additionalIncomeStartAge').value,
        incomeDecayRate: document.getElementById('incomeDecayRate').value,
        decayFlattenYears: document.getElementById('decayFlattenYears').value,
        guardrailThreshold: document.getElementById('guardrailThreshold').value,
        guardrailCut: document.getElementById('guardrailCut').value,
        years: document.getElementById('years').value
    };
    
    localStorage.setItem(STORAGE_KEY, JSON.stringify(scenarios));
    updateScenarioDropdown();
    document.getElementById('savedScenarios').value = name;
    alert(`Scenario "${name}" saved successfully!`);
}

function updateScenarioDropdown() {
    const scenarios = getSavedScenarios();
    const select = document.getElementById('savedScenarios');
    select.innerHTML = '<option value="">-- Select --</option>';
    
    for (const name in scenarios) {
        const option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        select.appendChild(option);
    }
}

function loadScenario() {
    const name = document.getElementById('savedScenarios').value;
    if (!name) return alert('Please select a scenario to load.');

    const config = getSavedScenarios()[name];
    if (config) {
        document.getElementById('startingAge').value = config.startingAge || 65;
        document.getElementById('capital').value = config.capital;
        document.getElementById('positiveYearMin').value = config.positiveYearMin || 1.0;
        document.getElementById('positiveYearLikely').value = config.positiveYearLikely || 14.0;
        document.getElementById('positiveYearMax').value = config.positiveYearMax || 55.0;
        document.getElementById('probDownNormal').value = config.probDownNormal || 30;
        document.getElementById('probDownBounce').value = config.probDownBounce || 15;
        document.getElementById('probDownDeep').value = config.probDownDeep || 5;
        document.getElementById('deepSnapbackMult').value = config.deepSnapbackMult || 1.2;
        document.getElementById('negativeYearBest').value = config.negativeYearBest || -1;
        document.getElementById('negativeYearLikely').value = config.negativeYearLikely || -7;
        document.getElementById('negativeYearWorst').value = config.negativeYearWorst || -50;
        document.getElementById('taxRate').value = config.taxRate || 0;
        document.getElementById('inflation').value = config.inflation;
        document.getElementById('monthlyIncome').value = config.monthlyIncome;
        document.getElementById('additionalIncome').value = config.additionalIncome;
        document.getElementById('additionalIncomeStartAge').value = config.additionalIncomeStartAge || 67;
        document.getElementById('incomeDecayRate').value = config.incomeDecayRate || 0;
        document.getElementById('decayFlattenYears').value = config.decayFlattenYears || 0;
        document.getElementById('guardrailThreshold').value = config.guardrailThreshold || 0;
        document.getElementById('guardrailCut').value = config.guardrailCut || 0;
        document.getElementById('years').value = config.years;
        document.getElementById('scenarioName').value = name;
        calculateProjection();
    }
}

function deleteScenario() {
    const name = document.getElementById('savedScenarios').value;
    if (!name) return alert('Please select a scenario to delete.');

    if (confirm(`Are you sure you want to delete the scenario "${name}"?`)) {
        const scenarios = getSavedScenarios();
        delete scenarios[name];
        localStorage.setItem(STORAGE_KEY, JSON.stringify(scenarios));
        updateScenarioDropdown();
        document.getElementById('scenarioName').value = '';
    }
}

let burndownChart = null;
let incomeChart = null;
let currentRuns = [];

// --- Beta-PERT Distribution Math Functions ---
function normalRandom() {
    let u = 0, v = 0;
    while (u === 0) u = Math.random();
    while (v === 0) v = Math.random();
    return Math.sqrt(-2.0 * Math.log(u)) * Math.cos(2.0 * Math.PI * v);
}

function randomGamma(shape) {
    let d = shape - 1 / 3;
    let c = 1 / Math.sqrt(9 * d);
    while (true) {
        let x, v;
        do { x = normalRandom(); v = 1 + c * x; } while (v <= 0);
        v = v * v * v;
        let u = Math.random();
        let x2 = x * x;
        if (u < 1 - 0.0331 * x2 * x2) return d * v;
        if (Math.log(u) < 0.5 * x2 + d * (1 - v + Math.log(v))) return d * v;
    }
}

function randomBeta(alpha, beta) {
    let x = randomGamma(alpha);
    let y = randomGamma(beta);
    return x / (x + y);
}

function randomPERT(min, likely, max) {
    if (min === max) return min;
    let mu = (min + 4 * likely + max) / 6;
    let alpha = Math.max(1, ((mu - min) / (max - min)) * 6);
    let beta = Math.max(1, ((max - mu) / (max - min)) * 6);
    return min + randomBeta(alpha, beta) * (max - min);
}

function updateTableDisplay() {
    if (currentRuns.length === 0) return;
    const percentile = parseInt(document.getElementById('percentileSelect').value);
    const numSimulations = currentRuns.length;
    const runIndex = Math.min(Math.floor(numSimulations * (percentile / 100)), numSimulations - 1);
    const selectedRun = currentRuns[runIndex];

    const resultsBody = document.getElementById('results-body');
    resultsBody.innerHTML = '';

    selectedRun.tableRows.forEach(row => {
        const tr = document.createElement('tr');
        const ageLabel = `Age ${row.age} (Yr ${row.year})`;
        if (row.currentBalance <= 0 && row.startBalance <= 0) {
            tr.innerHTML = `
                <td>${ageLabel}</td>
                <td>${currencyFormatter.format(0)}</td>
                <td>${currencyFormatter.format(0)}</td>
                <td>${currencyFormatter.format(0)}</td>
                <td>${currencyFormatter.format(0)}</td>
                <td class="depleted">${currencyFormatter.format(0)}</td>
                <td class="depleted">${currencyFormatter.format(0)}</td>
            `;
        } else if (row.currentBalance <= 0) {
            tr.innerHTML = `
                <td>${ageLabel}</td>
                <td>${currencyFormatter.format(row.startBalance)}</td>
                <td>${currencyFormatter.format(row.growth)}</td>
                <td>${currencyFormatter.format(row.taxPaid)}</td>
                <td>${currencyFormatter.format(row.actualNetReceived)}</td>
                <td class="depleted">${currencyFormatter.format(0)}</td>
                <td class="depleted">${currencyFormatter.format(0)}</td>
            `;
        } else {
            tr.innerHTML = `
                <td>${ageLabel}</td>
                <td>${currencyFormatter.format(row.startBalance)}</td>
                <td>${currencyFormatter.format(row.growth)}</td>
                <td>${currencyFormatter.format(row.taxPaid)}</td>
                <td>${currencyFormatter.format(row.actualNetReceived)}</td>
                <td>${currencyFormatter.format(row.currentBalance)}</td>
                <td>${currencyFormatter.format(row.realBalance)}</td>
            `;
        }
        resultsBody.appendChild(tr);
    });
}

function calculateProjection(e) {
    if (e) e.preventDefault();

    // Get inputs
    const startingAge = parseInt(document.getElementById('startingAge').value);
    const startingCapital = parseFloat(document.getElementById('capital').value);
    const positiveYearMin = parseFloat(document.getElementById('positiveYearMin').value) / 100;
    const positiveYearLikely = parseFloat(document.getElementById('positiveYearLikely').value) / 100;
    const positiveYearMax = parseFloat(document.getElementById('positiveYearMax').value) / 100;
    const probDownNormal = parseFloat(document.getElementById('probDownNormal').value) / 100;
    const probDownBounce = parseFloat(document.getElementById('probDownBounce').value) / 100;
    const probDownDeep = parseFloat(document.getElementById('probDownDeep').value) / 100;
    const deepSnapbackMult = parseFloat(document.getElementById('deepSnapbackMult').value);
    const negativeYearBest = parseFloat(document.getElementById('negativeYearBest').value) / 100;
    const negativeYearLikely = parseFloat(document.getElementById('negativeYearLikely').value) / 100;
    const negativeYearWorst = parseFloat(document.getElementById('negativeYearWorst').value) / 100;
    const taxRate = parseFloat(document.getElementById('taxRate').value) / 100;
    const inflation = parseFloat(document.getElementById('inflation').value) / 100;
    const monthlyIncome = parseFloat(document.getElementById('monthlyIncome').value);
    const additionalIncome = parseFloat(document.getElementById('additionalIncome').value);
    const additionalIncomeStartAge = parseInt(document.getElementById('additionalIncomeStartAge').value);
    const incomeDecayRate = parseFloat(document.getElementById('incomeDecayRate').value) / 100;
    const decayFlattenYears = parseInt(document.getElementById('decayFlattenYears').value);
    const guardrailThreshold = parseFloat(document.getElementById('guardrailThreshold').value) / 100;
    const guardrailCut = parseFloat(document.getElementById('guardrailCut').value) / 100;
    const years = parseInt(document.getElementById('years').value);

    const numSimulations = 500;
    const runs = [];

    for (let sim = 0; sim < numSimulations; sim++) {
        let currentTargetIncome = monthlyIncome * 12;
        let currentBalance = startingCapital;
        let principalPool = startingCapital;
        let gainsPool = 0;
        let previousReturn = 0; // Assume we start in a flat/normal market state
        
        let runData = {
            chartDataNominal: [startingCapital],
            chartDataReal: [startingCapital],
            incomeDataNominal: [monthlyIncome],
            incomeDataReal: [monthlyIncome],
            taxDataNominal: [0],
            taxDataReal: [0],
            tableRows: [],
            finalBalance: 0,
            yearDepleted: -1,
            cumulativeReturn: 1.0,
            cagr: 0
        };

        for (let year = 1; year <= years; year++) {
            let currentAge = startingAge + year;
            const incomeInflationFactor = Math.pow(1 + inflation, year - 1);
            let currentAdditionalIncome = 0;
            if (currentAge >= additionalIncomeStartAge) {
                currentAdditionalIncome = additionalIncome * 12 * incomeInflationFactor;
            }

            // 3-State Markov Chain for Market Return
            let currentNegativeProb;
            let isDeepValueSnapback = false;
            
            if (previousReturn >= 0) {
                currentNegativeProb = probDownNormal;
            } else if (previousReturn >= -0.20) {
                currentNegativeProb = probDownBounce;
            } else {
                currentNegativeProb = probDownDeep;
                isDeepValueSnapback = true;
            }

            let isNegativeYear = Math.random() < currentNegativeProb;
            let targetReturn = isNegativeYear ? randomPERT(negativeYearWorst, negativeYearLikely, negativeYearBest) : randomPERT(positiveYearMin, positiveYearLikely, positiveYearMax);
            
            if (!isNegativeYear && isDeepValueSnapback) {
                targetReturn = Math.min(0.60, targetReturn * deepSnapbackMult); // Cap the snapback at +60%
            }
            previousReturn = targetReturn; // Update state for next year
            
            runData.cumulativeReturn *= (1 + targetReturn);

            if (currentBalance <= 0) {
                let currentMonthlyIncomeNominal = currentAdditionalIncome / 12;
                let currentMonthlyIncomeReal = currentMonthlyIncomeNominal / incomeInflationFactor;

                // Account depleted, pad zeros to maintain chart structure
                runData.chartDataNominal.push(0);
                runData.chartDataReal.push(0);
                runData.incomeDataNominal.push(currentMonthlyIncomeNominal);
                runData.incomeDataReal.push(currentMonthlyIncomeReal);
                runData.taxDataNominal.push(0);
                runData.taxDataReal.push(0);
                runData.tableRows.push({
                    year: year, age: currentAge, startBalance: 0, growth: 0, taxPaid: 0, actualNetReceived: 0, currentBalance: 0, realBalance: 0
                });
                
                // Still decay the target income so it stays in sync
                let currentDecay = (year <= decayFlattenYears) ? incomeDecayRate : 0;
                currentTargetIncome = currentTargetIncome * (1 + inflation) * (1 - currentDecay);

                continue;
            }

            // Determine starting balance for the year
            let startBalance = currentBalance;

            // Check dynamic spending guardrails
            let startRealBalance = startBalance / Math.pow(1 + inflation, year - 1);
            let isGuardrailActive = (guardrailThreshold > 0 && startRealBalance < startingCapital * (1 - guardrailThreshold));
            let actualTargetIncome = isGuardrailActive ? currentTargetIncome * (1 - guardrailCut) : currentTargetIncome;
            let currentNetWithdrawal = Math.max(0, actualTargetIncome - currentAdditionalIncome);

            // Calculate investment growth for the year
            let growth = startBalance * targetReturn;
            
            gainsPool += growth;
            let balanceBeforeWithdrawal = principalPool + gainsPool;

            // Determine proportional capital gains tax on the withdrawal
            let gainRatio = (balanceBeforeWithdrawal > 0 && gainsPool > 0) ? (gainsPool / balanceBeforeWithdrawal) : 0;
            let effectiveTaxRate = gainRatio * taxRate;

            // Gross withdrawal is the amount we need to pull out to net the requested amount after taxes
            let grossWithdrawal = currentNetWithdrawal / (1 - effectiveTaxRate);
            let actualNetReceived = currentNetWithdrawal;
            let taxPaid = grossWithdrawal - currentNetWithdrawal;

            if (grossWithdrawal >= balanceBeforeWithdrawal) {
                grossWithdrawal = balanceBeforeWithdrawal;
                actualNetReceived = grossWithdrawal * (1 - effectiveTaxRate);
                taxPaid = grossWithdrawal - actualNetReceived;
                principalPool = 0;
                gainsPool = 0;
                currentBalance = 0;
                if (runData.yearDepleted === -1) runData.yearDepleted = year;
            } else {
                principalPool -= grossWithdrawal * (1 - gainRatio);
                gainsPool -= grossWithdrawal * gainRatio;
                currentBalance = principalPool + gainsPool;
            }

            // Calculate inflation-adjusted balance for today's purchasing power
            const inflationFactor = Math.pow(1 + inflation, year);
            const realBalance = currentBalance / inflationFactor;

            runData.chartDataNominal.push(Math.max(0, currentBalance));
            runData.chartDataReal.push(Math.max(0, realBalance));

            
            let currentMonthlyIncomeNominal = (actualNetReceived / 12) + (currentAdditionalIncome / 12);
            let currentMonthlyIncomeReal = currentMonthlyIncomeNominal / incomeInflationFactor;

            let currentMonthlyTaxNominal = taxPaid / 12;
            let currentMonthlyTaxReal = currentMonthlyTaxNominal / incomeInflationFactor;

            runData.incomeDataNominal.push(currentMonthlyIncomeNominal);
            runData.incomeDataReal.push(currentMonthlyIncomeReal);
            runData.taxDataNominal.push(currentMonthlyTaxNominal);
            runData.taxDataReal.push(currentMonthlyTaxReal);

            // Create table row object
            runData.tableRows.push({
                year, age: currentAge, startBalance, growth, taxPaid, actualNetReceived, currentBalance, realBalance
            });

            // Adjust next year's target income for inflation, factoring in reduced spending (decay)
            let currentDecay = (year <= decayFlattenYears) ? incomeDecayRate : 0;
            currentTargetIncome = currentTargetIncome * (1 + inflation) * (1 - currentDecay);
        }
        
        runData.finalBalance = currentBalance;
        runData.cagr = Math.pow(runData.cumulativeReturn, 1 / years) - 1;
        runs.push(runData);
    }

    // Rank runs by depletion year, then final balance
    runs.sort((a, b) => {
        if (a.yearDepleted !== -1 && b.yearDepleted !== -1) return a.yearDepleted - b.yearDepleted; // Depleted earlier is worse
        if (a.yearDepleted !== -1) return -1; // A died, B lived (A is worse)
        if (b.yearDepleted !== -1) return 1;  // B died, A lived (B is worse)
        return a.finalBalance - b.finalBalance;
    });

    currentRuns = runs;

    // Update CAGR displays in the toggle labels
    document.querySelectorAll('.legend-text').forEach(el => {
        const p = parseInt(el.getAttribute('data-percentile'));
        const runIndex = Math.min(Math.floor(numSimulations * (p / 100)), numSimulations - 1);
        const run = runs[runIndex];
        const cagrFormatted = (run.cagr * 100).toFixed(2) + '%';
        
        let labelName = p + "th";
        if (p === 90) labelName = "90th (Best)";
        else if (p === 50) labelName = "Median";
        else if (p === 10) labelName = "10th (Worst)";
        
        el.textContent = `${labelName} [CAGR: ${cagrFormatted}]`;
    });

    // Update CAGR displays in the dropdown
    document.querySelectorAll('#percentileSelect option').forEach(opt => {
        const p = parseInt(opt.value);
        const runIndex = Math.min(Math.floor(numSimulations * (p / 100)), numSimulations - 1);
        const run = runs[runIndex];
        const cagrFormatted = (run.cagr * 100).toFixed(2) + '%';
        
        let labelName = p + "th";
        if (p === 90) labelName = "90th (Best Case)";
        else if (p === 50) labelName = "50th (Median Case)";
        else if (p === 10) labelName = "10th (Worst Case)";
        
        opt.textContent = `${labelName} - CAGR: ${cagrFormatted}`;
    });

    // Extract percentiles
    const worstRun = runs[Math.floor(numSimulations * 0.1)]; // 10th percentile
    const medianRun = runs[Math.floor(numSimulations * 0.5)]; // 50th percentile
    const bestRun = runs[Math.floor(numSimulations * 0.9)]; // 90th percentile

    // Update KPI Dashboard
    const totalMedianTaxesReal = medianRun.tableRows.reduce((sum, row) => {
        const inflationFactor = Math.pow(1 + inflation, row.year - 1);
        return sum + (row.taxPaid / inflationFactor);
    }, 0);

    const kpiDepletion = document.getElementById('kpi-depletion');
    if (worstRun.yearDepleted === -1) {
        kpiDepletion.textContent = `> Age ${startingAge + years}`;
        kpiDepletion.className = 'kpi-value success';
    } else {
        kpiDepletion.textContent = `Age ${startingAge + worstRun.yearDepleted}`;
        kpiDepletion.className = 'kpi-value danger';
    }
    document.getElementById('kpi-median-balance').textContent = currencyFormatter.format(medianRun.chartDataReal[years]);
    document.getElementById('kpi-median-taxes').textContent = currencyFormatter.format(totalMedianTaxesReal);
    document.getElementById('kpi-dashboard').style.display = 'flex';

    const chartLabels = [`Age ${startingAge}`];
    for (let i = 1; i <= years; i++) chartLabels.push(`Age ${startingAge + i}`);

    // Populate UI Table with Selected Outcome
    updateTableDisplay();

    // Show results
    document.getElementById('results-container').style.display = 'block';

    // Render Chart
    const ctx = document.getElementById('burndownChart').getContext('2d');
    if (burndownChart) {
        burndownChart.destroy();
    }

    const percentilesToPlot = [90, 80, 70, 60, 50, 40, 30, 20, 10];
    const burndownDatasets = percentilesToPlot.map(p => {
        const runIndex = Math.min(Math.floor(numSimulations * (p / 100)), numSimulations - 1);
        const run = runs[runIndex];
        const isChecked = document.querySelector(`.percentile-toggle[value="${p}"]`).checked;
        const cagrFormatted = (run.cagr * 100).toFixed(2) + '%';
        
        let label, borderColor, backgroundColor, borderWidth, borderDash, fill;
        
        if (p === 90) {
            label = `Best Case (90th%) [CAGR: ${cagrFormatted}] - Today's ${displaySymbol}`;
            borderColor = '#10b981';
            backgroundColor = 'transparent';
            borderWidth = 2;
            borderDash = [5, 5];
            fill = false;
        } else if (p === 50) {
            label = `Median Case [CAGR: ${cagrFormatted}] - Today's ${displaySymbol}`;
            borderColor = '#2563eb';
            backgroundColor = 'rgba(37, 99, 235, 0.1)';
            borderWidth = 2;
            borderDash = [];
            fill = true;
        } else if (p === 10) {
            label = `Worst Case (10th%) [CAGR: ${cagrFormatted}] - Today's ${displaySymbol}`;
            borderColor = '#ef4444';
            backgroundColor = 'transparent';
            borderWidth = 2;
            borderDash = [5, 5];
            fill = false;
        } else {
            label = `${p}th Percentile [CAGR: ${cagrFormatted}] - Today's ${displaySymbol}`;
            borderColor = '#cbd5e1';
            backgroundColor = 'transparent';
            borderWidth = 1;
            borderDash = [];
            fill = false;
        }

        return {
            label,
            data: run.chartDataReal,
            borderColor,
            backgroundColor,
            borderWidth,
            borderDash,
            fill,
            tension: 0.1,
            hidden: !isChecked
        };
    });

    burndownChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: chartLabels,
            datasets: burndownDatasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return currencyFormatter.format(value);
                        }
                    }
                }
            },
            plugins: {
                legend: {
                    display: false
                },
                title: {
                    display: true,
                    text: 'Capital Projection',
                    font: { size: 16 }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return currencyFormatter.format(context.parsed.y);
                        }
                    }
                }
            }
        }
    });

    // Render Income Chart
    const incomeCtx = document.getElementById('incomeChart').getContext('2d');
    if (incomeChart) {
        incomeChart.destroy();
    }
    incomeChart = new Chart(incomeCtx, {
        type: 'bar',
        data: {
            labels: chartLabels,
            datasets: [
                {
                    label: `Median Net Income (Today's ${displaySymbol})`,
                    data: medianRun.incomeDataReal,
                    backgroundColor: 'rgba(16, 185, 129, 0.8)',
                    borderColor: '#10b981',
                    borderWidth: 1
                },
                {
                    label: `Median Tax Paid (Today's ${displaySymbol})`,
                    data: medianRun.taxDataReal,
                    backgroundColor: 'rgba(239, 68, 68, 0.8)',
                    borderColor: '#ef4444',
                    borderWidth: 1
                },
                {
                    type: 'line',
                    label: `Worst Case Net Income (Today's ${displaySymbol})`,
                    data: worstRun.incomeDataReal,
                    borderColor: '#f59e0b',
                    backgroundColor: 'transparent',
                    borderWidth: 2,
                    borderDash: [5, 5],
                    tension: 0.1
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    stacked: true
                },
                y: {
                    stacked: true,
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return currencyFormatter.format(value);
                        }
                    }
                }
            },
            plugins: {
                title: {
                    display: true,
                    text: 'Monthly Income & Tax Projection (Gross)',
                    font: { size: 16 }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return currencyFormatter.format(context.parsed.y);
                        }
                    }
                }
            }
        }
    });
}

document.getElementById('calculator-form').addEventListener('submit', calculateProjection);