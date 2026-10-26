"use strict";

const state = { token: sessionStorage.getItem("vaultroute_token"), user: null, queryId: null };
const executiveRoles = new Set(["founder", "ceo", "cto", "director"]);
const managerRoles = new Set(["director", "cto", "engineering_manager", "product_manager", "hr_manager", "senior_designer", "business_manager"]);
const allDepartments = ["founding", "engineering", "hr", "design", "business"];

const byId = (id) => document.getElementById(id);
const show = (element) => element.classList.remove("hidden");
const hide = (element) => element.classList.add("hidden");

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401 && path !== "/auth/login") logout();
  const type = response.headers.get("content-type") || "";
  const payload = type.includes("json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof payload === "object" ? payload.detail : payload;
    throw new Error(typeof detail === "string" ? detail : "The request could not be completed");
  }
  return payload;
}

function toast(message) {
  const element = byId("toast");
  element.textContent = message;
  show(element);
  window.setTimeout(() => hide(element), 3200);
}

function initials(name) {
  return name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function canSeeMetrics() {
  return state.user.roles.some((role) => executiveRoles.has(role));
}

function canUpload() {
  return state.user.has_global_access || state.user.roles.some((role) => managerRoles.has(role));
}

function enterWorkspace(user) {
  state.user = user;
  hide(byId("login-view"));
  show(byId("app-view"));
  byId("user-name").textContent = user.full_name;
  byId("user-initials").textContent = initials(user.full_name);
  const scope = user.has_global_access ? "All departments" : user.departments.join(" · ") || "Company general";
  byId("user-scope").textContent = scope;
  byId("metrics-nav").classList.toggle("hidden", !canSeeMetrics());
  configureUpload();
}

function logout() {
  sessionStorage.removeItem("vaultroute_token");
  state.token = null;
  state.user = null;
  hide(byId("app-view"));
  show(byId("login-view"));
  byId("password").value = "";
}

async function restoreSession() {
  if (!state.token) return;
  try {
    const user = await api("/auth/me");
    enterWorkspace(user);
  } catch (_error) {
    logout();
  }
}

byId("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button");
  button.disabled = true;
  byId("login-error").textContent = "";
  try {
    const result = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({
        company_slug: byId("company").value.trim(),
        email: byId("email").value.trim(),
        password: byId("password").value,
      }),
    });
    state.token = result.access_token;
    sessionStorage.setItem("vaultroute_token", state.token);
    enterWorkspace(result.user);
  } catch (error) {
    byId("login-error").textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

byId("logout-button").addEventListener("click", logout);

const titles = {
  ask: ["Knowledge workspace", "Ask VaultRoute"],
  documents: ["Authorized sources", "Document library"],
  metrics: ["Executive view", "Insights and audit"],
};

document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", () => {
    const view = button.dataset.view;
    document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    document.querySelectorAll(".view-panel").forEach((panel) => panel.classList.remove("active-view"));
    byId(`${view}-view`).classList.add("active-view");
    byId("view-kicker").textContent = titles[view][0];
    byId("view-title").textContent = titles[view][1];
    if (view === "documents") loadDocuments();
    if (view === "metrics") loadMetrics();
  });
});

byId("question").addEventListener("input", (event) => {
  byId("question-count").textContent = `${event.target.value.length} / 2000`;
});

document.querySelectorAll("[data-question]").forEach((button) => {
  button.addEventListener("click", () => {
    byId("question").value = button.dataset.question;
    byId("question").dispatchEvent(new Event("input"));
    byId("question").focus();
  });
});

function addBadge(container, text, good = false) {
  const badge = document.createElement("span");
  badge.className = `badge${good ? " good" : ""}`;
  badge.textContent = text;
  container.appendChild(badge);
}

function appendSafeInlineMarkdown(container, text) {
  const boldPattern = /\*\*(.+?)\*\*/g;
  let cursor = 0;
  for (const match of text.matchAll(boldPattern)) {
    container.appendChild(document.createTextNode(text.slice(cursor, match.index)));
    const strong = document.createElement("strong");
    strong.textContent = match[1];
    container.appendChild(strong);
    cursor = match.index + match[0].length;
  }
  container.appendChild(document.createTextNode(text.slice(cursor)));
}

