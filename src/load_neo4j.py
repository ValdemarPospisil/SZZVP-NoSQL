"""
Naplnění Neo4j: uzly, hrany a graf dostupnosti pro minimální kostru.

Schéma grafu — uzly:

    (:Kraj   {kod, nazev})
    (:Okres  {kod, nazev})
    (:ORP    {kod, nazev})
    (:Obec   {kod, nazev, status, populace, poloha, lekaren, ma_lekarnu})
    (:Lekarna{id, nazev, retezec, poloha, geo_zdroj})

hrany:

    (:Okres)   -[:V_KRAJI]->   (:Kraj)
    (:ORP)     -[:V_OKRESE]->  (:Okres)      hierarchie ČSÚ
    (:Obec)    -[:V_ORP]->     (:ORP)
    (:Obec)    -[:V_OKRESE]->  (:Okres)      zkratka, viz níže
    (:Lekarna) -[:V_OBCI]->    (:Obec)
    (:Obec)    -[:BLIZKO {km}]-(:Obec)       graf dostupnosti pro kostru

Proč je hierarchie grafem a ne vlastnostmi uzlu:
  v Neo4j je vztah prvotřídní objekt, takže dotaz "kolik lékáren v ORP"
  je průchod hran, ne agregace nad zkopírovanými hodnotami. Tím se
  vyhneme denormalizaci, kterou musí dělat Mongo.

Proč přesto existuje zkratka (:Obec)-[:V_OKRESE]->(:Okres):
  hranice ORP a okresů se nekryjí (okres Litoměřice se dělí na 3 ORP),
  takže okres NELZE odvodit průchodem přes ORP. Je to samostatný fakt
  ze zdroje, ne redundance.

Hrany BLIZKO tvoří graf dostupnosti, nad kterým se počítá minimální
kostra. Úplný graf 354 obcí by měl 62 481 hran, což je pro kostru
zbytečné — proto se hrany omezují na k nejbližších sousedů (kNN),
což kostru nezmění, dokud graf zůstane spojitý.
"""

import math
from itertools import combinations

from neo4j import GraphDatabase

from build import postav_vse

NEO4J_URI = "bolt://localhost:7687"

# Počet nejbližších sousedů, se kterými se obec spojí hranou BLIZKO.
# 6 stačí na spojitost grafu ÚK a drží počet hran v tisících místo desítek
# tisíc. Spojitost se po vložení ověřuje (viz overit()).
K_SOUSEDU = 6


def vzdalenost_km(a, b):
    """
    Haversinova vzdálenost dvou bodů na kouli v kilometrech.

    Používá se pro předvýpočet hran BLIZKO. Neo4j má vlastní
    point.distance(), ale spočítat vzdálenosti v Pythonu je při vkládání
    rychlejší než 62 tisíc volání v Cypheru.

    a, b = (lat, lng)
    """
    R = 6371.0088                        # střední zemský radius v km
    lat1, lng1 = math.radians(a[0]), math.radians(a[1])
    lat2, lng2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def hrany_knn(obce, k=K_SOUSEDU):
    """
    Vytvoří hrany ke k nejbližším sousedům každé obce.

    Hrana je neorientovaná, takže se ukládá jen jednou (menší kód první).
    Symetrizace je záměrná: když je B mezi k nejbližšími od A, hrana
    vznikne i kdyby A nebylo mezi k nejbližšími od B. Bez toho by graf
    snadno zůstal nespojitý.
    """
    body = [(o["_id"], o["loc"]["coordinates"][1], o["loc"]["coordinates"][0])
            for o in obce if o["loc"]]

    hrany = {}
    for kod, lat, lng in body:
        vzdalenosti = sorted(
            ((vzdalenost_km((lat, lng), (lat2, lng2)), kod2)
             for kod2, lat2, lng2 in body if kod2 != kod),
        )[:k]
        for km, kod2 in vzdalenosti:
            klic = tuple(sorted((kod, kod2)))
            hrany[klic] = round(km, 4)
    return [{"a": a, "b": b, "km": km} for (a, b), km in hrany.items()]


