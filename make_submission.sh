#!/usr/bin/env bash
# 產生交付包：submission/ 與 submission.zip（只含題目要求的內容）
set -euo pipefail
cd "$(dirname "$0")"

rm -rf submission submission.zip
mkdir -p submission/poc/output

cp answer-v0-gemini.md submission/answers.md
sed 's/\[answer-v0-gemini\.md\](answer-v0-gemini\.md)/[answers.md](answers.md)/' \
  taxonomy-and-priority-spec.md > submission/taxonomy-and-priority-spec.md

cp -R poc/README.md poc/pyproject.toml poc/uv.lock poc/.gitignore \
      poc/triage.py poc/evaluate.py poc/pipeline poc/config poc/data submission/poc/
cp poc/output/triage_result.csv poc/output/review.html poc/output/run.log submission/poc/output/
find submission -name '__pycache__' -prune -exec rm -rf {} + -o -name '.DS_Store' -exec rm -f {} +

(cd submission && zip -qr ../submission.zip .)
echo "OK: submission/ and submission.zip"
