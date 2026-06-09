"""
Chain / franchise detection filter v2.
Keeps local independent businesses; rejects national/regional chains.
"""

import re

CHAIN_KEYWORDS = [
    # ── Fast food ────────────────────────────────────────────────────────────
    "mcdonald", "burger king", "wendy's", "wendys", "taco bell", "subway",
    "domino's", "dominos", "pizza hut", "little caesars", "little caesar",
    "kfc", "popeye", "chick-fil-a", "chickfila", "chick fil a",
    "sonic drive", "dairy queen", "dq grill",
    "arby", "jack in the box", "whataburger", "five guys", "shake shack",
    "in-n-out", "in n out", "hardee", "carl's jr", "carls jr",
    "chipotle", "qdoba", "moe's", "moes southwest",
    "panda express", "wingstop", "raising cane", "zaxby",
    "starbucks", "dunkin'", "dunkin ", "tim horton", "panera", "jersey mike",
    "firehouse sub", "jimmy john", "potbelly", "quiznos",
    "culver", "cook out", "cookout", "del taco", "el pollo loco", "pollo tropical",
    "captain d's", "captain ds", "long john silver", "church's chicken",
    "churchs chicken", "krystal", "checkers", "rally's", "rallys",
    "steak 'n shake", "steak n shake", "fatburger", "habit burger",
    "smashburger", "freddy's", "freddys",
    "braum's", "braums", "slim chickens", "portillo's", "portillos",
    "slim chicken", "raising cane's", "zaxby's",
    "bojangles", "popeyes", "mcalister's", "mcalisters",
    "jason's deli", "jasons deli", "which wich",
    "schlotzsky", "schlotzskys", "blimpie",
    "penn station sub", "charley's grilled", "charleys grilled",
    "tropical smoothie", "jamba juice", "jamba", "smoothie king",
    "white castle", "krystal burger",
    "wienerschnitzel", "hot dog on a stick",
    "del taco", "taco john's", "taco johns",
    # ── Coffee / bakery chains ───────────────────────────────────────────────
    "coffee bean", "peet's coffee", "peets coffee", "dutch bros",
    "caribou coffee", "biggby", "scooter's coffee", "scooters coffee",
    "einstein bros", "einstein bagel",
    "bruegger", "noah's bagel", "noahs bagel", "great harvest",
    "nothing bundt", "cinnabon", "auntie anne", "auntie annes",
    "pretzelmaker", "wetzel's", "wetzels",
    # ── Pizza chains ─────────────────────────────────────────────────────────
    "papa john", "papa murphy", "round table pizza", "godfather's",
    "godfathers pizza", "hungry howie", "marcos pizza", "marco's pizza",
    "mod pizza", "blaze pizza", "pieology", "pizza ranch",
    "donatos", "cicis", "cici's", "jet's pizza", "jets pizza",
    "sbarro",
    # ── Casual / family dining ───────────────────────────────────────────────
    "applebee", "chili's", "chilis", "olive garden", "red lobster",
    "outback steakhouse", "longhorn steakhouse", "texas roadhouse",
    "cracker barrel", "ihop", "denny's", "dennys", "waffle house",
    "bob evans", "perkins", "village inn", "golden corral",
    "buffalo wild wings", "bdubs", "hooters", "ruby tuesday",
    "red robin", "tgi friday", "cheesecake factory",
    "p.f. chang", "pf chang", "benihana", "famous dave",
    "sizzler", "dine brands", "dine equity", "logan's roadhouse",
    "logans roadhouse", "marie callender", "bonefish grill",
    "carrabba", "fleming's", "flemings", "bloomin brands", "bloomin' brands",
    "cheddar's", "cheddars", "on the border", "el torito",
    "california pizza kitchen", "cpk", "mimi's cafe", "mimis cafe",
    "first watch", "eggs up grill", "broken yolk",
    "bahama breeze", "yard house", "seasons 52",
    "o'charley's", "ocharleys", "frisch's big boy", "frischs big boy",
    "big boy restaurant",
    "jack's family", "the melting pot", "melting pot",
    "shari's", "sharis", "noodles and company", "noodles & company",
    "zoe's kitchen", "zoës kitchen", "souplantation", "sweet tomatoes",
    "yum brands", "restaurant brands",
    "noodles & company", "corner bakery",
    "dave & buster", "dave and buster",
    "chuck e. cheese", "chuck e cheese",
    # ── Ice cream / dessert chains ───────────────────────────────────────────
    "baskin-robbins", "baskin robbins", "cold stone creamery",
    "marble slab creamery", "marble slab",
    "yogurtland", "menchie's", "menchies",
    "orange julius", "rita's italian ice", "ritas italian ice",
    "orange leaf", "tcby", "haagen-dazs", "haagen dazs",
    "ben & jerry's", "ben and jerrys",
    "maggie moo's", "maggie moos",
    # ── Fast casual ──────────────────────────────────────────────────────────
    "tijuana flats", "pei wei", "mcalister's deli",
    # ── Convenience / gas stations ───────────────────────────────────────────
    "7-eleven", "7 eleven", "circle k", "speedway ",
    "wawa ", "casey's general", "kwik trip", "kwik star",
    "love's travel", "pilot flying j", "pilot travel", "flying j",
    "sheetz ", "quiktrip", "quick trip", "racetrac",
    "thorntons ", "kum & go", "kum and go", "fas mart",
    "bp gas", "bp station", "shell gas", "shell station",
    "exxonmobil", "exxon mobil", "exxon station",
    "chevron gas", "chevron station",
    "marathon gas", "marathon petroleum",
    "sunoco ", "holiday stationstores",
    # ── Retail / grocery ─────────────────────────────────────────────────────
    "walmart", "wal-mart", "target ", "kroger", "meijer", "aldi ",
    "lidl ", "publix", "safeway", "albertsons", "h-e-b", "heb ",
    "food lion", "giant eagle", "winn-dixie", "winn dixie",
    "piggly wiggly", "trader joe's", "trader joes", "whole foods",
    "costco", "sam's club", "sams club", "bj's wholesale",
    "wegmans", "stop & shop", "stop and shop", "hannaford",
    "price chopper", "market basket", "shaw's", "shaws ",
    "harris teeter", "ralphs ", "fred meyer", "smiths food",
    "king soopers", "city market", "fry's food",
    "sprouts farmers market", "fresh market", "winco",
    "hy-vee", "hyvee",
    # ── Dollar / discount stores ─────────────────────────────────────────────
    "dollar general", "family dollar", "dollar tree", "five below",
    "big lots",
    # ── Home improvement / hardware ──────────────────────────────────────────
    "home depot", "the home depot", "lowe's", "lowes home", "lowes ",
    "menards ", "ace hardware", "true value hardware", "true value ",
    "do it best", "84 lumber",
    # ── Auto / tire / service chains ─────────────────────────────────────────
    "autozone", "o'reilly auto", "oreilly auto", "advance auto",
    "jiffy lube", "valvoline instant", "midas auto", "midas ",
    "firestone complete", "goodyear tire", "pep boys",
    "napa auto", "meineke", "monro muffler", "car-x",
    "christian brothers auto", "christian brothers automotive",
    "take 5 oil", "express oil change",
    "tires plus", "discount tire", "ntb tire",
    "mavis discount tire", "sullivan tire", "belle tire",
    "safelite", "carmax", "carvana",
    # ── Hair / beauty ────────────────────────────────────────────────────────
    "great clips", "supercuts", "sport clips", "cost cutters",
    "fantastic sam's", "fantastic sams", "regis salon", "regis salons",
    "hair cuttery", "first choice haircutters",
    "ulta beauty", "ulta salon", "sally beauty",
    "floyd's barbershop", "roosters men's grooming",
    "european wax center", "massage envy", "hand and stone",
    # ── Fitness ──────────────────────────────────────────────────────────────
    "planet fitness", "anytime fitness", "la fitness", "24 hour fitness",
    "gold's gym", "golds gym", "crunch fitness", "orangetheory",
    "orange theory fitness", "f45 training", "club pilates", "pure barre",
    "snap fitness", "retro fitness", "youfit",
    "lifetime fitness", "life time fitness",
    "equinox ", "soulcycle", "cyclebar",
    "burn boot camp", "title boxing",
    "curves fitness", "curves ",
    "the joint chiropractic",
    # ── Hotel / lodging ──────────────────────────────────────────────────────
    "holiday inn", "best western", "comfort inn", "days inn",
    "super 8", "motel 6", "hampton inn", "marriott",
    "hilton hotel", "hilton garden", "hilton inn",
    "hyatt ", "sheraton", "ramada", "quality inn", "fairfield inn",
    "courtyard by marriott", "residence inn", "springhill suites",
    "towneplace suites", "homewood suites", "home2 suites",
    "embassy suites", "doubletree", "aloft hotel", "westin hotel",
    "le meridien", "four points by sheraton",
    "delta hotels", "renaissance hotel", "autograph collection",
    "la quinta", "drury inn", "red roof inn", "sleep inn",
    "candlewood suites", "staybridge suites", "extended stay",
    "wyndham", "radisson", "choice hotels",
    "tru by hilton", "curio collection",
    "intercontinental hotel", "crowne plaza",
    "kimpton hotel", "four seasons hotel", "ritz-carlton", "ritz carlton",
    "microtel inn", "woodspring suites",
    "econo lodge", "rodeway inn", "clarion hotel",
    "mainstay suites", "suburban extended stay",
    # ── Banking / financial (specific named chains) ───────────────────────────
    "chase bank", "bank of america", "wells fargo", "citibank",
    "us bank", "u.s. bank", "pnc bank", "regions bank",
    "fifth third bank", "suntrust", "truist", "td bank", "bb&t",
    "ameriprise", "edward jones", "merrill lynch", "fidelity investments",
    "navy federal", "usaa",
    # ── Pharmacy ─────────────────────────────────────────────────────────────
    "walgreens", "cvs pharmacy", "cvs health", "rite aid", "duane reade",
    # ── Telecom retail ───────────────────────────────────────────────────────
    "at&t store", "at&t wireless", "t-mobile store", "tmobile ",
    "verizon wireless", "verizon store", "sprint store",
    "boost mobile", "metro pcs", "metropcs",
    # ── Electronics / tech retail ─────────────────────────────────────────────
    "best buy", "bestbuy", "apple store", "microsoft store",
    "radio shack", "radioshack",
    # ── Healthcare chains ─────────────────────────────────────────────────────
    "concentra ", "medexpress", "md now", "nextcare",
    "statcare", "american family care",
    "carespot", "patient first", "carenow",
    "minuteclinic", "minute clinic", "urgent care express",
    # ── Veterinary / pet ─────────────────────────────────────────────────────
    "banfield pet hospital", "vca animal", "vca hospitals",
    "petsmart", "petco", "pet supplies plus",
    # ── Pest / cleaning services ─────────────────────────────────────────────
    "terminix", "orkin pest", "rentokil",
    "molly maid", "merry maids", "the maids",
    "servpro", "servicemaster", "stanley steemer",
    # ── Shipping / printing ───────────────────────────────────────────────────
    "the ups store", "ups store", "fedex office", "fedex store",
    "mailboxes etc", "pak mail", "uhaul", "u-haul",
    # ── Tax / financial services ──────────────────────────────────────────────
    "h&r block", "jackson hewitt", "liberty tax",
    # ── Staffing (national) ───────────────────────────────────────────────────
    "robert half", "manpower staffing", "adecco", "kelly services",
    "staffmark", "randstad", "aerotek",
    # ── Child care / education ───────────────────────────────────────────────
    "kindercare", "learning care group", "bright horizons",
    "the learning experience", "primrose schools",
    "goddard school", "kumon learning", "sylvan learning",
    # ── Sporting goods / outdoor ──────────────────────────────────────────────
    "dick's sporting goods", "dicks sporting", "academy sports",
    "cabela's", "cabelas", "bass pro shops", "bass pro shop",
    "rei ", "big 5 sporting",
    # ── Clothing / apparel ───────────────────────────────────────────────────
    "old navy", "gap store", "banana republic", "athleta ",
    "h&m store", "zara store", "forever 21",
    "american eagle outfitters", "hollister", "abercrombie",
    "victoria's secret", "victoria secret",
    "bath & body works", "bath and body works",
    # ── Real estate / property chains ─────────────────────────────────────────
    "re/max", "remax ", "keller williams", "coldwell banker",
    "century 21 real estate", "berkshire hathaway realt",
    "exp realty", "exit realty",
]

