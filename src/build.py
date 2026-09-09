"""
Spojení tří zdrojů do finálních dokumentů + report nekonzistencí.

Výstup je společný pro MongoDB i Neo4j, aby šla stejná data porovnat
ve dvou modelech. Schéma viz docs/schema.md.
"""

from normalize import KRAJ_UK_NUTS, norm
from parse_geonames import (index_sidel, nacti_sidla, napoj_okresy_na_nuts,
                            vyber_stred)
from parse_lekarny import nacti_lekarny, urci_retezec
from parse_uzemi import LIST_AKTUALNI, mapa_okresu, nacti_obce


def geojson_point(lat, lng):
    """
    Zabalí souřadnice do GeoJSON Point.

    Pořadí je [lng, lat] podle specifikace GeoJSON (RFC 7946) — nejčastější
    zdroj chyb v geodotazech. Vrací None, když poloha není známa; Mongo pak
    dokument z 2dsphere indexu vynechá, místo aby ho umístil na nulový bod.
    """
    if lat is None or lng is None:
        return None
    return {"type": "Point", "coordinates": [lng, lat]}


def postav_obce(kraj=KRAJ_UK_NUTS, rok=LIST_AKTUALNI):
    """
    Postaví dokumenty obcí: hierarchie z ČSÚ obohacená geometrií z Geonames.

    Vrací (obce, report). Obce bez nalezeného protějšku v Geonames zůstanou
    s loc=None — vyloučí se z geodotazů, ale v databázi zůstanou, aby počty
    za okresy a ORP byly úplné.
    """
    obce = nacti_obce(kraj_nuts=kraj, nazev_listu=rok)
    okresy_napojene, _ = napoj_okresy_na_nuts(mapa_okresu(rok))
    idx = index_sidel(nacti_sidla(fips_kraje=None), okresy_napojene)

    nenalezene, viceznacne = [], []
    for o in obce:
        kandidati = idx.get((o["nazev_norm"], o["okres"]["kod"]), [])
        stred = vyber_stred(kandidati)
        if stred is None:
            nenalezene.append({"kod": o["_id"], "nazev": o["nazev"],
                               "okres": o["okres"]["nazev"]})
            o["geonames"] = None
            o["loc"] = None
            o["populace"] = None
            continue
        if len(kandidati) > 1:
            viceznacne.append({
                "obec": o["nazev"], "okres": o["okres"]["kod"],
                "kandidatu": len(kandidati), "vybran": stred["geonameid"],
            })
        o["geonames"] = {
            "geonameid": stred["geonameid"],
            "nazev": stred["nazev"],
            "feature_code": stred["feature_code"],
            "kandidatu": len(kandidati),
        }
        o["loc"] = geojson_point(stred["lat"], stred["lng"])
        o["populace"] = stred["populace"] or None
        o["vyska_m"] = stred["vyska"]

    report = {
        "obci": len(obce),
        "s_geometrii": sum(1 for o in obce if o["loc"]),
        "bez_geometrie": nenalezene,
        "viceznacne_nazvy": viceznacne,
        "s_populaci": sum(1 for o in obce if o.get("populace")),
    }
    return obce, report


