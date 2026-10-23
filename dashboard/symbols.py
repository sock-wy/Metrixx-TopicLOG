"""Kalshi series -> Topic Log topic (the symbol appendix).

A topic is what an episode would be about: an underlying (BTC, SPX, TSLA, Gold,
EUR/USD, UST 10Y) or, for private companies and one-off themes, the company or
theme itself. Every open Kalshi series in the categories below maps to exactly
one topic. Unknown series fall back to their own series ticker as the topic and
are flagged `mapped = False` so the appendix shows what still needs a rule.

Each topic carries:
  asset_class   crypto | index | commodity | fx | rates | macro | equity | private | theme
  price         Yahoo Finance symbol for market data / momentum (None if none)
  adanos        (kind, symbol): kind "crypto" -> /reddit/crypto, "stocks" -> /reddit/stocks
"""
from __future__ import annotations

import re

CATEGORIES = ("Financials", "Crypto", "Commodities", "Companies", "Economics")

# ---------------------------------------------------------------- topic table
# topic id -> (display name, asset_class, yahoo symbol, adanos (kind, symbol))
CRYPTO = {
    "BTC": ("Bitcoin", "BTC-USD"), "ETH": ("Ethereum", "ETH-USD"), "SOL": ("Solana", "SOL-USD"),
    "XRP": ("XRP", "XRP-USD"), "DOGE": ("Dogecoin", "DOGE-USD"), "BNB": ("BNB", "BNB-USD"),
    "HYPE": ("Hyperliquid", "HYPE32196-USD"), "ZEC": ("Zcash", "ZEC-USD"), "NEAR": ("NEAR", "NEAR-USD"),
    "SHIB": ("Shiba Inu", "SHIB-USD"), "STRK": ("Starknet", "STRK22691-USD"),
}
TOPICS: dict[str, tuple] = {k: (v[0], "crypto", v[1], ("crypto", k)) for k, v in CRYPTO.items()}
TOPICS.update({
    "CRYPTO": ("Crypto market", "crypto", None, None),
    "STABLECOINS": ("Stablecoin supply", "crypto", None, ("crypto", "USDT")),
    # indices (Adanos via the ETF proxy, as in backtest/universes/crypto_indices.yaml)
    "SPX": ("S&P 500", "index", "^GSPC", ("stocks", "SPY")),
    "NDX": ("Nasdaq-100", "index", "^NDX", ("stocks", "QQQ")),
    "DJI": ("Dow Jones", "index", "^DJI", ("stocks", "DIA")),
    "FEARGREED": ("Fear & Greed index", "index", None, None),
    "NIKKEI": ("Nikkei 225", "index", "^N225", ("stocks", "EWJ")),
    "KOSPI": ("KOSPI", "index", "^KS11", ("stocks", "EWY")),
    "NIFTY": ("NIFTY 50", "index", "^NSEI", ("stocks", "INDA")),
    "TSX": ("S&P/TSX", "index", "^GSPTSE", ("stocks", "EWC")),
    "IBOV": ("Ibovespa", "index", "^BVSP", ("stocks", "EWZ")),
    "IPC": ("S&P/BMV IPC", "index", "^MXX", ("stocks", "EWW")),
    "INDEXCHANGES": ("Index membership changes", "index", None, None),
    "RUT": ("Russell 2000", "index", "^RUT", ("stocks", "IWM")),
    "DXY": ("US dollar index", "index", "DX-Y.NYB", ("stocks", "UUP")),
    # commodities
    "GOLD": ("Gold", "commodity", "GC=F", ("stocks", "GLD")),
    "SILVER": ("Silver", "commodity", "SI=F", ("stocks", "SLV")),
    "COPPER": ("Copper", "commodity", "HG=F", ("stocks", "CPER")),
    "PLATINUM": ("Platinum", "commodity", "PL=F", ("stocks", "PPLT")),
    "PALLADIUM": ("Palladium", "commodity", "PA=F", ("stocks", "PALL")),
    "WTI": ("WTI crude", "commodity", "CL=F", ("stocks", "USO")),
    "BRENT": ("Brent crude", "commodity", "BZ=F", ("stocks", "BNO")),
    "NATGAS": ("Natural gas", "commodity", "NG=F", ("stocks", "UNG")),
    "ALUMINUM": ("Aluminum", "commodity", "ALI=F", None),
    "POWER": ("US power prices", "commodity", None, None),
    "BEEF": ("Beef", "commodity", "LE=F", None),
    "TUNGSTEN": ("Tungsten", "commodity", None, None),
    "DRAM": ("DRAM prices", "commodity", None, ("stocks", "MU")),
    "GPUCOMPUTE": ("GPU rental prices", "commodity", None, ("stocks", "NVDA")),
    # rates
    "UST2Y": ("US 2Y yield", "rates", "2YY=F", None),
    "UST5Y": ("US 5Y yield", "rates", "^FVX", None),
    "UST7Y": ("US 7Y yield", "rates", None, None),
    "UST10Y": ("US 10Y yield", "rates", "^TNX", ("stocks", "TLT")),
    "UST30Y": ("US 30Y yield", "rates", "^TYX", ("stocks", "TLT")),
    "UST10Y2Y": ("10Y-2Y spread", "rates", None, None),
})
FX = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCAD", "USDCHF", "USDINR", "USDMXN", "USDBRL", "USDNOK", "USDSEK"]
for p in FX:
    TOPICS[p] = (f"{p[:3]}/{p[3:]}", "fx", f"{p}=X" if p.startswith("USD") is False else f"{p[3:]}=X", None)
