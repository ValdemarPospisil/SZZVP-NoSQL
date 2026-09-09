"""
Dotazy nad MongoDB — agregační pipeline.

Každá funkce vrací seznam dictů, aby výstup šel rovnou do DataFrame.
"""

from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "lekarny"


def pripoj(uri=MONGO_URI, db=DB_NAME):
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    return client[db]


# ---------------------------------------------------------------------------
# 1. Povinná tabulka: počty lékáren v okresech a ORP
# ---------------------------------------------------------------------------

def pocty_okresy(db):
    """
    Počty lékáren a obcí za okresy.

    Sloučení dvou agregací: lékárny se počítají v kolekci lekarny,
    obce v kolekci obce. Spojení přes $unionWith by šlo taky, ale dvě
    jednoduché agregace jsou čitelnější a rychlejší než jedna složitá.

    Denormalizace se tu vyplácí: okres je zkopírovaný do každé lékárny,
    takže stačí $group bez $lookup.
    """
    lek = {r["_id"]: r for r in db.lekarny.aggregate([
        {"$group": {
            "_id": "$uzemi.okres_kod",
            "nazev": {"$first": "$uzemi.okres_nazev"},
            "lekaren": {"$sum": 1},
        }},
    ])}

    obce = {r["_id"]: r for r in db.obce.aggregate([
        {"$group": {
            "_id": "$okres.kod",
            "nazev": {"$first": "$okres.nazev"},
            "obci": {"$sum": 1},
            "obci_s_lekarnou": {"$sum": {"$cond": ["$ma_lekarnu", 1, 0]}},
            "populace": {"$sum": {"$ifNull": ["$populace", 0]}},
        }},
    ])}

    vysledek = []
    for kod in sorted(obce):
        o = obce[kod]
        l = lek.get(kod, {})
        pocet = l.get("lekaren", 0)
        pop = o["populace"]
        vysledek.append({
            "kod": kod,
            "okres": o["nazev"],
            "obci": o["obci"],
            "obci_s_lekarnou": o["obci_s_lekarnou"],
            "obci_bez_lekarny": o["obci"] - o["obci_s_lekarnou"],
            "lekaren": pocet,
            "populace": pop,
            # Hustota na 10 tisíc obyvatel — srovnatelné mezi okresy,
            # absolutní počty srovnávat nelze (Most má 63 tis., Louny 18).
            "lekaren_na_10tis": round(pocet / pop * 10000, 2) if pop else None,
        })
    return vysledek


def pocty_orp(db):
    """Počty lékáren a obcí za ORP (obec s rozšířenou působností)."""
    lek = {r["_id"]: r for r in db.lekarny.aggregate([
        {"$group": {
            "_id": "$uzemi.orp_kod",
            "nazev": {"$first": "$uzemi.orp_nazev"},
            "lekaren": {"$sum": 1},
        }},
    ])}

    obce = {r["_id"]: r for r in db.obce.aggregate([
        {"$group": {
            "_id": "$orp.kod",
            "nazev": {"$first": "$orp.nazev"},
            "obci": {"$sum": 1},
            "obci_s_lekarnou": {"$sum": {"$cond": ["$ma_lekarnu", 1, 0]}},
            "populace": {"$sum": {"$ifNull": ["$populace", 0]}},
        }},
    ])}

    vysledek = []
    for kod in sorted(obce):
        o = obce[kod]
        pocet = lek.get(kod, {}).get("lekaren", 0)
        pop = o["populace"]
        vysledek.append({
            "kod": kod,
            "orp": o["nazev"],
            "obci": o["obci"],
            "obci_s_lekarnou": o["obci_s_lekarnou"],
            "obci_bez_lekarny": o["obci"] - o["obci_s_lekarnou"],
            "lekaren": pocet,
            "populace": pop,
            "lekaren_na_10tis": round(pocet / pop * 10000, 2) if pop else None,
        })
    return vysledek


