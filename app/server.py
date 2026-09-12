#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project

"""Persistent manager for a Recipes-configured vLLM CPU service.

The manager owns the control plane only. Inference clients connect directly to
the supervised vLLM process so the portal is not in the token-serving path.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
import yaml
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from hardware import HardwareSelection, detect_recipe_hardware
from model_support import check_model_support
from persisted_state import restore_last_job
from recipe_errors import classify_recipe_error
from sweep_runtime import run_sweep_process


STATE_DIR = Path(os.environ.get("EIM_STATE_DIR", "/workspace/eim"))
RECIPES_DIR = Path(os.environ.get("EIM_RECIPES_DIR", "/opt/vllm-recipes"))
CONFIG_DIR = STATE_DIR / "config"
JOBS_DIR = STATE_DIR / "jobs"
LOG_DIR = STATE_DIR / "logs"
STATIC_DIR = Path(__file__).with_name("static")

INITIAL_CONFIG = CONFIG_DIR / "initial-config.yml"
ACTIVE_CONFIG = CONFIG_DIR / "active-config.yml"
PREVIOUS_CONFIG = CONFIG_DIR / "previous-config.yml"
ACTIVE_ENV = CONFIG_DIR / "active-env.sh"
STATE_FILE = STATE_DIR / "state.json"
DEMO_REPORT = STATE_DIR / "demo" / "sweep-report.html"
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SweepRequest(BaseModel):
    input_tokens: int = Field(128, gt=0)
    output_tokens: int = Field(128, gt=0)
    concurrency: int = Field(32, gt=0)
    ttft_sla_ms: float | None = Field(3000, gt=0)
    tpot_sla_ms: float | None = Field(100, gt=0)


class Manager:
    def __init__(self) -> None:
        for directory in (STATE_DIR, CONFIG_DIR, JOBS_DIR, LOG_DIR):
            directory.mkdir(parents=True, exist_ok=True)
        self.model = os.environ.get("EIM_MODEL_ID") or os.environ.get(
            "INFERENCE_MODEL_ID"
        )
        self.hardware_request = os.environ.get("EIM_HARDWARE", "auto")
        self.hardware_selection: HardwareSelection | None = None
        self.vllm_host = os.environ.get("EIM_VLLM_HOST", "0.0.0.0")
        self.vllm_port = int(os.environ.get("EIM_VLLM_PORT", "8000"))
        self.model_support_url = os.environ.get("EIM_MODEL_SUPPORT_URL", "").strip()
        self.model_support_timeout = float(
            os.environ.get("EIM_MODEL_SUPPORT_TIMEOUT", "180")
        )
        self.process: subprocess.Popen[str] | None = None
        self.process_log: Any = None
        self.lock = threading.RLock()
        self.job: dict[str, Any] | None = None
        self.last_error: str | None = None
        self.error_code: str | None = None
        self.model_support: dict[str, Any] = {
            "state": "not_configured" if not self.model_support_url else "idle"
        }
        self._shutdown = False
        self.restore_state()

    def restore_state(self) -> None:
        """Restore the last sweep while treating files on disk as authoritative."""
        self.job = restore_last_job(STATE_FILE, JOBS_DIR, self.model)

    def startup(self) -> None:
        if not self.model:
            self.last_error = "Set EIM_MODEL_ID (or INFERENCE_MODEL_ID) to start vLLM."
            self._write_state()
            return
        try:
            self.generate_initial_config()
            self.start_vllm()
        except Exception as exc:  # keep the portal available for diagnosis
            classified = classify_recipe_error(
                self.read_file(LOG_DIR / "recipe-generation.log"),
                self.model,
                self._selected_hardware_name(),
            )
            if classified:
                self.error_code = classified.code
                self.last_error = classified.message
                self.model_support = {
                    "state": (
                        "checking" if self.model_support_url else "not_configured"
                    )
                }
                self._write_state()
                if self.model_support_url:
                    self.model_support = check_model_support(
                        self.model_support_url,
                        self.model,
                        self.model_support_timeout,
                    )
            else:
                self.error_code = "startup_failed"
                self.last_error = str(exc)
            self._write_state()

    def shutdown(self) -> None:
        self._shutdown = True
        self.stop_vllm()

    def _converter_command(
        self,
        config_out: Path,
        env_out: Path,
        sweep: SweepRequest | None = None,
        sweep_dir: Path | None = None,
    ) -> list[str]:
        hardware = self._select_hardware().recipe_key
        command = [
            sys.executable,
            str(RECIPES_DIR / "recipe_json_to_vllm_config.py"),
            "--model",
            str(self.model),
            "--hardware",
            hardware,
            "--detect-hardware",
            "--config-out",
            str(config_out),
            "--env-out",
            str(env_out),
        ]
        if sweep is not None:
            command += [
                "--input-tokens",
                str(sweep.input_tokens),
                "--output-tokens",
                str(sweep.output_tokens),
                "--concurrency",
                str(sweep.concurrency),
                "--generate-full-sweep",
                "--sweep-out-dir",
                str(sweep_dir),
            ]
            if sweep.ttft_sla_ms is not None:
                command += ["--ttft-sla-ms", str(sweep.ttft_sla_ms)]
            if sweep.tpot_sla_ms is not None:
                command += ["--tpot-sla-ms", str(sweep.tpot_sla_ms)]
        return command

    def _select_hardware(self) -> HardwareSelection:
        with self.lock:
            if self.hardware_selection is None:
                self.hardware_selection = detect_recipe_hardware(
                    self.hardware_request
                )
                self._write_state()
            return self.hardware_selection

    def _selected_hardware_name(self) -> str:
        if self.hardware_selection:
            return self.hardware_selection.recipe_key
        return self.hardware_request

    @staticmethod
    def _run_checked(command: list[str], log_path: Path) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as log:
            result = subprocess.run(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        if result.returncode:
            raise RuntimeError(
                f"Command failed with exit code {result.returncode}; see {log_path}."
            )

    def generate_initial_config(self) -> None:
        """Always call the Recipes hardware-aware path for the first config."""
        command = self._converter_command(INITIAL_CONFIG, ACTIVE_ENV)
        self._run_checked(command, LOG_DIR / "recipe-generation.log")
        shutil.copy2(INITIAL_CONFIG, ACTIVE_CONFIG)
        self.last_error = None
        self.error_code = None
        self.model_support = {
            "state": "not_configured" if not self.model_support_url else "idle"
        }
        self._write_state()

    @staticmethod
    def parse_env_file(path: Path) -> dict[str, str]:
        """Parse the converter's export-only env.sh without executing a shell."""
        values: dict[str, str] = {}
        if not path.is_file():
            return values
        for line_number, raw in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            name, separator, encoded_value = line.partition("=")
            if not separator or not ENV_ASSIGNMENT.fullmatch(name):
                raise ValueError(f"Unsupported env.sh line {line_number}: {raw}")
            parsed = shlex.split(encoded_value, posix=True)
            if len(parsed) != 1:
                raise ValueError(f"Unsupported env.sh value on line {line_number}")
            values[name] = parsed[0]
        return values

    def start_vllm(self) -> None:
        with self.lock:
            if self.process and self.process.poll() is None:
                return
            if not ACTIVE_CONFIG.is_file():
                raise RuntimeError("No active configuration is available.")

            child_env = os.environ.copy()
            child_env.update(self.parse_env_file(ACTIVE_ENV))
            log_path = LOG_DIR / "vllm.log"
            self.process_log = log_path.open("a", encoding="utf-8")
            self.process = subprocess.Popen(
                [
                    "vllm",
                    "serve",
                    "--config",
                    str(ACTIVE_CONFIG),
                    "--host",
                    self.vllm_host,
                    "--port",
                    str(self.vllm_port),
                ],
                stdout=self.process_log,
                stderr=subprocess.STDOUT,
                text=True,
                env=child_env,
                start_new_session=True,
            )
            self.last_error = None
            self.error_code = None
            self._write_state()

    def stop_vllm(self, timeout: int = 60) -> None:
        with self.lock:
            process = self.process
            if process is None or process.poll() is not None:
                self.process = None
                return
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
            finally:
                if self.process_log:
                    self.process_log.close()
                    self.process_log = None
                self.process = None
                self._write_state()

    def restart_vllm(self) -> None:
        self.stop_vllm()
        self.start_vllm()

    def vllm_healthy(self) -> bool:
        if not self.process or self.process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.vllm_port}/health", timeout=1
            ) as response:
                return response.status == 200
        except Exception:
            return False

    def status(self) -> dict[str, Any]:
        with self.lock:
            process_running = bool(self.process and self.process.poll() is None)
            return {
                "manager": "running",
                "model": self.model,
                "hardware": (
                    self.hardware_selection.recipe_key
                    if self.hardware_selection
                    else self.hardware_request
                ),
                "hardware_detection": (
                    self.hardware_selection.to_dict()
                    if self.hardware_selection
                    else None
                ),
                "vllm": {
                    "state": "healthy"
                    if self.vllm_healthy()
                    else "starting"
                    if process_running
                    else "stopped",
                    "pid": self.process.pid if process_running else None,
                    "port": self.vllm_port,
                },
                "job": self.job,
                "last_error": self.last_error,
                "error_code": self.error_code,
                "model_support": self.model_support,
                "files": {
                    "active_config": ACTIVE_CONFIG.is_file(),
                    "initial_config": INITIAL_CONFIG.is_file(),
                    "demo_report": DEMO_REPORT.is_file(),
                },
            }

    def start_sweep(self, request: SweepRequest) -> dict[str, Any]:
        with self.lock:
            if self.job and self.job.get("state") in {"queued", "running"}:
                raise RuntimeError("A sweep is already running.")
            job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
            job_dir = JOBS_DIR / job_id
            self.job = {
                "id": job_id,
                "state": "queued",
                "stage": "waiting",
                "created_at": time.time(),
                "report_available": False,
                "recommendation_available": False,
                "error": None,
            }
            self._write_state()
            threading.Thread(
                target=self._run_sweep,
                args=(request, job_dir),
                daemon=True,
            ).start()
            return dict(self.job)

    def _set_job(self, **changes: Any) -> None:
        with self.lock:
            if self.job:
                self.job.update(changes)
            self._write_state()

    def _run_sweep(self, request: SweepRequest, job_dir: Path) -> None:
        sweep_dir = job_dir / "sweep"
        sweep_config = job_dir / "input-config.yml"
        sweep_env = job_dir / "env.sh"
        try:
            job_dir.mkdir(parents=True)
            self._set_job(state="running", stage="stopping_vllm")
            self.stop_vllm()

            self._set_job(stage="generating_sweep")
            command = self._converter_command(
                sweep_config, sweep_env, request, sweep_dir
            )
            self._run_checked(command, job_dir / "generate.log")

            runner = sweep_dir / "run_full_sweep.sh"
            if not runner.is_file():
                raise RuntimeError(f"Sweep generator did not create {runner}.")

            self._set_job(stage="running_sweep")
            sweep_child_env = os.environ.copy()
            sweep_child_env.update(self.parse_env_file(sweep_env))
            with (job_dir / "sweep.log").open("w", encoding="utf-8") as log:
                result = run_sweep_process(runner, log, sweep_child_env)
            if result.returncode:
                raise RuntimeError(
                    f"Sweep failed with exit code {result.returncode}; "
                    f"see {job_dir / 'sweep.log'}."
                )

            report = sweep_dir / "sweep-report.html"
            recommendation = sweep_dir / "recommended-config.yml"
            self._set_job(
                state="completed",
                stage="completed",
                completed_at=time.time(),
                report_available=report.is_file(),
                recommendation_available=recommendation.is_file(),
            )
        except Exception as exc:
            self._set_job(
                state="failed",
                stage="failed",
                completed_at=time.time(),
                error=str(exc),
            )
        finally:
            if not self._shutdown:
                try:
                    self.start_vllm()
                except Exception as exc:
                    self.last_error = f"Could not restore vLLM after sweep: {exc}"
                    self._write_state()

    def apply_recommendation(self) -> None:
        with self.lock:
            if not self.job or self.job.get("state") != "completed":
                raise RuntimeError("No completed sweep recommendation is available.")
            recommendation = (
                JOBS_DIR
                / str(self.job["id"])
                / "sweep"
                / "recommended-config.yml"
            )
            if not recommendation.is_file():
                raise RuntimeError("The completed sweep has no recommended-config.yml.")
            if ACTIVE_CONFIG.is_file():
                shutil.copy2(ACTIVE_CONFIG, PREVIOUS_CONFIG)
            self.stop_vllm()
            shutil.copy2(recommendation, ACTIVE_CONFIG)
            try:
                self.start_vllm()
            except Exception:
                if PREVIOUS_CONFIG.is_file():
                    shutil.copy2(PREVIOUS_CONFIG, ACTIVE_CONFIG)
                    self.start_vllm()
                raise

    @staticmethod
    def read_file(path: Path) -> str:
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def hardware_info(self) -> dict[str, Any]:
        path = CONFIG_DIR / "hardware.json"
        # Current converter writes detected hardware in generated metadata/logs,
        # but does not promise a standalone JSON contract. Expose the generation
        # log until that API is added.
        return {
            "hardware": (
                self.hardware_selection.recipe_key
                if self.hardware_selection
                else self.hardware_request
            ),
            "detection": (
                self.hardware_selection.to_dict()
                if self.hardware_selection
                else None
            ),
            "recipe_generation_log": self.read_file(LOG_DIR / "recipe-generation.log"),
            "hardware_json": json.loads(path.read_text()) if path.is_file() else None,
        }

    def _write_state(self) -> None:
        state = {
            "model": self.model,
            "hardware": (
                self.hardware_selection.recipe_key
                if self.hardware_selection
                else self.hardware_request
            ),
            "hardware_detection": (
                self.hardware_selection.to_dict()
                if self.hardware_selection
                else None
            ),
            "job": self.job,
            "last_error": self.last_error,
            "error_code": self.error_code,
            "model_support": self.model_support,
            "updated_at": time.time(),
        }
        temporary = STATE_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temporary.replace(STATE_FILE)