# Yahoo quotes USD-base pairs as e.g. JPY=X (USD/JPY)

# Listed companies: topic = stock ticker. name, yahoo override (non-US listings)
EQUITY = {
    "AAL": "American Airlines", "AAPL": "Apple", "ABNB": "Airbnb", "AC": ("Air Canada", "AC.TO"),
    "AFRM": "Affirm", "ALK": "Alaska Air", "AMZN": "Amazon", "ANF": "Abercrombie & Fitch",
    "ATZ": ("Aritzia", "ATZ.TO"), "AXP": "American Express", "BA": "Boeing", "BBY": "Best Buy",
    "BP": "BP", "BROS": "Dutch Bros", "BTSG": "BrightSpring", "BUD": "AB InBev", "BULL": "Webull",
    "CAKE": "Cheesecake Factory", "CART": "Instacart", "CAVA": "CAVA", "CCL": "Carnival", "CDE": "Coeur Mining",
    "CELH": "Celsius", "CHWY": "Chewy", "CHYM": "Chime", "CMG": "Chipotle", "CMCSA": "Comcast",
    "COIN": "Coinbase", "COST": "Costco", "CRWV": "CoreWeave", "CTC": ("Canadian Tire", "CTC-A.TO"),
    "CVNA": "Carvana", "CVX": "Chevron", "DAL": "Delta Air Lines", "DASH": "DoorDash", "DAVE": "Dave",
    "DDOG": "Datadog", "DG": "Dollar General", "DIS": "Disney", "DKNG": "DraftKings", "DKS": "Dick's Sporting Goods",
    "DOL": ("Dollarama", "DOL.TO"), "DPZ": "Domino's", "DUOL": "Duolingo", "EBAY": "eBay", "ETOR": "eToro",
    "ETSY": "Etsy", "EVLV": "Evolv", "F": "Ford", "FIG": "Figma", "FLUT": "Flutter (FanDuel)", "FSLR": "First Solar",
    "FUTU": "Futu", "GEN": "Gen Digital", "GOOGL": "Alphabet", "GRAB": "Grab", "GRND": "Grindr", "GS": "Goldman Sachs",
    "GTLB": "GitLab", "HD": "Home Depot", "HIMS": "Hims & Hers", "HOOD": "Robinhood", "INTC": "Intel",
    "IOT": "Samsara", "JPM": "JPMorgan", "KDP": "Keurig Dr Pepper", "KLAR": "Klarna", "KO": "Coca-Cola",
    "KR": "Kroger", "KVYO": "Klaviyo", "L": ("Loblaw", "L.TO"), "LIF": "Life360", "LLY": "Eli Lilly",
    "LMND": "Lemonade", "LMT": "Lockheed Martin", "LOW": "Lowe's", "LULU": "Lululemon", "LUV": "Southwest",
    "LYFT": "Lyft", "MAR": "Marriott", "MC": ("LVMH (Sephora)", "MC.PA"), "MCD": "McDonald's", "MDT": "Medtronic",
    "MELI": "MercadoLibre", "META": "Meta", "MNDY": "monday.com", "MNST": "Monster Beverage", "MO": "Altria",
    "MSFT": "Microsoft", "MTCH": "Match Group", "MTN": "Vail Resorts", "MU": "Micron", "NCLH": "Norwegian Cruise Line",
    "NEE": "NextEra Energy", "NET": "Cloudflare", "NFLX": "Netflix", "NTRA": "Natera", "NU": "Nu Holdings",
    "NVDA": "Nvidia", "OKTA": "Okta", "ORCL": "Oracle", "PATH": "UiPath", "PAY": "Paymentus", "PBR": "Petrobras",
    "PDD": "PDD (Temu)", "PEP": "PepsiCo", "PINS": "Pinterest", "PLTR": "Palantir", "PM": "Philip Morris",
    "PSKY": "Paramount Skydance", "PYPL": "PayPal", "QSR": "Restaurant Brands", "RACE": "Ferrari", "RBLX": "Roblox",
    "RDDT": "Reddit", "RELY": "Remitly", "RIVN": "Rivian", "RKLB": "Rocket Lab", "RYAAY": "Ryanair",
    "SBUX": "Starbucks", "SCHW": "Charles Schwab", "SE": "Sea Limited", "SEZL": "Sezzle", "SG": "Sweetgreen",
    "SHAK": "Shake Shack", "SHEL": "Shell", "SHOP": "Shopify", "SNAP": "Snap", "SNOW": "Snowflake", "SOFI": "SoFi",
    "SPOT": "Spotify", "STLA": "Stellantis", "STUB": "StubHub", "STZ": "Constellation Brands", "TAP": "Molson Coors",
    "TGT": "Target", "TLN": "Talen Energy", "TOL": "Toll Brothers", "TOST": "Toast", "TRP": "TC Energy",
    "TSLA": "Tesla", "TTAN": "ServiceTitan", "TTWO": "Take-Two", "UAL": "United Airlines", "UBER": "Uber",
    "ULTA": "Ulta Beauty", "URBN": "Urban Outfitters", "VG": "Venture Global", "VSCO": "Victoria's Secret",
    "VZ": "Verizon", "WBD": "Warner Bros. Discovery", "WDAY": "Workday", "WEN": "Wendy's", "WH": "Wyndham Hotels",
    "WING": "Wingstop", "WK": "Workiva", "WMT": "Walmart", "WSM": "Williams-Sonoma", "XOM": "ExxonMobil",
    "XYZ": "Block (Afterpay)", "YOU": "Clear Secure", "YUM": "Yum! Brands", "ZETA": "Zeta Global", "ZM": "Zoom",
    "BMW": ("BMW", "BMW.DE"), "SNY": "Sanofi", "BBIO": "BridgeBio", "SMMT": "Summit Therapeutics", "ACLX": "Arcellx",
    "NP": "Neptune Insurance",
}
for t, v in EQUITY.items():
    name, yh = (v, t) if isinstance(v, str) else v
    us = "." not in yh
    TOPICS[t] = (name, "equity", yh, ("stocks", t) if us else None)