def postav_lekarny(obce):
    """
    Postaví dokumenty lékáren: registr doplněný o ORP a chybějící souřadnice.

    Dvě denormalizace, obě vědomé:
      1. ORP se kopíruje z obce do lékárny, aby šla tabulka počtů za ORP
         udělat jednou agregací bez spojování kolekcí ($lookup).
      2. Název obce a okresu zůstává v dokumentu vedle kódu, aby výstupy
         dotazů byly čitelné bez dalšího dohledávání.
    Cena: kdyby ČSÚ přeřadil obec do jiného ORP (za 2013-2024 se to stalo
    19krát), je nutné přepsat i lékárny v ní - update_many, ne jeden zápis.
    """
    lekarny = nacti_lekarny()

    # Index obcí podle (normalizovaný název, okres) — stejný klíč jako
    # u Geonames, protože registr uvádí jen název obce a kód okresu.
    podle_klice = {(o["nazev_norm"], o["okres"]["kod"]): o for o in obce}
    # Záložní index jen podle názvu, kdyby okres v registru nesouhlasil.
    podle_nazvu = {}
    for o in obce:
        podle_nazvu.setdefault(o["nazev_norm"], []).append(o)

    nenapojene, dogeokodovane, jiny_okres = [], [], []
    for l in lekarny:
        klic = (l["adresa"]["obec_norm"], l["uzemi"]["okres_kod"])
        obec = podle_klice.get(klic)

        if obec is None:
            # Registr a ČSÚ se rozešly v okrese — zkusit jen podle názvu.
            kandidati = podle_nazvu.get(l["adresa"]["obec_norm"], [])
            if len(kandidati) == 1:
                obec = kandidati[0]
                jiny_okres.append({
                    "lekarna": l["_id"], "obec": l["adresa"]["obec"],
                    "okres_registr": l["uzemi"]["okres_kod"],
                    "okres_csu": obec["okres"]["kod"],
                })

        if obec is None:
            nenapojene.append({"lekarna": l["_id"], "obec": l["adresa"]["obec"],
                               "okres": l["uzemi"]["okres_kod"]})
            l["obec_kod"] = None
            l["uzemi"]["orp_kod"] = None
            l["uzemi"]["orp_nazev"] = None
        else:
            l["obec_kod"] = obec["_id"]
            # Denormalizace ORP z obce (registr ORP neuvádí vůbec).
            l["uzemi"]["orp_kod"] = obec["orp"]["kod"]
            l["uzemi"]["orp_nazev"] = obec["orp"]["nazev"]

        # Chybějící poloha -> střed obce, s příznakem o přibližnosti.
        if l["lat"] is None and obec is not None and obec["loc"] is not None:
            lng, lat = obec["loc"]["coordinates"]
            l["lat"], l["lng"] = lat, lng
            l["geo_zdroj"] = "obec"
            dogeokodovane.append({"lekarna": l["_id"], "nazev": l["nazev"],
                                  "obec": l["adresa"]["obec"]})

        l["loc"] = geojson_point(l["lat"], l["lng"])
        l["retezec"] = urci_retezec(l["nazev"])

    report = {
        "lekaren": len(lekarny),
        "s_geometrii": sum(1 for l in lekarny if l["loc"]),
        "z_registru": sum(1 for l in lekarny if l["geo_zdroj"] == "registr"),
        "dogeokodovane": dogeokodovane,
        "napojenych_na_obec": sum(1 for l in lekarny if l["obec_kod"]),
        "nenapojene": nenapojene,
        "okres_se_rozchazi": jiny_okres,
    }
    return lekarny, report


def postav_vse(kraj=KRAJ_UK_NUTS, rok=LIST_AKTUALNI):
    """Postaví obě kolekce a vrátí je se společným reportem."""
    obce, rep_obce = postav_obce(kraj, rok)
    lekarny, rep_lek = postav_lekarny(obce)

    # Kolik lékáren má která obec — potřeba pro úlohu "obce bez lékárny".
    from collections import Counter
    pocty = Counter(l["obec_kod"] for l in lekarny if l["obec_kod"])
    for o in obce:
        o["lekaren"] = pocty.get(o["_id"], 0)
        o["ma_lekarnu"] = o["lekaren"] > 0

    report = {
        "rok_hierarchie": rok,
        "kraj": kraj,
        "obce": rep_obce,
        "lekarny": rep_lek,
        "obci_s_lekarnou": sum(1 for o in obce if o["ma_lekarnu"]),
        "obci_bez_lekarny": sum(1 for o in obce if not o["ma_lekarnu"]),
    }
    return obce, lekarny, report


if __name__ == "__main__":
    obce, lekarny, rep = postav_vse()
    print(f"obcí: {rep['obce']['obci']}, s geometrií: {rep['obce']['s_geometrii']}, "
          f"s populací: {rep['obce']['s_populaci']}")
    print(f"  bez geometrie: {rep['obce']['bez_geometrie']}")
    print(f"  víceznačných názvů: {len(rep['obce']['viceznacne_nazvy'])}")
    print(f"\nlékáren: {rep['lekarny']['lekaren']}, "
          f"s geometrií: {rep['lekarny']['s_geometrii']} "
          f"(z registru {rep['lekarny']['z_registru']}, "
          f"dogeokódováno {len(rep['lekarny']['dogeokodovane'])})")
    print(f"  napojeno na obec: {rep['lekarny']['napojenych_na_obec']}")
    print(f"  nenapojeno: {rep['lekarny']['nenapojene']}")
    print(f"  okres se rozchází: {rep['lekarny']['okres_se_rozchazi']}")
    print(f"\nobcí s lékárnou: {rep['obci_s_lekarnou']}, "
          f"bez lékárny: {rep['obci_bez_lekarny']}")
    print("\nukázka obce s lékárnou:")
    vzorek = max(obce, key=lambda o: o["lekaren"])
    for k, v in vzorek.items():
        print(f"   {k:<14} {v}")
