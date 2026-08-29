#!/usr/bin/env python3
"""
Hyperliquid Performance Monitor & Adjustment Advisor

Tracks equity history, detects drawdowns, and generates actionable alerts
when the account balance is decreasing. Designed to run via cron job.

Outputs a diagnostic report when:
  - Equity drops below a rolling baseline
  - A bot is losing money consistently
  - Position risk is too high
  - A bot service has crashed

Usage:
  python3 hl_monitor.py                # Run check, print report
  python3 hl_monitor.py --json         # JSON output for logging
  python3 hl_monitor.py --alert-only   # Only print if alert triggered

Data files (in /home/efinney/hyperliquid-mm-bot/):
  monitor_equity_history.json  - Time series of equity snapshots
  monitor_alerts.log           - Append-only log of triggered alerts
"""

import sys
import os
import json
import time
import subprocess
from datetime import datetime, timezone, timedelta

# Add both bot dirs to path
sys.path.insert(0, "/home/efinney/hyperliquid-mm-bot")

from dotenv import load_dotenv
load_dotenv("/home/efinney/hyperliquid-mm-bot/.env")

from hyperliquid.info import Info
from hyperliquid.utils import constants

# ── Configuration ────────────────────────────────────────────────────
import os
from dotenv import load_dotenv
load_dotenv()

PARENT_ADDRESS = os.getenv("HL_PARENT_ADDRESS", os.getenv("PARENT_ADDRESS", "0xYOUR_PARENT_WALLET_ADDRESS"))
SCALPER_COINS = ["BTC", "ETH", "SOL", "XRP", "ZEC", "PAXG"]
MM_COINS = ["kPEPE", "kBONK", "ARB"]
ALL_COINS = SCALPER_COINS + MM_COINS

BASE_DIR = "/home/efinney/hyperliquid-mm-bot"
EQUITY_HISTORY_FILE = os.path.join(BASE_DIR, "monitor_equity_history.json")
ALERTS_LOG = os.path.join(BASE_DIR, "monitor_alerts.log")
SCALPER_TRADES = "/home/efinney/hyperliquid-scalper/trades.json"

# Alert thresholds
DRAWDOWN_ALERT_PCT = 5.0        # Alert if equity drops 5% from peak
DRAWDOWN_CRITICAL_PCT = 10.0    # Critical alert at 10% drop
DAILY_LOSS_ALERT_PCT = 3.0      # Alert if down 3% in 24h
DAILY_LOSS_CRITICAL_PCT = 5.0   # Critical if down 5% in 24h
STALE_BOT_THRESHOLD_S = 300     # Bot service down >5 min = alert
MAX_HISTORY_POINTS = 10000      # Cap equity history file size


def load_equity_history() -> list:
    """Load equity history from JSON file."""
    try:
        with open(EQUITY_HISTORY_FILE, "r") as f:
            return json.loads(f.read())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_equity_history(history: list):
    """Save equity history, capping size."""
    if len(history) > MAX_HISTORY_POINTS:
        history = history[-MAX_HISTORY_POINTS:]
    with open(EQUITY_HISTORY_FILE, "w") as f:
        f.write(json.dumps(history, indent=2))


def log_alert(severity: str, title: str, details: str, recommendations: list):
    """Log an alert to the alerts log file."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    entry = f"""
{'='*70}
[{severity}] {title}
Time: {now}
{'='*70}
{details}

