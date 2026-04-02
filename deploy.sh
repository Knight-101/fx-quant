#!/usr/bin/env bash
# FX1 deployment script — run from LOCAL machine
# Usage: SERVER=user@your-azure-ip bash deploy.sh
set -euo pipefail

SERVER="${SERVER:?Set SERVER=user@ip before running this script}"
REMOTE_DIR="/opt/fx1"
SERVICE_NAME="fx1"

echo "==> Deploying FX1 to ${SERVER}:${REMOTE_DIR}"

# ── 1. Sync source (exclude heavy/ephemeral dirs) ─────────────────────────────
echo "==> Syncing source files…"
rsync -avz --progress \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.pyc' \
  --exclude 'data/cache/' \
  --exclude 'artifacts/' \
  --exclude 'backtest/results/' \
  --exclude 'backtests/' \
  --exclude 'backtests_smoke_true/' \
  --exclude 'frontend/node_modules/' \
  --exclude 'frontend/dist/' \
  --exclude '.git/' \
  --exclude '*.egg-info/' \
  --exclude '.venv/' \
  --exclude 'venv/' \
  "$(dirname "$0")/" \
  "${SERVER}:${REMOTE_DIR}/"

# ── 2. Remote setup ───────────────────────────────────────────────────────────
echo "==> Running remote setup…"
ssh "${SERVER}" bash -s <<'REMOTE'
set -euo pipefail
REMOTE_DIR="/opt/fx1"

echo "--- Creating artifact dirs…"
mkdir -p "${REMOTE_DIR}/artifacts/models"
mkdir -p "${REMOTE_DIR}/data/cache"
mkdir -p "${REMOTE_DIR}/backtest/results"

echo "--- Setting up Python venv…"
if [ ! -d "${REMOTE_DIR}/venv" ]; then
  python3 -m venv "${REMOTE_DIR}/venv"
fi

echo "--- Installing Python deps…"
"${REMOTE_DIR}/venv/bin/pip" install --upgrade pip -q
"${REMOTE_DIR}/venv/bin/pip" install -r "${REMOTE_DIR}/requirements_fx.txt" -q

echo "--- Building React frontend…"
cd "${REMOTE_DIR}/frontend"
if command -v npm &>/dev/null; then
  npm ci --silent
  npm run build
else
  echo "WARNING: npm not found — skipping frontend build. Install Node.js on the server."
fi

echo "--- Installing systemd service…"
cp "${REMOTE_DIR}/fx1.service" /etc/systemd/system/fx1.service
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

echo "--- Service status:"
sleep 2
systemctl status "${SERVICE_NAME}" --no-pager || true
REMOTE

# ── 3. Done ───────────────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo "  FX1 Dashboard deployed successfully!"
echo "  URL: http://$(echo ${SERVER} | cut -d@ -f2):8001"
echo "=========================================="
