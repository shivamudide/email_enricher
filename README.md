# Email Enricher

Automatically fill in missing B2B contact emails using a handful of lightweight, **public-data** techniques – no paid look-up services required.

Key features

*   Caches company email patterns (e.g. *first.last* vs *flast*)
*   Falls back to Google & LinkedIn scraping when patterns are unknown
*   Handles vanity domains via a small alias table (e.g. `becn.com → beaconroofingsupply.com`)

## Project Layout

```
emails/
├── email_enricher.py   # Core enrichment logic
├── environment.yml     # Conda environment (optional)
├── sample_data.csv     # Example input
└── ...                 # Test / helper CSVs
```

## Quick setup

```bash
# Option A – Conda (recommended)
conda env create -f environment.yml
conda activate email_enricher

# Option B – plain pip
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt   # generated from environment.yml
```

To boost pattern accuracy you may add a **free** Hunter.io key:

```bash
export HUNTER_API_KEY=your_key_here
```

## How it works

1. **Domain normalisation** – extracts and cleans the company website, applying any hard-coded aliases.
2. **Direct lookup** – searches Google & LinkedIn for an explicit email that contains the contact's last name.
3. **Pattern discovery**
   * Scrapes the company site (and a quick Google search) to collect samples and infer the dominant pattern.
4. **Heuristic fallbacks** – tries a small set of common formats (`jdoe`, `john.doe`, `john@`, …).
5. **Deduping** – ensures each generated email is unique within the dataset.

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
python email_enricher.py test_no_email_short.csv test_enriched_short.csv
```

### Testing Accuracy

```bash
import pandas as pd

# 1. Load your CSVs
df_test = pd.read_csv('test.csv')        # replace with your true-email filename
df_enriched = pd.read_csv('new_predicted3.csv')   # replace with your predicted-email filename

# 2. Build a comparison DataFrame
#    If the rows align 1:1, just zip the columns. 
#    If there's a shared key (e.g. Contact ID), use pd.merge on that key instead.
df = pd.DataFrame({
    'true_email':      df_test['Contact: Email'],
    'predicted_email': df_enriched['contact_email']
})

# 3. Compute a boolean "match" column and overall accuracy
df['match'] = df['true_email'] == df['predicted_email']
accuracy = df['match'].mean()  # fraction of True's

print(f'Accuracy: {accuracy:.2%}')  # e.g. "Accuracy: 87.50%"

# 4. Save the side-by-side comparison
df.to_csv('email_comparison.csv', index=False)
```