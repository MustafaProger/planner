#!/bin/sh
set -eu
if [ "${RENEWED_LINEAGE:-}" != /etc/letsencrypt/live/charterstats.ru ]; then
    exit 0
fi
/usr/sbin/nginx -t
/usr/bin/systemctl reload nginx
