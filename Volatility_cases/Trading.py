from py_vollib.black_scholes.implied_volatility import implied_volatility as iv
import warnings
import signal
import requests
from time import sleep
import pandas as pd
import numpy as np
import Parse

def place_order(session, ticker, type, quantity, action):
    if type == "STOCK" and quantity > 10000:
        while(quantity > 10000):
            amount = 9000
            params = {
                'ticker': ticker,
                'type': type,
                'quantity': amount,
                'action': action
            }
            # Make the POST request with proper URL and 
            response = session.post('http://localhost:9999/v1/orders', params=params)
            quantity = quantity - amount

    if type != "STOCK" and quantity > 100:
        while(quantity > 100):
            amount = 90
            params = {
                'ticker': ticker,
                'type': type, 
                'quantity': amount,
                'action': action
         }
            # Make the POST request with proper URL and 
            response = session.post('http://localhost:9999/v1/orders', params=params)
            quantity = quantity - amount

    params = {
        'ticker': ticker,
        'type': type, 
        'quantity': quantity,
        'action': action
        }
    response = session.post('http://localhost:9999/v1/orders', params=params)
    print(response)
    return response

    

def trade(session, assets2, helper, vol, news_volatilities=None):
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
   #Trade the shares to match the required hedge first
    current_exposure = helper['must_be_traded'].iloc[0]
    if np.isnan(current_exposure):
        current_exposure = 0
    print("CURRENT EXPOSURE:", current_exposure)
    if current_exposure > 0:
        print("BUYING EXPOSURE SHARES:")
        place_order(session, assets2['ticker'].iloc[0], "MARKET", int(current_exposure), "BUY")
    if current_exposure < 0:
        print("SELLING EXPOSURE SHARES:")
        place_order(session, assets2['ticker'].iloc[0], "MARKET", abs(int(current_exposure)), "SELL")

     # --- Risk Limits ---
    DELTA_LIMIT = 7000
    STOCK_LIMIT = 50000
    OPT_GROSS_LIMIT = 2500
    OPT_NET_LIMIT = 1000

    #Position details
    profitability = np.abs(np.array(assets2['diffcom'].iloc[1:]))
    detlas = np.array(assets2['delta'].iloc[1:])
    decisions = np.array(assets2['decision'].iloc[1:])
    positions = np.array(assets2['position'])
    sizes = np.array(assets2['size'])
        

    option_positions = positions[1:]
    for i in range(len(option_positions)):
        if 'P' in assets2['ticker'].iloc[i+1]:
            option_positions[i] *= -1  # Invert position for puts'

    #Limit calculations
    stock_position = positions[0] * sizes[0]
    opt_gross = np.nansum(np.abs(option_positions))
    opt_net = np.nansum(option_positions) 


    #Step 1: Sell all options that are in SELL position first, sell the corresponding hedged shares too
    for i in range(len(decisions)):
        print("DECISION:", decisions[i], "POSITION:", positions[i+1], assets2['ticker'].iloc[i+1])
        if decisions[i] == "SELL" and abs(positions[i+1]) > 0:
            opt_pos = option_positions[i]
            opt_size = sizes[i]
            opt_delta = detlas[i]
            proposed_sell = abs(opt_pos)
            print("Preparing to SELL", proposed_sell, "contracts of", assets2['ticker'].iloc[i+1], "opt_pos:", opt_pos, "opt_size:", opt_size, "opt_delta:", opt_delta)

            # Check option net after selling
            projected_net = opt_net - opt_pos

            # Resize if over limits
            if abs(projected_net) > OPT_NET_LIMIT:
                if np.sign(opt_pos) == 1:
                    proposed_sell = OPT_NET_LIMIT - opt_net
                else:
                    proposed_sell = OPT_NET_LIMIT + opt_net #If put, we add the position, since put is negative

            # Hedge amount (shares)
            hedge_shares = int(proposed_sell * opt_size * opt_delta)

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

            if abs(hedge_shares) > 0:
                if hedge_shares < 0:
                    place_order(session, assets2['ticker'].iloc[0], "MARKET", abs(hedge_shares), "BUY")
                else:
                    place_order(session, assets2['ticker'].iloc[0], "MARKET", abs(hedge_shares), "SELL")
   
    
    #Get current trade details
    max_id = np.argmax(profitability) #Index of most profitable option
    delta_val = detlas[max_id]        #Delta of this option
    decision = decisions[max_id]      #Decision of this option

    # Step 2: Trading logic for BUY
    if decision == "BUY":

        num_contracts = Parse.kelly(assets2['last'].iloc[0], vol, assets2['last'].iloc[max_id+1], 
                              assets2['ticker'].iloc[max_id+1], 
                              detlas[max_id], profitability[max_id], 
                              OPT_NET_LIMIT - opt_gross, news_volatilities=news_volatilities)
        print("THIS IS NUM KELLY CONTRACTS:", num_contracts)
        #num_contracts = (profitability[max_id] * 20) // delta_val
    
        #Enforce option gross limit
        if abs(num_contracts) + opt_gross > OPT_GROSS_LIMIT:
            num_contracts = (OPT_GROSS_LIMIT - opt_gross) * np.sign(num_contracts)
            #print("NUM_CONTRACTS AFTER GROSS LIMIT:", num_contracts)

        # Enforce option net limits
        
            if np.sign(num_contracts) == -1:
                if abs(num_contracts + opt_net) > OPT_NET_LIMIT:
                    num_contracts = OPT_NET_LIMIT + opt_net
                    #print("NUM_CONTRACTS AFTER NET LIMIT:", num_contracts)
            else:
                num_contracts = OPT_NET_LIMIT - opt_net
                #print("NUM_CONTRACTS AFTER NET LIMIT:", num_contracts)

        #Recompute trade_size after option adjustments
        trade_size = num_contracts * 100 * abs(delta_val)

        if abs(trade_size) > DELTA_LIMIT:
            # shrink contracts to stay inside delta bounds
            allowed_delta = DELTA_LIMIT - abs(trade_size)
            num_contracts = int(allowed_delta / (100 * delta_val))
            #print("NUM_CONTRACTS AFTER DELTA LIMIT:", num_contracts)

        #Recompute trade_size after delta adjustments
        trade_size = num_contracts * 100 * delta_val
        need_hedge = -1 * trade_size

        #Enforce Stock Limit (hedge capacity)
        if np.sign(need_hedge) == -1:
            allowed_stock = STOCK_LIMIT + need_hedge
        else:
            allowed_stock = STOCK_LIMIT - need_hedge
        if abs(need_hedge) > abs(allowed_stock):
            num_contracts = int(np.sign(num_contracts) * abs(allowed_stock) / (100 * abs(delta_val)))
            #print("NUM_CONTRACTS AFTER STOCK LIMIT:", num_contracts)
        
        #Final trade size, and how much stock we need to hedge
        trade_size = num_contracts * 100 * delta_val
        need_hedge = -1 * trade_size
        print("num_contracts", num_contracts, "FINAL TRADE SIZE:", trade_size, "NEED HEDGE:", need_hedge)
        
        # If after all adjustments, trade_size is zero, skip
        if trade_size == 0:
            pass
        else:
            #Placing BUY order for {num_contracts} contracts of {assets2['ticker'].iloc[max_id]} with hedge {need_hedge} shares, 
            # with the current exposure added (from helper['share_exposure'])
            if abs(num_contracts) > 0:
                place_order(session, assets2['ticker'].iloc[max_id+1], "MARKET", int(abs(num_contracts)), "BUY")
            if need_hedge != 0:
                print("NEED HEDGE:", need_hedge)
                if need_hedge  > 0:
                    print("BUYING HEDGE SHARES:")
                    place_order(session, assets2['ticker'].iloc[0], "MARKET", int(need_hedge), "BUY")
                else:
                    print("SELLING HEDGE SHARES:")
                    place_order(session, assets2['ticker'].iloc[0], "MARKET", int(abs(need_hedge)), "SELL")
        

    



