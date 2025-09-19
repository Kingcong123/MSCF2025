from py_vollib.black_scholes.implied_volatility import implied_volatility as iv
import math
import numpy as np

def parse_news(news):
    volatilities = []
    for item in news:
        if 'volatility' in item['body'].lower():
            words = item['body'].split()
            for word in words:
                try:
                    # Check if word ends with '%' before trying to convert
                    if word.endswith('%'):
                        vol = float(word.strip('%')) / 100
                        # Only include reasonable volatility values (1% to 100%)
                        if 0.01 <= vol <= 1.0:
                            volatilities.append(vol)
                except ValueError:
                    continue
    return volatilities

#parse.parse_news(news)

def normPDF(number):
    return np.exp(0.5*((number)**2.0))/(np.sqrt(2.0*np.pi))

def normCDF(number, stdev):
    return (1.0+ math.erf((number)/stdev*np.sqrt(2.0)))/2.0

def calculate_improved_win_probability(volDiff, etfIV, news_volatilities=None):
    """
    Calculate win probability using market context and adaptive parameters.
    
    Parameters:
    - volDiff: Difference between option IV and ETF IV
    - etfIV: ETF implied volatility
    - news_volatilities: List of volatilities from news parsing
    
    Returns:
    - winProb: Probability of winning the volatility arbitrage trade
    """
    
    # Base parameters - more realistic than hardcoded values
    base_mean = 0.0  # Volatility differences should converge to 0
    base_stdev = 0.05  # 5% standard deviation (more realistic than 1 or 3%)
    
    # Adjust parameters based on market conditions
    if news_volatilities and len(news_volatilities) > 0:
        # Use news-derived volatility to adjust our model
        avg_news_vol = np.mean(news_volatilities)
        vol_uncertainty = np.std(news_volatilities) if len(news_volatilities) > 1 else 0.02
        
        # Higher market volatility = higher uncertainty in our predictions
        adjusted_stdev = base_stdev + vol_uncertainty
        
        # If news suggests high volatility, increase our uncertainty
        if avg_news_vol > 0.3:  # High volatility regime
            adjusted_stdev *= 1.5
        elif avg_news_vol < 0.15:  # Low volatility regime
            adjusted_stdev *= 0.8
    else:
        adjusted_stdev = base_stdev
    
    # Adjust based on ETF IV level
    if etfIV > 0.4:  # Very high volatility
        adjusted_stdev *= 1.3
    elif etfIV < 0.15:  # Very low volatility
        adjusted_stdev *= 0.9
    
    # Calculate win probability using improved parameters
    # Use absolute value since we care about magnitude of mispricing
    abs_vol_diff = abs(volDiff)
    
    # Cap the volatility difference to prevent extreme probabilities
    capped_diff = min(abs_vol_diff, 0.2)  # Cap at 20% difference
    
    # Calculate probability using normal CDF
    winProb = normCDF(capped_diff, adjusted_stdev)
    
    # Ensure reasonable bounds (between 0.5 and 0.95)
    winProb = max(0.1, min(0.95, winProb))
    
    return winProb

def kelly(etfPrice, etfIV, optionPrice, name, 
          delta, diffcom, sharesLeft, news_volatilities = None):
    #debugging
    """print("THIS IS KELLY PARAMETER", etfPrice, etfIV, optionPrice, name, 
          delta, diffcom, sharesLeft, optionIV)"""
    
    #we don't actually get the IV of the option. Imma black scholes it here
    expiry = (20/240) 
    safetyMargin = 0.5
    strike = float(name[3:5])
    type = 'c' if 'C' in name else 'p'
    sgn = 1

    optionIV = iv(optionPrice, etfPrice, strike, expiry, 0.0, type) #implied vol of the option
    
    #for the scholes 
    d1 = (math.log(etfPrice/strike) + 0.5*(optionIV**2)*expiry) / (optionIV*math.sqrt(expiry))
    vega = etfPrice * normPDF(d1) * math.sqrt(expiry) #this is price change sensitivity to volatility

    volDiff = optionIV - etfIV #difference in volatility... consider switching out with diffcom entirely?
    profitMargin = (-volDiff) * vega #if volDiff is negative, we long, positive we short
    rateOfReturn = abs(profitMargin) / optionPrice 
    
    if volDiff > 0: #vol is too high => priced too high, short it
        sgn = -1
    
    # Improved win probability calculation using market context
    winProb = calculate_improved_win_probability(volDiff, etfIV, news_volatilities)
    
    kelly = ((winProb * rateOfReturn) - (1-winProb)) / (rateOfReturn)
    
    safeKelly = kelly * safetyMargin
    
    """print("input variables:", type, optionIV, etfIV, volDiff)
    print("calculations:", sgn, profitMargin, rateOfReturn, winProb)
    print("output items:", kelly, safeKelly, sharesLeft, sgn)'"""
    
    return safeKelly * sharesLeft * sgn