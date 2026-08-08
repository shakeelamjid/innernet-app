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

## Why the build takes ~15 minutes

v2rayNG is not a plain Gradle project. The workflow has to fetch two git
submodules, install a specific NDK, compile a native tunnel library from C
source, and download the matching Xray core `.aar` before Gradle can even start.
That is all automatic — it just isn't fast. Later runs are quicker.

## If a build fails

Open the failed run and click the red step. Common causes:

- **A mistyped secret name.** They must be exactly `KEYSTORE_B64`,
  `KEYSTORE_PASSWORD`, `KEY_ALIAS`.
- **`brand.sh` stopped on purpose.** It fails loudly when upstream moves a file,
  rather than quietly shipping an app still called v2rayNG. The message says
  which step it could not complete.
- **Native build errors** in "Build the native tunnel library" usually mean
  upstream changed the NDK version. Compare `NDK_VERSION` at the top of the
  workflow with the one in upstream's own `.github/workflows/build.yml`.

Paste the red step's name and the last few lines of its log and it can be
diagnosed from that.

---

## Update: the app now shows *your* screens

`add_webview.py` gives the fork an Innernet face — a WebView on
`innernetcorp.com/m` plus a native bridge. After this, the interface lives on
your server: change a screen, redeploy the panel, and every installed app shows
it. No new APK, no reinstall.

What the bridge does:

| The page calls | The app does |
|---|---|
| `setConnected(true/false)` | starts or stops the tunnel |
| `scan()` | opens the QR scanner, imports what it reads |
| `paste()` | reads the clipboard, imports a config link |
| `biometric(reason)` | fingerprint prompt for the operator panel |
| `advanced()` | opens the original v2rayNG screens |

It **fails the build** if upstream renames any of the functions it hooks into,
rather than shipping an app whose buttons quietly do nothing.

### To update the app repo

1. Replace `brand.sh` with the new version
2. Add `add_webview.py` as a new file
3. Replace `.github/workflows/build-apk.yml`
4. Actions → Build Innernet APK → Run workflow
5. Install and check: the app opens the Innernet connect screen, not a config list