function renderSafeMarkdown(container, text) {
  container.replaceChildren();
  let list = null;
  text.split(/\r?\n/).forEach((line) => {
    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    if (bullet) {
      if (!list) {
        list = document.createElement("ul");
        container.appendChild(list);
      }
      const item = document.createElement("li");
      appendSafeInlineMarkdown(item, bullet[1]);
      list.appendChild(item);
      return;
    }
    list = null;
    if (!line.trim()) return;
    const paragraph = document.createElement("p");
    appendSafeInlineMarkdown(paragraph, line);
    container.appendChild(paragraph);
  });
}

function renderAnswer(result) {
  state.queryId = result.query_id;
  renderSafeMarkdown(byId("answer-text"), result.answer);
  const badges = byId("answer-badges");
  badges.replaceChildren();
  addBadge(badges, result.cache_hit ? "Cache hit" : result.route.provider, result.cache_hit);
  addBadge(badges, `${result.usage.total_tokens} tokens`);
  if (result.cache_similarity !== null) addBadge(badges, `${Math.round(result.cache_similarity * 100)}% match`);

  const sources = byId("source-list");
  sources.replaceChildren();
  result.citations.forEach((citation) => {
    const card = document.createElement("div");
    card.className = "source-card";
    const title = document.createElement("strong");
    title.textContent = `${citation.source_id} · ${citation.title}`;
    const meta = document.createElement("span");
    meta.textContent = `${citation.departments.join(", ")} · v${citation.document_version}`;
    card.append(title, meta);
    sources.appendChild(card);
  });
  byId("feedback-panel").classList.toggle("hidden", !result.query_id);
  byId("feedback-message").textContent = "";
  show(byId("answer-card"));
}

byId("ask-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  hide(byId("answer-card"));
  hide(byId("ask-error"));
  show(byId("answer-loading"));
  const button = event.currentTarget.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    const result = await api("/query", { method: "POST", body: JSON.stringify({ question: byId("question").value.trim() }) });
    renderAnswer(result);
  } catch (error) {
    byId("ask-error").textContent = error.message;
    show(byId("ask-error"));
  } finally {
    hide(byId("answer-loading"));
    button.disabled = false;
  }
});

for (let rating = 1; rating <= 5; rating += 1) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = String(rating);
  button.setAttribute("aria-label", `${rating} out of 5`);
  button.addEventListener("click", async () => {
    try {
      await api("/feedback", { method: "POST", body: JSON.stringify({ query_id: state.queryId, rating }) });
      byId("feedback-message").textContent = "Thank you—rating saved.";
    } catch (error) {
      byId("feedback-message").textContent = error.message;
    }
  });
  byId("rating-buttons").appendChild(button);
}

function configureUpload() {
  byId("upload-panel").classList.toggle("hidden", !canUpload());
  if (!canUpload()) return;
  const departments = state.user.has_global_access ? allDepartments : state.user.departments;
  const select = byId("upload-department");
  select.replaceChildren();
  departments.forEach((department) => {
    const option = document.createElement("option");
    option.value = department;
    option.textContent = department.replace("_", " ");
    select.appendChild(option);
  });
  byId("company-wide-label").classList.toggle("hidden", !state.user.has_global_access);
}

async function loadDocuments() {
  try {
    const documents = await api("/documents");
    const list = byId("document-list");
    list.replaceChildren();
    byId("document-empty").classList.toggle("hidden", documents.length > 0);
    const chunks = documents.reduce((sum, document) => sum + document.chunk_count, 0);
    const departments = new Set(documents.flatMap((document) => document.departments));
    byId("document-stats").replaceChildren(
      miniStat(`${documents.length} documents`), miniStat(`${chunks} indexed chunks`), miniStat(`${departments.size} departments`)
    );
    documents.forEach((document) => list.appendChild(documentRow(document)));
  } catch (error) {
    toast(error.message);
  }
}

function miniStat(text) {
  const item = document.createElement("span");
  item.className = "mini-stat";
  item.textContent = text;
  return item;
}

