/** Demo UI for document extraction. */

const SCALAR_FIELD_TYPES = ["string", "integer", "float", "number", "boolean", "date"];
const LIST_COLUMN_TYPES = ["string", "integer", "float", "number", "boolean"];
const FIELD_KEY_RE = /^[a-zA-Z0-9_.-]{1,64}$/;

const TABLE_HEAD = `
  <thead>
    <tr>
      <th>Label</th>
      <th>Key</th>
      <th>Description</th>
      <th>Type</th>
      <th class="col-action"></th>
    </tr>
  </thead>
`;

const demoSelect = document.getElementById("demo-select");
const modelSelect = document.getElementById("model-select");
const backendSelect = document.getElementById("backend-select");

const BACKEND_STORAGE_KEY = "extractor-backend";
const DEFAULT_MODEL_ID = "deepseek-v3.2";
const DEFAULT_BACKEND = "api";

const state = {
  file: null,
  fields: [],
  jobId: null,
  pollTimer: null,
  demos: [],
  activeDemoId: null,
};

const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");
const fileInfo = document.getElementById("file-info");
const fieldBuilder = document.getElementById("field-builder");
const activityFeed = document.getElementById("activity-feed");

const ACTIVITY_SOURCES = ["pipeline", "agent", "tool"];

const activityState = {
  activeSource: null,
  streamBuffer: "",
};

function eventSource(event) {
  const s = event.source || "pipeline";
  return ACTIVITY_SOURCES.includes(s) ? s : "pipeline";
}

function isActivityNoise(event) {
  return event.type === "heartbeat" || event.type === "agent_text_delta";
}

function activityMessage(event) {
  if (event.type === "heartbeat") return event.message || "Still working…";
  if (event.type === "agent_text_delta") {
    activityState.streamBuffer = (activityState.streamBuffer + (event.message || "")).slice(-100);
    return activityState.streamBuffer.trim() || "Streaming…";
  }
  activityState.streamBuffer = "";
  return event.message || event.type;
}

function formatTrailRoute(from, to) {
  if (!from || from === to) {
    return `<span class="${to}">${escapeHtml(to)}</span>`;
  }
  return `<span class="${from}">${escapeHtml(from)}</span> → <span class="${to}">${escapeHtml(to)}</span>`;
}

function resetActivity() {
  activityState.activeSource = null;
  activityState.streamBuffer = "";
}
const resultsEl = document.getElementById("results");
const rawJson = document.getElementById("raw-json");
const costFooter = document.getElementById("cost-footer");
const btnExtract = document.getElementById("btn-extract");

function uid() {
  return Math.random().toString(36).slice(2, 9);
}

function slugify(text) {
  return text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 64);
}

function escAttr(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;");
}

function typeOptions(selected, types) {
  return types
    .map((t) => `<option value="${t}" ${selected === t ? "selected" : ""}>${t}</option>`)
    .join("");
}

function validateFieldKey(name, context) {
  if (!name || !name.trim()) return `${context}: field key is required`;
  if (!FIELD_KEY_RE.test(name.trim())) {
    return `${context}: use letters, numbers, underscore, dot, or hyphen only (e.g. company_name)`;
  }
  return "";
}

function collectValidationErrors() {
  const errors = [];
  const seen = new Set();

  state.fields.forEach((field, index) => {
    const ctx = `Field ${index + 1}`;
    const keyErr = validateFieldKey(field.name, ctx);
    if (keyErr) errors.push(keyErr);
    else if (seen.has(field.name)) errors.push(`${ctx}: duplicate field key "${field.name}"`);
    else seen.add(field.name);

    if (!field.label?.trim()) errors.push(`${ctx}: label is required`);

    if (field.type === "array") {
      const itemSeen = new Set();
      (field.item_fields || []).forEach((item, itemIndex) => {
        const itemCtx = `${ctx} column ${itemIndex + 1}`;
        const itemKeyErr = validateFieldKey(item.name, itemCtx);
        if (itemKeyErr) errors.push(itemKeyErr);
        else if (itemSeen.has(item.name)) errors.push(`${itemCtx}: duplicate key "${item.name}"`);
        else itemSeen.add(item.name);
        if (!item.label?.trim()) errors.push(`${itemCtx}: label is required`);
      });
    }
  });

  return errors;
}

