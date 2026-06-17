# Mini App deploy (Faza 1)

Bot bilan yonma-yon FastAPI backend + HTML katalog. **O'sha PostgreSQL** bazaga ulanadi.

## Fayllar
| Fayl | Vazifa |
|------|--------|
| `webapp_server.py` | FastAPI backend (katalog API + rasm-proksi) |
| `webapp_auth.py` | Telegram initData imzo tekshiruvi (6/6 test) |
| `webapp_static/index.html` | Rasm gridli katalog frontend |
| `webapp_requirements.txt` | fastapi, uvicorn, httpx |

API: `/api/categories`, `/api/products`, `/api/products/{id}`, `/api/image/{file_id}`, `/api/config`.
Har bir API `Authorization: tma <initData>` talab qiladi (bot tokeni bilan tekshiriladi).

## 1. Fayllarni yuklash (kompyuterda)
```powershell
scp C:\marketplace-bot\webapp_server.py C:\marketplace-bot\webapp_auth.py C:\marketplace-bot\webapp_requirements.txt root@178.105.229.54:/root/
scp -r C:\marketplace-bot\webapp_static root@178.105.229.54:/root/
```

## 2. Paketlar (server)
```bash
python3 -m pip install -r /root/webapp_requirements.txt --break-system-packages
```

## 3. Backend'ni systemd xizmati qilish (server)
```bash
cat > /etc/systemd/system/tezbozor-webapp.service <<'EOF'
[Unit]
Description=TezBozor Mini App
After=network.target postgresql.service

[Service]
WorkingDirectory=/root
ExecStart=/usr/bin/python3 -m uvicorn webapp_server:app --host 127.0.0.1 --port 8080
Restart=always

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now tezbozor-webapp
systemctl status tezbozor-webapp --no-pager
curl -s localhost:8080/api/health
```
➡️ `{"ok":true,"backend":"postgres"}` chiqsa — backend ishlayapti.

## 4. HTTPS — DuckDNS (bepul) + nginx + Let's Encrypt
1. https://www.duckdns.org → GitHub/Google bilan kiring → subdomen yarating (masalan `tezbozor`) → IP'ga `178.105.229.54` qo'ying.
2. Server:
```bash
apt install -y nginx certbot python3-certbot-nginx
cat > /etc/nginx/sites-available/tezbozor <<'EOF'
server {
    listen 80;
    server_name tezbozor.duckdns.org;
    client_max_body_size 5m;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
EOF
ln -sf /etc/nginx/sites-available/tezbozor /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d tezbozor.duckdns.org --non-interactive --agree-tos -m beksherzod41@gmail.com --redirect
```
➡️ Endi `https://tezbozor.duckdns.org` ochilsa — katalog ko'rinadi (lekin to'g'ridan brauzerда 401 — chunki initData yo'q; faqat Telegram orqali ishlaydi).

## 5. Botda Mini App tugmasi
`main.py` ga `WebAppInfo` tugma qo'shiladi (URL: `https://tezbozor.duckdns.org`). Buyurtma deep-link uchun bot `/start order_<id>` ni qo'llashi kerak. — bu qadamni Claude qiladi (URL tayyor bo'lgach).

## Eslatma
- Mini App faqat **HTTPS** + Telegram ichidа ishlaydi (brauzerда 401 normal).
- Rasmlar `/api/image/{file_id}` orqali (Telegram getFile + disk-cache `/root/img_cache`).