Recommendations:
"""
    for i, rec in enumerate(recommendations, 1):
        entry += f"  {i}. {rec}\n"
    entry += f"{'='*70}\n\n"

    with open(ALERTS_LOG, "a") as f:
        f.write(entry)
    return entry


def get_account_state(info: Info) -> dict:
    """Query full account state from Hyperliquid."""
    try:
        state = info.user_state(PARENT_ADDRESS)
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
            margin_pos = float(pos.get("marginUsed", 0))
            roe = float(pos.get("returnOnEquity", 0))

            if abs(size) > 0:
                total_unrealized += unrealized
                is_scalper = coin in SCALPER_COINS
                is_mm = coin in MM_COINS
                positions.append({
                    "coin": coin,
                    "direction": "LONG" if size > 0 else "SHORT",
                    "size": abs(size),
                    "entry_price": entry_px,
                    "mark_price": mark_px,
                    "unrealized_pnl": unrealized,
                    "margin_used": margin_pos,
                    "roe_pct": roe * 100,
                    "bot": "SCALPER" if is_scalper else ("MM" if is_mm else "UNKNOWN"),
                })

        # Spot USDC
        spot_usdc = 0.0
        try:
            spot = info.spot_user_state(PARENT_ADDRESS)
            for b in spot.get("balances", []):
                if b.get("coin") == "USDC":
                    spot_usdc += float(b.get("total", 0))
        except Exception:
            pass

        return {
            "equity": equity,
            "margin_used": margin_used,
            "free_margin": equity - margin_used,
            "withdrawable": withdrawable,
            "unrealized_pnl": total_unrealized,
            "spot_usdc": spot_usdc,
            "positions": positions,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"error": str(e), "equity": 0, "positions": []}


def get_bot_status(service_name: str) -> dict:
    """Check systemd service status."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", service_name],
            capture_output=True, text=True, timeout=5,
        )
        status = result.stdout.strip()
        active = status == "active"

        # Get last log line
        log_result = subprocess.run(
            ["journalctl", "--user", "-u", service_name, "--no-pager", "-n", "1",
             "--since", "10 min ago"],
            capture_output=True, text=True, timeout=5,
        )
        last_log = log_result.stdout.strip().split("\n")[-1] if log_result.stdout.strip() else ""

        return {
            "status": status.upper(),
            "active": active,
            "last_log": last_log[:200],
        }
    except Exception as e:
        return {"status": "UNKNOWN", "active": False, "error": str(e)}