# ---------------------------------------------------------------------------
# 2. Hlavní úloha: vzdálenost obcí bez lékárny od nejbližší lékárny
# ---------------------------------------------------------------------------

def _pipeline_nejblizsi(jen_bez_lekarny=True):
    """
    Sestaví pipeline pro vzdálenost k nejbližší lékárně.

    Konstrukce po stupních:
      $match    vybere obce (bez lékárny, se známou polohou)
      $lookup   pro KAŽDOU obec spustí vnořenou pipeline nad lekarny:
                  $geoNear  vzdálenosti od středu té obce ('let' předá loc)
                  $limit 1  jen nejbližší
                Vnořená pipeline je jediný způsob, jak dostat $geoNear
                na první místo pro každý dokument zvlášť.
      $unwind   rozbalí jednoprvkové pole na podobjekt
      $project  přepočet metrů na kilometry, výběr čitelných polí
      $sort     nejvzdálenější první
    """
    podminka = {"loc": {"$ne": None}}
    if jen_bez_lekarny:
        podminka["ma_lekarnu"] = False

    return [
        {"$match": podminka},
        {"$lookup": {
            "from": "lekarny",
            "as": "nejblizsi",
            # 'let' zpřístupní hodnotu z nadřazeného dokumentu ve vnořené
            # pipeline jako $$stred.
            "let": {"stred": "$loc"},
            "pipeline": [
                {"$geoNear": {
                    "near": "$$stred",
                    "distanceField": "vzdalenost_m",
                    "spherical": True,          # počítat po povrchu kulové Země
                }},
                {"$limit": 1},                   # Mongo 8: limit NELZE do $geoNear
                {"$project": {
                    "vzdalenost_m": 1, "nazev": 1, "retezec": 1,
                    "obec": "$adresa.obec", "geo_zdroj": 1,
                }},
            ],
        }},
        {"$unwind": "$nejblizsi"},
        {"$project": {
            "_id": 1,
            "obec": "$nazev",
            "okres": "$okres.nazev",
            "orp": "$orp.nazev",
            "status": "$status_popis",
            "populace": 1,
            "km": {"$round": [{"$divide": ["$nejblizsi.vzdalenost_m", 1000]}, 2]},
            "lekarna": "$nejblizsi.nazev",
            "lekarna_v": "$nejblizsi.obec",
            "lekarna_retezec": "$nejblizsi.retezec",
            # Příznak přibližné polohy lékárny se nese do výsledku, aby
            # nezmizela informace o kvalitě dat.
            "lekarna_geo_zdroj": "$nejblizsi.geo_zdroj",
        }},
        {"$sort": {"km": -1}},
    ]


def nejvzdalenejsi_obce(db, limit=10):
    """Deset (nebo jiný počet) nejvzdálenějších obcí bez lékárny."""
    return list(db.obce.aggregate(_pipeline_nejblizsi() + [{"$limit": limit}]))


def vzdalenosti_vsechny(db):
    """
    Vzdálenosti pro všechny obce bez lékárny — vstup pro histogram
    a pro souhrnné statistiky.
    """
    return list(db.obce.aggregate(_pipeline_nejblizsi()))


def souhrn_vzdalenosti(db):
    """
    Souhrnné statistiky vzdálenosti k nejbližší lékárně.

    Medián se v Mongu počítá přes $percentile (od verze 7), ne ručním
    tříděním.
    """
    return list(db.obce.aggregate(_pipeline_nejblizsi() + [
        {"$group": {
            "_id": None,
            "obci": {"$sum": 1},
            "prumer_km": {"$avg": "$km"},
            "min_km": {"$min": "$km"},
            "max_km": {"$max": "$km"},
            "median_km": {"$percentile": {
                "input": "$km", "p": [0.5], "method": "approximate"}},
            # Kolik lidí žije dál než 5 km od lékárny.
            "obyvatel_nad_5km": {"$sum": {
                "$cond": [{"$gt": ["$km", 5]}, {"$ifNull": ["$populace", 0]}, 0]}},
            "obci_nad_5km": {"$sum": {"$cond": [{"$gt": ["$km", 5]}, 1, 0]}},
            "obci_nad_10km": {"$sum": {"$cond": [{"$gt": ["$km", 10]}, 1, 0]}},
        }},
        {"$project": {
            "_id": 0, "obci": 1, "obci_nad_5km": 1, "obci_nad_10km": 1,
            "obyvatel_nad_5km": 1,
            "prumer_km": {"$round": ["$prumer_km", 2]},
            "median_km": {"$round": [{"$first": "$median_km"}, 2]},
            "min_km": 1, "max_km": 1,
        }},
    ]))[0]


