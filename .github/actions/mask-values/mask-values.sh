#!/usr/bin/env bash
# Reads values on stdin (one per line, or a JSON document) and prints an ::add-mask:: command
# for each line, each GUID inside the input, and each key and string of a JSON document, so a
# value stays masked when a later step prints only a part of it (a subscription ID inside a
# resource ID, one object ID out of a JSON map). Shorter than MASK_MIN_LENGTH: not masked.
set -euo pipefail

min_length="${MASK_MIN_LENGTH:?MASK_MIN_LENGTH is not set}"
guid='[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
input=$(cat)

{
  tr -d '\r' <<<"$input"
  grep -Eo "$guid" <<<"$input" || true
  if jq -e 'type == "object" or type == "array"' >/dev/null 2>&1 <<<"$input"; then
    jq -r '(.. | strings), (.. | objects | keys[])' <<<"$input"
  fi
} | awk -v min="$min_length" 'length($0) >= min' | sort -u | while IFS= read -r value; do
  # Workflow command data escapes % first (docs: "workflow commands", escaping).
  printf '::add-mask::%s\n' "${value//%/%25}"
done
