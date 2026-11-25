"""Static seed inputs: stations, routes and name pools.

ALL OF THIS IS SIMULATED. Station coordinates are approximate (good to a km or
two); train numbers start with 9 and operators are invented so nothing here can
be mistaken for real IRCTC or bus-operator data.
"""

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class StationSeed:
    code: str
    name: str
    city: str
    lat: float
    lon: float
    is_primary: bool = False
    aliases: tuple[str, ...] = ()  # extra spellings; name, code and (for primary) city are added automatically


def _s(code, name, city, lat, lon, primary=False, *aliases):
    return StationSeed(code, name, city, lat, lon, primary, aliases)


STATIONS: tuple[StationSeed, ...] = (
    # Bengaluru: alternatives sit ~4, ~11, ~14 and ~28 km from SBC (drives the 5/15/30 km experiment).
    _s("SBC", "KSR Bengaluru City", "Bengaluru", 12.9783, 77.5683, True,
       "bangalore", "blr", "bangaluru", "banglore", "बेंगलुरु", "बैंगलोर", "बंगलौर", "ಬೆಂಗಳೂರು"),
    _s("BNC", "Bengaluru Cantonment", "Bengaluru", 12.9930, 77.5990),
    _s("YPR", "Yesvantpur Junction", "Bengaluru", 13.0230, 77.5510, False, "yeshwantpur"),
    _s("SMVB", "SMVT Bengaluru (Baiyappanahalli)", "Bengaluru", 13.0090, 77.6680, False, "baiyappanahalli", "smvt"),
    _s("KJM", "Krishnarajapuram", "Bengaluru", 13.0050, 77.6980, False, "kr puram", "krishnarajapuram"),
    _s("BID", "Bidadi", "Bengaluru", 12.7970, 77.3880),
    _s("HYB", "Hyderabad Deccan (Nampally)", "Hyderabad", 17.3890, 78.4690, True,
       "hyd", "hydrabad", "nampally", "हैदराबाद", "హైదరాబాద్"),
    _s("KCG", "Kacheguda", "Hyderabad", 17.3870, 78.4990),
    _s("SC", "Secunderabad Junction", "Hyderabad", 17.4339, 78.5011, False, "secunderabad", "सिकंदराबाद"),
    _s("HTE", "Hitec City", "Hyderabad", 17.4430, 78.3770, False, "hi tech city", "hitech city"),
    _s("LPI", "Lingampalli", "Hyderabad", 17.4930, 78.3190),
    _s("NDLS", "New Delhi", "Delhi", 28.6429, 77.2191, True, "dilli", "ndls", "दिल्ली", "नई दिल्ली"),
    _s("DLI", "Old Delhi", "Delhi", 28.6607, 77.2279, False, "delhi junction", "पुरानी दिल्ली"),
    _s("NZM", "Hazrat Nizamuddin", "Delhi", 28.5880, 77.2540, False, "nizamuddin"),
    _s("ANVT", "Anand Vihar Terminal", "Delhi", 28.6510, 77.3160, False, "anand vihar"),
    _s("MMCT", "Mumbai Central", "Mumbai", 18.9690, 72.8190, True, "bombay", "मुंबई", "मुम्बई", "बॉम्बे"),
    _s("CSMT", "Mumbai CSMT", "Mumbai", 18.9400, 72.8355, False, "cst", "victoria terminus"),
    _s("LTT", "Lokmanya Tilak Terminus", "Mumbai", 19.0690, 72.8890, False, "kurla", "ltt"),
    _s("DR", "Dadar", "Mumbai", 19.0190, 72.8420, False, "dadar"),
    _s("PUNE", "Pune Junction", "Pune", 18.5290, 73.8740, True, "poona", "पुणे"),
    _s("SVJR", "Shivajinagar", "Pune", 18.5320, 73.8480),
    _s("MAS", "Chennai Central", "Chennai", 13.0827, 80.2757, True, "madras", "चेन्नई", "சென்னை", "மெட்ராஸ்"),
    _s("MS", "Chennai Egmore", "Chennai", 13.0732, 80.2609, False, "egmore"),
    _s("TBM", "Tambaram", "Chennai", 12.9249, 80.1190),
    _s("HWH", "Howrah Junction", "Kolkata", 22.5830, 88.3420, True, "calcutta", "howrah", "कोलकाता", "कलकत्ता"),
    _s("SDAH", "Sealdah", "Kolkata", 22.5670, 88.3700),
    _s("KOAA", "Kolkata Terminal", "Kolkata", 22.6200, 88.3770, False, "chitpur"),
    _s("KOTA", "Kota Junction", "Kota", 25.1800, 75.8650, True, "कोटा"),
    _s("JP", "Jaipur Junction", "Jaipur", 26.9195, 75.7873, True, "जयपुर"),
    _s("ADI", "Ahmedabad Junction", "Ahmedabad", 23.0260, 72.6010, True, "amdavad", "अहमदाबाद"),
    _s("LKO", "Lucknow Charbagh", "Lucknow", 26.8325, 80.9230, True, "charbagh", "लखनऊ"),
    _s("LJN", "Lucknow Junction", "Lucknow", 26.8300, 80.9300),
)

# Directed both ways. Chosen so Kota (the sponsor brief's example) and the
# demo route Bengaluru <-> Hyderabad are well covered.
CITY_PAIRS: tuple[tuple[str, str], ...] = (
    ("Bengaluru", "Hyderabad"),
    ("Bengaluru", "Chennai"),
    ("Bengaluru", "Pune"),
    ("Bengaluru", "Mumbai"),
    ("Bengaluru", "Delhi"),
    ("Bengaluru", "Kota"),
    ("Hyderabad", "Mumbai"),
    ("Hyderabad", "Delhi"),
    ("Hyderabad", "Kota"),
    ("Hyderabad", "Chennai"),
    ("Hyderabad", "Pune"),
    ("Delhi", "Kota"),
    ("Delhi", "Jaipur"),
    ("Delhi", "Lucknow"),
    ("Delhi", "Kolkata"),
    ("Mumbai", "Pune"),
    ("Mumbai", "Ahmedabad"),
    ("Mumbai", "Kota"),
    ("Chennai", "Kolkata"),
    ("Kolkata", "Lucknow"),
    ("Kota", "Jaipur"),
    ("Jaipur", "Ahmedabad"),
)

TRAIN_KINDS = ("Express", "Superfast", "Mail", "Festival Special")
BUS_OPERATORS = ("Safar Lines", "Rajmarg Travels", "Sunrise Coaches", "Blue Horizon", "Nomad Express")
FIRST_NAMES = (
    "Aarav", "Ananya", "Arjun", "Diya", "Ishaan", "Kavya", "Rohan", "Meera", "Vihaan", "Saanvi",
    "Aditya", "Priya", "Karthik", "Neha", "Rahul", "Sneha", "Siddharth", "Pooja", "Varun", "Riya",
    "Manish", "Tanvi", "Harsh", "Nisha", "Yash", "Aisha", "Dev", "Lakshmi", "Nikhil", "Zoya",
    "Ravi", "Shreya", "Amit", "Divya", "Kunal", "Isha", "Tarun", "Mansi", "Gaurav", "Pallavi",
)

# The scripted demo (see seed.py): Bengaluru -> Hyderabad on this date.
DEMO_DATE = dt.date(2026, 11, 27)
DEFAULT_START_DATE = dt.date(2026, 11, 26)
DEFAULT_DAYS = 6
