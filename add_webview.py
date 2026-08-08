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
find(r"object CoreServiceManager", java_root, "CoreServiceManager")
find(r"fun isRunning", java_root, "CoreServiceManager.isRunning")
find(r"fun getSelectServer", java_root, "MmkvManager.getSelectServer")
find(r"fun setSelectServer", java_root, "MmkvManager.setSelectServer")
find(r"fun decodeServerList", java_root, "MmkvManager.decodeServerList")
find(r"fun removeServer\b", java_root, "MmkvManager.removeServer")
find(r"fun stopService", java_root, "LauncherManager.stopService")
find(r"fun decodeServerConfig", java_root, "MmkvManager.decodeServerConfig")
find(r"fun queryAllOutboundTrafficStats", java_root, "CoreServiceManager.queryAllOutboundTrafficStats")
find(r"MSG_STATE_START_SUCCESS", java_root, "AppConfig.MSG_STATE_START_SUCCESS")
find(r"MSG_STATE_NOT_RUNNING", java_root, "AppConfig.MSG_STATE_NOT_RUNNING")
find(r"BROADCAST_ACTION_ACTIVITY", java_root, "AppConfig.BROADCAST_ACTION_ACTIVITY")
find(r"fun sendMsg2Service", java_root, "MessageHelper.sendMsg2Service")
find(r"fun initAssets", java_root, "SettingsManager.initAssets")
find(r"fun removeServer", java_root, "MmkvManager.removeServer")
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
import com.v2ray.ang.handler.MmkvManager
import com.v2ray.ang.core.CoreServiceManager
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

    /** What the service last told us. The core lives in another process, so this
     *  broadcast — not a local flag — is the only honest answer. */
    @Volatile private var serviceRunning = false
    private var stateReceiver: android.content.BroadcastReceiver? = null

    private val notifyPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) {{ /* proceed either way; the service degrades rather than refuses */ }}

    private val vpnConsent = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) {{ result ->
        // Android asks the customer to allow a VPN. Without this the service
        // silently never starts, and the page happily shows a green light.
        val granted = result.resultCode == Activity.RESULT_OK
        if (!granted) {{
            pushState(false)
            return@registerForActivityResult
        }}
        LauncherManager.startService(this)
        // Saying "connected" the instant the service is asked to start is a
        // guess. Watch until it really is, then say so.
        CoroutineScope(Dispatchers.IO).launch {{
            repeat(50) {{
                if (serviceRunning) return@launch      // the broadcast beat us to it
                kotlinx.coroutines.delay(500)
            }}
            if (!serviceRunning) runOnUiThread {{ pushState(false) }}
        }}
    }}

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
        web.webChromeClient = object : android.webkit.WebChromeClient() {{
            override fun onPermissionRequest(req: android.webkit.PermissionRequest?) {{
                // the page's own QR scanner needs the camera
                runOnUiThread {{ req?.grant(req.resources) }}
            }}
        }}
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

        // The core needs its geo data files present before it can start. Upstream
        // does this from MainActivity, which is no longer the launcher, so nothing
        // was doing it — the core initialised and stopped without a word.
        CoroutineScope(Dispatchers.IO).launch {{
            try {{
                com.v2ray.ang.handler.SettingsManager.initAssets(
                    applicationContext, applicationContext.assets)
            }} catch (e: Exception) {{
                android.util.Log.e("Innernet", "initAssets failed", e)
            }}
        }}

        stateReceiver = object : android.content.BroadcastReceiver() {{
            override fun onReceive(ctx: Context?, intent: Intent?) {{
                when (intent?.getIntExtra("key", 0)) {{
                    com.v2ray.ang.AppConfig.MSG_STATE_RUNNING,
                    com.v2ray.ang.AppConfig.MSG_STATE_START_SUCCESS -> {{
                        serviceRunning = true; pushState(true)
                    }}
                    com.v2ray.ang.AppConfig.MSG_STATE_NOT_RUNNING,
                    com.v2ray.ang.AppConfig.MSG_STATE_START_FAILURE,
                    com.v2ray.ang.AppConfig.MSG_STATE_STOP_SUCCESS -> {{
                        serviceRunning = false; pushState(false)
                    }}
                }}
            }}
        }}
        ContextCompat.registerReceiver(
            this, stateReceiver,
            android.content.IntentFilter(com.v2ray.ang.AppConfig.BROADCAST_ACTION_ACTIVITY),
            ContextCompat.RECEIVER_EXPORTED
        )

        // Ask before the customer taps Connect, so the tunnel is not blocked at
        // the moment it matters.
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, "android.permission.POST_NOTIFICATIONS")
                != android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {{
            notifyPermission.launch("android.permission.POST_NOTIFICATIONS")
        }}
        // A cache-buster on the first load guarantees a fresh page after a
        // redeploy, even if something between us and the server caches.
        val fresh = home + (if (home.contains("?")) "&" else "?") + "b=" + System.currentTimeMillis()
        web.loadUrl(if (savedInstanceState == null) fresh else web.url ?: fresh)
    }}

    /** Push the service's actual state into the page. */
    private fun pushState(running: Boolean) {{
        web.evaluateJavascript(
            "window.dispatchEvent(new CustomEvent('innernet:state'," +
                "{{detail:{{connected:$running}}}}))", null
        )
    }}

    override fun onResume() {{
        super.onResume()
        // ask the service where it stands; it answers on the broadcast above
        com.v2ray.ang.helper.MessageHelper.sendMsg2Service(
            this, com.v2ray.ang.AppConfig.MSG_REGISTER_CLIENT, "")
        if (::web.isInitialized) pushState(serviceRunning)
    }}

    override fun onDestroy() {{
        stateReceiver?.let {{ try {{ unregisterReceiver(it) }} catch (e: Exception) {{}} }}
        super.onDestroy()
    }}

    override fun onBackPressed() {{
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }}

    /** Push a scanned or pasted config into the app, then tell the page. */
    private fun handOff(text: String) {{
        CoroutineScope(Dispatchers.IO).launch {{
            val beforeImport = try {{ MmkvManager.decodeServerList("").toSet() }}
                               catch (e: Exception) {{ emptySet<String>() }}
            val (count, _) = try {{
                AngConfigManager.importBatchConfig(text, "", false)
            }} catch (e: Exception) {{
                Pair(0, 0)
            }}
            // Importing does not select. Without this the tunnel has nothing to
            // start and the connect button fails for no visible reason.
            if (count > 0) {{
                try {{
                    val after = MmkvManager.decodeServerList("")
                    val added = after.firstOrNull {{ it !in beforeImport }} ?: after.lastOrNull()
                    added?.let {{ MmkvManager.setSelectServer(it) }}
                }} catch (e: Exception) {{ /* selection is best effort */ }}
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

        /** Bridge generation. Bump on every change to the methods below, so the
         *  page can tell whether the installed app is current. Without this,
         *  testing a server fix against an old APK looks like the fix failed. */
        @JavascriptInterface
        fun version(): Int = 7

        /** Start or stop the tunnel.
         *
         *  Returns false when it could not be started — no config chosen, or the
         *  customer has not yet allowed a VPN. The page must never claim to be
         *  connected on the strength of a tap alone.
         */
        @JavascriptInterface
        fun setConnected(on: Boolean): Boolean {{
            if (!on) {{
                runOnUiThread {{
                    LauncherManager.stopService(this@InnernetActivity)
                    pushState(false)
                }}
                return false
            }}
            if (MmkvManager.getSelectServer().isNullOrEmpty()) return false
            runOnUiThread {{
                val consent = android.net.VpnService.prepare(this@InnernetActivity)
                if (consent == null) {{
                    LauncherManager.startService(this@InnernetActivity)
                    CoroutineScope(Dispatchers.IO).launch {{
                        repeat(50) {{
                            if (serviceRunning) return@launch
                            kotlinx.coroutines.delay(500)
                        }}
                        if (!serviceRunning) runOnUiThread {{ pushState(false) }}
                    }}
                }} else {{
                    vpnConsent.launch(consent)     // result handled above
                }}
            }}
            return true
        }}

        /** The truth, as reported by the process that actually runs the tunnel. */
        @JavascriptInterface
        fun isConnected(): Boolean = serviceRunning

        /** Is there anything to connect with? */
        @JavascriptInterface
        fun hasConfig(): Boolean = !MmkvManager.getSelectServer().isNullOrEmpty()

        /** Put a config into the tunnel.
         *
         *  A config typed or pasted into the page reaches the server but not the
         *  engine, so the page shows a plan while there is nothing to connect
         *  with. This closes that gap.
         */
        @JavascriptInterface
        fun importConfig(text: String): Boolean {{
            return try {{
                val before = MmkvManager.decodeServerList("").toSet()
                val (count, _) = AngConfigManager.importBatchConfig(text, "", false)
                if (count > 0) {{
                    // pick the one we just added, not whatever happens to be first
                    val after = MmkvManager.decodeServerList("")
                    val added = after.firstOrNull {{ it !in before }} ?: after.lastOrNull()
                    added?.let {{ MmkvManager.setSelectServer(it) }}
                }}
                count > 0
            }} catch (e: Exception) {{
                false
            }}
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

        /** Take the current config off this phone.
         *
         *  Stops the tunnel first — deleting the config a running service is
         *  using leaves it connected to something that no longer exists.
         */
        @JavascriptInterface
        fun removeConfig(): Boolean {{
            return try {{
                val guid = MmkvManager.getSelectServer()
                runOnUiThread {{
                    if (serviceRunning) {{
                        LauncherManager.stopService(this@InnernetActivity)
                    }}
                    if (!guid.isNullOrEmpty()) MmkvManager.removeServer(guid)
                    pushState(false)
                }}
                true
            }} catch (e: Exception) {{
                false
            }}
        }}

        /** Every config the app is holding, and which one is current.
         *
         *  Returned as JSON so the page can offer a choice — a phone with two
         *  cards had no way to say which one to connect with.
         */
        @JavascriptInterface
        fun listConfigs(): String {{
            return try {{
                val selected = MmkvManager.getSelectServer().orEmpty()
                val arr = org.json.JSONArray()
                MmkvManager.decodeServerList("").forEach {{ guid ->
                    val p = MmkvManager.decodeServerConfig(guid)
                    arr.put(org.json.JSONObject()
                        .put("id", guid)
                        .put("name", p?.remarks ?: guid.take(8))
                        .put("selected", guid == selected))
                }}
                arr.toString()
            }} catch (e: Exception) {{
                "[]"
            }}
        }}

        /** Choose which config the tunnel should use. */
        @JavascriptInterface
        fun selectConfig(guid: String): Boolean {{
            return try {{
                if (guid.isBlank()) return false
                val running = serviceRunning
                MmkvManager.setSelectServer(guid)
                if (running) {{
                    // switching while connected must actually switch the tunnel
                    runOnUiThread {{
                        LauncherManager.stopService(this@InnernetActivity)
                        LauncherManager.startService(this@InnernetActivity)
                    }}
                }}
                true
            }} catch (e: Exception) {{
                false
            }}
        }}

        /** Not usable from here, and kept only so older pages do not break.
         *
         *  queryAllOutboundTrafficStats() returns nothing unless the caller is
         *  the process running the tunnel, which this is not. The page reads
         *  usage from the server instead.
         */
        @JavascriptInterface
        fun stats(): String {{
            return try {{
                if (!serviceRunning) return "{{}}"
                var up = 0L
                var down = 0L
                CoreServiceManager.queryAllOutboundTrafficStats().forEach {{ stat ->
                    if (stat.tag != com.v2ray.ang.AppConfig.TAG_BLOCKED &&
                        stat.tag != com.v2ray.ang.AppConfig.TAG_DIRECT) {{
                        when (stat.direction) {{
                            com.v2ray.ang.AppConfig.UPLINK -> up += stat.value
                            com.v2ray.ang.AppConfig.DOWNLINK -> down += stat.value
                        }}
                    }}
                }}
                org.json.JSONObject()
                    .put("up", up).put("down", down)
                    .put("at", System.currentTimeMillis()).toString()
            }} catch (e: Exception) {{
                "{{}}"
            }}
        }}

        /** What the app thinks it is working with — shown when a start fails,
         *  so "can't connect" stops being the end of the conversation. */
        @JavascriptInterface
        fun diagnostics(): String {{
            return try {{
                val guid = MmkvManager.getSelectServer().orEmpty()
                val p = if (guid.isNotEmpty()) MmkvManager.decodeServerConfig(guid) else null
                org.json.JSONObject()
                    .put("configs", MmkvManager.decodeServerList("").size)
                    .put("selected", p?.remarks ?: "(none)")
                    .put("server", p?.server ?: "")
                    .put("port", p?.serverPort ?: "")
                    .put("running", serviceRunning)
                    .put("notifications", Build.VERSION.SDK_INT < 33 ||
                        ContextCompat.checkSelfPermission(this@InnernetActivity,
                            "android.permission.POST_NOTIFICATIONS") ==
                            android.content.pm.PackageManager.PERMISSION_GRANTED)
                    .put("vpnReady", android.net.VpnService.prepare(this@InnernetActivity) == null)
                    .put("sdk", Build.VERSION.SDK_INT)
                    .toString()
            }} catch (e: Exception) {{
                org.json.JSONObject().put("error", e.message ?: "unknown").toString()
            }}
        }}

        /** The last thing the tunnel engine said.
         *
         *  When a start fails, the engine has almost always written the reason.
         *  Reading it here turns "couldn't connect" into something specific.
         */
        @JavascriptInterface
        fun lastLog(): String {{
            return try {{
                val cmd = arrayOf("logcat", "-d", "-t", "400", "-v", "brief",
                                  "-s", "GoLog,com.v2ray.ang,AndroidRuntime,System.err")
                val proc = Runtime.getRuntime().exec(cmd)
                val lines = proc.inputStream.bufferedReader().use {{ it.readLines() }}
                val interesting = lines.filter {{ l ->
                    val t = l.lowercase()
                    t.contains("fail") || t.contains("error") || t.contains("invalid") ||
                    t.contains("refused") || t.contains("timeout") || t.contains("panic") ||
                    t.contains("unable")
                }}
                val pick = if (interesting.isNotEmpty()) interesting else lines
                pick.takeLast(6).joinToString(" | ").take(600)
            }} catch (e: Exception) {{
                ""
            }}
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
# ------------------------------------------------- the bridge must be complete
# Methods have been lost mid-edit before, which silently kills a button in the
# app while everything still compiles. Fail the build instead.
REQUIRED = ["version", "setConnected", "isConnected", "hasConfig", "importConfig",
            "scan", "paste", "biometric", "removeConfig", "listConfigs",
            "selectConfig", "stats", "diagnostics", "lastLog", "advanced"]
written = open(path, encoding="utf-8").read()
missing = [m for m in REQUIRED if f"fun {m}" not in written]
if missing:
    fail(f"bridge is incomplete, these methods are gone: {', '.join(missing)}")
if written.count("{") != written.count("}"):
    fail("generated Kotlin has unbalanced braces")
print(f"  bridge      : {len(REQUIRED)} methods, braces balanced")


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
