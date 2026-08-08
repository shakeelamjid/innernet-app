#!/usr/bin/env bash
# Turn a fresh v2rayNG checkout into the Innernet client.
#
# Finds the app module rather than assuming paths, so an upstream reshuffle
# doesn't silently produce an unbranded build — it fails loudly instead.
set -euo pipefail

APP_NAME="${APP_NAME:-Innernet}"
APP_ID="${APP_ID:-com.innernetcorp.app}"
SCHEME="${SCHEME:-innernet}"
SITE_URL="${SITE_URL:-https://innernetcorp.com/buy}"
BUY_LABEL="${BUY_LABEL:-Buy or renew}"
ACCENT="${ACCENT:-#17E6C9}"
SRC="${SRC:-upstream}"
BRANDING="$(cd "$(dirname "$0")" && pwd)/branding"

say()  { printf '  %s\n' "$*"; }
fail() { printf '\n!! %s\n' "$*" >&2; exit 1; }

[ -d "$SRC" ] || fail "No '$SRC' checkout. Run: git clone --depth 1 https://github.com/2dust/v2rayNG $SRC"

# ---------------------------------------------------------------- app module
# The Android project sits under V2rayNG/app in current upstream, but locate it
# by looking for the module that declares an applicationId.
GRADLE="$(grep -rl --include='build.gradle*' 'applicationId' "$SRC" | head -1 || true)"
[ -n "$GRADLE" ] || fail "Could not find a build.gradle declaring applicationId under $SRC"
APP_DIR="$(dirname "$GRADLE")"
RES_DIR="$APP_DIR/src/main/res"
[ -d "$RES_DIR" ] || fail "No res/ directory at $RES_DIR"
# Build flavours (fdroid, dev, pre_release...) keep their own res/ and override
# app_name. Branding only src/main leaves those variants named v2rayNG.
SRC_DIR="$APP_DIR/src"
say "app module : $APP_DIR"
say "source sets: $(ls "$SRC_DIR" | tr '\n' ' ')"

# ---------------------------------------------------------------- identity
OLD_ID="$(grep -oE 'applicationId[[:space:]]*=?[[:space:]]*"[^"]+"' "$GRADLE" | head -1 | grep -oE '"[^"]+"' | tr -d '"')"
[ -n "$OLD_ID" ] || fail "Could not read the existing applicationId"
# Only the applicationId — NOT `namespace`. Namespace is the code package that
# every Kotlin file declares; changing it breaks the build.
sed -i -E "s|(applicationId[[:space:]]*=?[[:space:]]*)\"$OLD_ID\"|\1\"$APP_ID\"|" "$GRADLE"
grep -q "applicationId.*\"$APP_ID\"" "$GRADLE" || fail "applicationId was not rewritten"
grep -q "namespace.*\"$OLD_ID\"" "$GRADLE" || say "note       : upstream namespace differs from the old id (fine)"
say "app id     : $OLD_ID -> $APP_ID  (namespace left untouched)"

# app_name across every locale that defines it
CHANGED=0
# every source set, not just main — and both <string> and <item type="string">
while IFS= read -r f; do
    sed -i -E "s|(<string name=\"app_name\"[^>]*>)[^<]*(</string>)|\1${APP_NAME}\2|" "$f"
    sed -i -E "s|(<item name=\"app_name\"[^>]*>)[^<]*(</item>)|\1${APP_NAME}\2|" "$f"
    CHANGED=$((CHANGED+1))
done < <(grep -rlE '(<string|<item) name="app_name"' "$SRC_DIR" || true)
[ "$CHANGED" -gt 0 ] || fail "Nothing declared app_name — nothing was renamed"
say "app name   : $APP_NAME  (in $CHANGED file(s) across all source sets)"
# prove no variant kept the old name (check the app_name line only — other
# strings legitimately mention v2rayNG in help text)
LEFT="$(grep -rhE '(<string|<item) name="app_name"' "$SRC_DIR" | grep -v ">${APP_NAME}<" || true)"
[ -z "$LEFT" ] || fail "an app_name was not renamed:
$LEFT"
say "verified   : every app_name now reads $APP_NAME"