function createScalarTable() {
  const wrap = document.createElement("div");
  wrap.className = "schema-table-wrap";
  wrap.innerHTML = `<table class="schema-table">${TABLE_HEAD}<tbody></tbody></table>`;
  return { wrap, tbody: wrap.querySelector("tbody") };
}

function renderScalarRow(field) {
  const tr = document.createElement("tr");
  tr.dataset.id = field.id;
  const keyError = field.name ? validateFieldKey(field.name, "Key") : "";
  tr.innerHTML = `
    <td><input data-key="label" value="${escAttr(field.label)}" placeholder="Company Name" title="Display label" /></td>
    <td><input data-key="name" value="${escAttr(field.name)}" placeholder="company_name" class="${keyError ? "invalid" : ""}" title="JSON key${keyError ? `: ${keyError}` : ""}" /></td>
    <td><input data-key="description" value="${escAttr(field.description || "")}" placeholder="optional hint" title="Agent hint" /></td>
    <td><select data-key="type">${typeOptions(field.type, SCALAR_FIELD_TYPES)}</select></td>
    <td class="col-action"><button type="button" class="btn-icon" data-action="remove" title="Remove">×</button></td>
  `;

  tr.querySelector('[data-key="label"]').addEventListener("input", (e) => {
    field.label = e.target.value;
    if (!field.nameManual) {
      field.name = slugify(e.target.value);
      tr.querySelector('[data-key="name"]').value = field.name;
    }
    updateExtractButton();
  });
  tr.querySelector('[data-key="name"]').addEventListener("input", (e) => {
    field.name = e.target.value;
    field.nameManual = true;
    updateExtractButton();
  });
  tr.querySelector('[data-key="description"]').addEventListener("input", (e) => {
    field.description = e.target.value;
  });
  tr.querySelector('[data-key="type"]').addEventListener("change", (e) => {
    field.type = e.target.value;
  });
  tr.querySelector('[data-action="remove"]').addEventListener("click", () => {
    state.fields = state.fields.filter((f) => f.id !== field.id);
    renderFields();
  });

  return tr;
}

function renderListColumnRow(field, item) {
  const tr = document.createElement("tr");
  tr.className = "list-col-row";
  tr.dataset.itemId = item.id;
  const keyError = item.name ? validateFieldKey(item.name, "Key") : "";
  tr.innerHTML = `
    <td><input data-item-label value="${escAttr(item.label)}" placeholder="Description" /></td>
    <td><input data-item-name value="${escAttr(item.name)}" placeholder="description" class="${keyError ? "invalid" : ""}" /></td>
    <td><input data-item-description value="${escAttr(item.description || "")}" placeholder="optional hint" /></td>
    <td><select data-item-type>${typeOptions(item.type, LIST_COLUMN_TYPES)}</select></td>
    <td class="col-action"><button type="button" class="btn-icon" data-action="remove-item" title="Remove column">×</button></td>
  `;

  tr.querySelector("[data-item-label]").addEventListener("input", (e) => {
    item.label = e.target.value;
    if (!item.nameManual) {
      item.name = slugify(e.target.value);
      tr.querySelector("[data-item-name]").value = item.name;
    }
    updateExtractButton();
  });
  tr.querySelector("[data-item-name]").addEventListener("input", (e) => {
    item.name = e.target.value;
    item.nameManual = true;
    updateExtractButton();
  });
  tr.querySelector("[data-item-description]").addEventListener("input", (e) => {
    item.description = e.target.value;
  });
  tr.querySelector("[data-item-type]").addEventListener("change", (e) => {
    item.type = e.target.value;
  });
  tr.querySelector('[data-action="remove-item"]').addEventListener("click", () => {
    field.item_fields = (field.item_fields || []).filter((i) => i.id !== item.id);
    renderFields();
  });

  return tr;
}

