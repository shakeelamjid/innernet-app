"""Prove the bundled connect screen works with NO network and NO reachable site.

Loads assets/connect.html from file:// (as the APK does), injects a mock of the
v7 bridge, and exercises the whole critical path. There is no server anywhere in
this test — that is the point: if it works here, it works when innernetcorp.com
is blocked.
"""
import os, pathlib
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).parent
URL = (HERE / "assets" / "connect.html").as_uri()
fails = []

# a faithful mock of the v7 bridge, entirely in-page (no network)
BRIDGE = """
(function(){
  const S = {
    cfgs: [{id:'a', name:'Ali — iPhone', selected:true},
           {id:'b', name:'Family tablet', selected:false}],
    running: false
  };
  function broadcast(){ window.dispatchEvent(new CustomEvent('innernet:state',
    {detail:{connected:S.running}})); }
  window.Innernet = {
    version: ()=>8,
    currentLink: ()=>(S.cfgs.find(c=>c.selected)
        ? 'vless://11111111-2222-3333-4444-555555555555@x:443' : ''),
    listConfigs: ()=>JSON.stringify(S.cfgs),
    selectConfig: (id)=>{ S.cfgs.forEach(c=>c.selected = c.id===id); return true; },
    hasConfig: ()=>S.cfgs.some(c=>c.selected),
    setConnected: (on)=>{
      // model the real thing: it comes up a beat later, then broadcasts
      if(on){ setTimeout(()=>{ S.running=true; broadcast(); }, 400); }
      else { S.running=false; broadcast(); }
      return true;
    },
    isConnected: ()=>S.running,
    importConfig: ()=>true,
    removeConfig: ()=>{ S.cfgs = S.cfgs.filter(c=>!c.selected);
      if(S.cfgs.length) S.cfgs[0].selected=true; S.running=false; broadcast(); return true; },
    listRemove: ()=>true,
    scan: ()=>{ window.__scanned = (window.__scanned||0)+1; },
    paste: ()=>{ window.__pasted = (window.__pasted||0)+1; },
    diagnostics: ()=>JSON.stringify({configs:S.cfgs.length, selected:'Ali — iPhone',
      server:'1.2.3.4', port:8443, running:S.running, notifications:true, vpnReady:true}),
    lastLog: ()=>'', stats: ()=>'{}',
    biometric: ()=>false, advanced: ()=>{}
  };
})();
"""

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width":390,"height":844}, is_mobile=True,
                        offline=True)                    # <-- NO NETWORK AT ALL
    ctx.add_init_script(BRIDGE)
    pg = ctx.new_page()
    errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL); pg.wait_for_timeout(700)

    print("=== loads with no network, no server ===")
    body = (pg.inner_text("body") or "").strip()
    print("  screen is not blank:", len(body) > 20, "|", repr(body[:40]))
    if len(body) <= 20: fails.append("blank offline screen")
    if errs: fails.append("js error: "+errs[0][:80]); print("  JS error:", errs[0][:80])

    print("=== shows the held connections (from the engine, not a server) ===")
    opts = pg.eval_on_selector_all("#pick option", "e=>e.map(o=>o.textContent.trim())")
    print("  picker offers:", opts)
    if len(opts) != 2: fails.append("configs not listed offline")

    print("=== tap connect: works offline, waits for the service, then confirms ===")
    pg.click("#dial"); pg.wait_for_timeout(1200)
    connected = pg.eval_on_selector("#stage", "e=>e.classList.contains('on')")
    label = pg.text_content("#stateText")
    print("  connected:", connected, "| label:", label)
    if not connected: fails.append("could not connect offline")

    print("=== tap again: disconnects ===")
    pg.click("#dial"); pg.wait_for_timeout(600)
    off = not pg.eval_on_selector("#stage", "e=>e.classList.contains('on')")
    print("  disconnected:", off)
    if not off: fails.append("could not disconnect")

    print("=== switch connection (pure bridge) ===")
    pg.select_option("#pick", "b"); pg.wait_for_timeout(400)
    sel = pg.eval_on_selector("#pick option:checked", "e=>e.textContent.trim()")
    print("  now selected:", sel)
    if "tablet" not in (sel or ""): fails.append("switch failed")

    print("=== scan / paste reach the native bridge ===")
    pg.click("#scanBtn"); pg.click("#pasteBtn"); pg.wait_for_timeout(200)
    s = pg.evaluate("()=>window.__scanned||0"); pa = pg.evaluate("()=>window.__pasted||0")
    print("  scan calls:", s, "| paste calls:", pa)
    if not s or not pa: fails.append("scan/paste not wired")

    print("=== the store hint appears (site unreachable -> connect first) ===")
    mh = pg.text_content("#manageHint") or ""
    print("  hint:", mh[:60] or "(none)")
    if "Connect first" not in mh: fails.append("no bootstrap hint when offline")

    print("=== no traffic must NOT read as Connected ===")
    # The probe fails, which is what airplane mode looks like from in here.
    pg.route("**/speed/probe*", lambda route: route.abort())
    pg.click("#dial"); pg.wait_for_timeout(4500)
    head = pg.text_content("#stateText") or ""
    hint2 = pg.text_content("#stateHint") or ""
    print("  headline:", head, "| hint:", hint2)
    if "Connected" in head:
        fails.append("headline still says Connected with nothing getting through")
    pg.unroute("**/speed/probe*")
    pg.click("#dial"); pg.wait_for_timeout(800)

    print("=== a scan must not blank the screen ===")
    pg.evaluate("window.innernetImported && window.innernetImported()")
    pg.wait_for_timeout(300)
    body = (pg.inner_text("body") or "").strip()
    print("  still rendering after import:", len(body) > 20)
    if len(body) <= 20: fails.append("import hook blanked the page")
    print("  url unchanged:", pg.url.endswith("connect.html"))
    if not pg.url.endswith("connect.html"): fails.append("import navigated away")

    print("=== connection speed is measured while connected ===")
    # stand in for the server's probe: 1 MB served instantly, so the number is
    # deterministic enough to assert on
    pg.route("**/speed/probe*", lambda route: route.fulfill(
        status=200, body=b"\0" * 1000000,
        headers={"Content-Type": "application/octet-stream",
                 "Access-Control-Allow-Origin": "*"}))
    reported = []
    pg.route("**/speed/report", lambda route: (reported.append(route.request.post_data or ""),
                                               route.fulfill(status=200, body="{}")))
    pg.click("#dial")
    pg.wait_for_timeout(6000)
    shown = pg.is_visible("#live")
    val = pg.text_content("#mbps")
    print("  panel visible:", shown, "| reads:", val, "Mbps")
    if not shown: fails.append("no speed panel while connected")
    if val in ("—", "…"): fails.append("speed never resolved")
    print("  reported home:", bool(reported), "| carries a timezone:",
          any("tz=" in r for r in reported))
    if not reported: fails.append("measurement not reported")

    print("=== My plan opens inside the app, never navigating away ===")
    pg.route("**/api/plan*", lambda route: route.fulfill(
        status=200, content_type="application/json",
        headers={"Access-Control-Allow-Origin": "*"},
        body='{"ok":true,"name":"Ali","unlimited_data":false,"no_expiry":false,'
             '"gb_left":12.5,"gb_total":40,"pct":31,"days_left":9}'))
    pg.click("#mAccount"); pg.wait_for_timeout(1800)
    sheet_open = pg.is_visible("#sheet")
    body = pg.inner_text("#sheetBody") or ""
    print("  sheet body was:", repr(body[:90]))
    print("  sheet opened:", sheet_open, "| url unchanged:", pg.url.endswith("connect.html"))
    print("  shows the plan:", "12.5" in body and "9 days" in body.replace("  ", " "))
    if not sheet_open: fails.append("My plan did not open")
    if not pg.url.endswith("connect.html"): fails.append("My plan navigated away")
    if "12.5" not in body: fails.append("plan data missing")

    print("=== renew is drawn in the app, not fetched as a page ===")
    pg.route("**/api/renew*", lambda route: route.fulfill(
        status=200, content_type="application/json",
        headers={"Access-Control-Allow-Origin": "*"},
        body='{"ok":true,"name":"Ali","unlimited":false,"never_expires":false,'
             '"gb":40,"days":30,"price_cents":770,"price":"$7.70",'
             '"min_gb":5,"max_gb":500,"step_gb":5,"min_days":7,"max_days":180,'
             '"step_days":1,"networks":["TRC20"],"wallets":{"TRC20":"TXaddr"},"pending":""}'))
    pg.click("#sheetClose"); pg.wait_for_timeout(300)
    pg.click("#mRenew"); pg.wait_for_timeout(1600)
    rbody = pg.inner_text("#sheetBody") or ""
    print("  no iframe used:", not pg.is_visible("#sheetFrame"))
    print("  shows a price:", "$7.70" in rbody, "| steppers:", "40 GB" in rbody and "30 days" in rbody)
    if pg.is_visible("#sheetFrame"): fails.append("renew still loads a server page")
    if "$7.70" not in rbody: fails.append("renew price not drawn")
    pg.click('[data-step="gb"][data-dir="1"]'); pg.wait_for_timeout(400)
    print("  stepper moves:", pg.text_content("#r_gb"))
    if "45" not in (pg.text_content("#r_gb") or ""): fails.append("stepper does not step")
    pg.click("#payVoucher"); pg.wait_for_timeout(300)
    print("  voucher field appears:", pg.is_visible("#vCode"))
    if not pg.is_visible("#vCode"): fails.append("no voucher entry")
    pg.click("#payCrypto"); pg.wait_for_timeout(300)
    print("  usdt address shown:", "TXaddr" in (pg.inner_text("#payArea") or ""))
    pg.unroute("**/api/renew*")

    print("=== an unlimited plan is not offered a renewal ===")
    pg.click("#sheetClose"); pg.wait_for_timeout(400)
    pg.route("**/api/plan*", lambda route: route.fulfill(
        status=200, content_type="application/json",
        headers={"Access-Control-Allow-Origin": "*"},
        body='{"ok":true,"name":"Forever","unlimited_data":true,"no_expiry":true,'
             '"gb_left":null,"gb_total":null,"pct":0,"days_left":null}'))
    pg.click("#mAccount"); pg.wait_for_timeout(1800)
    body2 = pg.inner_text("#sheetBody") or ""
    print("  says unlimited:", "Unlimited" in body2)
    print("  offers renew:", "Renew" in body2, "(must be False)")
    if "Renew" in body2: fails.append("unlimited plan still offered a renewal")
    if "Unlimited" not in body2: fails.append("unlimited not stated")

    print("=== closing returns to a live connect screen ===")
    pg.click("#sheetClose"); pg.wait_for_timeout(700)
    print("  sheet closed:", not pg.is_visible("#sheet"),
          "| still connected:", pg.eval_on_selector("#stage","e=>e.classList.contains('on')"))
    if pg.is_visible("#sheet"): fails.append("sheet would not close")

    print("=== version stamp visible ===")
    print("  stamp:", pg.text_content("#stamp"))

    print("=== ONE config: no dropdown clutter ===")
    ctx2 = b.new_context(viewport={"width":390,"height":844}, is_mobile=True, offline=True)
    ctx2.add_init_script(BRIDGE.replace(
        "{id:'b', name:'Family tablet', selected:false}", ""))
    p2 = ctx2.new_page(); p2.goto(URL); p2.wait_for_timeout(600)
    # The <select> must still EXIST — destroying it is what broke switching
    # once a second config was added — but it must not be shown for one.
    exists = p2.query_selector("#pick") is not None
    shown = p2.is_visible("#pick")
    label = p2.is_visible("#pickOne")
    print("  select exists:", exists, "| hidden:", not shown, "| name shown instead:", label)
    if not exists: fails.append("the select was destroyed; switching will break later")
    if shown: fails.append("dropdown shown for a single config")
    if not label: fails.append("single config name not shown")

    print("=== adding a second config must leave a working picker ===")
    # The exact regression: hold one config, then receive another. The old code
    # replaced the <select> with a <div> for the single case, so the options
    # rendered as plain stacked text and nothing could be chosen again.
    c3 = b.new_context(viewport={"width":390,"height":844}, is_mobile=True, offline=True)
    c3.add_init_script(BRIDGE.replace(
        "{id:'b', name:'Family tablet', selected:false}", ""))
    p3 = c3.new_page()
    p3.goto(URL)
    p3.wait_for_timeout(700)
    p3.evaluate("""() => {
        const first = JSON.parse(window.Innernet.listConfigs());
        window.Innernet.listConfigs = () => JSON.stringify(
            first.concat([{id: 'b', name: 'Family tablet', selected: false}]));
    }""")
    p3.evaluate("window.innernetImported && window.innernetImported()")
    p3.wait_for_timeout(600)
    tag = p3.eval_on_selector("#pick", "e=>e.tagName.toLowerCase()")
    opts = p3.eval_on_selector_all("#pick option", "e=>e.map(o=>o.textContent.trim())")
    visible = p3.is_visible("#pick")
    print("  #pick is still a <" + tag + ">, visible:", visible, "| offers:", opts)
    if tag != "select":
        fails.append("the single-config path destroyed the picker")
    if len(opts) != 2 or not visible:
        fails.append("second config is not selectable")

    b.close()

print("\nFAILURES:", fails if fails else "NONE")
