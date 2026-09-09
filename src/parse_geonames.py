"""
Parser Geonames pro ČR: CZ.txt (objekty) + admin2Codes.txt (okresy).

Zdroj geometrie — souřadnice středů obcí a populace. Obsahuje ale i části
obcí a osady, takže seznam obcí musí pocházet z ČSÚ.
"""

from collections import defaultdict
from pathlib import Path

from normalize import (FIPS_TO_NUTS3, KRAJ_UK_FIPS, clean_str, norm,
                       norm_okres, to_float, to_int)

ROOT = Path(__file__).resolve().parent.parent
CZ_TXT = ROOT / "data" / "CZ" / "CZ.txt"
ADMIN2 = ROOT / "data" / "admin2Codes.txt"

TRIDA_SIDLA = "P"

KODY_NEEXISTUJICICH = {"PPLW", "PPLQ", "PPLH"}


def nacti_okresy_geonames():
    """
    Načte české okresy z admin2Codes.txt.

    Vrací dict: admin2 kód ("0426") -> {geonames_nazev, geonameid, klic}.
    Filtruje jen řádky začínající "CZ." — soubor je celosvětový (2,4 MB).
    """
    okresy = {}
    with open(ADMIN2, encoding="utf-8") as f:
        for line in f:
            casti = line.rstrip("\n").split("\t")
            if len(casti) < 4 or not casti[0].startswith("CZ."):
                continue
            klic = casti[0]                       # "CZ.89.0426"
            _, fips, admin2 = klic.split(".", 2)
            okresy[admin2] = {
                "klic": klic,
                "admin2": admin2,
                "fips_kraje": fips,
                "geonames_nazev": clean_str(casti[1]),      # "Okres Teplice"
                "nazev_norm": norm_okres(casti[1]),         # "teplice"
                "geonameid": to_int(casti[3]),
            }
    return okresy


def napoj_okresy_na_nuts(mapa_okresu_csu):
    """
    Spojí okresy Geonames s NUTS kódy ČSÚ podle normalizovaného názvu.

    Vrací (napojeno, nenapojeno):
      napojeno   — admin2 kód -> záznam okresu doplněný o okres_kod (NUTS)
      nenapojeno — seznam okresů Geonames bez protějšku v ČSÚ

    Očekávaný výsledek: 75 ze 77 okresů ČSÚ se napojí; nenapojené jsou
    pražské městské části, které normalize.norm_okres sjednotí na "praha",
    takže se napojí na okres CZ0100 hromadně.
    """
    geo = nacti_okresy_geonames()
    napojeno, nenapojeno = {}, []
    for admin2, zaznam in geo.items():
        csu = mapa_okresu_csu.get(zaznam["nazev_norm"])
        if csu is None:
            nenapojeno.append(zaznam)
            continue
        napojeno[admin2] = {**zaznam, "okres_kod": csu["kod"], "okres_nazev": csu["nazev"]}
    return napojeno, nenapojeno


def nacti_sidla(fips_kraje=KRAJ_UK_FIPS):
    """
    Načte sídla (feature_class 'P') ze CZ.txt, volitelně jen pro jeden kraj.

    `fips_kraje=None` znamená celou ČR. Streamuje po řádcích — soubor má
    43 264 záznamů a načítat ho celý do paměti není potřeba.
    """
    sidla = []
    with open(CZ_TXT, encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) < 19 or p[6] != TRIDA_SIDLA:
                continue
            admin1 = clean_str(p[10])
            if fips_kraje is not None and admin1 != fips_kraje:
                continue
            lat, lng = to_float(p[4]), to_float(p[5])
            if lat is None or lng is None:
                continue
            sidla.append({
                "geonameid": to_int(p[0]),
                "nazev": clean_str(p[1]),
                "nazev_norm": norm(p[1]),
                "nazev_ascii": clean_str(p[2]),
                "lat": lat,
                "lng": lng,
                "feature_code": clean_str(p[7]),
                "fips_kraje": admin1,
                "kraj_kod": FIPS_TO_NUTS3.get(admin1),   # FIPS -> NUTS 3
                "admin2": clean_str(p[11]),
                "obec_kod_geonames": clean_str(p[12]),   # admin3, nespolehlivý
                "populace": to_int(p[14]) or 0,
                "vyska": to_int(p[16]),
            })
    return sidla


def index_sidel(sidla, okresy_napojene):
    """
    Postaví vyhledávací index pro dohledání středu obce.

    Klíč je (normalizovaný název, NUTS kód okresu) — název sám nestačí,
    protože se opakuje. Ke každému klíči patří SEZNAM kandidátů; výběr
    z nich řeší vyber_stred().
    """
    idx = defaultdict(list)
    for s in sidla:
        info = okresy_napojene.get(s["admin2"])
        if info is None:
            continue
        s = {**s, "okres_kod": info["okres_kod"], "okres_nazev": info["okres_nazev"]}
        idx[(s["nazev_norm"], s["okres_kod"])].append(s)
    return idx


def vyber_stred(kandidati):
    """
    Vybere jedno sídlo jako střed obce, když je kandidátů víc.

    Pravidla v tomto pořadí:
      1. vyřaď zaniklá / opuštěná / historická sídla (PPLW, PPLQ, PPLH)
      2. preferuj vyšší populaci — obec bývá zanesena s počtem obyvatel,
         zatímco její část nulou
      3. preferuj obecnější feature_code (PPL* před PPLX = část sídla)
      4. při plné remíze vezmi nejnižší geonameid (determinismus, aby
         opakované načtení dalo vždy stejný výsledek)

    Konkrétní případ z dat — dva "Bečovy" v Ústeckém kraji:
      3079610  Bečov  okres CZ0422  populace 0
      3079611  Bečov  okres CZ0425  populace 2072
    Klíč obsahuje okres, takže se rozliší už v indexu; kdyby ne, rozhodne
    populace.
    """
    if not kandidati:
        return None
    zive = [k for k in kandidati if k["feature_code"] not in KODY_NEEXISTUJICICH]
    vyber = zive or kandidati          # když jsou všechna zaniklá, ber je
    return sorted(
        vyber,
        key=lambda s: (-s["populace"], s["feature_code"] == "PPLX", s["geonameid"]),
    )[0]


if __name__ == "__main__":
    from parse_uzemi import mapa_okresu

    mapa = mapa_okresu()
    napojeno, nenapojeno = napoj_okresy_na_nuts(mapa)
    print(f"okresů Geonames: {len(napojeno) + len(nenapojeno)}, "
          f"napojeno na NUTS: {len(napojeno)}, nenapojeno: {len(nenapojeno)}")
    for z in nenapojeno:
        print("   NENAPOJENO:", z["klic"], z["geonames_nazev"])

    sidla = nacti_sidla()
    print(f"\nsídel (P) v Ústeckém kraji: {len(sidla)}")
    print(f"z toho s populací > 0: {sum(1 for s in sidla if s['populace'] > 0)}")

    idx = index_sidel(sidla, napojeno)
    print(f"unikátních klíčů (název, okres): {len(idx)}")
    viceznacne = {k: v for k, v in idx.items() if len(v) > 1}
    print(f"klíčů s víc kandidáty: {len(viceznacne)}")
    for k, v in list(viceznacne.items())[:3]:
        print(f"   {k} -> " + ", ".join(
            f"{s['geonameid']}/{s['feature_code']}/pop={s['populace']}" for s in v))
        print(f"      vybrán: {vyber_stred(v)['geonameid']}")
