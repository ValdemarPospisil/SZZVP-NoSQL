"""
Dotazy nad grafem v Neo4j, včetně minimální kostry dostupnosti lékáren.

Hlavní úloha ze zadání: minimální kostra grafu obcí, kde ohodnocením hrany
je geografická vzdálenost. Kostra je nejlevnější podmnožina hran, která
udrží graf spojitý — interpretace pro tuto úlohu je "nejkratší možná síť
spojnic, po níž je dosažitelná každá obec v kraji".

Past v GDS: gds.spanningTree.stream vrací i řádek pro KOŘEN stromu,
kde nodeId == parentId a weight = 0. Bez jeho odfiltrování vyjde o jednu
hranu víc, než strom může mít (n uzlů -> n-1 hran).
"""

from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
PROJEKCE = "dostupnost"

# Kořenový řádek se pozná podle nodeId == parentId a musí se vyloučit.
KOSTRA_STREAM = """
    MATCH (start:Obec) WHERE start.poloha IS NOT NULL
    WITH start LIMIT 1
    CALL gds.spanningTree.stream($projekce, {
        sourceNode: start, relationshipWeightProperty: 'km'})
    YIELD nodeId, parentId, weight
    WITH gds.util.asNode(nodeId) AS a, gds.util.asNode(parentId) AS b, weight
    WHERE a <> b
"""


def pripoj(uri=NEO4J_URI):
    drv = GraphDatabase.driver(uri)
    drv.verify_connectivity()
    return drv


def vytvor_projekci(drv, nazev=PROJEKCE):
    """
    Promítne hrany BLIZKO do paměťového grafu GDS.

    Algoritmy GDS nepracují nad uloženým grafem, ale nad projekcí v paměti.
    undirectedRelationshipTypes je nutné: kostra dává smysl jen nad
    neorientovaným grafem.
    """
    drv.execute_query(
        "CALL gds.graph.drop($n, false) YIELD graphName RETURN graphName", n=nazev)
    recs, _, _ = drv.execute_query("""
        MATCH (source:Obec)-[r:BLIZKO]-(target:Obec)
        RETURN gds.graph.project($n, source, target,
            {relationshipProperties: r {.km}},
            {undirectedRelationshipTypes: ['*']}) AS g
        """, n=nazev)
    return recs[0]["g"]


def kostra_souhrn(drv, nazev=PROJEKCE):
    """Souhrnné údaje o minimální kostře."""
    recs, _, _ = drv.execute_query(KOSTRA_STREAM + """
        RETURN count(*) AS hran,
               round(sum(weight)*100)/100 AS celkem_km,
               round(avg(weight)*100)/100 AS prumer_km,
               round(min(weight)*100)/100 AS nejkratsi_km,
               round(max(weight)*100)/100 AS nejdelsi_km
        """, projekce=nazev)
    return dict(recs[0])


def kostra_hrany(drv, limit=15, nazev=PROJEKCE):
    """Nejdelší hrany kostry — kritická spojení, jejichž ztráta síť rozdělí."""
    recs, _, _ = drv.execute_query(KOSTRA_STREAM + """
        RETURN a.nazev AS obec, a.ma_lekarnu AS obec_ma_lekarnu,
               b.nazev AS soused, b.ma_lekarnu AS soused_ma_lekarnu,
               round(weight*100)/100 AS km
        ORDER BY km DESC LIMIT $limit
        """, projekce=nazev, limit=limit)
    return [dict(r) for r in recs]


def kostra_zapis(drv, nazev=PROJEKCE):
    """
    Uloží hrany kostry do grafu jako :V_KOSTRE, aby šly zobrazit v Browseru.

    Neo4j Browser kreslí výsledek dotazu; uložením kostry jako hran ji lze
    vykreslit samostatně místo celého grafu 1266 hran.
    """
    drv.execute_query("MATCH ()-[r:V_KOSTRE]-() DELETE r")
    drv.execute_query(KOSTRA_STREAM + """
        MERGE (a)-[e:V_KOSTRE]-(b) SET e.km = round(weight*100)/100
        """, projekce=nazev)
    recs, _, _ = drv.execute_query(
        "MATCH ()-[r:V_KOSTRE]-() RETURN count(r)/2 AS hran")
    return recs[0]["hran"]