PRIVATE = {
    "ANTHROPIC": "Anthropic", "OPENAI": "OpenAI", "XAI": "xAI / X", "SPACEX": "SpaceX", "REDBULL": "Red Bull",
    "CHICKFILA": "Chick-fil-A", "SHEIN": "Shein", "RO": "Ro", "C4": "C4 Energy", "ROGUE": "Rogue",
    "PRIVATEIPOS": "Private-company IPOs", "PRIVATELEGAL": "Private-company lawsuits", "WATCHES": "Luxury watches",
}
for t, n in PRIVATE.items():
    TOPICS[t] = (n, "private", None, None)

THEMES = {
    "MNA": "M&A and corporate actions", "LAYOFFS": "Layoffs", "AIRACE": "AI race", "ADSPEND": "Ad spend by sector",
    "CONSUMERSPEND": "Consumer spend trackers", "APPDOWNLOADS": "App download races", "CEOS": "CEO changes",
    "PRICEHIKES": "Price increases", "BIOTECH": "Drug approvals", "OTHER": "Other",
}
for t, n in THEMES.items():
    TOPICS[t] = (n, "theme", None, None)

MACRO = {
    "FED": ("Fed rates", ("stocks", "TLT")), "CPI": ("US inflation (CPI)", None), "JOBS": ("US jobs and unemployment", None),
    "GDP": ("US growth and recession", None), "GASPRICES": ("US gas and diesel prices", ("stocks", "USO")),
    "CENTRALBANKS": ("Global central banks", None), "HOUSING": ("US housing and mortgages", ("stocks", "XHB")),
    "TARIFFS": ("Tariffs and trade", None), "USDEBT": ("US debt and Treasury", None),
    "TRAVEL": ("US travel and tourism", None), "PRODUCTION": ("US production and shipping data", None),
}
for t, (n, ad) in MACRO.items():
    TOPICS[t] = (n, "macro", None, ad)