# ---------------------------------------------------------------- icons
ICONS=0
for d in "$RES_DIR"/mipmap-*; do
    [ -d "$d" ] || continue
    dens="$(basename "$d" | sed 's/^mipmap-//')"
    src="$BRANDING/ic_launcher_${dens}.png"
    [ -f "$src" ] || continue
    for target in ic_launcher ic_launcher_round; do
        [ -f "$d/$target.png" ] && cp "$src" "$d/$target.png" && ICONS=$((ICONS+1))
    done
done
# adaptive icons would override our PNG, so drop them
rm -rf "$RES_DIR"/mipmap-anydpi-v26 2>/dev/null || true
say "icons      : $ICONS file(s) replaced, adaptive icons removed"

python3 "$(dirname "$0")/fix_shortcuts.py" "$RES_DIR" "$SRC_DIR" "$OLD_ID" "$APP_ID" "$SITE_URL" "$BUY_LABEL"

# ------------------------------------------------------------ size shrinking
# Upstream ships with minification disabled. Turning it on strips unused Kotlin
# and Compose code — typically a few MB. It is OPT-IN because upstream does not
# test with it: R8 can break reflection at runtime, and the failure shows up when
# a user tries to connect, not at build time. Test any MINIFY=1 build properly.
if [ "${MINIFY:-0}" = "1" ]; then
    if grep -q 'isMinifyEnabled = false' "$GRADLE"; then
        sed -i 's/isMinifyEnabled = false/isMinifyEnabled = true\n            isShrinkResources = true/' "$GRADLE"
        say "shrinking  : R8 enabled (test this build carefully)"
    fi
else
    say "shrinking  : off (set MINIFY=1 to try it)"
fi

# ---------------------------------------------------------------- colours
mkdir -p "$RES_DIR/values"
cat > "$RES_DIR/values/colors_innernet.xml" <<XML
<?xml version="1.0" encoding="utf-8"?>
<!-- Innernet brand colours. Loaded after the upstream palette. -->
<resources>
    <color name="colorPrimary">$ACCENT</color>
    <color name="colorPrimaryDark">#0C9C88</color>
    <color name="colorAccent">$ACCENT</color>
    <color name="colorSecondary">$ACCENT</color>
</resources>
XML
say "colours    : $ACCENT"

# ---------------------------------------------------------------- deep link
# So a tap on innernet://import/<sub> from our site opens *this* app.
MANIFEST="$APP_DIR/src/main/AndroidManifest.xml"
[ -f "$MANIFEST" ] || fail "No AndroidManifest.xml at $MANIFEST"
if grep -q "android:scheme=\"$SCHEME\"" "$MANIFEST"; then
    say "deep link  : $SCHEME:// already present"
else
    python3 - "$MANIFEST" "$SCHEME" <<'PY'
import re, sys
path, scheme = sys.argv[1], sys.argv[2]
xml = open(path, encoding='utf-8').read()
# attach to the activity that already handles a VIEW intent, else the launcher
m = re.search(r'<activity\b[^>]*>(?:(?!</activity>).)*?android\.intent\.action\.MAIN.*?</activity>', xml, re.S)
if not m:
    sys.exit("could not locate the launcher activity")
block = m.group(0)
filt = ('\n            <intent-filter>\n'
        '                <action android:name="android.intent.action.VIEW" />\n'
        '                <category android:name="android.intent.category.DEFAULT" />\n'
        '                <category android:name="android.intent.category.BROWSABLE" />\n'
        f'                <data android:scheme="{scheme}" />\n'
        '            </intent-filter>\n        ')
patched = block[:block.rfind('</activity>')] + filt + '</activity>'
open(path, 'w', encoding='utf-8').write(xml.replace(block, patched))
PY
    grep -q "android:scheme=\"$SCHEME\"" "$MANIFEST" || fail "deep link was not written"
    say "deep link  : ${SCHEME}://import/... registered"
fi

# ------------------------------------------------------- the Innernet face
# Without this the app is a rebranded v2rayNG showing its own engineer-facing
# screens. This points it at the panel's /m pages and wires the native bridge.
python3 "$(dirname "$0")/add_webview.py" "$APP_DIR" "${WEB_URL:-${SITE_URL%/buy}/m}" "$APP_ID"

printf '\nBranding applied. Build with:\n  cd %s && ./gradlew assembleRelease\n' "$(dirname "$APP_DIR")"