function renderListBlock(field) {
  const block = document.createElement("div");
  block.className = "list-block";
  block.dataset.id = field.id;

  const keyError = field.name ? validateFieldKey(field.name, "Key") : "";
  block.innerHTML = `
    <table class="schema-table">
      ${TABLE_HEAD}
      <tbody data-list-meta></tbody>
    </table>
    <div class="list-block-footer">
      <button type="button" class="btn-inline" data-action="add-item">+ column</button>
    </div>
  `;

  const tbody = block.querySelector("[data-list-meta]");
  const metaRow = document.createElement("tr");
  metaRow.className = "list-meta-row";
  metaRow.innerHTML = `
    <td><input data-key="label" value="${escAttr(field.label)}" placeholder="Line Items" /></td>
    <td><input data-key="name" value="${escAttr(field.name)}" placeholder="line_items" class="${keyError ? "invalid" : ""}" /></td>
    <td><input data-key="description" value="${escAttr(field.description || "")}" placeholder="one row per …" /></td>
    <td><span class="type-tag">list</span></td>
    <td class="col-action"><button type="button" class="btn-icon" data-action="remove" title="Remove list">×</button></td>
  `;
  tbody.appendChild(metaRow);

  (field.item_fields || []).forEach((item) => {
    tbody.appendChild(renderListColumnRow(field, item));
  });

  metaRow.querySelector('[data-key="label"]').addEventListener("input", (e) => {
    field.label = e.target.value;
    updateExtractButton();
  });
  metaRow.querySelector('[data-key="name"]').addEventListener("input", (e) => {
    field.name = e.target.value;
    field.nameManual = true;
    updateExtractButton();
  });
  metaRow.querySelector('[data-key="description"]').addEventListener("input", (e) => {
    field.description = e.target.value;
  });
  metaRow.querySelector('[data-action="remove"]').addEventListener("click", () => {
    state.fields = state.fields.filter((f) => f.id !== field.id);
    renderFields();
  });

  block.querySelector('[data-action="add-item"]').addEventListener("click", () => {
    field.item_fields = field.item_fields || [];
    field.item_fields.push({
      id: uid(),
      name: "",
      label: "",
      description: "",
      type: "string",
      nameManual: false,
    });
    renderFields();
  });

  return block;
}

function renderFields() {
  fieldBuilder.innerHTML = "";
  let scalarTable = null;

  state.fields.forEach((field) => {
    if (field.type !== "array") {
      if (!scalarTable) {
        scalarTable = createScalarTable();
        fieldBuilder.appendChild(scalarTable.wrap);
      }
      scalarTable.tbody.appendChild(renderScalarRow(field));
    } else {
      scalarTable = null;
      fieldBuilder.appendChild(renderListBlock(field));
    }
  });

  if (state.fields.length === 0) {
    fieldBuilder.innerHTML = `<p class="schema-empty muted">No fields yet — add a field or load the invoice preset.</p>`;
  }

  updateExtractButton();
}

function addScalarField() {
  state.fields.push({
    id: uid(),
    name: "",
    label: "",
    description: "",
    type: "string",
    nameManual: false,
  });
  renderFields();
}

function addListField() {
  state.fields.push({
    id: uid(),
    name: "line_items",
    label: "Line Items",
    description: "",
    type: "array",
    nameManual: true,
    item_fields: [
      {
        id: uid(),
        name: "description",
        label: "Description",
        description: "",
        type: "string",
        nameManual: true,
      },
      {
        id: uid(),
        name: "quantity",
        label: "Quantity",
        description: "",
        type: "integer",
        nameManual: true,
      },
      {
        id: uid(),
        name: "total",
        label: "Total",
        description: "",
        type: "float",
        nameManual: true,
      },
    ],
  });
  renderFields();
}

function buildFieldSpec() {
  return {
    fields: state.fields.map((f) => {
      const base = {
        name: f.name.trim(),
        label: f.label.trim(),
      };
      if (f.description?.trim()) base.description = f.description.trim();

      if (f.type === "array") {
        return {
          ...base,
          type: "array",
          item_fields: (f.item_fields || []).map(({ name, label, description, type }) => {
            const item = { name: name.trim(), label: label.trim(), type };
            if (description?.trim()) item.description = description.trim();
            return item;
          }),
        };
      }
      return { ...base, type: f.type };
    }),
  };
}

