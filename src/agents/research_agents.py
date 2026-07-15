
import json
import os
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI


MODEL = "gpt-5.5"
OUTPUT_FILE = Path("ticker_universe.json")
EXPECTED_UNIVERSE_SIZE = 100
MAX_FORMAT_ATTEMPTS = 3


def build_research_prompt() -> str:
    """
    Prompt for stage one.

    This stage may use web search, but it does not request JSON mode.
    Its output becomes source material for the formatting stage.
    """
    return """
You are an elite AI infrastructure investment research agent.

Research and construct a candidate universe of exactly 100 publicly traded
companies for an AI-driven adaptive trading system.

You MUST use web search extensively. Do not construct the universe from memory
alone.

For every company, verify from current internet sources that:

1. The company is currently publicly traded.
2. Its ticker symbol is current.
3. The ticker corresponds to the named company.
4. The company is not an ETF, cryptocurrency, or private company.
5. The company has a meaningful connection to at least one target category.

Investment theme:
Use an "AI picks and shovels" philosophy inspired by AI infrastructure growth.

Target categories:

1. Semiconductors
2. AI accelerators
3. GPU supply chain
4. Semiconductor equipment
5. Advanced packaging
6. Foundries
7. Data centers
8. Cloud computing
9. Optical interconnects
10. Networking
11. Power generation
12. Nuclear energy
13. Grid infrastructure
14. Electrical equipment
15. Cooling systems
16. Robotics
17. Space infrastructure
18. Cybersecurity
19. Quantum computing
20. AI software infrastructure
21. Industrial automation
22. Memory and storage
23. Energy storage
24. Rare earths and critical minerals

Selection rules:

- Select exactly 100 unique publicly traded stock tickers.
- Prefer companies with substantial growth potential.
- Prefer companies benefiting directly or indirectly from AI infrastructure demand.
- Include a mix of large-cap, mid-cap, and smaller speculative companies.
- Avoid random or extremely illiquid penny stocks.
- Avoid ETFs.
- Avoid cryptocurrencies.
- Avoid private companies.
- Avoid companies whose primary business is widely considered unethical.
- Prefer liquid stocks suitable for a momentum strategy.
- Favor companies with catalysts, volatility, and narrative momentum.
- Make the universe useful for an XGBoost model attempting to identify stocks
  likely to appreciate by at least 10% within 50 trading days.
- Do not give personal financial advice.

For each selected company, provide:

- Current ticker
- Company name
- Primary category
- Concise reason for inclusion
- Brief verification note explaining how the ticker and public listing were checked
- Source names or URLs used for verification

Before finishing, audit the proposed universe for:

- Duplicate tickers
- Duplicate companies with multiple share classes
- Delisted companies
- Acquired companies
- Renamed tickers
- ETFs
- Private companies
- Companies with only a weak relationship to the target investment theme

Return a detailed research report. The report may use headings, prose, or tables.
Do not attempt to return strict JSON in this stage because another model call
will convert the research into structured JSON.
""".strip()


def build_formatting_prompt(research_report: str) -> str:
    """
    Prompt for stage two.

    This stage does not use web search. It converts the researched material
    into the required JSON structure.
    """
    return f"""
Convert the research report below into the required ticker-universe structure.

Important requirements:

- Return exactly 100 ticker entries.
- Every ticker must be unique, using a case-insensitive comparison.
- Every company must be publicly traded.
- Do not include ETFs, cryptocurrencies, private companies, or delisted stocks.
- Do not invent companies or facts that are absent from the research.
- Use uppercase ticker symbols.
- Keep each reason concise and specific.
- Assign one primary category to each company.
- Set "strategy" exactly to "AI picks and shovels".
- Set "universe_size" exactly to 100.
- Do not include source URLs or verification notes in the final structure.
- Do not give financial advice.

RESEARCH REPORT
================
{research_report}
================
END RESEARCH REPORT
""".strip()


TICKER_UNIVERSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "strategy": {
            "type": "string",
            "enum": ["AI picks and shovels"],
        },
        "universe_size": {
            "type": "integer",
            "enum": [EXPECTED_UNIVERSE_SIZE],
        },
        "tickers": {
            "type": "array",
            "minItems": EXPECTED_UNIVERSE_SIZE,
            "maxItems": EXPECTED_UNIVERSE_SIZE,
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "company": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "category": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "reason": {
                        "type": "string",
                        "minLength": 1,
                    },
                },
                "required": [
                    "ticker",
                    "company",
                    "category",
                    "reason",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "strategy",
        "universe_size",
        "tickers",
    ],
    "additionalProperties": False,
}


def get_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set.\n"
            "In WSL, set it with:\n"
            'export OPENAI_API_KEY="your-api-key"'
        )

    return OpenAI(api_key=api_key)


