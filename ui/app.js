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

const TOOL_LABELS = {
  analyze_document: "Analyze document",
  extract_pdf_text: "Extract PDF text",
  render_pdf_pages: "Render pages (vision)",
  get_document_metadata: "Read metadata",
};

const BACKEND_LABELS = {
  api: "OpenRouter API",
  agent: "Agent SDK",
};

const state = {
  file: null,
  fields: [],
  jobId: null,
  pollTimer: null,
  demos: [],
  activeDemoId: null,
  runContext: null,
  previewObjectUrl: null,
};

const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");
const fileInfo = document.getElementById("file-info");
const btnViewDoc = document.getElementById("btn-view-doc");
const docViewer = document.getElementById("doc-viewer");
const docViewerTitle = document.getElementById("doc-viewer-title");
const docViewerFrame = document.getElementById("doc-viewer-frame");
const docViewerImage = document.getElementById("doc-viewer-image");
const docViewerClose = document.getElementById("doc-viewer-close");
const docViewerExpand = document.getElementById("doc-viewer-expand");
const fieldBuilder = document.getElementById("field-builder");
const activityFeed = document.getElementById("activity-feed");
const runStatusEl = document.getElementById("run-status");
const runSummaryEl = document.getElementById("run-summary");

const ACTIVITY_SOURCES = ["pipeline", "agent", "tool"];

const activityState = {
  activeSource: null,
  streamBuffer: "",
};

function normalizeToolName(raw) {
  if (!raw) return null;
  const name = String(raw);
  const prefix = "mcp__extractor__";
  return name.startsWith(prefix) ? name.slice(prefix.length) : name;
}

function toolLabel(name) {
  return TOOL_LABELS[name] || name;
}

function backendLabel(id) {
  return BACKEND_LABELS[id] || id;
}

function formatModelLabel(id) {
  if (!modelSelect || !id) return id || "—";
  const opt = modelSelect.querySelector(`option[value="${id}"]`);
  return opt ? opt.textContent : id;
}

function resetRunContext() {
  state.runContext = {
    tools: new Set(),
    stageStarted: false,
    fieldCount: state.fields.filter((f) => f.name?.trim()).length,
    requestedModel: modelSelect?.value || DEFAULT_MODEL_ID,
    requestedBackend: selectedBackend(),
  };
  hideRunSummary();
  setRunStatus("Starting extraction…", { active: true });
}

function hideRunStatus() {
  if (!runStatusEl) return;
  runStatusEl.classList.add("is-hidden");
  runStatusEl.innerHTML = "";
}

function setRunStatus(message, { active = true, badge = null } = {}) {
  if (!runStatusEl) return;
  runStatusEl.classList.remove("is-hidden");
  runStatusEl.classList.toggle("run-status-active", active);
  const badgeHtml = badge
    ? `<span class="run-status-badge">${escapeHtml(badge)}</span>`
    : "";
  runStatusEl.innerHTML = `${badgeHtml}<span class="run-status-text">${escapeHtml(message)}</span>`;
}

function hideRunSummary() {
  if (!runSummaryEl) return;
  runSummaryEl.classList.add("is-hidden");
  runSummaryEl.innerHTML = "";
}

function summaryRow(label, value) {
  return `<div class="run-summary-row"><dt>${escapeHtml(label)}</dt><dd>${value}</dd></div>`;
}

