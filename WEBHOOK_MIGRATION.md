# Polling → Webhook (ixtiyoriy, env bilan boshqariladi)

Bot endi **dual-mode**: `WEBHOOK_URL` env o'rnatilsa webhook, aks holda polling.
**Default = polling** — hech narsa o'rnatmasangiz, hozirgi xatti-harakat aynan o'zgarmaydi.
Webhook = pastroq kechikish + kamroq bo'sh trafik; masshtab uchun foydali (hozirgi
yuk uchun shart emas — bu optimizatsiya, bug tuzatish emas).

## Nega kerak emas (hali)
Polling joriy yuk uchun mutlaqo yetarli. Webhook'ni faqat foydalanuvchi/yuk o'sganda
yoqing. Noto'g'ri sozlangan webhook = bot **jim** qoladi (xato bermaydi), shuning
uchun cutover ehtiyotkor bo'lsin.

## Env o'zgaruvchilari (`.env`, VPS'da)
| Env | Misol | Izoh |
|-----|-------|------|
| `WEBHOOK_URL` | `https://tezbozor.duckdns.org/tg/9f3k...` | Telegram POST qiladigan TO'LIQ ommaviy URL. Oxirgi bo'lak — **maxfiy** token-yo'l |
| `WEBHOOK_PORT` | `8443` | Bot lokal tinglaydigan port (nginx orqasida). Default 8443 |
| `WEBHOOK_PATH` | `tg/9f3k...` | Ixtiyoriy. Berilmasa `WEBHOOK_URL` oxirgi bo'lagidan olinadi |
| `WEBHOOK_SECRET` | `uzun-tasodifiy-satr` | Ixtiyoriy. Telegram so'rovini `X-Telegram-Bot-Api-Secret-Token` header bilan tasdiqlaydi |

## VPS qadamlari
```bash
# 0) Webhook kutubxonasi (PTB [webhooks] extra — tornado). requirements.txt'da bor,
#    lekin eski o'rnatishda bo'lmasligi mumkin — aks holda run_webhook RuntimeError beradi:
python3.14 -m pip install "python-telegram-bot[job-queue,webhooks]==22.7" --break-system-packages

# 1) Maxfiy yo'l + sirni generatsiya
SECRET_PATH="tg/$(openssl rand -hex 16)"
SECRET_TOKEN="$(openssl rand -hex 32)"

# 2) nginx: ommaviy yo'lni bot lokal portiga proxy qilamiz (webapp server bloki ichiga)
#    location = /tg/<...>  { proxy_pass http://127.0.0.1:8443; }
#    (webapp allaqachon shu domenda TLS bilan ishlaydi — sertifikat qayta ishlatiladi)
cat >> /etc/nginx/sites-available/tezbozor <<EOF
    location /${SECRET_PATH} {
        proxy_pass http://127.0.0.1:8443/${SECRET_PATH};
        proxy_set_header Host \$host;
    }
EOF
nginx -t && systemctl reload nginx

# 3) .env'ga qo'shamiz
echo "WEBHOOK_URL=https://tezbozor.duckdns.org/${SECRET_PATH}" >> /root/.env
echo "WEBHOOK_PORT=8443" >> /root/.env
echo "WEBHOOK_SECRET=${SECRET_TOKEN}" >> /root/.env

# 4) Botni qayta yoqamiz — run_webhook o'zi set_webhook chaqiradi (webhook_url + secret_token)
systemctl restart tezbozor-bot
journalctl -u tezbozor-bot -n 30 --no-pager   # "Webhook rejimi: ..." log chiqsin

# 5) Tekshirish: Telegram webhook holati
curl -s "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
#   -> "url" to'g'ri, "pending_update_count" o'smasligi, "last_error_message" yo'q
```

## Smoke-test
Botga `/start` yozing → darhol javob. Mahsulot ko'rish, savatga qo'shish, buyurtma.

## Rollback (polling'ga qaytish)
```bash
# .env'dan WEBHOOK_URL ni olib tashlang (yoki bo'sh qoldiring) va webhook'ni o'chiring
curl -s "https://api.telegram.org/bot<TOKEN>/deleteWebhook"
sed -i '/^WEBHOOK_URL=/d' /root/.env
systemctl restart tezbozor-bot     # WEBHOOK_URL yo'q → polling
```

## Eslatma
- Webhook va polling **bir vaqtda** ishlay olmaydi (Telegram cheklovi). Webhook
  yoqilsa `getUpdates` (polling) 409 beradi — shu sabab dual-mode `else` orqali
  faqat bittasini ishga tushiradi.
- TLS nginx'da terminatsiya bo'ladi; bot 127.0.0.1'da oddiy HTTP tinglaydi (xavfsiz,
  chunki port faqat lokal). Telegram → nginx (HTTPS) → bot (lokal HTTP).
