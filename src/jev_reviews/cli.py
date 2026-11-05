"""Command line entry point.

  jev-reviews classify --input data/sample_reviews.csv --output reports/decisions.csv
  jev-reviews classify --sheet                     # Google Sheet in -> decisions tab out
  jev-reviews benchmark                            # Bedrock (+ Jev if TYPESAFE_API_KEY is set)
  jev-reviews benchmark --models bedrock,bedrock:anthropic.claude-haiku-5-5
  jev-reviews serve                                # web UI at http://127.0.0.1:8000
  jev-reviews eval                                 # quality gate on labeled data; exit 1 on failure
  jev-reviews doctor                               # check credentials, model access, tracing

Model specs: "bedrock" (BEDROCK_MODEL_ID), "bedrock:<model id>", or "jev".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import io
from .config import get_settings
from .classifiers import default_models, make_classifier
from .pipeline import benchmark, run


def cmd_classify(args) -> int:
    s = get_settings()
    threshold = args.threshold if args.threshold is not None else s.confidence_threshold
    reviews = io.read_sheet(s) if args.sheet else io.read_csv(args.input)
    clf = make_classifier(args.model, s)
    decisions, errors = run(clf, reviews, workers=args.workers)
    texts = {r.review_id: r.text for r in reviews}
    rows = [{"text": texts[d.review_id], **d.to_row(threshold)} for d in decisions]
    if args.sheet:
        io.write_sheet(s, rows)
        print(f"Wrote {len(rows)} decisions to sheet tab '{s.sheet_output_tab}'.")
    else:
        io.write_csv(args.output, rows)
        print(f"Wrote {len(rows)} decisions to {args.output}.")
    flagged = sum(r["needs_review"] for r in rows)
    print(f"{flagged}/{len(rows)} flagged for human review (min confidence < {threshold}).")
    if errors:
        print(f"{len(errors)} errors:", file=sys.stderr)
        for e in errors[:10]:
            print(f"  {e['review_id']}: {e['error']}", file=sys.stderr)
    return 1 if errors and not decisions else 0


def cmd_benchmark(args) -> int:
    s = get_settings()
    reviews = io.read_csv(args.input)
    specs = [m for m in (args.models or default_models(s)).split(",") if m.strip()]
    shared: dict[type, object] = {}  # reuse one client per classifier type
    clfs = []
    for spec in specs:
        clf = make_classifier(spec, s)
        if type(clf) in shared:
            clf.client = shared[type(clf)]
        else:
            shared[type(clf)] = getattr(clf, "client", None)
        clfs.append(clf)
    threshold = args.threshold if args.threshold is not None else s.confidence_threshold
    report = benchmark(clfs, reviews, args.out_dir, threshold, workers=args.workers)
    print(summarize(report))
    print(f"\nFull report: {Path(args.out_dir) / 'benchmark.json'}")
    return 0


def summarize(report: dict) -> str:
    lines = [f"Benchmark on {report['n_reviews']} labeled reviews", ""]
    header = f"{'metric':<28}" + "".join(f"{n:>16}" for n in report["models"])
    lines.append(header)
    lines.append("-" * len(header))

    def row(label, fn):
        cells = []
        for m in report["models"].values():
            try:
                cells.append(fn(m["metrics"]))
            except Exception:
                cells.append("-")
        lines.append(f"{label:<28}" + "".join(f"{c:>16}" for c in cells))

    row("all-fields accuracy", lambda m: f"{m['all_fields_accuracy']:.1%}")
    for f in ("topic", "sentiment", "defect", "refund_request"):
        row(f"{f} accuracy", lambda m, f=f: f"{m['per_field'][f]['accuracy']:.1%}")
    row("topic macro-F1", lambda m: f"{m['per_field']['topic']['macro_f1']:.3f}")
    row("ECE (lower=better)", lambda m: f"{m['overall_ece']:.3f}")
    row("Brier (lower=better)", lambda m: f"{m['overall_brier']:.3f}")
    row("latency p50 (ms)", lambda m: f"{m['latency_ms']['p50']:.0f}")
    row("latency p95 (ms)", lambda m: f"{m['latency_ms']['p95']:.0f}")
    row("cost / 1k reviews (USD)", lambda m: f"${m['cost']['per_1k_reviews_usd']:.4f}")
    errs = {n: len(m["errors"]) for n, m in report["models"].items()}
    lines.append("")
    lines.append(f"errors: {json.dumps(errs)}")
    return "\n".join(lines)


def cmd_eval(args) -> int:
    from .evals import DEFAULT_DATASETS, format_report, load_dataset, load_gates, run_eval

    s = get_settings()
    threshold = args.threshold if args.threshold is not None else s.confidence_threshold
    data = load_dataset(args.data.split(",") if args.data else DEFAULT_DATASETS)
    gates = load_gates(args.gates)
    clf = make_classifier(args.model, s)
    result = run_eval(clf, data, threshold, gates, workers=args.workers)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str))
    print(format_report(result))
    print(f"\nFull results: {out}")
    return 0 if result["passed"] else 1


def cmd_doctor(args) -> int:
    import os

    from .schema import Review
    from .tracing import setup_tracing

    s = get_settings()
    ok = True
    print(f"region          {s.aws_region}")
    print(f"model           {s.bedrock_model_id}")
    if os.getenv("AWS_BEARER_TOKEN_BEDROCK"):
        print("auth            Bedrock API key (AWS_BEARER_TOKEN_BEDROCK)")
    else:
        try:
            import boto3

            ident = boto3.client("sts", region_name=s.aws_region).get_caller_identity()
            print(f"auth            AWS credentials: {ident['Arn']}")
        except Exception as e:
            print(f"auth            FAIL: no Bedrock API key and no usable AWS credentials ({e})")
            ok = False
    tracing = setup_tracing()
    print(f"tracing         {'Phoenix at ' + os.environ['PHOENIX_COLLECTOR_ENDPOINT'] if tracing else 'off (set PHOENIX_COLLECTOR_ENDPOINT)'}")
    print(f"jev             {'enabled' if s.jev_enabled else 'off (no TYPESAFE_API_KEY)'}")
    if not ok:
        return 1
    print("test call       ", end="", flush=True)
    try:
        d = make_classifier(args.model, s).classify(
            Review("doctor", "The zipper broke after two days. I want my money back."))
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        print(f"FAIL\n  {msg[:400]}")
        if "bedrock-mantle:CreateInference" in msg:
            print("  -> Your AWS identity needs the bedrock-mantle:CreateInference permission "
                  "(see README, setup step 2), or set AWS_BEARER_TOKEN_BEDROCK.")
        elif "403" in msg or "401" in msg:
            print("  -> Check the API key / region, and that model access is enabled in the Bedrock console.")
        return 1
    print(f"OK  {d.topic}/{d.sentiment} defect={d.defect} refund={d.refund_request} "
          f"min_conf={d.min_confidence():.2f}  {d.latency_ms:.0f} ms  ${d.cost_usd:.5f}")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    print(f"Review Decisions UI → http://{args.host}:{args.port}")
    uvicorn.run("jev_reviews.api:get_app", factory=True, host=args.host, port=args.port, reload=args.reload)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="jev-reviews")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("classify", help="Classify reviews into typed decisions")
    src = c.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", help="CSV with review_id,text columns")
    src.add_argument("--sheet", action="store_true", help="Read from / write to the Google Sheet in .env")
    c.add_argument("--output", default="reports/decisions.csv")
    c.add_argument("--model", default="bedrock", help="bedrock | bedrock:<model id> | jev")
    c.add_argument("--threshold", type=float)
    c.add_argument("--workers", type=int, default=8)
    c.set_defaults(func=cmd_classify)

    b = sub.add_parser("benchmark", help="Accuracy / calibration / cost benchmark on labeled data")
    b.add_argument("--input", default="data/sample_reviews.csv")
    b.add_argument("--models", help="Comma-separated specs (default: bedrock, plus jev if TYPESAFE_API_KEY is set)")
    b.add_argument("--out-dir", default="reports")
    b.add_argument("--threshold", type=float)
    b.add_argument("--workers", type=int, default=8)
    b.set_defaults(func=cmd_benchmark)

    e = sub.add_parser("eval", help="Quality gate on labeled data (exit 1 if any check fails)")
    e.add_argument("--model", default="bedrock", help="bedrock | bedrock:<model id> | jev")
    e.add_argument("--data", help="Comma-separated labeled CSVs (default: sample + edge cases)")
    e.add_argument("--gates", default="evals/gates.json")
    e.add_argument("--out", default="reports/eval.json")
    e.add_argument("--threshold", type=float)
    e.add_argument("--workers", type=int, default=8)
    e.set_defaults(func=cmd_eval)

    dr = sub.add_parser("doctor", help="Check credentials, model access and tracing with one test call")
    dr.add_argument("--model", default="bedrock")
    dr.set_defaults(func=cmd_doctor)

    v = sub.add_parser("serve", help="Run the web UI + API")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8000)
    v.add_argument("--reload", action="store_true")
    v.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