function renderRunSummary(payload) {
  if (!runSummaryEl || !payload) return;

  const meta = payload.metadata || {};
  const usage = payload.usage || {};
  const models = meta.models_used || {};
  const ctx = state.runContext || {};
  const tools = ctx.tools ? [...ctx.tools].map((t) => toolLabel(t)) : [];

  const kind = (meta.document_kind || "document").toUpperCase();
  const pages = meta.page_count != null ? `${meta.page_count} page(s)` : "—";
  const docPath = meta.document_needs_vision ? "vision (scanned/image)" : "text layer";
  const backend = backendLabel(meta.extraction_backend || ctx.requestedBackend);
  const extractionModel = formatModelLabel(models.extraction || meta.models_used?.extraction);
  const requestedModel = formatModelLabel(models.extraction_requested || ctx.requestedModel);
  const duration =
    meta.duration_ms != null ? `${(meta.duration_ms / 1000).toFixed(1)}s` : "—";
  const cost = usage.cost_usd != null ? `$${Number(usage.cost_usd).toFixed(4)}` : "—";
  const tokens =
    usage.input_tokens != null
      ? `${Number(usage.input_tokens).toLocaleString()} in / ${Number(usage.output_tokens || 0).toLocaleString()} out`
      : "—";

  let modelLine = escapeHtml(extractionModel);
  if (meta.vision_fallback && requestedModel !== extractionModel) {
    modelLine += ` <span class="run-summary-note">(auto — switched from ${escapeHtml(requestedModel)})</span>`;
  }

  const statusClass =
    payload.status === "success"
      ? "run-summary-ok"
      : payload.status === "needs_review"
        ? "run-summary-review"
        : "run-summary-failed";

  runSummaryEl.className = `run-summary ${statusClass}`;
  runSummaryEl.innerHTML = `
    <h3 class="run-summary-title">What happened</h3>
    <dl class="run-summary-grid">
      ${summaryRow("Document", `${escapeHtml(pages)} · ${escapeHtml(kind)} · ${escapeHtml(docPath)}`)}
      ${summaryRow("Schema", `${ctx.fieldCount || "—"} field(s) from your definition`)}
      ${summaryRow("Backend", escapeHtml(backend))}
      ${summaryRow("Model", modelLine)}
      ${summaryRow("Tools", tools.length ? escapeHtml(tools.join(" · ")) : "—")}
      ${summaryRow("Duration", escapeHtml(duration))}
      ${summaryRow("Cost", `${escapeHtml(cost)} · ${escapeHtml(tokens)}`)}
    </dl>
  `;
  runSummaryEl.classList.remove("is-hidden");

  if (payload.status === "failed") {
    setRunStatus(payload.error || "Extraction failed", { active: false, badge: "Failed" });
  } else if (payload.status === "needs_review") {
    setRunStatus(`Finished in ${duration} · ${cost} — needs review`, { active: false, badge: "Review" });
  } else {
    setRunStatus(`Finished in ${duration} · ${cost}`, { active: false, badge: "Done" });
  }
}

function handleRunEvent(event) {
  if (!state.runContext) return;

  const type = event.type;
  const detail = event.detail || {};

  if (type === "run_started") {
    setRunStatus("Validating document and building schema…", { active: true });
    return;
  }

  if (type === "file_validated") {
    setRunStatus(event.message || "File validated", { active: true });
    return;
  }

  if (type === "schema_built") {
    setRunStatus("Schema ready — starting extraction agent…", { active: true });
    return;
  }

  if (type === "stage_started" && event.stage === "extraction") {
    state.runContext.stageStarted = true;
    const badge = detail.vision_fallback ? "Auto vision" : null;
    setRunStatus(event.message || "Extracting…", { active: true, badge });
    return;
  }

  if (type === "tool_started" || type === "agent_tool_called") {
    const tool = normalizeToolName(detail.tool);
    if (tool) state.runContext.tools.add(tool);
    setRunStatus(`Reading document: ${toolLabel(tool || "tool")}…`, { active: true });
    return;
  }

  if (type === "run_completed" || type === "run_failed") {
    return;
  }
}

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

