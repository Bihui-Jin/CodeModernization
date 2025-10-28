#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob

echo "Starting notebook copy script..."
SRC="/home/b27jin/mle-bench-internal/docker-test/scripts_full"
DST="/home/b27jin/CodeModernization/notebooks"

readarray -t COMPETITIONS <<'EOF'
aerial-cactus-identification
aptos2019-blindness-detection
denoising-dirty-documents
detecting-insults-in-social-commentary
dog-breed-identification
dogs-vs-cats-redux-kernels-edition
histopathologic-cancer-detection
jigsaw-toxic-comment-classification-challenge
leaf-classification
mlsp-2013-birds
new-york-city-taxi-fare-prediction
nomad2018-predict-transparent-conductors
plant-pathology-2020-fgvc7
random-acts-of-pizza
ranzcr-clip-catheter-line-classification
siim-isic-melanoma-classification
spooky-author-identification
tabular-playground-series-dec-2021
tabular-playground-series-may-2022
text-normalization-challenge-english-language
text-normalization-challenge-russian-language
the-icml-2013-whale-challenge-right-whale-redux
EOF

echo "Notebook copy script initialized."

total_copied=0

for prefix in "${COMPETITIONS[@]}"; do
  matches=( "$SRC"/"$prefix"*.ipynb )

  # echo "[INFO] $prefix — found ${#matches[@]} notebooks."

  # Count how many matching notebooks exist for this competition.
  count=$(find "$SRC" -maxdepth 1 -type f -name "${prefix}*.ipynb" | wc -l || true)
  if (( count == 0 )); then
    echo "[SKIP] $prefix — no notebooks found."
    continue
  fi

  # echo "[INFO] $prefix — processing $count notebooks."

  # Randomly choose up to 15 notebooks for THIS competition
  picked=()
  copied_this=0
  mapfile -t picked < <(printf '%s\0' "${matches[@]}" | xargs -0 -n1 | shuf | head -n 15 || true)

  echo "[INFO] $prefix — selected ${#picked[@]} notebooks for copying."

  for nb in "${picked[@]}"; do
    cp -n -- "$nb" "$DST"/ && {
      copied_this=$((copied_this+1))
      total_copied=$((total_copied+1))
    }
  done

  echo "[OK]   $prefix — selected ${#picked[@]} (of $count); copied $copied_this."
done

echo "================================================================"
echo "All done. Total notebooks copied: $total_copied → $DST"