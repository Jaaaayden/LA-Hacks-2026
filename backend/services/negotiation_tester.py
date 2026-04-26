"""CLI REPL for testing the negotiation AI without a real browser.

Usage:
    .venv/Scripts/python.exe -m backend.services.negotiation_tester
    .venv/Scripts/python.exe -m backend.services.negotiation_tester \\
        --title "Sony WH-1000XM4" --asking 120 --target 85
"""

from __future__ import annotations

import argparse
import sys

from backend.services.gen_negotiation_message import gen_negotiation_message


def _prompt_float(prompt_text: str) -> float:
    while True:
        raw = input(prompt_text).strip().lstrip("$").replace(",", "")
        try:
            value = float(raw)
            if value > 0:
                return value
            print("  Enter a positive number.")
        except ValueError:
            print("  Not a valid number, try again.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate a price negotiation against a human-typed seller."
    )
    parser.add_argument("--title", type=str, default=None, help="Listing title")
    parser.add_argument("--asking", type=float, default=None, help="Seller's asking price (USD)")
    parser.add_argument("--target", type=float, default=None, help="Buyer's target price (USD)")
    parser.add_argument(
        "--model",
        type=str,
        default="claude-haiku-4-5-20251001",
        help="Anthropic model to use",
    )
    return parser.parse_args()


def run(
    listing_title: str,
    asking_price_usd: float,
    target_price_usd: float,
    model: str = "claude-haiku-4-5-20251001",
) -> None:
    conversation: list[dict[str, str]] = []

    print(f"\nNegotiating: {listing_title}")
    print(f"  Asking ${asking_price_usd:.2f}  |  Target ${target_price_usd:.2f}")
    print("  Type the seller's response at each [Seller] prompt. Ctrl-C to quit.\n")

    while True:
        result = gen_negotiation_message(
            listing_title,
            asking_price_usd,
            target_price_usd,
            conversation,
            model=model,
        )
        action: str = result["action"]
        message: str | None = result["message"]

        if action == "give_up":
            print("[You] — (no message sent, giving up)")
            print("\nNegotiation ended: seller was not flexible enough.")
            break

        print(f"[You ->] {message}")

        if action == "accept":
            print("\nNegotiation ended: deal accepted.")
            break

        conversation.append({"role": "negotiator", "content": message or ""})

        try:
            seller_reply = input("[Seller ->] ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession interrupted.")
            break

        if not seller_reply:
            print("  (empty response — enter something to continue)")
            conversation.pop()
            continue

        conversation.append({"role": "seller", "content": seller_reply})


def main() -> None:
    args = _parse_args()

    title = args.title or input("Listing title: ").strip()
    if not title:
        print("Title cannot be empty.", file=sys.stderr)
        sys.exit(1)

    asking = args.asking if args.asking is not None else _prompt_float("Asking price ($): ")
    target = args.target if args.target is not None else _prompt_float("Your target price ($): ")

    run(title, asking, target, model=args.model)


if __name__ == "__main__":
    main()