def pocty_lekaren_okresy(drv):
    """Počty lékáren a obcí za okresy — průchodem hran, bez denormalizace."""
    recs, _, _ = drv.execute_query("""
        MATCH (o:Okres)<-[:V_OKRESE]-(b:Obec)
        OPTIONAL MATCH (b)<-[:V_OBCI]-(l:Lekarna)
        WITH o, b, count(l) AS lek
        RETURN o.kod AS kod, o.nazev AS okres,
               count(b) AS obci, sum(lek) AS lekaren,
               sum(CASE WHEN lek > 0 THEN 1 ELSE 0 END) AS obci_s_lekarnou,
               sum(b.populace) AS populace
        ORDER BY kod
        """)
    return [dict(r) for r in recs]


def pocty_lekaren_orp(drv):
    """Počty lékáren a obcí za ORP."""
    recs, _, _ = drv.execute_query("""
        MATCH (p:ORP)<-[:V_ORP]-(b:Obec)
        OPTIONAL MATCH (b)<-[:V_OBCI]-(l:Lekarna)
        WITH p, b, count(l) AS lek
        RETURN p.kod AS kod, p.nazev AS orp,
               count(b) AS obci, sum(lek) AS lekaren,
               sum(CASE WHEN lek > 0 THEN 1 ELSE 0 END) AS obci_s_lekarnou
        ORDER BY kod
        """)
    return [dict(r) for r in recs]


def nejblizsi_lekarna(drv, limit=10):
    """
    Obce bez lékárny a jejich nejbližší lékárna, nejvzdálenější první.

    Grafová obdoba mongo úlohy — pro srovnání obou modelů. Používá
    nativní point.distance() nad prostorovým typem Neo4j.
    """
    recs, _, _ = drv.execute_query("""
        MATCH (b:Obec) WHERE b.ma_lekarnu = false AND b.poloha IS NOT NULL
        MATCH (l:Lekarna) WHERE l.poloha IS NOT NULL
        WITH b, l, point.distance(b.poloha, l.poloha)/1000 AS km
        ORDER BY b.kod, km
        WITH b, collect({lekarna: l.nazev, obec: l.obec_nazev, km: km})[0] AS nej
        MATCH (b)-[:V_OKRESE]->(o:Okres)
        RETURN b.nazev AS obec, o.nazev AS okres, b.populace AS populace,
               round(nej.km*100)/100 AS km, nej.obec AS lekarna_v
        ORDER BY km DESC LIMIT $limit
        """, limit=limit)
    return [dict(r) for r in recs]


if __name__ == "__main__":
    drv = pripoj()
    g = vytvor_projekci(drv)
    print(f"projekce GDS: {g['nodeCount']} uzlů, {g['relationshipCount']} hran "
          f"(orientované obousměrně, proto 2x počet BLIZKO)")

    s = kostra_souhrn(drv)
    print(f"\n=== MINIMÁLNÍ KOSTRA DOSTUPNOSTI ===")
    print(f"  hran:           {s['hran']}  (uzlů {g['nodeCount']} -> strom má n-1)")
    print(f"  celková délka:  {s['celkem_km']} km")
    print(f"  průměrná hrana: {s['prumer_km']} km")
    print(f"  rozsah hran:    {s['nejkratsi_km']} – {s['nejdelsi_km']} km")

    print(f"\n  Nejdelší hrany (kritická spojení):")
    for h in kostra_hrany(drv, 8):
        lek = "L" if h["obec_ma_lekarnu"] else " "
        lek2 = "L" if h["soused_ma_lekarnu"] else " "
        print(f"     {h['km']:>5} km  {h['obec']:<20}[{lek}] -- "
              f"{h['soused']:<20}[{lek2}]")

    n = kostra_zapis(drv)
    print(f"\n  kostra uložena jako hrany :V_KOSTRE ({n} hran) — "
          f"zobraz v Browseru dotazem:")
    print("     MATCH p=()-[:V_KOSTRE]-() RETURN p")

    print(f"\n=== POČTY LÉKÁREN ZA OKRESY (průchodem grafu) ===")
    for r in pocty_lekaren_okresy(drv):
        print(f"  {r['kod']}  {r['okres']:<16} obcí {r['obci']:>4}  "
              f"lékáren {r['lekaren']:>3}  s lékárnou {r['obci_s_lekarnou']:>3}")

    print(f"\n=== TOP 10 NEJVZDÁLENĚJŠÍCH OBCÍ (Neo4j) ===")
    for r in nejblizsi_lekarna(drv):
        print(f"  {r['km']:>6} km  {r['obec']:<22} {r['okres']:<16} "
              f"-> {r['lekarna_v']}")
    drv.close()
