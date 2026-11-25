"""CLI: nomad-search "question" """

from __future__ import annotations

import argparse
import json
import sys

from nomad_search import __version__, config
from nomad_search.format import format_hits
from nomad_search.search import search_knowledge


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nomad-search",
        description="Search the local Nomad knowledge base (read-only, offline).",
    )
    parser.add_argument("query", nargs="+", help="The question or search phrase")
    parser.add_argument(
        "-k",
        "--top-k",
        type=int,
        default=config.DEFAULT_TOP_K,
        help=f"Number of passages (1-{config.MAX_TOP_K}, default {config.DEFAULT_TOP_K})",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    parser.add_argument("--version", action="version", version=f"nomad-search {__version__}")
    args = parser.parse_args(argv)
    query = " ".join(args.query)
    try:
        hits = search_knowledge(query, args.top_k)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"nomad-search: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"query": config.sanitize_query(query), "hits": hits}, ensure_ascii=False, indent=2))
        return 0
    sys.stdout.write(format_hits(query, hits))
    return 0


if __name__ == "__main__":
    sys.exit(main())
