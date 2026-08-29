"""
Trade Logger - Ensures data integrity and error handling
"""

import json
import os
from config import LOG_DIR

def log_trade(trade: dict):
    log_file = os.path.join(LOG_DIR, "trades.json")
    
    # Ensure directory exists
    os.makedirs(LOG_DIR, exist_ok=True)
    
    try:
        # Read existing trades
        if os.path.exists(log_file):
            with open(log_file, "r") as f:
                trades = json.load(f)
        else:
            trades = []
        
        # Append new trade
        trades.append(trade)
        
        # Write updated trades
        with open(log_file, "w") as f:
            json.dump(trades, f, indent=4)
    except Exception as e:
        print(f"Error logging trade: {e}")