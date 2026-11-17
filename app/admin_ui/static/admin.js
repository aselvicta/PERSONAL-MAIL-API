// Personal Mail API admin UI. Plain JavaScript, no build step.
// Every value from the server is rendered as text (textContent), never parsed as HTML.
"use strict";

const API = "/api/v1";
const TOKEN_KEY = "pm_admin_token";

const $ = (id) => document.getElementById(id);
const state = { projects: [], current: null };

// --- helpers -----------------------------------------------------------------

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

let toastTimer;
function toast(message, bad = false) {
  const box = $("toast");
  box.textContent = message;
  box.className = bad ? "toast bad" : "toast";
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (box.hidden = true), bad ? 8000 : 3500);
}

function fmtDate(value) {
  return value ? new Date(value).toLocaleString() : "—";
}

function lines(text) {
  return text.split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
}

// Accept "mysite.vercel.app" or a pasted page URL and reduce it to the origin
// ("https://mysite.vercel.app"). Anything that is not http(s) is sent as typed
// so the server rejects it with a clear message.
function toOrigin(value) {
  let v = value.trim().replace(/\/+$/, "");
  if (/^(localhost|127\.0\.0\.1)(:\d+)?$/i.test(v)) v = "http://" + v;
  else if (!v.includes("://")) v = "https://" + v;
  if (!/^https?:\/\//i.test(v)) return v;
  try {
    return new URL(v).origin;
  } catch {
    return v;
  }
}

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function api(path, { method = "GET", body } = {}) {
  const headers = { Accept: "application/json" };
  const token = sessionStorage.getItem(TOKEN_KEY);
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(API + path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const json = await res.json().catch(() => null);
  if (res.status === 401 && path !== "/auth/login") {
    sessionStorage.removeItem(TOKEN_KEY);
    showLogin("Your session expired. Please sign in again.");
    throw new ApiError("Session expired", 401);
  }
  if (!res.ok || !json || json.success === false) {
    let message = json?.message || `Request failed (${res.status})`;
    const details = json?.error?.details;
    if (Array.isArray(details) && details.length) {
      message += "\n" + details.map((d) => `• ${d.field.replace(/^body\./, "")}: ${d.message}`).join("\n");
    }
    throw new ApiError(message, res.status);
  }
  return json.data;
}

async function withBusy(button, fn) {
  if (button) button.disabled = true;
  try {
    return await fn();
  } catch (err) {
    if (!(err instanceof ApiError && err.status === 401)) toast(err.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}

// --- views -------------------------------------------------------------------

function showLogin(message) {
  $("app-view").hidden = true;
  $("logout").hidden = true;
  $("whoami").textContent = "";
  $("login-view").hidden = false;
  const error = $("login-error");
  error.hidden = !message;
  error.textContent = message || "";
}

async function showApp() {
  const me = await api("/auth/me");
  $("whoami").textContent = me.email;
  $("logout").hidden = false;
  $("login-view").hidden = true;
  $("app-view").hidden = false;
  await loadProjects();
}

function showPanel(name) {
  $("empty-state").hidden = name !== "empty";
  $("create-form").hidden = name !== "create";
  $("project-view").hidden = name !== "project";
}

async function loadProjects(selectId) {
  const page = await api("/admin/projects?limit=100");
  state.projects = page.items;
  renderProjectList();
  const id = selectId || state.current?.id;
  const project = state.projects.find((p) => p.id === id);
  if (project) await openProject(project.id);
  else if (state.projects.length === 1) await openProject(state.projects[0].id);
  else showPanel(state.projects.length ? "empty" : "create");
}

function renderProjectList() {
  const list = $("project-list");
  list.replaceChildren(
    ...state.projects.map((p) =>
      el(
        "li",
        {},
        el(
          "button",
          {
            class: state.current?.id === p.id ? "active" : "",
            onclick: () => withBusy(null, () => openProject(p.id)),
          },
          p.name,
          el("small", {}, p.slug + (p.is_active ? "" : " · disabled")),
        ),
      ),
    ),
  );
}

async function openProject(id) {
  const project = await api(`/admin/projects/${id}`);
  state.current = project;
  renderProjectList();
  showPanel("project");
  $("new-key").hidden = true;
  renderProject(project);
  await Promise.all([loadUsage(id), loadKeys(id), loadEmails(id), loadMessages(id)]);
}

function renderProject(p) {
  $("p-name").textContent = p.name;
  $("p-slug").textContent = p.slug;
  const status = $("p-status");
  status.textContent = p.is_active ? "active" : "disabled";
  status.className = "badge " + (p.is_active ? "ok" : "bad");
  $("toggle-active").textContent = p.is_active ? "Disable" : "Enable";

  const form = $("edit-form");
  for (const name of ["name", "recipient_email", "sender_name", "sender_email", "description", "rate_limit", "daily_quota"]) {
    form.elements[name].value = p[name] ?? "";
  }
  form.elements.allowed_origins.value = p.allowed_origins.join("\n");
  form.elements.allowed_recipient_domains.value = p.allowed_recipient_domains.join("\n");
  for (const name of ["contact_enabled", "notifications_enabled", "transactional_enabled", "acknowledgement_enabled", "turnstile_enabled"]) {
    form.elements[name].checked = Boolean(p[name]);
  }

  $("snippet").textContent =
    `fetch("${location.origin}${API}/contact", {\n` +
    `  method: "POST",\n` +
    `  headers: { "Content-Type": "application/json" },\n` +
    `  body: JSON.stringify({\n` +
    `    project: "${p.slug}",\n` +
    `    name, email, subject, message,\n` +
    `    website: ""  // hidden honeypot field, leave empty\n` +
    `  }),\n` +
    `});`;
}

async function loadUsage(id) {
  const u = await api(`/admin/projects/${id}/usage`);
  const stat = (value, label) => el("div", { class: "stat" }, el("b", {}, value), el("span", {}, label));
  const delivered = (u.emails_by_status.delivered || 0) + (u.emails_by_status.sent || 0);
  $("p-usage").replaceChildren(
    stat(`${u.emails_today} / ${u.daily_quota}`, "emails today / quota"),
    stat(u.emails_total, "emails total"),
    stat(delivered, "sent or delivered"),
    stat(u.emails_by_status.failed || 0, "failed"),
    stat(u.contact_submissions_total, "contact messages"),
  );
}

async function loadKeys(id) {
  const keys = await api(`/admin/projects/${id}/api-keys`);
  const body = $("keys");
  if (!keys.length) {
    body.replaceChildren(el("tr", {}, el("td", { colspan: "5", class: "muted" }, "No keys.")));
    return;
  }
  body.replaceChildren(
    ...keys.map((k) =>
      el(
        "tr",
        {},
        el("td", {}, el("code", {}, k.key_prefix + "…")),
        el("td", {}, el("span", { class: "badge " + (k.is_active ? "ok" : "bad") }, k.is_active ? "active" : "revoked")),
        el("td", {}, fmtDate(k.created_at)),
        el("td", {}, fmtDate(k.last_used_at)),
        el(
          "td",
          {},
          k.is_active
            ? el(
                "button",
                {
                  class: "btn btn-small btn-danger",
                  onclick: (e) =>
                    confirm("Revoke this key? Apps using it will stop working.") &&
                    withBusy(e.currentTarget, async () => {
                      await api(`/admin/projects/${id}/api-keys/${k.id}`, { method: "DELETE" });
                      toast("Key revoked.");
                      await loadKeys(id);
                    }),
                },
                "Revoke",
              )
            : "",
        ),
      ),
    ),
  );
}

const STATUS_CLASS = {
  delivered: "ok", sent: "ok", accepted: "ok",
  pending: "warn", delivery_delayed: "warn",
  failed: "bad", bounced: "bad", complained: "bad",
};

async function loadEmails(id) {
  const page = await api(`/admin/projects/${id}/emails?limit=20`);
  const body = $("emails");
  if (!page.items.length) {
    body.replaceChildren(el("tr", {}, el("td", { colspan: "5", class: "muted" }, "No emails yet.")));
    return;
  }
  body.replaceChildren(
    ...page.items.map((m) =>
      el(
        "tr",
        { title: m.error_message || "" },
        el("td", {}, fmtDate(m.created_at)),
        el("td", { class: "wrap" }, m.recipient),
        el("td", { class: "wrap" }, m.subject),
        el("td", {}, m.email_type.replaceAll("_", " ")),
        el(
          "td",
          {},
          el("span", { class: "badge " + (STATUS_CLASS[m.status] || "") }, m.status),
          m.error_code ? el("div", { class: "error" }, m.error_code) : null,
        ),
      ),
    ),
  );
}

async function loadMessages(id) {
  const page = await api(`/admin/projects/${id}/contact-submissions?limit=10`);
  const box = $("messages");
  if (!page.items.length) {
    box.replaceChildren(el("p", { class: "muted" }, "No contact messages yet."));
    return;
  }
  box.replaceChildren(
    ...page.items.map((m) =>
      el(
        "div",
        { class: "message" },
        el("div", {}, el("strong", {}, m.sender_name), " <", m.sender_email, "> · ", el("span", { class: "muted" }, fmtDate(m.created_at))),
        el("div", {}, m.subject),
        el("p", {}, m.message),
      ),
    ),
  );
}

function showNewKey(key) {
  $("new-key-value").textContent = key;
  $("new-key").hidden = false;
  $("new-key").scrollIntoView({ behavior: "smooth", block: "center" });
}

// --- events ------------------------------------------------------------------

$("login-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  withBusy(form.querySelector("button"), async () => {
    $("login-error").hidden = true;
    try {
      const data = await api("/auth/login", {
        method: "POST",
        body: { email: form.elements.email.value, password: form.elements.password.value },
      });
      sessionStorage.setItem(TOKEN_KEY, data.access_token);
      form.reset();
      await showApp();
    } catch (err) {
      showLogin(err.message);
    }
  });
});

$("logout").addEventListener("click", () => {
  sessionStorage.removeItem(TOKEN_KEY);
  state.current = null;
  showLogin();
});

$("new-project").addEventListener("click", () => {
  state.current = null;
  renderProjectList();
  $("create-form").reset();
  showPanel("create");
});

$("create-form").querySelector("[data-cancel]").addEventListener("click", () => {
  showPanel(state.projects.length ? "empty" : "create");
});

$("create-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const f = event.currentTarget.elements;
  withBusy(event.submitter, async () => {
    const created = await api("/admin/projects", {
      method: "POST",
      body: {
        name: f.name.value.trim(),
        slug: f.slug.value.trim(),
        recipient_email: f.recipient_email.value.trim(),
        allowed_origins: lines(f.allowed_origins.value).map(toOrigin),
      },
    });
    toast("Project created.");
    await loadProjects(created.project.id);
    showNewKey(created.api_key.api_key);
  });
});

