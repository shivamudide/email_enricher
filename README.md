# Email Enricher

This mini-project demonstrates how to automatically populate missing email addresses in a contact list using simple heuristics.

## Project Structure

```
emails/
├── environment.yml     # Conda environment definition
├── sample_data.csv     # Example dataset containing missing emails
├── email_enricher.py   # Main script that fills in empty emails
└── README.md           # This file
```

## Setup

1.  Create the Conda environment and activate it:

    ```bash
    conda env create -f environment.yml
    conda activate email_enricher
    ```

2.  (Optional) Install the environment with **mamba** for faster resolution:

    ```bash
    mamba env create -f environment.yml
    ```

3.  (Optional) Set a Hunter.io API key for higher-confidence pattern discovery (free plan ⇒ 25 requests/month):

    ```bash
    export HUNTER_API_KEY=your_key_here
    ```

   Alternatively, create a `.env` file in the repo root with the same variable.

## Usage

Run the script on any CSV or Excel file that contains **at minimum** the following column names (case-insensitive):

* `contact_first_name`
* `contact_last_name`
* `contact_email` – may be empty / NaN when you want it filled
* `account_website` – the company domain or website (e.g. *firstsupply.com*)

```bash
python email_enricher.py <input_file> [output_file] [--changes <changes_file>]
```

Argument details:

| Position / Flag | Required | Description |
|-----------------|----------|-------------|
| `<input_file>`  | ✔️       | Original spreadsheet you want to enrich. Supports **.csv**, **.xls**, **.xlsx**. |
| `[output_file]` | ❓        | Where to write the *full* enriched dataset. Defaults to `<input_stem>_enriched.<ext>`. |
| `--changes`     | ❓        | After `--changes` you may optionally supply a path. The file will contain **only those rows whose `contact_email` was filled or changed**. If no path is given it defaults to `<input_stem>_changes.<ext>`. |

### Quick examples

```bash
# 1) Fast start – enrich sample data shipped with the repo
python email_enricher.py sample_data.csv                          # ⇒ sample_data_enriched.csv

# 2) Custom output paths
python email_enricher.py data/contacts.xlsx results/enriched.xlsx

# 3) Produce an extra file of modified rows for audit
python email_enricher.py data/contacts.xlsx results/enriched.xlsx \
                          --changes results/changed_only.xlsx
```

---

## Comparing Predictions with Ground Truth & Measuring Accuracy

If you have a **ground-truth file** (e.g. `correct_emails.csv`) containing the *actual* emails, you can create a comparison file and compute accuracy with a short pandas snippet:

```bash
python - <<'PY'
import pandas as pd

# Paths – change as needed
predicted = 'predicted_emails.csv'   # output from email_enricher.py
truth     = 'correct_emails.csv'     # file that has the real emails
out_cmp   = 'comparison.csv'         # where to save the side-by-side view

pred = pd.read_csv(predicted)
true = pd.read_csv(truth)

# Rename for clarity & merge on a stable key (adjust the key column if yours differs)
true = true.rename(columns={'Contact: Email': 'correct_email'})
merged = pred.merge(true, how='left')

merged['predicted_email'] = merged['contact_email']
merged['match'] = merged['correct_email'].str.lower() == merged['predicted_email'].str.lower()

merged.to_csv(out_cmp, index=False)
print(f"Accuracy: {merged['match'].mean():.2%} (saved to {out_cmp})")
PY
```

The one-liner above will:
1. Join the predicted and correct datasets.
2. Write `comparison.csv` that shows `correct_email`, `predicted_email`, and a boolean `match` column.
3. Print the overall accuracy (percentage of `True` values in `match`).

---

## Search Provider (Google vs DuckDuckGo)

The enrichment script currently uses **DuckDuckGo** when it looks for public LinkedIn profiles (`_email_from_linkedin`) because that API has a straightforward JSON endpoint and minimal blocking.  A Google-based helper function (`_email_from_google`) is already implemented in the codebase but is **not invoked by default**.

If you prefer to rely solely on Google search, you can:
1. Edit `email_enricher.py` and call `_email_from_google` as an additional step before or after the LinkedIn lookup.
2. Or, replace the DuckDuckGo portion inside `_email_from_linkedin` with `googlesearch.search` (already imported near the top of the script).

> **Tip:** Google tends to rate-limit automated scraping.  To stay under the radar, keep result counts low (the helper uses `num_results=8`) and set a proper `User-Agent` header when making subsequent page requests.

---

## How It Works

1. The script reads the spreadsheet into a pandas `DataFrame`.
2. For each row with an empty `contact_email` it tries to **discover the true pattern for that company**:
   * If `HUNTER_API_KEY` is set, it queries Hunter.io Domain Search to learn the pattern (e.g. `first.last`).
   * Otherwise (or if the API fails) it scrapes the company website and `/contact` page, looking for existing email addresses and inferring the pattern.
3. Using the discovered pattern, it creates one precise candidate (e.g. `john.doe@domain.com`).
4. If discovery fails, it falls back to common patterns (`first.last`, `jdoe`, etc.) but still guarantees no duplicates in the sheet.
5. The enriched spreadsheet is written back to disk (CSV or Excel, matching the requested output extension).

⚠️  **Accuracy note:** Pattern discovery dramatically improves correctness, but absolute certainty often requires a verification step (SMTP or a paid validation API). Integrate one if 100 % accuracy is mandatory.

## Extending the Logic

This heuristic works well for companies that follow standard email patterns.  In real-world scenarios you might also want to:

* Verify candidate emails via SMTP or services like Hunter or ZeroBounce.
* Use external "people-enrichment" APIs (e.g. FullContact) when heuristics fail.
* Add support for multiple companies with differing patterns.
* Cache previously observed valid patterns for each domain.

These enhancements can be slotted into `email_enricher.py` where candidate emails are generated and validated.

---
Created with ❤️ by your friendly AI assistant.
