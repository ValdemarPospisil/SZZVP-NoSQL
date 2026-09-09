# Schéma dokumentů a grafu

Stejná data jsou uložená dvakrát — dokumentově v MongoDB a grafově v Neo4j.
Není to duplikace z nerozhodnosti: každá z požadovaných úloh patří jinému
modelu a projekt to má ukázat na stejném datovém základu.

| Úloha | Model | Proč |
|---|---|---|
| vzdálenost obce k nejbližší lékárně, 10 nejvzdálenějších | dokumentový | agregace nad dokumenty s geoprostorovým indexem |
| minimální kostra dostupnosti | grafový | průchod grafem, vztah je prvotřídní objekt |
| počty lékáren za okresy a ORP | oba | slouží ke srovnání modelů |

---

## 1. MongoDB — dokumentový model

Databáze `lekarny`, dvě kolekce.

### 1.1 Kolekce `obce` (354 dokumentů)

```javascript
{
  _id: "554804",                    // kód obce ČSÚ — přirozený klíč
  nazev: "Ústí nad Labem",
  nazev_norm: "usti nad labem",     // předpočítáno pro spojování zdrojů
  status: "S",                      // H/M/O/S/T/U dle listu Komentář
  status_popis: "statutární město",

  // Územní hierarchie — VNOŘENÁ, viz rozhodnutí 2 níže
  pou:   { kod: "42142", nazev: "Ústí nad Labem" },
  orp:   { kod: "4214",  nazev: "Ústí nad Labem" },
  okres: { kod: "CZ0427", nazev: "Ústí nad Labem" },
  kraj:  { kod: "CZ042", nazev: "Ústecký kraj" },
  nuts2: { kod: "CZ04",  nazev: "Severozápad" },
  rok_listu: "1.1.2024",            // ke kterému řezu se hierarchie vztahuje

  // Geometrie z Geonames
  geonames: {
    geonameid: 3063548,
    nazev: "Ústí nad Labem",
    feature_code: "PPLA",
    kandidatu: 1                    // kolik sídel se jménem shodovalo
  },
  loc: { type: "Point", coordinates: [14.03227, 50.6607] },   // [lng, lat]!
  populace: 90378,
  vyska_m: 150,

  // Předpočítáno při načtení — viz rozhodnutí 4
  lekaren: 19,
  ma_lekarnu: true
}
```

**Indexy**

| Index | Účel |
|---|---|
| `obce_loc_2dsphere` | `$geoNear`, bez něj Mongo geodotaz odmítne |
| `obce_okres`, `obce_orp` | filtry a `$group` v agregacích |
| `obce_ma_lekarnu` | výběr 305 obcí bez lékárny |
| `obce_nazev_norm` | dohledání obce podle názvu |

### 1.2 Kolekce `lekarny` (167 dokumentů)

```javascript
{
  _id: "248001",                    // MistoPoskytovaniId, bez duplicit
  zarizeni_id: "178352",
  kod: "28511298604000",
  nazev: "ČESKÁ LÉKÁRNA HOLDING, a.s., Dr. Max Lékárna",
  druhy_zarizeni: ["Lékárna"],      // SEZNAM — u 3 lékáren je jich víc
  je_lekarna: true,

  adresa: {
    obec: "Postoloprty",
    obec_norm: "postoloprty",
    psc: "43942",
    ulice: "Mírové náměstí",
    cislo: "70"
  },

  uzemi: {
    kraj_kod: "CZ042",  kraj_nazev: "Ústecký kraj",
    okres_kod: "CZ0424", okres_nazev: "Louny",
    orp_kod: "4207", orp_nazev: "Louny"      // DENORMALIZOVÁNO z obce
  },

  lat: 50.360664, lng: 13.699670,
  loc: { type: "Point", coordinates: [13.699670, 50.360664] },
  geo_zdroj: "registr",             // "registr" = přesná adresa
                                    // "obec" = dogeokódováno na střed obce
  obec_kod: "565229",               // reference do kolekce obce
  retezec: "Dr. Max",               // odvozeno z názvu

  poskytovatel: {
    ico: "28511298",
    web: "http://www.drmax.cz",
    email: null, telefon: null,
    pravni_forma_kod: "121",
    sidlo_obec: "Brno",             // SÍDLO FIRMY, nikdy ne poloha lékárny
    sidlo_okres_kod: "CZ0642"
  },
  obor_pece: "praktické lékárenství"
}
```

**Indexy:** `lekarny_loc_2dsphere`, `lekarny_okres`, `lekarny_orp`,
`lekarny_obec`, `lekarny_retezec`.