def naplnit(uri=NEO4J_URI, k=K_SOUSEDU):
    """Smaže graf a vloží uzly, hierarchii a hrany dostupnosti."""
    obce, lekarny, report = postav_vse()

    drv = GraphDatabase.driver(uri)
    drv.verify_connectivity()

    # --- vyčištění a omezení (constraints) ---
    drv.execute_query("MATCH (n) DETACH DELETE n")
    for label, klic in [("Kraj", "kod"), ("Okres", "kod"), ("ORP", "kod"),
                        ("Obec", "kod"), ("Lekarna", "id")]:
        # Omezení na jednoznačnost zároveň zakládá index — bez něj by
        # MERGE nad 354 obcemi dělal plný průchod grafem.
        drv.execute_query(
            f"CREATE CONSTRAINT {label.lower()}_{klic} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{klic} IS UNIQUE")

    # --- hierarchie: kraj, okresy, ORP ---
    # UNWIND + MERGE v jednom dotazu místo dotazu na řádek.
    kraje = {(o["kraj"]["kod"], o["kraj"]["nazev"]) for o in obce}
    drv.execute_query(
        "UNWIND $d AS r MERGE (k:Kraj {kod: r.kod}) SET k.nazev = r.nazev",
        d=[{"kod": k, "nazev": n} for k, n in kraje])

    okresy = {(o["okres"]["kod"], o["okres"]["nazev"], o["kraj"]["kod"]) for o in obce}
    drv.execute_query("""
        UNWIND $d AS r
        MERGE (o:Okres {kod: r.kod}) SET o.nazev = r.nazev
        WITH o, r MATCH (k:Kraj {kod: r.kraj}) MERGE (o)-[:V_KRAJI]->(k)
        """, d=[{"kod": k, "nazev": n, "kraj": kr} for k, n, kr in okresy])

    orp = {(o["orp"]["kod"], o["orp"]["nazev"], o["okres"]["kod"]) for o in obce}
    drv.execute_query("""
        UNWIND $d AS r
        MERGE (p:ORP {kod: r.kod}) SET p.nazev = r.nazev
        WITH p, r MATCH (o:Okres {kod: r.okres}) MERGE (p)-[:V_OKRESE]->(o)
        """, d=[{"kod": k, "nazev": n, "okres": ok} for k, n, ok in orp])

    # --- obce ---
    # point({latitude, longitude}) je nativní typ Neo4j; umožní
    # point.distance() a prostorový index.
    drv.execute_query("""
        UNWIND $d AS r
        MERGE (b:Obec {kod: r.kod})
        SET b.nazev = r.nazev, b.nazev_norm = r.nazev_norm,
            b.status = r.status, b.status_popis = r.status_popis,
            b.populace = r.populace, b.lekaren = r.lekaren,
            b.ma_lekarnu = r.ma_lekarnu,
            b.poloha = CASE WHEN r.lat IS NULL THEN NULL
                       ELSE point({latitude: r.lat, longitude: r.lng, crs:'WGS-84'}) END
        WITH b, r
        MATCH (p:ORP {kod: r.orp}) MERGE (b)-[:V_ORP]->(p)
        WITH b, r
        MATCH (o:Okres {kod: r.okres}) MERGE (b)-[:V_OKRESE]->(o)
        """, d=[{
            "kod": o["_id"], "nazev": o["nazev"], "nazev_norm": o["nazev_norm"],
            "status": o["status"], "status_popis": o["status_popis"],
            "populace": o.get("populace"), "lekaren": o["lekaren"],
            "ma_lekarnu": o["ma_lekarnu"],
            "lat": o["loc"]["coordinates"][1] if o["loc"] else None,
            "lng": o["loc"]["coordinates"][0] if o["loc"] else None,
            "orp": o["orp"]["kod"], "okres": o["okres"]["kod"],
        } for o in obce])

    # --- lékárny ---
    drv.execute_query("""
        UNWIND $d AS r
        MERGE (l:Lekarna {id: r.id})
        SET l.nazev = r.nazev, l.retezec = r.retezec, l.geo_zdroj = r.geo_zdroj,
            l.obec_nazev = r.obec_nazev, l.ulice = r.ulice,
            // Krátký popisek pro zobrazení v Browseru: plný název z registru
            // má až 80 znaků ("ČESKÁ LÉKÁRNA HOLDING, a.s., Dr. Max Lékárna")
            // a v kolečku uzlu se nevejde.
            l.popis = r.retezec + ' ' + r.obec_nazev,
            l.poloha = CASE WHEN r.lat IS NULL THEN NULL
                       ELSE point({latitude: r.lat, longitude: r.lng, crs:'WGS-84'}) END
        WITH l, r
        MATCH (b:Obec {kod: r.obec_kod}) MERGE (l)-[:V_OBCI]->(b)
        """, d=[{
            "id": l["_id"], "nazev": l["nazev"], "retezec": l["retezec"],
            "geo_zdroj": l["geo_zdroj"], "obec_nazev": l["adresa"]["obec"],
            "ulice": l["adresa"]["ulice"],
            "lat": l["lat"], "lng": l["lng"], "obec_kod": l["obec_kod"],
        } for l in lekarny if l["obec_kod"]])

    # --- graf dostupnosti (hrany BLIZKO) ---
    hrany = hrany_knn(obce, k)
    drv.execute_query("""
        UNWIND $d AS r
        MATCH (a:Obec {kod: r.a}), (b:Obec {kod: r.b})
        MERGE (a)-[e:BLIZKO]-(b) SET e.km = r.km
        """, d=hrany)

    return drv, report, len(hrany)