# Regex patterns for franchise numbering
_FRANCHISE_RE = [
    re.compile(r'#\s*\d{3,}', re.IGNORECASE),            # "Subway #1234"
    re.compile(r'\bno\.?\s*\d{2,}', re.IGNORECASE),      # "No. 42"
    re.compile(r'\blocation\s+\d+', re.IGNORECASE),       # "Location 5"
    re.compile(r'\bstore\s+#?\s*\d{3,}', re.IGNORECASE), # "Store #0042"
    re.compile(r'\bunit\s+#?\s*\d{3,}', re.IGNORECASE),  # "Unit 1138"
]

# Named national banks (avoids false-positives on "Riverbank Bistro")
_BANK_RE = re.compile(
    r'\b(chase|wells fargo|bank of america|citibank|usaa|navy federal'
    r'|us bank|u\.s\. bank|pnc bank|regions bank|fifth third'
    r'|keybank|key bank|huntington bank|td bank|truist|suntrust|bb&?t'
    r'|citizens bank|capital one bank|ally bank)\b',
    re.IGNORECASE,
)

# Generic "First National Bank"-style patterns
_GENERIC_BANK_RE = re.compile(
    r'\b(national|federal|first|community|heritage|peoples|american|united)\s+'
    r'(bank|savings bank|savings & loan|savings and loan)\b',
    re.IGNORECASE,
)

_CREDIT_UNION_RE = re.compile(r'\bcredit union\b', re.IGNORECASE)


def is_chain(name: str) -> bool:
    """Return True if *name* looks like a chain / franchise, not a local independent."""
    if not name:
        return False
    n = name.lower().strip()

    # 1. Keyword substring match
    if any(k in n for k in CHAIN_KEYWORDS):
        return True

    # 2. Franchise number patterns (#1234, No. 42, Store #0042 …)
    if any(p.search(name) for p in _FRANCHISE_RE):
        return True

    # 3. Named national banks
    if _BANK_RE.search(name):
        return True

    # 4. Generic bank phrasing ("First National Bank", "Heritage Savings Bank")
    if _GENERIC_BANK_RE.search(name):
        return True

    # 5. Any credit union
    if _CREDIT_UNION_RE.search(name):
        return True

    return False
