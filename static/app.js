'use strict';

const $ = (selector) => document.querySelector(selector);
const features = Array.from({ length: 8 }, (_, i) => `X${i + 1}`);
const methods = ['MLR', 'DT', 'RF'];
const methodNames = { MLR: 'Linear regression', DT: 'Decision Tree', RF: 'Random Forest' };
const names = { X1: 'Relative compactness', X2: 'Surface area', X3: 'Wall area', X4: 'Roof area', X5: 'Overall height', X6: 'Orientation', X7: 'Glazing area', X8: 'Glazing distribution', Y1: 'Heating reference', Y2: 'Cooling reference' };
const distributions = { 0: 'No glazing', 1: 'Uniform', 2: 'North emphasis', 3: 'East emphasis', 4: 'South emphasis', 5: 'West emphasis' };
let catalog, studyData, predictor, compareA, compareB, latestPrediction, latestComparison;
let currentDataset, currentReport, lastValidation;
let activeView, introduced = false, importing = false, openRequest = 0;
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
const root = document.documentElement;
root.dataset.input = 'pointer';

function cancelMotion() { document.getAnimations().forEach(animation => animation.cancel()); }
document.addEventListener('keydown', event => { if (!event.metaKey && !event.ctrlKey && !event.altKey) { root.dataset.input = 'keyboard'; cancelMotion(); } });
document.addEventListener('pointerdown', () => { root.dataset.input = 'pointer'; }, { passive: true });
document.addEventListener('visibilitychange', () => { if (document.hidden) cancelMotion(); });
reduceMotion.addEventListener('change', () => { if (reduceMotion.matches) cancelMotion(); });
function motionAllowed() { return !reduceMotion.matches && root.dataset.input !== 'keyboard' && !document.hidden; }
function reveal(element, lift = false, delay = 0) {
  if (!element || element.closest('[hidden]') || !motionAllowed() || !element.animate) return;
  element.getAnimations().forEach(animation => animation.cancel());
  const frames = lift ? [{ opacity: 0, transform: 'translateY(8px)' }, { opacity: 1, transform: 'translateY(0)' }] : [{ opacity: 0 }, { opacity: 1 }];
  const tokens = getComputedStyle(root);
  element.animate(frames, { duration: parseFloat(tokens.getPropertyValue('--motion-enter')), easing: tokens.getPropertyValue('--ease-out').trim(), delay, fill: 'backwards' });
}
function setBusy(button, busy, text) {
  const label = button.querySelector('.button-label');
  if (busy) { label.dataset.idle = label.textContent; label.textContent = text; }
  else if (label.dataset.idle) label.textContent = label.dataset.idle;
  button.disabled = busy;
  button.setAttribute('aria-busy', String(busy));
}
function datasetStep(step) {
  for (const item of document.querySelectorAll('#dataset-steps li')) {
    const index = Number(item.dataset.step), state = index < step ? 'complete' : index === step ? 'current' : 'upcoming';
    item.dataset.state = state;
    item.querySelector('.step-number').textContent = state === 'complete' ? '✓' : `0${index + 1}`;
    item.querySelector('.step-state').textContent = state === 'complete' ? 'Complete' : state === 'current' ? 'Current step' : 'Upcoming';
    if (state === 'current') item.setAttribute('aria-current', 'step'); else item.removeAttribute('aria-current');
  }
}
function mappingStatus() {
  const count = [...document.querySelectorAll('#column-mapping select')].filter(control => control.value).length;
  $('#mapping-completeness').textContent = `${count} of 8 mapped`;
  $('#mapping-completeness').dataset.complete = String(count === 8);
  for (const input of [$('#response-units'), $('#response-definition')]) input.required = $('#confirm-comparable').checked;
}
function focusPanel(selector) {
  const panel = $(selector), heading = panel.querySelector('h2');
  if (panel.closest('.view').hidden) return;
  heading.setAttribute('tabindex', '-1');
  heading.focus({ preventScroll: true });
  panel.scrollIntoView({ behavior: 'instant', block: 'start' });
}