ECON_RULES = [  # (regex on series-without-KX, topic) for the Economics category, checked in order
    (r"^(FED|RATECUT|RATEHIKE|ZERORATE|FEDCHG)", "FED"),
    (r"(CPI|INFL|ECONSTATCPI|ECONSTATCORECPI)", "CPI"),
    (r"^(AAAGAS|DIESEL)", "GASPRICES"),
    (r"^(U3|UE$|PAYROLL|EMPLOYMENTCOMBO|ECONSTATU3|JOBLESS|NFP)", "JOBS"),
    (r"^(GDP|RECSS|ECONPATH)", "GDP"),
    (r"^(CBD|CBDECISION)", "CENTRALBANKS"),
    (r"^(30YMORT|MORTGAGE|NHSALES|HOUSE|CASESHILLER|EXISTHOME)", "HOUSING"),
    (r"^(TARIFF)", "TARIFFS"),
    (r"^(TGA|DEBT|USDEBT)", "USDEBT"),
    (r"EMP$|EMPLOY|JOBS", "JOBS"),
    (r"PERMIT|HOMESALE|HOUSING", "HOUSING"),
    (r"VISIT|PASSENG|TSA|FLYCANC|AIRPORT|SKI", "TRAVEL"),
    (r"POWER|ERCOT|ELECT", "POWER"),
    (r"CORN|COTTON|BROILER|MAPLE|LOBSTER|QUAHOG|FARMLAND|HARVEST|COAL|CRUDE|OIL$|NATGAS|MARCELLUS|PAPER|TEU|VEHICLEPROD", "PRODUCTION"),
]

# Phrases that identify a topic inside free text (Polymarket titles, new Kalshi series titles).
ALIASES = {
    "FED": ["Fed", "Federal Reserve", "Fed Decision", "FOMC", "rate cut", "rate cuts", "rate hike", "interest rate", "Powell", "Warsh"],
    "CPI": ["CPI", "inflation", "Inflation", "PCE"], "JOBS": ["unemployment", "jobs report", "nonfarm", "payrolls", "jobless"],
    "GDP": ["recession", "GDP"], "GASPRICES": ["gas price", "gas prices", "diesel"], "TARIFFS": ["tariff", "tariffs"],
    "CENTRALBANKS": ["ECB", "Bank of England", "Bank of Japan", "Bank of Canada", "Bank of Russia", "Bank of Mexico", "Bank of Korea", "Reserve Bank", "BoJ", "BoE", "central bank", "rate decision"],
    "HOUSING": ["mortgage", "home sales", "housing", "home value", "home prices"], "USDEBT": ["debt ceiling", "national debt", "Treasury General Account"],
    "SPX": ["S&P 500", "S&P500", "SPX"], "DXY": ["Dollar Index", "DXY"], "NDX": ["Nasdaq-100", "Nasdaq 100", "NASDAQ"], "DJI": ["Dow Jones", "the Dow"],
    "GOLD": ["Gold"], "SILVER": ["Silver"], "WTI": ["WTI", "crude oil", "Crude Oil", "oil price"], "BRENT": ["Brent"],
    "NATGAS": ["natural gas", "Natural Gas"], "COPPER": ["Copper"],
    "UST10Y": ["10-year", "10Y yield", "10-Year"], "UST2Y": ["2-year yield", "2-year Treasury"], "UST30Y": ["30-year yield", "30-year Treasury"], "UST5Y": ["5-year Treasury", "5-year yield"], "RUT": ["Russell 2000"],
    "BTC": ["Bitcoin", "BTC"], "ETH": ["Ethereum", "ETH"], "SOL": ["Solana", "SOL"], "XRP": ["XRP", "Ripple"],
    "DOGE": ["Dogecoin", "DOGE"], "BNB": ["BNB"], "HYPE": ["Hyperliquid", "HYPE"], "ZEC": ["Zcash", "ZEC"],
    "SHIB": ["Shiba Inu"], "NEAR": ["NEAR Protocol"], "STRK": ["Starknet"], "STABLECOINS": ["stablecoin", "USDT", "Tether", "USDC"],
    "ANTHROPIC": ["Anthropic", "Claude"], "OPENAI": ["OpenAI", "ChatGPT", "Sam Altman", "GPT-"], "XAI": ["xAI", "Grok"],
    "SPACEX": ["SpaceX", "Starship", "Starlink"], "TSLA": ["Tesla"], "GOOGL": ["Google", "Alphabet", "Gemini", "Waymo"],
    "META": ["Meta", "Facebook", "Instagram", "Zuckerberg"], "MSFT": ["Microsoft", "Xbox"], "AAPL": ["Apple", "iPhone"],
    "AMZN": ["Amazon"], "NVDA": ["Nvidia", "NVIDIA"], "NFLX": ["Netflix"], "PRIVATEIPOS": ["IPO", "IPOs"],
    "KOSPI": ["KOSPI"], "NIKKEI": ["Nikkei"], "GPUCOMPUTE": ["GPU rental", "H100", "B200"], "DRAM": ["DRAM", "DDR5"],
    "CRYPTO": ["launch a token", "FDV", "airdrop", "memecoin", "crypto market"],
    "MNA": ["acquire", "acquisition", "merger"], "LAYOFFS": ["layoff", "layoffs"], "AIRACE": ["AGI", "best AI model", "top AI model", "AI model", "AI bubble"],
}
TOPICS["MACRO"] = ("Macro (other)", "macro", None, None)

