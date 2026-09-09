"""
Kontrolní výpis stavu zdrojových dat — spusť a uvidíš, co skripty načetly.

Nezapisuje do databází, jen čte soubory z data/ a tiskne, co v nich je.
Účel: každé tvrzení o datech (počty, nekonzistence, napojení kódů) si má jít
ověřit jedním příkazem, ne věřit na slovo.

Spuštění z korene repozitáře:
    PYTHONPATH=src .venv/bin/python src/kontrola.py
"""

import collections

from parse_geonames import (index_sidel, nacti_okresy_geonames, nacti_sidla,
                            napoj_okresy_na_nuts, vyber_stred)
from parse_uzemi import LIST_AKTUALNI, mapa_okresu, nacti_obce, zmeny_prislusnosti


def hlavicka(text):
    print()
    print("=" * 78)
    print(f"  {text}")
    print("=" * 78)


def tabulka(radky, sloupce):
    """Vytiskne jednoduchou zarovnanou tabulku."""
    if not radky:
        print("  (žádná data)")
        return
    sirky = [max(len(str(r[i])) for r in [sloupce] + radky) for i in range(len(sloupce))]
    print("  " + " | ".join(str(sloupce[i]).ljust(sirky[i]) for i in range(len(sloupce))))
    print("  " + "-+-".join("-" * s for s in sirky))
    for r in radky:
        print("  " + " | ".join(str(r[i]).ljust(sirky[i]) for i in range(len(sloupce))))


# ---------------------------------------------------------------------------
hlavicka(f"1. ÚZEMNÍ STRUKTURA ČSÚ (list {LIST_AKTUALNI})")

obce_cr = nacti_obce(kraj_nuts=None)
obce_uk = nacti_obce()
print(f"  obcí v ČR:              {len(obce_cr)}")
print(f"  obcí v Ústeckém kraji:  {len(obce_uk)}")
print(f"  okresů v ČR:            {len({o['okres']['kod'] for o in obce_cr})}")
print(f"  ORP v ČR:               {len({o['orp']['kod'] for o in obce_cr})}")

print("\n  Okresy Ústeckého kraje:")
po_okresech = collections.Counter(
    (o["okres"]["kod"], o["okres"]["nazev"]) for o in obce_uk)
tabulka([[k[0], k[1], n] for k, n in sorted(po_okresech.items())],
        ["kód", "okres", "obcí"])
print(f"  součet: {sum(po_okresech.values())} (musí být {len(obce_uk)})")

print("\n  ORP Ústeckého kraje:")
po_orp = collections.Counter((o["orp"]["kod"], o["orp"]["nazev"]) for o in obce_uk)
tabulka([[k[0], k[1], n] for k, n in sorted(po_orp.items())], ["kód", "ORP", "obcí"])
print(f"  součet: {sum(po_orp.values())} (musí být {len(obce_uk)})")

print("\n  Ukázka jedné obce (celý dokument, jak půjde do Mongo):")
for k, v in obce_uk[0].items():
    print(f"     {k:<14} {v}")

# ---------------------------------------------------------------------------
hlavicka("2. ZMĚNY ÚZEMNÍ PŘÍSLUŠNOSTI 2013 -> 2024 (vlastní analýza)")

zm = zmeny_prislusnosti()
print(f"  obcí v ČR {zm['rok_od']}: {zm['pocet_obci_od']}")
print(f"  obcí v ČR {zm['rok_do']}: {zm['pocet_obci_do']}")
print(f"  nově vzniklých: {len(zm['nove'])}   zaniklých: {len(zm['zaniklé'])}"
      f"   přesunutých jinam: {len(zm['presunute'])}")

if zm["nove"]:
    print("\n  Nové obce:")
    tabulka([[o["kod"], o["nazev"]] for o in zm["nove"]], ["kód", "název"])
if zm["zaniklé"]:
    print("\n  Zaniklé obce:")
    tabulka([[o["kod"], o["nazev"]] for o in zm["zaniklé"]], ["kód", "název"])

print("\n  Všechny obce, které změnily ORP nebo okres:")
radky = []
for z in zm["presunute"]:
    for uroven, d in z["zmeny"].items():
        radky.append([z["obec_kod"], z["obec_nazev"], uroven,
                      f"{d['z']['nazev']} ({d['z']['kod']})",
                      f"{d['na']['nazev']} ({d['na']['kod']})"])