def overit(drv):
    """Ověří, co je v grafu — počty uzlů, hran a spojitost."""
    def jedna(q, **kw):
        recs, _, _ = drv.execute_query(q, **kw)
        return recs[0][0] if recs else None

    stav = {
        "Kraj": jedna("MATCH (n:Kraj) RETURN count(n)"),
        "Okres": jedna("MATCH (n:Okres) RETURN count(n)"),
        "ORP": jedna("MATCH (n:ORP) RETURN count(n)"),
        "Obec": jedna("MATCH (n:Obec) RETURN count(n)"),
        "Lekarna": jedna("MATCH (n:Lekarna) RETURN count(n)"),
        "obce_s_polohou": jedna("MATCH (n:Obec) WHERE n.poloha IS NOT NULL RETURN count(n)"),
        "V_ORP": jedna("MATCH ()-[r:V_ORP]->() RETURN count(r)"),
        "V_OKRESE": jedna("MATCH ()-[r:V_OKRESE]->() RETURN count(r)"),
        "V_KRAJI": jedna("MATCH ()-[r:V_KRAJI]->() RETURN count(r)"),
        "V_OBCI": jedna("MATCH ()-[r:V_OBCI]->() RETURN count(r)"),
        "BLIZKO": jedna("MATCH ()-[r:BLIZKO]-() RETURN count(r)/2"),
    }

    # Spojitost grafu BLIZKO: kostra existuje jen nad spojitým grafem.
    # Průchod z jedné obce musí dosáhnout všech ostatních s polohou.
    stav["dosazitelnych_z_jedne"] = jedna("""
        MATCH (start:Obec) WHERE start.poloha IS NOT NULL
        WITH start LIMIT 1
        MATCH path = (start)-[:BLIZKO*]-(o:Obec)
        RETURN count(DISTINCT o)
        """)
    return stav


if __name__ == "__main__":
    drv, report, pocet_hran = naplnit()
    stav = overit(drv)

    print("=" * 70)
    print("  Neo4j: graf naplněn")
    print("=" * 70)
    print("  uzly:")
    for label in ("Kraj", "Okres", "ORP", "Obec", "Lekarna"):
        print(f"     {label:<10} {stav[label]:>5}")
    print(f"     (obcí s polohou: {stav['obce_s_polohou']})")
    print("  hrany:")
    for typ in ("V_KRAJI", "V_OKRESE", "V_ORP", "V_OBCI", "BLIZKO"):
        print(f"     {typ:<10} {stav[typ]:>5}")

    print(f"\n  spojitost grafu BLIZKO (k={K_SOUSEDU}):")
    print(f"     z jedné obce dosažitelných: {stav['dosazitelnych_z_jedne']} "
          f"z {stav['obce_s_polohou']}")
    if stav["dosazitelnych_z_jedne"] == stav["obce_s_polohou"]:
        print("     graf je SPOJITÝ -> minimální kostra pokryje všechny obce")
    else:
        print("     POZOR: graf je NESPOJITÝ -> kostra bude jen les, "
              "zvyš K_SOUSEDU")

    print("\n  Prohlédni si graf: http://localhost:7474")
    drv.close()
