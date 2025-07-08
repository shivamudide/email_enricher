import sys
from pathlib import Path
from urllib.parse import urlparse
import os
import re
from collections import Counter
from typing import Optional

from googlesearch import search

import pandas as pd
import requests
from bs4 import BeautifulSoup
import tldextract


# Optional Hunter.io support (free plan: 25 reqs/month). Set env var HUNTER_API_KEY.
_HUNTER_API_KEY: str | None = os.getenv("HUNTER_API_KEY")

# ---------------------------------------------------------------------------
# Custom domain aliases – when the public-facing website uses a short vanity
# domain (e.g. becn.com) but employees actually use a different canonical
# email domain (e.g. beaconroofingsupply.com). This small mapping is purely
# heuristic and can be extended over time.
# ---------------------------------------------------------------------------
_DOMAIN_ALIASES: dict[str, str] = {
    "becn.com": "beaconroofingsupply.com",
    "bunzldistribution.com": "bunzlusa.com",
}

# Cache discovered patterns (pattern, canonical domain) per input domain so we don't hit rate-limits / scrape multiple times
_PATTERN_CACHE: dict[str, tuple[str | None, str]] = {}

# No DuckDuckGo singleton needed after migration to Google search


# --------------------------------------------
# Helper utilities
# --------------------------------------------


_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}")


def _clean_name(name: str) -> str:
    """Return a lowercase version of *name* containing **only** alphabetic characters.

    Examples
    --------
    >>> _clean_name("G. Francis")
    'francis'
    >>> _clean_name("Barker Johns")
    'johns'
    """
    name = name.strip().lower()
    # Keep only alphabetic characters – this removes dots, commas, etc.
    cleaned = re.sub(r"[^a-z]", "", name)
    return cleaned


def _email_from_google(first: str, last: str, company: str | None) -> str | None:
    """Search Google for an email address that matches *first* and *last*.

    The query strategy favours high-accuracy sources (company website, LinkedIn).
    If any email from the results contains the *last* name (to reduce false positives)
    it is returned.
    """
    try:
        queries = []
        base_q = f"{first} {last}"
        if company and isinstance(company, str):
            queries.extend([
                f'"{base_q}" "{company}" email',
                f'"{base_q}" "{company}" "@"',
            ])
        # Broader fallbacks – used only if the company-specific queries fail
        queries.extend([
            f'"{base_q}" email',
            f'"{base_q}" "@"',
        ])

        for q in queries:
            # The *search* generator may raise HTTPError if Google blocks – catch & continue
            try:
                results = list(search(q, num_results=8))  # small number to be respectful
            except Exception:
                continue

            for url in results:
                # We skip common sites that are unlikely to expose direct emails
                if any(bad in url for bad in ["facebook.com"]):
                    continue
                try:
                    resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
                    if not resp.ok:
                        continue
                    emails = _EMAIL_RE.findall(resp.text)
                    if not emails:
                        continue
                    # Prefer emails that contain the (cleaned) last name
                    clean_last = _clean_name(last)
                    for e in emails:
                        if clean_last and clean_last in e.lower():
                            return e.lower()
                    # If none with last name, return first retrieved (makes query order the filter)
                    return emails[0].lower()
                except Exception:
                    continue
    except Exception:
        # Any unexpected failure – just fall back to existing heuristics
        return None

    return None


def _normalize_domain(website: str | None) -> str | None:
    """Extract and normalize domain from a website string.

    Examples
    --------
    >>> _normalize_domain("https://www.firstsupply.com")
    'firstsupply.com'
    >>> _normalize_domain("firstsupply.com")
    'firstsupply.com'
    """
    if not website or pd.isna(website):
        return None
    website = str(website).strip()
    if not website:
        return None
    # Prepend protocol if missing so urlparse can work reliably
    if not website.startswith(("http://", "https://")):
        website = "http://" + website
    parsed = urlparse(website)
    domain = parsed.netloc if parsed.netloc else parsed.path
    if domain.startswith("www."):
        domain = domain[4:]
    return domain.lower() if domain else None


def _generate_candidates(first: str, last: str, domain: str) -> list[str]:
    """Return a *deduplicated* list of potential email addresses."""
    first_clean = _clean_name(first)
    last_clean_full = _clean_name(last)

    # Handle multi-word last names – take the *last* token by default (e.g. "Barker Johns" → "johns")
    last_tokens = [t for t in re.split(r"\s+", last.strip()) if t]
    last_main = _clean_name(last_tokens[-1]) if last_tokens else last_clean_full

    fi = first_clean[0] if first_clean else ""
    li = last_main[0] if last_main else ""

    raw_candidates = [
        f"{fi}{last_main}@{domain}",               # jdoe@domain.com (first initial + last)
        f"{first_clean}{li}@{domain}",             # johnd@domain.com (first + last initial)
        f"{first_clean}.{last_main}@{domain}",     # john.doe@domain.com
        f"{first_clean}{last_main}@{domain}",      # johndoe@domain.com
        f"{first_clean}@{domain}",                 # john@domain.com
        # Variants using *full* last name (include middle particles such as "von")
        f"{first_clean}.{last_clean_full}@{domain}",   # john.vonschwarzenfeld@domain.com
        f"{first_clean}{last_clean_full}@{domain}",    # johnvonschwarzenfeld@domain.com
        f"{fi}{last_clean_full}@{domain}",             # jvonschwarzenfeld@domain.com
    ]

    # Remove duplicates while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for cand in raw_candidates:
        cand = cand.lower()
        if cand not in seen:
            unique.append(cand)
            seen.add(cand)
    return unique