tabulka(radky, ["kód obce", "obec", "úroveň", "z", "na"])

# ---------------------------------------------------------------------------
hlavicka("3. NAPOJENÍ OKRESŮ: GEONAMES <-> ČSÚ (přes názvy, admin2Codes nemá NUTS)")

mapa = mapa_okresu()
geo_okresy = nacti_okresy_geonames()
napojeno, nenapojeno = napoj_okresy_na_nuts(mapa)
print(f"  okresů v admin2Codes.txt (CZ):  {len(geo_okresy)}")
print(f"  z toho napojeno na NUTS kód:    {len(napojeno)}")
print(f"  nenapojeno:                     {len(nenapojeno)}")
for z in nenapojeno:
    print(f"     NENAPOJENO: {z['klic']} {z['geonames_nazev']}")

podle_nuts = collections.defaultdict(list)
for z in napojeno.values():
    podle_nuts[z["okres_kod"]].append(z["geonames_nazev"])
print(f"\n  NUTS okresů pokryto: {len(podle_nuts)} ze {len(mapa)}")
nepokryto = {m['kod'] for m in mapa.values()} - set(podle_nuts)
print(f"  NUTS okresů bez protějšku v Geonames: {sorted(nepokryto) if nepokryto else 'žádný'}")

print("\n  Případy, kdy víc záznamů Geonames ukazuje na jeden okres ČSÚ:")
radky = [[kod, len(nazvy), ", ".join(sorted(nazvy)[:3]) + (" …" if len(nazvy) > 3 else "")]
         for kod, nazvy in sorted(podle_nuts.items()) if len(nazvy) > 1]
tabulka(radky, ["NUTS kód", "záznamů", "názvy v Geonames"])

print("\n  Kontrola ošetřených anomálií:")
for popis, klic in [("alias Město Brno -> Brno-město", "brno-mesto"),
                    ("Praha jako jeden okres", "praha"),
                    ("Praha-východ zůstala samostatná", "praha-vychod"),
                    ("Praha-západ zůstala samostatná", "praha-zapad")]:
    print(f"     {popis:<36} -> {mapa.get(klic)}")

# ---------------------------------------------------------------------------
hlavicka("4. GEONAMES: SÍDLA V ÚSTECKÉM KRAJI")

sidla = nacti_sidla()
print(f"  sídel (feature_class = P):   {len(sidla)}")
print(f"  z toho s populací > 0:       {sum(1 for s in sidla if s['populace'] > 0)}")
print(f"  POZOR: obcí podle ČSÚ je jen {len(obce_uk)} — Geonames obsahuje")
print(f"         i části obcí, osady a samoty, proto je autoritativní ČSÚ.")

print("\n  Rozdělení podle typu sídla (feature_code):")
tabulka([[k, v] for k, v in collections.Counter(
            s["feature_code"] for s in sidla).most_common()],
        ["feature_code", "počet"])

idx = index_sidel(sidla, napojeno)
viceznacne = {k: v for k, v in idx.items() if len(v) > 1}
print(f"\n  Klíčů (název, okres) celkem: {len(idx)}")
print(f"  Z toho dvojznačných:         {len(viceznacne)}")
print("\n  Všechny dvojznačné případy a co z nich skript vybral:")
radky = []
for (nazev, okres), kandidati in sorted(viceznacne.items()):
    zvoleny = vyber_stred(kandidati)
    for s in sorted(kandidati, key=lambda x: x["geonameid"]):
        radky.append([nazev, okres, s["geonameid"], s["feature_code"], s["populace"],
                      "<-- VYBRÁN" if s["geonameid"] == zvoleny["geonameid"] else ""])
tabulka(radky, ["název", "okres", "geonameid", "typ", "populace", ""])

print("\n  Ukázka jednoho sídla (celý záznam):")
vzorek = max(sidla, key=lambda s: s["populace"])
for k, v in vzorek.items():
    print(f"     {k:<20} {v}")

hlavicka("HOTOVO — vše výše načteno přímo ze souborů v data/")
