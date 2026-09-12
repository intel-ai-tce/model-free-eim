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
    $("#sweep-state").textContent = status.job ? `${status.job.state}: ${status.job.stage}` : "Not started";
    $("#job-message").textContent = status.last_error || (status.job && status.job.error) || "";

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

loadConfig();
refresh();
setInterval(refresh, 5000);
