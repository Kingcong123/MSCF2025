"""
RIT Market Simulator Algorithmic ETF Arbitrage Trading Module
Rotman BMO Finance Research and Trading Lab, University of Toronto (C)
All rights reserved.

This module implements ETF arbitrage strategies using creation/redemption mechanisms
to close positions efficiently and capture arbitrage opportunities.
"""

import requests
import numpy as np
from time import sleep

# Tickers
CAD = "CAD"    # currency instrument quoted in CAD
USD = "USD"    # price of 1 USD in CAD (i.e., USD/CAD)
BULL = "BULL"  # stock in CAD
BEAR = "BEAR"  # stock in CAD
RITC = "RITC"  # ETF quoted in USD

# Trading parameters
FEE_MKT = 0.02           # $/share (market orders)
REBATE_LMT = 0.01        # $/share (passive orders)
MAX_SIZE_EQUITY = 10000  # per order for BULL/BEAR/RITC
MAX_SIZE_FX = 2500000    # per order for CAD/USD

# Risk management parameters
MAX_LONG_NET = 25000
MAX_SHORT_NET = -25000
MAX_GROSS = 500000
ORDER_QTY = 5000         # child order size for arb legs

# Arbitrage threshold - must cover fees, slippage, and converter costs
CONVERTER_COST = 1500    # Cost per ETF creation/redemption
ARB_THRESHOLD_CAD = 0.07 + (CONVERTER_COST / 10000)  # 0.07 + 0.15 = 0.22 CAD per share

# ETF Creation/Redemption parameters
ETF_CREATION_UNITS = 10000  # Standard creation/redemption unit size

