# Deploying the AFRIMAPESA preview (DigitalOcean + GoDaddy)

One server runs everything with Docker Compose. Caddy terminates HTTPS (free Let's Encrypt
certificates), puts a password on the whole site, and routes `/v1`, `/admin`, `/static`,
`/health` to Django and everything else to Next.js.

```
Internet ──443──> Caddy ──> web (Next.js :3000)
                        └─> api (Django/gunicorn :8000) ──> db (Postgres + TimescaleDB), redis
```

## 1. Create the droplet (DigitalOcean)

- **Create → Droplets**, region **London (LON1)**, image **Ubuntu 24.04 LTS**.
- Plan: **Basic → Regular SSD → 2 GB RAM / 1 vCPU / 50 GB** (\$12/month). Smaller plans
  run out of memory building the frontend.
- **Authentication: SSH key** (not password). On your PC: `ssh-keygen -t ed25519`, then
  paste the contents of `~/.ssh/id_ed25519.pub` into DigitalOcean.
- Enable **weekly backups**.
- Note the droplet's **public IPv4** address.

## 2. Point the domain at it (GoDaddy)

GoDaddy → **My Products → your domain → DNS → Add new record**:

| Type | Name | Value | TTL |
|---|---|---|---|
| A | `preview` | the droplet IPv4 | 600 seconds |

This serves the preview at `preview.<your-domain>` and leaves the root domain free for
launch. Check it has propagated (can take a few minutes): `nslookup preview.<your-domain>`.

## 3. Prepare the server (once)

```bash
ssh root@<droplet-ip>

# Firewall: SSH + web only
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable

# 2 GB swap: headroom for the frontend build
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

# Docker
curl -fsSL https://get.docker.com | sh
```

## 4. Get the code

The repos are private. Create a GitHub **fine-grained personal access token** with
read-only **Contents** access to `afrimapesa/backend-app` and `afrimapesa/frontend-app`,
then:

```bash
mkdir -p /opt/afrimapesa && cd /opt/afrimapesa
git clone https://<token>@github.com/afrimapesa/backend-app.git
git clone https://<token>@github.com/afrimapesa/frontend-app.git
```

## 5. Configure

```bash
cd /opt/afrimapesa/backend-app/deploy
cp .env.prod.example .env.prod

# preview password hash (put it in PREVIEW_PASSWORD_HASH, keep the single quotes)
docker run --rm caddy:2-alpine caddy hash-password --plaintext 'choose-a-password'
# secrets for DJANGO_SECRET_KEY and POSTGRES_PASSWORD
openssl rand -base64 48 | tr -d '\n/+='; echo

nano .env.prod   # set DOMAIN=preview.<your-domain>, ACME_EMAIL, the hash and secrets
chmod 600 .env.prod
```

## 6. Start

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
docker compose -f docker-compose.prod.yml --env-file .env.prod ps
```

The first build takes several minutes. Open `https://preview.<your-domain>`, log in with
`PREVIEW_USER` and the password. Django admin: create a login with

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec api python manage.py createsuperuser
```

## Updating after new commits

```bash
cd /opt/afrimapesa/frontend-app && git pull
cd /opt/afrimapesa/backend-app && git pull
cd deploy && docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

Migrations run automatically when the `api` container starts.

## Useful commands

```bash
C="docker compose -f docker-compose.prod.yml --env-file .env.prod"
$C logs -f --tail=100 api        # or web, caddy, db
$C exec api python manage.py import_fx_history /path/in/container.xlsx
$C exec db pg_dump -U afrimapesa afrimapesa | gzip > backup-$(date +%F).sql.gz
```

To copy a file into the api container for import: `docker cp rates.xlsx afrimapesa-api-1:/tmp/`.
