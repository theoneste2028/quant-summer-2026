"""
Week 12 — Build the self-contained capstone results page
========================================================
Reads `capstone.json` and writes `capstone.html`: one file, no external
requests, no build step, deployable anywhere (Vercel, GitHub Pages, or opened
straight from disk).

The JSON is inlined rather than fetched so the page works from `file://` and
under a strict CSP. Charts are hand-drawn SVG — a charting library would be a
CDN request the page cannot make.

Run:
    python site/build_page.py
"""
from __future__ import annotations
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(HERE, "capstone.json")
OUT_PATH = os.path.join(HERE, "capstone.html")

TEMPLATE_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Utility-Based Portfolio Optimizer — Quant Summer 2026</title>
<meta name="description" content="A four-layer quantitative pipeline: SQL data layer, distribution fitting, Markowitz optimization with shrinkage, certainty-equivalent selection, and Monte Carlo risk.">
<style>
:root{
  --ground:#F6F6F4; --raised:#FFFFFF; --ink:#191C22; --muted:#626A77;
  --rule:#DEDFDB; --rule-strong:#C7C9C4;
  --current:#3F6698; --recommended:#B0703A; --warn:#A8453A; --good:#3F7A5E;
  --shadow:0 1px 2px rgba(20,24,32,.05), 0 8px 24px rgba(20,24,32,.04);
}
@media (prefers-color-scheme: dark){
  :root{
    --ground:#15171B; --raised:#1C1F24; --ink:#E6E8EC; --muted:#949CAA;
    --rule:#282C33; --rule-strong:#3A3F48;
    --current:#7BA3D6; --recommended:#D9A06A; --warn:#D97B6E; --good:#6FB392;
    --shadow:0 1px 2px rgba(0,0,0,.3), 0 8px 24px rgba(0,0,0,.25);
  }
}
:root[data-theme="light"]{
  --ground:#F6F6F4; --raised:#FFFFFF; --ink:#191C22; --muted:#626A77;
  --rule:#DEDFDB; --rule-strong:#C7C9C4;
  --current:#3F6698; --recommended:#B0703A; --warn:#A8453A; --good:#3F7A5E;
  --shadow:0 1px 2px rgba(20,24,32,.05), 0 8px 24px rgba(20,24,32,.04);
}
:root[data-theme="dark"]{
  --ground:#15171B; --raised:#1C1F24; --ink:#E6E8EC; --muted:#949CAA;
  --rule:#282C33; --rule-strong:#3A3F48;
  --current:#7BA3D6; --recommended:#D9A06A; --warn:#D97B6E; --good:#6FB392;
  --shadow:0 1px 2px rgba(0,0,0,.3), 0 8px 24px rgba(0,0,0,.25);
}

*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
    "Helvetica Neue",Arial,sans-serif;
  font-size:16px; line-height:1.6;
  -webkit-font-smoothing:antialiased;
}
.mono{font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,
  "Liberation Mono",monospace; font-variant-numeric:tabular-nums}

.wrap{max-width:1080px; margin:0 auto; padding:0 24px}
.col{max-width:68ch}
main{display:flex; flex-direction:column; gap:64px; padding-bottom:96px}

/* ---------- masthead ---------- */
header{border-bottom:1px solid var(--rule); padding:56px 0 32px; margin-bottom:8px}
.eyebrow{
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:12px; letter-spacing:.14em; text-transform:uppercase;
  color:var(--muted); margin:0 0 18px;
}
h1{
  font-size:clamp(30px,4.6vw,50px); line-height:1.08; letter-spacing:-.022em;
  font-weight:660; margin:0 0 18px; text-wrap:balance;
}
.lede{font-size:19px; line-height:1.62; color:var(--muted); margin:0; max-width:62ch}
.meta{
  display:flex; flex-wrap:wrap; gap:8px 28px; margin-top:26px;
  font-size:12.5px; color:var(--muted);
}
.meta b{color:var(--ink); font-weight:600}

