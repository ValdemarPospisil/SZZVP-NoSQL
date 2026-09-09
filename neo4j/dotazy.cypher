// --- 1. MINIMÁLNÍ KOSTRA DOSTUPNOSTI -------------------------------------
// Celá kostra: 351 hran, 986,53 km. Hrany nesou vzdálenost v km.
MATCH p=()-[:V_KOSTRE]-() RETURN p;

// Jen kritická spojení nad 5 km — přehlednější, ukáže krušnohorský hřeben.
MATCH p=()-[r:V_KOSTRE]-() WHERE r.km > 5 RETURN p;

// Nejdelší hrany kostry jako tabulka.
MATCH (a:Obec)-[r:V_KOSTRE]-(b:Obec)
WHERE a.kod < b.kod
RETURN a.nazev AS obec, b.nazev AS soused, r.km AS km,
       a.ma_lekarnu AS obec_ma_lekarnu, b.ma_lekarnu AS soused_ma_lekarnu
ORDER BY km DESC LIMIT 15;


// --- 2. HIERARCHIE ÚZEMÍ -------------------------------------------------
// Kraj -> okresy -> ORP: celá správní struktura kraje.
MATCH p=(:Kraj)<-[:V_KRAJI]-(:Okres)<-[:V_OKRESE]-(:ORP) RETURN p;

// Jeden okres s obcemi a lékárnami.
// POZOR: tento dotaz ukáže jen obce, které lékárnu MAJÍ (3 z 26 v okrese
// Most). MATCH vyžaduje celý vzor, takže obec bez navázané lékárny vypadne
// z výsledku úplně — není to vinou LIMITu, dotaz vrací jen 18 cest.
MATCH p=(:Okres {nazev:'Most'})<-[:V_OKRESE]-(b:Obec)<-[:V_OBCI]-(:Lekarna)
RETURN p LIMIT 60;

// Správně všech 26 obcí okresu: OPTIONAL MATCH se chová jako LEFT JOIN,
// obec vrátí i bez lékárny.
MATCH p1=(:Kraj)<-[:V_KRAJI]-(o:Okres {nazev:'Most'})<-[:V_OKRESE]-(b:Obec)
OPTIONAL MATCH p2=(b)<-[:V_OBCI]-(:Lekarna)
RETURN p1, p2;

// Naopak jen obce BEZ lékárny — WHERE NOT (vzor) je negace existence.
// V okrese Most jich je 23 z 26, největší Lom s 3762 obyvateli.
MATCH p=(:Okres {nazev:'Most'})<-[:V_OKRESE]-(b:Obec)
WHERE NOT (b)<-[:V_OBCI]-(:Lekarna)
RETURN p;

// Pozor: okres NELZE odvodit průchodem přes ORP, hranice se nekryjí.
// Tento dotaz to ukáže — okres Litoměřice se dělí na 3 ORP.
MATCH (o:Okres {nazev:'Litoměřice'})<-[:V_OKRESE]-(:Obec)-[:V_ORP]->(p:ORP)
RETURN DISTINCT p.kod AS orp_kod, p.nazev AS orp;


// --- 3. POČTY LÉKÁREN (průchodem grafu, bez denormalizace) ---------------
// Za okresy.
MATCH (o:Okres)<-[:V_OKRESE]-(b:Obec)
OPTIONAL MATCH (b)<-[:V_OBCI]-(l:Lekarna)
WITH o, b, count(l) AS lek
RETURN o.kod AS kod, o.nazev AS okres, count(b) AS obci, sum(lek) AS lekaren,
       sum(CASE WHEN lek > 0 THEN 1 ELSE 0 END) AS obci_s_lekarnou,
       sum(b.populace) AS populace
ORDER BY kod;

// Za ORP.
MATCH (p:ORP)<-[:V_ORP]-(b:Obec)
OPTIONAL MATCH (b)<-[:V_OBCI]-(l:Lekarna)
WITH p, b, count(l) AS lek
RETURN p.kod AS kod, p.nazev AS orp, count(b) AS obci, sum(lek) AS lekaren,
       sum(CASE WHEN lek > 0 THEN 1 ELSE 0 END) AS obci_s_lekarnou
ORDER BY kod;

// Podle řetězců — koncentrace trhu.
MATCH (l:Lekarna)-[:V_OBCI]->(:Obec)-[:V_OKRESE]->(o:Okres)
RETURN o.nazev AS okres, l.retezec AS retezec, count(*) AS lekaren
ORDER BY okres, lekaren DESC;


// --- 4. NEJVZDÁLENĚJŠÍ OBCE OD LÉKÁRNY -----------------------------------
// Grafová obdoba mongo pipeline; používá nativní point.distance().
MATCH (b:Obec) WHERE b.ma_lekarnu = false AND b.poloha IS NOT NULL
MATCH (l:Lekarna) WHERE l.poloha IS NOT NULL
WITH b, l, point.distance(b.poloha, l.poloha)/1000 AS km
ORDER BY b.kod, km
WITH b, collect({obec: l.obec_nazev, nazev: l.nazev, km: km})[0] AS nej
MATCH (b)-[:V_OKRESE]->(o:Okres)
RETURN b.nazev AS obec, o.nazev AS okres, b.populace AS obyvatel,
       round(nej.km*100)/100 AS km, nej.obec AS lekarna_v
ORDER BY km DESC LIMIT 10;


// --- 5. OKOLÍ JEDNÉ OBCE -------------------------------------------------
// Nejvzdálenější obec kraje a její sousedé.
MATCH p=(b:Obec {nazev:'Brandov'})-[:BLIZKO]-() RETURN p;

// Cesta z Brandova k nejbližší obci s lékárnou po hranách kostry.
MATCH (a:Obec {nazev:'Brandov'}), (b:Obec {ma_lekarnu: true})
MATCH p = shortestPath((a)-[:V_KOSTRE*]-(b))
RETURN p ORDER BY length(p) LIMIT 1;
