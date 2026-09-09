// ===========================================================================
// 1. DESET NEJVZDÁLENĚJŠÍCH OBCÍ BEZ LÉKÁRNY 
// kolekce: obce
// ===========================================================================
[
  { $match: { ma_lekarnu: false, loc: { $ne: null } } },
  {
    $lookup: {
      from: "lekarny",
      as: "nejblizsi",
      let: { stred: "$loc" },
      pipeline: [
        {
          $geoNear: {
            near: "$$stred",
            distanceField: "vzdalenost_m",
            spherical: true
          }
        },
        { $limit: 1 },
        {
          $project: {
            vzdalenost_m: 1, nazev: 1, retezec: 1,
            obec: "$adresa.obec"
          }
        }
      ]
    }
  },
  { $unwind: "$nejblizsi" },
  {
    $project: {
      obec: "$nazev",
      okres: "$okres.nazev",
      orp: "$orp.nazev",
      populace: 1,
      km: { $round: [{ $divide: ["$nejblizsi.vzdalenost_m", 1000] }, 2] },
      lekarna_v: "$nejblizsi.obec",
      retezec: "$nejblizsi.retezec"
    }
  },
  { $sort: { km: -1 } },
  { $limit: 10 }
]


// ===========================================================================
// 2. POČTY LÉKÁREN A OBCÍ ZA OKRESY
// kolekce: obce
// ===========================================================================
[
  {
    $group: {
      _id: "$okres.kod",
      okres: { $first: "$okres.nazev" },
      obci: { $sum: 1 },
      obci_s_lekarnou: { $sum: { $cond: ["$ma_lekarnu", 1, 0] } },
      populace: { $sum: { $ifNull: ["$populace", 0] } }
    }
  },
  {
    $lookup: {
      from: "lekarny",
      localField: "_id",
      foreignField: "uzemi.okres_kod",
      as: "lek"
    }
  },
  {
    $project: {
      _id: 0,
      kod: "$_id",
      okres: 1,
      obci: 1,
      obci_s_lekarnou: 1,
      obci_bez_lekarny: { $subtract: ["$obci", "$obci_s_lekarnou"] },
      lekaren: { $size: "$lek" },
      populace: 1,
      lekaren_na_10tis: {
        $round: [{
          $multiply: [
            { $divide: [{ $size: "$lek" }, "$populace"] }, 10000]
        }, 2]
      }
    }
  },
  { $sort: { kod: 1 } }
]


// ===========================================================================
// 3. POČTY LÉKÁREN A OBCÍ ZA ORP  (povinná tabulka)
// kolekce: obce
// ===========================================================================
[
  {
    $group: {
      _id: "$orp.kod",
      orp: { $first: "$orp.nazev" },
      obci: { $sum: 1 },
      obci_s_lekarnou: { $sum: { $cond: ["$ma_lekarnu", 1, 0] } },
      populace: { $sum: { $ifNull: ["$populace", 0] } }
    }
  },
  {
    $lookup: {
      from: "lekarny",
      localField: "_id",
      foreignField: "uzemi.orp_kod",
      as: "lek"
    }
  },
  {
    $project: {
      _id: 0,
      kod: "$_id",
      orp: 1,
      obci: 1,
      obci_s_lekarnou: 1,
      obci_bez_lekarny: { $subtract: ["$obci", "$obci_s_lekarnou"] },
      lekaren: { $size: "$lek" },
      lekaren_na_10tis: {
        $round: [{
          $multiply: [
            { $divide: [{ $size: "$lek" }, "$populace"] }, 10000]
        }, 2]
      }
    }
  },
  { $sort: { kod: 1 } }
]


// ===========================================================================
// 4. SOUHRN VZDÁLENOSTÍ  (medián přes $percentile, Mongo 7+)
// kolekce: obce
// ===========================================================================
[
  { $match: { ma_lekarnu: false, loc: { $ne: null } } },
  {
    $lookup: {
      from: "lekarny", as: "n", let: { stred: "$loc" },
      pipeline: [
        { $geoNear: { near: "$$stred", distanceField: "d", spherical: true } },
        { $limit: 1 }
      ]
    }
  },
  { $unwind: "$n" },
  { $addFields: { km: { $round: [{ $divide: ["$n.d", 1000] }, 2] } } },
  {
    $group: {
      _id: null,
      obci: { $sum: 1 },
      prumer_km: { $avg: "$km" },
      min_km: { $min: "$km" },
      max_km: { $max: "$km" },
      median_km: {
        $percentile: {
          input: "$km", p: [0.5],
          method: "approximate"
        }
      },
      obci_nad_5km: { $sum: { $cond: [{ $gt: ["$km", 5] }, 1, 0] } },
      obci_nad_10km: { $sum: { $cond: [{ $gt: ["$km", 10] }, 1, 0] } },
      obyvatel_nad_5km: {
        $sum: {
          $cond: [{ $gt: ["$km", 5] },
          { $ifNull: ["$populace", 0] }, 0]
        }
      }
    }
  },
  {
    $project: {
      _id: 0, obci: 1, obci_nad_5km: 1, obci_nad_10km: 1, obyvatel_nad_5km: 1,
      min_km: 1, max_km: 1,
      prumer_km: { $round: ["$prumer_km", 2] },
      median_km: { $round: [{ $first: "$median_km" }, 2] }
    }
  }
]


