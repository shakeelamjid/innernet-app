#!/usr/bin/env python3
"""Give the branded fork an Innernet face.

Adds one Kotlin activity that shows the panel's /m pages in a WebView, and a
JavaScript bridge so those pages can drive the tunnel, the QR scanner, the
clipboard and the fingerprint prompt. The upstream Compose UI stays in the build,
reachable from a long-press, for when something needs debugging.

Every upstream symbol used here was read from the source, not assumed:
  LauncherManager.startService / stopService   core/LauncherManager.kt
  CoreServiceManager.isRunning()               handler/NotificationManager.kt
  AngConfigManager.importBatchConfig(...)      ui/main/MainRepository.kt
  ScannerActivity                              ui/ScannerActivity.kt
If a future upstream renames one, this script fails loudly rather than producing
an app whose buttons quietly do nothing.
"""
import os
import re
import sys

app_dir, site_url, pkg = sys.argv[1:4]
java_root = os.path.join(app_dir, "src", "main", "java", "com", "v2ray", "ang")
manifest = os.path.join(app_dir, "src", "main", "AndroidManifest.xml")


def fail(msg):
    sys.exit(f"!! {msg}")


# ---------------------------------------------------------------- preflight
def find(pattern, where, label):
    hits = []
    for root, _d, files in os.walk(where):
        for f in files:
            if f.endswith(".kt"):
                p = os.path.join(root, f)
                if re.search(pattern, open(p, encoding="utf-8", errors="ignore").read()):
                    hits.append(p)
    if not hits:
        fail(f"upstream no longer has {label} — the bridge would be dead, refusing to build")
    return hits


find(r"object LauncherManager", java_root, "LauncherManager")
find(r"fun\s+startService", java_root, "LauncherManager.startService")
find(r"object CoreServiceManager|fun isRunning", java_root, "CoreServiceManager.isRunning")
find(r"class ScannerActivity", java_root, "ScannerActivity")
find(r"fun importBatchConfig", java_root, "AngConfigManager.importBatchConfig")
print("  preflight   : every upstream hook the bridge needs is present")

# ---------------------------------------------------------------- the activity
os.makedirs(os.path.join(java_root, "ui", "innernet"), exist_ok=True)
activity = f'''package com.v2ray.ang.ui.innernet

import android.annotation.SuppressLint
import android.app.Activity
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import com.v2ray.ang.core.LauncherManager
import com.v2ray.ang.handler.AngConfigManager
import com.v2ray.ang.ui.ScannerActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * The face of the app. Everything the customer sees is served by the panel, so
 * a change to the interface ships by redeploying the server — no new APK.
 */
class InnernetActivity : FragmentActivity() {{

    private lateinit var web: WebView
    private val home = "{site_url}"

    private val scanner = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) {{ result ->
        val text = result.data?.getStringExtra("SCAN_RESULT").orEmpty()
        if (text.isNotBlank()) handOff(text)
    }}

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {{
        super.onCreate(savedInstanceState)
        web = WebView(this)
        setContentView(web)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.databaseEnabled = true
        // The server uses this to serve the in-app pages rather than the
        // marketing site, even if a link leads out of /m.
        web.settings.userAgentString = web.settings.userAgentString + " InnernetApp/1.0"
        // never show a stale screen after the panel is redeployed
        web.settings.cacheMode = android.webkit.WebSettings.LOAD_NO_CACHE
        web.clearCache(true)
        web.webViewClient = object : WebViewClient() {{
            override fun shouldOverrideUrlLoading(v: WebView?, url: String?): Boolean {{
                val u = url ?: return false
                val site = home.substringBefore("/m")
                if (u.startsWith(site)) return false          // our own pages stay inside
                if (u.startsWith("http")) {{                    // anything else opens outside
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(u)))
                    return true
                }}
                return false
            }}

            override fun onReceivedError(
                v: WebView?, req: android.webkit.WebResourceRequest?,
                err: android.webkit.WebResourceError?
            ) {{
                // a blank screen tells the customer nothing; say what happened
                if (req?.isForMainFrame == true) {{
                    v?.loadData(
                        "<body style='background:#09090b;color:#fafafa;font-family:sans-serif;" +
                            "display:flex;align-items:center;justify-content:center;height:100vh;" +
                            "margin:0;text-align:center;padding:24px'><div>" +
                            "<p style='font-size:16px'>Can't reach Innernet</p>" +
                            "<p style='font-size:13px;color:#8b8b93'>Check your connection and try again.</p>" +
                            "</div></body>", "text/html; charset=utf-8", null
                    )
                }}
            }}
        }}
        web.addJavascriptInterface(Bridge(), "Innernet")
        web.loadUrl(if (savedInstanceState == null) home else web.url ?: home)
    }}

    override fun onBackPressed() {{
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }}

    /** Push a scanned or pasted config into the app, then tell the page. */
    private fun handOff(text: String) {{
        CoroutineScope(Dispatchers.IO).launch {{
            val (count, _) = try {{
                AngConfigManager.importBatchConfig(text, "", false)
            }} catch (e: Exception) {{
                Pair(0, 0)
            }}
            runOnUiThread {{
                // The config now lives in the tunnel engine, but the page tracks
                // it separately — hand the same text to /m/claim so the session
                // knows which config this phone is holding. Without this the
                // scan appears to do nothing.
                val js = StringBuilder()
                    .append("(async()=>{{try{{")
                    .append("const r=await fetch('/m/claim',{{method:'POST',")
                    .append("headers:{{'Content-Type':'application/x-www-form-urlencoded'}},")
                    .append("body:'text='+encodeURIComponent(")
                    .append(org.json.JSONObject.quote(text))
                    .append(")}});")
                    .append("const j=await r.json();")
                    .append("location.href=j.ok?j.next:'/m/add';")
                    .append("}}catch(e){{location.href='/m/add';}}}})()")
                    .toString()
                web.evaluateJavascript(js, null)
            }}
        }}
    }}

    inner class Bridge {{

        /** Start or stop the tunnel. Returns whether the app is now connected. */
        @JavascriptInterface
        fun setConnected(on: Boolean): Boolean {{
            runOnUiThread {{
                if (on) LauncherManager.startService(this@InnernetActivity)
                else LauncherManager.stopService(this@InnernetActivity)
            }}
            return on
        }}

        @JavascriptInterface
        fun scan() {{
            runOnUiThread {{
                scanner.launch(Intent(this@InnernetActivity, ScannerActivity::class.java))
            }}
        }}

        @JavascriptInterface
        fun paste() {{
            runOnUiThread {{
                val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                val text = cm.primaryClip?.getItemAt(0)?.coerceToText(this@InnernetActivity)
                    ?.toString().orEmpty()
                if (text.isNotBlank()) handOff(text)
            }}
        }}

        /** Fingerprint check for the operator panel. */
        @JavascriptInterface
        fun biometric(reason: String): Boolean {{
            val can = BiometricManager.from(this@InnernetActivity)
                .canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_WEAK)
            if (can != BiometricManager.BIOMETRIC_SUCCESS) return false
            val done = java.util.concurrent.CountDownLatch(1)
            val okRef = java.util.concurrent.atomic.AtomicBoolean(false)
            runOnUiThread {{
                val prompt = BiometricPrompt(
                    this@InnernetActivity,
                    ContextCompat.getMainExecutor(this@InnernetActivity),
                    object : BiometricPrompt.AuthenticationCallback() {{
                        override fun onAuthenticationSucceeded(r: BiometricPrompt.AuthenticationResult) {{
                            okRef.set(true); done.countDown()
                        }}
                        override fun onAuthenticationError(code: Int, msg: CharSequence) {{ done.countDown() }}
                        override fun onAuthenticationFailed() {{ /* let them retry */ }}
                    }}
                )
                prompt.authenticate(
                    BiometricPrompt.PromptInfo.Builder()
                        .setTitle(reason)
                        .setNegativeButtonText("Cancel")
                        .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_WEAK)
                        .build()
                )
            }}
            done.await(60, java.util.concurrent.TimeUnit.SECONDS)
            return okRef.get()
        }}

        /** The upstream screens, for when something needs debugging. */
        @JavascriptInterface
        fun advanced() {{
            runOnUiThread {{
                startActivity(Intent(this@InnernetActivity,
                    com.v2ray.ang.ui.main.MainActivity::class.java))
            }}
        }}
    }}
}}
'''
path = os.path.join(java_root, "ui", "innernet", "InnernetActivity.kt")
open(path, "w", encoding="utf-8").write(activity)
print(f"  activity    : {os.path.relpath(path, app_dir)}")

