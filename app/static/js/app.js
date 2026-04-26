/* =====================================================
   Dashboard JavaScript — Instagram Auto-DM
   ===================================================== */

const API = "/api";

// -------------------------------------------------------
// Utility
// -------------------------------------------------------
function $(sel, ctx = document) { return ctx.querySelector(sel); }
function $$(sel, ctx = document) { return [...ctx.querySelectorAll(sel)]; }

function toast(msg, type = "info") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  $("#toast-container").appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit"
  });
}

function badge(status) {
  const map = {
    sent: "badge-green",
    skipped_no_follow: "badge-yellow",
    skipped_rate_limit: "badge-yellow",
    failed: "badge-red",
  };
  return `<span class="badge ${map[status] || "badge-muted"}">${status}</span>`;
}

async function apiFetch(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  if (res.status === 204) return null;
  return res.json();
}

// -------------------------------------------------------
// Navigation
// -------------------------------------------------------
function navigate(page) {
  $$(".nav-item").forEach(n => n.classList.remove("active"));
  $$(".page").forEach(p => p.classList.remove("active"));
  $(`[data-page="${page}"]`).classList.add("active");
  $(`#page-${page}`).classList.add("active");
  if (page === "dashboard") loadDashboard();
  if (page === "automations") loadAutomations();
  if (page === "leads") loadLeads();
  if (page === "logs") loadLogs();
}

$$(".nav-item").forEach(n => {
  n.addEventListener("click", () => navigate(n.dataset.page));
});

// -------------------------------------------------------
// Status bar
// -------------------------------------------------------
async function refreshStatus() {
  try {
    const s = await apiFetch("/status");
    const dot = $("#status-dot");
    const label = $("#status-label");
    if (s.logged_in) {
      dot.className = "status-dot online";
      label.textContent = `@${s.username || "connected"}`;
    } else {
      dot.className = "status-dot offline";
      label.textContent = "Not logged in";
    }
    const sched = $("#status-scheduler");
    if (sched) {
      sched.textContent = s.scheduler_running
        ? `Next poll: ${s.next_poll ? fmtDate(s.next_poll) : "soon"}`
        : "Scheduler stopped";
    }
  } catch {
    // silent
  }
}

setInterval(refreshStatus, 15000);
refreshStatus();

// -------------------------------------------------------
// Dashboard page
// -------------------------------------------------------
async function loadDashboard() {
  try {
    const [autos, leadsCount, logs] = await Promise.all([
      apiFetch("/automations"),
      apiFetch("/leads/count"),
      apiFetch("/logs?limit=5"),
    ]);

    $("#stat-automations").textContent = autos.length;
    $("#stat-active").textContent = autos.filter(a => a.is_active).length;
    $("#stat-leads").textContent = leadsCount.count;
    const sentLogs = logs.filter(l => l.status === "sent");
    $("#stat-dms").textContent = sentLogs.length + (sentLogs.length === 5 ? "+" : "");

    // Recent activity table
    const tbody = $("#recent-activity-body");
    if (!logs.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="empty"><p>No activity yet — start an automation to see results here.</p></td></tr>`;
      return;
    }
    tbody.innerHTML = logs.map(l => `
      <tr>
        <td>${fmtDate(l.created_at)}</td>
        <td>@${l.username}</td>
        <td class="truncate text-muted monospace">${escHtml(l.comment_text)}</td>
        <td>${badge(l.status)}</td>
        <td class="text-muted">#${l.automation_id}</td>
      </tr>
    `).join("");
  } catch (e) {
    toast("Failed to load dashboard: " + e.message, "error");
  }
}

// -------------------------------------------------------
// Automations page
// -------------------------------------------------------
let _posts = []; // cached for post selector in modal

async function loadAutomations() {
  try {
    const autos = await apiFetch("/automations");
    const tbody = $("#automations-body");

    if (!autos.length) {
      tbody.innerHTML = `
        <tr><td colspan="6">
          <div class="empty">
            <svg width="40" height="40" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 9v3m0 0v3m0-3h3m-3 0H9m12 0a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            <p>No automations yet. Click <strong>New Automation</strong> to create one.</p>
          </div>
        </td></tr>`;
      return;
    }

    tbody.innerHTML = autos.map(a => `
      <tr>
        <td><strong>${escHtml(a.name)}</strong></td>
        <td><code>${escHtml(a.keyword)}</code></td>
        <td class="truncate text-muted">${escHtml(a.dm_message)}</td>
        <td>${a.require_follow
          ? '<span class="badge badge-green">Yes</span>'
          : '<span class="badge badge-muted">No</span>'}</td>
        <td>
          <label class="toggle">
            <input type="checkbox" ${a.is_active ? "checked" : ""}
              onchange="toggleAutomation(${a.id}, this.checked)">
            <span class="toggle-slider"></span>
          </label>
        </td>
        <td>
          <div style="display:flex;gap:6px;">
            <button class="btn btn-ghost btn-sm" onclick="openEditModal(${a.id})">Edit</button>
            <button class="btn btn-danger btn-sm" onclick="deleteAutomation(${a.id}, '${escHtml(a.name)}')">Delete</button>
          </div>
        </td>
      </tr>
    `).join("");
  } catch (e) {
    toast("Failed to load automations: " + e.message, "error");
  }
}

async function toggleAutomation(id, active) {
  try {
    await apiFetch(`/automations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_active: active }),
    });
    toast(active ? "Automation enabled" : "Automation paused", "success");
  } catch (e) {
    toast("Failed to update: " + e.message, "error");
    loadAutomations();
  }
}

