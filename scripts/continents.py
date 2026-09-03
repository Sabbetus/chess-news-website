"""ISO country-code -> continent mapping and continent page slugs, kept in
sync with chesstournamentcalendar.com's own src/lib/continents.ts /
locationSlug.ts (CONTINENT_MAP / CONTINENT_SLUGS) so our aggregate articles
group tournaments identically to how the calendar site groups them, and so
sourceUrl links to a real /continent/<slug>/ page there. If that mapping
changes upstream, update this to match.
"""

CONTINENT_NAMES = {
    "EU": "Europe",
    "AS": "Asia",
    "NA": "North America",
    "SA": "South America",
    "AF": "Africa",
    "OC": "Oceania",
}

CONTINENT_SLUGS = {
    "EU": "europe",
    "AS": "asia",
    "NA": "north-america",
    "SA": "south-america",
    "AF": "africa",
    "OC": "oceania",
}

CONTINENT_CODES = list(CONTINENT_NAMES.keys())

_MAP = {
    "FI": "EU", "SE": "EU", "NO": "EU", "DK": "EU", "IS": "EU", "GB": "EU", "IE": "EU",
    "FR": "EU", "ES": "EU", "PT": "EU", "DE": "EU", "AT": "EU", "CH": "EU", "NL": "EU",
    "BE": "EU", "LU": "EU", "IT": "EU", "GR": "EU", "CY": "EU", "MT": "EU", "PL": "EU",
    "CZ": "EU", "SK": "EU", "HU": "EU", "RO": "EU", "BG": "EU", "RS": "EU", "HR": "EU",
    "SI": "EU", "BA": "EU", "ME": "EU", "MK": "EU", "AL": "EU", "XK": "EU", "LT": "EU",
    "LV": "EU", "EE": "EU", "BY": "EU", "UA": "EU", "MD": "EU", "RU": "EU", "AD": "EU",
    "FO": "EU", "GG": "EU",
    "GE": "AS", "AM": "AS", "AZ": "AS", "TR": "AS", "IN": "AS", "CN": "AS", "JP": "AS",
    "KR": "AS", "TH": "AS", "VN": "AS", "PH": "AS", "ID": "AS", "MY": "AS", "SG": "AS",
    "PK": "AS", "BD": "AS", "LK": "AS", "NP": "AS", "MN": "AS", "UZ": "AS", "KZ": "AS",
    "KG": "AS", "TM": "AS", "AE": "AS", "QA": "AS", "KW": "AS", "SA": "AS", "IR": "AS",
    "IQ": "AS", "JO": "AS", "LB": "AS", "SY": "AS", "IL": "AS", "HK": "AS", "BH": "AS",
    "PS": "AS", "TW": "AS",
    "US": "NA", "CA": "NA", "MX": "NA", "GT": "NA", "CR": "NA", "CU": "NA", "DO": "NA",
    "PA": "NA", "PR": "NA", "AW": "NA", "HN": "NA", "NI": "NA",
    "BR": "SA", "AR": "SA", "CL": "SA", "CO": "SA", "PE": "SA", "VE": "SA", "UY": "SA",
    "EC": "SA", "PY": "SA",
    "AU": "OC", "NZ": "OC",
    "ZA": "AF", "EG": "AF", "MA": "AF", "TN": "AF", "DZ": "AF", "KE": "AF", "BW": "AF",
    "ZM": "AF", "CI": "AF", "CV": "AF", "ET": "AF", "MU": "AF", "NG": "AF", "UG": "AF",
}


def continent_code_for(country_code: str | None) -> str:
    return _MAP.get((country_code or "").upper(), "XX")


def continent_name_for(country_code: str | None) -> str:
    return CONTINENT_NAMES.get(continent_code_for(country_code), "Other")


def continent_url(code: str) -> str:
    slug = CONTINENT_SLUGS.get(code)
    return f"https://chesstournamentcalendar.com/continent/{slug}/" if slug else "https://chesstournamentcalendar.com/"
