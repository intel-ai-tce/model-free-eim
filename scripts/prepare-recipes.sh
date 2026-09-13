#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
project_dir=$(cd -- "${script_dir}/.." && pwd)
repository=${VLLM_RECIPES_REPOSITORY:-https://github.com/intel-ai-tce/vllm.git}
ref=${VLLM_RECIPES_REF:-recipe_improve}
destination="${project_dir}/vendor/vllm-recipes-tools"
temporary_dir=$(mktemp -d)

cleanup() {
  rm -rf -- "${temporary_dir}"
}
trap cleanup EXIT

checkout="${temporary_dir}/checkout"
staged="${temporary_dir}/vllm-recipes-tools"

echo "Fetching vLLM Recipes tools from ${repository} (${ref})..."
git init -q "${checkout}"
git -C "${checkout}" remote add origin "${repository}"
git -C "${checkout}" sparse-checkout init --cone
git -C "${checkout}" sparse-checkout set tools/recipes
git -C "${checkout}" -c protocol.version=2 fetch \
  --depth=1 \
  --filter=blob:none \
  --no-tags \
  origin "${ref}"
git -C "${checkout}" checkout -q --detach FETCH_HEAD

mkdir -p "${staged}"
cp -a "${checkout}/tools/recipes/." "${staged}/"
test -f "${staged}/recipe_json_to_vllm_config.py"
test -f "${staged}/requirements.txt"

commit=$(git -C "${checkout}" rev-parse HEAD)
printf '%s\n' "${commit}" >"${staged}/SOURCE_COMMIT"
printf '%s\n' "${repository}" >"${staged}/SOURCE_REPOSITORY"

mkdir -p "$(dirname -- "${destination}")"
if [[ -e "${destination}" ]]; then
  backup="${destination}.backup.$(date +%Y%m%d%H%M%S)"
  mv -- "${destination}" "${backup}"
  echo "Previous staged vLLM Recipes tools saved at ${backup}"
fi
mv -- "${staged}" "${destination}"

echo "Staged vLLM Recipes tools commit ${commit}"
echo "Next: docker build -t vllm-recipes-manager:latest ${project_dir}"
