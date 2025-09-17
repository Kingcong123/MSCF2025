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
    return np.exp(0.5*(number**2.0))/np.sqrt(2.0*np.pi)

def normCDF(number):
    return (1.0+ math.erf(number/np.sqrt(2.0)))/2.0

def kelly(etfPrice, etfIV, optionPrice, name, 
          delta, diffcom, sharesLeft, optionIV = None):
    #we don't actually get the IV of the option. Imma black scholes it here
    expiry = (20/240) 
    safetyMargin = 0.9
    strike = float(name[3:5])
    type = 'c' if 'C' in name else 'p'

    if optionIV is None:
        optionIV = iv(optionPrice, etfPrice, strike, expiry, 0.0, type) #implied vol of the option
    
    #for the scholes 
    d1 = (math.log(etfPrice/strike) + 0.5*(optionIV**2)*expiry) / (optionIV*math.sqrt(expiry))
    vega = etfPrice * normPDF(d1) * math.sqrt(expiry) #this is price change sensitivity to volatility

    volDiff = optionIV - etfIV #difference in volatility... consider switching out with diffcom entirely?
    profitMargin = (-volDiff) * vega #if volDiff is negative, we make money, positive we lose money
    rateOfReturn = profitMargin / optionPrice 
    
    winProb = normCDF(abs(volDiff)/0.02) #probability of winning if we take the correct side
    
    kelly = ((winProb * rateOfReturn) - (1-winProb)) / (rateOfReturn)
    
    safeKelly = kelly * safetyMargin
    
    return safeKelly * sharesLeft