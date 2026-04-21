#!/usr/bin/env bash
set -euo pipefail

theme="${1:-}"
case "$theme" in
  light | dark)
    ;;
  *)
    echo "Unknown theme '$theme'" >&2
    exit 1
    ;;
esac

flavor="mocha"
if [[ "$theme" == "light" ]]; then
  flavor="latte"
fi

declare -a roots=(
  "/usr/share/Kvantum"
  "${XDG_CONFIG_HOME:-$HOME/.config}/Kvantum"
)

declare -a candidates=()
for root in "${roots[@]}"; do
  [[ -d "$root" ]] || continue
  while IFS= read -r -d '' dir; do
    name="$(basename "$dir")"
    lower_name="${name,,}"
    [[ "$lower_name" == *catppuccin* ]] || continue
    candidates+=("$name")
  done < <(find "$root" -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null)
done

if [[ "${#candidates[@]}" -eq 0 ]]; then
  echo "warning: no Catppuccin Kvantum themes found under ${roots[*]}; skipping kvantum update" >&2
  exit 0
fi

unique_candidates=()
while IFS= read -r name; do
  [[ -n "$name" ]] || continue
  unique_candidates+=("$name")
done < <(printf '%s\n' "${candidates[@]}" | awk '!seen[$0]++' | sort -f)

other_flavor="latte"
if [[ "$flavor" == "latte" ]]; then
  other_flavor="mocha"
fi

selected=""
best_score=-1
for name in "${unique_candidates[@]}"; do
  lower_name="${name,,}"
  score=0

  [[ "$lower_name" == *"$flavor"* ]] && ((score += 100))
  [[ "$lower_name" == *"lavender"* ]] && ((score += 20))
  [[ "$lower_name" == *"$other_flavor"* ]] && ((score -= 100))

  if (( score > best_score )); then
    selected="$name"
    best_score=$score
  fi
done

if [[ -z "$selected" ]]; then
  echo "warning: unable to resolve Catppuccin $flavor Kvantum theme; skipping kvantum update" >&2
  exit 0
fi

config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/Kvantum"
config_file="$config_dir/kvantum.kvconfig"
mkdir -p "$config_dir"

tmp="$(mktemp "${config_file}.tmp.XXXXXX")"
cat >"$tmp" <<EOF
[General]
theme=$selected
EOF
mv "$tmp" "$config_file"

echo "setting kvantum theme to $selected"