manager = Manager()


def require_control_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.environ.get("EIM_API_TOKEN")
    if not expected:
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")


@asynccontextmanager
async def lifespan(_: FastAPI):
    threading.Thread(target=manager.startup, daemon=True).start()
    try:
        yield
    finally:
        manager.shutdown()


app = FastAPI(title="vLLM Recipes Deployment Manager", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/static/{name}")
def static_file(name: str) -> FileResponse:
    if name not in {"app.js", "style.css"}:
        raise HTTPException(status_code=404)
    return FileResponse(STATIC_DIR / name)


@app.get("/api/health")
def manager_health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
def status() -> dict[str, Any]:
    return manager.status()


@app.get("/api/hardware")
def hardware() -> dict[str, Any]:
    return manager.hardware_info()


@app.get("/api/config/{kind}", response_class=PlainTextResponse)
def config(kind: str) -> str:
    paths = {
        "initial": INITIAL_CONFIG,
        "active": ACTIVE_CONFIG,
        "environment": ACTIVE_ENV,
    }
    if kind not in paths:
        raise HTTPException(status_code=404)
    return manager.read_file(paths[kind])


@app.get("/api/logs/{kind}", response_class=PlainTextResponse)
def logs(kind: str) -> str:
    paths = {
        "vllm": LOG_DIR / "vllm.log",
        "recipe": LOG_DIR / "recipe-generation.log",
    }
    if kind not in paths:
        raise HTTPException(status_code=404)
    content = manager.read_file(paths[kind])
    return "\n".join(content.splitlines()[-500:])


@app.post("/api/server/restart", dependencies=[Depends(require_control_token)])
def restart_server() -> dict[str, str]:
    if manager.job and manager.job.get("state") in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="A sweep is running")
    manager.restart_vllm()
    return {"status": "restarting"}