def perform_web_research(client: OpenAI) -> str:
    """
    Stage one: conduct current web research without JSON mode.
    """
    print("Stage 1/2: Researching and validating companies with web search...")

    response = client.responses.create(
        model=MODEL,
        input=build_research_prompt(),
        tools=[
            {
                "type": "web_search",
            }
        ],
        tool_choice="required",
    )

    research_report = response.output_text.strip()

    if not research_report:
        raise RuntimeError("The web-research stage returned no text.")

    print(
        "Research stage completed "
        f"({len(research_report):,} characters received)."
    )

    return research_report


def format_research_as_json(
    client: OpenAI,
    research_report: str,
) -> dict[str, Any]:
    """
    Stage two: convert the research report into strict structured JSON.

    No web-search tool is attached to this request, so structured output can
    be used here.
    """
    print("Stage 2/2: Converting the research into validated JSON...")

    response = client.responses.create(
        model=MODEL,
        input=build_formatting_prompt(research_report),
        text={
            "format": {
                "type": "json_schema",
                "name": "ticker_universe",
                "strict": True,
                "schema": TICKER_UNIVERSE_SCHEMA,
            }
        },
    )

    output_text = response.output_text.strip()

    if not output_text:
        raise RuntimeError("The JSON-formatting stage returned no text.")

    try:
        return json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "The formatting stage did not return valid JSON."
        ) from exc


def validate_universe(universe: dict[str, Any]) -> None:
    """
    Perform application-level validation not fully enforced by JSON Schema.

    JSON Schema can enforce array length, but it cannot conveniently enforce
    uniqueness based on a nested ticker field.
    """
    if universe.get("strategy") != "AI picks and shovels":
        raise ValueError("Unexpected strategy value.")

    tickers = universe.get("tickers")

    if not isinstance(tickers, list):
        raise ValueError("'tickers' must be a list.")

    if len(tickers) != EXPECTED_UNIVERSE_SIZE:
        raise ValueError(
            f"Expected {EXPECTED_UNIVERSE_SIZE} tickers, "
            f"but received {len(tickers)}."
        )

    declared_size = universe.get("universe_size")

    if declared_size != len(tickers):
        raise ValueError(
            f"universe_size is {declared_size}, but the ticker list contains "
            f"{len(tickers)} entries."
        )

    normalized_tickers: list[str] = []

    for index, entry in enumerate(tickers, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Ticker entry {index} is not an object.")

        for field in ("ticker", "company", "category", "reason"):
            value = entry.get(field)

            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"Ticker entry {index} has an invalid '{field}' value."
                )

            entry[field] = value.strip()

        entry["ticker"] = entry["ticker"].upper()
        normalized_tickers.append(entry["ticker"])

    duplicate_tickers = sorted(
        {
            ticker
            for ticker in normalized_tickers
            if normalized_tickers.count(ticker) > 1
        }
    )

    if duplicate_tickers:
        raise ValueError(
            "Duplicate ticker symbols found: "
            + ", ".join(duplicate_tickers)
        )


def get_ticker_universe() -> dict[str, Any]:
    """
    Run the complete two-stage pipeline.

    Formatting is retried if the second response passes JSON Schema but fails
    an application-level rule such as nested ticker uniqueness.
    """
    client = get_client()
    research_report = perform_web_research(client)

    last_error: Exception | None = None

    for attempt in range(1, MAX_FORMAT_ATTEMPTS + 1):
        try:
            universe = format_research_as_json(
                client=client,
                research_report=research_report,
            )
            validate_universe(universe)
            return universe

        except (RuntimeError, ValueError) as exc:
            last_error = exc

            if attempt == MAX_FORMAT_ATTEMPTS:
                break

            print(
                f"Formatting attempt {attempt} failed: {exc}",
                file=sys.stderr,
            )
            print("Retrying the formatting stage...", file=sys.stderr)

    raise RuntimeError(
        f"Could not produce a valid ticker universe after "
        f"{MAX_FORMAT_ATTEMPTS} formatting attempts."
    ) from last_error


def save_universe(
    universe: dict[str, Any],
    filename: Path = OUTPUT_FILE,
) -> None:
    """
    Save through a temporary file and then replace the destination.

    This avoids leaving a partially written JSON file if writing fails.
    """
    filename.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = filename.with_suffix(filename.suffix + ".tmp")

    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(
            universe,
            file,
            indent=2,
            ensure_ascii=False,
        )
        file.write("\n")

    temporary_file.replace(filename)


def main() -> None:
    try:
        universe = get_ticker_universe()
        save_universe(universe)

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"Saved ticker universe to '{OUTPUT_FILE.resolve()}'")
    print(f"Validated {len(universe['tickers'])} unique ticker entries.")
    print(json.dumps(universe, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
