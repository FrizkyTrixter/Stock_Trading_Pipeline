import json
import os
from openai import OpenAI


MODEL = "gpt-5.5"
OUTPUT_FILE = "ticker_universe.json"


def build_god_prompt() -> str:
    return """
You are an elite AI infrastructure investment research agent.

Your task is to build a 100-stock ticker universe for an AI-driven adaptive trading system.

Strategy:
Use the "AI picks and shovels" investment philosophy inspired by Leopold Aschenbrenner-style AI infrastructure thinking.

Find public companies that could benefit from massive AI growth through:

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
- Return exactly 100 publicly traded stock tickers.
- Prefer stocks with high growth potential.
- Prefer companies that benefit indirectly from AI infrastructure demand.
- Include a mix of large caps, mid caps, and smaller speculative names.
- Avoid random low-quality penny stocks.
- Avoid ETFs.
- Avoid crypto.
- Avoid private companies.
- Avoid unethical companies.
- Prefer liquid stocks suitable for a momentum strategy.
- The universe should be useful for an XGBoost model trying to find stocks likely to rise 10% within 50 trading days.
- Include companies that could have strong catalysts, volatility, and narrative momentum.
- Do not give financial advice.
- Do not say anything outside the JSON.

Return valid JSON only.

JSON format:

{
  "strategy": "AI picks and shovels",
  "universe_size": 100,
  "tickers": [
    {
      "ticker": "NVDA",
      "company": "NVIDIA",
      "category": "AI accelerators",
      "reason": "Dominant GPU supplier for AI training and inference infrastructure."
    }
  ]
}
"""


def get_ticker_universe() -> dict:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    response = client.responses.create(
        model=MODEL,
        input=build_god_prompt(),
        text={
            "format": {
                "type": "json_object"
            }
        }
    )

    return json.loads(response.output_text)


def save_universe(universe: dict, filename: str = OUTPUT_FILE):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(universe, f, indent=2, ensure_ascii=False)


def main():
    universe = get_ticker_universe()

    # Save JSON to disk
    save_universe(universe)

    print(f"Saved ticker universe to '{OUTPUT_FILE}'")
    print(json.dumps(universe, indent=2))


if __name__ == "__main__":
    main()