async function deleteAutomation(id, name) {
  if (!confirm(`Delete automation "${name}"? This also removes all its logs and leads.`)) return;
  try {
    await apiFetch(`/automations/${id}`, { method: "DELETE" });
    toast("Automation deleted", "success");
    loadAutomations();
  } catch (e) {
    toast("Delete failed: " + e.message, "error");
  }
}

// ---- Modal: New / Edit ----
let _editingId = null;

async function openNewModal() {
  _editingId = null;
  resetModal();
  $("#modal-title").textContent = "New Automation";
  await loadPostsForSelector();
  openModal();
}

async function openEditModal(id) {
  _editingId = id;
  resetModal();
  $("#modal-title").textContent = "Edit Automation";
  try {
    const a = await apiFetch(`/automations/${id}`);
    $("#field-name").value = a.name;
    $("#field-keyword").value = a.keyword;
    $("#field-message").value = a.dm_message;
    $("#field-require-follow").checked = a.require_follow;
    $("#field-active").checked = a.is_active;
    await loadPostsForSelector(a.post_ids);
    openModal();
  } catch (e) {
    toast("Failed to load automation: " + e.message, "error");
  }
}

async function loadPostsForSelector(selectedIds = "") {
  const container = $("#post-selector");
  container.innerHTML = `<p class="text-muted" style="font-size:12px;">Loading your posts...</p>`;

  try {
    if (!_posts.length) {
      _posts = await apiFetch("/posts");
    }
    const selected = selectedIds ? selectedIds.split(",").map(s => s.trim()) : [];

    if (!_posts.length) {
      container.innerHTML = `<p class="text-muted" style="font-size:12px;">No posts found. Leave blank to watch all recent posts.</p>`;
      return;
    }

    container.innerHTML = `
      <p class="form-hint" style="margin-bottom:8px;">Select posts to watch — leave all unchecked to watch all recent posts.</p>
      ${_posts.map(p => `
        <label style="display:flex;align-items:flex-start;gap:8px;margin-bottom:8px;cursor:pointer;">
          <input type="checkbox" value="${p.media_id}" ${selected.includes(p.media_id) ? "checked" : ""}
            style="margin-top:3px;width:auto;">
          <span>
            <span style="font-size:12px;color:var(--text-muted);">${fmtDate(p.timestamp)} &nbsp;·&nbsp; </span>
            <span style="font-size:13px;">${escHtml(p.caption || "(no caption)")}</span>
          </span>
        </label>
      `).join("")}
    `;
  } catch {
    container.innerHTML = `<p class="text-muted" style="font-size:12px;">Could not load posts. You can enter post IDs manually.</p>`;
  }
}

function getSelectedPostIds() {
  const checks = $$("#post-selector input[type=checkbox]:checked");
  return checks.map(c => c.value).join(",");
}