# ---------------------------------------------------------------- series rules
# Exact series (without the KX prefix) -> topic, checked first.
EXACT = {
    # Treasury
    "10Y2Y": "UST10Y2Y", "10Y2YDATE": "UST10Y2Y", "NOTE10Y": "UST10Y",
    # indices
    "FEAR": "FEARGREED", "ME": "IPC", "NDQDIRY": "NDX", "NASDAQDUD": "NDX",
    "INXVSBTC": "SPX", "INXVSGOLD": "SPX", "INXVSINXEW": "SPX", "DJIAREMOVE": "INDEXCHANGES",
    "MSCIADDQ": "INDEXCHANGES", "MSCIREMOVEQ": "INDEXCHANGES", "SP500ADDQ": "INDEXCHANGES",
    "SP500REMOVEQ": "INDEXCHANGES", "SP500WHEN": "SPX",
    # commodities
    "ALMWP": "ALUMINUM", "DXYVSGOLD": "GOLD", "B65": "BEEF", "B85": "BEEF", "EUBEEFQ": "BEEF",
    "APSMM": "TUNGSTEN", "APTROT": "TUNGSTEN", "DRAMAY": "DRAM", "WTIVSBRENT": "WTI",
    "KEYSTONEFID": "TRP",
    # crypto
    "SHIBA": "SHIB", "SHIBAD": "SHIB", "STABLETOTAL": "STABLECOINS", "CRYPTOLEAD15M": "CRYPTO",
    "CRYPTOPAY": "CRYPTO", "CRYPTORETURNY": "CRYPTO", "TOKENLAUNCH": "CRYPTO", "FDVOPENSEA": "CRYPTO",
    "SATOSHIBTCYEAR": "BTC", "BTCVSGOLD": "BTC", "SOLE": "SOL",
    # companies (series whose base is not the stock ticker)
    "AALA": "AAL", "AALCC": "AAL", "ACA": "AC", "ALKA": "ALK", "AMZNA": "AMZN", "AMZNCC": "AMZN", "AAPLA": "AAPL",
    "AFRMCC": "AFRM", "AFTERPAYCC": "XYZ", "ANFCC": "ANF", "BPCC": "BP", "BKFT": "QSR", "BUDLIGHTPOS": "BUD",
    "CELSIUSPOS": "CELH", "ALANIPOS": "CELH", "COCACOLAPOS": "KO", "SPRITEPOS": "KO", "COORSLIGHTPOS": "TAP",
    "MILLERLITEPOS": "TAP", "DRPEPPERPOS": "KDP", "MONSTERPOS": "MNST", "MOUNTAINDEWPOS": "PEP",
    "PEPSIPOS": "PEP", "ROCKSTARPOS": "PEP", "ONPOS": "MO", "ZYNPOS": "PM", "PMA": "PM", "VELOPOS": "BTI",
    "REDBULLPOS": "REDBULL", "C4POS": "C4", "ROGUEPOS": "ROGUE", "CFILCC": "CHICKFILA", "SHEINCC": "SHEIN",
    "ROCC": "RO", "SEPHORACC": "MC", "TEMUCC": "PDD", "EXXONCC": "XOM", "CVXCC": "CVX", "SHELCC": "SHEL",
    "LLYCC": "LLY", "COINA": "COIN", "COINBASE": "COIN", "SNOWA": "SNOW", "SNOWFLAKE": "SNOW", "GOOG": "GOOGL",
    "GOOGA": "GOOGL", "GEMINIAPP": "GOOGL", "GEMINI35OY": "GOOGL", "GEMINI35Y": "GOOGL", "WAYMO": "GOOGL",
    "COMPANYACTIONWAYMO": "GOOGL", "DISA": "DIS", "DISNEYAPP": "DIS", "ESPNAPP": "DIS", "HULUAPP": "DIS",
    "FANDUELAPP": "FLUT", "MAXAPP": "WBD", "PARAMOUNTAPP": "PSKY", "RELOCATEPSKY": "PSKY", "PEACOCKAPP": "CMCSA",
    "UBEREAPP": "UBER", "JOINUBER": "UBER", "FA": "F", "IOTA": "IOT", "LOBA": "L", "DOLA": "DOL", "CTCA": "CTC",
    "CTCQ": "CTC", "LUVA": "LUV", "LUVCC": "LUV", "UALA": "UAL", "UALCC": "UAL", "RELOCATEUNITED": "UAL",
    "METAA": "META", "ACQUANNOUNCEMETA": "META", "NFLXA": "NFLX", "NFLXAPP": "NFLX", "NFLXINCREASE": "NFLX",
    "NETFLIXSTUDIO": "NFLX", "NVDAA": "NVDA", "VERARELEASE": "NVDA", "ORCLA": "ORCL", "PATHA": "PATH",
    "PBRA": "PBR", "SEA": "SE", "SGA": "SG", "SGFT": "SG", "SHAKFT": "SHAK", "SPCXA": "SPACEX",
    "STARSHIPMARS": "SPACEX", "TOLA": "TOL", "VSXY": "VSCO", "VSXYA": "VSCO", "WHA": "WH", "YUMTBFT": "YUM",
    "NPA": "NP", "MOA": "MO", "MTCHA": "MTCH", "HOODA": "HOOD", "HIMSA": "HIMS", "INTCA": "INTC", "MELIA": "MELI",
    "NUA": "NU", "PLTRA": "PLTR", "RACEA": "RACE", "LUCEDELIVERY": "RACE", "RDDTA": "RDDT",
    "COMPANYACTIONRDDT": "RDDT", "RIVNA": "RIVN", "SCHWA": "SCHW", "STZA": "STZ", "TOSTA": "TOST", "TSLAA": "TSLA",
    "YOUA": "YOU", "MARA": "MAR", "CCLA": "CCL", "NCLHA": "NCLH", "COMPANYACTIONTTWO": "TTWO",
    "ACQANNOUNCEEBAY": "EBAY", "ACQANNOUNCEGEN": "GEN", "ACQANNOUNCEGS": "GS", "NEWROLEGS": "GS",
    "ACQANNOUNCEJPM": "JPM", "JPMCEOCHANGE": "JPM", "JPMCEONEW": "JPM", "NEWROLEJP": "JPM",
    "ACQANNOUNCESBUX": "SBUX", "ACQANNOUNCEWDAY": "WDAY", "ACQPYPL": "PYPL", "ACQUANNOUNCEPINS": "PINS",
    "ACQANNOUNCESPACEX": "TSLA", "COMPANYACTIONMERGER": "TSLA", "ROADSTERPRICE": "TSLA",
    "COMPANYSTAKERYANAIR": "RYAAY", "CEODAL": "DAL", "TAKEOVERNEE": "NEE", "IPHONERELEASE": "AAPL",
    "MACBOOKPRICE": "AAPL", "MACCELL": "AAPL", "APPLEUS": "AAPL", "APPLEOPENAICASE": "AAPL", "NEWXBOX": "MSFT",
    "ELECTRICM3": "BMW", "HELLCAT": "STLA", "VENGLUSTAT": "SNY", "BBP418": "BBIO", "IVONESCIMAB": "SMMT",
    "ANITOCABTAGENE": "ACLX", "SAROGLITAZAR": "BIOTECH", "PRICEINCREASESPOTIFY": "SPOT",
    "PRICEINCREASESPOTIFYDUO": "SPOT", "PRICEINCREASESPOTIFYFAMILY": "SPOT",
    # private companies and themes
    "CLAUDEAPP": "ANTHROPIC", "IPOANTHROPIC": "ANTHROPIC", "CHIPBURRITO": "CMG", "BKDWHOPPER": "QSR", "WENBACONATOR": "WEN", "POPCHICKSAND": "QSR", "MUSKWEALTH": "TSLA", "SIENNAMSRP": "TM", "IPOOPENAI": "OPENAI", "IPODISCORD": "PRIVATEIPOS", "LAYOFFSYINFO": "LAYOFFS", "CEOANTHROPIC": "ANTHROPIC",
    "COMPANYACTIONANTH": "ANTHROPIC", "SUPERVOTEDARIO": "ANTHROPIC", "PRICEINCREASECLAUDE": "ANTHROPIC",
    "OPUS48OY": "ANTHROPIC", "OPUS48Y": "ANTHROPIC", "GPTAPP": "OPENAI", "GPT55Y": "OPENAI", "GBT55OY": "OPENAI",
    "NEWROLEOPENAI": "OPENAI", "SUPERVOTEALTMAN": "OPENAI", "OPENAICEOCHANGE": "OPENAI", "OAIANTH": "AIRACE",
    "AGICO": "AIRACE", "AIAPPARRAY": "APPDOWNLOADS", "GROKAPP": "XAI", "XAIGAME": "XAI", "NEWROLEX": "XAI",
    "XMONEYAPY": "XAI", "IPO": "PRIVATEIPOS", "IPOBLOOMBERG": "PRIVATEIPOS", "IPOCANVA": "PRIVATEIPOS",
    "IPOPERPLEXITY": "PRIVATEIPOS", "IPOSKIMS": "PRIVATEIPOS", "KRAKENBANKPUBLIC": "PRIVATEIPOS",
    "DATABRICKS": "PRIVATEIPOS", "RAMPBREX": "PRIVATEIPOS", "DEELRIP": "PRIVATELEGAL",
    "RIPPLINGDEEL": "PRIVATELEGAL", "BEZELP": "WATCHES", "BEZELR": "WATCHES", "BEZELRO": "WATCHES",
    "ACQANNOUNCEANNUAL": "MNA", "ACQLETTERBOXD": "MNA", "USACOMPANYSTAKE": "MNA", "USFUNDHEAD": "MNA",
    "COMPANYACTIONLAYOFF": "LAYOFFS", "COMPANYLAYOFF": "LAYOFFS", "NEWROLEFAZE": "CEOS",
    "PRICEINCREASEAZICEDTEA": "PRICEHIKES", "BIGBOXARRAY": "CONSUMERSPEND", "FASTARRAY": "CONSUMERSPEND",
    "ENERGYARRAY": "CONSUMERSPEND", "NICOTINEARRAY": "CONSUMERSPEND", "SODAARRAY": "CONSUMERSPEND",
    "DELIVARRAY": "APPDOWNLOADS", "RIDEARRAY": "APPDOWNLOADS", "STREAMARRAY": "APPDOWNLOADS",
    "LYFTAPP": "LYFT", "UBERAPP": "UBER", "DASHAPP": "DASH", "DKNGAPP": "DKNG", "CARTAPP": "CART",
    "GRUBHUBAPP": "APPDOWNLOADS",
}
# ETFs and index tickers that stand for a topic when they appear as a ticker
ETF_TOPIC = {"SPY": "SPX", "VOO": "SPX", "QQQ": "NDX", "DIA": "DJI", "IWM": "RUT", "GLD": "GOLD", "SLV": "SILVER", "USO": "WTI",
             "UNG": "NATGAS", "EWY": "KOSPI", "EWJ": "NIKKEI", "EWZ": "IBOV", "INDA": "NIFTY", "TLT": "UST10Y", "UUP": "DXY",
             "IBIT": "BTC", "ETHA": "ETH", "SPX": "SPX", "NDX": "NDX", "RUT": "RUT", "VIX": "FEARGREED"}
