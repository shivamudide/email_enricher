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
accuracy = df['match'].mean()  # fraction of True’s

print(f'Accuracy: {accuracy:.2%}')  # e.g. "Accuracy: 87.50%"

# 4. Save the side-by-side comparison
df.to_csv('email_comparison.csv', index=False)
```