// Suggest a slug from the name.
$("create-form").elements.name.addEventListener("input", (event) => {
  const slug = $("create-form").elements.slug;
  if (slug.dataset.touched) return;
  slug.value = event.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64);
});
$("create-form").elements.slug.addEventListener("input", (event) => {
  event.target.dataset.touched = "1";
});

$("edit-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const f = event.currentTarget.elements;
  const optional = (v) => (v.trim() === "" ? null : v.trim());
  const id = state.current.id;
  withBusy(event.submitter, async () => {
    const updated = await api(`/admin/projects/${id}`, {
      method: "PATCH",
      body: {
        name: f.name.value.trim(),
        recipient_email: f.recipient_email.value.trim(),
        sender_name: optional(f.sender_name.value),
        sender_email: optional(f.sender_email.value),
        description: optional(f.description.value),
        allowed_origins: lines(f.allowed_origins.value).map(toOrigin),
        allowed_recipient_domains: lines(f.allowed_recipient_domains.value),
        contact_enabled: f.contact_enabled.checked,
        notifications_enabled: f.notifications_enabled.checked,
        transactional_enabled: f.transactional_enabled.checked,
        acknowledgement_enabled: f.acknowledgement_enabled.checked,
        turnstile_enabled: f.turnstile_enabled.checked,
        rate_limit: Number(f.rate_limit.value),
        daily_quota: Number(f.daily_quota.value),
      },
    });
    state.current = updated;
    state.projects = state.projects.map((p) => (p.id === id ? updated : p));
    renderProjectList();
    renderProject(updated);
    await loadUsage(id);
    toast("Saved.");
  });
});

