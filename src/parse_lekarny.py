"""
Parser lékáren z registru NRPZS (lekarny_uk.csv).

Lékárny jsou vlastní předmět analýzy — 167 míst poskytování lékárenské péče
v Ústeckém kraji. Soubor je proti ostatním zdrojům čistý: OkresCode je
vyplněný u všech řádků a MistoPoskytovaniId je bez duplicit, takže napojení
na okres je bezproblémové.

Nekonzistence, které parser řeší:

1) 3 lékárny nemají souřadnice (Lat/Lng prázdné). Dogeokódují se na střed
   obce z Geonames a dostanou příznak geo_zdroj="obec", aby bylo v datech
   poznat, že poloha je přibližná. Zamlčet to nelze — ovlivňuje to výpočty
   vzdáleností.

2) U 3 lékáren je DruhZarizeni slepenec víc druhů (poliklinika, která má
   i lékárnu). Parsuje se na seznam, aby šel dotaz "Lékárna in druhy".

3) Sloupce s příponou Sidlo jsou adresa SÍDLA FIRMY, ne lékárny. Dr. Max
   má sídlo v Brně, takže geokódování podle nich by umístilo desítky
   lékáren do Brna. Do výstupu jdou zvlášť a nikdy se nepoužijí jako poloha.

Nepoužitelné sloupce: SpravniObvod je prázdný u všech řádků,
PoskytovatelFax téměř všude, OdbornyZastupce je slepenec až 17 jmen.
"""

import csv
from pathlib import Path

from normalize import clean_str, norm, split_list, to_float

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "lekarny_uk.csv"

# Druh zařízení, který dělá z místa lékárnu. U polikliniek je jednou
# z několika hodnot ve slepeném sloupci.
DRUH_LEKARNA = "Lékárna"


def nacti_lekarny():
    """
    Načte lékárny z CSV do normalizovaných dictů.

    Souřadnice zůstávají None, když v CSV chybí — dogeokódování řeší až
    build.py, protože potřebuje Geonames. Tady se schválně nic nedomýšlí.
    """
    lekarny = []
    with open(CSV_PATH, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            lat, lng = to_float(r.get("Lat")), to_float(r.get("Lng"))
            druhy = split_list(r.get("DruhZarizeni"))
            lekarny.append({
                "_id": clean_str(r.get("MistoPoskytovaniId")),
                "zarizeni_id": clean_str(r.get("ZdravotnickeZarizeniId")),
                "kod": clean_str(r.get("Kod")),
                "nazev": clean_str(r.get("NazevZarizeni")),
                "druhy_zarizeni": druhy,
                "je_lekarna": DRUH_LEKARNA in druhy,

                # Adresa lékárny (nikoli sídla poskytovatele).
                "adresa": {
                    "obec": clean_str(r.get("Obec")),
                    "obec_norm": norm(r.get("Obec")),
                    "psc": clean_str(r.get("Psc")),
                    "ulice": clean_str(r.get("Ulice")),
                    "cislo": clean_str(r.get("CisloDomovniOrientacni")),
                },

                # Územní příslušnost přímo z registru — kódy jsou NUTS/LAU,
                # tedy stejný systém jako v XLSX ČSÚ. ORP registr neuvádí,
                # doplní se v build.py z hierarchie ČSÚ.
                "uzemi": {
                    "kraj_kod": clean_str(r.get("KrajCode")),
                    "kraj_nazev": clean_str(r.get("Kraj")),
                    "okres_kod": clean_str(r.get("OkresCode")),
                    "okres_nazev": clean_str(r.get("Okres")),
                },

                # Poloha; geo_zdroj říká, odkud pochází.
                "lat": lat,
                "lng": lng,
                "geo_zdroj": "registr" if lat is not None and lng is not None else None,

                "poskytovatel": {
                    "ico": clean_str(r.get("Ico")),
                    "web": clean_str(r.get("PoskytovatelWeb")),
                    "email": clean_str(r.get("PoskytovatelEmail")),
                    "telefon": clean_str(r.get("PoskytovatelTelefon")),
                    "pravni_forma_kod": clean_str(r.get("PravniFormaKod")),
                    # Sídlo firmy - NIKDY nepoužívat jako polohu lékárny.
                    "sidlo_obec": clean_str(r.get("ObecSidlo")),
                    "sidlo_okres_kod": clean_str(r.get("OkresCodeSidlo")),
                },
                "obor_pece": clean_str(r.get("OborPece")),
            })
    return lekarny


# Řetězce lékáren podle názvu zařízení. Rozpoznání sítí je potřeba pro
# vlastní analýzu (koncentrace trhu), název v registru není normalizovaný.
RETEZCE = {
    "dr. max": "Dr. Max",
    "benu": "BENU",
    "pilulka": "Pilulka",
    "devetsil": "Devětsil",
    "moje lekarna": "Moje lékárna",
}


def urci_retezec(nazev):
    """
    Zařadí lékárnu k řetězci podle názvu, jinak vrátí "nezávislá".

    Hledá se v normalizovaném názvu (bez diakritiky), protože registr píše
    názvy nejednotně — "Dr.Max", "Dr. Max Lékárna", velká i malá písmena.
    """
    n = norm(nazev)
    for klic, jmeno in RETEZCE.items():
        if klic in n:
            return jmeno
    return "nezávislá"


if __name__ == "__main__":
    import collections

    lekarny = nacti_lekarny()
    print(f"lékáren v CSV: {len(lekarny)}")
    print(f"unikátních _id: {len({l['_id'] for l in lekarny})}")
    print(f"označených jako Lékárna: {sum(1 for l in lekarny if l['je_lekarna'])}")

    bez_geo = [l for l in lekarny if l["lat"] is None]
    print(f"\nbez souřadnic: {len(bez_geo)}")
    for l in bez_geo:
        print(f"   {l['_id']}  {l['adresa']['obec']:<16} "
              f"{l['uzemi']['okres_nazev']:<16} {l['nazev'][:40]}")

    slepence = [l for l in lekarny if len(l["druhy_zarizeni"]) > 1]
    print(f"\nse slepeným DruhZarizeni: {len(slepence)}")
    for l in slepence:
        print(f"   {l['_id']}  {len(l['druhy_zarizeni'])} druhů: {l['druhy_zarizeni']}")

    print("\npodle okresů:")
    for (kod, nazev), n in sorted(collections.Counter(
            (l["uzemi"]["okres_kod"], l["uzemi"]["okres_nazev"]) for l in lekarny).items()):
        print(f"   {kod}  {nazev:<16} {n:>3}")

    print("\npodle řetězců:")
    for jmeno, n in collections.Counter(
            urci_retezec(l["nazev"]) for l in lekarny).most_common():
        print(f"   {jmeno:<16} {n:>3}")

    print(f"\nobcí s alespoň jednou lékárnou: "
          f"{len({l['adresa']['obec_norm'] for l in lekarny})}")
    print("\nukázka jedné lékárny:")
    for k, v in lekarny[0].items():
        print(f"   {k:<16} {v}")
