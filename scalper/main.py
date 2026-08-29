#!/usr/bin/env python3
"""
main.py — Hyperliquid Scalping Bot Entry Point
Supports Unified Account Mode with combined Spot + Perp balance display
"""

import argparse
import sys
import os
import json
import requests
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from eth_account import Account

# Load environment variables
load_dotenv()

# ═══════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════

API_URL = "https://api.hyperliquid.xyz/info"
TESTNET_API_URL = "https://api.hyperliquid-testnet.xyz/info"

BOT_DIR = Path(__file__).parent


# ═══════════════════════════════════════════════════════════════
# ACCOUNT BALANCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def fetch_account_data(wallet: str, testnet: bool = False) -> tuple:
    """Fetch perp and spot account data from Hyperliquid API"""
    api = TESTNET_API_URL if testnet else API_URL
    
    headers = {"Content-Type": "application/json"}
    
    # Fetch perp state
    perp_response = requests.post(
        api,
        headers=headers,
        json={"type": "clearinghouseState", "user": wallet},
        timeout=10
    )
    perp_data = perp_response.json()
    
    # Fetch spot state
    spot_response = requests.post(
        api,
        headers=headers,
        json={"type": "spotClearinghouseState", "user": wallet},
        timeout=10
    )
    spot_data = spot_response.json()
    
    # Fetch all mids for price data
    mids_response = requests.post(
        api,
        headers=headers,
        json={"type": "allMids"},
        timeout=10
    )
    mids_data = mids_response.json()
    
    return perp_data, spot_data, mids_data


