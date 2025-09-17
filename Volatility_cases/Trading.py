import warnings
import signal
import requests
from time import sleep
import pandas as pd
import numpy as np

#Create function that will be used for trading

#Delta limit = 7000, Stock net/gross limit = 50000, Options gross/net limit = 2500/1000

#Algorithm: Check with option is most profitable, buy using some sizing function based on delta and diff_comm
    #Only if this option's position is BUY
    #Calculate how many shares we need to buy/sell to cover the delta exposure, if too much, reduce position
    #Or if our net limit for options is too high, reduce position

#Move to selling, if the position of any option is SELL, sell this along with corresponding shares (same current delta change)
def trade(assets2, helper):
    """
    Trading logic for options and hedging using RIT Market Simulator.
    
    Parameters
    ----------
    assets2 : pd.DataFrame
        DataFrame from main loop with option data:
        ['ticker', 'last', 'delta', 'diffcom', 'decision', 'position', 'size', ...]
    helper : pd.DataFrame
        Contains hedging and exposure calculations (share_exposure, required_hedge, etc.)
    """
    # --- Risk Limits ---
    DELTA_LIMIT = 7000
    STOCK_LIMIT = 50000
    OPT_GROSS_LIMIT = 2500
    OPT_NET_LIMIT = 1000

    #Position details
    profitability = np.array(assets2['diffcom'].iloc[1:])
    detlas = np.array(assets2['delta'].iloc[1:])
    decisions = np.array(assets2['decision'].iloc[1:])
    positions = np.array(assets2['position'])
    sizes = np.array(assets2['size'])
    current_exposure = helper['must_be_traded']

    #Limit details
    stock_position = positions[0] * sizes[0]
    opt_positions = positions[1:] * sizes[1:]
    opt_gross = np.nansum(np.abs(opt_positions))
    opt_net = np.nansum(opt_positions) 

    #Step 1: Sell all options that are in SELL position first, sell the corresponding hedged shares too
    for i in range(1, len(positions), 1):
        if decisions[i] == "SELL":

            if 'P' in assets2['ticker'].iloc[i]:
                op_type = 'PUT'
            else:
                op_type = 'CALL'
            opt_pos = positions[i]
            opt_size = sizes[i]
            opt_delta = detlas[i]

            # Proposed option sale size
            proposed_sell = abs(opt_pos)

            # Check option gross + net after selling
            projected_net = opt_net - (proposed_sell * opt_size)

            # Resize if over limits
            if abs(projected_net) > OPT_NET_LIMIT:
                allowed_net_change = OPT_NET_LIMIT - abs(opt_net)
                allowed_sell = allowed_net_change // opt_size
                proposed_sell = min(proposed_sell, abs(allowed_sell))

            # Hedge amount (shares)
            hedge_shares = int(abs(proposed_sell * opt_size * opt_delta))

        # Check stock limit before hedging
        projected_stock = stock_position
        if 'P' in opt_ticker:
            projected_stock -= hedge_shares
        else:
            projected_stock += hedge_shares

        if abs(projected_stock) > STOCK_LIMIT:
            # shrink hedge to fit inside stock limit
            allowed_stock_change = STOCK_LIMIT - abs(stock_position)
            if allowed_stock_change < 0:
                proposed_sell = 0
                hedge_shares = 0
            else:
                max_contracts_for_stock = allowed_stock_change // (opt_size * abs(opt_delta))
                proposed_sell = min(proposed_sell, max_contracts_for_stock)
                hedge_shares = int(abs(proposed_sell * opt_size * opt_delta))

        # Execute if still positive
        if proposed_sell > 0:
            place_order(opt_ticker, 'SELL', proposed_sell)

            if hedge_shares > 0:
                if 'P' in opt_ticker:
                    place_order('RIT', 'SELL', hedge_shares)
                else:
                    place_order('RIT', 'BUY', hedge_shares)
   
    
    #Get current trade details
    max_id = np.argmax(profitability) #Index of most profitable option
    delta_val = detlas[max_id]        #Delta of this option
    decision = decisions[max_id]      #Decision of this option

    # Step 2: Trading logic for BUY
    if decision == "BUY":

        num_contracts = NotImplemented # Define based on your strategy

        #Enforce option gross limit
        if abs(num_contracts) + opt_gross > OPT_GROSS_LIMIT:
            num_contracts = (OPT_GROSS_LIMIT - opt_gross) * np.sign(num_contracts)

        # Enforce option net limits
        if abs(num_contracts + opt_net) > OPT_NET_LIMIT:
            if np.sign(num_contracts) == -1:
                num_contracts = -OPT_NET_LIMIT - opt_net
            else:
                num_contracts = OPT_NET_LIMIT - opt_net

        #Recompute trade_size after option adjustments
        trade_size = num_contracts * 100 * abs(delta_val)

        #Enforce Delta Exposure Limit
        recalculated_exposure = trade_size + current_exposure
        if abs(recalculated_exposure) > 7000:
            # shrink contracts to stay inside delta bounds
            if np.sign( num_contracts) == -1:
                allowed_delta = -DELTA_LIMIT - recalculated_exposure
                num_contracts = int(-1 * (abs(allowed_delta) / (100 * abs(delta_val))))
            else:
                allowed_delta = DELTA_LIMIT - recalculated_exposure
                num_contracts = int(allowed_delta / (100 * delta_val))

        #Recompute trade_size after delta adjustments
        trade_size = num_contracts * 100 * abs(delta_val)
        need_hedge = -1 * trade_size

        #Enforce Stock Limit (hedge capacity)
        if np.sign(need_hedge) == -1:
            allowed_stock = -STOCK_LIMIT - stock_position
        else:
            allowed_stock = STOCK_LIMIT - stock_position
        if abs(need_hedge) > abs(allowed_stock):
            num_contracts = int(np.sign(num_contracts) * abs(allowed_stock) / (100 * abs(delta_val)))
        
        #Final trade size, and how much stock we need to hedge
        trade_size = num_contracts * 100 * delta_val
        need_hedge = -1 * trade_size
        
        # If after all adjustments, trade_size is zero, skip
        if trade_size == 0:
            pass
        else:
            #Placing BUY order for {num_contracts} contracts of {assets2['ticker'].iloc[max_id]} with hedge {need_hedge} shares, 
            # with the current exposure added (from helper['share_exposure'])
            place_order(assets2['ticker'].iloc[max_id], 'BUY', abs(num_contracts))
            if need_hedge + current_exposure != 0:
                if need_hedge + current_exposure > 0:
                    place_order('RIT', 'BUY', abs(need_hedge + current_exposure))
                else:
                    place_order('RIT', 'SELL', abs(need_hedge + current_exposure))

    



