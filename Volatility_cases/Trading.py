from py_vollib.black_scholes.implied_volatility import implied_volatility as iv
import warnings
import signal
import requests
from time import sleep
import pandas as pd
import numpy as np
import Parse

def place_order(session, ticker, type, quantity, action):
    params = {
        'ticker': ticker,
        'type': type, 
        'quantity': quantity,
        'action': action
    }
    # Make the POST request with proper URL and parameters
    response = session.post('http://localhost:9999/v1/orders', params=params)
    if response.status_code == 500:
        print("SERVER ERROR - Check your parameters!")
        print(f"Sent params: {params}")
    print(response)
    return response

def trade(session, assets2, helper):
    """
    Trading logic for volatility case.
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
    current_exposure = helper['must_be_traded'].iloc[0]
    if np.isnan(current_exposure):
        current_exposure = 0
        

    option_positions = positions[1:]
    for i in range(len(option_positions)):
        if 'P' in assets2['ticker'].iloc[i+1]:
            option_positions[i] *= -1  # Invert position for puts'

    #Limit details
    stock_position = positions[0] * sizes[0]
    opt_positions = option_positions * sizes[1:] # Exclude stock position and use option positions, -ve for puts, +ve for calls
    opt_gross = np.nansum(np.abs(opt_positions))
    opt_net = np.nansum(opt_positions) 


    #Step 1: Sell all options that are in SELL position first, sell the corresponding hedged shares too
    for i in range(len(decisions)):
        if decisions[i] == "SELL" and positions[i+1] > 0:
            opt_pos = positions[i]
            opt_size = sizes[i]
            opt_delta = detlas[i]
            proposed_sell = opt_pos

            # Check option net after selling
            projected_net = opt_net - opt_pos

            # Resize if over limits
            if abs(projected_net) > OPT_NET_LIMIT:
                if np.sign(opt_pos) == 1:
                    proposed_sell = OPT_NET_LIMIT - opt_net
                else:
                    proposed_sell = OPT_NET_LIMIT + opt_net #If put, we add the position, since put is negative

            # Hedge amount (shares)
            hedge_shares = int(-1 * proposed_sell * opt_size * opt_delta)

            # Check stock limit before hedging
            projected_stock = stock_position + hedge_shares

            if abs(projected_stock) > STOCK_LIMIT:
                # shrink hedge to fit inside stock limit
                if np.sign(hedge_shares) == 1:  # Need to buy shares
                    allowed_stock_change = STOCK_LIMIT - stock_position
                else:  # Need to sell shares
                    allowed_stock_change = STOCK_LIMIT + stock_position

                max_contracts_for_stock = allowed_stock_change // (opt_size * abs(opt_delta))
                proposed_sell = min(proposed_sell, max_contracts_for_stock)
                hedge_shares = int(-1 * proposed_sell * opt_size * opt_delta)

            # Execute if still positive
            if proposed_sell > 0:
                print(f"Placing SELL order for {proposed_sell} contracts of {assets2['ticker'].iloc[i+1]} with hedge {hedge_shares} shares")
                place_order(session, assets2['ticker'].iloc[i+1], "MARKET", int(proposed_sell), "SELL")

            if hedge_shares > 0:
                print("THIS IS HEDGE SHARES:", hedge_shares)
                if 'P' in assets2['ticker'].iloc[i]:
                    place_order(session, assets2['ticker'].iloc[0], "MARKET", abs(hedge_shares), "SELL")
                else:
                    place_order(session, assets2['ticker'].iloc[0], "MARKET", abs(hedge_shares), "BUY")
   
    
    #Get current trade details
    max_id = np.argmin(profitability) #Index of most profitable option
    delta_val = detlas[max_id]        #Delta of this option
    print("THIS IS DELTA_VAL:", delta_val)
    decision = decisions[max_id]      #Decision of this option

    # Step 2: Trading logic for BUY
    if decision == "BUY":
        
        num_contracts = Parse.kelly(assets2['last'].iloc[0], assets2['i_vol'].iloc[0], assets2['last'].iloc[max_id+1], 
                              assets2['ticker'].iloc[max_id+1], 
                              detlas[max_id], profitability[max_id], 
                              opt_gross)
        #num_contracts = (profitability[max_id] * 100) // abs(delta_val)
        print("THIS IS NUM KELLY CONTRACTS:", num_contracts)

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
        if abs(recalculated_exposure) > DELTA_LIMIT:
            # shrink contracts to stay inside delta bounds
            if np.sign( num_contracts) == -1:
                allowed_delta = DELTA_LIMIT + recalculated_exposure
                num_contracts = int(-1 * allowed_delta / (100 * abs(delta_val)))
            else:
                allowed_delta = DELTA_LIMIT - recalculated_exposure
                num_contracts = int(allowed_delta / (100 * delta_val))

        #Recompute trade_size after delta adjustments
        trade_size = num_contracts * 100 * abs(delta_val)
        need_hedge = -1 * trade_size
        recalculated_exposure = need_hedge + current_exposure

        #Enforce Stock Limit (hedge capacity)
        if np.sign(recalculated_exposure) == -1:
            allowed_stock = STOCK_LIMIT + recalculated_exposure
        else:
            allowed_stock = STOCK_LIMIT - recalculated_exposure
        if abs(recalculated_exposure) > abs(allowed_stock):
            num_contracts = int(np.sign(num_contracts) * abs(allowed_stock) / (100 * abs(delta_val)))
        
        #Final trade size, and how much stock we need to hedge
        trade_size = num_contracts * 100 * delta_val
        need_hedge = -1 * trade_size
        recalculated_exposure = need_hedge + current_exposure
        
        # If after all adjustments, trade_size is zero, skip
        if trade_size == 0:
            pass
        else:
            #Placing BUY order for {num_contracts} contracts of {assets2['ticker'].iloc[max_id]} with hedge {need_hedge} shares, 
            # with the current exposure added (from helper['share_exposure'])
            if num_contracts > 0:
                print("THIS IS NUM CONTRACTS", num_contracts)
                place_order(session, assets2['ticker'].iloc[max_id+1], "MARKET", int(abs(num_contracts)), "BUY")
            if recalculated_exposure  != 0:
                print("THIS IS RECALCULATED EXPOSURE:", recalculated_exposure)
                if recalculated_exposure  > 0:
                    place_order(session, assets2['ticker'].iloc[0], "MARKET", int(recalculated_exposure), "BUY")
                else:
                    place_order(session, assets2['ticker'].iloc[0], "MARKET", int(abs(recalculated_exposure)), "SELL")

    



