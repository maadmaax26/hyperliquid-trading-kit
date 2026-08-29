#!/usr/bin/env bash
set -euo pipefail

# ════════════════════════════════════════════════════════════════════
#  Hyperliquid Trading Bot Kit — Installation Script
#  Sets up scalper bot, market maker bot, simulator, and monitor
# ════════════════════════════════════════════════════════════════════

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Hyperliquid Trading Bot Kit — Installer                     ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Pre-flight checks ──────────────────────────────────────────────
echo "Step 1: Pre-flight checks..."

if [ -z "$HOME" ]; then
    echo "ERROR: HOME environment variable not set"
    exit 1
fi

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.11+ first."
    exit 1
fi
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  ✓ Python $PY_VER found"

# Check pip/venv
if ! python3 -m venv --help &>/dev/null; then
    echo "ERROR: python3-venv not available. Install with: sudo apt install python3-venv"
    exit 1
fi
echo "  ✓ venv available"

# Determine install location
INSTALL_DIR="${1:-$HOME/hyperliquid-trading-kit}"
if [ "$INSTALL_DIR" = "$HOME/hyperliquid-trading-kit" ] && [ -d "$INSTALL_DIR" ]; then
    echo "  ⚠️  $INSTALL_DIR already exists. Using script location."
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    INSTALL_DIR="$SCRIPT_DIR"
fi
echo "  ✓ Install location: $INSTALL_DIR"

echo ""

# ── Create virtual environments ────────────────────────────────────
echo "Step 2: Creating Python virtual environments..."

# Scalper venv
SCALPER_DIR="$INSTALL_DIR/scalper"
if [ ! -d "$SCALPER_DIR/venv" ]; then
    python3 -m venv "$SCALPER_DIR/venv"
    echo "  ✓ Created scalper venv"
else
    echo "  ✓ Scalper venv exists"
fi

# MM bot venv (shared with simulator + monitor)
MM_DIR="$INSTALL_DIR/market-maker"
if [ ! -d "$MM_DIR/venv" ]; then
    python3 -m venv "$MM_DIR/venv"
    echo "  ✓ Created market-maker venv"
else
    echo "  ✓ Market-maker venv exists"
fi

echo ""

# ── Install dependencies ───────────────────────────────────────────
echo "Step 3: Installing Python dependencies..."

echo "  Installing scalper dependencies..."
"$SCALPER_DIR/venv/bin/pip" install --upgrade pip -q
"$SCALPER_DIR/venv/bin/pip" install -r "$SCALPER_DIR/requirements.txt" -q
echo "  ✓ Scalper dependencies installed"

echo "  Installing market-maker dependencies..."
"$MM_DIR/venv/bin/pip" install --upgrade pip -q
"$MM_DIR/venv/bin/pip" install -r "$MM_DIR/requirements.txt" -q
echo "  ✓ Market-maker dependencies installed"

echo ""

# ── Create .env files ──────────────────────────────────────────────
echo "Step 4: Setting up configuration files..."

setup_env() {
    local env_file="$1"
    local example_file="$2"
    local name="$3"
    
    if [ ! -f "$env_file" ]; then
        cp "$example_file" "$env_file"
        echo "  ⚠️  Created $env_file from template"
        echo "     → Edit $env_file with YOUR wallet details before starting the $name"
    else
        echo "  ✓ $env_file already exists"
    fi
}

setup_env "$SCALPER_DIR/.env" "$SCALPER_DIR/.env.example" "scalper bot"
setup_env "$MM_DIR/.env" "$MM_DIR/.env.example" "market maker bot"

echo ""

# ── Install systemd services ──────────────────────────────────────
echo "Step 5: Setting up systemd user services..."

SYSTEMD_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_DIR"

TEMPLATE_DIR="$INSTALL_DIR/systemd"

# Function to install a service file with path substitution
install_service() {
    local src="$1"
    local dst="$2"
    local name="$3"
    
    if [ -f "$dst" ]; then
        echo "  ✓ $name service already installed"
        return
    fi
    
    # Replace placeholder paths with actual install directory
    sed "s|INSTALL_DIR|$INSTALL_DIR|g" "$src" > "$dst"
    echo "  ✓ Installed $name service → $dst"
}

install_service "$TEMPLATE_DIR/hl-scalper-bot.service" "$SYSTEMD_DIR/hl-scalper-bot.service" "scalper"
install_service "$TEMPLATE_DIR/hl-mm-bot.service" "$SYSTEMD_DIR/hl-mm-bot.service" "market-maker"
install_service "$TEMPLATE_DIR/hl-status.service" "$SYSTEMD_DIR/hl-status.service" "status monitor"
install_service "$TEMPLATE_DIR/hl-status.timer" "$SYSTEMD_DIR/hl-status.timer" "status timer"

# Reload systemd
systemctl --user daemon-reload
echo "  ✓ Systemd reloaded"

echo ""

# ── Verify installation ────────────────────────────────────────────
echo "Step 6: Verifying installation..."

echo "  Testing scalper imports..."
cd "$SCALPER_DIR"
if "$SCALPER_DIR/venv/bin/python" -c "from config import BotConfig; print('  ✓ Scalper config OK')" 2>/dev/null; then
    true
else
    echo "  ⚠️  Scalper import test failed (may need .env configured first)"
fi

echo "  Testing market-maker imports..."
cd "$MM_DIR"
if "$MM_DIR/venv/bin/python" -c "from mm_config import MMConfig; print('  ✓ MM config OK')" 2>/dev/null; then
    true
else
    echo "  ⚠️  Market-maker import test failed (may need .env configured first)"
fi

echo ""

# ── Summary ────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Installation Complete!                                      ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "NEXT STEPS:"
echo ""
echo "1. EDIT .env files with your wallet details:"
echo "   nano $SCALPER_DIR/.env"
echo "   nano $MM_DIR/.env"
echo ""
echo "2. TEST the bots (dry run — will connect but not trade):"
echo "   $SCALPER_DIR/venv/bin/python $SCALPER_DIR/bot.py"
echo "   $MM_DIR/venv/bin/python $MM_DIR/mm_bot.py"
echo ""
echo "3. START bots as systemd services:"
echo "   systemctl --user start hl-scalper-bot.service"
echo "   systemctl --user start hl-mm-bot.service"
echo "   systemctl --user start hl-status.timer"
echo ""
echo "4. CHECK status:"
echo "   $MM_DIR/venv/bin/python $INSTALL_DIR/monitor/hl_status.py"
echo ""
echo "5. RUN BACKTESTS (simulates trading with $1000 on historical data):"
echo "   $MM_DIR/venv/bin/python $INSTALL_DIR/simulator/backtest_scalper.py"
echo "   $MM_DIR/venv/bin/python $INSTALL_DIR/simulator/backtest_mm.py"
echo "   $MM_DIR/venv/bin/python $INSTALL_DIR/simulator/coin_optimizer.py"
echo ""
echo "6. VIEW LOGS:"
echo "   journalctl --user -u hl-scalper-bot -f"
echo "   journalctl --user -u hl-mm-bot -f"
echo ""
echo "7. STOP bots:"
echo "   systemctl --user stop hl-scalper-bot.service"
echo "   systemctl --user stop hl-mm-bot.service"
echo ""
echo "📖  Read the full documentation: $INSTALL_DIR/docs/README.md"
echo ""