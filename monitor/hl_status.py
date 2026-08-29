#!/usr/bin/env python3
"""
Hyperliquid Combined Bot Status Monitor
Queries both the scalper (parent) and market maker (sub-account) accounts
and prints a unified P&L + position report.

Usage:
  python3 hl_status.py              # One-shot report
  python3 hl_status.py --watch      # Refresh every 30s
  python3 hl_status.py --json       # JSON output for machine consumption

Can also be called by a systemd timer for periodic status logging.
"""
import sys
import os
import json
import time
from datetime import datetime, timezone
from dotenv import load_dotenv

# Add both bot dirs to path for shared SDK access
sys.path.insert(0, "/home/efinney/hyperliquid-mm-bot")

from hyperliquid.info import Info
from hyperliquid.utils import constants

# ── Configuration ────────────────────────────────────────────────────
PARENT_ADDRESS = "0xYOUR_PARENT_WALLET_ADDRESS"
SUB_ACCOUNT = "0xYOUR_SUB_ACCOUNT_ADDRESS"

# Asset display config
ASSETS = ["BTC", "ETH", "SOL", "XRP", "ZEC", "kPEPE", "kBONK", "ARB"]


def get_account_state(info: Info, address: str, label: str) -> dict:
    """Query full account state for a wallet."""
    try:
        state = info.user_state(address)
        margin = state.get("crossMarginSummary", state.get("marginSummary", {}))
        equity = float(margin.get("accountValue", 0))
        margin_used = float(margin.get("totalMarginUsed", 0))
        withdrawable = float(state.get("withdrawable", 0))

        positions = []
        total_unrealized = 0.0

        for p in state.get("assetPositions", []):
            pos = p.get("position", {})
            coin = pos.get("coin", "")
            size = float(pos.get("szi", 0))
            entry_px = float(pos.get("entryPx", 0))
            mark_px = float(pos.get("markPx", 0))
            unrealized = float(pos.get("unrealizedPnl", 0))
            margin_used_pos = float(pos.get("marginUsed", 0))
            roe = float(pos.get("returnOnEquity", 0))

            if abs(size) > 0:
                total_unrealized += unrealized
                positions.append({
                    "coin": coin,
                    "direction": "LONG" if size > 0 else "SHORT",
                    "size": abs(size),
                    "entry_price": entry_px,
                    "mark_price": mark_px,
                    "unrealized_pnl": unrealized,
                    "margin_used": margin_used_pos,
                    "roe_pct": roe * 100,
                })

        # Get open orders
        try:
            orders = info.frontend_open_orders(address)
        except Exception:
            orders = info.open_orders(address)

        # Categorize orders
        buy_orders = [o for o in orders if o.get("side") == "B"]
        sell_orders = [o for o in orders if o.get("side") == "A"]
        reduce_orders = [o for o in orders if o.get("reduceOnly")]
        resting_orders = [o for o in orders if not o.get("reduceOnly")]

        return {
            "label": label,
            "address": address,
            "equity": equity,
            "margin_used": margin_used,
            "free_margin": equity - margin_used,
            "withdrawable": withdrawable,
            "unrealized_pnl": total_unrealized,
            "positions": positions,
            "open_orders": len(orders),
            "buy_orders": len(buy_orders),
            "sell_orders": len(sell_orders),
            "reduce_orders": len(reduce_orders),
            "resting_orders": len(resting_orders),
            "orders_detail": orders[:20],  # Keep raw for JSON mode
        }
    except Exception as e:
        return {
            "label": label,
            "address": address,
            "error": str(e),
            "equity": 0,
            "positions": [],
            "open_orders": 0,
        }


