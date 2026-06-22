#!/usr/bin/env python3
"""Pull PredictLeads News Events and export raw JSON, CSV, and TSV."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any


API_URL = "https://predictleads.com/api/v3/discover/news_events"
DEFAULT_CATEGORIES = [
    "acquires",
    "merges_with",
    "sells_assets_to",
    "spins_off_company",
    "spins_off_division",
]
DEFAULT_START_DATE = "2026-06-15"
DEFAULT_END_DATE = "2026-06-17"
DEFAULT_LIMIT = 1000
DEFAULT_MAX_PAGES = 100

EVENT_COLUMNS = [
    "id",
    "type",
    "category",
    "summary",
    "found_at",
    "confidence",
    "article_sentence",
    "planning",
    "amount",
    "amount_normalized",
    "assets",
    "assets_tags",
    "award",
    "contact",
    "division",
    "effective_date",
    "event",
    "financing_type",
    "financing_type_normalized",
    "financing_type_tags",
    "headcount",
    "job_title",
    "job_title_tags",
    "location",
    "location_data",
    "product",
    "product_data",
    "product_tags",
    "recognition",
    "vulnerability",
    "company1_id",
    "company1_name",
    "company1_domain",
    "company1_ticker",
    "company2_id",
    "company2_name",
    "company2_domain",
    "company2_ticker",
    "most_relevant_source_id",
    "source_url",
    "source_title",
    "source_published_at",
    "source_author",
    "source_image_url",
    "source_body_lite",
]
READABLE_COLUMNS = [column for column in EVENT_COLUMNS if column != "source_body_lite"]
ARTICLE_COLUMNS = [
    "event_id",
    "category",
    "source_title",
    "source_url",
    "source_body_lite",
    "summary",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pull PredictLeads News Events for a date range and export JSON/CSV/TSV."
    )
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument(
        "--categories",
        default=",".join(DEFAULT_CATEGORIES),
        help="Comma-separated PredictLeads News Event categories.",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parent / "output"),
        help="Directory where output files will be written.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the first request URL and exit without credentials or API calls.",
    )
    return parser.parse_args()


def get_credentials() -> tuple[str, str]:
    api_key = os.environ.get("PL_KEY")
    api_token = os.environ.get("PL_TOKEN")

    missing = [name for name, value in (("PL_KEY", api_key), ("PL_TOKEN", api_token)) if not value]
    if missing:
        raise SystemExit(
            "Missing environment variable(s): "
            + ", ".join(missing)
            + ". In GitHub Actions, pass secrets into env as PL_KEY and PL_TOKEN."
        )

    return api_key, api_token


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"Invalid date {value!r}. Use YYYY-MM-DD.") from exc


def parse_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None

    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def build_url(categories: list[str], page: int, limit: int) -> str:
    query = urllib.parse.urlencode(
        {
            "categories": ",".join(categories),
            "page": page,
            "limit": limit,
        },
        safe=",",
    )
    return f"{API_URL}?{query}"


def fetch_json(url: str, api_key: str, api_token: str, retries: int = 3) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "predictleads-news-events-export/1.0",
        "X-Api-Key": api_key,
        "X-Api-Token": api_token,
    }

    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:1000]
            if exc.code in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(f"PredictLeads API returned HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            if attempt < retries:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(f"PredictLeads API request failed: {exc}") from exc

    raise RuntimeError("PredictLeads API request failed after retries.")


def get_relationship_id(item: dict[str, Any], relationship_name: str) -> str:
    relationship = item.get("relationships", {}).get(relationship_name, {})
    data = relationship.get("data")

    if isinstance(data, dict):
        return str(data.get("id") or "")
    if isinstance(data, list):
        return ";".join(str(entry.get("id", "")) for entry in data if isinstance(entry, dict))
    return ""


def build_included_index(raw_pages: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    included_index: dict[tuple[str, str], dict[str, Any]] = {}
    for page in raw_pages:
        for item in page.get("included", []) or []:
            item_type = item.get("type")
            item_id = item.get("id")
            if item_type and item_id:
                included_index[(str(item_type), str(item_id))] = item
    return included_index


def json_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, bool)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def single_line_cell(value: Any) -> str:
    return json_cell(value).replace("\r", "\\r").replace("\n", "\\n").replace("\t", " ")


def company_fields(
    included_index: dict[tuple[str, str], dict[str, Any]], company_id: str, prefix: str
) -> dict[str, str]:
    company = included_index.get(("company", company_id), {}) if company_id else {}
    attributes = company.get("attributes", {}) if isinstance(company, dict) else {}
    return {
        f"{prefix}_id": company_id,
        f"{prefix}_name": json_cell(attributes.get("company_name")),
        f"{prefix}_domain": json_cell(attributes.get("domain")),
        f"{prefix}_ticker": json_cell(attributes.get("ticker")),
    }


def source_fields(
    included_index: dict[tuple[str, str], dict[str, Any]], source_id: str
) -> dict[str, str]:
    source = (
        included_index.get(("news_article", source_id), {})
        or included_index.get(("news_article_lite", source_id), {})
        if source_id
        else {}
    )
    attributes = source.get("attributes", {}) if isinstance(source, dict) else {}
    source_body_lite = (
        attributes.get("source_body_lite")
        or attributes.get("body_lite")
        or attributes.get("body")
    )
    return {
        "most_relevant_source_id": source_id,
        "source_url": json_cell(attributes.get("url")),
        "source_title": json_cell(attributes.get("title")),
        "source_published_at": json_cell(attributes.get("published_at")),
        "source_author": json_cell(attributes.get("author")),
        "source_image_url": json_cell(attributes.get("image_url")),
        "source_body_lite": json_cell(source_body_lite),
    }


def flatten_event(
    item: dict[str, Any], included_index: dict[tuple[str, str], dict[str, Any]]
) -> dict[str, str]:
    attributes = item.get("attributes", {}) or {}
    row = {column: "" for column in EVENT_COLUMNS}
    row["id"] = json_cell(item.get("id"))
    row["type"] = json_cell(item.get("type"))

    for column in EVENT_COLUMNS:
        if column in attributes:
            row[column] = json_cell(attributes.get(column))

    company1_id = get_relationship_id(item, "company1")
    company2_id = get_relationship_id(item, "company2")
    source_id = get_relationship_id(item, "most_relevant_source")

    row.update(company_fields(included_index, company1_id, "company1"))
    row.update(company_fields(included_index, company2_id, "company2"))
    row.update(source_fields(included_index, source_id))
    return row


def article_row(row: dict[str, str]) -> dict[str, str]:
    return {
        "event_id": row.get("id", ""),
        "category": row.get("category", ""),
        "source_title": single_line_cell(row.get("source_title", "")),
        "source_url": row.get("source_url", ""),
        "source_body_lite": single_line_cell(row.get("source_body_lite", "")),
        "summary": single_line_cell(row.get("summary", "")),
    }


def is_in_date_range(item: dict[str, Any], start_at: datetime, end_before: datetime) -> bool:
    found_at = parse_datetime((item.get("attributes") or {}).get("found_at"))
    return bool(found_at and start_at <= found_at < end_before)


def page_is_before_start(page: dict[str, Any], start_at: datetime) -> bool:
    found_dates = [
        found_at
        for item in page.get("data", []) or []
        if (found_at := parse_datetime((item.get("attributes") or {}).get("found_at")))
    ]
    return bool(found_dates and max(found_dates) < start_at)


def write_rows(
    path: Path, rows: list[dict[str, str]], delimiter: str, fieldnames: list[str]
) -> None:
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(
            output_file,
            fieldnames=fieldnames,
            delimiter=delimiter,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_counts(path: Path, categories: list[str], counts: Counter[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.writer(output_file, lineterminator="\n")
        writer.writerow(["category", "count"])
        for category in categories:
            writer.writerow([category, counts.get(category, 0)])
        writer.writerow(["total", sum(counts.values())])


def main() -> int:
    args = parse_args()
    categories = [category.strip() for category in args.categories.split(",") if category.strip()]
    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)

    if end_date < start_date:
        raise SystemExit("--end-date must be on or after --start-date.")
    if not categories:
        raise SystemExit("At least one category is required.")
    if not 1 <= args.limit <= 1000:
        raise SystemExit("--limit must be between 1 and 1000.")

    start_at = datetime.combine(start_date, dt_time.min, tzinfo=timezone.utc)
    end_before = datetime.combine(end_date + timedelta(days=1), dt_time.min, tzinfo=timezone.utc)
    output_dir = Path(args.output_dir)
    date_label = f"{start_date.isoformat()}_to_{end_date.isoformat()}"

    first_url = build_url(categories, page=1, limit=args.limit)
    if args.dry_run:
        print(first_url)
        return 0

    api_key, api_token = get_credentials()
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_pages: list[dict[str, Any]] = []
    filtered_events_by_id: dict[str, dict[str, Any]] = {}

    for page_number in range(1, args.max_pages + 1):
        url = build_url(categories, page=page_number, limit=args.limit)
        page = fetch_json(url, api_key, api_token)
        raw_pages.append(page)

        data = page.get("data", []) or []
        for item in data:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "")
            if item_id and is_in_date_range(item, start_at, end_before):
                filtered_events_by_id[item_id] = item

        print(f"Fetched page {page_number}: {len(data)} records", file=sys.stderr)

        if not data or page_is_before_start(page, start_at):
            break
    else:
        print(
            f"Stopped after --max-pages={args.max_pages}; increase it if older pages are needed.",
            file=sys.stderr,
        )

    filtered_events = list(filtered_events_by_id.values())
    included_index = build_included_index(raw_pages)
    rows = [flatten_event(item, included_index) for item in filtered_events]
    counts = Counter(row["category"] for row in rows)

    raw_json_path = output_dir / f"news_events_raw_api_responses_{date_label}.json"
    csv_path = output_dir / f"news_events_{date_label}.csv"
    tsv_path = output_dir / f"news_events_{date_label}.tsv"
    readable_tsv_path = output_dir / f"news_events_readable_{date_label}.tsv"
    articles_tsv_path = output_dir / f"news_events_articles_{date_label}.tsv"
    counts_path = output_dir / f"category_counts_{date_label}.csv"

    with raw_json_path.open("w", encoding="utf-8") as output_file:
        json.dump(raw_pages, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")

    write_rows(csv_path, rows, delimiter=",", fieldnames=READABLE_COLUMNS)
    write_rows(tsv_path, rows, delimiter="\t", fieldnames=EVENT_COLUMNS)
    write_rows(readable_tsv_path, rows, delimiter="\t", fieldnames=READABLE_COLUMNS)
    write_rows(
        articles_tsv_path,
        [article_row(row) for row in rows],
        delimiter="\t",
        fieldnames=ARTICLE_COLUMNS,
    )
    write_counts(counts_path, categories, counts)

    print("\nCategory counts")
    for category in categories:
        print(f"{category}\t{counts.get(category, 0)}")
    print(f"total\t{sum(counts.values())}")

    print("\nOutput files")
    print(raw_json_path)
    print(csv_path)
    print(tsv_path)
    print(readable_tsv_path)
    print(articles_tsv_path)
    print(counts_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
