#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != Linux ]]; then
  echo "Linux build required" >&2
  exit 1
fi

export QWENSCRIBE_BUILD_VARIANT=gal_cpu
python -m PyInstaller --clean --noconfirm QwenASRDesktop.spec
package="dist/QwenScribe-GalCPU-Linux-x86_64"
test -x "$package/QwenScribeDesktop"
if find "$package" -type f \( -name '*.safetensors' -o -name '*.gguf' -o -name '*.part' \) | grep -q .; then
  echo "Model weights or partial downloads must not be packaged" >&2
  exit 1
fi
"$package/QwenScribeDesktop" --check > "dist/gal-linux-check.json"
"$package/QwenScribeDesktop" --smoke-test-package "dist/gal-linux-smoke.json"
"$package/QwenScribeDesktop" --gal-cutter-cli --help > "dist/gal-linux-cli-help.txt"
printf '{"command":"close"}\n' | "$package/QwenScribeDesktop" --forced-aligner-worker > "dist/gal-linux-worker-smoke.json"
grep -q '"ok": true' "dist/gal-linux-worker-smoke.json"
cp README.md "$package/README.md"
cp docs/GAL_TTS_BATCH_CONTRACT.md "$package/GAL_TTS_BATCH_CONTRACT.md"
cp THIRD_PARTY_NOTICES.md "$package/THIRD_PARTY_NOTICES.md"
tar -C dist -czf "dist/QwenScribe-GalCPU-Linux-x86_64.tar.gz" "QwenScribe-GalCPU-Linux-x86_64"
sha256sum "dist/QwenScribe-GalCPU-Linux-x86_64.tar.gz" > "dist/QwenScribe-GalCPU-Linux-x86_64.sha256"
