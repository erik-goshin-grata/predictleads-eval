# PredictLeads News Events Pull

Pulls PredictLeads News Events for these categories:

- `acquires`
- `merges_with`
- `sells_assets_to`
- `spins_off_company`
- `spins_off_division`

Default date window: `2026-06-15` through `2026-06-17`, inclusive, using the event `found_at` timestamp.

## Run Locally

```bash
export PL_KEY="your_api_key"
export PL_TOKEN="your_api_token"
python3 fetch_news_events.py
```

## GitHub Actions

Pass GitHub Secrets into environment variables before running the script:

```yaml
env:
  PL_KEY: ${{ secrets.PL_KEY }}
  PL_TOKEN: ${{ secrets.PL_TOKEN }}
run: python3 PredictLeads/fetch_news_events.py
```

## Outputs

Files are written to `PredictLeads/output/`:

- `news_events_raw_api_responses_2026-06-15_to_2026-06-17.json`
- `news_events_2026-06-15_to_2026-06-17.csv` - readable export without `source_body_lite`
- `news_events_2026-06-15_to_2026-06-17.tsv` - full export with `source_body_lite` preserved
- `news_events_readable_2026-06-15_to_2026-06-17.tsv` - readable TSV without `source_body_lite`
- `news_events_full_review_2026-06-15_to_2026-06-17.tsv` - full review TSV with line breaks escaped
- `category_counts_2026-06-15_to_2026-06-17.csv`

The full TSV includes the `source_body_lite` column. If PredictLeads returns article text as `body`, the script maps it into `source_body_lite` and preserves the full value. Use the CSV or readable TSV for spreadsheet review.
Use the full review TSV when you want to inspect story bodies without embedded line breaks disrupting the row layout.
