# Деплой Robot.KG на VPS (Ubuntu 22.04/24.04)

Схема: браузер → **nginx** (HTTPS, статика, медиа) → unix-сокет → **gunicorn** → Django → SQLite.

Все команды выполняются на сервере, если не сказано иначе. `<IP>` — IP вашего VPS.

## 1. Подключиться и обновить систему

```bash
ssh root@<IP>
apt update && apt upgrade -y
apt install -y python3 python3-venv git nginx certbot python3-certbot-nginx
```

## 2. Пользователь и код

```bash
adduser --system --group --home /srv/robot-kg robotkg
usermod -aG www-data robotkg
git clone https://github.com/GitHubNurisalsm/robot-kg.git /srv/robot-kg-tmp
cp -a /srv/robot-kg-tmp/. /srv/robot-kg/ && rm -rf /srv/robot-kg-tmp
cd /srv/robot-kg
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 3. Переменные окружения

```bash
cp deploy/env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # скопировать в DJANGO_SECRET_KEY
nano .env
chmod 600 .env
```

## 4. База, статика, админ

```bash
set -a; . ./.env; set +a
.venv/bin/python manage.py check --deploy
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py seed_demo            # демо-товары (по желанию)
.venv/bin/python manage.py createsuperuser
mkdir -p media
chown -R robotkg:www-data /srv/robot-kg
chmod 750 /srv/robot-kg
```

## 5. gunicorn (systemd)

```bash
cp deploy/robot-kg.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now robot-kg
systemctl status robot-kg          # должно быть active (running)
```

## 6. nginx

```bash
cp deploy/nginx-robot-kg.conf /etc/nginx/sites-available/robot-kg
ln -s /etc/nginx/sites-available/robot-kg /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

## 7. DNS (панель регистратора)

Для `robot.kg` нужны A-записи: `@` → `<IP>` и `www` → `<IP>`.
Сейчас NS домена указывают на hoster.kg — записи создаются там, где реально обслуживается DNS
(или NS переключаются на «Услугу DNS» cctld.kg). Проверка с любого компьютера:

```bash
dig +short robot.kg A        # должен вернуть <IP>
```

## 8. HTTPS

Только после того, как DNS начал возвращать `<IP>`:

```bash
certbot --nginx -d robot.kg -d www.robot.kg --redirect
```

## 9. Файрвол

```bash
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw enable
```

## Обновление сайта после новых коммитов

```bash
cd /srv/robot-kg
sudo -u robotkg git pull
sudo -u robotkg .venv/bin/pip install -r requirements.txt
set -a; . ./.env; set +a
sudo -u robotkg -E .venv/bin/python manage.py migrate
sudo -u robotkg -E .venv/bin/python manage.py collectstatic --noinput
systemctl restart robot-kg
```

## Резервная копия базы

```bash
sqlite3 /srv/robot-kg/db.sqlite3 ".backup '/root/backup-$(date +%F).sqlite3'"
```

## Если что-то не работает

| Симптом | Где смотреть |
|---|---|
| 502 Bad Gateway | `journalctl -u robot-kg -n 50` — gunicorn не запустился |
| Нет стилей | выполнен ли `collectstatic`, права на `/srv/robot-kg/staticfiles` |
| 400 Bad Request | домен не указан в `DJANGO_ALLOWED_HOSTS` |
| 403 CSRF при отправке формы | `DJANGO_CSRF_TRUSTED_ORIGINS` в `.env` (с `https://`) |
| Ошибка nginx | `nginx -t`, `tail /var/log/nginx/error.log` |
