"""
Parser územní struktury ČR z XLSX ČSÚ (soubor 0043).

Autoritativní hierarchie obec → POÚ → ORP → okres → kraj. Jeden list
na rok (1.1.2013 až 1.1.2024), dvouřádková hlavička, indexy sloupců
napevno.
"""

from pathlib import Path

import openpyxl

from normalize import KRAJ_UK_NUTS, clean_str, norm

# Cesty k datům jsou relativní ke korenu repozitáře, ne k aktuálnímu adresáři,
# aby skript šel spustit odkudkoli.
ROOT = Path(__file__).resolve().parent.parent
XLSX_PATH = ROOT / "data" / "0043_Struktura uzemi CR 1.1.2013 - 1.1.2024.xlsx"

# Referenční rok pro hlavní analýzu (nejnovější dostupný list).
LIST_AKTUALNI = "1.1.2024"
LIST_HISTORICKY = "1.1.2013"

# Status obce — legenda je uvedena v listu "Komentář" zdrojového XLSX.
# Ověřeno proti datům: v souboru se vyskytuje všech šest hodnot
# (O 5413, M 583, T 231, S 26, U 4, H 1).
STATUS_POPIS = {
    "H": "hlavní město",
    "M": "město",
    "O": "obec",
    "S": "statutární město",
    "T": "městys",
    "U": "vojenský újezd",
}


def _radky_listu(wb, nazev_listu):
    """Vrátí datové řádky listu jako seznam tuple; přeskočí dvouřádkovou hlavičku."""
    ws = wb[nazev_listu]
    vysledek = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i < 2:            # dva řádky slučované hlavičky
            continue
        if not row or not row[0]:   # patička nebo prázdný řádek
            continue
        vysledek.append(row)
    return vysledek


def nacti_obce(kraj_nuts=KRAJ_UK_NUTS, nazev_listu=LIST_AKTUALNI):
    """
    Načte obce ze zadaného listu, volitelně omezené na jeden kraj.

    Vrací seznam dictů s plnou hierarchií. `kraj_nuts=None` znamená celou ČR
    (potřeba pro kontrolní součty a pro mapování okresů celé republiky).
    """
    wb = openpyxl.load_workbook(XLSX_PATH, read_only=True, data_only=True)
    try:
        obce = []
        for row in _radky_listu(wb, nazev_listu):
            kraj_kod = clean_str(row[9])
            if kraj_nuts is not None and kraj_kod != kraj_nuts:
                continue
            status = clean_str(row[2])
            obce.append({
                "_id": clean_str(row[0]),              # kód obce ČSÚ = přirozený klíč
                "nazev": clean_str(row[1]),
                "nazev_norm": norm(row[1]),            # předpočítáno pro spojování
                "status": status,
                "status_popis": STATUS_POPIS.get(status, status),
                "pou": {"kod": clean_str(row[3]), "nazev": clean_str(row[4])},
                "orp": {"kod": clean_str(row[5]), "nazev": clean_str(row[6])},
                "okres": {"kod": clean_str(row[7]), "nazev": clean_str(row[8])},
                "kraj": {"kod": kraj_kod, "nazev": clean_str(row[10])},
                "nuts2": {"kod": clean_str(row[11]), "nazev": clean_str(row[12])},
                "rok_listu": nazev_listu,
            })
        return obce
    finally:
        wb.close()


def mapa_okresu(nazev_listu=LIST_AKTUALNI):
    """
    Postaví převodník normalizovaný název okresu -> {kod, nazev} pro celou ČR.

    Tohle je most ke Geonames: admin2Codes.txt zná jen názvy okresů
    ("Okres Teplice") a NEMÁ NUTS kód, takže se okres dohledává právě takhle.
    Musí být za celou ČR, ne jen za Ústecký kraj, aby šla ověřit úplnost
    napojení (75 ze 77, viz normalize.OKRES_ALIAS).
    """
    from normalize import norm_okres

    mapa = {}
    for obec in nacti_obce(kraj_nuts=None, nazev_listu=nazev_listu):
        okres = obec["okres"]
        if okres["kod"]:
            mapa[norm_okres(okres["nazev"])] = dict(okres)
    return mapa


def zmeny_prislusnosti(rok_od=LIST_HISTORICKY, rok_do=LIST_AKTUALNI):
    """
    Najde obce, které mezi dvěma roky změnily ORP nebo okres, a obce
    zaniklé či nově vzniklé.

    Vlastní přidané zpracování nad rámec povinných úloh: XLSX obsahuje
    12 ročních řezů, takže územní změny jsou v datech zdarma. Porovnává se
    podle kódu obce (stabilní identifikátor), ne podle názvu.
    """
    stary = {o["_id"]: o for o in nacti_obce(kraj_nuts=None, nazev_listu=rok_od)}
    novy = {o["_id"]: o for o in nacti_obce(kraj_nuts=None, nazev_listu=rok_do)}

    zmeny = []
    for kod in sorted(set(stary) & set(novy)):
        a, b = stary[kod], novy[kod]
        rozdily = {}
        for uroven in ("orp", "okres", "kraj"):
            if a[uroven]["kod"] != b[uroven]["kod"]:
                rozdily[uroven] = {
                    "z": {"kod": a[uroven]["kod"], "nazev": a[uroven]["nazev"]},
                    "na": {"kod": b[uroven]["kod"], "nazev": b[uroven]["nazev"]},
                }
        if rozdily:
            zmeny.append({"obec_kod": kod, "obec_nazev": b["nazev"], "zmeny": rozdily})

    return {
        "rok_od": rok_od,
        "rok_do": rok_do,
        "pocet_obci_od": len(stary),
        "pocet_obci_do": len(novy),
        "zaniklé": sorted(
            {"kod": k, "nazev": stary[k]["nazev"]} for k in set(stary) - set(novy)
        ) if set(stary) - set(novy) else [],
        "nove": [{"kod": k, "nazev": novy[k]["nazev"]} for k in sorted(set(novy) - set(stary))],
        "presunute": zmeny,
    }


if __name__ == "__main__":
    obce_uk = nacti_obce()
    print(f"obcí v Ústeckém kraji ({LIST_AKTUALNI}): {len(obce_uk)}")
    print("ukázka:", obce_uk[0])

    okresy = {o["okres"]["kod"] for o in obce_uk}
    orp = {o["orp"]["kod"] for o in obce_uk}
    print(f"okresů: {len(okresy)}, ORP: {len(orp)}")

    mapa = mapa_okresu()
    print(f"okresů v ČR celkem: {len(mapa)}")

    zm = zmeny_prislusnosti()
    print(f"\nzměny {zm['rok_od']} -> {zm['rok_do']}: "
          f"obcí {zm['pocet_obci_od']} -> {zm['pocet_obci_do']}, "
          f"přesunutých {len(zm['presunute'])}, "
          f"nových {len(zm['nove'])}, zaniklých {len(zm['zaniklé'])}")
    for z in zm["presunute"][:5]:
        print("  ", z)