def print_account_summary(wallet: str, testnet: bool = False):
    """
    Print complete account summary supporting Unified Account Mode.
    Shows combined Spot + Perp balances.
    """
    try:
        perp, spot, mids = fetch_account_data(wallet, testnet)
    except Exception as e:
        print(f"\n❌ Failed to fetch account data: {e}")
        return None
    
    # Determine account mode
    is_unified = 'crossMarginSummary' in perp
    margin = perp.get('crossMarginSummary') or perp.get('marginSummary', {})
    
    # Perp values
    perp_value = float(margin.get('accountValue', 0))
    margin_used = float(margin.get('totalMarginUsed', 0))
    total_ntl_pos = float(margin.get('totalNtlPos', 0))
    available = perp_value - margin_used
    withdrawable = float(perp.get('withdrawable', '0'))
    
    # Spot balances
    spot_balances = spot.get('balances', [])
    spot_total_usd = 0
    spot_holdings = []
    
    for b in spot_balances:
        coin = b.get('coin', '?')
        total = float(b.get('total', 0))
        hold = float(b.get('hold', 0))
        
        if total < 0.0001:
            continue
        
        # Calculate USD value
        if coin == 'USDC':
            usd_value = total
        elif coin in mids:
            usd_value = total * float(mids[coin])
        else:
            usd_value = 0
        
        spot_total_usd += usd_value
        spot_holdings.append({
            'coin': coin,
            'total': total,
            'hold': hold,
            'usd_value': usd_value
        })
    
    # Sort by USD value
    spot_holdings.sort(key=lambda x: x['usd_value'], reverse=True)
    
    # Calculate total funds based on mode
    if is_unified:
        total_funds = perp_value  # Spot USDC already included
        note = '(Spot USDC included in Account Value)'
    else:
        total_funds = perp_value + spot_total_usd
        note = '(Spot + Perp separate)'
    
    # Parse positions
    positions = perp.get('assetPositions', [])
    open_pos = [p for p in positions if abs(float(p.get('position', {}).get('szi', 0))) > 0]
    
    total_upnl = sum(float(p.get('position', {}).get('unrealizedPnl', 0)) for p in open_pos)
    
    # Get wallet short form
    wallet_short = f"{wallet[:6]}...{wallet[-4:]}"
    mode_str = "UNIFIED (Cross Margin)" if is_unified else "SEPARATE SPOT/PERP"
    network = "TESTNET" if testnet else "MAINNET"
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    
    # ═══════════════════════════════════════════════════════════
    # PRINT OUTPUT
    # ═══════════════════════════════════════════════════════════
    
    print()
    print('╔═══════════════════════════════════════════════════════════════╗')
    print('║           HYPERLIQUID COMPLETE ACCOUNT SUMMARY                ║')
    print('╠═══════════════════════════════════════════════════════════════╣')
    print(f'║  Wallet:    {wallet_short:<50} ║')
    print(f'║  Network:   {network:<50} ║')
    print(f'║  Mode:      {mode_str:<50} ║')
    print(f'║  Timestamp: {timestamp:<50} ║')
    print('╠═══════════════════════════════════════════════════════════════╣')
    print('║                        ACCOUNT VALUE                          ║')
    print('╠═══════════════════════════════════════════════════════════════╣')
    print(f'║  💎 Total Funds:         ${total_funds:>14,.2f}                     ║')
    print(f'║  📊 Perp Account Value:  ${perp_value:>14,.2f}                     ║')
    print(f'║  🔒 Margin Used:         ${margin_used:>14,.2f}                     ║')
    print(f'║  🟢 Available Margin:    ${available:>14,.2f}                     ║')
    print(f'║  💵 Withdrawable:        ${withdrawable:>14,.2f}                     ║')
    print(f'║  📈 Notional Exposure:   ${abs(total_ntl_pos):>14,.2f}                     ║')
    
    if total_upnl != 0:
        upnl_emoji = '🟢' if total_upnl >= 0 else '🔴'
        print(f'║  {upnl_emoji} Unrealized PnL:       ${total_upnl:>+14,.2f}                     ║')
    
    print('╠═══════════════════════════════════════════════════════════════╣')
    print('║                        SPOT WALLET                            ║')
    print('╠═══════════════════════════════════════════════════════════════╣')
    
    if spot_holdings:
        print(f'║  💰 Spot Total Value:    ${spot_total_usd:>14,.2f}                     ║')
        print('║  ─────────────────────────────────────────────────────────── ║')
        print('║  Token        Amount            Hold       USD Value         ║')
        print('║  ─────────────────────────────────────────────────────────── ║')
        for h in spot_holdings:
            coin = h['coin']
            total = h['total']
            hold = h['hold']
            usd = h['usd_value']
            
            # Format based on size
            if total >= 1000:
                amt_str = f"{total:>14,.2f}"
            elif total >= 1:
                amt_str = f"{total:>14,.4f}"
            else:
                amt_str = f"{total:>14,.6f}"
            
            hold_str = f"{hold:>10,.4f}" if hold > 0 else "        —"
            
            print(f'║  {coin:<10}  {amt_str}  {hold_str}   ${usd:>10,.2f}      ║')
    else:
        print('║  (No spot holdings)                                          ║')
    
    print('╠═══════════════════════════════════════════════════════════════╣')
    print('║                      OPEN POSITIONS                           ║')
    print('╠═══════════════════════════════════════════════════════════════╣')
    
    if open_pos:
        for p in open_pos:
            pos = p.get('position', {})
            coin = pos.get('coin', '?')
            size = float(pos.get('szi', 0))
            entry = float(pos.get('entryPx', 0))
            mark = float(pos.get('markPx', entry))
            upnl = float(pos.get('unrealizedPnl', 0))
            liq = pos.get('liquidationPx')
            margin_pos = float(pos.get('marginUsed', 0))
            roe = float(pos.get('returnOnEquity', 0)) * 100
            
            lev = pos.get('leverage', {})
            if isinstance(lev, dict):
                lev_val = lev.get('value', '?')
                lev_type = lev.get('type', 'cross')
            else:
                lev_val = lev if lev else '?'
                lev_type = 'cross'
            
            side = 'LONG' if size > 0 else 'SHORT'
            emoji = '🟢' if upnl >= 0 else '🔴'
            notional = abs(size * mark)
            
            print(f'║  {emoji} {side:<5} {coin:<6}                                           ║')
            print(f'║     Size:        {abs(size):<12,.6f}  (~${notional:>10,.2f} notional)   ║')
            print(f'║     Entry:       ${entry:>12,.2f}                                 ║')
            print(f'║     Mark:        ${mark:>12,.2f}                                 ║')
            print(f'║     uPnL:        ${upnl:>+12,.2f}  ({roe:>+6.1f}% ROE)            ║')
            print(f'║     Margin:      ${margin_pos:>12,.2f}                                 ║')
            print(f'║     Leverage:    {str(lev_val) + "x":<12}   ({lev_type})                   ║')
            if liq:
                liq_price = float(liq)
                liq_dist = abs(mark - liq_price) / mark * 100 if mark > 0 else 0
                print(f'║     Liquidation: ${liq_price:>12,.2f}  ({liq_dist:.1f}% away)              ║')
            print('║  ─────────────────────────────────────────────────────────── ║')
    else:
        print('║  (No open positions)                                         ║')
    
    print('╠═══════════════════════════════════════════════════════════════╣')
    print(f'║  ℹ️  {note:<56} ║')
    print('╚═══════════════════════════════════════════════════════════════╝')
    print()
    
    return {
        'total_funds': total_funds,
        'perp_value': perp_value,
        'available': available,
        'margin_used': margin_used,
        'positions': len(open_pos),
        'is_unified': is_unified,
    }


