#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"
CALLBACK_PORT="${ZIVO_PAYMENT_CALLBACK_PORT:-8765}"
SITE_NAME="zivo-payment"
SITE_AVAIL="/etc/nginx/sites-available/${SITE_NAME}"
SITE_ENABLED="/etc/nginx/sites-enabled/${SITE_NAME}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: run as root"
  exit 1
fi

DOMAIN="${DOMAIN#http://}"
DOMAIN="${DOMAIN#https://}"
DOMAIN="${DOMAIN%%/*}"
DOMAIN="${DOMAIN%.}"
DOMAIN="$(printf '%s' "$DOMAIN" | tr '[:upper:]' '[:lower:]')"

if [[ ! "$DOMAIN" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]] || [[ "$DOMAIN" != *.* ]]; then
  echo "ERROR: invalid domain. Example: pay.example.com"
  exit 1
fi

if ! getent ahostsv4 "$DOMAIN" >/dev/null 2>&1; then
  echo "ERROR: DNS for $DOMAIN does not resolve yet. Point the domain A record to this server first."
  exit 1
fi

echo "[1/7] Installing Nginx/Certbot if needed..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y >/dev/null
apt-get install -y nginx certbot python3-certbot-nginx curl >/dev/null

echo "[2/7] Writing dedicated ZIVO payment reverse proxy..."
cat > "$SITE_AVAIL" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    access_log /var/log/nginx/zivo-payment-access.log;
    error_log  /var/log/nginx/zivo-payment-error.log;

    location = /zivo/payment/health {
        proxy_pass http://127.0.0.1:${CALLBACK_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 3s;
        proxy_read_timeout 10s;
    }

    location = /zivo/zibal/callback {
        proxy_pass http://127.0.0.1:${CALLBACK_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 5s;
        proxy_read_timeout 30s;
    }

    location / {
        return 404;
    }
}
EOF
ln -sfn "$SITE_AVAIL" "$SITE_ENABLED"
nginx -t
systemctl enable --now nginx
systemctl reload nginx

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
  ufw allow 'Nginx Full' >/dev/null || true
fi

echo "[3/7] Checking ZIVO local callback worker..."
if ! curl -fsS --max-time 4 "http://127.0.0.1:${CALLBACK_PORT}/zivo/payment/health" | grep -q 'ZIVO PAYMENT OK'; then
  echo "ERROR: ZIVO callback worker is not responding on 127.0.0.1:${CALLBACK_PORT}."
  echo "Install/restart zivo60.96.38 first, then run this script again."
  exit 1
fi

echo "[4/7] Checking Nginx proxy locally..."
curl -fsS --max-time 4 -H "Host: ${DOMAIN}" "http://127.0.0.1/zivo/payment/health" | grep -q 'ZIVO PAYMENT OK'

echo "[5/7] Requesting/refreshing HTTPS certificate..."
CERTBOT_ARGS=(--nginx -d "$DOMAIN" --redirect --non-interactive --agree-tos)
if [[ -n "$EMAIL" ]]; then
  CERTBOT_ARGS+=(--email "$EMAIL")
else
  CERTBOT_ARGS+=(--register-unsafely-without-email)
fi
certbot "${CERTBOT_ARGS[@]}"

echo "[6/7] Verifying public HTTPS health endpoint..."
curl -fsS --max-time 15 "https://${DOMAIN}/zivo/payment/health" | grep -q 'ZIVO PAYMENT OK'

echo "[7/7] ZIVO payment domain ready."
echo "DOMAIN=${DOMAIN}"
echo "CALLBACK=https://${DOMAIN}/zivo/zibal/callback"
echo "HEALTH=https://${DOMAIN}/zivo/payment/health"
echo "The main website does NOT need to be running. This domain only proxies the payment callback."
