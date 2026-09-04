#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Turn day-recap.json + all-time-curve.json into the finished trading-progress.html.

Pure stdlib, no Claude/skill dependency — this is the same file every run: read
build_recap.py's two JSON outputs, drop them into report_template.html (which sits
next to this file), write the result. The only judgement call this script does not
make is the investigation callouts at the top of the page (a reset write-off found,
a stale carried position dropped, and so on) — those are supplied as --notes, because
deciding what happened to the account's history is not something a template can do.

Usage:
    python render_report.py DAY_RECAP.json ALL_TIME_CURVE.json OUTPUT.html \
        [--notes notes.json]

notes.json (optional) is a JSON array of {"title": str, "body": str (may contain
simple HTML), "tone": "info"|"critical"}, rendered as callout boxes above the KPI
row, in order. Omit it (or pass an empty array) for a plain report with no narrative.
"""
import argparse
import json
import os
import re
import sys


def main():
    p = argparse.ArgumentParser()
    p.add_argument("day_recap_json")
    p.add_argument("all_time_curve_json")
    p.add_argument("output_html")
    p.add_argument("--notes", help="path to a JSON array of callout notes (see module docstring)")
    args = p.parse_args()

    with open(args.day_recap_json, encoding="utf-8") as fh:
        day_recap = json.load(fh)
    with open(args.all_time_curve_json, encoding="utf-8") as fh:
        curve = json.load(fh)
    notes = []
    if args.notes:
        with open(args.notes, encoding="utf-8") as fh:
            notes = json.load(fh)

    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_template.html")
    with open(template_path, encoding="utf-8") as fh:
        html = fh.read()

    def inject(marker, payload):
        needle = "__{}__".format(marker)
        if needle not in html:
            sys.exit("template is missing the {} placeholder".format(needle))
        return html.replace(needle, json.dumps(payload, ensure_ascii=False, separators=(",", ":")), 1)

    html = inject("DAY_RECAP_JSON", day_recap)
    html = inject("CURVE_JSON", curve)
    html = inject("NOTES_JSON", notes)

    with open(args.output_html, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("wrote {} ({} trades, {} tickers, {} notes)".format(
        args.output_html, len(curve.get("trades", [])), len(curve.get("tickers", [])), len(notes)))


if __name__ == "__main__":
    main()
