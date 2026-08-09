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
    version: ()=>7,
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

    print("=== airplane mode must NOT claim traffic is flowing ===")
    pg.evaluate("Object.defineProperty(navigator,'onLine',{get:()=>false,configurable:true})")
    pg.evaluate("window.dispatchEvent(new CustomEvent('innernet:state',{detail:{connected:true}}))")
    pg.wait_for_timeout(400)
    h = pg.text_content("#stateHint") or ""
    print("  hint while offline:", h)
    if "nothing is getting through" not in h:
        fails.append("still claims a working connection with no network")

    print("=== version stamp visible ===")
    print("  stamp:", pg.text_content("#stamp"))

    print("=== ONE config: no dropdown clutter ===")
    ctx2 = b.new_context(viewport={"width":390,"height":844}, is_mobile=True, offline=True)
    ctx2.add_init_script(BRIDGE.replace(
        "{id:'b', name:'Family tablet', selected:false}", ""))
    p2 = ctx2.new_page(); p2.goto(URL); p2.wait_for_timeout(600)
    is_select = p2.eval_on_selector("#pick", "e=>e.tagName.toLowerCase()") if p2.query_selector("#pick") else "none"
    print("  #pick is a <"+is_select+"> (want div, not select)")
    if is_select == "select": fails.append("dropdown shown for a single config")

    b.close()

print("\nFAILURES:", fails if fails else "NONE")
