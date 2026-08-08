#!/usr/bin/env python3
"""Repoint stale package references and add the storefront shortcut.

Run after the id/name/icon changes. Kept as a separate file because it edits XML,
which is safer done with a parser-ish approach than with sed.
"""
import os
import sys

res_dir, old_id, new_id, site_url, buy_label = sys.argv[1:6]

# --- 1. resources that hard-code the old package (shortcuts, widgets) ---------
repointed = 0
for root, _dirs, files in os.walk(res_dir):
    for name in files:
        if not name.endswith(".xml"):
            continue
        path = os.path.join(root, name)
        try:
            text = open(path, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        if old_id in text:
            open(path, "w", encoding="utf-8").write(text.replace(old_id, new_id))
            repointed += 1
print(f"  pkg refs   : {repointed} resource file(s) repointed to {new_id}")

# --- 2. a long-press shortcut that opens the storefront -----------------------
shortcuts = os.path.join(res_dir, "xml", "shortcuts.xml")
if not site_url:
    print("  buy link   : skipped (no SITE_URL)")
    sys.exit(0)
if not os.path.isfile(shortcuts):
    print("  buy link   : skipped (no shortcuts.xml upstream)")
    sys.exit(0)

xml = open(shortcuts, encoding="utf-8").read()
if "innernet_buy" in xml:
    print("  buy link   : already present")
    sys.exit(0)

os.makedirs(os.path.join(res_dir, "values"), exist_ok=True)
with open(os.path.join(res_dir, "values", "strings_innernet.xml"), "w", encoding="utf-8") as fh:
    fh.write(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
        f'    <string name="innernet_buy" translatable="false">{buy_label}</string>\n'
        "</resources>\n"
    )

entry = f'''    <shortcut
        android:enabled="true"
        android:icon="@drawable/ic_qu_scan_24dp"
        android:shortcutDisabledMessage="@string/innernet_buy"
        android:shortcutId="innernet_buy"
        android:shortcutLongLabel="@string/innernet_buy"
        android:shortcutShortLabel="@string/innernet_buy">
        <intent
            android:action="android.intent.action.VIEW"
            android:data="{site_url}" />
    </shortcut>
</shortcuts>'''

if "</shortcuts>" not in xml:
    sys.exit("!! shortcuts.xml has no closing tag — not patching")
open(shortcuts, "w", encoding="utf-8").write(xml.replace("</shortcuts>", entry))
print(f"  buy link   : long-press icon -> {site_url}")
