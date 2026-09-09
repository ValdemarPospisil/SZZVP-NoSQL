"""
Normalizace identifikátorů a názvů — jádro řešení nekonzistencí mezi zdroji.

Tři zdroje dat používají tři různé identifikační systémy a jediné, co je
spolehlivě spojuje, je NÁZEV. Proto tu je normalizace názvů a překladové
tabulky mezi kódovými systémy.

Přehled systémů:
  - ČSÚ / NRPZS (XLSX, lekarny_uk.csv) — NUTS/LAU kódy: kraj CZ042,
    okres CZ0426, obec 567043 (šestimístný kód obce)
  - Geonames (CZ.txt)                  — admin1 = FIPS kód kraje ("89"),
    admin2 = čtyřznakový kód okresu ("0426"), vlastní geonameid
  - admin2Codes.txt                    — klíč "CZ.89.0426" + název
    "Okres Teplice", BEZ jakéhokoli NUTS kódu
"""

import unicodedata

# ---------------------------------------------------------------------------
# Normalizace názvů
# ---------------------------------------------------------------------------

def norm(s) -> str:
    """
    Převede název na kanonickou podobu pro porovnávání mezi zdroji.

    Odstraní diakritiku, sjednotí velikost písmen a zredukuje vnitřní mezery.
    Bez tohohle by se "Ústí nad Labem" a "Usti nad Labem" (ASCII varianta
    z geonames) nikdy nespojily.

    >>> norm("Ústí nad  Labem")
    'usti nad labem'
    >>> norm("Brno-město")
    'brno-mesto'
    """
    if s is None:
        return ""
    # NFKD rozloží 'ú' na 'u' + kombinující čárku, encode ASCII čárku zahodí.
    s = unicodedata.normalize("NFKD", str(s))
    s = s.encode("ascii", "ignore").decode("ascii")
    return " ".join(s.lower().split())


# ---------------------------------------------------------------------------
# Kraje: FIPS (geonames admin1) -> NUTS 3
# ---------------------------------------------------------------------------
# Geonames uvádí u českých záznamů FIPS kód kraje, ne NUTS. Bez téhle tabulky
# nelze geonames sídlo přiřadit ke kraji z XLSX.
FIPS_TO_NUTS3 = {
    "52": "CZ010",  # Praha (v geonames vedena jako samostatný admin1)
    "78": "CZ064",  # Jihomoravský
    "79": "CZ031",  # Jihočeský
    "80": "CZ063",  # Vysočina
    "81": "CZ041",  # Karlovarský
    "82": "CZ052",  # Královéhradecký
    "83": "CZ051",  # Liberecký
    "84": "CZ071",  # Olomoucký
    "85": "CZ080",  # Moravskoslezský
    "86": "CZ053",  # Pardubický
    "87": "CZ032",  # Plzeňský
    "88": "CZ020",  # Středočeský
    "89": "CZ042",  # Ústecký
    "90": "CZ072",  # Zlínský
}

# Ústecký kraj — předmět úlohy.
KRAJ_UK_NUTS = "CZ042"
KRAJ_UK_FIPS = "89"


# ---------------------------------------------------------------------------
# Okresy: aliasy názvů mezi geonames a ČSÚ
# ---------------------------------------------------------------------------
# Spojení okresů podle názvu uspěje u 75 ze 77. Zbytek jsou tyto dvě anomálie
# (ověřeno porovnáním admin2Codes.txt s listem 1.1.2024):
#
#   1) geonames "Město Brno"  vs. ČSÚ "Brno-město"      -> alias
#   2) geonames dělí Prahu na 22 městských částí
#      ("Praha 1".."Praha 22"), ČSÚ má jeden okres CZ0100 -> agregace
#
# Ústeckého kraje se ani jedna netýká, ale skript má být obecný — a u obhajoby
# je právě tohle ta "nekonzistence identifikátorů" ze zadání.
OKRES_ALIAS = {
    "mesto brno": "brno-mesto",
}


def norm_okres(nazev: str) -> str:
    """
    Kanonický název okresu: zahodí prefix "Okres ", normalizuje a aplikuje alias.

    Všech 22 pražských městských částí sjednotí na "praha", protože ČSÚ zná
    jen jeden okres Praha (CZ0100).

    >>> norm_okres("Okres Teplice")
    'teplice'
    >>> norm_okres("Město Brno")
    'brno-mesto'
    >>> norm_okres("Praha 13")
    'praha'
    """
    s = str(nazev or "").strip()
    for prefix in ("Okres ", "okres "):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    key = norm(s)
    key = OKRES_ALIAS.get(key, key)
    # "praha 1".."praha 22" -> "praha"; pozor, nesmí to chytit "praha-vychod"
    # ani "praha-zapad", což jsou skutečné samostatné okresy CZ020B/CZ020C.
    parts = key.split()
    if len(parts) == 2 and parts[0] == "praha" and parts[1].isdigit():
        key = "praha"
    return key


# ---------------------------------------------------------------------------
# Drobné pomůcky pro čištění hodnot
# ---------------------------------------------------------------------------

def clean_str(v):
    """Prázdný string -> None, jinak osekaný text. Mongo tak nedostane "" místo null."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def to_float(v):
    """Bezpečná konverze na float; prázdno i nesmysl -> None (chybějící souřadnice)."""
    s = clean_str(v)
    if s is None:
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def to_int(v):
    """Bezpečná konverze na int; prázdno i nesmysl -> None."""
    s = clean_str(v)
    if s is None:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def split_list(v, sep=","):
    """
    Rozdělí slepený víceznačkový sloupec na seznam.

    Sloupec DruhZarizeni u 3 ze 167 lékáren obsahuje víc druhů zařízení
    (poliklinika, která má i lékárnu). Jako seznam se dá filtrovat
    dotazem "Lékárna in druhy" místo rovnosti.
    """
    s = clean_str(v)
    if s is None:
        return []
    return [p.strip() for p in s.split(sep) if p.strip()]
