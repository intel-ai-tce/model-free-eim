# SPDX-License-Identifier: Apache-2.0

ARG VLLM_BASE_IMAGE=vllm/vllm-openai-cpu:latest-x86_64
ARG VLLM_RECIPES_REPOSITORY=https://github.com/intel-ai-tce/vllm.git
ARG VLLM_RECIPES_REF=recipe_improve

# Fetch only the Recipes implementation. The application itself remains an
# independent project and does not modify or build the vLLM source tree.
FROM ${VLLM_BASE_IMAGE} AS recipes-source
ARG VLLM_RECIPES_REPOSITORY
ARG VLLM_RECIPES_REF
RUN git clone --depth 1 --branch "${VLLM_RECIPES_REF}" \
      "${VLLM_RECIPES_REPOSITORY}" /tmp/vllm-recipes-source \
    && test -f /tmp/vllm-recipes-source/tools/recipes/recipe_json_to_vllm_config.py

FROM ${VLLM_BASE_IMAGE}

USER root
WORKDIR /opt/vllm-recipes-manager

COPY --from=recipes-source /tmp/vllm-recipes-source/tools/recipes/ /opt/vllm-recipes/
COPY requirements.txt /opt/vllm-recipes-manager/requirements.txt
COPY app/ /opt/vllm-recipes-manager/app/

RUN python3 -m pip install --no-cache-dir \
      -r /opt/vllm-recipes/requirements.txt \
      -r /opt/vllm-recipes-manager/requirements.txt \
    && mkdir -p /workspace/eim/config /workspace/eim/jobs \
      /workspace/eim/logs /workspace/eim/home \
      /workspace/model-cache/huggingface \
    && chmod -R a+rwX /workspace/eim /workspace/model-cache

ENV EIM_STATE_DIR=/workspace/eim \
    EIM_RECIPES_DIR=/opt/vllm-recipes \
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

ENTRYPOINT ["python3", "/opt/vllm-recipes-manager/app/server.py"]
