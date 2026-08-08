# Innernet Android app

This folder builds the branded APK. **It does not contain a copy of v2rayNG** — it
clones upstream at build time and applies the Innernet identity on top. That keeps
the fork tiny and makes picking up upstream fixes a one-line change.

You do not need Android Studio. GitHub builds it for you, free.

---

## What it does to v2rayNG

`brand.sh` locates the app module itself rather than hard-coding paths, so if
upstream reorganises, the script **fails loudly instead of quietly shipping an
unbranded app**. Verified against current upstream:

| | Result |
|---|---|
| Application id | `com.v2ray.ang` → `com.innernetcorp.app` |
| App name | `v2rayNG` → `Innernet`, across all 9 locale files |
| Launcher icons | replaced at every density; adaptive icons removed so the PNG is used |
| Colours | brand teal written to `colors_innernet.xml` |
| Deep link | `innernet://import/…` registered on the launcher activity |

The deep link is the point: your config pages emit `innernet://import/<sub>`, so a
customer taps once and the connection lands in *your* app. If they don't have it
installed, the page falls back to `hiddify://` automatically.

---

## What the build actually needs

v2rayNG is not a plain Gradle project, and a naive `gradlew assembleRelease`
fails. The workflow mirrors upstream's own build:

1. clone **with submodules** (`AndroidLibXrayLite`, `hev-socks5-tunnel`)
2. install **NDK 29.0.14206865** and pin `ndkVersion` in the Gradle file
3. compile the native tunnel library via `compile-hevtun.sh`
4. download **`libv2ray.aar`** from the AndroidLibXrayLite release matching the
   submodule's tag
5. write `local.properties`, run the licence report task, then build

Roughly 15 minutes on a clean run.

> `brand.sh` deliberately changes **`applicationId` only, never `namespace`**.
> Namespace is the code package every Kotlin file declares; rewriting it breaks
> compilation.

## Building it

### 1. Put this folder in its own GitHub repo

```bash
cd apk
git init && git add -A && git commit -m "Innernet Android client"
git remote add origin https://github.com/<you>/innernet-app
git push -u origin main
```

### 2. Make a signing key — once, and keep it forever

```bash
keytool -genkey -v -keystore innernet.keystore -alias innernet \
        -keyalg RSA -keysize 2048 -validity 10000
base64 -w0 innernet.keystore > keystore.b64
```

> **Back up `innernet.keystore` and its password.** Lose them and you can never
> ship an update that installs over the existing app — every user would have to
> uninstall first and lose their configs. There is no recovery.

### 3. Add three repository secrets

Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `KEYSTORE_B64` | contents of `keystore.b64` |
| `KEYSTORE_PASSWORD` | the store password you chose |
| `KEY_ALIAS` | `innernet` |

### 4. Run it

Actions tab → **Build Innernet APK** → *Run workflow*. Takes roughly 5–10 minutes.
The signed APK appears as a build artifact and as a GitHub release.

Without the secrets it still builds, but produces an **unsigned** APK, which will
not install on a phone.

---

## Publishing to your site

Drop the signed file into the panel:

```
app/static/downloads/innernet-1.0.apk
```

`/app` picks it up automatically — version, file size, correct MIME type, install
instructions. Nothing else to change.

---

## Updating

Upstream fixes come free: re-run the workflow and it clones the latest v2rayNG.
Before shipping an update, raise `versionCode` and `versionName` in
`upstream/V2rayNG/app/build.gradle.kts` — or pass them in `brand.sh` — and sign
with the **same** keystore, or phones will refuse to install over the old app.

---

## Licence

v2rayNG is GPL-3.0. Distributing a modified build means publishing your modified
source — which this repo is. Keep it public and link to it from the app's About
screen. That satisfies the licence and costs you nothing.
