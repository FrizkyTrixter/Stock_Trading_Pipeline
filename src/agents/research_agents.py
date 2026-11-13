"""Conservative, diversified ticker-universe research agent.

Requires: pip install openai
Environment: OPENAI_API_KEY; optional OPENAI_MODEL (default gpt-5.5).
Produces ticker_universe.json and ticker_universe_research.txt.

Research assessments are LLM-derived, not independently audited financial data.
"""

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from openai import OpenAI

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
OUTPUT_FILE = Path("ticker_universe.json")
RESEARCH_FILE = Path("ticker_universe_research.txt")
EXPECTED_UNIVERSE_SIZE = 100
MAX_FORMAT_ATTEMPTS = 3
# Preserve the original strategy string for existing downstream consumers.
LEGACY_STRATEGY = "AI picks and shovels"
MAX_SECTOR_COUNT = 25

RESEARCH_PROMPT = """
# Institutional-Quality Equity Universe Research Agent

You are a conservative, evidence-driven equity research analyst responsible for
constructing a diversified universe of 100 publicly traded companies for a
systematic XGBoost trading platform.

Your responsibility is NOT to predict which stocks will rise the fastest.
Identify financially credible, liquid, established businesses with acceptable
financial risk and sufficient historical data for quantitative modeling.
The XGBoost model independently evaluates short-term trading opportunities.

## 1. Research requirements
Use current public financial information and extensive web research. Do not
select companies from memory alone. Begin with established equity benchmarks:
S&P 500, S&P MidCap 400, Nasdaq-100, and selectively S&P SmallCap 600.
Verify membership from official index-provider or exchange information when
available. Index membership is NOT proof of financial safety.
Do not restrict the universe to AI, technology, or any investment narrative.

## 2. Fundamental quality
Prioritize positive recent operating cash flow; positive free cash flow in at
least two of the past three fiscal years; positive operating income; manageable
debt relative to cash generation; adequate liquidity for near-term obligations;
sustainable operating history; reliable financial disclosures; sufficient
market capitalization and trading volume; and limited dependence on repeated
external financing. Use the latest available filings and report their dates.

## 3. Financial risk exclusions
Exclude companies with documented material going-concern concerns, severe
liquidity or solvency distress, persistent negative operating cash flow combined
with external financing dependence, unsustainable interest expense, material
unfunded near-term refinancing obligations, serious unresolved accounting
concerns, or speculative business models without established operations.
Review customer/counterparty concentration, off-balance-sheet obligations,
capital expenditure commitments, and deteriorating financial performance.
Apply exclusions using documented evidence, not narrative or guesswork.
Use sector-appropriate analysis for banks, insurers, utilities, and REITs;
industrial leverage ratios are not universal.

## 4. Market quality
Prefer market capitalization >= USD 5 billion; median daily dollar volume
>= USD 20 million over 60 sessions; >= 3 years of usable daily price history;
reliable adjusted prices; active listing; and no trading suspension.
These are initial policy thresholds, not guarantees. Do not include ETFs,
cryptocurrencies, private companies, delisted stocks, or duplicate share classes.

## 5. Diversification
Diversify across information technology, healthcare, financials, industrials,
consumer staples, consumer discretionary, utilities, energy, materials,
communication services, and real estate. Aim for no more than 25 companies
in one sector. Consider shared sensitivity to rates, credit conditions,
commodities, and the economic cycle.

## 6. AI exposure
AI-related companies may qualify only under the SAME financial standards.
Do not favor GPU, cloud, data-center, nuclear, quantum, robotics, or other
emerging-technology companies simply because of enthusiasm, revenue growth,
large customers, ambitious capex plans, or narrative momentum.

## 7. Evidence and integrity
For EACH selected company, document its exact uppercase ticker, company name,
primary sector, listing verification, index membership if verified, market cap,
liquidity, operating cash flow, free cash flow, debt and liquidity condition,
material risks, and at least one specific source URL with its reporting date.
Distinguish observed facts from analysis. Never fabricate a metric or citation.
If data is unavailable, say UNKNOWN and do not claim verification.
Do not include a company unless its essential financial quality, current listing,
and liquidity can be reasonably supported by retrieved evidence.

## 8. Selection process
Research a broad candidate pool from established indices, then assess
financial strength, trading liquidity, data availability, and concentration.
Exclude material financial distress and select the 100 strongest eligible
candidates, without optimizing for expected 50-day gains.
If you cannot verify 100 eligible companies, state the shortfall explicitly.
NEVER invent companies, evidence, or weaken standards to hit a quota.

## 9. Output format (research stage only)
Produce a detailed report. Start with a section titled EXACTLY:
SELECTED TICKERS
Then provide exactly one ticker per line in this form:
TICKER | Company Name | Primary GICS Sector
Only include companies whose financial quality and eligibility you researched.
After that section, start a section titled EXACTLY:
END SELECTED TICKERS
Then provide a separate numbered evidence section for EACH selected company,
including financial strength, risk factors, listing verification, sources,
and reporting dates. End with a sector count summary and verification gaps.
Do not write JSON in this research stage.
""".strip()