function bindLabelToKey(labelEl, nameEl, obj) {
  labelEl.addEventListener("input", (e) => {
    obj.label = e.target.value;
    if (!obj.nameManual) {
      obj.name = slugify(e.target.value);
      nameEl.value = obj.name;
    }
    updateExtractButton();
  });
  nameEl.addEventListener("input", (e) => {
    obj.name = e.target.value;
    obj.nameManual = true;
    updateExtractButton();
  });
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

  bindLabelToKey(tr.querySelector('[data-key="label"]'), tr.querySelector('[data-key="name"]'), field);
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

  bindLabelToKey(
    tr.querySelector("[data-item-label]"),
    tr.querySelector("[data-item-name]"),
    item
  );
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

  bindLabelToKey(
    metaRow.querySelector('[data-key="label"]'),
    metaRow.querySelector('[data-key="name"]'),
    field
  );
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
    fieldBuilder.innerHTML = `<p class="schema-empty muted">No fields yet — add a field or list, or pick a demo document.</p>`;
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
  const label = "Line Items";
  state.fields.push({
    id: uid(),
    name: slugify(label),
    label,
    description: "",
    type: "array",
    nameManual: false,
    item_fields: [],
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
  if (event.type === "stage_started" || event.type === "run_completed") li.className = "milestone";
  if (event.detail?.vision_fallback) li.classList.add("vision-fallback");
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
  handleRunEvent(event);
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

  if (failed) {
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
    const reviewMsg =
      payload.error === "schema_validation_failed"
        ? "Output did not match the extraction schema (see warnings below)."
        : payload.error === "could_not_parse_result_json"
          ? "Model returned a response that could not be parsed as JSON (see raw JSON below)."
          : payload.error === "empty_list_extraction"
            ? "An array field came back empty but the document may contain multiple records (see warnings)."
            : "Agent flagged this result for review.";
    banner.textContent = reviewMsg;
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
  if (state.runContext || payload.metadata?.page_count != null) {
    renderRunSummary(payload);
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
  demoSelect.innerHTML =
    `<option value="">Custom upload</option>` +
    state.demos
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
  resetRunContext();
  if (state.file) openDocViewer();
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
  if (!state.runContext) resetRunContext();
  const res = await fetch("/v1/extract", { method: "POST", body: form });
  const payload = await res.json();
  renderResults(payload);
  if (payload.job_id) startPoll(payload.job_id);
}

function clearFieldSpec() {
  state.fields = [];
  renderFields();
}

function setFile(file, { resetFields = false } = {}) {
  state.file = file;
  fileInfo.textContent = file ? `${file.name} (${(file.size / 1024).toFixed(1)} KB)` : "";
  if (resetFields) {
    state.activeDemoId = null;
    if (demoSelect) demoSelect.value = "";
    clearFieldSpec();
  }
  refreshDocumentPreview(file);
  updateExtractButton();
}

const IMAGE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"]);

function isImageFile(file) {
  if (!file) return false;
  if (file.type?.startsWith("image/")) return true;
  const ext = file.name.includes(".") ? file.name.slice(file.name.lastIndexOf(".")).toLowerCase() : "";
  return IMAGE_EXTENSIONS.has(ext);
}

function revokePreviewUrl() {
  if (state.previewObjectUrl) {
    URL.revokeObjectURL(state.previewObjectUrl);
    state.previewObjectUrl = null;
  }
}

function refreshDocumentPreview(file) {
  revokePreviewUrl();
  if (docViewerFrame) {
    docViewerFrame.removeAttribute("src");
    docViewerFrame.classList.add("is-hidden");
  }
  if (docViewerImage) {
    docViewerImage.removeAttribute("src");
    docViewerImage.classList.add("is-hidden");
  }
  if (!file) {
    if (btnViewDoc) btnViewDoc.disabled = true;
    if (docViewerTitle) docViewerTitle.textContent = "Document";
    closeDocViewer();
    return;
  }
  state.previewObjectUrl = URL.createObjectURL(file);
  if (docViewerTitle) docViewerTitle.textContent = file.name;
  if (btnViewDoc) btnViewDoc.disabled = false;
  if (isImageFile(file)) {
    if (docViewerImage) {
      docViewerImage.src = state.previewObjectUrl;
      docViewerImage.classList.remove("is-hidden");
    }
  } else if (docViewerFrame) {
    docViewerFrame.src = state.previewObjectUrl;
    docViewerFrame.classList.remove("is-hidden");
  }
}

function openDocViewer() {
  if (!state.file || !docViewer) return;
  docViewer.classList.remove("is-hidden");
  docViewer.setAttribute("aria-hidden", "false");
}

function closeDocViewer() {
  if (!docViewer) return;
  docViewer.classList.add("is-hidden");
  docViewer.classList.remove("is-expanded");
  docViewer.setAttribute("aria-hidden", "true");
  if (docViewerExpand) {
    docViewerExpand.textContent = "Expand";
    docViewerExpand.setAttribute("aria-label", "Expand preview");
  }
}

function toggleDocViewerExpanded() {
  if (!docViewer) return;
  docViewer.classList.toggle("is-expanded");
  const expanded = docViewer.classList.contains("is-expanded");
  if (docViewerExpand) {
    docViewerExpand.textContent = expanded ? "Shrink" : "Expand";
    docViewerExpand.setAttribute("aria-label", expanded ? "Shrink preview" : "Expand preview");
  }
}

function toggleDocViewer() {
  if (!docViewer) return;
  if (docViewer.classList.contains("is-hidden")) openDocViewer();
  else closeDocViewer();
}

dropZone.addEventListener("click", () => fileInput.click());
dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("dragover"); });
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("dragover");
  if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0], { resetFields: true });
});
fileInput.addEventListener("change", () => {
  if (fileInput.files[0]) setFile(fileInput.files[0], { resetFields: true });
});

btnViewDoc?.addEventListener("click", toggleDocViewer);
docViewerClose?.addEventListener("click", closeDocViewer);
docViewerExpand?.addEventListener("click", toggleDocViewerExpanded);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && docViewer && !docViewer.classList.contains("is-hidden")) {
    closeDocViewer();
  }
});

document.getElementById("btn-add-field").addEventListener("click", addScalarField);
document.getElementById("btn-add-list").addEventListener("click", addListField);
demoSelect.addEventListener("change", () => {
  if (!demoSelect.value) return;
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
