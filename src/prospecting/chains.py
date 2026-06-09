CHAIN_KEYWORDS = [
    "mcdonald","burger king","wendys","taco bell","subway","dominos",
    "pizza hut","little caesars","kfc","popeyes","chick-fil-a","sonic",
    "dairy queen","dq grill","arbys","jack in the box","whataburger",
    "five guys","shake shack","chipotle","qdoba","panda express",
    "wingstop","raising canes","starbucks","dunkin","panera",
    "jersey mikes","firehouse subs","jimmy johns","applebees","chilis",
    "olive garden","red lobster","outback steakhouse","longhorn steakhouse",
    "texas roadhouse","cracker barrel","ihop","dennys","waffle house",
    "bob evans","golden corral","buffalo wild wings","hooters","ruby tuesday",
    "red robin","tgi fridays","cheesecake factory","pf changs",
    "dollar general","family dollar","autozone","great clips","supercuts",
    "planet fitness","holiday inn","best western","motel 6","hampton inn",
]

def is_chain(name):
    if not name: return False
    n = name.lower()
    return any(k in n for k in CHAIN_KEYWORDS)