def get_account_state_with_spot(info: Info, address: str, label: str) -> dict:
    """Query account state, including spot USDC for sub-accounts."""
    state = get_account_state(info, address, label)

    # For sub-accounts with unified accounts, add spot USDC to equity
    if state.get("equity", 0) == 0 and "error" not in state:
        try:
            spot = info.spot_user_state(address)
            spot_usdc = 0.0
            for b in spot.get("balances", []):
                if b.get("coin") == "USDC":
                    spot_usdc += float(b.get("total", 0))
            if spot_usdc > 0:
                state["equity"] = spot_usdc
                state["free_margin"] = spot_usdc
                state["spot_usdc"] = spot_usdc
        except Exception:
            pass

    return state


def get_mid_prices(info: Info) -> dict:
    """Get current mid prices for all assets."""
    try:
        all_mids = info.all_mids()
        return {coin: float(all_mids.get(coin, 0)) for coin in ASSETS}
    except Exception:
        return {}


def format_currency(val: float, prefix: str = "$") -> str:
    """Format a currency value with sign."""
    if val >= 0:
        return f"{prefix}{val:>+.2f}"
    return f"{prefix}{val:>+.2f}"


def print_report(parent_state: dict, sub_state: dict, prices: dict, bot_statuses: dict):
    """Print a formatted status report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    total_equity = parent_state.get("equity", 0) + sub_state.get("equity", 0)
    total_unrealized = parent_state.get("unrealized_pnl", 0) + sub_state.get("unrealized_pnl", 0)
    total_orders = parent_state.get("open_orders", 0) + sub_state.get("open_orders", 0)
    total_positions = len(parent_state.get("positions", [])) + len(sub_state.get("positions", []))

    print()
    print("╔" + "═" * 68 + "╗")
    print(f"║  🤖 HYPERLIQUID COMBINED BOT STATUS — {now:<37}║")
    print("╠" + "═" * 68 + "╣")

    # ── Combined summary ─────────────────────────────────────────────
    print(f"║  Total Equity:       {format_currency(total_equity):>12}                         ║")
    print(f"║  Total Unrealized:   {format_currency(total_unrealized):>12}                         ║")
    print(f"║  Total Positions:    {total_positions:>12}    Total Orders: {total_orders:<8}        ║")
    print("╠" + "═" * 68 + "╣")

    # ── Bot process status ───────────────────────────────────────────
    print(f"║  📡 BOT PROCESSES:                                             ║")
    for bot_name, status in bot_statuses.items():
        icon = "✅" if status == "RUNNING" else "🔴"
        print(f"║    {icon} {bot_name:<25} {status:<34}║")
    print("╠" + "═" * 68 + "╣")

    # ── Current prices ───────────────────────────────────────────────
    price_str = "  ".join(f"{c} ${prices.get(c, 0):.2f}" for c in ASSETS)
    print(f"║  💰 Prices: {price_str:<52}║")
    print("╠" + "═" * 68 + "╣")

    # ── Scalper bot (parent) ─────────────────────────────────────────
    print(f"║  📈 SCALPER + MM BOT (Parent Account — shared)                 ║")
    print(f"║     Equity:     {format_currency(parent_state.get('equity', 0)):>12}    "
          f"Free Margin: {format_currency(parent_state.get('free_margin', 0)):>10}       ║")
    print(f"║     Unrealized: {format_currency(parent_state.get('unrealized_pnl', 0)):>12}    "
          f"Orders: {parent_state.get('open_orders', 0):>3}  "
          f"(B:{parent_state.get('buy_orders', 0)} S:{parent_state.get('sell_orders', 0)})       ║")

    if parent_state.get("positions"):
        print(f"║     ── Open Positions ──                                       ║")
        for pos in parent_state["positions"]:
            pnl_str = format_currency(pos["unrealized_pnl"])
            roe_str = f"({pos['roe_pct']:+.1f}% ROE)"
            print(f"║     {pos['direction']:>5} {pos['coin']:<5} size={pos['size']:<12.4f} "
                  f"entry=${pos['entry_price']:<10.2f} mark=${pos['mark_price']:<10.2f} "
                  f"PnL={pnl_str:>8} {roe_str:>10}  ║")
    else:
        print(f"║     No open positions                                          ║")
    print("╠" + "═" * 68 + "╣")

    # ── Market maker bot (sub-account) ───────────────────────────────
    print(f"║  🤖 MARKET MAKER BOT (Sub-Account)                             ║")
    print(f"║     Equity:     {format_currency(sub_state.get('equity', 0)):>12}    "
          f"Free Margin: {format_currency(sub_state.get('free_margin', 0)):>10}       ║")
    print(f"║     Unrealized: {format_currency(sub_state.get('unrealized_pnl', 0)):>12}    "
          f"Orders: {sub_state.get('open_orders', 0):>3}  "
          f"(B:{sub_state.get('buy_orders', 0)} S:{sub_state.get('sell_orders', 0)})       ║")

    if sub_state.get("positions"):
        print(f"║     ── Open Positions ──                                       ║")
        for pos in sub_state["positions"]:
            pnl_str = format_currency(pos["unrealized_pnl"])
            roe_str = f"({pos['roe_pct']:+.1f}% ROE)"
            print(f"║     {pos['direction']:>5} {pos['coin']:<5} size={pos['size']:<12.4f} "
                  f"entry=${pos['entry_price']:<10.2f} mark=${pos['mark_price']:<10.2f} "
                  f"PnL={pnl_str:>8} {roe_str:>10}  ║")
    else:
        print(f"║     No open positions (flat)                                   ║")

    # Show MM order book if there are resting orders
    if sub_state.get("open_orders", 0) > 0 and sub_state.get("orders_detail"):
        print(f"║     ── Resting Quotes ({sub_state['open_orders']} orders) ──                 ║")
        for o in sub_state["orders_detail"][:10]:
            coin = o.get("coin", "")
            side = "BID" if o.get("side") == "B" else "ASK"
            sz = float(o.get("sz", 0))
            px = float(o.get("limitPx", 0))
            reduce = " (reduce)" if o.get("reduceOnly") else ""
            print(f"║       {coin:<5} {side:>3} {sz:<10.4f} @ ${px:<10.2f}{reduce:<16}        ║")

    print("╚" + "═" * 68 + "╝")
    print()


def get_bot_status(service_name: str) -> str:
    """Check if a systemd user service is running."""
    import subprocess
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", service_name],
            capture_output=True, text=True, timeout=5,
        )
        if result.stdout.strip() == "active":
            return "RUNNING"
        elif result.stdout.strip() == "inactive":
            return "STOPPED"
        elif result.stdout.strip() == "failed":
            return "FAILED"
        return result.stdout.strip().upper()
    except Exception:
        return "UNKNOWN"


def main():
    watch = "--watch" in sys.argv
    json_mode = "--json" in sys.argv

    info = Info(constants.MAINNET_API_URL, skip_ws=True)

    def run_once():
        # Both bots run on the same parent account (different coins)
        # Show unified status with both bots' activity
        parent = get_account_state(info, PARENT_ADDRESS, "Combined (Parent)")
        sub = get_account_state_with_spot(info, SUB_ACCOUNT, "Sub-Account (Unused)")
        prices = get_mid_prices(info)

        bot_statuses = {
            "Scalper Bot": get_bot_status("hl-scalper-bot.service"),
            "MM Bot": get_bot_status("hl-mm-bot.service"),
        }

        if json_mode:
            output = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "prices": prices,
                "bot_statuses": bot_statuses,
                "scalper": parent,
                "market_maker": sub,
                "combined": {
                    "total_equity": parent.get("equity", 0) + sub.get("equity", 0),
                    "total_unrealized": parent.get("unrealized_pnl", 0) + sub.get("unrealized_pnl", 0),
                    "total_positions": len(parent.get("positions", [])) + len(sub.get("positions", [])),
                    "total_orders": parent.get("open_orders", 0) + sub.get("open_orders", 0),
                },
            }
            print(json.dumps(output, indent=2, default=str))
        else:
            print_report(parent, sub, prices, bot_statuses)

    if watch:
        try:
            while True:
                run_once()
                time.sleep(30)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        run_once()


if __name__ == "__main__":
    main()