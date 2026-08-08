# Getting your Android app — step by step

No Android Studio, no local setup. GitHub builds it for you, free.
Steps 1–3 take about ten minutes. Step 4 is the one to be careful with.

---

## What you'll end up with

An app called **Innernet**, your icon, your colours, that already does:

- **Scan a QR** from a printed card — config added
- **Save many configs** and switch between them
- **Subscription links** that update themselves when you change something server-side
- **Connect / disconnect**, ping test to pick the fastest, traffic counter
- **Per-app routing** — send only chosen apps through the tunnel
- **Long-press the icon → "Buy or renew"** — opens your storefront
- Tapping a config link on your site opens **your** app, not someone else's

**Not included:** wallet, balance and purchase *screens inside the app*. Those don't
exist in the base app, and building them is real Android development. The long-press
shortcut and your mobile site cover buying and renewals for now.

---

## Step 1 — GitHub account

Go to **github.com**, sign up. Free.

## Step 2 — New repository

Click **New repository**. Name it `innernet-app`. Set it to **Public** — the licence
requires this, and it costs nothing.

## Step 3 — Upload this folder

On the empty repo page click **uploading an existing file**, then drag in everything
from the `apk` folder: `brand.sh`, `fix_shortcuts.py`, `README.md`, `STEPS.md`, and
the `branding` and `.github` folders. Click **Commit changes**.

> If the `.github` folder won't drag (some browsers hide dotted folders), use
> **Add file → Create new file**, type `.github/workflows/build-apk.yml` as the
> name, and paste the file's contents in.

## Step 4 — Make your signing key (do this once, keep it forever)

On any computer with Java installed:

```bash
keytool -genkey -v -keystore innernet.keystore -alias innernet \
        -keyalg RSA -keysize 2048 -validity 10000
```

It asks for a password and a few details — any answers are fine. Then:

```bash
base64 -w0 innernet.keystore > keystore.b64
```

> **Back up `innernet.keystore` and the password permanently** — cloud drive, USB
> stick, password manager. If you lose them you can never publish an update that
> installs over the app; every customer would have to uninstall and lose their
> configs. There is no way to recover it.

## Step 5 — Add three secrets

In your repo: **Settings → Secrets and variables → Actions → New repository secret.**

| Name | Value |
|---|---|
| `KEYSTORE_B64` | the whole contents of `keystore.b64` |
| `KEYSTORE_PASSWORD` | the password you chose |
| `KEY_ALIAS` | `innernet` |

## Step 6 — Build

**Actions** tab → **Build Innernet APK** → **Run workflow**. Five to ten minutes.
A green tick means it worked.

## Step 7 — Download it

Open the finished run and download **innernet-apk** at the bottom, or take it from
the **Releases** page on the right of your repo.

## Step 8 — Put it on your site

Upload the `.apk` into `app/static/downloads/` on your server, then rebuild:

```bash
docker compose build --no-cache && docker compose up -d
```

Your `/app` page finds it automatically and shows the version and size.

## Step 9 — Test it yourself first

Install it on your own phone, scan a real config card, connect. Only then tell
anyone it exists.

---

## Later: updating the app

Re-run the workflow — it always clones the newest v2rayNG, so upstream fixes come
free. Before shipping an update, raise `versionCode` and `versionName` in
`upstream/V2rayNG/app/build.gradle.kts`, and always sign with the **same** keystore.

## If a build fails

Open the failed run and read the red step. The most common causes are a mistyped
secret name, or `brand.sh` stopping on purpose because upstream moved a file — it
is written to fail loudly rather than quietly ship an app still called v2rayNG.