class ArbitrageTrader:
    def __init__(self, session):
        self.session = session
        self.arb_positions = []  # Track open arbitrage positions
        self.last_prices = {}    # Cache for price data
        
    def get_best_prices(self):
        """Get best bid/ask prices for all relevant securities"""
        prices = {}
        
        for ticker in [BULL, BEAR, RITC, USD]:
            try:
                r = self.session.get(f"http://localhost:9999/v1/securities/book", 
                                   params={"ticker": ticker})
                r.raise_for_status()
                book = r.json()
                
                bid = float(book["bids"][0]["price"]) if book["bids"] else 0.0
                ask = float(book["asks"][0]["price"]) if book["asks"] else 1e12
                prices[ticker] = {"bid": bid, "ask": ask}
                
            except Exception as e:
                print(f"Error getting prices for {ticker}: {e}")
                return None
                
        return prices
    
    def get_positions(self):
        """Get current positions for all securities"""
        try:
            r = self.session.get("http://localhost:9999/v1/securities")
            r.raise_for_status()
            securities = r.json()
            
            positions = {}
            for sec in securities:
                ticker = sec["ticker"]
                positions[ticker] = int(sec.get("position", 0))
                
            # Ensure all tickers are present
            for ticker in [BULL, BEAR, RITC, USD, CAD]:
                positions.setdefault(ticker, 0)
                
            return positions
            
        except Exception as e:
            print(f"Error getting positions: {e}")
            return None
    
    def place_order(self, ticker, action, qty, order_type="MARKET"):
        """Place an order with proper size limits"""
        if qty <= 0:
            return False
            
        # Handle size limits
        max_size = MAX_SIZE_EQUITY if ticker in [BULL, BEAR, RITC] else MAX_SIZE_FX
        
        while qty > max_size:
            params = {
                'ticker': ticker,
                'type': order_type,
                'quantity': max_size,
                'action': action
            }
            response = self.session.post('http://localhost:9999/v1/orders', params=params)
            if not response.ok:
                print(f"Order failed: {response.text}")
                return False
            qty -= max_size
        
        if qty > 0:
            params = {
                'ticker': ticker,
                'type': order_type,
                'quantity': qty,
                'action': action
            }
            response = self.session.post('http://localhost:9999/v1/orders', params=params)
            if not response.ok:
                print(f"Order failed: {response.text}")
                return False
                
        return True
    
    def etf_creation(self, quantity):
        """Convert 10,000 BULL + 10,000 BEAR stocks to 10,000 RITC ETF units"""
        if quantity % ETF_CREATION_UNITS != 0:
            print(f"ETF creation quantity must be multiple of {ETF_CREATION_UNITS}")
            return False
            
        try:
            # Use ETF creation converter
            params = {
                'from': 'BULL,BEAR',
                'to': 'RITC',
                'quantity': quantity
            }
            response = self.session.post('http://localhost:9999/v1/converters', params=params)
            
            if response.ok:
                print(f"ETF Creation: {quantity} BULL+BEAR -> {quantity} RITC")
                return True
            else:
                print(f"ETF Creation failed: {response.text}")
                return False
                
        except Exception as e:
            print(f"ETF Creation error: {e}")
            return False
    
    def etf_redemption(self, quantity):
        """Convert 10,000 RITC ETF units to 10,000 BULL + 10,000 BEAR stocks"""
        if quantity % ETF_CREATION_UNITS != 0:
            print(f"ETF redemption quantity must be multiple of {ETF_CREATION_UNITS}")
            return False
            
        try:
            # Use ETF redemption converter
            params = {
                'from': 'RITC',
                'to': 'BULL,BEAR',
                'quantity': quantity
            }
            response = self.session.post('http://localhost:9999/v1/converters', params=params)
            
            if response.ok:
                print(f"ETF Redemption: {quantity} RITC -> {quantity} BULL+BEAR")
                return True
            else:
                print(f"ETF Redemption failed: {response.text}")
                return False
                
        except Exception as e:
            print(f"ETF Redemption error: {e}")
            return False
    
    def within_risk_limits(self, positions):
        """Check if positions are within risk limits"""
        if not positions:
            return False
            
        gross = abs(positions[BULL]) + abs(positions[BEAR]) + abs(positions[RITC])
        net = positions[BULL] + positions[BEAR] + positions[RITC]
        
        return (gross < MAX_GROSS) and (MAX_SHORT_NET < net < MAX_LONG_NET)
    
    def detect_arbitrage_opportunity(self, prices):
        """Detect arbitrage opportunities between ETF and underlying basket"""
        if not prices:
            return None
            
        # Convert RITC prices to CAD
        ritc_bid_cad = prices[RITC]["bid"] * prices[USD]["bid"]
        ritc_ask_cad = prices[RITC]["ask"] * prices[USD]["ask"]
        
        # Basket prices
        basket_bid = prices[BULL]["bid"] + prices[BEAR]["bid"]  # Sell basket
        basket_ask = prices[BULL]["ask"] + prices[BEAR]["ask"]  # Buy basket
        
        # Calculate arbitrage edges
        # Direction 1: Basket rich vs ETF (sell basket, buy ETF)
        edge1 = basket_bid - ritc_ask_cad
        
        # Direction 2: ETF rich vs Basket (sell ETF, buy basket)  
        edge2 = ritc_bid_cad - basket_ask
        
        return {"edge1": edge1, "edge2": edge2, "ritc_bid_cad": ritc_bid_cad, 
                "ritc_ask_cad": ritc_ask_cad, "basket_bid": basket_bid, "basket_ask": basket_ask}
    
    def execute_arbitrage_trade(self, arb_data, prices, positions):
        """Execute arbitrage trade and close position using converters"""
        if not arb_data or not self.within_risk_limits(positions):
            return False
            
        edge1 = arb_data["edge1"]
        edge2 = arb_data["edge2"]
        traded = False
        
        # Direction 1: Basket rich - sell BULL+BEAR, buy RITC, then create ETF to close
        if edge1 >= ARB_THRESHOLD_CAD:
            print(f"Basket Rich Arbitrage: Edge = {edge1:.4f} CAD")
            
            # Execute the arbitrage trade
            qty = min(ORDER_QTY, MAX_SIZE_EQUITY)
            
            # Sell BULL and BEAR (hit bids)
            self.place_order(BULL, "SELL", qty)
            self.place_order(BEAR, "SELL", qty)
            
            # Buy RITC (lift ask)
            self.place_order(RITC, "BUY", qty)
            
            # Record the position for later closure
            self.arb_positions.append({
                "type": "basket_rich",
                "bull_qty": -qty,  # Short position
                "bear_qty": -qty,  # Short position  
                "ritc_qty": qty,   # Long position
                "edge": edge1
            })
            
            traded = True
            
        # Direction 2: ETF rich - buy BULL+BEAR, sell RITC, then redeem ETF to close
        elif edge2 >= ARB_THRESHOLD_CAD:
            print(f"ETF Rich Arbitrage: Edge = {edge2:.4f} CAD")
            
            # Execute the arbitrage trade
            qty = min(ORDER_QTY, MAX_SIZE_EQUITY)
            
            # Buy BULL and BEAR (lift asks)
            self.place_order(BULL, "BUY", qty)
            self.place_order(BEAR, "BUY", qty)
            
            # Sell RITC (hit bid)
            self.place_order(RITC, "SELL", qty)
            
            # Record the position for later closure
            self.arb_positions.append({
                "type": "etf_rich",
                "bull_qty": qty,   # Long position
                "bear_qty": qty,   # Long position
                "ritc_qty": -qty,  # Short position
                "edge": edge2
            })
            
            traded = True
            
        return traded
    
    def close_arbitrage_positions(self, positions):
        """Close arbitrage positions using ETF creation/redemption"""
        if not self.arb_positions or not positions:
            return
            
        for pos in self.arb_positions[:]:  # Copy list to modify during iteration
            bull_pos = positions.get(BULL, 0)
            bear_pos = positions.get(BEAR, 0) 
            ritc_pos = positions.get(RITC, 0)
            
            # Check if we have enough position to close
            if pos["type"] == "basket_rich":
                # We're short BULL+BEAR, long RITC
                # Need to create ETF: convert BULL+BEAR to RITC to close shorts
                if bull_pos <= pos["bull_qty"] and bear_pos <= pos["bear_qty"]:
                    # Close short positions by buying back and creating ETF
                    close_qty = abs(pos["bull_qty"])
                    if close_qty >= ETF_CREATION_UNITS and close_qty % ETF_CREATION_UNITS == 0:
                        # Buy back the short positions
                        self.place_order(BULL, "BUY", close_qty)
                        self.place_order(BEAR, "BUY", close_qty)
                        
                        # Create ETF to close the long RITC position
                        if self.etf_creation(close_qty):
                            self.arb_positions.remove(pos)
                            print(f"Closed basket_rich position: {close_qty} units")
                            
            elif pos["type"] == "etf_rich":
                # We're long BULL+BEAR, short RITC
                # Need to redeem ETF: convert RITC to BULL+BEAR to close shorts
                if ritc_pos <= pos["ritc_qty"]:
                    # Close short RITC position by redeeming ETF
                    close_qty = abs(pos["ritc_qty"])
                    if close_qty >= ETF_CREATION_UNITS and close_qty % ETF_CREATION_UNITS == 0:
                        if self.etf_redemption(close_qty):
                            self.arb_positions.remove(pos)
                            print(f"Closed etf_rich position: {close_qty} units")
    
    def trade(self, session=None, assets2=None, helper=None, vol=None, news_volatilities=None):
        """
        Main trading function for ETF arbitrage
        """
        # Get current market data
        prices = self.get_best_prices()
        positions = self.get_positions()
        
        if not prices or not positions:
            return
            
        # Close any existing arbitrage positions first
        self.close_arbitrage_positions(positions)
        
        # Detect new arbitrage opportunities
        arb_data = self.detect_arbitrage_opportunity(prices)
        
        if arb_data:
            # Execute new arbitrage trades if profitable
            self.execute_arbitrage_trade(arb_data, prices, positions)
            
            # Print current status
            print(f"Arbitrage Status:")
            print(f"  Basket Rich Edge: {arb_data['edge1']:.4f} CAD")
            print(f"  ETF Rich Edge: {arb_data['edge2']:.4f} CAD")
            print(f"  Open Positions: {len(self.arb_positions)}")
            print(f"  Current Positions - BULL: {positions[BULL]}, BEAR: {positions[BEAR]}, RITC: {positions[RITC]}")

# Compatibility function for existing code structure
def trade(session, assets2=None, helper=None, vol=None, news_volatilities=None):
    """
    Compatibility wrapper for the main trading function
    """
    trader = ArbitrageTrader(session)
    trader.trade(session, assets2, helper, vol, news_volatilities)