# ---------------------------------------------------------------------------
# 3. Vlastní zpracování nad rámec zadání
# ---------------------------------------------------------------------------

def retezce_po_okresech(db):
    """
    Koncentrace lékárenských sítí po okresech.

    $group se složeným _id, pak $group podruhé pro sbalení do řádku
    na okres — typický dvoustupňový pivot v agregační pipeline.
    """
    return list(db.lekarny.aggregate([
        {"$group": {
            "_id": {"okres": "$uzemi.okres_nazev", "retezec": "$retezec"},
            "pocet": {"$sum": 1},
        }},
        {"$group": {
            "_id": "$_id.okres",
            "celkem": {"$sum": "$pocet"},
            "retezce": {"$push": {"retezec": "$_id.retezec", "pocet": "$pocet"}},
        }},
        {"$project": {
            "_id": 0, "okres": "$_id", "celkem": 1,
            "retezce": {"$sortArray": {"input": "$retezce", "sortBy": {"pocet": -1}}},
            # Podíl největšího řetězce = míra koncentrace trhu.
            "nejvetsi_podil": {"$round": [{"$multiply": [
                {"$divide": [{"$max": "$retezce.pocet"}, "$celkem"]}, 100]}, 1]},
        }},
        {"$sort": {"celkem": -1}},
    ]))


def lekarenska_pustina(db, limit=10):
    """
    Obce vážené počtem obyvatel × vzdálenost k lékárně.

    Samotná vzdálenost neříká, kolika lidí se problém týká: Brandov je
    nejdál (14,98 km), ale má 249 obyvatel. Součin dává "osobokilometry",
    tedy kde je nedostupnost nejcitelnější v součtu.
    """
    return list(db.obce.aggregate(_pipeline_nejblizsi() + [
        {"$match": {"populace": {"$ne": None}}},
        {"$addFields": {"osobokm": {"$round": [
            {"$multiply": ["$populace", "$km"]}, 0]}}},
        {"$sort": {"osobokm": -1}},
        {"$limit": limit},
    ]))


def obce_s_nejvic_lekarnami(db, limit=10):
    """Obce s nejvyšší hustotou lékáren na obyvatele."""
    return list(db.obce.aggregate([
        {"$match": {"lekaren": {"$gt": 0}, "populace": {"$ne": None}}},
        {"$project": {
            "_id": 0, "obec": "$nazev", "okres": "$okres.nazev",
            "status": "$status_popis", "lekaren": 1, "populace": 1,
            "na_10tis": {"$round": [{"$multiply": [
                {"$divide": ["$lekaren", "$populace"]}, 10000]}, 2]},
        }},
        {"$sort": {"na_10tis": -1}},
        {"$limit": limit},
    ]))


def kvalita_geokodovani(db):
    """
    Přehled kvality polohových dat — kolik lékáren má přesnou adresu
    a kolik jen střed obce.

    Patří do výstupů: ovlivňuje to spolehlivost všech vzdáleností.
    """
    return list(db.lekarny.aggregate([
        {"$group": {"_id": "$geo_zdroj", "pocet": {"$sum": 1},
                    "obce": {"$push": "$adresa.obec"}}},
        {"$sort": {"pocet": -1}},
    ]))


