# Standalone vLLM Recipes Deployment Manager

This project builds an independent management service on top of the official
vLLM CPU image. It does not patch, build, or contribute files to the vLLM
repository.

During the Docker build, an intermediate stage fetches only `tools/recipes`
from the configured repository and revision. The final image contains:

- the published vLLM runtime from `vllm/vllm-openai-cpu:latest-x86_64`;
- the selected vLLM Recipes tools;
- a persistent manager and web portal.

Inference clients connect directly to vLLM on port 8000. The manager remains
available on port 8080 and is not an inference proxy.

## Flow

```text
container startup
  -> recipe_json_to_vllm_config.py --detect-hardware
  -> initial-config.yml + env.sh
  -> supervised vllm serve

maintenance sweep
  -> stop vLLM
  -> generate and run full sweep
  -> recommended-config.yml + sweep-report.html
  -> restart the original vLLM configuration
  -> let the user review and optionally apply the recommendation
```

## Build

```bash
docker build -t vllm-recipes-manager:latest .
```

The defaults are:

```text
VLLM_BASE_IMAGE=vllm/vllm-openai-cpu:latest-x86_64
VLLM_RECIPES_REPOSITORY=https://github.com/intel-ai-tce/vllm.git
VLLM_RECIPES_REF=recipe_improve
```

They can be replaced without changing this project:

```bash
docker build \
  --build-arg VLLM_BASE_IMAGE=vllm/vllm-openai-cpu:latest-x86_64 \
  --build-arg VLLM_RECIPES_REPOSITORY=https://github.com/intel-ai-tce/vllm.git \
  --build-arg VLLM_RECIPES_REF=recipe_improve \
  -t vllm-recipes-manager:latest .
```

For a reproducible production build, set `VLLM_BASE_IMAGE` to an immutable
image digest and `VLLM_RECIPES_REF` to a tested commit SHA.

## Run

```bash
mkdir -p state

docker run --rm \
  --shm-size=4g \
  -p 8000:8000 \
  -p 8080:8080 \
  -e EIM_MODEL_ID=meta-llama/Llama-3.1-8B-Instruct \
  -e HF_TOKEN \
  -v "$HOME/.cache/huggingface:/workspace/model-cache/huggingface" \
  -v "$PWD/state:/workspace/eim" \
  vllm-recipes-manager:latest
```

Open:

```text
Portal:           http://localhost:8080
OpenAI endpoint:  http://localhost:8000/v1
vLLM health:      http://localhost:8000/health
```

## Initial configuration

Every startup runs the required hardware-aware Recipes path before launching
vLLM. The manager first maps the host CPU to the Recipes hardware key, then
runs the converter:

```bash
python3 /opt/vllm-recipes/recipe_json_to_vllm_config.py \
  --model "$EIM_MODEL_ID" \
  --hardware "$DETECTED_RECIPE_HARDWARE" \
  --detect-hardware \
  --config-out /workspace/eim/config/initial-config.yml \
  --env-out /workspace/eim/config/active-env.sh
```

The manager copies the result to `active-config.yml`, safely parses the
generated exports, and launches:

```bash
vllm serve --config /workspace/eim/config/active-config.yml \
  --host 0.0.0.0 --port 8000
```

### Automatic Xeon detection

`EIM_HARDWARE=auto` is the default and needs no special container privileges.
The manager reads the CPUID family and model exposed through `/proc/cpuinfo`:

| Detected processor | Recipes key |
| --- | --- |
| Emerald Rapids, 5th Gen Xeon Scalable | `xeon5` |
| Granite Rapids, Xeon 6 P-core | `xeon6` |
| Sierra Forest, Xeon 6 E-core | `xeon6` |

The resolved key and detection details are shown in the portal and returned by
`GET /api/hardware`. Unknown and future processors fail with an actionable
message instead of silently choosing the wrong recipe. Override detection only
when necessary, for example `-e EIM_HARDWARE=xeon6`.

### Optional NUMA-performance permissions

The minimum command deliberately omits `SYS_NICE` and unconfined seccomp. They
are not required to generate Recipes configuration, run the manager, or start
basic vLLM serving. On some hosts, vLLM's NUMA memory-binding calls may be
restricted without them. If logs show a binding/permission failure, test these
options after reviewing the security policy:

```bash
docker run --rm \
  --cap-add SYS_NICE \
  --security-opt seccomp=unconfined \
  ... \
  vllm-recipes-manager:latest
```

These broad permissions may be rejected by Kubernetes Pod Security or
OpenShift Security Context Constraints. Prefer the minimum command first and
add only the narrowly approved permission available in the target cluster.

## Maintenance sweep

The portal accepts input/output token lengths, representative concurrency,
and TTFT/TPOT SLAs. Starting a sweep:

1. Stops the active vLLM process.
2. Calls the converter with `--detect-hardware --generate-full-sweep`.
3. Runs the generated `run_full_sweep.sh`.
4. Saves all results under `/workspace/eim/jobs/<job-id>/sweep`.
5. Restarts the original active configuration.
6. Displays `recommended-config.yml` and `sweep-report.html`.

Applying the recommendation remains a separate action and restarts vLLM.

## Configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `EIM_MODEL_ID` | required | Model ID used for Recipes discovery |
| `EIM_HARDWARE` | `auto` | Auto-detect `xeon5`/`xeon6`, or explicitly set a Recipes key |
| `EIM_VLLM_PORT` | `8000` | Direct vLLM API port |
| `EIM_MANAGER_PORT` | `8080` | Portal and management API port |
| `EIM_STATE_DIR` | `/workspace/eim` | Persistent configs, jobs, logs and reports |
| `EIM_API_TOKEN` | unset | Optional bearer token for mutating APIs |

For shared deployments, set `EIM_API_TOKEN` and place authentication in front
of port 8080. The first version is an administrative portal, not a public
security boundary.

## Current limitations

- One model and one local vLLM server are supported.
- The sweep intentionally interrupts inference.
- Most configuration changes require a vLLM restart.
- Historical sweep discovery after a manager restart is not implemented yet.
- The build requires access to the configured Recipes Git repository.
- Automatic mapping currently covers Xeon 5 and Xeon 6. Xeon 4 and unknown
  processors require an explicit supported Recipes key.
- The manager remains available when recipe generation or vLLM startup fails,
  so the user can inspect the error and logs.