def get_scalper_trades() -> list:
    """Load scalper trade history."""
    try:
        with open(SCALPER_TRADES, "r") as f:
            return json.loads(f.read())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def analyze_performance(account: dict, history: list, bot_statuses: dict) -> dict:
    """Analyze performance and identify issues."""
    now = datetime.now(timezone.utc)
    current_equity = account.get("equity", 0)
    positions = account.get("positions", [])
    alerts = []
    metrics = {}

    # ── Equity trend analysis ────────────────────────────────────────
    if history:
        # Peak equity (rolling max)
        peak_equity = max(h.get("equity", 0) for h in history)
        trough_equity = min(h.get("equity", 0) for h in history)

        # Current drawdown from peak
        if peak_equity > 0:
            drawdown_pct = (peak_equity - current_equity) / peak_equity * 100
        else:
            drawdown_pct = 0
        metrics["peak_equity"] = peak_equity
        metrics["trough_equity"] = trough_equity
        metrics["current_equity"] = current_equity
        metrics["drawdown_from_peak_pct"] = drawdown_pct

        # 24h change
        cutoff_24h = (now - timedelta(hours=24)).isoformat()
        points_24h = [h for h in history if h.get("timestamp", "") >= cutoff_24h]
        if points_24h:
            equity_24h_ago = points_24h[0].get("equity", current_equity)
            daily_change = current_equity - equity_24h_ago
            daily_change_pct = (daily_change / equity_24h_ago * 100) if equity_24h_ago > 0 else 0
            metrics["equity_24h_ago"] = equity_24h_ago
            metrics["daily_change"] = daily_change
            metrics["daily_change_pct"] = daily_change_pct

            if daily_change_pct <= -DAILY_LOSS_CRITICAL_PCT:
                alerts.append({
                    "severity": "CRITICAL",
                    "title": f"Daily Loss: {daily_change_pct:.1f}% (${daily_change:.2f})",
                    "details": f"Equity dropped from ${equity_24h_ago:.2f} to ${current_equity:.2f} "
                               f"in 24h ({daily_change_pct:.1f}%). This exceeds the {DAILY_LOSS_CRITICAL_PCT}% critical threshold.",
                    "recommendations": [
                        "Check if a bot has runaway losses — review journalctl logs",
                        "Verify TP/SL orders are being placed correctly on exchange",
                        "Consider stopping the losing bot until cause is identified",
                        "Review recent trades for pattern (same coin losing repeatedly?)",
                    ],
                })
            elif daily_change_pct <= -DAILY_LOSS_ALERT_PCT:
                alerts.append({
                    "severity": "WARNING",
                    "title": f"Daily Decline: {daily_change_pct:.1f}% (${daily_change:.2f})",
                    "details": f"Equity down {daily_change_pct:.1f}% in 24h "
                               f"(${equity_24h_ago:.2f} → ${current_equity:.2f}).",
                    "recommendations": [
                        "Monitor closely for continued decline",
                        "Check bot logs for errors or rejections",
                        "Review which coins/positions are driving the loss",
                    ],
                })

        # Drawdown from peak
        if drawdown_pct >= DRAWDOWN_CRITICAL_PCT:
            alerts.append({
                "severity": "CRITICAL",
                "title": f"Critical Drawdown: {drawdown_pct:.1f}% from peak",
                "details": f"Peak equity was ${peak_equity:.2f}, current ${current_equity:.2f}. "
                           f"Drawdown of {drawdown_pct:.1f}% exceeds {DRAWDOWN_CRITICAL_PCT}% critical threshold.",
                "recommendations": [
                    "Reduce position sizes immediately (lower order_size_pct)",
                    "Stop the bot that's contributing most to losses",
                    "Close losing positions manually if they exceed risk budget",
                    "Review whether market conditions have changed (high volatility regime?)",
                ],
            })
        elif drawdown_pct >= DRAWDOWN_ALERT_PCT:
            alerts.append({
                "severity": "WARNING",
                "title": f"Drawdown Alert: {drawdown_pct:.1f}% from peak",
                "details": f"Peak ${peak_equity:.2f}, current ${current_equity:.2f}. "
                           f"Drawdown {drawdown_pct:.1f}%.",
                "recommendations": [
                    "Monitor for continued drawdown",
                    "Check if one bot is underperforming significantly",
                    "Consider tightening stops or reducing position size",
                ],
            })

        # 6h trend (short-term momentum)
        cutoff_6h = (now - timedelta(hours=6)).isoformat()
        points_6h = [h for h in history if h.get("timestamp", "") >= cutoff_6h]
        if len(points_6h) >= 3:
            equity_6h_ago = points_6h[0].get("equity", current_equity)
            change_6h = current_equity - equity_6h_ago
            change_6h_pct = (change_6h / equity_6h_ago * 100) if equity_6h_ago > 0 else 0
            metrics["change_6h"] = change_6h
            metrics["change_6h_pct"] = change_6h_pct

            if change_6h_pct <= -2.0:
                alerts.append({
                    "severity": "WARNING",
                    "title": f"Short-term Decline: {change_6h_pct:.1f}% in 6h",
                    "details": f"Equity down ${change_6h:.2f} ({change_6h_pct:.1f}%) in last 6 hours.",
                    "recommendations": [
                        "Check if a specific position is dragging equity",
                        "Verify MM bot is still quoting (not stuck or errored)",
                        "Review scalper trade frequency — is it overtrading?",
                    ],
                })

    # ── Position risk analysis ───────────────────────────────────────
    if positions:
        total_margin = sum(p["margin_used"] for p in positions)
        margin_pct = (total_margin / current_equity * 100) if current_equity > 0 else 0
        metrics["total_margin_used"] = total_margin
        metrics["margin_pct_of_equity"] = margin_pct

        if margin_pct > 80:
            alerts.append({
                "severity": "CRITICAL",
                "title": f"Over-leveraged: {margin_pct:.0f}% margin in use",
                "details": f"${total_margin:.2f} margin used out of ${current_equity:.2f} equity "
                           f"({margin_pct:.0f}%). Free margin is only ${current_equity - total_margin:.2f}.",
                "recommendations": [
                    "Close some positions to free margin",
                    "Reduce order_size_pct in both bots",
                    "Risk of liquidation if price moves against positions",
                ],
            })
        elif margin_pct > 60:
            alerts.append({
                "severity": "WARNING",
                "title": f"High margin usage: {margin_pct:.0f}% of equity",
                "details": f"${total_margin:.2f} margin used ({margin_pct:.0f}% of ${current_equity:.2f}). "
                           f"Free margin: ${current_equity - total_margin:.2f}.",
                "recommendations": [
                    "Monitor position sizes — approaching limit",
                    "Consider reducing order_size_pct if bots try to open more",
                ],
            })

        # Per-position analysis
        for pos in positions:
            if pos["unrealized_pnl"] < -current_equity * 0.03:
                # Single position losing >3% of equity
                alerts.append({
                    "severity": "WARNING",
                    "title": f"Large losing position: {pos['coin']} {pos['direction']} "
                             f"${pos['unrealized_pnl']:.2f} ({pos['roe_pct']:.1f}% ROE)",
                    "details": f"{pos['coin']} {pos['direction']} size={pos['size']:.4f} "
                               f"entry=${pos['entry_price']:.4f} mark=${pos['mark_price']:.4f} "
                               f"uPnL=${pos['unrealized_pnl']:.2f} ({pos['roe_pct']:.1f}% ROE). "
                               f"This single position is down {abs(pos['unrealized_pnl'])/current_equity*100:.1f}% of equity.",
                    "recommendations": [
                        f"Check if {pos['coin']} TP/SL is set correctly",
                        f"Consider manual close if {pos['coin']} continues to deteriorate",
                        "Verify the bot managing this coin is still running",
                    ],
                })

    # ── Bot service health ───────────────────────────────────────────
    for bot_name, status in bot_statuses.items():
        if not status.get("active", False):
            alerts.append({
                "severity": "CRITICAL",
                "title": f"{bot_name} is {status.get('status', 'UNKNOWN')}",
                "details": f"Service is not running. Last log: {status.get('last_log', 'N/A')}",
                "recommendations": [
                    f"Restart: systemctl --user start {'hl-scalper-bot' if 'Scalper' in bot_name else 'hl-mm-bot'}.service",
                    f"Check logs: journalctl --user -u {'hl-scalper-bot' if 'Scalper' in bot_name else 'hl-mm-bot'} -n 50",
                    "Verify no config errors caused crash",
                ],
            })

    # ── Per-bot P&L attribution ───────────────────────────────────────
    scalper_positions = [p for p in positions if p["bot"] == "SCALPER"]
    mm_positions = [p for p in positions if p["bot"] == "MM"]
    scalper_pnl = sum(p["unrealized_pnl"] for p in scalper_positions)
    mm_pnl = sum(p["unrealized_pnl"] for p in mm_positions)
    metrics["scalper_unrealized"] = scalper_pnl
    metrics["mm_unrealized"] = mm_pnl
    metrics["scalper_positions"] = len(scalper_positions)
    metrics["mm_positions"] = len(mm_positions)

    # If one bot is clearly dragging
    if scalper_pnl < -2.0 and mm_pnl > 0:
        alerts.append({
            "severity": "WARNING",
            "title": f"Scalper underperforming MM: Scalper ${scalper_pnl:.2f} vs MM ${mm_pnl:.2f}",
            "details": f"Scalper has {len(scalper_positions)} positions with combined uPnL ${scalper_pnl:.2f}, "
                       f"while MM has {len(mm_positions)} positions with uPnL ${mm_pnl:.2f}.",
            "recommendations": [
                "Review scalper's recent trades — is it counter-trend?",
                "Consider reducing scalper's max_position_pct temporarily",
                "Check if the 1h trend filter is working (should prevent counter-trend entries)",
            ],
        })

    return {"alerts": alerts, "metrics": metrics}