def get_wallet_from_key(private_key: str = None) -> str:
    """Get wallet address from private key"""
    if private_key is None:
        private_key = os.getenv('HL_PRIVATE_KEY')
    
    if not private_key:
        print("❌ HL_PRIVATE_KEY not set in .env file")
        sys.exit(1)
    
    account = Account.from_key(private_key)
    return account.address


# ═══════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='Hyperliquid Autonomous Scalping Bot',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 main.py                     # Run on mainnet with defaults
  python3 main.py --testnet           # Run on testnet
  python3 main.py --leverage 5        # Use 5x leverage
  python3 main.py --balance           # Show balance only, don't start bot
  python3 main.py --wallet 0x123...   # Check specific wallet balance
        """
    )
    
    parser.add_argument(
        '--testnet', '-t',
        action='store_true',
        help='Run on testnet instead of mainnet'
    )
    
    parser.add_argument(
        '--leverage', '-l',
        type=int,
        default=None,
        help='Override default leverage (default: from config)'
    )
    
    parser.add_argument(
        '--assets', '-a',
        type=str,
        nargs='+',
        default=None,
        help='Assets to trade (default: BTC ETH SOL ZEC XRP PAXG)'
    )
    
    parser.add_argument(
        '--balance', '-b',
        action='store_true',
        help='Show account balance only, do not start the bot'
    )
    
    parser.add_argument(
        '--wallet', '-w',
        type=str,
        default=None,
        help='Wallet address to check (default: from .env private key)'
    )
    
    parser.add_argument(
        '--dry-run', '-d',
        action='store_true',
        help='Dry run mode — generate signals but do not execute trades'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # ═══════════════════════════════════════════════════════════
    # LOAD CONFIG
    # ═══════════════════════════════════════════════════════════
    
    from config import BotConfig
    config = BotConfig()
    
    # Determine wallet
    parent_wallet = os.getenv("HL_PARENT_ADDRESS", "0xYOUR_PARENT_WALLET_ADDRESS")
    
    if args.wallet:
        wallet = args.wallet
    else:
        # Objective: Track and grow the Parent Account
        wallet = parent_wallet
        print(f"🎯 Objective: Tracking Parent Account balance ({wallet[:8]}...)")
    
    # Determine if testnet
    is_testnet = args.testnet or (not config.use_mainnet)
    
    # ═══════════════════════════════════════════════════════════
    # BALANCE CHECK MODE
    # ═══════════════════════════════════════════════════════════
    
    if args.balance:
        print_account_summary(wallet, testnet=is_testnet)
        return
    
    # ═══════════════════════════════════════════════════════════
    # STARTUP BANNER
    # ═══════════════════════════════════════════════════════════
    
    print()
    print('╔══════════════════════════════════════════════════════════════╗')
    print('║                                                              ║')
    print('║     ██╗  ██╗██╗   ██╗██████╗ ███████╗██████╗                ║')
    print('║     ██║  ██║╚██╗ ██╔╝██╔══██╗██╔════╝██╔══██╗               ║')
    print('║     ███████║ ╚████╔╝ ██████╔╝█████╗  ██████╔╝               ║')
    print('║     ██╔══██║  ╚██╔╝  ██╔═══╝ ██╔══╝  ██╔══██╗               ║')
    print('║     ██║  ██║   ██║   ██║     ███████╗██║  ██║               ║')
    print('║     ╚═╝  ╚═╝   ╚═╝   ╚═╝     ╚══════╝╚═╝  ╚═╝               ║')
    print('║                                                              ║')
    print('║         AUTONOMOUS SCALPING BOT v1.0                         ║')
    print('║                                                              ║')
    print('╚══════════════════════════════════════════════════════════════╝')
    print()
    
    # ═══════════════════════════════════════════════════════════
    # SHOW ACCOUNT SUMMARY BEFORE STARTING
    # ═══════════════════════════════════════════════════════════
    
    print("🔍 Fetching account status...")
    account_info = print_account_summary(wallet, testnet=is_testnet)
    
    if not account_info:
        print("❌ Failed to fetch account data. Check your connection and wallet address.")
        sys.exit(1)
    
    # Warn if low balance
    if account_info['total_funds'] < 10:
        print("⚠️  WARNING: Low account balance. Consider depositing more funds.")
        print()
    
    # Warn if unified mode not enabled
    if not account_info['is_unified']:
        print("💡 TIP: Enable Unified Account Mode on Hyperliquid for better margin efficiency.")
        print("   Go to app.hyperliquid.xyz → Settings → Enable Cross Margin")
        print()
    
    # ═══════════════════════════════════════════════════════════
    # APPLY COMMAND LINE OVERRIDES
    # ═══════════════════════════════════════════════════════════
    
    # Get asset list from config (it's a dict)
    asset_names = list(config.assets.keys())
    
    if args.testnet:
        config.use_mainnet = False
    
    if args.leverage:
        config.leverage = args.leverage
        print(f"⚙️  Leverage override: {args.leverage}x")
    
    if args.assets:
        # Filter to only requested assets
        requested = [a.upper() for a in args.assets]
        config.assets = {k: v for k, v in config.assets.items() if k in requested}
        asset_names = list(config.assets.keys())
        print(f"⚙️  Assets override: {', '.join(asset_names)}")
    
    if args.verbose:
        config.verbose = True
        import logging
        logging.getLogger().setLevel(logging.DEBUG)
        print("⚙️  Verbose logging enabled")
    
    print()
    
    # ═══════════════════════════════════════════════════════════
    # CONFIGURATION DISPLAY
    # ═══════════════════════════════════════════════════════════
    
    network = "TESTNET" if is_testnet else "MAINNET"
    
    # Build per-asset TP/SL summary string
    asset_tp_sl_lines = []
    for aname, acfg in config.assets.items():
        asset_tp_sl_lines.append(
            f'│  {aname:<8}  TP {acfg.take_profit_pct*100:.1f}%  SL {acfg.stop_loss_pct*100:.1f}%'
            f'  size {acfg.position_size_pct*100:.0f}%  score>={acfg.min_signal_score}'
        )

    print('┌────────────────────────────────────────────────────────────┐')
    print('│                    CONFIGURATION                          │')
    print('├────────────────────────────────────────────────────────────┤')
    print(f'│  Network:       {network:<42} │')
    print(f'│  Wallet:        {wallet[:8]}...{wallet[-4:]:<32} │')
    print(f'│  Assets:        {", ".join(asset_names):<42} │')
    print(f'│  Leverage:      {config.leverage}x{" " * 40} │')
    print(f'│  Max Position:  {config.max_position_pct * 100:.0f}% of equity{" " * 27} │')
    print(f'│  Max Positions: {config.max_concurrent_positions} concurrent{" " * 28} │')
    print(f'│  Cross Margin:  {"Yes" if config.cross_margin else "No":<42} │')
    print(f'│  Dry Run:       {"Yes" if args.dry_run else "No":<42} │')
    print('├────────────────────────────────────────────────────────────┤')
    print('│  Asset     TP     SL     Size    Min Score                │')
    for line in asset_tp_sl_lines:
        print(f'{line:<61} │')
    print('└────────────────────────────────────────────────────────────┘')
    print()
    
    # ═══════════════════════════════════════════════════════════
    # CONFIRMATION
    # ═══════════════════════════════════════════════════════════
    # Skip confirmation if running as a service (no TTY)
    import sys
    is_interactive = sys.stdin.isatty()
    
    if config.use_mainnet and not args.dry_run and is_interactive:
        print("⚠️  WARNING: You are about to start LIVE TRADING on MAINNET!")
        print("   Real money will be at risk.")
        print()
        try:
            confirm = input("   Type 'yes' to confirm and start: ").strip().lower()
            if confirm != 'yes':
                print("\n❌ Aborted. Bot not started.")
                sys.exit(0)
        except KeyboardInterrupt:
            print("\n\n❌ Aborted.")
            sys.exit(0)
        print()
    elif config.use_mainnet and not args.dry_run:
        print("⚠️  Running on MAINNET (service mode - no confirmation required)")
        print()
    
    # ═══════════════════════════════════════════════════════════
    # START THE BOT
    # ═══════════════════════════════════════════════════════════
    
    try:
        print("🚀 Starting bot...")
        print("   Press Ctrl+C to stop gracefully (positions will be closed)")
        print()
        
        # Import and start the bot
        from bot import HyperliquidScalper
        
        bot = HyperliquidScalper(config)
        bot.run()
        
    except KeyboardInterrupt:
        print("\n\n🛑 Interrupted by user")
    except ImportError as e:
        print(f"\n❌ Failed to import bot module: {e}")
        print("   Check that bot.py exists and has no syntax errors:")
        print("   python3 -m py_compile bot.py")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# QUICK BALANCE CHECK (can be imported)
# ═══════════════════════════════════════════════════════════════

def check_balance(wallet: str = None, testnet: bool = False):
    """
    Quick balance check function that can be called from other scripts.
    
    Usage:
        from main import check_balance
        check_balance()  # Uses wallet from .env
        check_balance("0x123...")  # Specific wallet
    """
    if wallet is None:
        wallet = get_wallet_from_key()
    
    return print_account_summary(wallet, testnet=testnet)


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()