/* ---------- section furniture ---------- */
section h2{
  font-size:13px; letter-spacing:.13em; text-transform:uppercase;
  color:var(--muted); font-weight:600; margin:0 0 6px;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
section h3{
  font-size:clamp(21px,2.5vw,28px); line-height:1.22; letter-spacing:-.015em;
  font-weight:640; margin:0 0 16px; text-wrap:balance;
}
section p{margin:0 0 16px}
section p:last-child{margin-bottom:0}
.note{font-size:14.5px; color:var(--muted)}

/* ---------- scorecard ---------- */
/* Six cards, so the column count must divide 6 evenly — an auto-fit grid
   leaves a trailing empty cell that shows the rule-coloured background as a
   grey block. Explicit breakpoints keep every row full. */
.scorecard{
  display:grid; grid-template-columns:repeat(3,1fr); gap:1px;
  background:var(--rule); border:1px solid var(--rule); border-radius:10px;
  overflow:hidden; box-shadow:var(--shadow);
}
@media (max-width:880px){ .scorecard{grid-template-columns:repeat(2,1fr)} }
@media (max-width:520px){ .scorecard{grid-template-columns:1fr} }
.cell{background:var(--raised); padding:18px 18px 16px}
.cell .k{
  font-size:11px; letter-spacing:.1em; text-transform:uppercase;
  color:var(--muted); margin-bottom:10px;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
.pair{display:flex; align-items:baseline; justify-content:space-between; gap:10px}
.pair + .pair{margin-top:7px}
.pair .lbl{font-size:11.5px; color:var(--muted)}
.v{font-size:19px; font-weight:620; letter-spacing:-.01em}
.v.cur{color:var(--current)} .v.rec{color:var(--recommended)}
.delta{font-size:11.5px; margin-top:11px; padding-top:10px;
  border-top:1px solid var(--rule); color:var(--muted)}
.delta b{font-weight:640}
.delta.better b{color:var(--good)} .delta.worse b{color:var(--warn)}

/* ---------- legend ---------- */
.legend{display:flex; flex-wrap:wrap; gap:18px; margin:0 0 14px; font-size:13px}
.legend span{display:inline-flex; align-items:center; gap:7px; color:var(--muted)}
.sw{width:13px; height:13px; border-radius:3px; flex:none}

/* ---------- figures ---------- */
figure{margin:0}
.chart{
  background:var(--raised); border:1px solid var(--rule); border-radius:10px;
  padding:18px; box-shadow:var(--shadow); overflow-x:auto;
}
.chart svg{display:block; width:100%; height:auto; min-width:520px}
figcaption{font-size:13.5px; color:var(--muted); margin-top:12px; max-width:70ch}

/* ---------- layers ---------- */
.layers{display:flex; flex-direction:column; gap:1px; background:var(--rule);
  border:1px solid var(--rule); border-radius:10px; overflow:hidden}
.layer{background:var(--raised); padding:18px 20px; display:grid;
  grid-template-columns:auto 1fr; gap:18px; align-items:start}
.layer .n{
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:12px; color:var(--muted); padding-top:3px; letter-spacing:.06em;
}
.layer .t{font-weight:640; margin:0 0 3px}
.layer .s{font-size:14px; color:var(--muted); margin:0}
.layer .src{
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:11.5px; color:var(--muted); margin-top:6px;
}

/* ---------- tables ---------- */
.tablewrap{overflow-x:auto; border:1px solid var(--rule); border-radius:10px;
  background:var(--raised); box-shadow:var(--shadow)}
table{border-collapse:collapse; width:100%; font-size:14px; min-width:480px}
th,td{padding:10px 14px; text-align:right; border-bottom:1px solid var(--rule)}
th:first-child,td:first-child{text-align:left}
thead th{
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:11px; letter-spacing:.08em; text-transform:uppercase;
  color:var(--muted); font-weight:600; white-space:nowrap;
}
tbody tr:last-child td{border-bottom:none}
tbody tr.hi td{background:color-mix(in srgb, var(--recommended) 9%, transparent)}
td.num{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-variant-numeric:tabular-nums}

/* ---------- finding blocks ---------- */
.finding{border-left:2px solid var(--rule-strong); padding-left:22px}
.finding + .finding{margin-top:34px}
.finding .tag{
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:11px; letter-spacing:.11em; text-transform:uppercase;
  color:var(--muted); display:block; margin-bottom:7px;
}
.finding h4{font-size:19px; font-weight:640; margin:0 0 12px; letter-spacing:-.01em}

ul.plain{margin:0; padding-left:20px}
ul.plain li{margin-bottom:9px}
ul.plain li:last-child{margin-bottom:0}

footer{border-top:1px solid var(--rule); padding:28px 0 60px; font-size:13px;
  color:var(--muted)}
footer a{color:var(--ink); text-decoration:none; border-bottom:1px solid var(--rule-strong)}
footer a:hover{border-bottom-color:var(--ink)}
a:focus-visible,button:focus-visible{outline:2px solid var(--current); outline-offset:3px}

@media (max-width:640px){
  header{padding-top:38px}
  .layer{grid-template-columns:1fr; gap:7px}
  main{gap:48px}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important; transition:none!important}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <p class="eyebrow">Quant Summer 2026 &middot; Capstone</p>
  <h1>What a portfolio is actually worth taking on</h1>
  <p class="lede">A four-layer pipeline that reads a real brokerage history out of SQL,
  measures how badly returns break the normality assumption, traces an efficient
  frontier, and picks one allocation using a risk tolerance rather than a hunch.
  Then it says honestly what it still cannot see.</p>
  <div class="meta" id="meta"></div>
</header>
<main></main>
</div>
"""

TEMPLATE_TAIL = """
<script>
(function(){
  const $ = (s,r)=> (r||document).querySelector(s);
  const main = $("main");
  const pct = (v,d)=> (v*100).toFixed(d===undefined?1:d)+"%";
  const NS = "http://www.w3.org/2000/svg";
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

  function el(tag, attrs, txt){
    const e = document.createElementNS(NS, tag);
    for(const k in attrs) e.setAttribute(k, attrs[k]);
    if(txt !== undefined) e.textContent = txt;
    return e;
  }
  function svg(w,h){
    const s = el("svg", {viewBox:`0 0 ${w} ${h}`, role:"img"});
    return s;
  }
  function section(id, kicker, title, bodyHTML){
    const s = document.createElement("section");
    s.className = "wrapsec";
    s.innerHTML = `<div class="col"><h2>${kicker}</h2><h3>${title}</h3>${bodyHTML||""}</div>`;
    main.appendChild(s);
    return s;
  }

  // ---------- meta ----------
  const m = DATA.meta;
  $("#meta").innerHTML = [
    ["Estimation window", `${m.window_start} → ${m.window_end}`],
    ["Trading days", m.n_days],
    ["Assets", m.n_assets],
    ["Risk tolerance", pct(m.risk_tolerance_pct_of_wealth,0)+" of portfolio value"],
    ["Values", m.value_unit]
  ].map(([k,v])=>`<div>${k} <b>${v}</b></div>`).join("");

  // ---------- scorecard ----------
  const rec = DATA.portfolios.recommended, cur = DATA.portfolios.current;
  const mt = DATA.monte_carlo.recommended_t, ct = DATA.monte_carlo.current_t;
  const cards = [
    {k:"Expected return", cur:pct(cur.ret), rec:pct(rec.ret),
     note:"Lower — deliberately", cls:""},
    {k:"Volatility", cur:pct(cur.vol), rec:pct(rec.vol),
     note:`${((1-rec.vol/cur.vol)*100).toFixed(0)}% less risk`, cls:"better"},
    {k:"Sharpe ratio", cur:cur.sharpe.toFixed(2), rec:rec.sharpe.toFixed(2),
     note:`+${((rec.sharpe/cur.sharpe-1)*100).toFixed(0)}% per unit of risk`, cls:"better"},
    {k:"P(loss > 10%)", cur:pct(ct.p_loss_10), rec:pct(mt.p_loss_10),
     note:`${((1-mt.p_loss_10/ct.p_loss_10)*100).toFixed(0)}% less likely`, cls:"better"},
    {k:"1% VaR (1 year)", cur:pct(ct.var_1), rec:pct(mt.var_1),
     note:"Worst-case tail, cut by half", cls:"better"},
    {k:"Certainty equivalent", cur:cur.ce.toFixed(1), rec:rec.ce.toFixed(1),
     note:`+${(rec.ce-cur.ce).toFixed(1)} on a base of 100`, cls:"better"}
  ];
  const sc = document.createElement("section");
  sc.innerHTML = `<div class="col"><h2>The result</h2>
    <h3>Same money, materially less risk</h3>
    <p>Every column compares the portfolio as it is against the allocation the
    pipeline recommends for a moderate risk tolerance. The recommendation gives
    up expected return on purpose: it buys a far better trade-off per unit of
    risk, and a much thinner tail.</p></div>
    <div class="legend" style="margin-top:22px">
      <span><i class="sw" style="background:var(--current)"></i> Current portfolio</span>
      <span><i class="sw" style="background:var(--recommended)"></i> Recommended</span>
    </div>
    <div class="scorecard">${cards.map(c=>`
      <div class="cell">
        <div class="k">${c.k}</div>
        <div class="pair"><span class="lbl">Current</span><span class="v cur mono">${c.cur}</span></div>
        <div class="pair"><span class="lbl">Recommended</span><span class="v rec mono">${c.rec}</span></div>
        <div class="delta ${c.cls}"><b>${c.note}</b></div>
      </div>`).join("")}</div>`;
  main.appendChild(sc);

  // ---------- layers ----------
  const layers = [
    ["Data","Read the real trade history and prices out of SQLite — never a live API call. The database built in weeks 5–8 is the single source of truth.","CS 217 · SQL, ETL, indexing"],
    ["Statistics","Estimate the mean vector and covariance, then fit Normal, Student-t and Laplace to every asset to measure how far from normal the returns really are.","IEMS 302 · distributions, estimation"],
    ["Optimization","Solve the Markowitz problem across a grid of risk-aversion values with CVXPY to trace the efficient frontier, using shrunk estimates and a position cap.","CivEnv 205 · constrained optimization"],
    ["Decision","A frontier is a menu, not an answer. Certainty equivalents under an exponential utility pick the single portfolio a given risk tolerance should hold.","Week 10 · utility, decision analysis"],
    ["Simulation","Simulate the chosen portfolio forward for a year under both normal and fat-tailed innovations, and report the loss probabilities and tail risk.","Week 3 · Monte Carlo, CLT"]
  ];
  const ls = document.createElement("section");
  ls.innerHTML = `<div class="col"><h2>How it works</h2>
    <h3>Five layers, each one a different course</h3>
    <p>The pipeline runs in sequence — each layer consumes what the one above
    produced, so a mistake anywhere changes the recommendation at the end.</p></div>
    <div class="layers" style="margin-top:24px">${layers.map((l,i)=>`
      <div class="layer">
        <div class="n">0${i+1}</div>
        <div><p class="t">${l[0]}</p><p class="s">${l[1]}</p>
        <p class="src">${l[2]}</p></div>
      </div>`).join("")}</div>`;
  main.appendChild(ls);

  // ---------- frontier chart ----------
  function frontierChart(){
    const W=880,H=470,P={t:24,r:26,b:52,l:66};
    const pts = DATA.frontier.robust;
    const xs = pts.map(p=>p.vol).concat([cur.vol, rec.vol, DATA.portfolios.min_variance.vol]);
    const ys = pts.map(p=>p.ret).concat([cur.ret, rec.ret, DATA.portfolios.min_variance.ret]);
    const x0=0, x1=Math.max(...xs)*1.08, y0=0, y1=Math.max(...ys)*1.1;
    const X=v=>P.l+(v-x0)/(x1-x0)*(W-P.l-P.r);
    const Y=v=>H-P.b-(v-y0)/(y1-y0)*(H-P.t-P.b);
    const s=svg(W,H);
    s.appendChild(el("title",{},"Efficient frontier with the current and recommended portfolios"));

    for(let i=0;i<=5;i++){
      const gv=y0+(y1-y0)*i/5;
      s.appendChild(el("line",{x1:P.l,x2:W-P.r,y1:Y(gv),y2:Y(gv),
        stroke:css("--rule"),"stroke-width":1}));
      s.appendChild(el("text",{x:P.l-10,y:Y(gv)+4,"text-anchor":"end",
        fill:css("--muted"),"font-size":11,"font-family":"ui-monospace,Menlo,monospace"},
        (gv*100).toFixed(0)+"%"));
    }
    for(let i=0;i<=5;i++){
      const gv=x0+(x1-x0)*i/5;
      s.appendChild(el("text",{x:X(gv),y:H-P.b+20,"text-anchor":"middle",
        fill:css("--muted"),"font-size":11,"font-family":"ui-monospace,Menlo,monospace"},
        (gv*100).toFixed(0)+"%"));
    }
    s.appendChild(el("line",{x1:P.l,x2:W-P.r,y1:H-P.b,y2:H-P.b,
      stroke:css("--rule-strong"),"stroke-width":1}));

    const dpath = pts.map((p,i)=>(i?"L":"M")+X(p.vol)+" "+Y(p.ret)).join(" ");
    s.appendChild(el("path",{d:dpath,fill:"none",stroke:css("--ink"),
      "stroke-width":2,"stroke-linejoin":"round"}));

    const mv=DATA.portfolios.min_variance;
    s.appendChild(el("circle",{cx:X(mv.vol),cy:Y(mv.ret),r:5.5,
      fill:css("--ground"),stroke:css("--ink"),"stroke-width":2}));
    s.appendChild(el("text",{x:X(mv.vol)+11,y:Y(mv.ret)+4,fill:css("--muted"),
      "font-size":11.5},"Minimum variance"));

    // dashed connector current -> recommended
    s.appendChild(el("line",{x1:X(cur.vol),y1:Y(cur.ret),x2:X(rec.vol),y2:Y(rec.ret),
      stroke:css("--muted"),"stroke-width":1.4,"stroke-dasharray":"5 5"}));

    s.appendChild(el("circle",{cx:X(cur.vol),cy:Y(cur.ret),r:8,
      fill:css("--current"),stroke:css("--raised"),"stroke-width":2}));
    s.appendChild(el("text",{x:X(cur.vol)-12,y:Y(cur.ret)+4,"text-anchor":"end",
      fill:css("--current"),"font-size":12.5,"font-weight":600},"Current"));

    s.appendChild(el("circle",{cx:X(rec.vol),cy:Y(rec.ret),r:8,
      fill:css("--recommended"),stroke:css("--raised"),"stroke-width":2}));
    s.appendChild(el("text",{x:X(rec.vol),y:Y(rec.ret)-15,"text-anchor":"middle",
      fill:css("--recommended"),"font-size":12.5,"font-weight":600},"Recommended"));

    s.appendChild(el("text",{x:(P.l+W-P.r)/2,y:H-10,"text-anchor":"middle",
      fill:css("--muted"),"font-size":12},"Annualised volatility"));
    s.appendChild(el("text",{x:16,y:(P.t+H-P.b)/2,"text-anchor":"middle",
      fill:css("--muted"),"font-size":12,
      transform:`rotate(-90 16 ${(P.t+H-P.b)/2})`},"Expected annual return"));
    return s;
  }

  const fsec = section("frontier","Layer 3 &middot; Optimization",
    "The current portfolio sits well below the frontier",
    `<p>Every point on the curve is a portfolio that gets the most return
     available for its level of risk. The current allocation sits below and to
     the right of it — carrying about ${pct(cur.vol,0)} volatility for a
     trade-off the frontier delivers at far less. The dashed line is the move
     the recommendation proposes.</p>`);
  const f1=document.createElement("figure");
  f1.innerHTML = `<div class="chart"></div>
    <figcaption>Frontier computed from shrunk estimates with a
    ${pct(m.max_weight,0)} cap on any single position. The minimum-variance
    point uses no expected-return estimates at all — it is the benchmark a
    return forecast has to beat to justify itself.</figcaption>`;
  f1.querySelector(".chart").appendChild(frontierChart());
  fsec.appendChild(f1);

  // ---------- allocation ----------
  function allocChart(){
    const keys = Array.from(new Set(Object.keys(rec.weights).concat(Object.keys(cur.weights))));
    keys.sort((a,b)=> ((rec.weights[b]||0)+(cur.weights[b]||0)) - ((rec.weights[a]||0)+(cur.weights[a]||0)));
    const rowH=30, W=880, P={t:14,r:70,b:34,l:66};
    const H=P.t+P.b+keys.length*rowH;
    const maxw=Math.max(...keys.map(k=>Math.max(rec.weights[k]||0,cur.weights[k]||0)))*1.12;
    const X=v=>P.l+v/maxw*(W-P.l-P.r);
    const s=svg(W,H);
    s.appendChild(el("title",{},"Recommended versus current allocation by ticker"));
    keys.forEach((k,i)=>{
      const y=P.t+i*rowH, bh=10.5;
      s.appendChild(el("text",{x:P.l-12,y:y+rowH/2+4,"text-anchor":"end",
        fill:css("--ink"),"font-size":12.5,"font-weight":600,
        "font-family":"ui-monospace,Menlo,monospace"},k));
      const rw=rec.weights[k]||0, cw=cur.weights[k]||0;
      s.appendChild(el("rect",{x:P.l,y:y+rowH/2-bh-1.5,width:Math.max(X(rw)-P.l,0),
        height:bh,fill:css("--recommended"),rx:2}));
      s.appendChild(el("rect",{x:P.l,y:y+rowH/2+1.5,width:Math.max(X(cw)-P.l,0),
        height:bh,fill:css("--current"),rx:2}));
      if(rw>0) s.appendChild(el("text",{x:X(rw)+7,y:y+rowH/2-3.5,
        fill:css("--recommended"),"font-size":11,
        "font-family":"ui-monospace,Menlo,monospace"},pct(rw,0)));
      if(cw>0) s.appendChild(el("text",{x:X(cw)+7,y:y+rowH/2+10,
        fill:css("--current"),"font-size":11,
        "font-family":"ui-monospace,Menlo,monospace"},pct(cw,0)));
    });
    return s;
  }
  const asec = section("alloc","Layer 4 &middot; Decision",
    "What would actually change",
    `<p>The recommendation keeps the strongest existing positions and adds two
     things the portfolio has none of: a broad dividend fund and gold. Both earn
     their place through low correlation rather than high expected return —
     which is exactly what an optimizer is for and what intuition tends to miss.</p>`);
  const f2=document.createElement("figure");
  f2.innerHTML=`<div class="legend"><span><i class="sw" style="background:var(--recommended)"></i>Recommended</span><span><i class="sw" style="background:var(--current)"></i>Current</span></div><div class="chart"></div>
    <figcaption>Positions excluded from the universe for insufficient price
    history are not shown; they account for
    ${pct(1-DATA.universe.coverage,0)} of current portfolio value.</figcaption>`;
  f2.querySelector(".chart").appendChild(allocChart());
  asec.appendChild(f2);

  // ---------- fan ----------
  function fanChart(){
    const fan=DATA.monte_carlo.fan, W=880,H=430,P={t:20,r:24,b:50,l:66};
    const mo=fan.months, base=m.wealth;
    const all=[].concat(fan.p5,fan.p95);
    const y0=Math.min(...all)*0.97, y1=Math.max(...all)*1.03;
    const X=v=>P.l+v/12*(W-P.l-P.r);
    const Y=v=>H-P.b-(v-y0)/(y1-y0)*(H-P.t-P.b);
    const s=svg(W,H);
    s.appendChild(el("title",{},"Simulated portfolio value over the next year"));
    for(let i=0;i<=5;i++){
      const gv=y0+(y1-y0)*i/5;
      s.appendChild(el("line",{x1:P.l,x2:W-P.r,y1:Y(gv),y2:Y(gv),
        stroke:css("--rule"),"stroke-width":1}));
      s.appendChild(el("text",{x:P.l-10,y:Y(gv)+4,"text-anchor":"end",
        fill:css("--muted"),"font-size":11,"font-family":"ui-monospace,Menlo,monospace"},
        gv.toFixed(0)));
    }
    const band=(lo,hi,op)=>{
      const d=mo.map((t,i)=>(i?"L":"M")+X(t)+" "+Y(lo[i])).join(" ")+" "+
        mo.slice().reverse().map((t,i)=>"L"+X(t)+" "+Y(hi[hi.length-1-i])).join(" ")+" Z";
      s.appendChild(el("path",{d:d,fill:css("--recommended"),opacity:op,stroke:"none"}));
    };
    band(fan.p5,fan.p95,.15); band(fan.p10,fan.p90,.2); band(fan.p25,fan.p75,.28);
    s.appendChild(el("path",{d:mo.map((t,i)=>(i?"L":"M")+X(t)+" "+Y(fan.p50[i])).join(" "),
      fill:"none",stroke:css("--recommended"),"stroke-width":2.4}));
    s.appendChild(el("line",{x1:P.l,x2:W-P.r,y1:Y(base),y2:Y(base),
      stroke:css("--ink"),"stroke-width":1.3,"stroke-dasharray":"6 4"}));
    s.appendChild(el("text",{x:W-P.r-4,y:Y(base)-7,"text-anchor":"end",
      fill:css("--ink"),"font-size":11.5},"Starting value"));
    s.appendChild(el("line",{x1:P.l,x2:W-P.r,y1:Y(base*0.9),y2:Y(base*0.9),
      stroke:css("--warn"),"stroke-width":1.2,"stroke-dasharray":"3 4"}));
    s.appendChild(el("text",{x:W-P.r-4,y:Y(base*0.9)+15,"text-anchor":"end",
      fill:css("--warn"),"font-size":11.5},"\\u221210% threshold"));
    [0,3,6,9,12].forEach(t=>s.appendChild(el("text",{x:X(t),y:H-P.b+20,
      "text-anchor":"middle",fill:css("--muted"),"font-size":11,
      "font-family":"ui-monospace,Menlo,monospace"},t+"m")));
    s.appendChild(el("text",{x:(P.l+W-P.r)/2,y:H-10,"text-anchor":"middle",
      fill:css("--muted"),"font-size":12},"Months ahead"));
    return s;
  }
  const msec = section("mc","Layer 5 &middot; Simulation",
    "A year of possible outcomes",
    `<p>One hundred thousand simulated years of the recommended portfolio, with
     fat-tailed innovations calibrated to the fitted degrees of freedom. The
     median path ends around ${pct(mt.median)} up, but roughly one year in five
     ends below where it started.</p>`);
  const f3=document.createElement("figure");
  f3.innerHTML=`<div class="chart"></div>
    <figcaption>Shaded bands cover the middle 50%, 80% and 90% of outcomes.
    P(loss&nbsp;&gt;&nbsp;10%) = <b>${pct(mt.p_loss_10)}</b> &middot;
    5% VaR = <b>${pct(mt.var_5)}</b> &middot;
    1% VaR = <b>${pct(mt.var_1)}</b>.</figcaption>`;
  f3.querySelector(".chart").appendChild(fanChart());
  msec.appendChild(f3);

  // ---------- risk sweep table ----------
  const sweep=DATA.risk_sweep;
  const chosen=m.risk_tolerance_pct_of_wealth;
  const ssec = section("sweep","Layer 4 &middot; Sensitivity",
    "The answer depends on a number nobody knows exactly",
    `<p>Risk tolerance is not observable. Rather than defend one guess, the
     pipeline reports the whole map: for each tolerance, the portfolio it
     implies. A reader can find their own row instead of trusting mine.</p>`);
  const tw=document.createElement("div");
  tw.className="tablewrap";
  tw.innerHTML=`<table><thead><tr>
    <th>Risk tolerance</th><th>Return</th><th>Volatility</th><th>Sharpe</th>
    <th>Holdings</th><th>Largest positions</th></tr></thead><tbody>
    ${sweep.map(r=>`<tr class="${Math.abs(r.r_fraction-chosen)<1e-9?"hi":""}">
      <td class="num">${pct(r.r_fraction,0)} of value</td>
      <td class="num">${pct(r.ret)}</td><td class="num">${pct(r.vol)}</td>
      <td class="num">${r.sharpe.toFixed(2)}</td>
      <td class="num">${r.n_holdings}</td>
      <td style="text-align:left" class="mono">${r.top}</td></tr>`).join("")}
    </tbody></table>`;
  ssec.appendChild(tw);
  const cap=document.createElement("p");
  cap.className="note"; cap.style.marginTop="12px";
  cap.innerHTML=`The highlighted row is the tolerance used throughout this page.
    At the conservative end the optimizer holds bonds and dividend funds; at the
    aggressive end it concentrates into the highest-return names it is allowed.`;
  ssec.appendChild(cap);

  // ---------- findings ----------
  const st=DATA.statistics, ht=DATA.monte_carlo.horizon_tails;
  const fsec2=section("findings","What the build taught me",
    "Two results I did not expect",
    `<div class="finding">
      <span class="tag">Finding 01 &middot; Optimization</span>
      <h4>Markowitz is an error maximizer</h4>
      <p>Run on raw sample estimates, the optimizer put the entire
      recommendation into the four names that happened to return 116–131%
      annualised in the estimation window, and reported a 124% expected return.
      It cannot distinguish a genuinely high expected return from a lucky one,
      so it concentrates on whichever estimate is noisiest in a favourable
      direction.</p>
      <p>Shrinking the means toward a common anchor
      (${pct(st.mean_shrinkage,0)} intensity) and the covariance toward constant
      correlation cut the covariance condition number from
      ${st.cond_naive.toLocaleString()} to ${st.cond_robust.toLocaleString()} and
      produced a recommendation that holds ${rec.n_holdings} positions instead of
      four. The fix is not a better solver — it is admitting the inputs are
      estimates.</p>
    </div>
    <div class="finding">
      <span class="tag">Finding 02 &middot; Risk</span>
      <h4>Fat tails matter far less over a year than over a day</h4>
      <p>All ${st.n_reject_normal} assets reject the normal distribution, with a
      median fitted ${st.median_t_df.toFixed(1)} degrees of freedom — so I
      expected the fat-tailed simulation to produce a much worse VaR. It barely
      moved: ${(ht[0].ratio).toFixed(2)}× worse at a one-day horizon, falling to
      ${(ht[ht.length-1].ratio).toFixed(2)}× over a year.</p>
      <p>That is the Central Limit Theorem doing its work. A one-year return is
      a sum of 252 daily draws, and sums of independent heavy-tailed variables
      with finite variance converge toward normality. Daily fat tails dominate
      short-horizon risk and wash out at long ones. The real long-horizon danger
      is not fat tails but <em>dependence</em> — volatility clustering,
      correlations rising together in a crash — which an independent-draw
      simulation does not model and therefore understates.</p>
    </div>`);

  // ---------- limitations ----------
  section("limits","Honest limits","What this does not tell you",
    `<ul class="plain">
      <li><b>The window is short and flattering.</b> ${m.n_days} trading days
      covering a strong market. Expected returns estimated from it are
      backward-looking, and shrinkage reduces that problem without solving it.</li>
      <li><b>Five holdings are missing.</b> Positions with under 400 days of
      price history were excluded, so ${pct(1-DATA.universe.coverage,0)} of
      current portfolio value is not modelled.</li>
      <li><b>Returns are assumed independent.</b> No volatility clustering, no
      correlations that rise in a crash — which is precisely when they do.</li>
      <li><b>No costs.</b> Rebalancing to the recommendation would incur spreads
      and taxes that the comparison ignores.</li>
      <li><b>This is coursework, not advice.</b> It is a demonstration of method
      on a portfolio that happens to be mine.</li>
    </ul>`);

  // ---------- footer ----------
  const f=document.createElement("footer");
  f.className="wrapfoot";
  f.innerHTML=`<div class="col">Built over twelve weeks consolidating IEMS 302,
    CS 217 and CivEnv 205. Data layer in SQLite, optimization in CVXPY,
    everything precomputed in Python and rendered as a static page.
    Generated ${m.generated}.</div>`;
  document.querySelector(".wrap").appendChild(f);
})();
</script>
</body>
</html>
"""


def build():
    with open(JSON_PATH) as fh:
        data = json.load(fh)
    payload = "<script>const DATA = " + json.dumps(data, separators=(",", ":")) + ";</script>"
    html = TEMPLATE_HEAD + payload + TEMPLATE_TAIL
    with open(OUT_PATH, "w") as fh:
        fh.write(html)
    print(f"wrote {OUT_PATH}  ({os.path.getsize(OUT_PATH)/1024:.1f} KB, self-contained)")
    return OUT_PATH


if __name__ == "__main__":
    build()
