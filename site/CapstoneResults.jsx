/**
 * Drop-in React component for a Next.js / Vercel portfolio site.
 * ==============================================================
 * Renders the capstone results from the precomputed JSON. No chart library:
 * the SVGs are hand-drawn, so this adds zero dependencies and no bundle weight.
 *
 * Setup
 * -----
 *   1. Copy `capstone.json` into your site's `public/` directory.
 *   2. Copy this file into `components/`.
 *   3. Use it from a page:
 *
 *        // app/quant/page.jsx
 *        import CapstoneResults from "@/components/CapstoneResults";
 *        import data from "@/public/capstone.json";
 *        export default function Page() {
 *          return <CapstoneResults data={data} />;
 *        }
 *
 * Regenerate the JSON after any change to the model:
 *   python projects/11-capstone-platform/export_results.py
 *
 * Styling assumes Tailwind. If you do not use Tailwind, the className strings
 * are the only thing to replace — no logic depends on them.
 */
import React, { useMemo } from "react";

const pct = (v, d = 1) => `${(v * 100).toFixed(d)}%`;

/* ------------------------------------------------------------------ */
/* Scorecard                                                           */
/* ------------------------------------------------------------------ */
function Scorecard({ data }) {
  const rec = data.portfolios.recommended;
  const cur = data.portfolios.current;
  const mt = data.monte_carlo.recommended_t;
  const ct = data.monte_carlo.current_t;

  const cards = [
    { k: "Expected return", cur: pct(cur.ret), rec: pct(rec.ret),
      note: "Lower — deliberately" },
    { k: "Volatility", cur: pct(cur.vol), rec: pct(rec.vol),
      note: `${((1 - rec.vol / cur.vol) * 100).toFixed(0)}% less risk`, good: true },
    { k: "Sharpe ratio", cur: cur.sharpe.toFixed(2), rec: rec.sharpe.toFixed(2),
      note: `+${((rec.sharpe / cur.sharpe - 1) * 100).toFixed(0)}% per unit of risk`, good: true },
    { k: "P(loss > 10%)", cur: pct(ct.p_loss_10), rec: pct(mt.p_loss_10),
      note: `${((1 - mt.p_loss_10 / ct.p_loss_10) * 100).toFixed(0)}% less likely`, good: true },
    { k: "1% VaR (1 year)", cur: pct(ct.var_1), rec: pct(mt.var_1),
      note: "Worst-case tail, cut by half", good: true },
    { k: "Certainty equivalent", cur: cur.ce.toFixed(1), rec: rec.ce.toFixed(1),
      note: `+${(rec.ce - cur.ce).toFixed(1)} on a base of 100`, good: true },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-px bg-neutral-200 dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-800 rounded-xl overflow-hidden">
      {cards.map((c) => (
        <div key={c.k} className="bg-white dark:bg-neutral-900 p-5">
          <div className="text-[11px] uppercase tracking-widest text-neutral-500 font-mono mb-3">
            {c.k}
          </div>
          <div className="flex items-baseline justify-between">
            <span className="text-xs text-neutral-500">Current</span>
            <span className="font-mono tabular-nums text-lg font-semibold text-sky-700 dark:text-sky-300">
              {c.cur}
            </span>
          </div>
          <div className="flex items-baseline justify-between mt-1.5">
            <span className="text-xs text-neutral-500">Recommended</span>
            <span className="font-mono tabular-nums text-lg font-semibold text-amber-700 dark:text-amber-400">
              {c.rec}
            </span>
          </div>
          <div className={`text-xs mt-3 pt-2.5 border-t border-neutral-200 dark:border-neutral-800 font-semibold ${
            c.good ? "text-emerald-700 dark:text-emerald-400" : "text-neutral-500"}`}>
            {c.note}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Efficient frontier                                                  */
/* ------------------------------------------------------------------ */
function Frontier({ data }) {
  const { pathD, marks, ticks, W, H, P } = useMemo(() => {
    const W = 880, H = 470, P = { t: 24, r: 26, b: 52, l: 66 };
    const pts = data.frontier.robust;
    const rec = data.portfolios.recommended;
    const cur = data.portfolios.current;
    const mv = data.portfolios.min_variance;
    const x1 = Math.max(...pts.map((p) => p.vol), cur.vol) * 1.08;
    const y1 = Math.max(...pts.map((p) => p.ret), cur.ret) * 1.1;
    const X = (v) => P.l + (v / x1) * (W - P.l - P.r);
    const Y = (v) => H - P.b - (v / y1) * (H - P.t - P.b);
    return {
      W, H, P,
      pathD: pts.map((p, i) => `${i ? "L" : "M"}${X(p.vol)} ${Y(p.ret)}`).join(" "),
      marks: {
        rec: { x: X(rec.vol), y: Y(rec.ret) },
        cur: { x: X(cur.vol), y: Y(cur.ret) },
        mv: { x: X(mv.vol), y: Y(mv.ret) },
      },
      ticks: {
        y: Array.from({ length: 6 }, (_, i) => ({ v: (y1 * i) / 5, y: Y((y1 * i) / 5) })),
        x: Array.from({ length: 6 }, (_, i) => ({ v: (x1 * i) / 5, x: X((x1 * i) / 5) })),
      },
    };
  }, [data]);

  return (
    <div className="overflow-x-auto rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-4">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto min-w-[520px]" role="img">
        <title>Efficient frontier with current and recommended portfolios</title>
        {ticks.y.map((t, i) => (
          <g key={i}>
            <line x1={P.l} x2={W - P.r} y1={t.y} y2={t.y}
                  className="stroke-neutral-200 dark:stroke-neutral-800" strokeWidth="1" />
            <text x={P.l - 10} y={t.y + 4} textAnchor="end"
                  className="fill-neutral-500 font-mono" fontSize="11">
              {(t.v * 100).toFixed(0)}%
            </text>
          </g>
        ))}
        {ticks.x.map((t, i) => (
          <text key={i} x={t.x} y={H - P.b + 20} textAnchor="middle"
                className="fill-neutral-500 font-mono" fontSize="11">
            {(t.v * 100).toFixed(0)}%
          </text>
        ))}
        <path d={pathD} fill="none" strokeWidth="2"
              className="stroke-neutral-900 dark:stroke-neutral-100" />
        <line x1={marks.cur.x} y1={marks.cur.y} x2={marks.rec.x} y2={marks.rec.y}
              className="stroke-neutral-400" strokeWidth="1.4" strokeDasharray="5 5" />
        <circle cx={marks.mv.x} cy={marks.mv.y} r="5.5"
                className="fill-white dark:fill-neutral-900 stroke-neutral-900 dark:stroke-neutral-100"
                strokeWidth="2" />
        <circle cx={marks.cur.x} cy={marks.cur.y} r="8"
                className="fill-sky-600 dark:fill-sky-400" stroke="white" strokeWidth="2" />
        <circle cx={marks.rec.x} cy={marks.rec.y} r="8"
                className="fill-amber-600 dark:fill-amber-400" stroke="white" strokeWidth="2" />
        <text x={marks.cur.x - 12} y={marks.cur.y + 4} textAnchor="end"
              className="fill-sky-700 dark:fill-sky-300 font-semibold" fontSize="12.5">Current</text>
        <text x={marks.rec.x} y={marks.rec.y - 15} textAnchor="middle"
              className="fill-amber-700 dark:fill-amber-400 font-semibold" fontSize="12.5">Recommended</text>
        <text x={(P.l + W - P.r) / 2} y={H - 10} textAnchor="middle"
              className="fill-neutral-500" fontSize="12">Annualised volatility</text>
      </svg>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Allocation comparison                                               */
/* ------------------------------------------------------------------ */
function Allocation({ data }) {
  const rec = data.portfolios.recommended.weights;
  const cur = data.portfolios.current.weights;
  const keys = useMemo(() => {
    const all = Array.from(new Set([...Object.keys(rec), ...Object.keys(cur)]));
    return all.sort((a, b) => ((rec[b] || 0) + (cur[b] || 0)) - ((rec[a] || 0) + (cur[a] || 0)));
  }, [rec, cur]);
  const max = Math.max(...keys.map((k) => Math.max(rec[k] || 0, cur[k] || 0)));

  return (
    <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-5">
      <div className="flex gap-5 mb-4 text-sm text-neutral-500">
        <span className="flex items-center gap-2">
          <i className="w-3 h-3 rounded-sm bg-amber-600 dark:bg-amber-400 inline-block" />Recommended
        </span>
        <span className="flex items-center gap-2">
          <i className="w-3 h-3 rounded-sm bg-sky-600 dark:bg-sky-400 inline-block" />Current
        </span>
      </div>
      <div className="flex flex-col gap-3">
        {keys.map((k) => (
          <div key={k} className="grid grid-cols-[3.5rem_1fr] gap-3 items-center">
            <span className="font-mono text-xs font-semibold text-right">{k}</span>
            <div className="flex flex-col gap-1">
              <Bar w={(rec[k] || 0) / max} label={rec[k] ? pct(rec[k], 0) : ""}
                   cls="bg-amber-600 dark:bg-amber-400" />
              <Bar w={(cur[k] || 0) / max} label={cur[k] ? pct(cur[k], 0) : ""}
                   cls="bg-sky-600 dark:bg-sky-400" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Bar({ w, label, cls }) {
  return (
    <div className="flex items-center gap-2">
      <div className={`h-2.5 rounded-sm ${cls}`} style={{ width: `${Math.max(w * 100, 0)}%` }} />
      <span className="font-mono text-[11px] text-neutral-500 tabular-nums">{label}</span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Risk-tolerance sweep                                                */
/* ------------------------------------------------------------------ */
function RiskSweep({ data }) {
  const chosen = data.meta.risk_tolerance_pct_of_wealth;
  return (
    <div className="overflow-x-auto rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900">
      <table className="w-full text-sm min-w-[480px]">
        <thead>
          <tr className="text-[11px] uppercase tracking-wider text-neutral-500 font-mono">
            <th className="text-left p-3 font-semibold">Risk tolerance</th>
            <th className="text-right p-3 font-semibold">Return</th>
            <th className="text-right p-3 font-semibold">Volatility</th>
            <th className="text-right p-3 font-semibold">Sharpe</th>
            <th className="text-left p-3 font-semibold">Largest positions</th>
          </tr>
        </thead>
        <tbody>
          {data.risk_sweep.map((r) => (
            <tr key={r.r_fraction}
                className={`border-t border-neutral-200 dark:border-neutral-800 ${
                  Math.abs(r.r_fraction - chosen) < 1e-9 ? "bg-amber-50 dark:bg-amber-950/30" : ""}`}>
              <td className="p-3 font-mono tabular-nums">{pct(r.r_fraction, 0)} of value</td>
              <td className="p-3 text-right font-mono tabular-nums">{pct(r.ret)}</td>
              <td className="p-3 text-right font-mono tabular-nums">{pct(r.vol)}</td>
              <td className="p-3 text-right font-mono tabular-nums">{r.sharpe.toFixed(2)}</td>
              <td className="p-3 font-mono text-xs text-neutral-500">{r.top}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------------------ */
export default function CapstoneResults({ data }) {
  if (!data) return null;
  const m = data.meta;
  return (
    <article className="max-w-5xl mx-auto px-6 py-16 flex flex-col gap-16">
      <header className="flex flex-col gap-4">
        <p className="font-mono text-xs uppercase tracking-[0.14em] text-neutral-500">
          Quant Summer 2026 · Capstone
        </p>
        <h1 className="text-4xl sm:text-5xl font-semibold tracking-tight text-balance">
          What a portfolio is actually worth taking on
        </h1>
        <p className="text-lg text-neutral-500 max-w-2xl">
          A four-layer pipeline that reads a real brokerage history out of SQL,
          measures how badly returns break the normality assumption, traces an
          efficient frontier, and picks one allocation using a risk tolerance
          rather than a hunch.
        </p>
        <div className="flex flex-wrap gap-x-7 gap-y-2 text-xs text-neutral-500 mt-2">
          <span>Window <b className="text-neutral-900 dark:text-neutral-100">{m.window_start} → {m.window_end}</b></span>
          <span>Trading days <b className="text-neutral-900 dark:text-neutral-100">{m.n_days}</b></span>
          <span>Assets <b className="text-neutral-900 dark:text-neutral-100">{m.n_assets}</b></span>
          <span>Values <b className="text-neutral-900 dark:text-neutral-100">{m.value_unit}</b></span>
        </div>
      </header>

      <section className="flex flex-col gap-5">
        <h2 className="text-2xl font-semibold tracking-tight">Same money, materially less risk</h2>
        <Scorecard data={data} />
      </section>

      <section className="flex flex-col gap-5">
        <h2 className="text-2xl font-semibold tracking-tight">The current portfolio sits below the frontier</h2>
        <Frontier data={data} />
      </section>

      <section className="flex flex-col gap-5">
        <h2 className="text-2xl font-semibold tracking-tight">What would actually change</h2>
        <Allocation data={data} />
      </section>

      <section className="flex flex-col gap-5">
        <h2 className="text-2xl font-semibold tracking-tight">The answer depends on risk tolerance</h2>
        <RiskSweep data={data} />
      </section>
    </article>
  );
}
