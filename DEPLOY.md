# Deploying to a permanent link (PythonAnywhere, free)

The goal: one HTTPS URL you hand to participants that keeps working when your laptop is shut,
and **does not change when you redeploy**.

Why PythonAnywhere and not Render/Fly: Render's free tier cannot attach a disk, so `study.db`
is destroyed on every redeploy, restart or idle spin-down, and Fly.io no longer has a free tier.
PythonAnywhere free gives a real persistent filesystem, so SQLite works unchanged.

**What you get:** `https://<username>.pythonanywhere.com` — permanent, always on, no cold start.

---

## Before you start
Push the latest code, because the server deploys by cloning your repo:
```sh
git push origin main
```
Generate the two secrets, and keep them somewhere safe — you will paste them in step 5:
```sh
python -c "import secrets; print('SECRET_KEY   =', secrets.token_urlsafe(32))"
python -c "import secrets; print('EXPORT_TOKEN =', secrets.token_urlsafe(16))"
```

## 1. Sign up
<https://www.pythonanywhere.com/registration/register/beginner/> — the "Beginner" account is
free and needs no card. Your username becomes your URL, so pick one you are happy to send to
participants. Note it down; every `<username>` below is that name.

## 2. Get the code onto the server
**Consoles** tab → **Bash**. Then:
```sh
git clone https://github.com/divyas39/HAI-task.git
mkvirtualenv study --python=/usr/bin/python3.10
pip install flask google-genai pandas python-dotenv
```
Install these unpinned: `requirements.txt` pins pandas 3, which needs Python 3.11+.
`mkvirtualenv` leaves the new virtualenv active and named `study`. If the repo is private, use a
GitHub personal access token as the password when prompted.

**Do not use Python 3.11 here** — that build is broken on PythonAnywhere and `pip` dies with
`ModuleNotFoundError: No module named '_posixsubprocess'`. 3.10 is what PythonAnywhere's own
docs use. To see what else is available: `ls /usr/bin/python3.* /usr/local/bin/python3.* | grep -v config`.
Whichever you pick, **choose the same version for the web app in step 3.**

`gunicorn` in `requirements.txt` is for other hosts and not needed here.

## 3. Create the web app
**Web** tab → **Add a new web app** → **Manual configuration** (*not* the "Flask" option — that
scaffolds a new app over yours) → same Python version as above.

## 4. Point it at your code
On the Web tab, set:

| field | value |
|---|---|
| Source code | `/home/<username>/HAI-task` |
| Working directory | `/home/<username>/HAI-task` |
| Virtualenv | `/home/<username>/.virtualenvs/study` (leave blank if you skipped it) |

## 5. The WSGI file
On the Web tab, click the **WSGI configuration file** link. Delete everything in it and paste
the contents of [`wsgi_template.py`](wsgi_template.py) from this repo, replacing every
`<placeholder>` with your username, the two generated secrets and your Gemini API key. Save.

This file lives at `/var/www/...`, outside your repo — which is why the secrets in it are never
committed. Note that `DB_PATH` points at `/home/<username>/study.db`, **outside** the checkout,
so a `git pull` can never disturb collected data.

## 6. Reload
Green **Reload** button on the Web tab. Open `https://<username>.pythonanywhere.com/`.

---

## Redeploying later
The URL never changes. In a Bash console:
```sh
cd ~/HAI-task && git pull
```
then hit **Reload**. Existing responses are untouched — they live outside the checkout.

## Two things that will lose you data if ignored

**Renew monthly.** Since January 2026 a free web app expires after **1 month**. On the Web tab
there is a "Run until <date>" button — click it any time before the date shown and it extends.
Put a monthly reminder in your calendar; if it expires, the link 404s for participants.

**Back up the data.** PythonAnywhere's disk is your only copy. Pull it down regularly:
```sh
curl "https://<username>.pythonanywhere.com/export?token=<EXPORT_TOKEN>" -o responses_backup.csv
```

## Check that live AI hints work
The free tier only reaches allow-listed sites; `.googleapis.com` is on the list. In a Bash console:
```sh
workon study && cd ~/HAI-task
GEMINI_API_KEY=<your key> python run_model.py "The tacos were great but the wait was long."
```
It should print a verdict. If it fails, the study still runs on the stored A2 outputs
(`ai_source = cache` in the export), and `./run_study.sh` from a laptop gives live hints.

## Checks after deploying
1. Open the URL **on your phone**, not just the laptop, and complete both versions.
   Links for participants: `https://<username>.pythonanywhere.com/?c=baseline` (AI-unassisted)
   and `https://<username>.pythonanywhere.com/?c=ai` (AI-assisted). Both open the instructions first.
2. `curl "https://<username>.pythonanywhere.com/export?token=<token>"` — your answers are there,
   and in AI-assisted rows most have `ai_source` = `live`.
3. Hit **Reload**, run check 2 again. The row must survive. This is the whole reason for
   choosing this host.
4. `curl -o /dev/null -w "%{http_code}\n" "https://<username>.pythonanywhere.com/export"` — must
   print `403`. Without the token nobody can read participant data.

## Troubleshooting
- **`pip` fails with `No module named '_posixsubprocess'`** → the virtualenv was built from a
  broken interpreter (3.11). `rmvirtualenv study`, then recreate it with `--python=/usr/bin/python3.10`.
- **500 error** → Web tab → **Error log**. A `ModuleNotFoundError: flask` means the virtualenv
  path in step 4 is wrong; a `FileNotFoundError` means the source-code path is.
- **Site shows "Hello from Flask!"** → you picked the Flask option in step 3 instead of Manual
  configuration; delete the web app and redo it.
- **Changes not showing** → you did not press Reload.