### 1.3 Schéma validace

Obě kolekce mají `$jsonSchema` validátor (`validationAction: "error"`).
MongoDB je schemaless, ale validaci umí — připojení validátoru ukazuje, že
volba „bez pevného schématu" je rozhodnutí, ne neznalost.

Validace je záměrně mírná: povinné je jen to, na čem stojí dotazy, a `loc`
smí být `null` (dvě obce nemají záznam v Geonames). Kód okresu je omezen
vzorem `^CZ[0-9A-C]{4}$`, protože kódy jsou hexadecimální (`CZ020A`).

---

## 2. Neo4j — grafový model

### 2.1 Uzly

| Uzel | Počet | Klíč | Vlastnosti |
|---|---|---|---|
| `:Kraj` | 1 | `kod` | `nazev` |
| `:Okres` | 7 | `kod` | `nazev` |
| `:ORP` | 16 | `kod` | `nazev` |
| `:Obec` | 354 | `kod` | `nazev`, `status`, `populace`, `poloha`, `lekaren`, `ma_lekarnu` |
| `:Lekarna` | 167 | `id` | `nazev`, `popis`, `retezec`, `poloha`, `geo_zdroj`, `obec_nazev`, `ulice` |

Na každém klíči je omezení `IS UNIQUE`, které zároveň zakládá index — bez
něj by `MERGE` nad 354 obcemi procházel celý graf.

Poloha je nativní typ `point({latitude, longitude, crs:'WGS-84'})`, nad kterým
funguje `point.distance()`.

### 2.2 Hrany

```
(:Okres)   -[:V_KRAJI]->    (:Kraj)         7
(:ORP)     -[:V_OKRESE]->   (:Okres)       16 ┐ typ V_OKRESE má 370 hran
(:Obec)    -[:V_OKRESE]->   (:Okres)      354 ┘ (vychází ze dvou typů uzlů)
(:Obec)    -[:V_ORP]->      (:ORP)        354
(:Lekarna) -[:V_OBCI]->     (:Obec)       167
(:Obec)    -[:BLIZKO {km}]- (:Obec)      1266      ← graf dostupnosti
(:Obec)    -[:V_KOSTRE {km}]-(:Obec)      351      ← výsledek kostry
```

Celkem **545 uzlů** a **2 515 orientovaných hran** (neorientované `BLIZKO`
a `V_KOSTRE` se v Neo4j ukládají s jedním směrem, ale dotazují se bez ohledu
na něj).

**Proč existuje `(:Obec)-[:V_OKRESE]->(:Okres)`, když vede cesta přes ORP:**
hranice ORP a okresů se nekryjí. Okres Litoměřice se dělí na ORP Litoměřice,
Lovosice a Roudnice nad Labem, a naopak ORP může zasahovat do dvou okresů.
Okres tedy **nelze odvodit průchodem** — je to samostatný fakt ze zdroje.

**Hrany `BLIZKO`** tvoří graf dostupnosti pro kostru. Úplný graf 352 obcí by
měl 61 776 hran; omezení na **6 nejbližších sousedů** dá 1 266 hran a kostru
nezmění, dokud zůstane graf spojitý. Hrany jsou **symetrizované**: pár se
zachová, když má aspoň jeden z uzlů druhý mezi svými nejbližšími — bez toho
se graf snadno rozpadne. Spojitost se po načtení ověřuje (352 z 352 dosažitelných).

**Hrany `V_KOSTRE`** jsou zapsaný výsledek `gds.spanningTree`, aby šla kostra
zobrazit v Browseru samostatně místo všech 1 266 hran `BLIZKO`.

---

## 3. Rozhodnutí o modelu a jejich cena

### Rozhodnutí 1: dvě kolekce, ne lékárny vnořené do obcí

Nabízelo by se uložit obec s polem jejích lékáren — čte se to spolu a poměr
je 1:málo (nejvíc 19 lékáren v Ústí). **Přesto to je špatně**, a to z jednoho
technického důvodu:

`$geoNear` musí být **první stupeň agregační pipeline** a pracuje **nad
kolekcí**, ne nad vnořeným polem. Úloha „najdi nejbližší lékárnu ke středu
obce" by s vnořenými lékárnami nešla udělat vůbec.

Vedle toho: lékárny se čtou i samostatně (přehled řetězců, hustota na
obyvatele) a mění se nezávisle na obci.

### Rozhodnutí 2: hierarchie ORP/okres/kraj vnořená do obce