TOPICS["TM"] = ("Toyota", "equity", "TM", ("stocks", "TM"))
TOPICS["BTI"] = ("British American Tobacco", "equity", "BTI", ("stocks", "BTI"))

PREFIX = [  # (regex on series-without-KX, topic) checked in order
    (r"^(10Y|10YR|UST10|10YRRATE)", "UST10Y"), (r"^(2Y|2YR|UST2)", "UST2Y"), (r"^(30Y|30YR|UST30)", "UST30Y"),
    (r"^(5Y|5YR|UST5)", "UST5Y"), (r"^(7Y|7YR|UST7)", "UST7Y"),
    (r"^(INX|SP500)", "SPX"), (r"^NASDAQ100", "NDX"), (r"^DJI", "DJI"), (r"^NIKKEI", "NIKKEI"),
    (r"^KOSPI", "KOSPI"), (r"^NIFTY", "NIFTY"), (r"^TSX", "TSX"), (r"^IBOV", "IBOV"),
    (r"^GOLD", "GOLD"), (r"^SILVER", "SILVER"), (r"^COPPER", "COPPER"), (r"^PLATINUM", "PLATINUM"),
    (r"^PALLADIUM", "PALLADIUM"), (r"^WTI", "WTI"), (r"^BRENT", "BRENT"), (r"^NATGAS", "NATGAS"),
    (r"^(ERCOT|PJM|MISO)", "POWER"), (r"^DDR5", "DRAM"), (r"^(A100|B200|H100|H200|RTX5090)", "GPUCOMPUTE"),
    (r"^(BTC)", "BTC"), (r"^(ETH)(?!OR)", "ETH"), (r"^SOL", "SOL"), (r"^XRP", "XRP"), (r"^DOGE", "DOGE"),
    (r"^BNB", "BNB"), (r"^HYPE", "HYPE"), (r"^ZEC", "ZEC"), (r"^NEAR", "NEAR"), (r"^STRK", "STRK"),
    (r"ADS$", "ADSPEND"), (r"^(TESLA)", "TSLA"), (r"^(ANTHROPIC)", "ANTHROPIC"), (r"^(OPENAI)", "OPENAI"),
    (r"^(" + "|".join(FX) + r")", None),  # handled below
]