function documentRow(documentData) {
  const row = document.createElement("article");
  row.className = "document-row";
  const title = document.createElement("div");
  title.className = "document-title";
  const name = document.createElement("strong");
  name.textContent = documentData.title;
  const file = document.createElement("span");
  file.textContent = documentData.source_filename;
  title.append(name, file);
  const department = document.createElement("div");
  department.className = "document-meta";
  department.textContent = documentData.is_company_wide ? "Company-wide" : documentData.departments.join(", ");
  const classification = document.createElement("div");
  classification.className = "classification";
  classification.textContent = documentData.classification;
  const status = document.createElement("div");
  status.className = "document-status";
  status.textContent = documentData.status;
  row.append(title, department, classification, status);
  return row;
}

byId("refresh-documents").addEventListener("click", loadDocuments);

byId("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const companyWide = byId("upload-company-wide").checked;
  const access = {
    classification: byId("upload-classification").value,
    department_codes: companyWide ? [] : [byId("upload-department").value],
    is_company_wide: companyWide,
  };
  const form = new FormData();
  form.append("file", byId("upload-file").files[0]);
  form.append("title", byId("upload-title").value.trim());
  form.append("access_json", JSON.stringify(access));
  const button = event.currentTarget.querySelector("button");
  button.disabled = true;
  byId("upload-message").classList.remove("error");
  byId("upload-message").textContent = "Indexing…";
  try {
    const result = await api("/documents/upload", { method: "POST", body: form });
    byId("upload-message").textContent = `${result.title} indexed in ${result.chunk_count} chunk(s).`;
    event.currentTarget.reset();
    configureUpload();
    await loadDocuments();
  } catch (error) {
    byId("upload-message").textContent = error.message;
    byId("upload-message").classList.add("error");
  } finally {
    button.disabled = false;
  }
});

function metricCard(label, value, note) {
  const card = document.createElement("div");
  card.className = "metric-card";
  const labelElement = document.createElement("span");
  labelElement.textContent = label;
  const valueElement = document.createElement("strong");
  valueElement.textContent = value;
  const noteElement = document.createElement("small");
  noteElement.textContent = note;
  card.append(labelElement, valueElement, noteElement);
  return card;
}

async function loadMetrics() {
  hide(byId("metrics-error"));
  try {
    const [metrics, audit] = await Promise.all([api("/metrics/summary?days=30"), api("/audit/queries?days=30&limit=20")]);
    byId("metric-cards").replaceChildren(
      metricCard("Queries", String(metrics.total_queries), `${metrics.generated_answers} generated`),
      metricCard("Cache hit rate", `${Math.round(metrics.cache_hit_rate * 100)}%`, `${metrics.cache_hits} zero-token hits`),
      metricCard("Average latency", `${Math.round(metrics.average_response_ms)} ms`, `p95 ${Math.round(metrics.p95_response_ms)} ms`),
      metricCard("Estimated cost", `$${metrics.estimated_cost_usd.toFixed(4)}`, `${metrics.total_tokens} model tokens`),
      metricCard("Auto quality", metrics.average_automatic_quality === null ? "—" : `${Math.round(metrics.average_automatic_quality * 100)}%`, "retrieval + grounding"),
      metricCard("User rating", metrics.average_feedback_rating === null ? "—" : `${metrics.average_feedback_rating.toFixed(1)} / 5`, `${metrics.feedback_count} ratings`),
      metricCard("Refusals", String(metrics.refusals), "weak evidence, no model"),
      metricCard("Failures", String(metrics.failures), "provider or system errors")
    );
    const body = byId("audit-body");
    body.replaceChildren();
    audit.forEach((event) => {
      const row = document.createElement("tr");
      const values = [
        new Date(event.created_at).toLocaleString(), event.outcome, event.provider || "none",
        event.cache_hit ? "hit" : "miss", `${Math.round(event.total_ms)} ms`,
        event.automatic_quality_score === null ? "—" : `${Math.round(event.automatic_quality_score * 100)}%`,
      ];
      values.forEach((value) => { const cell = document.createElement("td"); cell.textContent = value; row.appendChild(cell); });
      body.appendChild(row);
    });
  } catch (error) {
    byId("metrics-error").textContent = error.message;
    show(byId("metrics-error"));
  }
}

byId("refresh-metrics").addEventListener("click", loadMetrics);
restoreSession();