def _extract_emails_from_html(html: str, domain: str) -> list[str]:
    """Return all email addresses @<domain> found in the HTML source."""
    pattern = re.compile(rf"[a-zA-Z0-9._%+-]+@{re.escape(domain)}")
    return pattern.findall(html)


def _deduce_pattern_from_emails(emails: list[str]) -> str | None:
    """Given samples like john.doe@x.com, jdoe@x.com, find the most common pattern."""
    if not emails:
        return None
    candidates: list[str] = []
    for email in emails:
        local = email.split("@")[0]
        if "." in local:
            candidates.append("first.last")
        elif len(local) > 1 and local[0].isalpha():
            # first initial + last e.g. jdoe
            if len(local) <= 2:
                continue
            # If local part starts with a *single* character followed by full last name → flast
            first_initial, rest = local[0], local[1:]
            if rest.isalpha():
                candidates.append("flast")
            # If local part ends with a *single* character (last initial) preceded by full first name → firstl
            if local[-1].isalpha() and local[:-1].isalpha():
                # crude check: last char is initial, preceding part could be first name
                candidates.append("firstl")
            # Otherwise treat as firstlast (no delimiter, full names joined)
            candidates.append("firstlast")
        else:
            continue
    if not candidates:
        return None
    return Counter(candidates).most_common(1)[0][0]


def _pattern_from_hunter(domain: str) -> str | None:
    """Try Hunter.io Domain Search to fetch the common email pattern."""
    if not _HUNTER_API_KEY:
        return None
    try:
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": _HUNTER_API_KEY, "limit": 1},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("pattern")
    except Exception:
        return None


def _extract_all_emails(html: str) -> list[str]:
    """Return *all* email addresses found in HTML (no domain filtering)."""
    return _EMAIL_RE.findall(html)


def _discover_pattern_and_domain(domain: str) -> tuple[str | None, str]:
    """Attempt to discover (pattern, canonical_domain) for *domain*.

    If emails on the site point to a *different* domain, that domain is returned.
    The pattern is deduced from those emails (or via Hunter.io).
    """
    if domain in _PATTERN_CACHE:
        return _PATTERN_CACHE[domain]

    # First attempt: Hunter.io (fast & reliable when available)
    pattern = _pattern_from_hunter(domain)
    canonical = domain

    if pattern is None:
        # Scrape company pages to infer pattern & canonical domain
        potential_urls = [
            f"https://{domain}",
            f"http://{domain}",
            f"https://www.{domain}",
            f"http://www.{domain}",
            f"https://{domain}/contact",
            f"http://{domain}/contact",
        ]
        emails_found: list[str] = []
        for url in potential_urls:
            try:
                r = requests.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0"})
                if r.ok:
                    # collect *all* emails regardless of domain
                    emails_found.extend(_extract_all_emails(r.text))
                if emails_found:
                    break
            except Exception:
                continue

        # If still nothing, perform a lightweight Google search for any emails at the domain
        if not emails_found:
            try:
                google_results = list(search(f'"@{domain}"', num_results=6))
                for g_url in google_results:
                    try:
                        resp = requests.get(g_url, timeout=6, headers={"User-Agent": "Mozilla/5.0"})
                        if resp.ok:
                            emails_found.extend(_extract_all_emails(resp.text))
                    except Exception:
                        continue
            except Exception:
                pass

        # If emails with a *different* domain exist, prefer that as canonical
        domains_counter = Counter([e.split("@")[-1].lower() for e in emails_found])
        if domains_counter:
            canonical = domains_counter.most_common(1)[0][0]
        # Deduce pattern solely from *those* emails that match canonical domain (if any)
        relevant_emails = [e for e in emails_found if e.endswith("@" + canonical)] or emails_found
        pattern = _deduce_pattern_from_emails(relevant_emails)

    _PATTERN_CACHE[domain] = (pattern, canonical)
    return pattern, canonical


def _build_email_from_pattern(first: str, last: str, domain: str, pattern: str) -> str | None:
    match pattern:
        case "first.last":
            return f"{first.lower()}.{last.lower()}@{domain}"
        case "firstlast":
            return f"{first.lower()}{last.lower()}@{domain}"
        case "firstl":
            return f"{first.lower()}{last.lower()[0]}@{domain}"
        case "flast":
            return f"{first.lower()[0]}{last.lower()}@{domain}"
        case _:
            return None