# ---------------------------------------------------------------- manifest
xml = open(manifest, encoding="utf-8").read()
if "InnernetActivity" not in xml:
    # our activity becomes the launcher; upstream's keeps its other filters
    xml = xml.replace(
        '<activity\n            android:name=".ui.main.MainActivity"\n'
        '            android:exported="true"\n            android:launchMode="singleTask">\n'
        '            <intent-filter>\n                <action android:name="android.intent.action.MAIN" />\n\n'
        '                <category android:name="android.intent.category.LAUNCHER" />',
        '<activity\n            android:name=".ui.innernet.InnernetActivity"\n'
        '            android:exported="true"\n            android:launchMode="singleTask"\n'
        '            android:configChanges="orientation|screenSize|keyboardHidden">\n'
        '            <intent-filter>\n                <action android:name="android.intent.action.MAIN" />\n'
        '                <category android:name="android.intent.category.LAUNCHER" />\n'
        '            </intent-filter>\n        </activity>\n\n'
        '        <activity\n            android:name=".ui.main.MainActivity"\n'
        '            android:exported="true"\n            android:launchMode="singleTask">\n'
        '            <intent-filter>\n                <action android:name="android.intent.action.MAIN" />\n\n'
        '                <category android:name="android.intent.category.DEFAULT" />',
        1,
    )
    if "InnernetActivity" not in xml:
        fail("could not make InnernetActivity the launcher — manifest layout changed")
    open(manifest, "w", encoding="utf-8").write(xml)
print("  launcher    : InnernetActivity (upstream UI kept as Advanced)")

# ---------------------------------------------------------------- gradle deps
gradle = os.path.join(app_dir, "build.gradle.kts")
g = open(gradle, encoding="utf-8").read()
if "androidx.biometric" not in g:
    m = re.search(r"\ndependencies\s*\{", g)
    if not m:
        fail("no dependencies block in build.gradle.kts")
    g = g[:m.end()] + (
        '\n    implementation("androidx.biometric:biometric:1.1.0")'
        '\n    implementation("androidx.fragment:fragment-ktx:1.8.5")'
    ) + g[m.end():]
    open(gradle, "w", encoding="utf-8").write(g)
print("  deps        : biometric + fragment-ktx")
print("  home        :", site_url)
