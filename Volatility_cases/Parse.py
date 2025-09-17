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