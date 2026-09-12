# SPDX-License-Identifier: Apache-2.0

ARG VLLM_BASE_IMAGE=vllm/vllm-openai-cpu:latest-x86_64

FROM ${VLLM_BASE_IMAGE}

USER root
WORKDIR /opt/vllm-recipes-manager

# Recipes is staged by scripts/prepare-recipes.sh before the image build. This
# keeps GitHub access out of BuildKit and avoids cloning the full vLLM repo.
COPY vendor/recipes/ /opt/vllm-recipes/
COPY requirements.txt /opt/vllm-recipes-manager/requirements.txt
COPY app/ /opt/vllm-recipes-manager/app/

RUN test -f /opt/vllm-recipes/recipe_json_to_vllm_config.py \
    || (echo >&2 "Recipes not staged; run ./scripts/prepare-recipes.sh first"; exit 1) \
    && python3 -m pip install --no-cache-dir \
      -r /opt/vllm-recipes/requirements.txt \
      -r /opt/vllm-recipes-manager/requirements.txt \
    && mkdir -p /workspace/eim/config /workspace/eim/jobs \
      /workspace/eim/logs /workspace/eim/home \
      /workspace/model-cache/huggingface \
    && chmod -R a+rwX /workspace/eim /workspace/model-cache

ENV EIM_STATE_DIR=/workspace/eim \
    EIM_RECIPES_DIR=/opt/vllm-recipes \
    EIM_VLLM_WORKDIR=/vllm-workspace \
    EIM_HARDWARE=auto \
    EIM_MANAGER_HOST=0.0.0.0 \
    EIM_MANAGER_PORT=8080 \
    EIM_VLLM_HOST=0.0.0.0 \
    EIM_VLLM_PORT=8000 \
    HOME=/workspace/eim/home \
    HF_HOME=/workspace/model-cache/huggingface \
    PYTHONUNBUFFERED=1

EXPOSE 8000 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/api/health || exit 1

# Recipes may emit paths relative to the vLLM source tree, such as
# examples/tool_chat_template_gemma4.jinja. Restore the base image's runtime
# working directory so vLLM can resolve those bundled assets.
WORKDIR /vllm-workspace

ENTRYPOINT ["python3", "/opt/vllm-recipes-manager/app/server.py"]