async function saveAutomation() {
  const payload = {
    name: $("#field-name").value.trim(),
    keyword: $("#field-keyword").value.trim(),
    dm_message: $("#field-message").value.trim(),
    require_follow: $("#field-require-follow").checked,
    is_active: $("#field-active").checked,
    post_ids: getSelectedPostIds() || null,
  };

  if (!payload.name || !payload.keyword || !payload.dm_message) {
    toast("Name, keyword, and message are required.", "error");
    return;
  }

  try {
    if (_editingId) {
      await apiFetch(`/automations/${_editingId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      toast("Automation updated!", "success");
    } else {
      await apiFetch("/automations", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      toast("Automation created!", "success");
    }
    closeModal();
    loadAutomations();
  } catch (e) {
    toast("Save failed: " + e.message, "error");
  }
}

function resetModal() {
  $("#field-name").value = "";
  $("#field-keyword").value = "";
  $("#field-message").value = "";
  $("#field-require-follow").checked = true;
  $("#field-active").checked = true;
  $("#post-selector").innerHTML = "";
}

function openModal() { $("#automation-modal").classList.add("open"); }
function closeModal() { $("#automation-modal").classList.remove("open"); }

// -------------------------------------------------------
// Leads page
// -------------------------------------------------------
async function loadLeads() {
  try {
    const leads = await apiFetch("/leads?limit=200");
    const tbody = $("#leads-body");

    if (!leads.length) {
      tbody.innerHTML = `<tr><td colspan="5"><div class="empty"><p>No leads yet. When users DM are sent, they appear here.</p></div></td></tr>`;
      return;
    }

    tbody.innerHTML = leads.map(l => `
      <tr>
        <td><strong>@${l.username}</strong></td>
        <td class="truncate text-muted">${escHtml(l.comment_text)}</td>
        <td class="text-muted monospace">${l.media_id}</td>
        <td class="text-muted">#${l.automation_id}</td>
        <td class="text-muted">${fmtDate(l.dm_sent_at)}</td>
      </tr>
    `).join("");
  } catch (e) {
    toast("Failed to load leads: " + e.message, "error");
  }
}

function exportLeads() {
  apiFetch("/leads?limit=5000").then(leads => {
    if (!leads.length) { toast("No leads to export.", "info"); return; }
    const header = ["username", "user_id", "automation_id", "media_id", "comment_text", "dm_sent_at"];
    const rows = leads.map(l =>
      [l.username, l.user_id, l.automation_id, l.media_id,
        `"${l.comment_text.replace(/"/g, '""')}"`, l.dm_sent_at].join(",")
    );
    const csv = [header.join(","), ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "leads.csv";
    a.click();
    toast("Leads exported!", "success");
  }).catch(e => toast("Export failed: " + e.message, "error"));
}

// -------------------------------------------------------
// Logs page
// -------------------------------------------------------
async function loadLogs(filterStatus = "") {
  try {
    const path = filterStatus ? `/logs?status=${filterStatus}&limit=200` : "/logs?limit=200";
    const logs = await apiFetch(path);
    const tbody = $("#logs-body");

    if (!logs.length) {
      tbody.innerHTML = `<tr><td colspan="6"><div class="empty"><p>No log entries found.</p></div></td></tr>`;
      return;
    }

    tbody.innerHTML = logs.map(l => `
      <tr>
        <td>${fmtDate(l.created_at)}</td>
        <td><strong>@${l.username}</strong></td>
        <td class="truncate">${escHtml(l.comment_text)}</td>
        <td class="text-muted monospace">${l.media_id}</td>
        <td>${badge(l.status)}</td>
        <td class="text-muted">#${l.automation_id}</td>
      </tr>
    `).join("");
  } catch (e) {
    toast("Failed to load logs: " + e.message, "error");
  }
}

// -------------------------------------------------------
// Manual poll trigger
// -------------------------------------------------------
async function triggerPoll() {
  const btn = $("#btn-trigger-poll");
  btn.disabled = true;
  btn.textContent = "Running…";
  try {
    const res = await apiFetch("/poll/trigger", { method: "POST" });
    const total = res.summaries.reduce((s, r) => s + r.sent, 0);
    toast(`Poll complete — ${total} DM(s) sent.`, "success");
    if ($("#page-dashboard").classList.contains("active")) loadDashboard();
  } catch (e) {
    toast("Poll failed: " + e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Run Now";
  }
}

// -------------------------------------------------------
// Security helpers
// -------------------------------------------------------
function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// -------------------------------------------------------
// Boot
// -------------------------------------------------------
navigate("dashboard");