def _email_from_linkedin(first: str, last: str, company: str | None, domain: str | None) -> str | None:
    """Attempt to locate a direct email address on the person's public LinkedIn page using Google Search.

    The function queries Google for LinkedIn profile URLs that match the provided
    first/last name (optionally company) and then scrapes each result for emails.
    Preference is given to addresses matching the company *domain* when supplied;
    otherwise, any email containing the person's last name is considered.
    """

    # Build a Google query focused on LinkedIn profiles
    query_parts = [f'"{first}"', f'"{last}"']
    if company:
        query_parts.append(f'"{company}"')
    query_parts.extend(["site:linkedin.com/in", "email"])
    query = " ".join(query_parts)

    try:
        # Retrieve up to 8 Google Search results (small number to remain respectful)
        results = list(search(query, num_results=8))
    except Exception:
        results = []

    for url in results:
        if "linkedin.com/in" not in url:
            continue
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
            if not r.ok:
                continue
            emails = _extract_emails_from_html(r.text, domain if domain else "")
            if not emails and domain:
                # If no company-domain emails found, consider any containing the last name
                possible = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", r.text)
                emails = [e for e in possible if last.lower() in e.lower()]
            if emails:
                return emails[0].lower()
        except Exception:
            continue
    return None


def enrich_emails(df: pd.DataFrame) -> pd.DataFrame:
    """Fill empty `contact_email` fields with best-guess *validated* addresses."""
    # Ensure contact_email column is treated as string to avoid AttributeError when the column is all-NA
    used_emails: set[str] = set(df["contact_email"].dropna().astype(str).str.lower())

    for idx, row in df.iterrows():
        email = row.get("contact_email")
        if pd.isna(email) or not str(email).strip():
            first = str(row.get("contact_first_name", "")).strip()
            last = str(row.get("contact_last_name", "")).strip()
            domain = _normalize_domain(row.get("account_website"))
            # Apply known domain aliases (e.g., becn.com -> beaconroofingsupply.com)
            if domain in _DOMAIN_ALIASES:
                domain = _DOMAIN_ALIASES[domain]
            if not (first and last and domain):
                continue  # insufficient data

            # Step 0: Attempt to fetch direct email from a Google search (high precision when available)
            google_email = _email_from_google(first, last, row.get("account_name"))
            if google_email and google_email not in used_emails:
                df.at[idx, "contact_email"] = google_email.lower()
                used_emails.add(google_email.lower())
                continue

            # Step 0: Attempt to fetch direct email from LinkedIn profile (conservative)
            linkedin_email = _email_from_linkedin(first, last, row.get("account_name"), domain)
            if linkedin_email and linkedin_email not in used_emails:
                df.at[idx, "contact_email"] = linkedin_email
                used_emails.add(linkedin_email)
                continue

            # Step 1: discover pattern for domain (cached)
            pattern, canonical = _discover_pattern_and_domain(domain)

            candidate_emails: list[str] = []
            if pattern:
                cand = _build_email_from_pattern(first, last, canonical, pattern)
                if cand:
                    candidate_emails.append(cand)

            # Step 2: fallback to generic heuristics (use canonical domain)
            candidate_emails.extend(
                [c for c in _generate_candidates(first, last, canonical) if c not in candidate_emails]
            )

            # Select first unused candidate *after* stripping any whitespace just in case
            for cand in candidate_emails:
                cand_clean = cand.replace(" ", "").lower()
                if cand_clean not in used_emails:
                    df.at[idx, "contact_email"] = cand_clean
                    used_emails.add(cand_clean)
                    break
    return df


def _read_input(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path)


def _write_output(df: pd.DataFrame, path: Path) -> None:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df.to_excel(path, index=False)
    else:
        df.to_csv(path, index=False)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python email_enricher.py <input_file> [output_file]", file=sys.stderr)
        sys.exit(1)

    input_path = Path(sys.argv[1]).expanduser()
    if not input_path.exists():
        print(f"Error: {input_path} does not exist", file=sys.stderr)
        sys.exit(1)

    output_path = (
        Path(sys.argv[2]).expanduser()
        if len(sys.argv) > 2
        else input_path.with_name(f"{input_path.stem}_enriched{input_path.suffix}")
    )

    df = _read_input(input_path)
    enriched_df = enrich_emails(df)
    _write_output(enriched_df, output_path)
    print(f"Enriched file saved to {output_path}")

    # Optionally emit file of modified rows for easier review
    if "--changes" in sys.argv:
        changes_index = sys.argv.index("--changes")
        dest = (
            Path(sys.argv[changes_index + 1]).expanduser()
            if len(sys.argv) > changes_index + 1
            else input_path.with_name(f"{input_path.stem}_changes{input_path.suffix}")
        )
        modified_rows = enriched_df[df["contact_email"].isna() | (df["contact_email"] != enriched_df["contact_email"])]
        _write_output(modified_rows, dest)
        print(f"Changes file saved to {dest}")


if __name__ == "__main__":
    main()