_SUFFIXES = ("CC", "FT", "APP", "POS", "A")


def map_series(series: str, title: str = "", tags=None, category: str | None = None) -> dict:
    """Return {topic, mapped, rule} for a Kalshi series ticker (with or without the KX prefix)."""
    s = series[2:] if series.startswith("KX") else series
    if category == "Economics" and s not in EXACT:
        for pat, topic in ECON_RULES:
            if re.search(pat, s):
                return dict(topic=topic, mapped=True, rule="economics")
    if s in EXACT:
        return dict(topic=EXACT[s], mapped=True, rule="exact")
    for pat, topic in PREFIX:
        m = re.match(pat, s) if pat.startswith("^") else re.search(pat, s)
        if m:
            if topic is None:
                return dict(topic=m.group(1), mapped=True, rule="fx")
            return dict(topic=topic, mapped=True, rule="prefix")
    # stock-ticker series: KXTSLA, KXCMGFT, KXHDCC, KXMCDA ...
    if s in TOPICS and TOPICS[s][1] == "equity":
        return dict(topic=s, mapped=True, rule="ticker")
    for suf in _SUFFIXES:
        if s.endswith(suf) and s[: -len(suf)] in TOPICS and TOPICS[s[: -len(suf)]][1] == "equity":
            return dict(topic=s[: -len(suf)], mapped=True, rule="ticker+" + suf)
    tags = tags or []
    if any(t in ("Medicine", "Biotech") for t in tags):
        return dict(topic="BIOTECH", mapped=True, rule="tag")
    if "CEOs" in tags:
        return dict(topic="CEOS", mapped=True, rule="tag")
    if "M&A" in tags:
        return dict(topic="MNA", mapped=True, rule="tag")
    return dict(topic=s, mapped=False, rule="unmapped", fallback_class="macro" if category == "Economics" else "theme")


EXTRA: dict[str, tuple] = {}  # topics created at run time (registry): id -> (name, class, price symbol, adanos)


def topic_info(topic: str, fallback_name: str = "", fallback_class: str = "theme") -> dict:
    if topic in TOPICS:
        name, ac, yh, ad = TOPICS[topic]
    elif topic in EXTRA:
        name, ac, yh, ad = EXTRA[topic]
    else:
        name, ac, yh, ad = fallback_name or topic, fallback_class, None, None
    return dict(topic=topic, name=name, asset_class=ac, price_symbol=yh,
                adanos_kind=ad[0] if ad else None, adanos_symbol=ad[1] if ad else None)
