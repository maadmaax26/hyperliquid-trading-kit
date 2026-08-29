#!/usr/bin/env python3
"""
Lightweight equity snapshot script for the HL monitor cron job's change detector.
Outputs a single line: EQUITY=<value> FREE=<value> POSITIONS=<count> UPNL=<value>
Deterministic output — used as a monitor script for change detection.
"""
import sys, os, json
from datetime import datetime, timezone
sys.path.insert(0, "/home/efinney/hyperliquid-mm-bot")
from dotenv import load_dotenv
load_dotenv("/home/efinney/hyperliquid-mm-bot/.env")
from hyperliquid.info import Info
from hyperliquid.utils import constants

PARENT = "0xYOUR_PARENT_WALLET_ADDRESS"

info = Info(constants.MAINNET_API_URL, skip_ws=True)
state = info.user_state(PARENT)
margin = state.get("crossMarginSummary", state.get("marginSummary", {}))
equity = float(margin.get("accountValue", 0))
margin_used = float(margin.get("totalMarginUsed", 0))
free = equity - margin_used

positions = 0
upnl = 0.0
for p in state.get("assetPositions", []):
    pos = p.get("position", {})
    sz = float(pos.get("szi", 0))
    if abs(sz) > 0:
        positions += 1
        upnl += float(pos.get("unrealizedPnl", 0))

# Also check bot services
import subprocess
def svc_active(name):
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", name],
                          capture_output=True, text=True, timeout=3)
        return r.stdout.strip()
    except:
        return "unknown"

scalper = svc_active("hl-scalper-bot.service")
mm = svc_active("hl-mm-bot.service")

print(f"EQUITY={equity:.2f} FREE={free:.2f} POSITIONS={positions} UPNL={upnl:.2f} SCALPER={scalper} MM={mm}")