function updateExtractButton() {
  const hasFile = Boolean(state.file);
  const hasFields = state.fields.some((f) => f.name?.trim());
  const errors = collectValidationErrors();
  btnExtract.disabled = !(hasFile && hasFields && errors.length === 0);
  btnExtract.title = errors.length ? errors.join("\n") : "";
}

function addActivity(event) {
  const prevSource = activityState.activeSource;
  const source = eventSource(event);
  const message = activityMessage(event);

  if (!isActivityNoise(event)) {
    activityState.activeSource = source;
  }

  if (isActivityNoise(event)) {
    const last = activityFeed.lastElementChild;
    if (last && !last.classList.contains("history-empty") && last.dataset.source === source) {
      const msgEl = last.querySelector(".trail-msg");
      if (msgEl) msgEl.textContent = message;
      return;
    }
  }

  activityFeed.querySelector(".history-empty")?.remove();

  const li = document.createElement("li");
  li.dataset.source = source;
  if (event.type === "heartbeat") li.className = "heartbeat";
  if (event.type === "run_failed") li.className = "run-failed";
  li.innerHTML = `
    <span class="trail-route">${formatTrailRoute(
      prevSource && prevSource !== source ? prevSource : null,
      source
    )}</span>
    <code class="trail-type">${escapeHtml(event.type)}</code>
    <span class="trail-msg">${escapeHtml(message)}</span>
  `;
  activityFeed.appendChild(li);
  activityFeed.scrollTop = activityFeed.scrollHeight;
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function renderResults(payload) {
  rawJson.textContent = JSON.stringify(payload, null, 2);
  resultsEl.innerHTML = "";

  const failed = payload.status === "failed";
  const errorText = payload.error?.trim();

  if (failed || errorText) {
    const banner = document.createElement("div");
    banner.className = "error-banner";
    banner.innerHTML = `
      <strong>Extraction failed</strong>
      <p>${escapeHtml(errorText || "Unknown error")}</p>
    `;
    resultsEl.appendChild(banner);
  }

  if (payload.status === "needs_review") {
    const banner = document.createElement("div");
    banner.className = "review-banner";
    banner.textContent = "Agent flagged this result for review.";
    resultsEl.appendChild(banner);
  }
  if (payload.warnings?.length) {
    const note = document.createElement("div");
    note.className = "verify-note";
    note.textContent = "Text-layer check (advisory):";
    resultsEl.appendChild(note);
    const ul = document.createElement("ul");
    ul.className = "warning-list";
    payload.warnings.forEach((w) => {
      const li = document.createElement("li");
      li.textContent = w;
      ul.appendChild(li);
    });
    resultsEl.appendChild(ul);
  }

  const data = payload.data || {};
  if (!failed || Object.keys(data).length) {
    const dl = document.createElement("dl");
    dl.className = "kv";
    Object.entries(data).forEach(([key, val]) => {
      if (Array.isArray(val)) {
        const h = document.createElement("h3");
        h.textContent = key;
        resultsEl.appendChild(h);
        const table = document.createElement("table");
        if (val.length) {
          const headers = Object.keys(val[0]);
          table.innerHTML = `<thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead>`;
          const tbody = document.createElement("tbody");
          val.forEach((row) => {
            const tr = document.createElement("tr");
            tr.innerHTML = headers.map((h) => `<td>${row[h] ?? ""}</td>`).join("");
            tbody.appendChild(tr);
          });
          table.appendChild(tbody);
        }
        resultsEl.appendChild(table);
      } else {
        const dt = document.createElement("dt");
        dt.textContent = key;
        const dd = document.createElement("dd");
        dd.textContent = val ?? "";
        dl.appendChild(dt);
        dl.appendChild(dd);
      }
    });
    if (dl.children.length) resultsEl.appendChild(dl);
  }
  if (payload.usage) {
    const u = payload.usage;
    costFooter.textContent = `Cost: $${(u.cost_usd || 0).toFixed(4)} · tokens in=${u.input_tokens || 0} out=${u.output_tokens || 0}`;
  }
}

function applyPresetFields(preset) {
  state.fields = preset.fields.map((f) => ({
    id: uid(),
    ...f,
    description: f.description || "",
    nameManual: true,
    item_fields: (f.item_fields || []).map((item) => ({
      id: uid(),
      ...item,
      description: item.description || "",
      nameManual: true,
    })),
  }));
  renderFields();
}

async function initModels() {
  if (!modelSelect) return;
  let health = null;
  try {
    const [modelsRes, healthRes] = await Promise.all([
      fetch("/v1/models"),
      fetch("/health"),
    ]);
    if (healthRes.ok) {
      health = await healthRes.json();
    }
    if (!modelsRes.ok) throw new Error(await modelsRes.text());
    const body = await modelsRes.json();
    const models = body.models || [];
    if (!models.length) throw new Error("no models configured");
    renderModelOptions(models);
    applyDefaultModel();
    initBackendSelect(health);
  } catch (err) {
    modelSelect.innerHTML = `
      <option value="deepseek-v3.2">DeepSeek V3.2</option>
      <option value="kimi-k2.6">Kimi K2.6</option>
      <option value="deepseek-v4-pro">DeepSeek V4 Pro</option>
      <option value="claude-haiku-4-5-20251001">Claude Haiku 4.5 (fast/cheap)</option>
      <option value="claude-sonnet-4-6">Claude Sonnet 4.6</option>
      <option value="gemini-2.5-flash">Gemini 2.5 Flash</option>
    `;
    applyDefaultModel();
    console.warn("Failed to load /v1/models, using fallback list:", err);
    initBackendSelect(null);
  }
}

function sortModelsForUi(models) {
  const defaultModel = models.find((m) => m.id === DEFAULT_MODEL_ID);
  const rest = models.filter((m) => m.id !== DEFAULT_MODEL_ID);
  return defaultModel ? [defaultModel, ...rest] : models;
}

function renderModelOptions(models) {
  modelSelect.innerHTML = sortModelsForUi(models)
    .map((m) => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.label)}</option>`)
    .join("");
}

function applyDefaultModel() {
  if (!modelSelect) return;
  if (modelSelect.querySelector(`option[value="${DEFAULT_MODEL_ID}"]`)) {
    modelSelect.value = DEFAULT_MODEL_ID;
  }
}

function initBackendSelect(health) {
  if (!backendSelect) return;

  const saved = localStorage.getItem(BACKEND_STORAGE_KEY);
  const apiAvailable = !health || health.api_backend_available;

  backendSelect.querySelector('option[value="api"]')?.toggleAttribute(
    "disabled",
    !apiAvailable,
  );

  let backend = saved || DEFAULT_BACKEND;
  if (backend === "api" && !apiAvailable) {
    backend = "agent";
  }
  backendSelect.value = backend;

  if (!backendSelect.dataset.bound) {
    backendSelect.dataset.bound = "1";
    backendSelect.addEventListener("change", () => {
      localStorage.setItem(BACKEND_STORAGE_KEY, backendSelect.value);
    });
  }
}

function selectedBackend() {
  return backendSelect?.value || localStorage.getItem(BACKEND_STORAGE_KEY) || DEFAULT_BACKEND;
}

async function loadDemo(demoId) {
  const demo = state.demos.find((d) => d.id === demoId);
  if (!demo) return;

  state.activeDemoId = demoId;
  if (demoSelect.value !== demoId) demoSelect.value = demoId;

  const presetRes = await fetch(demo.preset);
  if (!presetRes.ok) throw new Error(`Failed to load preset: ${demo.preset}`);
  const preset = await presetRes.json();
  applyPresetFields(preset);

  const pdfRes = await fetch(demo.pdf);
  if (!pdfRes.ok) throw new Error(`Failed to load demo PDF: ${demo.pdf}`);
  const blob = await pdfRes.blob();
  const filename = demo.pdf.split("/").pop() || "document.pdf";
  setFile(new File([blob], filename, { type: blob.type || "application/pdf" }));
}

async function initDemos() {
  const res = await fetch("presets/demos.json");
  if (!res.ok) throw new Error("Failed to load demo manifest");
  const manifest = await res.json();
  state.demos = manifest.demos || [];
  demoSelect.innerHTML = state.demos
    .map((d) => `<option value="${d.id}">${escapeHtml(d.label)}</option>`)
    .join("");
  const defaultId = manifest.default || state.demos[0]?.id;
  if (defaultId) await loadDemo(defaultId);
}

async function showSample() {
  const res = await fetch("sample_result.json");
  const sample = await res.json();
  renderResults(sample);
  addActivity({ source: "pipeline", message: "Loaded offline sample result", type: "run_completed" });
}

function startPoll(jobId) {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/v1/jobs/${jobId}`);
      if (!res.ok) return;
      const job = await res.json();
      if (job.message) {
        addActivity({ source: "pipeline", message: `[poll] ${job.message}`, type: "heartbeat" });
      }
      if (job.status === "completed" && job.result) {
        clearInterval(state.pollTimer);
        renderResults(job.result);
      }
    } catch (_) { /* ignore */ }
  }, 1000);
}