$("toggle-active").addEventListener("click", (event) => {
  const p = state.current;
  const action = p.is_active ? "disable" : "enable";
  if (p.is_active && !confirm(`Disable ${p.name}? It will stop sending email.`)) return;
  withBusy(event.currentTarget, async () => {
    await api(`/admin/projects/${p.id}/${action}`, { method: "POST" });
    toast(`Project ${action}d.`);
    await loadProjects(p.id);
  });
});

$("delete-project").addEventListener("click", (event) => {
  const p = state.current;
  const typed = prompt(`This permanently deletes "${p.name}" with its keys and logs.\nType the slug "${p.slug}" to confirm:`);
  if (typed !== p.slug) {
    if (typed !== null) toast("Slug did not match. Nothing was deleted.", true);
    return;
  }
  withBusy(event.currentTarget, async () => {
    await api(`/admin/projects/${p.id}`, { method: "DELETE" });
    state.current = null;
    toast("Project deleted.");
    await loadProjects();
  });
});

$("regen-key").addEventListener("click", (event) => {
  if (!confirm("Generate a new key? All current keys of this project are revoked immediately.")) return;
  const id = state.current.id;
  withBusy(event.currentTarget, async () => {
    const key = await api(`/admin/projects/${id}/api-keys`, { method: "POST" });
    showNewKey(key.api_key);
    await loadKeys(id);
  });
});

$("copy-key").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("new-key-value").textContent);
    toast("Copied.");
  } catch {
    toast("Copy failed. Select the key and copy it manually.", true);
  }
});

// --- start -------------------------------------------------------------------

if (sessionStorage.getItem(TOKEN_KEY)) {
  showApp().catch(() => showLogin());
} else {
  showLogin();
}
