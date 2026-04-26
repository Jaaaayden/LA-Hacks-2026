"""Interactive negotiation simulator.

Pretend to be an OfferUp seller while the real negotiation bot responds.
This only calls Claude through gen_negotiation_message; it does not open
OfferUp, MongoDB, or Playwright.

Usage:
    python scripts/simulate_negotiation.py "Burton snowboard 158cm" 180 140
"""

from __future__ import annotations

import argparse

from backend.services.gen_negotiation_message import gen_negotiation_message


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with the negotiation bot.")
    parser.add_argument("listing_title", help="OfferUp listing title")
    parser.add_argument("asking_price", type=float, help="Seller's asking price")
    parser.add_argument("target_price", type=float, help="Bot's target price")
    args = parser.parse_args()

    conversation: list[dict[str, str]] = []

    print("\nNegotiation simulator")
    print("Type seller replies. Use /quit to stop.\n")
    print(f"Listing: {args.listing_title}")
    print(f"Asking: ${args.asking_price:.2f}")
    print(f"Target: ${args.target_price:.2f}\n")

    while True:
        result = gen_negotiation_message(
            args.listing_title,
            args.asking_price,
            args.target_price,
            conversation,
        )

        action = result["action"]
        message = result["message"]

        print(f"Bot action: {action}")
        if message:
            print(f"Bot: {message}")
            conversation.append({"role": "negotiator", "content": message})
        else:
            print("Bot: (no message)")

        if action in {"accept", "give_up"}:
            break

        seller_reply = input("\nSeller: ").strip()
        if seller_reply.lower() in {"/q", "/quit", "quit", "exit"}:
            break
        if not seller_reply:
            print("Seller reply cannot be empty. Try again.")
            continue

        conversation.append({"role": "seller", "content": seller_reply})
        print()


if __name__ == "__main__":
    main()
