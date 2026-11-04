"""Constants that define the bootstrap event repertoire.

Every value here is a decision that shows up in the report. Nothing is tuned to
make a result come out a particular way; where a choice is arguable it is
commented with why, so the report can defend it.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = REPO_ROOT / "data" / "raw"  # gitignored cache
DATA_OUT = REPO_ROOT / "data" / "out"  # versioned outputs
DATA_INTERIM = REPO_ROOT / "data" / "interim"  # gitignored caches
DATA_REVIEW = REPO_ROOT / "data" / "review"  # versioned hand decisions
MANIFEST_PATH = DATA_OUT / "manifest.json"

# ---------------------------------------------------------------- window ----

WINDOW_FROM = date(2018, 1, 1)
WINDOW_TO = date(2024, 12, 31)

# ------------------------------------------------------------ exclusions ----

# Swissvotes policy-domain prefix for media policy. Any ballot object carrying
# it is dropped: the outlets are a party to the object, so their self-interest
# is confounded with their position. Found mechanically rather than by naming
# objects -- it catches the media package (654), Lex Netflix (655) and the
# No-Billag initiative (617) alike.
EXCLUDED_DOMAIN_PREFIX = "12.5"

# ----------------------------------------------------------- party codes ----

# Swissvotes encodes a voting recommendation as an integer; these are the only
# two that state a side. 5 = Stimmfreigabe, 9999 = the organisation did not
# exist, "." and "" = unknown.
RECO_YES, RECO_NO = 1.0, 2.0

# The six parties represented in the Federal Council / large enough to move the
# electorate over the whole window. `CENTRE` is synthetic: see MERGER_DATE.
MAIN_PARTIES = ("p-svp", "p-sps", "p-fdp", "CENTRE", "p-gps", "p-glp")

# CVP + BDP merged into Die Mitte / Le Centre on this date. Swissvotes marks
# p-mitte as 9999 before it and p-cvp/p-bdp as 9999 after. A fixed party list
# would silently drop a governing party from half the panel, so the centre
# column follows the institution across its rename instead.
MERGER_DATE = date(2021, 1, 1)

# ------------------------------------------------------- language regions ----

# There is no canton-level language or region attribute anywhere in Swissvotes
# or its codebook -- this mapping is ours, and it is visible in every
# Roestigraben value we publish.
#
# Only unambiguous cantons take part. BE, FR and VS are officially bilingual,
# TI is Italian-speaking and GR is trilingual; assigning any of them to a side
# would put our thumb on the axis. Excluding them costs statistical power and
# buys a number we can defend.
CANTONS_FR = ("vd", "ge", "ne", "ju")
CANTONS_DE = (
    "zh", "lu", "ur", "sz", "ow", "nw", "gl", "zg", "so",
    "bs", "bl", "sh", "ar", "ai", "sg", "ag", "tg",
)
CANTONS_EXCLUDED = ("be", "fr", "vs", "ti", "gr")

# ------------------------------------------------------------- selection ----

SEED = 20260914  # only breaks ties; the rule itself is deterministic
BLOCK_A_N_CELLS = 4  # polarization high/low x Roestigraben high/low
BLOCK_A_PER_CELL = 2

# Swissvotes policy-domain prefixes for the required migration / asylum / EU
# objects. Level-3 codes drop their second dot in the file: 10.3.1 -> "10.31".
MIGRATION_EU_PREFIXES = ("2.2", "10.31", "10.32")
BLOCK_A_MIN_MIGRATION_EU = 2

# ------------------------------------------------------- coverage window ----

# Days before / after an event date to pull coverage for. The fog
# Abstimmungsmonitor counts editorial items over the 12 weeks before a vote; we
# take a shorter pre-window and a short tail for reactions.
COVERAGE_DAYS_BEFORE = 30
COVERAGE_DAYS_AFTER = 14


# ------------------------------------------------ blocks B, C, E (Wikidata) ----

# Candidate events are ranked by sitelinks -- the number of Wikipedia language
# editions carrying an article. This is the notability proxy, and it is chosen
# precisely because it is NOT a media measure: ranking events by Swiss press
# coverage would select on the very quantity the project sets out to measure.
POOL_MIN_SITELINKS_CH = 3
POOL_MIN_SITELINKS_INTL = 45

# Type roots whose subclasses are dropped from both pools. The concrete type
# set is derived from Wikidata's own class hierarchy at run time (P279*), not
# written out here, so the rule survives a class we did not anticipate.
TYPE_ROOTS_SPORT_ENTERTAINMENT = (
    "Q16510064",   # sporting event
    "Q13406554",   # sports competition
    "Q27020041",   # sports season
    "Q26213387",   # Olympic delegation
    "Q4504495",    # award ceremony
    "Q15416",      # television program
)

# Dropped from the SWISS pool only: votes and elections are already blocks A
# and B, and would otherwise be selected twice.
TYPE_ROOTS_VOTES_ELECTIONS = (
    "Q40231",      # public election
    "Q43109",      # referendum
    "Q15078695",   # Swiss federal popular initiative
    "Q4393809",    # Swiss referendum
    "Q431226",     # popular referendum
    "Q335918",     # popular initiative
    "Q1006573",    # Swiss Federal Council election
    "Q22160401",   # Swiss federal election
    "Q2618461",    # legislative election
)

# Block B: the Federal Council election. Small, fully known actor set -- the
# easy reference case for the entity linker.
TYPE_FEDERAL_COUNCIL_ELECTION = "Q1006573"

# Block C is "Swiss events not carried by the institutional calendar", not
# strictly "unplanned": the pool is too thin for the stricter reading, and the
# women's strike is planned yet non-institutional. The relaxation is declared
# here and in the dataset rather than being quietly assumed.
BLOCK_C_N = 3
BLOCK_C_LABEL = "non-institutional Swiss event"

# Block E is diagnostic only and NEVER enters the calibration set. Its job is
# identical actors on both sides of the Roestigraben, hence a test of the
# language confounder with no difference in coverage support.
BLOCK_E_N = 4