if __name__ == "__main__":
    db = pripoj()

    def tab(radky, sloupce):
        if not radky:
            print("   (nic)")
            return
        sirky = [max(len(str(r.get(c, ""))) for r in radky + [{c: c for c in sloupce}])
                 for c in sloupce]
        print("   " + " | ".join(c.ljust(sirky[i]) for i, c in enumerate(sloupce)))
        print("   " + "-+-".join("-" * s for s in sirky))
        for r in radky:
            print("   " + " | ".join(
                str(r.get(c, "")).ljust(sirky[i]) for i, c in enumerate(sloupce)))

    print("=" * 78)
    print("  1. POČTY LÉKÁREN V OKRESECH")
    print("=" * 78)
    tab(pocty_okresy(db), ["kod", "okres", "obci", "obci_s_lekarnou",
                            "obci_bez_lekarny", "lekaren", "populace",
                            "lekaren_na_10tis"])

    print("\n" + "=" * 78)
    print("  2. POČTY LÉKÁREN V ORP")
    print("=" * 78)
    tab(pocty_orp(db), ["kod", "orp", "obci", "obci_s_lekarnou",
                         "obci_bez_lekarny", "lekaren", "lekaren_na_10tis"])

    print("\n" + "=" * 78)
    print("  3. DESET NEJVZDÁLENĚJŠÍCH OBCÍ BEZ LÉKÁRNY (hlavní úloha)")
    print("=" * 78)
    tab(nejvzdalenejsi_obce(db), ["obec", "okres", "orp", "populace", "km",
                                   "lekarna_v", "lekarna_retezec"])

    print("\n" + "=" * 78)
    print("  4. SOUHRN VZDÁLENOSTÍ")
    print("=" * 78)
    s = souhrn_vzdalenosti(db)
    print(f"   obcí bez lékárny se známou polohou: {s['obci']}")
    print(f"   vzdálenost k nejbližší lékárně: "
          f"min {s['min_km']} km, medián {s['median_km']} km, "
          f"průměr {s['prumer_km']} km, max {s['max_km']} km")
    print(f"   obcí dál než 5 km:  {s['obci_nad_5km']}")
    print(f"   obcí dál než 10 km: {s['obci_nad_10km']}")
    print(f"   obyvatel žijících dál než 5 km: {s['obyvatel_nad_5km']}")

    print("\n" + "=" * 78)
    print("  5. LÉKÁRENSKÁ PUSTINA (obyvatelé × km) — vlastní zpracování")
    print("=" * 78)
    tab(lekarenska_pustina(db), ["obec", "okres", "populace", "km", "osobokm",
                                  "lekarna_v"])

    print("\n" + "=" * 78)
    print("  6. KONCENTRACE ŘETĚZCŮ PO OKRESECH — vlastní zpracování")
    print("=" * 78)
    for r in retezce_po_okresech(db):
        rozpis = ", ".join(f"{x['retezec']} {x['pocet']}" for x in r["retezce"])
        print(f"   {r['okres']:<16} celkem {r['celkem']:>3}  "
              f"největší podíl {r['nejvetsi_podil']:>5} %   {rozpis}")

    print("\n" + "=" * 78)
    print("  7. NEJVYŠŠÍ HUSTOTA LÉKÁREN — vlastní zpracování")
    print("=" * 78)
    tab(obce_s_nejvic_lekarnami(db), ["obec", "okres", "status", "lekaren",
                                       "populace", "na_10tis"])

    print("\n" + "=" * 78)
    print("  8. KVALITA GEOKÓDOVÁNÍ")
    print("=" * 78)
    for r in kvalita_geokodovani(db):
        print(f"   geo_zdroj={r['_id']!r:<12} {r['pocet']:>3} lékáren", end="")
        if r["_id"] == "obec":
            print(f"   ({', '.join(sorted(set(r['obce'])))})")
        else:
            print()