Tady naopak vnoření platí:

- poměr **1:málo** a čte se **vždy s obcí**
- žádná agregace za okresy nepotřebuje `$lookup`, stačí `$group`
- hierarchie se mění řádově jednou za roky

### Rozhodnutí 3: ORP denormalizované i do lékárny

Registr lékáren ORP vůbec neuvádí. Zkopírováním z obce se tabulka počtů za
ORP udělá jedním `$group` bez spojování kolekcí.

**Cena, kterou je nutné umět pojmenovat:** když ČSÚ přeřadí obec do jiného
ORP, je nutné přepsat i všechny lékárny v ní — `update_many`, ne jeden zápis.
A není to hypotetická situace: mezi lety 2013 a 2024 se to stalo **19krát**
(viz `parse_uzemi.zmeny_prislusnosti`).

### Rozhodnutí 4: předpočítané `lekaren` a `ma_lekarnu` v obci

Počet lékáren v obci se dá spočítat agregací, ale filtr „obce bez lékárny"
je vstupem hlavní úlohy a použije se opakovaně. Předpočítané pole umožní
index `obce_ma_lekarnu`.

**Cena:** hodnota je platná jen k okamžiku načtení. Kdyby lékárny přibývaly
za běhu, je nutné ji přepočítávat — v této úloze jde o statický import, takže
je to bezpečné.

### Rozhodnutí 5: `loc` jako GeoJSON, ne dvě čísla

`lat`/`lng` v lékárnách zůstávají pro čitelnost, ale dotazy používají `loc`
jako GeoJSON `Point`, protože jen nad ním funguje index `2dsphere`.

**Past:** GeoJSON má pořadí **`[longitude, latitude]`** (RFC 7946), tedy
obráceně, než jak se souřadnice běžně čtou a než je má registr ve sloupcích
`Lat`, `Lng`. Záměna nezpůsobí chybu, jen tiše přesune všechny body mimo ČR.
Mapa v notebooku slouží i jako kontrola tohoto pořadí.

---

## 4. Jak vznikly klíče a spojení

```
XLSX 1.1.2024                admin2Codes.txt              CZ.txt (class P)
354 obcí ÚK                  CZ.89.0426 = Okres Teplice   1270 sídel v ÚK
kód obce, ORP, okres (NUTS)         │                     admin2 = "0426"
      │                             │  název okresu       admin1 = "89" (FIPS)
      │                             └──────────┬──────────────┘
      │                                        │  normalizovaný název + FIPS→NUTS
      │   normalizovaný název obce + okres     │
      └────────────────────────┬───────────────┘
                               │
                        obce (354 dokumentů)
                        loc, populace, hierarchie
                               ▲
                               │  Obec + OkresCode (NUTS, shodné s ČSÚ)
                               │
                     lekarny_uk.csv (167)
```

**Autoritativní je ČSÚ** (seznam obcí a hierarchie), **Geonames dodává
geometrii**, **admin2Codes je most** mezi číselným kódem Geonames a názvem
okresu, **registr lékáren je předmět analýzy**.

Kritické místo: `admin2Codes.txt` **neobsahuje NUTS kód**, takže spojení
Geonames → ČSÚ jde výhradně přes **textový název okresu**. Proto je
normalizace názvů (`normalize.norm_okres`) nutná, ne kosmetická. Výsledek:
98 záznamů Geonames pokryje všech 77 okresů ČSÚ.

---

## 5. Odmítnuté varianty

**Jedna kolekce `misto` s příznakem typu.** Obce a lékárny by byly v jedné
kolekci s polem `typ: "obec" | "lekarna"`. Umožnilo by to jeden `$geoNear`
nad vším, ale za cenu, že každý dotaz musí filtrovat podle typu a validace
schématu by musela být sjednocením dvou nesourodých tvarů.

**Uložení všech 12 ročních řezů hierarchie.** XLSX obsahuje roky 2013–2024.
Verzování dokumentů obcí (`platnost_od`, `platnost_do`) je zajímavé
modelovací téma, ale pro zadané úlohy je zbytečné — analýza pracuje
s aktuálním stavem. Změny mezi řezy se místo toho počítají na vyžádání
(`parse_uzemi.zmeny_prislusnosti`) a jsou samostatným výstupem.

**Úplný graf vzdáleností v Neo4j.** 61 776 hran místo 1 266. Kostra by vyšla
stejně, protože Primův algoritmus stejně vybírá jen nejkratší hrany, ale
projekce do GDS a vykreslení v Browseru by byly zbytečně těžké.
