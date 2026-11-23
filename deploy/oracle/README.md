# Deploying to an Oracle Cloud Always Free VM

This moves the app off Render's free Web Service (which sleeps ~50 s per cold start) to
an always-on Oracle Cloud VM. Nothing about the app changes: same repo, same
`scripts/start_railway.py`, same Neon `DATABASE_URL`. The VM holds no data — if it is
ever destroyed, the database is untouched and this guide re-creates everything.

Files in this directory:

| File | Purpose |
| --- | --- |
| `setup_vm.sh` | One-time provisioning: packages, Python venv, service user, firewall, Caddy HTTPS, systemd unit. Safe to re-run. |
| `sts.service` | systemd unit that runs the same start script as Render. |
| `Caddyfile` | Reverse proxy + automatic HTTPS (Let's Encrypt). |
| `deploy.sh` | Pull latest `main`, reinstall deps, restart the service. |
| `.env.example` | Variable names only. Real values live in `/etc/sts/sts.env` on the VM, never in git. |

## What you need

- An Oracle Cloud account (free signup; a card is used for identity verification, not charged).
- Pick a **home region near Kenya** at signup — e.g. `South Africa Central (Johannesburg)`.
  Always Free resources only exist in the home region.
- ~20 minutes and an SSH key.

## Step 1 — Create the VM (Oracle console)

Compute → Instances → **Create instance**:

1. **Name**: `mytransport`
2. **Image**: Canonical **Ubuntu 24.04** (the aarch64 build is offered automatically for A1 shapes).
3. **Shape**: Ampere → **VM.Standard.A1.Flex**, **1 OCPU / 6 GB**.
   Always Free covers 4 OCPU + 24 GB total, so this leaves headroom.
   If the console says *"Out of host capacity"*, try the other Availability Domain, or fall
   back to **VM.Standard.E2.1.Micro** (AMD, 1 GB RAM — also Always Free, fine for this app).
4. **Networking**: keep the default VCN; make sure **Assign a public IPv4 address = Yes**.
5. **SSH keys**: upload your public key (or let Oracle generate a pair and **download the
   private key immediately** — it cannot be downloaded again).
6. **Boot volume**: defaults (≤ 50 GB) stay inside the 200 GB Always Free allowance.
7. Confirm the **"Always Free eligible"** badge is shown, then Create.

Note the **public IP** from the instance page.

## Step 2 — Open ports 80 and 443 for the instance

This is the #1 reason HTTPS fails on Oracle — the cloud firewall blocks everything except SSH.

Instance → **Networking** tab → **Primary VNIC** → click the **Subnet** name →
**Security** → **Default Security List** → **Add Ingress Rules**, twice:

| Source CIDR | IP Protocol | Destination Port |
| --- | --- | --- |
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |

If an NSG (Network Security Group) is attached to the VNIC, add the same two rules there too.
Leave the port 22 rule as it is.

## Step 3 — SSH in and run the setup script

From PowerShell or Windows Terminal (built-in OpenSSH). If Windows complains that the
private key is unprotected, lock it down once:

```
icacls C:\path\to\key.key /inheritance:r /grant:r "$env:USERNAME:R"
```

Connect and paste this one block:

```
ssh -i C:\path\to\key.key ubuntu@<PUBLIC_IP>

sudo apt-get update -y && sudo apt-get install -y git && \
sudo git clone https://github.com/bevin3360-design/school-transport.git /opt/school-transport && \
sudo bash /opt/school-transport/deploy/oracle/setup_vm.sh
```

The script ends by printing an HTTPS host. Without a custom domain it uses the free
`<public-ip-with-dashes>.sslip.io` name, which resolves to your VM and gets a real
Let's Encrypt certificate. If you have a domain, point its A record at the VM's IP first,
then run the last command again with it:

```
sudo bash /opt/school-transport/deploy/oracle/setup_vm.sh school.example.co.ke
```

## Step 4 — Add the Neon database URL

The setup script created `/etc/sts/sts.env` with a fresh `SECRET_KEY` already generated;
only the database URL is missing.

```
sudo nano /etc/sts/sts.env
```

Fill the last line — keep the URL on one line, in double quotes:

```
DATABASE_URL="postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"
```

Copy it from the Neon dashboard (or the Render service's `DATABASE_URL` environment value)
— never paste it into chat, git, or a screenshot. Leave the `SUPERADMIN_*` lines commented
out: the production database already has accounts.

Save, then start the service:

```
sudo systemctl start sts
sudo journalctl -u sts -f
```

A healthy boot prints:

```
DATABASE_URL fingerprint: scheme=postgresql length=NNN has_credentials=True
PostgreSQL DATABASE_URL detected; applying ride-hailing schema.
[gunicorn] Listening at: http://0.0.0.0:8000
```

(The production database already has accounts, so no super-admin bootstrap line should
appear — if one does, stop and check which database the URL points at.)

If `length` is suspiciously short or `has_credentials=False`, the URL line was mangled —
fix it in the env file and `sudo systemctl restart sts`.

## Step 5 — Verify before switching over

Both Render and this VM now share the same Neon database, so the content should be identical.

```
curl -I http://127.0.0.1:8000/            # 200 from the app itself
curl -I https://<the host the setup printed>/   # 200 with a valid certificate
```

Then in a browser:

1. `https://<host>/` renders the landing page.
2. `https://<host>/login` loads and you can sign in with the real admin account
   (same credentials as on Render — same database).
3. Open the dashboard and check the Live Tracking map loads (static assets included).

Also confirm the clock is synced, since GPS freshness depends on it:

```
timedatectl     # "System clock synchronized: yes"
```

## Step 6 — Cut over, and keep a way back

1. Everything above passes → in Render: the service menu → **Suspend service**
   (don't delete it yet).
2. Run only one host at a time in steady state; stop Render before leaving the VM serving.
3. Rollback if needed: resume the Render service — nothing on the VM is stateful, and both
   point at the same Neon database.
4. After a week of stability you can delete the Render service and the old Render Postgres
   (the latter was already scheduled to lapse on 2026-12-20).

## Day-to-day operation

| Task | Command (on the VM) |
| --- | --- |
| Deploy the latest `main` | `sudo bash /opt/school-transport/deploy/oracle/deploy.sh` |
| App logs | `sudo journalctl -u sts -n 200` (add `-f` to follow) |
| HTTPS / proxy logs | `sudo journalctl -u caddy -n 100` |
| Restart the app | `sudo systemctl restart sts` |
| Check it listens | `ss -ltnp \| grep 8000` |

There is no auto-deploy from GitHub on the VM — push to `main`, then run `deploy.sh`.
Port 8000 is never opened to the internet (the setup script adds a firewall DROP for it);
Caddy is the only public entry point and renews certificates automatically.

## Troubleshooting

- **Certificate never issues / `https://` times out** — Step 2 was skipped or applies to the
  wrong subnet. Check both the Security List (and NSG, if any) plus
  `sudo iptables -L INPUT -n --line-numbers` shows ACCEPT for 80 and 443.
- **`sts` won't start** — `sudo journalctl -u sts -n 80`. A `RuntimeError` about `SECRET_KEY`
  means the env file is unreadable; a database error usually means the `DATABASE_URL` line
  was split or unquoted.
- **Login succeeds on Render but not on the VM** — different `SECRET_KEY` is fine (sessions
  are host-local), but a wrong `DATABASE_URL` means a different database; compare the boot
  fingerprint line and the school list after sign-in.
- **Landing page shows but images are missing** — check
  `curl -I https://<host>/static/img/landing/admin-dashboard.png`; it should be 200 `image/png`.
- **VM reclaimed / destroyed** — nothing is lost: recreate per this guide, reuse the same
  Neon URL.
- **Capacity error creating A1** — switch Availability Domain or use `VM.Standard.E2.1.Micro`.