async function runExtraction() {
  const errors = collectValidationErrors();
  if (errors.length) {
    alert(errors.join("\n"));
    return;
  }

  activityFeed.innerHTML = `<li class="muted history-empty">No events yet</li>`;
  resetActivity();
  resultsEl.innerHTML = "";
  rawJson.textContent = "";
  costFooter.textContent = "Cost: running…";

  const form = new FormData();
  form.append("file", state.file);
  form.append("field_spec", JSON.stringify(buildFieldSpec()));
  form.append("options", JSON.stringify({
    model: document.getElementById("model-select").value,
    backend: selectedBackend(),
  }));

  try {
    const res = await fetch("/v1/extract/stream", { method: "POST", body: form });
    if (!res.ok) throw new Error(await res.text());

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        const event = JSON.parse(line.slice(5).trim());
        addActivity(event);
        if (event.type === "run_completed" && event.detail?.result) {
          renderResults(event.detail.result);
        }
        if (event.type === "run_failed" && event.detail?.result) {
          renderResults(event.detail.result);
        }
        if (event.detail?.result?.job_id) {
          state.jobId = event.detail.result.job_id;
        }
      }
    }
  } catch (err) {
    addActivity({ source: "pipeline", message: `Error: ${err.message}. Trying sync fallback…`, type: "run_failed" });
    await runExtractionSync(form);
  }
}