def build_research_prompt() -> str:
    return RESEARCH_PROMPT


def extract_researched_tickers(report: str) -> dict[str, dict[str, str]]:
    """Extract only the explicitly selected companies, not incidental mentions."""
    match = re.search(
        r"(?im)^SELECTED TICKERS\s*$([\s\S]*?)^END SELECTED TICKERS\s*$",
        report,
    )
    if not match:
        raise ValueError("Research report lacks the required selected-tickers section.")
    result: dict[str, dict[str, str]] = {}
    companies: set[str] = set()
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 3:
            raise ValueError(f"Invalid research ticker line: {line[:120]}")
        ticker, company, sector = parts
        ticker = ticker.upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", ticker):
            raise ValueError(f"Invalid ticker format: {ticker}")
        company_key = re.sub(r"[^a-z0-9]", "", company.casefold())
        if not company_key or not sector:
            raise ValueError(f"Missing company or sector for {ticker}")
        if ticker in result or company_key in companies:
            raise ValueError(f"Duplicate ticker/company in research: {ticker}")
        companies.add(company_key)
        result[ticker] = {"company": company, "category": sector}
    if len(result) != EXPECTED_UNIVERSE_SIZE:
        raise ValueError(
            f"Research documented {len(result)} companies, not "
            f"{EXPECTED_UNIVERSE_SIZE}; refusing to fill gaps with guesses."
        )
    counts = Counter(v["category"].casefold() for v in result.values())
    if any(count > MAX_SECTOR_COUNT for count in counts.values()):
        raise ValueError(f"Research exceeds sector limit: {dict(counts)}")
    return result


def build_formatting_prompt(report: str, error: str = "") -> str:
    return f"""Convert the research below into the specified JSON schema.
Use ONLY the 100 companies between SELECTED TICKERS and END SELECTED TICKERS.
Do not add, replace, or omit any ticker. Preserve each researched company name
and sector exactly. Set category to that sector. Write a concise, specific
reason focused on documented financial quality, not price speculation.
Set strategy exactly to {LEGACY_STRATEGY!r} solely for backward compatibility;
this label does NOT describe the new diversified investment philosophy.
Set universe_size to {EXPECTED_UNIVERSE_SIZE}.
Do not fabricate financial claims. Do not include sources in the legacy JSON.
Previous validation error, if any: {error or 'None'}

RESEARCH REPORT:
{report}
"""