// ===========================================================================
// 5. LÉKÁRENSKÁ PUSTINA: obyvatelé x vzdálenost  (vlastní zpracování)
// kolekce: obce
// ===========================================================================
// Samotná vzdálenost neříká, kolika lidí se problém týká — Brandov je
// nejdál (14,98 km), ale má 249 obyvatel. Součin dává osobokilometry.
[
  { $match: { ma_lekarnu: false, loc: { $ne: null }, populace: { $ne: null } } },
  {
    $lookup: {
      from: "lekarny", as: "n", let: { stred: "$loc" },
      pipeline: [
        { $geoNear: { near: "$$stred", distanceField: "d", spherical: true } },
        { $limit: 1 },
        { $project: { d: 1, obec: "$adresa.obec" } }
      ]
    }
  },
  { $unwind: "$n" },
  {
    $project: {
      _id: 0,
      obec: "$nazev",
      okres: "$okres.nazev",
      populace: 1,
      km: { $round: [{ $divide: ["$n.d", 1000] }, 2] },
      osobokm: {
        $round: [{
          $multiply: [
            "$populace", { $divide: ["$n.d", 1000] }]
        }, 0]
      },
      lekarna_v: "$n.obec"
    }
  },
  { $sort: { osobokm: -1 } },
  { $limit: 10 }
]


// ===========================================================================
// 6. KONCENTRACE ŘETĚZCŮ PO OKRESECH  (vlastní zpracování)
// kolekce: lekarny
// ===========================================================================
// Dvoustupňový pivot: první $group po (okres, řetězec), druhý sbalí
// řádek na okres a spočítá podíl největšího hráče.
[
  {
    $group: {
      _id: { okres: "$uzemi.okres_nazev", retezec: "$retezec" },
      pocet: { $sum: 1 }
    }
  },
  {
    $group: {
      _id: "$_id.okres",
      celkem: { $sum: "$pocet" },
      retezce: { $push: { retezec: "$_id.retezec", pocet: "$pocet" } }
    }
  },
  {
    $project: {
      _id: 0,
      okres: "$_id",
      celkem: 1,
      retezce: { $sortArray: { input: "$retezce", sortBy: { pocet: -1 } } },
      nejvetsi_podil: {
        $round: [{
          $multiply: [
            { $divide: [{ $max: "$retezce.pocet" }, "$celkem"] }, 100]
        }, 1]
      }
    }
  },
  { $sort: { celkem: -1 } }
]


// ===========================================================================
// 7. NEJVYŠŠÍ HUSTOTA LÉKÁREN NA OBYVATELE  (vlastní zpracování)
// kolekce: obce
// ===========================================================================
// Pozor na interpretaci: vítěz Hřensko má 1 lékárnu na 247 obyvatel
// (40,5/10 tis.), což je turistika u Pravčické brány, ne péče o místní.
// Poměrový ukazatel na malém základu je nutné umět přečíst.
[
  { $match: { lekaren: { $gt: 0 }, populace: { $ne: null } } },
  {
    $project: {
      _id: 0,
      obec: "$nazev",
      okres: "$okres.nazev",
      status: "$status_popis",
      lekaren: 1,
      populace: 1,
      na_10tis: {
        $round: [{
          $multiply: [
            { $divide: ["$lekaren", "$populace"] }, 10000]
        }, 2]
      }
    }
  },
  { $sort: { na_10tis: -1 } },
  { $limit: 10 }
]


// ===========================================================================
// 8. KVALITA GEOKÓDOVÁNÍ
// kolekce: lekarny
// ===========================================================================
// 164 lékáren má přesnou adresu z registru, 3 jen střed obce
// (Louny, Lovosice, Ústí nad Labem) — ovlivňuje to spolehlivost vzdáleností.
[
  {
    $group: {
      _id: "$geo_zdroj",
      pocet: { $sum: 1 },
      obce: { $addToSet: "$adresa.obec" }
    }
  },
  { $sort: { pocet: -1 } }
]