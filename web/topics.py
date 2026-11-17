"""The broad topics shared by the studies index and Said & Checked.

Studies questions are grouped by keyword on their category (STUDY_KEYWORDS, first match wins).
Said & Checked statements carry a broad_topic chosen by the daily run from SAID_TOPICS; the
build rejects any other value."""
import re

OTHER_TOPIC = "Other"

# Said & Checked topics, in display order. A statement goes under its main subject.
SAID_TOPICS = (
    "Elections and Parties",
    "Congress and Government Spending",
    "Courts and Nominations",
    "War and Foreign Affairs",
    "Defense and National Security",
    "Immigration",
    "Civil Rights and Social Issues",
    "Crime and Policing",
    "AI and Technology",
    "Energy",
    "Environment and Climate",
    "Economy and Jobs",
    "Trade and Tariffs",
    "Agriculture",
    "Health",
    "Education",
    "Housing and Communities",
    "Transportation and Infrastructure",
    "Banking and Finance",
    "Disasters, Insurance and Risk",
    "Veterans",
)

# Studies only: a kind of question, not a subject.
TESTING_CLAIMS = "Testing Claims and Debates"

# Order matters: a category takes the first group with a matching keyword, so the narrower
# groups come before the broad ones they overlap ("corporate governance" is Banking and Finance,
# not Congress; "trade" is Trade and Tariffs, not Economy).
STUDY_KEYWORDS = [
    (TESTING_CLAIMS, ("article validation", "question bias", "causal chain", "policy debates",
                      "correlation")),
    ("Veterans", ("veteran",)),
    ("Disasters, Insurance and Risk", ("insurance", "catastrophe", "disaster", "underwriting",
                                       "business interruption", "cargo risk", "liability risk",
                                       "workers compensation", "emergency management",
                                       "site resilience")),
    ("Agriculture", ("agricultur", "crop", "commodity")),
    ("Energy", ("energy", "resource security")),
    ("Environment and Climate", ("environment", "climate")),
    ("Health", ("health", "pharma")),
    ("Education", ("education",)),
    ("Banking and Finance", ("bank", "credit risk", "consumer finance", "financial", "lending",
                             "rates signal", "corporate governance", "market structure")),
    ("Elections and Parties", ("election", "campaign finance", "money in politics", "political")),
    ("Courts and Nominations", ("court", "judicial", "nomination")),
    ("Congress and Government Spending", ("congressional", "governance", "fiscal",
                                          "public finance", "government spending", "regulat",
                                          "policy analysis")),
    ("War and Foreign Affairs", ("war", "foreign", "geopolit")),
    ("Defense and National Security", ("defense", "national security")),
    ("Immigration", ("immigration",)),
    ("Civil Rights and Social Issues", ("civil rights", "social issues", "voting rights")),
    ("Crime and Policing", ("criminal", "criminology", "police")),
    ("AI and Technology", ("artificial intelligence", "technology", "cyber", "semiconductor",
                           "innovation", "science")),
    ("Transportation and Infrastructure", ("infrastructure", "aviation", "transport",
                                           "logistics")),
    ("Housing and Communities", ("housing", "demographics", "social mobility", "social safety")),
    ("Trade and Tariffs", ("trade", "tariff")),
    ("Economy and Jobs", ("economic", "labor", "manufacturing", "industrial", "macro",
                          "market sizing", "retail", "workforce", "workplace")),
]

assert all(name in SAID_TOPICS or name == TESTING_CLAIMS for name, _ in STUDY_KEYWORDS)


def study_topic(category):
    """The group a studies question is listed under, or None when no keyword matches."""
    # Keywords match at the start of a word, so "war" never matches "software" or "award".
    name = category.replace("_", " ").replace("-", " ")
    for topic, words in STUDY_KEYWORDS:
        if any(re.search(r"\b" + re.escape(w), name) for w in words):
            return topic
    return None


def slug(topic):
    """'Disasters, Insurance and Risk' -> 'disasters-insurance-and-risk'."""
    out = "".join(c.lower() if c.isalnum() else "-" for c in topic)
    return "-".join(p for p in out.split("-") if p)