TICKER_UNIVERSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "strategy": {"type": "string", "enum": [LEGACY_STRATEGY]},
        "universe_size": {"type": "integer", "enum": [EXPECTED_UNIVERSE_SIZE]},
        "tickers": {
            "type": "array",
            "minItems": EXPECTED_UNIVERSE_SIZE,
            "maxItems": EXPECTED_UNIVERSE_SIZE,
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "company": {"type": "string"},
                    "category": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["ticker", "company", "category", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["strategy", "universe_size", "tickers"],
    "additionalProperties": False,
}


def get_client() -> OpenAI:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY environment variable is not set.")
    return OpenAI()


def perform_web_research(client: OpenAI) -> str:
    print("Stage 1/2: Researching diversified, financially established companies...")
    response = client.responses.create(
        model=MODEL,
        input=build_research_prompt(),
        tools=[{"type": "web_search"}],
        tool_choice="required",
    )
    report = response.output_text.strip()
    if not report:
        raise RuntimeError("Web research returned no report.")
    return report


def format_research_as_json(client: OpenAI, report: str, error: str = "") -> dict[str, Any]:
    response = client.responses.create(
        model=MODEL,
        input=build_formatting_prompt(report, error),
        text={"format": {
            "type": "json_schema",
            "name": "ticker_universe",
            "strict": True,
            "schema": TICKER_UNIVERSE_SCHEMA,
        }},
    )
    if not response.output_text.strip():
        raise RuntimeError("Formatting response was empty.")
    return json.loads(response.output_text)


def validate_universe(universe: dict[str, Any], researched: dict[str, dict[str, str]]) -> None:
    if universe.get("strategy") != LEGACY_STRATEGY:
        raise ValueError("Unexpected strategy field.")
    entries = universe.get("tickers")
    if not isinstance(entries, list) or len(entries) != EXPECTED_UNIVERSE_SIZE:
        raise ValueError("Expected exactly 100 ticker entries.")
    if universe.get("universe_size") != len(entries):
        raise ValueError("Universe size mismatch.")
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Ticker entry must be an object.")
        for key in ("ticker", "company", "category", "reason"):
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                raise ValueError(f"Invalid or missing field: {key}")
            entry[key] = entry[key].strip()
        ticker = entry["ticker"].upper()
        entry["ticker"] = ticker
        if ticker in seen:
            raise ValueError(f"Duplicate ticker: {ticker}")
        seen.add(ticker)
        if ticker not in researched:
            raise ValueError(f"Unresearched ticker introduced: {ticker}")
        original = researched[ticker]
        if entry["company"].casefold() != original["company"].casefold():
            raise ValueError(f"Company mismatch for {ticker}")
        if entry["category"].casefold() != original["category"].casefold():
            raise ValueError(f"Sector mismatch for {ticker}")
    if seen != set(researched):
        raise ValueError(f"Missing researched tickers: {sorted(set(researched) - seen)}")


def get_ticker_universe() -> tuple[dict[str, Any], str]:
    client = get_client()
    report = perform_web_research(client)
    # A failed research run is deliberately not repaired with invented names.
    researched = extract_researched_tickers(report)
    last_error = ""
    for attempt in range(1, MAX_FORMAT_ATTEMPTS + 1):
        try:
            print(f"Stage 2/2: Formatting attempt {attempt}...")
            universe = format_research_as_json(client, report, last_error)
            validate_universe(universe, researched)
            return universe, report
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            print(f"Formatting attempt {attempt} failed: {exc}", file=sys.stderr)
    raise RuntimeError(f"Formatting failed after {MAX_FORMAT_ATTEMPTS} attempts: {last_error}")


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def save_universe(universe: dict[str, Any], filename: Path = OUTPUT_FILE) -> None:
    atomic_write_text(filename, json.dumps(universe, indent=2, ensure_ascii=False) + "\n")


def main() -> None:
    try:
        universe, report = get_ticker_universe()
        # Preserve the report for human review; it is not independent verification.
        atomic_write_text(RESEARCH_FILE, report + "\n")
        save_universe(universe)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"Saved {len(universe['tickers'])} tickers to {OUTPUT_FILE.resolve()}")
    print(f"Research report: {RESEARCH_FILE.resolve()}")


if __name__ == "__main__":
    main()
