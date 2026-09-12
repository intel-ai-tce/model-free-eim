const $ = (selector) => document.querySelector(selector);
let activeConfig = "active";

async function request(path, options = {}, retryAuth = true) {
  const headers = { ...(options.headers || {}) };
  const token = localStorage.getItem("eim_api_token");
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401 && retryAuth) {
    const supplied = prompt("Enter the EIM control API token:");
    if (supplied) {
      localStorage.setItem("eim_api_token", supplied);
      return request(path, options, false);
    }
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return response;
}

async function loadConfig(kind = activeConfig) {
  activeConfig = kind;
  const response = await request(`/api/config/${kind}`);
  $("#config").textContent = await response.text() || "Not generated yet.";
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.config === kind);
  });
}

async function refresh() {
  try {
    const status = await (await request("/api/status")).json();
    $("#model").textContent = status.model || "Not configured";
    const detected = status.hardware_detection;
    $("#hardware").textContent = detected
      ? `${status.hardware} · ${detected.generation}`
      : status.hardware;
    $("#endpoint").textContent = `:${status.vllm.port}`;
    $("#status-badge").textContent = `vLLM ${status.vllm.state}`;
    $("#status-badge").classList.toggle("stopped", status.vllm.state !== "healthy");
    const recipeUnavailable = [
      "recipe_not_found",
      "recipe_hardware_unavailable",
    ].includes(status.error_code);
    $("#sweep-state").textContent = status.job ? `${status.job.state}: ${status.job.stage}` : "Not started";
    $("#job-message").textContent = (status.job && status.job.error)
      || (recipeUnavailable ? "" : status.last_error)
      || "";
    $("#recipe-alert").classList.toggle("hidden", !recipeUnavailable);
    $("#recipe-alert-message").textContent = recipeUnavailable
      ? status.last_error
      : "";
    const support = status.model_support || { state: "not_configured" };
    const supportResult = $("#model-support-result");
    supportResult.className = `support-result ${support.state}`;
    const supportLabels = {
      idle: "Waiting",
      checking: "Checking…",
      completed: support.verdict || "Completed",
      unavailable: "Service unavailable",
      failed: "Check failed",
      not_configured: "Not configured",
    };
    $("#model-support-verdict").textContent =
      supportLabels[support.state] || "Unknown";
    $("#model-support-message").textContent = support.message || (
      support.state === "not_configured"
        ? "Set EIM_MODEL_SUPPORT_URL to enable the fast support check."
        : ""
    );

    const demoAvailable = Boolean(status.files.demo_report);
    $("#demo-report-section").classList.toggle("hidden", !demoAvailable);
    if (!demoAvailable) {
      $("#demo-report-container").classList.add("hidden");
      $("#demo-report").removeAttribute("src");
      $("#toggle-demo-report").textContent = "View demo sweep report";
    }

    const running = status.job && ["queued", "running"].includes(status.job.state);
    $("#sweep-form").querySelector("button").disabled = Boolean(running);
    const ready = status.job && status.job.state === "completed" && status.job.recommendation_available;
    $("#recommendation-panel").classList.toggle("hidden", !ready);
    if (ready && !$("#recommendation").textContent) {
      $("#recommendation").textContent = await (await request("/api/recommendation")).text();
      if (status.job.report_available) $("#report").src = `/reports/sweep?t=${Date.now()}`;
    }
  } catch (error) {
    $("#status-badge").textContent = "Manager unavailable";
    $("#status-badge").classList.add("stopped");
    $("#job-message").textContent = error.message;
  }

  try {
    $("#logs").textContent = await (await request("/api/logs/vllm")).text() || "No vLLM log yet.";
  } catch (_) {}
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => loadConfig(tab.dataset.config));
});

$("#restart").addEventListener("click", async () => {
  try { await request("/api/server/restart", { method: "POST" }); }
  catch (error) { alert(error.message); }
  refresh();
});

$("#sweep-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!confirm("Inference will be unavailable while the maintenance sweep runs. Continue?")) return;
  const form = new FormData(event.target);
  const body = Object.fromEntries([...form.entries()].map(([key, value]) => [key, Number(value)]));
  try {
    await request("/api/sweeps", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    $("#recommendation").textContent = "";
    $("#report").removeAttribute("src");
  } catch (error) { alert(error.message); }
  refresh();
});

$("#apply").addEventListener("click", async () => {
  if (!confirm("Apply the recommended config and restart vLLM?")) return;
  try { await request("/api/recommendation/apply", { method: "POST" }); }
  catch (error) { alert(error.message); }
  loadConfig("active");
  refresh();
});

$("#toggle-demo-report").addEventListener("click", () => {
  const container = $("#demo-report-container");
  const frame = $("#demo-report");
  const opening = container.classList.contains("hidden");
  container.classList.toggle("hidden", !opening);
  $("#toggle-demo-report").textContent = opening
    ? "Hide demo sweep report"
    : "View demo sweep report";
  if (opening && !frame.getAttribute("src")) {
    frame.src = "/reports/demo";
  }
});

$("#toggle-recipe-log").addEventListener("click", async () => {
  const log = $("#recipe-log");
  const opening = log.classList.contains("hidden");
  log.classList.toggle("hidden", !opening);
  $("#toggle-recipe-log").textContent = opening
    ? "Hide recipe-generation log"
    : "View recipe-generation log";
  if (opening && !log.textContent) {
    try {
      log.textContent = await (await request("/api/logs/recipe")).text();
    } catch (error) {
      log.textContent = error.message;
    }
  }
});

loadConfig();
refresh();
setInterval(refresh, 5000);
