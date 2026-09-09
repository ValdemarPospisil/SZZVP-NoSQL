"""
Naplnění MongoDB: kolekce, indexy, schéma validace, zápis dokumentů.

Zvolené schéma — dvě kolekce, ne jedna:

    obce     dokument = obec (354), uvnitř vnořená hierarchie ORP/okres/kraj
             + GeoJSON Point středu + populace + počet lékáren
    lekarny  dokument = lékárna (167), uvnitř vnořená adresa a územní
             příslušnost + GeoJSON Point + řetězec

Proč zvlášť, a ne lékárny vnořené do obcí:
  - $geoNear musí být PRVNÍ stupeň pipeline a pracuje nad kolekcí, ne nad
    vnořeným polem. Úloha "nejbližší lékárna k obci" by se s vnořenými
    lékárnami dělat nedala.
  - lékárny se čtou i samostatně (přehled řetězců, hustota na obyvatele)
  - obec i lékárna se mění nezávisle na sobě

Proč naopak hierarchie ORP/okres/kraj JE vnořená:
  - poměr 1:málo a čte se vždy s obcí
  - žádná agregace za okresy nepotřebuje $lookup, stačí $group

Vědomá denormalizace: ORP a názvy okresů jsou zkopírované i do lékáren.
Cena za to je popsaná v build.postav_lekarny.
"""

import sys

from pymongo import ASCENDING, GEOSPHERE, MongoClient

from build import postav_vse

MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "lekarny"

# Validační schéma kolekce obce. Mongo je schemaless, ale $jsonSchema umí
# kontrolovat zápisy — ukazuje, že volba "bez schématu" je rozhodnutí,
# ne neznalost. Validace je záměrně mírná: povinné je jen to, na čem stojí
# dotazy, a loc smí být null (2 obce bez záznamu v Geonames).
SCHEMA_OBCE = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["_id", "nazev", "okres", "orp", "kraj", "lekaren"],
        "properties": {
            "_id": {"bsonType": "string", "description": "kód obce ČSÚ"},
            "nazev": {"bsonType": "string"},
            "status": {"enum": ["H", "M", "O", "S", "T", "U"]},
            "okres": {
                "bsonType": "object",
                "required": ["kod", "nazev"],
                "properties": {"kod": {"bsonType": "string", "pattern": "^CZ[0-9A-C]{4}$"}},
            },
            "orp": {"bsonType": "object", "required": ["kod", "nazev"]},
            "loc": {
                "oneOf": [
                    {"bsonType": "null"},
                    {
                        "bsonType": "object",
                        "required": ["type", "coordinates"],
                        "properties": {
                            "type": {"enum": ["Point"]},
                            "coordinates": {
                                "bsonType": "array",
                                "minItems": 2,
                                "maxItems": 2,
                                "items": {"bsonType": "double"},
                            },
                        },
                    },
                ]
            },
            "populace": {"bsonType": ["int", "null"], "minimum": 0},
            "lekaren": {"bsonType": "int", "minimum": 0},
        },
    }
}

SCHEMA_LEKARNY = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["_id", "nazev", "uzemi", "loc"],
        "properties": {
            "_id": {"bsonType": "string", "description": "MistoPoskytovaniId"},
            "nazev": {"bsonType": "string"},
            "druhy_zarizeni": {"bsonType": "array", "items": {"bsonType": "string"}},
            # geo_zdroj drží informaci o kvalitě polohy: "registr" = přesná
            # adresa, "obec" = dogeokódováno na střed obce.
            "geo_zdroj": {"enum": ["registr", "obec", None]},
            "obec_kod": {"bsonType": ["string", "null"]},
            "loc": {
                "oneOf": [
                    {"bsonType": "null"},
                    {"bsonType": "object", "required": ["type", "coordinates"]},
                ]
            },
        },
    }
}


def vytvor_kolekci(db, nazev, schema):
    """
    Vytvoří kolekci s validačním schématem; existující zahodí.

    validationLevel="moderate" a validationAction="error": neplatný zápis
    se odmítne, ale případné starší dokumenty se nekontrolují.
    """
    if nazev in db.list_collection_names():
        db[nazev].drop()
    db.create_collection(nazev, validator=schema,
                         validationLevel="moderate", validationAction="error")
    return db[nazev]


