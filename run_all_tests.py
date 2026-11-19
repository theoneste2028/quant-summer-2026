"""
Repo-wide test runner
=====================
Runs every project's test suite and self-validating demo, from the repo root,
and prints one summary table. Exit code is non-zero if anything failed, so this
doubles as a pre-commit check.

Run:
    python run_all_tests.py            # everything
    python run_all_tests.py --fast     # skip the slow ones (network / 3M rows)
    python run_all_tests.py --list     # show what would run
"""
from __future__ import annotations
import os, re, sys, time, subprocess, argparse

REPO = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(REPO, ".venv", "bin", "python")
if not os.path.exists(PY):
    PY = sys.executable

# (label, project dir, script, args, slow?)
SUITES = [
    ("W1 distribution fitting", "01-distribution-fitting", "test_synthetic.py", [], False),
    ("W2 blackjack",            "02-blackjack-probability", "test_blackjack.py", [], True),
    ("W3 monte carlo pricer",   "03-monte-carlo-pricer", "test_pricer.py", [], True),
    ("W4 options extensions",   "04-options-extensions", "test_options_extensions.py", [], True),
    ("W6 portfolio queries",    "05-portfolio-database", "test_queries.py", [], False),
    ("W6 ACID demos",           "05-portfolio-database", "transactions.py", [], False),
    ("W7 ETL pipeline",         "07-etl-pipeline", "test_etl.py", [], False),
    ("W8 index benchmark",      "08-query-optimization", "test_benchmark.py", [], True),
    ("W9 capital budgeting",    "09-capital-budgeting", "test_capital_budgeting.py", [], False),
    ("W10 decision analysis",   "10-decision-analysis", "test_decision_analysis.py", [], False),
    ("W11 capstone",            "11-capstone-platform", "test_capstone.py", [], True),
    ("W12 research app",        "11-capstone-platform", "test_app.py", [], True),
]

# "N passed, M failed" or the ACID demo's "N/M demonstrations"
COUNT_RE = re.compile(r"(\d+)\s+passed,\s+(\d+)\s+failed")
DEMO_RE = re.compile(r"(\d+)/(\d+)\s+demonstrations")


def run(label, folder, script, args, timeout=1800):
    path = os.path.join(REPO, "projects", folder)
    script_path = os.path.join(path, script)
    if not os.path.exists(script_path):
        return {"label": label, "status": "MISSING", "passed": 0, "failed": 0,
                "seconds": 0.0, "detail": script_path}
    t0 = time.perf_counter()
    try:
        p = subprocess.run([PY, script] + args, cwd=path, capture_output=True,
                           text=True, timeout=timeout)
        out = p.stdout + p.stderr
        rc = p.returncode
    except subprocess.TimeoutExpired:
        return {"label": label, "status": "TIMEOUT", "passed": 0, "failed": 0,
                "seconds": time.perf_counter() - t0, "detail": "exceeded timeout"}
    secs = time.perf_counter() - t0

    passed = failed = 0
    m = COUNT_RE.search(out)
    if m:
        passed, failed = int(m.group(1)), int(m.group(2))
    else:
        d = DEMO_RE.search(out)
        if d:
            passed, failed = int(d.group(1)), int(d.group(2)) - int(d.group(1))

    if rc != 0:
        status = "FAIL"
    elif failed > 0:
        status = "FAIL"
    else:
        status = "OK"
    tail = "\n".join(out.strip().splitlines()[-4:])
    return {"label": label, "status": status, "passed": passed, "failed": failed,
            "seconds": secs, "detail": tail, "rc": rc}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="skip slow suites")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    suites = [s for s in SUITES if not (a.fast and s[4])]
    if a.list:
        for label, folder, script, args, slow in suites:
            print(f"  {label:26} projects/{folder}/{script}"
                  + ("   [slow]" if slow else ""))
        return 0

    print("=" * 78)
    print(f"Running {len(suites)} suites with {PY}")
    print("=" * 78)
    results = []
    for label, folder, script, args, slow in suites:
        print(f"  running {label} ...", flush=True)
        r = run(label, folder, script, args)
        results.append(r)
        print(f"    {r['status']}  {r['passed']} passed, {r['failed']} failed"
              f"  ({r['seconds']:.1f}s)")

    print("\n" + "=" * 78)
    print(f"{'suite':<28}{'status':>9}{'passed':>9}{'failed':>8}{'seconds':>10}")
    print("-" * 78)
    tp = tf = 0
    for r in results:
        tp += r["passed"]; tf += r["failed"]
        print(f"{r['label']:<28}{r['status']:>9}{r['passed']:>9}"
              f"{r['failed']:>8}{r['seconds']:>10.1f}")
    print("-" * 78)
    print(f"{'TOTAL':<28}{'':>9}{tp:>9}{tf:>8}"
          f"{sum(r['seconds'] for r in results):>10.1f}")
    print("=" * 78)

    bad = [r for r in results if r["status"] != "OK"]
    if bad:
        print("\nFAILURES:")
        for r in bad:
            print(f"\n--- {r['label']} ({r['status']}) ---\n{r['detail']}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