function node(tag, attributes = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) if (value !== false && value != null) element.setAttribute(key, value === true ? '' : String(value));
  for (const child of children.flat(Infinity)) if (child != null) element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return element;
}
function svgNode(tag, attributes = {}, text) {
  const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  if (text != null) element.textContent = text;
  return element;
}
function format(value, digits = 3) { return Number.isFinite(value) ? value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits }) : '—'; }
function message(selector, text = '', type = '') {
  const element = $(selector);
  if (element.textContent !== text) element.textContent = text;
  element.className = `message ${type}`;
  element.setAttribute('aria-live', type === 'error' ? 'assertive' : 'polite');
}
async function api(path, options = {}) {
  const settings = { ...options, signal: AbortSignal.timeout(60000) };
  if (settings.body && !(settings.body instanceof FormData)) { settings.body = JSON.stringify(settings.body); settings.headers = { 'Content-Type': 'application/json' }; }
  let response;
  try { response = await fetch(path, settings); }
  catch { throw new Error('Cannot reach the local model engine. Check that ./run.sh is running, then try again.'); }
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : (data.detail || []).map(x => x.msg).join('; ') || 'The request could not be completed.');
  return data;
}
function table(headers, rows, numeric = [], highlight = -1) {
  const head = node('thead', {}, node('tr', {}, headers.map(label => node('th', { scope: 'col' }, label))));
  const body = node('tbody', {}, rows.map((row, index) => node('tr', { class: index === highlight ? 'recommended' : '' }, row.map((value, i) => node('td', { class: numeric.includes(i) ? 'numeric' : '' }, value ?? '—')))));
  return node('div', { class: 'table-wrap', tabindex: '0', 'aria-label': 'Scrollable data table' }, node('table', {}, head, body));
}
function rawTable(rows, columns) { return table(columns, rows.map(row => columns.map(column => typeof row[column] === 'number' ? format(row[column], 3) : row[column] ?? ''))); }
function statistics(selector, values) { $(selector).replaceChildren(...values.map(([value, label]) => node('div', {}, node('strong', {}, value), node('span', {}, label)))); }
function saveFile(filename, content, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = node('a', { href: url, download: filename });
  document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function csv(rows) { return rows.map(row => row.map(value => { let text = String(value ?? ''); if (typeof value === 'string' && /^[=+\-@\t\r\n]/.test(text)) text = `'${text}`; return `"${text.replaceAll('"', '""')}"`; }).join(',')).join('\r\n'); }

function setOptions(select, values, label, desired) {
  select.replaceChildren(...values.map(value => node('option', { value }, label(value))));
  select.value = values.some(value => String(value) === String(desired)) ? String(desired) : String(values[0]);
}
function createDesign(container, initialId, onChange) {
  const selects = {};
  for (const [key, label] of [['shape', 'Building shape'], ['X6', 'Orientation'], ['X7', 'Glazing / floor area'], ['X8', 'Glazing distribution']]) {
    const control = node('select', { id: `${container.id}-${key}`, name: key, required: true });
    selects[key] = control;
    container.append(node('label', { for: control.id }, label, control));
    control.addEventListener('change', sync);
  }
  let selected;
  function sync() {
    let rows = catalog.records.filter(row => row.shape_id === Number(selects.shape.value));
    for (const key of ['X6', 'X7', 'X8']) {
      const values = [...new Set(rows.map(row => row[key]))].sort((a, b) => a - b);
      setOptions(selects[key], values, value => key === 'X6' ? `Orientation ${value}` : key === 'X7' ? `${Math.round(value * 100)}%` : distributions[value], selects[key].value);
      selects[key].disabled = key === 'X8' && values.length === 1;
      rows = rows.filter(row => row[key] === Number(selects[key].value));
    }
    selected = rows[0];
    onChange?.(selected);
  }
  function setRow(rowId) {
    const row = catalog.records.find(item => item.row_id === rowId);
    setOptions(selects.shape, catalog.shapes.map(shape => shape.id), id => { const shape = catalog.shapes.find(item => item.id === id); return `${shape.label} · compactness ${shape.X1.toFixed(2)}`; }, row.shape_id);
    for (const key of ['X6', 'X7', 'X8']) { selects[key].replaceChildren(node('option', { value: row[key] }, row[key])); selects[key].value = String(row[key]); }
    sync();
  }
  setRow(initialId);
  return { getRow: () => selected, setRow };
}

function showGeometry(row) {
  const labels = ['Compactness', 'Surface area', 'Wall area', 'Roof area', 'Height'];
  $('#design-geometry').replaceChildren(...features.slice(0, 5).map((key, i) => node('div', {}, labels[i], node('strong', {}, format(row[key], key === 'X5' ? 1 : 2)))));
  $('.drawing-glazing').setAttribute('opacity', row.X7 === 0 ? '0' : String(0.45 + row.X7));
  $('#glazing-readout').textContent = `${Math.round(row.X7 * 100)}% glazing / floor area`;
  $('#prediction-output').hidden = true;
  $('#prediction-placeholder').hidden = false;
  $('#prediction-record').textContent = `RECORD ${row.row_id} / READY`;
  message('#prediction-message', 'Configuration ready. Run the models to see its response.');
}
async function runPrediction(event) {
  event?.preventDefault();
  const rowId = predictor.getRow().row_id;
  const button = $('#predict-form button');
  const animate = motionAllowed();
  setBusy(button, true, 'Predicting…'); $('#prediction-output').hidden = true;
  message('#prediction-message', 'Running the six frozen model pipelines…');
  try {
    const result = await api('/api/predict', { method: 'POST', body: { row_ids: [rowId] } });
    if (predictor.getRow().row_id !== rowId) return;
    latestPrediction = result;
    const row = result.predictions[0];
    $('#heating-value').textContent = format(row.models.RF.heating, 2);
    $('#cooling-value').textContent = format(row.models.RF.cooling, 2);
    $('#inference-time').textContent = `${format(result.inference_ms, 1)} ms · 6 pipelines`;
    $('#prediction-record').textContent = `RECORD ${rowId} / ${row.partition === 'test' ? 'HELD OUT' : 'DEVELOPMENT'}`;
    $('#prediction-table').replaceChildren(table(['Model', 'Heating', 'Cooling'], methods.map(method => [methodNames[method], format(row.models[method].heating), format(row.models[method].cooling)]), [1, 2], 2));
    $('#prediction-reference').replaceChildren(node('p', {}, `Simulated heating: ${format(row.reference.heating)}. Simulated cooling: ${format(row.reference.cooling)}. This record ${row.partition === 'test' ? 'was excluded from development training and tuning' : 'was available during development training'}.`));
    message('#prediction-message'); $('#prediction-placeholder').hidden = true; $('#prediction-output').hidden = false;
    if (animate) reveal($('#prediction-output'));
  } catch (error) { message('#prediction-message', error.message, 'error'); }
  finally { setBusy(button, false); }
}
async function runComparison(event) {
  event.preventDefault();
  const ids = [compareA.getRow().row_id, compareB.getRow().row_id];
  const button = $('#compare-form button[type=submit]'), animate = motionAllowed(); setBusy(button, true, 'Comparing…');
  $('#compare-output').hidden = true; message('#compare-message', 'Evaluating both designs with the same models…');
  try {
    const result = await api('/api/predict', { method: 'POST', body: { row_ids: ids } });
    if (ids[0] !== compareA.getRow().row_id || ids[1] !== compareB.getRow().row_id) return;
    latestComparison = result;
    const [a, b] = result.predictions;
    $('#comparison-table').replaceChildren(table(['Model', 'A · heating', 'B · heating', 'Δ heating', 'A · cooling', 'B · cooling', 'Δ cooling'], methods.map(method => {
      const first = a.models[method], second = b.models[method];
      return [methodNames[method], format(first.heating), format(second.heating), format(second.heating - first.heating), format(first.cooling), format(second.cooling), format(second.cooling - first.cooling)];
    }), [1, 2, 3, 4, 5, 6]));
    $('#comparison-reference').replaceChildren(node('span', { class: 'note-index' }, 'SIMULATED REFERENCES / ORIGINAL DATASET LOAD UNITS'), node('p', {}, `A · record ${a.row_id} (${a.partition}): heating ${format(a.reference.heating)}, cooling ${format(a.reference.cooling)}. B · record ${b.row_id} (${b.partition}): heating ${format(b.reference.heating)}, cooling ${format(b.reference.cooling)}. Differences describe model outputs, not verified energy savings.`));
    message('#compare-message'); $('#compare-output').hidden = false;
    if (animate) reveal($('#compare-output'));
  } catch (error) { message('#compare-message', error.message, 'error'); }
  finally { setBusy(button, false); }
}
function predictionExport(result, filename) {
  if (!result) return;
  const rows = [['record', 'partition', ...features, 'model', 'heating_predicted', 'cooling_predicted', 'heating_simulated', 'cooling_simulated']];
  for (const record of result.predictions) for (const method of methods) rows.push([record.row_id, record.partition, ...features.map(key => record.features[key]), method, record.models[method].heating, record.models[method].cooling, record.reference.heating, record.reference.cooling]);
  if (result.predictions.length === 2) {
    const [a, b] = result.predictions;
    for (const method of methods) rows.push(['B minus A', '', ...features.map(key => b.features[key] - a.features[key]), method, b.models[method].heating - a.models[method].heating, b.models[method].cooling - a.models[method].cooling, b.reference.heating - a.reference.heating, b.reference.cooling - a.reference.cooling]);
  }
  saveFile(filename, csv(rows), 'text/csv');
}

function protocolChart(target) {
  const svg = svgNode('svg', { viewBox: '0 0 440 190', role: 'img', 'aria-label': 'Mean absolute errors for random holdout and unseen-shape validation; values appear in the adjacent table.' });
  const rows = methods.map(method => [method, studyData.primary.find(row => row.target === target && row.model === method).MAE, studyData.shape.find(row => row.target === target && row.model === method).MAE]);
  const max = Math.max(...rows.flatMap(row => row.slice(1))) * 1.15;
  rows.forEach(([method, familiar, shape], index) => {
    const y = 15 + index * 58;
    svg.append(svgNode('text', { x: 0, y: y + 18, class: 'chart-label' }, method));
    for (const [value, offset, className] of [[familiar, 0, 'bar-familiar'], [shape, 19, 'bar-shape']]) {
      const width = value / max * 320;
      svg.append(svgNode('rect', { x: 55, y: y + offset, width, height: 13, rx: 1, class: className }), svgNode('text', { x: 62 + width, y: y + offset + 11, class: 'chart-value' }, format(value)));
    }
  });
  return node('div', { class: 'chart' }, svg);
}
function importanceChart(rows) {
  const svg = svgNode('svg', { viewBox: '0 0 440 280', role: 'img', 'aria-label': 'Random Forest permutation importance; values are also listed in the table.' });
  const max = Math.max(...rows.map(row => row.MAE_increase)) * 1.2;
  rows.forEach((row, index) => {
    const y = 9 + index * 34, width = Math.max(1, row.MAE_increase / max * 225);
    svg.append(svgNode('text', { x: 0, y: y + 12, class: 'chart-label' }, row.label), svgNode('rect', { x: 150, y, width, height: 17, rx: 1, class: 'bar-familiar' }), svgNode('text', { x: 157 + width, y: y + 12, class: 'chart-value' }, format(row.MAE_increase, 2)));
  });
  return node('div', { class: 'chart' }, svg);
}
function renderStudyTarget(target) {
  const primary = studyData.primary.filter(row => row.target === target);
  const shape = studyData.shape.filter(row => row.target === target);
  $('#protocol-chart').replaceChildren(protocolChart(target));
  $('#study-metrics').replaceChildren(table(['Protocol', 'Model', 'MAE', 'RMSE', 'R²'], [...primary.map(row => ['Holdout', row.model, format(row.MAE), format(row.RMSE), format(row.R2, 4)]), ...shape.map(row => ['Unseen shape', row.model, format(row.MAE), format(row.RMSE), format(row.R2, 4)])], [2, 3, 4]));
  const importance = studyData.importance.filter(row => row.target === target).sort((a, b) => b.MAE_increase - a.MAE_increase);
  $('#importance-chart').replaceChildren(importanceChart(importance));
  $('#importance-table').replaceChildren(table(['Input', 'Δ MAE', 'Permutation SD'], importance.map(row => [row.label, format(row.MAE_increase), format(row.sd)]), [1, 2]));
  $('#fold-table').replaceChildren(table(['Shape', 'Model', 'Records', 'MAE', 'RMSE', 'R²'], studyData.folds.filter(row => row.target === target).map(row => [String(row.shape_group + 1).padStart(2, '0'), row.model, row.n, format(row.MAE), format(row.RMSE), format(row.R2)]), [2, 3, 4, 5]));
  reveal($('#protocol-chart')); reveal($('#importance-chart'));
}
async function loadStudy() {
  if (studyData) return;
  message('#study-message', 'Loading the completed local experiment…');
  try {
    studyData = await api('/api/results');
    const info = studyData.metadata;
    statistics('#study-statistics', [[info.rows, 'SIMULATED CONFIGURATIONS'], [info.shapes, 'SHAPE FAMILIES'], [info.test_n, 'LOCKED TEST RECORDS'], ['5 + 3', 'PRIMARY + INNER GROUP FOLDS']]);
    renderStudyTarget('Y1');
    $('#glazing-table').replaceChildren(table(['Glazing', 'Heating · simulated', 'Heating · RF', 'Cooling · simulated', 'Cooling · RF'], studyData.demonstration.map(row => [`${Math.round(row.X7 * 100)}%`, format(row.Y1, 2), format(row.Y1_predicted, 2), format(row.Y2, 2), format(row.Y2_predicted, 2)]), [1, 2, 3, 4]));
    $('#timing-table').replaceChildren(table(['Target', 'Model', 'Fit median · ms', 'Fit IQR · ms', 'Predict median · ms', 'Predict IQR · ms', 'Batch median · ms'], studyData.primary.filter(row => row.model !== 'Mean baseline').map(row => [row.target === 'Y1' ? 'Heating' : 'Cooling', row.model, ...['fit_median_ms', 'fit_iqr_ms', 'single_median_ms', 'single_iqr_ms', 'batch_median_ms'].map(key => format(row[key], 2))]), [2, 3, 4, 5, 6]));
    const captions = ['Heating: held-out predictions and residuals', 'Cooling: held-out predictions and residuals', 'MAE for each excluded building shape'];
    $('#diagnostic-figures').replaceChildren(...studyData.figures.map((src, index) => node('figure', {}, node('img', { src, alt: captions[index], loading: 'lazy' }), node('figcaption', { class: 'fine-print' }, captions[index]))));
    $('#run-provenance').replaceChildren(node('div', { class: 'provenance-grid' }, [['SEED', info.seed], ['PYTHON', info.python.split(' ')[0]], ['SCIKIT-LEARN', info.sklearn], ['NUMPY / PANDAS', `${info.numpy} / ${info.pandas}`], ['LOCAL RUN TIME', `${format(info.total_seconds, 1)} seconds`], ['SOURCE CHECKSUM · SHA256', info.data_sha256]].map(([label, value]) => node('div', {}, node('span', {}, label), node('strong', {}, value)))));
    const reference = { 'Y1 RF holdout': 0.356, 'Y2 RF holdout': 1.202, 'Y1 MLR unseen': 3.473, 'Y2 MLR unseen': 3.926 };
    $('#paper-comparison').replaceChildren(table(['MAE check', 'Paper', 'This run', 'At paper precision'], Object.entries(reference).map(([key, expected]) => { const [target, method, protocol] = key.split(' '); const measured = (protocol === 'holdout' ? studyData.primary : studyData.shape).find(row => row.target === target && row.model === method).MAE; return [key, format(expected), format(measured), measured.toFixed(3) === expected.toFixed(3) ? 'Matches' : 'Different · retain measured result']; }), [1, 2]));
    $('#study-content').hidden = false; message('#study-message'); reveal($('#study-content'));
  } catch (error) {
    studyData = null; message('#study-message', error.message, 'error');
    const retry = node('button', { type: 'button', class: 'text-button' }, 'Try again →');
    retry.addEventListener('click', loadStudy); $('#study-message').append(node('br'), retry);
  }
}

function invalidateDataset() {
  lastValidation = null;
  $('#evaluate-button').disabled = true;
  $('#validation-output').hidden = true;
  $('#dataset-results').hidden = true;
  datasetStep(1); mappingStatus();
  $('#dataset-next-action').textContent = 'Validate the updated mappings before running a new test.';
  message('#dataset-message', 'Mapping or metadata changed. Validate before running a new test.');
}
function getConfig() {
  const mapping = {};
  for (const select of document.querySelectorAll('#column-mapping select, #reference-mapping select')) if (select.value) mapping[select.name] = select.value;
  return { mapping, source_type: $('#dataset-source').value, response_units: $('#response-units').value.trim(), response_definition: $('#response-definition').value.trim(), comparable: $('#confirm-comparable').checked, skip_invalid_rows: $('#skip-invalid').checked };
}
function mappingSuggestion(columns, key) {
  const normalize = value => value.toLowerCase().replace(/[^a-z0-9]/g, '');
  const aliases = [key, names[key], key === 'Y1' ? 'heatingload' : key === 'Y2' ? 'coolingload' : ''];
  return columns.find(column => aliases.filter(Boolean).some(alias => normalize(column) === normalize(alias))) || '';
}
function showDataset(data) {
  currentDataset = data; currentReport = null; lastValidation = null;
  $('#dataset-editor').hidden = false; $('#dataset-results').hidden = true; $('#validation-output').hidden = true;
  $('#evaluate-button').disabled = true; $('#skip-invalid-label').hidden = true; $('#skip-invalid').checked = false;
  $('#dataset-name').textContent = data.name;
  $('#dataset-size').textContent = `${data.rows.toLocaleString()} records / ${data.columns.length} columns`;
  $('#dataset-sheet').textContent = `${data.sheet ? `First worksheet: ${data.sheet}. ` : 'UTF-8 CSV. '}${data.blank_rows ? `${data.blank_rows} blank rows excluded. ` : ''}Original file retained locally. Source row numbers include the header.`;
  $('#source-preview').replaceChildren(table(data.columns.map(column => node('span', {}, column, node('small', { class: 'column-type' }, data.types[column]))), data.preview.map(row => data.columns.map(column => row[column] ?? ''))));
  const controls = [], referenceControls = [];
  for (const key of [...features, 'Y1', 'Y2']) {
    const control = node('select', { id: `map-${key}`, name: key, required: features.includes(key) });
    control.append(node('option', { value: '' }, features.includes(key) ? 'Select a source column' : 'Not supplied · predictions only'));
    control.append(...data.columns.map(column => node('option', { value: column }, column)));
    control.value = data.config ? (data.config.mapping[key] || '') : mappingSuggestion(data.columns, key);
    const label = node('label', { for: control.id }, node('span', { class: 'field-label' }, node('span', { class: 'field-code' }, key), names[key]), control);
    (features.includes(key) ? controls : referenceControls).push(label);
  }
  $('#column-mapping').replaceChildren(...controls);
  $('#reference-mapping').replaceChildren(...referenceControls);
  $('#dataset-source').value = data.config?.source_type || 'unknown';
  $('#response-units').value = data.config?.response_units || '';
  $('#response-definition').value = data.config?.response_definition || '';
  $('#confirm-comparable').checked = data.config?.comparable || false;
  $('#reference-options').open = [...document.querySelectorAll('#reference-mapping select')].some(control => control.value);
  datasetStep(1); mappingStatus();
  $('#dataset-next-action').textContent = 'Review the mappings, then validate to enable testing.';
  message('#dataset-message', 'Review all eight input mappings. Reference columns and comparable units are needed only for error scores.');
  reveal($('#dataset-editor'));
}
async function refreshLibrary() {
  try {
    const items = await api('/api/datasets');
    if (!items.length) { $('#dataset-library').replaceChildren(node('div', { class: 'library-empty' }, node('strong', {}, 'Your experiments start here.'), node('p', {}, 'Import a file or try the simulated example. Your datasets and latest results will appear here.'))); return; }
    $('#dataset-library').replaceChildren(...items.map(item => {
      const button = node('button', { type: 'button', class: 'text-button', 'aria-label': `Open ${item.name}` }, item.has_results ? 'Open saved evaluation →' : 'Continue mapping →');
      button.addEventListener('click', () => openDataset(item.id));
      return node('div', { class: 'library-item' }, node('strong', {}, item.name), node('span', {}, `${item.rows.toLocaleString()} records · ${new Date(item.created_at).toLocaleDateString()}`), button);
    }));
  } catch (error) { $('#dataset-library').replaceChildren(node('p', { class: 'fine-print' }, error.message)); }
}
async function openDataset(id) {
  const request = ++openRequest;
  message('#upload-message', 'Opening the saved local dataset…');
  try {
    const data = await api(`/api/datasets/${id}`);
    if (request !== openRequest) return;
    showDataset(data);
    if (data.config) {
      const report = await api(`/api/datasets/${id}/results`);
      if (request !== openRequest || currentDataset.id !== id) return;
      showEvaluation(report);
    }
    message('#upload-message'); focusPanel(data.config ? '#dataset-results' : '#dataset-editor');
  } catch (error) { if (request === openRequest) message('#upload-message', error.message, 'error'); }
}
function selectedFile() {
  const file = $('#dataset-file').files[0];
  $('#file-picker-label').textContent = file?.name || 'Drop your dataset here';
  $('#selected-filename').textContent = file ? `${format(file.size / 1024, 1)} KiB · ready to inspect` : 'Excel imports use the first worksheet.';
}
async function uploadDataset(event, example = false) {
  event?.preventDefault();
  if (importing) return;
  importing = true; ++openRequest;
  const button = $('#upload-button'), demo = $('#try-example');
  setBusy(button, true, example ? 'Preparing example…' : 'Inspecting…'); setBusy(demo, true, 'Please wait…');
  try {
    if (example) {
      message('#upload-message', 'Loading four simulated records from the prepared local study…');
      const response = await fetch('/api/template/example', { signal: AbortSignal.timeout(60000) });
      if (!response.ok) throw new Error('The simulated example could not load. Check the local model engine and try again.');
      const transfer = new DataTransfer();
      transfer.items.add(new File([await response.blob()], 'SIMULATED-demo-data.csv', { type: 'text/csv' }));
      $('#dataset-file').files = transfer.files; selectedFile();
    }
    const file = $('#dataset-file').files[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024 || !file.size || !/\.(csv|xlsx)$/i.test(file.name)) throw new Error('Choose a nonempty CSV or XLSX file up to 5 MiB.');
    message('#upload-message', 'Reading the file and inspecting its first table…');
    const body = new FormData(); body.append('file', file);
    const data = await api('/api/datasets', { method: 'POST', body });
    showDataset(data);
    if (example) {
      $('#dataset-source').value = 'simulation'; $('#response-units').value = 'Original dataset load units';
      $('#response-definition').value = 'UCI Energy Efficiency simulated Y1 and Y2';
    }
    message('#upload-message', 'Imported locally. Review the column mappings below.'); await refreshLibrary(); focusPanel('#dataset-editor');
  } catch (error) { message('#upload-message', error.message, 'error'); }
  finally { importing = false; setBusy(button, false); setBusy(demo, false); }
}
async function validateDataset() {
  if (!currentDataset || !$('#mapping-form').reportValidity()) return;
  $('#evaluate-button').disabled = true; setBusy($('#validate-button'), true, 'Checking columns…');
  $('#dataset-results').hidden = true;
  const config = getConfig(), snapshot = JSON.stringify(config), id = currentDataset.id;
  message('#dataset-message', 'Checking mapped values, categories, ranges, and reference coverage…');
  try {
    const report = await api(`/api/datasets/${id}/validate`, { method: 'POST', body: config });
    if (id !== currentDataset.id || snapshot !== JSON.stringify(getConfig())) return;
    lastValidation = report;
    const box = $('#validation-output');
    const stats = node('div', { class: 'stat-strip small' });
    stats.append(...[[report.total_rows, 'IMPORTED'], [report.valid_rows, 'VALID INPUTS'], [report.invalid_rows, 'INVALID INPUTS'], [report.warning_rows, 'ROWS WITH NOTICES']].map(([value, label]) => node('div', {}, node('strong', {}, value), node('span', {}, label))));
    const explanation = node('p', { class: 'fine-print' }, report.metrics_enabled ? 'Reference scoring is enabled by your comparability declaration. Its scientific validity depends on those definitions and units being correct.' : 'Prediction-only mode. Error scores require valid reference loads, their units and definition, and your comparability confirmation.');
    const issues = node('div', { class: 'validation-issues' });
    for (const issue of report.issues) issues.append(node('div', { class: 'validation-row' }, node('span', { class: 'mono' }, `Row ${issue.source_row}`), node('div', {}, issue.errors.length ? node('p', { class: 'row-errors' }, issue.errors.join('; ')) : null, issue.warnings.length ? node('p', {}, issue.warnings.join('; ')) : null)));
    box.replaceChildren(stats, explanation, issues, node('p', { class: 'fine-print' }, `${report.development_matches} input configurations match development data; ${report.test_matches} match held-out data. Input matches alone do not prove an observation is a duplicate. Showing up to 100 issue rows; the CSV preserves every record.`));
    box.hidden = false;
    $('#skip-invalid-label').hidden = report.invalid_rows === 0;
    $('#evaluate-button').disabled = !report.valid_rows || (report.invalid_rows > 0 && !$('#skip-invalid').checked);
    $('#dataset-next-action').textContent = !report.valid_rows ? 'Correct the invalid inputs and import the updated file.' : report.invalid_rows ? 'Choose whether to evaluate valid rows only, then run the test.' : report.metrics_enabled ? 'Ready to compare model predictions with your reference loads.' : 'Ready for batch predictions. Reference scoring is optional.';
    message('#dataset-message', report.invalid_rows ? 'Review the invalid inputs. Correct the file or explicitly evaluate valid rows only.' : 'Input validation passed. Notices identify domain limits; they do not stop a valid external-data experiment.', report.invalid_rows ? 'warning' : '');
  } catch (error) { lastValidation = null; $('#validation-output').hidden = true; message('#dataset-message', error.message, 'error'); }
  finally { setBusy($('#validate-button'), false); }
}
function scatterPlot(rows, target, predicted, residual = false) {
  const points = rows.filter(row => row.status === 'predicted' && Number.isFinite(row[target]) && Number.isFinite(row[predicted])).slice(0, 300);
  if (!points.length) return node('p', { class: 'fine-print' }, 'No usable reference pairs for this response.');
  const xs = points.map(row => residual ? row[predicted] : row[target]);
  const ys = points.map(row => residual ? row[predicted] - row[target] : row[predicted]);
  let low = residual ? Math.min(...xs) : Math.min(...xs, ...ys), high = residual ? Math.max(...xs) : Math.max(...xs, ...ys);
  if (low === high) { low -= 1; high += 1; }
  let yLow = residual ? Math.min(0, ...ys) : low, yHigh = residual ? Math.max(0, ...ys) : high;
  if (yLow === yHigh) { yLow -= 1; yHigh += 1; }
  const scaleX = value => (value - low) / (high - low) * 225, scaleY = value => (value - yLow) / (yHigh - yLow) * 225;
  const svg = svgNode('svg', { viewBox: '0 0 310 295', role: 'img', 'aria-label': residual ? 'Random Forest residuals: prediction minus reference, with a zero-error line.' : 'Random Forest predictions versus uploaded reference values, with a diagonal agreement line.' });
  svg.append(svgNode('line', { x1: 48, y1: residual ? 246 - scaleY(0) : 246, x2: 273, y2: residual ? 246 - scaleY(0) : 21, stroke: 'var(--clay)', 'stroke-dasharray': '4 4' }), svgNode('path', { d: 'M48 20V246H280', class: 'chart-axis', fill: 'none' }));
  points.forEach((row, index) => svg.append(svgNode('circle', { cx: 48 + scaleX(xs[index]), cy: 246 - scaleY(ys[index]), r: 3, fill: 'var(--teal)', opacity: '.6' })));
  svg.append(svgNode('text', { x: 165, y: 285, 'text-anchor': 'middle', class: 'chart-label' }, residual ? 'RF prediction' : 'Uploaded reference'), svgNode('text', { x: 12, y: 145, 'text-anchor': 'middle', transform: 'rotate(-90 12 145)', class: 'chart-label' }, residual ? 'Prediction − reference' : 'RF prediction'), svgNode('text', { x: 48, y: 265, class: 'chart-value' }, format(low, 1)), svgNode('text', { x: 273, y: 265, 'text-anchor': 'end', class: 'chart-value' }, format(high, 1)));
  return node('div', { class: 'chart' }, svg, node('p', { class: 'fine-print' }, `Up to 300 reference pairs shown. Full values and all models are included in the CSV.`));
}
function showEvaluation(report) {
  currentReport = report;
  $('#dataset-results').hidden = false;
  $('#evaluation-mode').textContent = report.metrics.length ? 'Reference evaluation' : 'Predictions only';
  $('#dataset-evaluation-note').textContent = `${report.notice} ${report.comparability} Latest saved run: ${new Date(report.evaluated_at).toLocaleString()}.`;
  statistics('#evaluation-statistics', [[report.valid_rows, 'PREDICTED'], [report.invalid_rows, 'REJECTED'], [report.metrics.length ? '3' : '—', 'MODELS WITH ERROR SCORES'], [format(report.inference_ms, 0), 'BATCH INFERENCE · MS']]);
  const scores = $('#dataset-score-table');
  scores.replaceChildren(report.metrics.length ? table(['Target', 'Model', 'Reference n', 'MAE', 'RMSE', 'R²'], report.metrics.map(row => [row.target === 'Y1' ? 'Heating' : 'Cooling', row.model, row.n, format(row.MAE), format(row.RMSE), row.R2 == null ? 'N/A · fewer than 2 or constant references' : format(row.R2, 4)]), [2, 3, 4, 5]) : node('p', { class: 'message' }, 'Predictions are available. No accuracy or error scores are claimed without comparable reference loads.'));
  const plots = $('#dataset-plots'); plots.replaceChildren();
  if (report.metrics.length) for (const [target, title] of [['Y1', 'Heating'], ['Y2', 'Cooling']]) if (report.reference_counts[target]) {
    plots.append(node('div', {}, node('h3', {}, `${title} · RF prediction`), scatterPlot(report.rows, target, `RF_${target}_predicted`)), node('div', {}, node('h3', {}, `${title} · RF residuals`), scatterPlot(report.rows, target, `RF_${target}_predicted`, true)));
  }
  const columns = ['source_row', 'status', 'benchmark_match', 'RF_Y1_predicted', 'RF_Y2_predicted', 'Y1', 'Y2', 'issues'].filter(key => key in report.rows[0]);
  $('#dataset-predictions').replaceChildren(rawTable(report.rows.slice(0, 100), columns), node('p', { class: 'fine-print' }, `Showing ${Math.min(report.rows.length, 100)} of ${report.rows.length} records. The CSV includes all inputs, models, and rejected records.`));
  $('#dataset-csv').href = `/api/datasets/${report.dataset_id}/results.csv`;
  datasetStep(2); reveal($('#dataset-results'));
}
async function evaluateDataset(event) {
  event.preventDefault();
  if (!currentDataset || !lastValidation) return;
  const button = $('#evaluate-button'), config = getConfig(), snapshot = JSON.stringify(config), id = currentDataset.id;
  const animate = motionAllowed();
  setBusy(button, true, 'Testing records…'); $('#dataset-results').hidden = true;
  message('#dataset-message', 'Running batch inference. The study models are frozen; no training is performed.');
  try {
    const report = await api(`/api/datasets/${id}/evaluate`, { method: 'POST', body: config });
    if (id !== currentDataset.id || snapshot !== JSON.stringify(getConfig())) return;
    showEvaluation(report); if (!animate) $('#dataset-results').getAnimations().forEach(animation => animation.cancel());
    message('#dataset-message', `Evaluation saved locally. ${report.valid_rows} records predicted; ${report.invalid_rows} rejected.`);
    $('#dataset-next-action').textContent = 'Results are saved. Change inputs and validate again to run another test.';
    await refreshLibrary(); focusPanel('#dataset-results');
  } catch (error) { message('#dataset-message', error.message, 'error'); }
  finally { setBusy(button, false); button.disabled = !lastValidation || !lastValidation.valid_rows || (lastValidation.invalid_rows > 0 && !$('#skip-invalid').checked); }
}

function navigate(focus = false) {
  const requested = location.hash.slice(1), view = ['predict', 'compare', 'study', 'datasets'].includes(requested) ? requested : 'predict';
  const changed = activeView !== view;
  if (changed && activeView) $(`#view-${activeView}`).getAnimations({ subtree: true }).forEach(animation => animation.cancel());
  for (const section of document.querySelectorAll('.view')) section.hidden = section.id !== `view-${view}`;
  for (const link of document.querySelectorAll('nav a')) { if (link.dataset.view === view) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current'); }
  if (focus) { $(`#${view}-title`).focus({ preventScroll: true }); window.scrollTo(0, 0); }
  if (catalog && (changed || !introduced)) {
    const section = $(`#view-${view}`);
    reveal(section.querySelector('.page-intro'), true);
    section.querySelectorAll('.workspace-grid > .panel, .compare-designs > .panel, .import-panel').forEach((panel, index) => reveal(panel, true, 30 * (index + 1)));
    introduced = true;
  }
  activeView = view;
  if (catalog && view === 'study') loadStudy();
  if (catalog && view === 'datasets') refreshLibrary();
}
async function initialize() {
  navigate();
  try {
    catalog = await api('/api/catalog');
    const health = await api('/api/health'); $('#engine-status').textContent = `${health.models} models · ${health.shared ? 'shared' : 'local'}`;
    if (health.shared) {
      $('#view-datasets .local-badge').replaceChildren(node('span', { class: 'status-dot' }), 'Uploads are visible to visitors with this link');
      $('.import-panel .tag').textContent = 'Shared workspace';
      $('.library-panel > .fine-print').textContent = 'Uploads and latest results are shared with everyone who has this link. Use non-sensitive data.';
    }
    predictor = createDesign($('#predict-form'), 2, showGeometry);
    $('#predict-form').append(node('div', { class: 'form-submit' }, node('button', { type: 'submit', class: 'button primary' }, node('span', { class: 'button-label' }, 'Run predictions'), node('span', { class: 'button-arrow', 'aria-hidden': 'true' }, '→')), node('small', {}, 'All three models. Two responses.')));
    compareA = createDesign($('#compare-a'), 332, () => { $('#compare-output').hidden = true; });
    compareB = createDesign($('#compare-b'), 572, () => { $('#compare-output').hidden = true; });
    $('#predict-form').addEventListener('submit', runPrediction);
    $('#compare-form').addEventListener('submit', runComparison);
    $('#prediction-export').addEventListener('click', () => predictionExport(latestPrediction, 'building-predictions.csv'));
    $('#compare-export').addEventListener('click', () => predictionExport(latestComparison, 'design-comparison.csv'));
    $('#use-in-compare').addEventListener('click', () => { compareA.setRow(predictor.getRow().row_id); location.hash = 'compare'; });
    for (const input of document.querySelectorAll('[name=study-target]')) input.addEventListener('change', () => { if (studyData) renderStudyTarget(input.value); });
    $('#upload-form').addEventListener('submit', uploadDataset);
    $('#try-example').addEventListener('click', event => uploadDataset(event, true));
    $('#dataset-file').addEventListener('change', selectedFile);
    const picker = $('.file-picker');
    for (const eventName of ['dragenter', 'dragover']) picker.addEventListener(eventName, event => {
      if (event.dataTransfer?.types.includes('Files')) { event.preventDefault(); picker.classList.add('is-dragging'); }
    });
    picker.addEventListener('dragleave', event => { if (!picker.contains(event.relatedTarget)) picker.classList.remove('is-dragging'); });
    picker.addEventListener('drop', event => {
      event.preventDefault(); picker.classList.remove('is-dragging');
      if (event.dataTransfer.files.length !== 1) { message('#upload-message', 'Choose one CSV or XLSX file at a time.', 'error'); return; }
      $('#dataset-file').files = event.dataTransfer.files; selectedFile();
    });
    $('#mapping-form').addEventListener('submit', evaluateDataset);
    $('#mapping-form').addEventListener('invalid', event => { const details = event.target.closest('details'); if (details) details.open = true; }, true);
    $('#mapping-form').addEventListener('change', event => { if (event.target.id !== 'skip-invalid') invalidateDataset(); });
    for (const input of [$('#response-units'), $('#response-definition')]) input.addEventListener('input', invalidateDataset);
    $('#skip-invalid').addEventListener('change', () => { $('#evaluate-button').disabled = !lastValidation || !lastValidation.valid_rows || (lastValidation.invalid_rows > 0 && !$('#skip-invalid').checked); });
    $('#validate-button').addEventListener('click', validateDataset);
    $('#dataset-json').addEventListener('click', () => { if (currentReport) saveFile(`dataset-${currentReport.dataset_id.slice(0, 8)}-report.json`, JSON.stringify(currentReport, null, 2)); });
    navigate(); await runPrediction();
  } catch (error) {
    $('#engine-status').textContent = 'Engine unavailable';
    const box = $('#connection-error'), retry = node('button', { type: 'button', class: 'button secondary' }, 'Reconnect');
    retry.addEventListener('click', () => location.reload());
    box.replaceChildren(node('p', {}, error.message), retry); box.hidden = false;
  }
}
window.addEventListener('hashchange', () => navigate(true));
initialize();