def generate_report(account: dict, analysis: dict, bot_statuses: dict) -> str:
    """Generate human-readable report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    metrics = analysis["metrics"]
    alerts = analysis["alerts"]
    positions = account.get("positions", [])

    lines = []
    lines.append(f"\n{'='*70}")
    lines.append(f"  📊 HYPERLIQUID PERFORMANCE MONITOR — {now}")
    lines.append(f"{'='*70}")

    # Equity summary
    lines.append(f"  Current Equity:     ${metrics.get('current_equity', account.get('equity', 0)):.2f}")
    if "peak_equity" in metrics:
        lines.append(f"  Peak Equity:        ${metrics['peak_equity']:.2f}")
        lines.append(f"  Drawdown from Peak: {metrics.get('drawdown_from_peak_pct', 0):.1f}%")
    if "daily_change" in metrics:
        dc = metrics["daily_change"]
        dcp = metrics["daily_change_pct"]
        arrow = "📈" if dc > 0 else "📉"
        lines.append(f"  24h Change:         {arrow} ${dc:+.2f} ({dcp:+.1f}%)")
    if "change_6h" in metrics:
        lines.append(f"  6h Change:          ${metrics['change_6h']:+.2f} ({metrics['change_6h_pct']:+.1f}%)")
    lines.append(f"  Free Margin:        ${account.get('free_margin', 0):.2f}")
    lines.append(f"  Margin Used:        ${metrics.get('total_margin_used', 0):.2f} "
                 f"({metrics.get('margin_pct_of_equity', 0):.0f}% of equity)")

    # Per-bot P&L
    lines.append(f"{'='*70}")
    lines.append(f"  📈 P&L Attribution:")
    lines.append(f"    Scalper:  {metrics.get('scalper_positions', 0)} positions, "
                 f"uPnL ${metrics.get('scalper_unrealized', 0):+.2f}")
    lines.append(f"    MM Bot:   {metrics.get('mm_positions', 0)} positions, "
                 f"uPnL ${metrics.get('mm_unrealized', 0):+.2f}")

    # Positions
    if positions:
        lines.append(f"{'='*70}")
        lines.append(f"  📋 Open Positions ({len(positions)}):")
        for p in positions:
            pnl = p["unrealized_pnl"]
            icon = "🟢" if pnl > 0 else "🔴"
            lines.append(f"    {icon} {p['bot']:>7} | {p['direction']:>5} {p['coin']:<6} "
                         f"${pnl:+.2f} ({p['roe_pct']:+.1f}% ROE) "
                         f"margin=${p['margin_used']:.2f}")

    # Bot status
    lines.append(f"{'='*70}")
    lines.append(f"  🤖 Bot Services:")
    for name, status in bot_statuses.items():
        icon = "✅" if status.get("active") else "🔴"
        lines.append(f"    {icon} {name}: {status.get('status', 'UNKNOWN')}")

    # Alerts
    if alerts:
        lines.append(f"{'='*70}")
        lines.append(f"  ⚠️  ALERTS ({len(alerts)}):")
        for alert in alerts:
            sev = alert["severity"]
            icon = "🚨" if sev == "CRITICAL" else "⚠️ "
            lines.append(f"    {icon} [{sev}] {alert['title']}")
            lines.append(f"       {alert['details']}")
            lines.append(f"       Recommendations:")
            for i, rec in enumerate(alert["recommendations"], 1):
                lines.append(f"         {i}. {rec}")
    else:
        lines.append(f"{'='*70}")
        lines.append(f"  ✅ No alerts — all systems nominal")

    lines.append(f"{'='*70}\n")
    return "\n".join(lines)


def main():
    alert_only = "--alert-only" in sys.argv
    json_mode = "--json" in sys.argv

    info = Info(constants.MAINNET_API_URL, skip_ws=True)

    # Get current state
    account = get_account_state(info)
    bot_statuses = {
        "Scalper Bot": get_bot_status("hl-scalper-bot.service"),
        "MM Bot": get_bot_status("hl-mm-bot.service"),
    }

    # Update equity history
    history = load_equity_history()
    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "equity": account.get("equity", 0),
        "free_margin": account.get("free_margin", 0),
        "unrealized_pnl": account.get("unrealized_pnl", 0),
        "position_count": len(account.get("positions", [])),
    }
    history.append(snapshot)
    save_equity_history(history)

    # Analyze
    analysis = analyze_performance(account, history, bot_statuses)
    report = generate_report(account, analysis, bot_statuses)

    # Log alerts
    for alert in analysis["alerts"]:
        log_alert(
            alert["severity"], alert["title"],
            alert["details"], alert["recommendations"]
        )

    # Output
    if json_mode:
        output = {
            "timestamp": snapshot["timestamp"],
            "account": account,
            "bot_statuses": bot_statuses,
            "metrics": analysis["metrics"],
            "alerts": analysis["alerts"],
            "alert_count": len(analysis["alerts"]),
            "critical_count": sum(1 for a in analysis["alerts"] if a["severity"] == "CRITICAL"),
            "warning_count": sum(1 for a in analysis["alerts"] if a["severity"] == "WARNING"),
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        if not alert_only or analysis["alerts"]:
            print(report)


if __name__ == "__main__":
    main()