def naplnit(uri=MONGO_URI, db_name=DB_NAME):
    """Postaví dokumenty, vytvoří kolekce s indexy a zapíše je."""
    obce, lekarny, report = postav_vse()

    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")          # ověří spojení hned, ne až u zápisu
    db = client[db_name]

    col_obce = vytvor_kolekci(db, "obce", SCHEMA_OBCE)
    col_lek = vytvor_kolekci(db, "lekarny", SCHEMA_LEKARNY)

    # insert_many po dávkách, ne dokument po dokumentu — jeden round-trip
    # na server místo stovek.
    col_obce.insert_many(obce, ordered=False)
    col_lek.insert_many(lekarny, ordered=False)

    # Indexy. 2dsphere je nutný pro $geoNear a $near; bez něj Mongo
    # geodotaz odmítne. Ostatní jsou pro filtry v agregacích.
    col_obce.create_index([("loc", GEOSPHERE)], name="obce_loc_2dsphere")
    col_obce.create_index([("okres.kod", ASCENDING)], name="obce_okres")
    col_obce.create_index([("orp.kod", ASCENDING)], name="obce_orp")
    col_obce.create_index([("ma_lekarnu", ASCENDING)], name="obce_ma_lekarnu")
    col_obce.create_index([("nazev_norm", ASCENDING)], name="obce_nazev_norm")

    col_lek.create_index([("loc", GEOSPHERE)], name="lekarny_loc_2dsphere")
    col_lek.create_index([("uzemi.okres_kod", ASCENDING)], name="lekarny_okres")
    col_lek.create_index([("uzemi.orp_kod", ASCENDING)], name="lekarny_orp")
    col_lek.create_index([("obec_kod", ASCENDING)], name="lekarny_obec")
    col_lek.create_index([("retezec", ASCENDING)], name="lekarny_retezec")

    return db, report


def overit(db):
    """
    Ověří, co se skutečně zapsalo — čte z databáze, ne z paměti.

    Kontrola musí jít do databáze; kdyby zápis částečně selhal, počty
    v Pythonu by o tom nevěděly.
    """
    obce, lek = db["obce"], db["lekarny"]
    return {
        "obci": obce.count_documents({}),
        "obci_s_loc": obce.count_documents({"loc": {"$ne": None}}),
        "obci_bez_loc": obce.count_documents({"loc": None}),
        "obci_s_lekarnou": obce.count_documents({"ma_lekarnu": True}),
        "obci_bez_lekarny": obce.count_documents({"ma_lekarnu": False}),
        "obci_s_populaci": obce.count_documents({"populace": {"$ne": None}}),
        "lekaren": lek.count_documents({}),
        "lekaren_s_loc": lek.count_documents({"loc": {"$ne": None}}),
        "lekaren_z_registru": lek.count_documents({"geo_zdroj": "registr"}),
        "lekaren_dogeokodovanych": lek.count_documents({"geo_zdroj": "obec"}),
        "lekaren_napojenych": lek.count_documents({"obec_kod": {"$ne": None}}),
        "indexy_obce": sorted(obce.index_information()),
        "indexy_lekarny": sorted(lek.index_information()),
    }


if __name__ == "__main__":
    db, report = naplnit()
    stav = overit(db)

    print("=" * 70)
    print(f"  MongoDB: databáze '{DB_NAME}' naplněna")
    print("=" * 70)
    print(f"  obce:     {stav['obci']:>4} dokumentů  "
          f"(se souřadnicemi {stav['obci_s_loc']}, bez {stav['obci_bez_loc']})")
    print(f"            s lékárnou {stav['obci_s_lekarnou']}, "
          f"bez lékárny {stav['obci_bez_lekarny']}, "
          f"s populací {stav['obci_s_populaci']}")
    print(f"  lekarny:  {stav['lekaren']:>4} dokumentů  "
          f"(z registru {stav['lekaren_z_registru']}, "
          f"dogeokódováno {stav['lekaren_dogeokodovanych']})")
    print(f"            napojeno na obec {stav['lekaren_napojenych']}")

    print(f"\n  indexy obce:    {', '.join(stav['indexy_obce'])}")
    print(f"  indexy lekarny: {', '.join(stav['indexy_lekarny'])}")

    # Kontrola, že validační schéma skutečně funguje — pokus o vadný zápis.
    print("\n  test validace ($jsonSchema):")
    try:
        db["obce"].insert_one({"_id": "TEST", "nazev": "Vadná obec"})
        print("     CHYBA: vadný dokument prošel!")
    except Exception as e:
        print(f"     OK, zápis bez povinných polí odmítnut "
              f"({type(e).__name__})")

    print(f"\n  Prohlédni si data: http://localhost:8081  -> databáze '{DB_NAME}'")
