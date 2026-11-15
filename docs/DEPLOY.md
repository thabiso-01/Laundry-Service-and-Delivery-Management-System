# Deploying LaundryConnect for free (Oracle Cloud, Johannesburg)

Everything runs on **one free Oracle Cloud server** with Docker Compose:
PostgreSQL + the API + Caddy (serves the website, forwards `/api`, gets HTTPS
certificates automatically). Data stays in South Africa (POPIA).

Total time: about an hour. You'll need a card to verify the Oracle account
(nothing is charged within the Always Free limits).

---

## 0. Try it on your own computer first (optional)

```bash
python deploy/make_env.py --local --port 8088
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
# open http://localhost:8088
```

Delete `.env.prod` afterwards (`docker compose -f docker-compose.prod.yml --env-file .env.prod down -v`
removes the local data too) – the server gets its own.

---

## 1. Create the server

1. Sign up at **https://cloud.oracle.com** → *Start for free*.
   **Home region: South Africa Central (Johannesburg).** It can't be changed later.
2. *Compute → Instances → Create instance*:
   - **Image:** Canonical Ubuntu 24.04
   - **Shape:** *Ampere* → **VM.Standard.A1.Flex**, **2 OCPUs, 12 GB memory** (free)
   - **Networking:** create a new VCN with a public subnet; *assign a public IPv4 address*
   - **SSH keys:** *Generate a key pair* → **download the private key** (you can't get it again)
   - **Boot volume:** 100 GB
3. Open the web ports: *Networking → Virtual cloud networks → your VCN → Security
   Lists → Default → Add Ingress Rules*, twice:
   - Source `0.0.0.0/0`, TCP, destination port **80**
   - Source `0.0.0.0/0`, TCP, destination port **443**
4. Copy the instance's **public IP address**.

> Oracle may reclaim Always Free servers that sit almost idle for a week. To
> avoid that, upgrade the account to *Pay As You Go* (usage within the free
> limits still costs nothing).

## 2. Free domain name

1. Go to **https://www.duckdns.org**, sign in.
2. Add a subdomain, e.g. `laundryconnect` → you get `laundryconnect.duckdns.org`.
3. Paste the server's public IP into *current ip* and click *update ip*.

## 3. Connect and prepare the server

```bash
# on your computer (Windows PowerShell works too)
ssh -i path/to/ssh-key.key ubuntu@<public-ip>
```

On the server:

```bash
# Oracle's Ubuntu images block web ports in the server's own firewall too
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save

# Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
exit        # log out and ssh in again so the docker group applies
```

## 4. Install LaundryConnect

```bash
git clone https://github.com/thabiso-01/Laundry-Service-and-Delivery-Management-System.git laundryconnect
cd laundryconnect

# Secrets are generated for you. Use your own domain and a contact e-mail.
python3 deploy/make_env.py --domain laundryconnect.duckdns.org --contact you@example.co.za
cat .env.prod      # copy POSTGRES_PASSWORD and BACKUP_ENCRYPTION_KEY into a password manager NOW

sudo chown 10001:10001 backups      # the API container writes backups here

docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
docker compose -f docker-compose.prod.yml --env-file .env.prod ps     # all three should be running
```

The first start takes a few minutes. Caddy then gets the HTTPS certificate by
itself. Open **https://laundryconnect.duckdns.org**.

Create your administrator (asks for a password):

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec api \
  python -m app.scripts.create_admin --email you@example.co.za --name "Your Name"
```

**Never run `seed_demo` on the real server** – it creates accounts with a public password.

## 5. Backups

Nightly encrypted backup with a test restore (see `docs/BACKUPS.md`):

```bash
crontab -e
```

Add this line (adjust the folder if you cloned elsewhere):

```
0 2 * * * cd /home/ubuntu/laundryconnect && docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T api python -m app.scripts.backup >> backups/backup.log 2>&1
```

**Off-site copy (free):** create a Cloudflare account → *R2* → bucket
`laundryconnect-backups` → *Manage API tokens* (Object Read & Write). Then:

```bash
sudo apt-get install -y rclone
rclone config        # new remote "r2", type "s3", provider "Cloudflare", paste the keys and endpoint
crontab -e           # add:
30 2 * * * rclone copy /home/ubuntu/laundryconnect/backups r2:laundryconnect-backups --exclude "*.log"
```

Backups are encrypted, so Cloudflare can't read them. Keep the
`BACKUP_ENCRYPTION_KEY` in your password manager – without it they can't be restored.

## 6. Real payments and SMS (when ready)

Edit `.env.prod`, then restart the API:

```bash
nano .env.prod     # PAYMENT_PROVIDER=payfast + PAYFAST_* (docs/PAYMENTS.md), SMS_PROVIDER=bulksms + BULKSMS_* (docs/SMS.md)
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
docker compose -f docker-compose.prod.yml --env-file .env.prod exec api python -m app.scripts.payfast_check
docker compose -f docker-compose.prod.yml --env-file .env.prod exec api python -m app.scripts.sms_check --to "082 123 4567"
```

PayFast notifications reach `https://<your-domain>/api/payments/payfast/notify` automatically.

## Updating

```bash
cd ~/laundryconnect
git pull
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

Database changes are applied automatically when the API starts. Take a backup first
(`... exec -T api python -m app.scripts.backup`) before big updates.

## Troubleshooting

| Problem | Check |
|---|---|
| Site doesn't load | `docker compose -f docker-compose.prod.yml --env-file .env.prod ps` and `... logs web` |
| No HTTPS / certificate errors | Ports 80 and 443 open in **both** the Oracle Security List and `iptables`; DuckDNS points to the right IP; `... logs web` |
| API errors | `... logs api` |
| Restore from a backup | `... exec api python -m app.scripts.restore latest --yes` (see `docs/BACKUPS.md`) |
