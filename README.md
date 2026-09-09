# Lékárny v Ústeckém kraji — NoSQL analýza

Řešení úlohy okruhu **NoSQL databáze** (SZZVP, Aplikovaná informatika UJEP).

Tři veřejné datové zdroje se spojí do dokumentové databáze (MongoDB) a
grafové databáze (Neo4j), nad nimiž se řeší dostupnost lékáren v Ústeckém
kraji.

## Zadání a co ho plní

| Požadavek | Řešení |
|---|---|
| návrh schématu dokumentů / uzlů a hran | [`docs/schema.md`](docs/schema.md) |
| skript pro zpracování zdrojů, včetně nekonzistencí | `src/parse_*.py`, `src/build.py`, `src/normalize.py` |
| návrh a implementace dotazů | `src/dotazy_mongo.py`, `src/dotazy_neo4j.py` |
| tabulka počtů lékáren v okresech a ORP | `dotazy_mongo.pocty_okresy()`, `pocty_orp()` |
| **neo4j:** minimální kostra dostupnosti | `dotazy_neo4j.kostra_souhrn()` — 351 hran, 986,53 km |
| **mongo:** vzdálenost obcí od nejbližší lékárny, 10 nejvzdálenějších | `dotazy_mongo.nejvzdalenejsi_obce()` — max 14,98 km (Brandov) |
| vlastní zpracování | 4 analýzy, viz [níže](#vlastní-zpracování) |
| kód s dokumentací | docstringy v každém modulu, [`notebooks/analyza.ipynb`](notebooks/analyza.ipynb) |

## Rychlý start

```bash
docker compose up -d                                   # MongoDB, Neo4j, mongo-express
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

PYTHONPATH=src .venv/bin/python src/kontrola.py        # co je ve zdrojových datech
PYTHONPATH=src .venv/bin/python src/load_mongo.py      # naplní MongoDB
PYTHONPATH=src .venv/bin/python src/load_neo4j.py      # naplní Neo4j
PYTHONPATH=src .venv/bin/python src/dotazy_mongo.py    # dotazy nad MongoDB
PYTHONPATH=src .venv/bin/python src/dotazy_neo4j.py    # dotazy + kostra
PYTHONPATH=src .venv/bin/python src/vizualizace.py     # grafy do out/

.venv/bin/jupyter lab notebooks/analyza.ipynb          # vše pohromadě s výkladem
```

Načítací skripty jsou **idempotentní** — kolekce i graf se před zápisem
vyprázdní, takže se dají spustit opakovaně.

### Kde se na data podívat

| Rozhraní | Adresa | K čemu |
|---|---|---|
| Neo4j Browser | <http://localhost:7474> | **kostra nakreslená jako graf**, hierarchie |
| mongo-express | <http://localhost:8081> | prohlížení dokumentů |
| MongoDB Compass | (desktop) | `Schema` → mapa lékáren, `Aggregations` s náhledem po stupních |

Pro Neo4j Browser přetáhni do okna [`neo4j/style.grass`](neo4j/style.grass) —
uzly pak nesou názvy místo kódů a hrany kostry vzdálenost v km. Připravené
dotazy jsou v [`neo4j/dotazy.cypher`](neo4j/dotazy.cypher), pipeline pro
Compass v [`mongo/pipelines.js`](mongo/pipelines.js).

## Struktura projektu

```
src/normalize.py        normalizace názvů, FIPS→NUTS, aliasy okresů
src/parse_uzemi.py      XLSX ČSÚ — autoritativní hierarchie + změny 2013→2024
src/parse_geonames.py   CZ.txt + admin2Codes — geometrie, řešení dvojznačností
src/parse_lekarny.py    registr NRPZS
src/build.py            spojení zdrojů → finální dokumenty + report
src/load_mongo.py       kolekce, 2dsphere indexy, $jsonSchema validace
src/load_neo4j.py       uzly, hrany, kNN graf dostupnosti
src/dotazy_mongo.py     agregační pipeline
src/dotazy_neo4j.py     Cypher + GDS spanningTree
src/vizualizace.py      grafy z výstupů dotazů (Matplotlib)
src/kontrola.py         kontrolní výpis zdrojových dat s kontrolními součty
```

---

## Proč NoSQL, a kdy by byl lepší SQL

Zadání okruhu vyžaduje zdůvodnění volby. Poctivá odpověď má dvě části.

### Co v této úloze mluví pro NoSQL

**1. Geoprostorové dotazy jsou tu hlavní operací.** MongoDB má index
`2dsphere` a stupeň `$geoNear` jako součást agregační pipeline. Hlavní úloha
— „najdi nejbližší lékárnu ke středu každé z 303 obcí" — je jeden dotaz.
V PostgreSQL by to šlo taky, ale **jen s rozšířením PostGIS**; čisté SQL
geoprostorový index nemá. Srovnání tedy není „SQL vs. NoSQL", ale
„MongoDB vs. PostgreSQL + PostGIS".

**2. Grafová úloha nemá v relačním modelu dobré řešení.** Minimální kostra
je průchod grafem, ne agregace. V SQL by to znamenalo rekurzivní CTE a ruční
implementaci Primova algoritmu; v Neo4j je to `gds.spanningTree` nad
projekcí. Tady je rozdíl podstatný, ne kosmetický.

**3. Zdroje mají nestejné a nepravidelné atributy.** Registr lékáren má 33
sloupců, z nichž je `SpravniObvod` prázdný u všech řádků a `PoskytovatelFax`
téměř všude. Geonames má 19 polí s různou hustotou vyplnění. Dokumentový
model dovolí uložit, co ve zdroji je, a chybějící vynechat — v relačním
schématu by vznikly tabulky s většinou `NULL` sloupců.

**4. Vnořená hierarchie se čte vždy celá.** Obec → POÚ → ORP → okres → kraj
→ NUTS 2 se v dotazech používá pohromadě. Vnořený podobjekt to vyřeší bez
spojování; relačně by to bylo pět tabulek a čtyři `JOIN` na každý dotaz.

### Co by mluvilo pro SQL

Kdyby se úloha posunula, relační databáze by vyhrála:

- **Data jsou malá a mají pevnou strukturu.** 354 obcí a 167 lékáren se
  vejde do jedné stránky paměti; kolekce mají 201 kB a 134 kB. NoSQL se
  vyplácí u objemů, kde je horizontální dělení nutné — tady o žádné nejde.
- **Referenční integrita je tu ručně.** Že `lekarny.obec_kod` odkazuje na
  existující obec, garantuje jen načítací skript. Cizí klíč v PostgreSQL by
  to vynutil databází.
- **Denormalizace se musí udržovat kódem.** ORP zkopírované do lékárny je
  v Mongu správný vzor, ale při přeřazení obce vyžaduje `update_many`.
  Relačně by to byl `JOIN`, který je vždy aktuální.
- **Analytické dotazy nad více úrovněmi.** Kdyby přišly časové řady lékáren
  po měsících a dotazy typu „meziroční změna počtu po ORP", je to
  učebnicová úloha pro SQL s okenními funkcemi — v agregační pipeline by
  byla podstatně méně čitelná.

### Závěr

Pro **tuto** úlohu je volba NoSQL věcně odůvodněná dvěma důvody: geoprostorové
operace v pipeline a grafový algoritmus, který relační model neumí přirozeně.
Ostatní důvody (schéma, vnořování) jsou příjemné, ale samy by volbu
neopravňovaly — při 500 dokumentech by PostgreSQL s JSONB sloupcem a PostGIS
posloužil stejně dobře a přidal integritu.

Neupřímné by bylo tvrdit, že úloha vyžaduje NoSQL kvůli objemu dat. Nevyžaduje.

---

## Výhody a nevýhody zvoleného řešení

### Výhody

- **Každá úloha běží v modelu, který jí odpovídá** — geodotazy dokumentově,
  kostra grafově. Načítací skript je společný (`build.py`), takže druhá
  databáze stála ~30 % práce navíc.
- **Křížová validace.** Deset nejvzdálenějších obcí spočítané nezávisle
  Mongem (`$geoNear`) a Neo4j (`point.distance()`) vyšlo shodně na dvě
  desetinná místa. Kdyby byla chyba v souřadnicích nebo v pořadí `lat`/`lng`,
  výsledky by se rozešly.
- **Kvalita dat zůstává v datech.** Příznak `geo_zdroj` říká, které tři
  lékárny mají jen přibližnou polohu; `geonames.kandidatu` říká, u kterých
  obcí se rozhodovalo mezi víc sídly. Nic z toho není zamlčené.
- **Ověřitelnost.** `src/kontrola.py` vypíše, co skripty ze zdrojů načetly,
  včetně kontrolních součtů. Notebook obsahuje důkaz použití indexu
  (`GEO_NEAR_2DSPHERE`) a důkaz funkční validace schématu.

### Nevýhody

- **Dvě databáze znamenají dvě kopie dat.** Nic je nedrží v konzistenci —
  po změně zdroje je nutné spustit oba loadery. V produkci by to byl
  problém; tady jde o statický import.
- **Referenční integrita není vynucená.** Viz výše.
- **Denormalizace ORP vyžaduje `update_many`** při přeřazení obce.
- **Graf `BLIZKO` je aproximace.** Omezení na 6 nejbližších sousedů drží
  počet hran v tisících, ale je to volba, která by při jiném kraji mohla
  vést k nespojitému grafu. Skript proto spojitost ověřuje a upozorní.
- **Vzdálenosti jsou vzdušnou čarou.** Pro Krušné hory je to podhodnocení —
  Brandov má do Jirkova 14,98 km vzdušnou čarou, po silnici podstatně víc.
  Řešením by bylo routovací API, což je mimo rozsah úlohy.
- **Dvě obce zůstaly bez souřadnic.** Líšťany a Nezabylice nemají záznam
  v Geonames, takže vypadly z geodotazů (303 z 305 obcí bez lékárny).

---

## Řešené nekonzistence

Tři zdroje používají tři nekompatibilní kódové systémy a jediné spolehlivé
pojivo je název.

| Zdroj | Kraj | Okres |
|---|---|---|
| ČSÚ (XLSX, registr NRPZS) | `CZ042` (NUTS 3) | `CZ0426` (LAU 1) |
| Geonames | `89` (**FIPS**) | `0426` |
| admin2Codes | — | `CZ.89.0426`, **bez NUTS** |

| Nekonzistence | Rozsah | Řešení |
|---|---|---|
| FIPS vs. NUTS u kraje | všechna sídla | převodní tabulka `FIPS_TO_NUTS3` |
| `admin2Codes` nemá NUTS kód | 98 řádků | spojení přes normalizovaný **název** → 77/77 okresů |
| Diakritika mezi zdroji | — | `norm()` přes NFKD |
| Praha dělená na 22 částí | 22 | sjednoceno na `CZ0100`; Praha-východ (`CZ0209`) a -západ (`CZ020A`) zůstaly zvlášť |
| `Město Brno` vs. `Brno-město` | 1 | alias |
| Lékárny bez souřadnic | 3 | dogeokódování na střed obce + příznak `geo_zdroj` |
| Duplicitní názvy obcí | 6 v ÚK | rozhodnutí podle okresu a populace, deterministicky |
| Slepený `DruhZarizeni` | 3 | parsováno na seznam |
| **Sídlo firmy ≠ poloha lékárny** | **91 ze 167** | sloupce `*Sidlo` se nikdy nepoužijí jako poloha |
| Obce bez záznamu v Geonames | 2 | `loc: null`, vyloučeny z geodotazů |
| Geonames má 4× víc sídel než obcí | 1 270 vs. 354 | autoritativní je ČSÚ, Geonames jen geometrie |

**Dvě pasti, které stojí za zapamatování:**

- Kódy okresů jsou **hexadecimální** (`0209, 020A, 020B, 020C`) — nikdy
  neparsovat jako `int`.
- Kdyby se geokódovalo podle sloupců `*Sidlo`, skončilo by 41 lékáren
  v Brně a 25 v Praze, protože to je sídlo Dr. Max a BENU.

---

## Hlavní výsledky

### Dostupnost lékáren (MongoDB)

Pro 303 obcí bez vlastní lékárny se známou polohou:

```
min 0,4 km │ medián 4,82 km │ průměr 4,99 km │ max 14,98 km
140 obcí je dál než 5 km, 12 obcí dál než 10 km
66 788 obyvatel žije dál než 5 km od lékárny
```

Nejvzdálenější: **Brandov 14,98 km**, Domoušice 14,05 km, Pnětluky 12,29 km.
V první desítce je **šest obcí okresu Louny** (13 lékáren na 70 obcí).

### Minimální kostra dostupnosti (Neo4j)

```
351 hran (352 uzlů → strom má n−1) │ celkem 986,53 km │ průměr 2,81 km
```

Tři nejdelší hrany leží v **Krušných horách** (Český Jiřetín–Klíny 7,7 km,
Kalek–Boleboř 7,69 km, Kryštofovy Hamry–Vejprty 7,4 km) — jsou to kritická
spojení, jejichž ztráta rozdělí síť. Hory se objevují jako překážka v obou
analýzách nezávisle.

### Vlastní zpracování

**1. Lékárenská pustina** — vážení vzdálenosti počtem obyvatel přeskládá
pořadí: Brandov je nejdál (14,98 km), ale má 249 obyvatel. Nejcitelnější
je **Peruc** (2 109 obyvatel × 9,09 km) a **Chlumec** (4 170 × 4,06 km).
Kdyby kraj řešil, kde otevřít lékárnu, samotná vzdálenost by ho poslala
ke 249 lidem.

**2. Koncentrace sítí** — nezávislé lékárny drží **62–67 %** ve všech
okresech kromě **Mostu, kde je trh rozdělený téměř na třetiny** (39 / 33 / 28 %).
Proti běžné představě, že sítě trh ovládly.

**3. Hustota na obyvatele** — ukazuje past poměrových ukazatelů na malém
základu: vítěz **Hřensko** má 40,5 lékáren na 10 tis. obyvatel, ale je to
turistické středisko u Pravčické brány. Věcně smysluplné jsou až
**Lovosice** (6,86) proti **Mostu** (1,9), tedy 3,6× rozdíl.

**4. Změny územní struktury 2013→2024** — 19 obcí změnilo ORP nebo okres,
6 obcí vzniklo zrušením vojenských újezdů (kódy `5001xx`), obec **Brdy**
zanikla. Územní příslušnost tedy **není v čase stabilní**, proto každý
dokument nese `rok_listu`.

---

## Zdroje dat

| Soubor | Obsah | Poskytovatel |
|---|---|---|
| `lekarny_uk.csv` | 167 lékáren v ÚK | NRPZS (Národní registr poskytovatelů zdravotních služeb) |
| `0043_Struktura uzemi CR 1.1.2013 - 1.1.2024.xlsx` | hierarchie obcí ČR, 13 listů | ČSÚ |
| `CZ/CZ.txt` | 43 264 geografických objektů ČR | Geonames |
| `admin2Codes.txt` | kódy okresů (celosvětové, 98 CZ) | Geonames |

Data jsou součástí repozitáře, aby šlo řešení spustit bez stahování.

## Prostředí

MongoDB 8.3, Neo4j 5.26 s pluginem Graph Data Science 2.13, Python 3.14.
Verze v `requirements.txt` nejsou připnuté — Python 3.14 je nový a starší
vydání `pandas`/`matplotlib` pro něj nemají předkompilované wheels. Přesné
rozpuštěné verze jsou v `requirements-lock.txt`.