@app.post("/api/sweeps", dependencies=[Depends(require_control_token)])
def start_sweep(request: SweepRequest) -> dict[str, Any]:
    try:
        return manager.start_sweep(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/api/recommendation/apply", dependencies=[Depends(require_control_token)]
)
def apply_recommendation() -> dict[str, str]:
    try:
        manager.apply_recommendation()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "restarting_with_recommendation"}


def _current_job_file(relative: str) -> Path:
    if not manager.job:
        raise HTTPException(status_code=404, detail="No sweep is available")
    path = JOBS_DIR / str(manager.job["id"]) / "sweep" / relative
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{relative} is not available")
    return path


@app.get("/reports/sweep", response_class=HTMLResponse)
def sweep_report() -> FileResponse:
    return FileResponse(_current_job_file("sweep-report.html"))


@app.get("/reports/demo", response_class=HTMLResponse)
def demo_sweep_report() -> FileResponse:
    if not DEMO_REPORT.is_file():
        raise HTTPException(status_code=404, detail="Demo report is unavailable")
    return FileResponse(DEMO_REPORT)


@app.get("/api/recommendation", response_class=PlainTextResponse)
def recommendation() -> str:
    return _current_job_file("recommended-config.yml").read_text(encoding="utf-8")


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("EIM_MANAGER_HOST", "0.0.0.0"),
        port=int(os.environ.get("EIM_MANAGER_PORT", "8080")),
        log_level=os.environ.get("EIM_LOG_LEVEL", "info").lower(),
    )