async function runExtractionSync(form) {
  const res = await fetch("/v1/extract", { method: "POST", body: form });
  const payload = await res.json();
  renderResults(payload);
  if (payload.job_id) startPoll(payload.job_id);
}

function setFile(file) {
  state.file = file;
  fileInfo.textContent = file ? `${file.name} (${(file.size / 1024).toFixed(1)} KB)` : "";
  updateExtractButton();
}

dropZone.addEventListener("click", () => fileInput.click());
dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("dragover"); });
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("dragover");
  if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", () => { if (fileInput.files[0]) setFile(fileInput.files[0]); });

document.getElementById("btn-add-field").addEventListener("click", addScalarField);
document.getElementById("btn-add-list").addEventListener("click", addListField);
demoSelect.addEventListener("change", () => {
  loadDemo(demoSelect.value).catch((err) => {
    addActivity({ source: "pipeline", message: `Demo load failed: ${err.message}`, type: "run_failed" });
  });
});
document.getElementById("btn-extract").addEventListener("click", runExtraction);
document.getElementById("btn-sample").addEventListener("click", showSample);

const THEME_STORAGE_KEY = "extractor-theme";

function getPreferredTheme() {
  const saved = localStorage.getItem(THEME_STORAGE_KEY);
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem(THEME_STORAGE_KEY, theme);
  const toggle = document.getElementById("theme-toggle");
  if (!toggle) return;
  const isDark = theme === "dark";
  toggle.textContent = isDark ? "Light mode" : "Dark mode";
  toggle.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
}

function initTheme() {
  applyTheme(getPreferredTheme());
  document.getElementById("theme-toggle")?.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    applyTheme(next);
  });
}

initTheme();

initModels()
  .then(() => initDemos())
  .then(() => applyDefaultModel())
  .catch((err) => {
    fileInfo.textContent = `Demo load failed: ${err.message}`;
  });
