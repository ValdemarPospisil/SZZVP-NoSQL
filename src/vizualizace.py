"""
Vizualizace výsledků dotazů (Matplotlib).
"""

from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

import dotazy_mongo as dm

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"

# Barvy podle okresů, aby byly grafy napříč výstupy konzistentní.
BARVA_HLAVNI = "#2E86AB"
BARVA_DOPLNEK = "#A23B72"
BARVA_VYSTRAHA = "#E4572E"
BARVA_SVETLA = "#C5D5E4"


def nastav_styl():
    """Jednotný vzhled grafů; DejaVu Sans umí českou diakritiku."""
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.grid": True,
        "grid.alpha": 0.3,
        "grid.linestyle": "--",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.dpi": 110,
    })


# ---------------------------------------------------------------------------
# 1. Povinná tabulka jako graf: počty lékáren za okresy a ORP
# ---------------------------------------------------------------------------

def graf_okresy(db):
    """
    Dvojice grafů za okresy: absolutní počty a hustota na obyvatele.

    Dva panely vedle sebe, protože absolutní počty a hustota říkají různé
    věci: Most má 18 lékáren (víc než Louny s 13), ale na obyvatele je
    hůř (1,68 vs. 1,55 — a přitom Louny mají poloviční populaci).
    """
    df = pd.DataFrame(dm.pocty_okresy(db)).sort_values("lekaren")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # Levý panel: skládaný graf obcí s lékárnou a bez ní.
    y = range(len(df))
    ax1.barh(y, df["obci_s_lekarnou"], color=BARVA_HLAVNI, label="obce s lékárnou")
    ax1.barh(y, df["obci_bez_lekarny"], left=df["obci_s_lekarnou"],
             color=BARVA_SVETLA, label="obce bez lékárny")
    ax1.set_yticks(list(y))
    ax1.set_yticklabels(df["okres"])
    ax1.set_xlabel("počet obcí")
    ax1.set_title("Obce s lékárnou a bez lékárny")
    ax1.legend(loc="upper right", fontsize=9)
    ax1.set_xlim(0, df["obci"].max() * 1.22)
    # Počet lékáren jako anotace, aby šlo číst obojí z jednoho panelu.
    for i, (_, r) in enumerate(df.iterrows()):
        ax1.text(r["obci"] + 1.5, i, f"{r['lekaren']} lék.",
                 va="center", fontsize=8, color=BARVA_DOPLNEK)

    # Pravý panel: hustota na 10 tisíc obyvatel.
    prumer = df["lekaren"].sum() / df["populace"].sum() * 10000
    barvy = [BARVA_VYSTRAHA if v < prumer else BARVA_HLAVNI
             for v in df["lekaren_na_10tis"]]
    ax2.barh(list(y), df["lekaren_na_10tis"], color=barvy)
    ax2.set_yticks(list(y))
    ax2.set_yticklabels(df["okres"])
    ax2.set_xlabel("lékáren na 10 000 obyvatel")
    ax2.set_title("Hustota lékáren na obyvatele")
    ax2.axvline(prumer, color="black", linestyle=":", linewidth=1.5,
                label=f"kraj {prumer:.2f}")
    ax2.legend(loc="lower right", fontsize=9)
    for i, v in enumerate(df["lekaren_na_10tis"]):
        ax2.text(v + 0.04, i, f"{v:.2f}", va="center", fontsize=8)

    fig.suptitle("Lékárny v okresech Ústeckého kraje", fontsize=14,
                 fontweight="bold")
    fig.tight_layout()
    return fig


def graf_orp(db):
    """Počty lékáren za ORP — 16 jednotek, proto jeden vysoký panel."""
    df = pd.DataFrame(dm.pocty_orp(db)).sort_values("lekaren")

    fig, ax = plt.subplots(figsize=(10, 7))
    y = range(len(df))
    barvy = [BARVA_VYSTRAHA if r["lekaren"] <= 4 else BARVA_HLAVNI
             for _, r in df.iterrows()]
    ax.barh(list(y), df["lekaren"], color=barvy)
    ax.set_yticks(list(y))
    ax.set_yticklabels([f"{r['orp']} ({r['kod']})" for _, r in df.iterrows()])
    ax.set_xlabel("počet lékáren")
    ax.set_title("Lékárny v ORP Ústeckého kraje\n"
                 "(červeně ORP se čtyřmi a méně lékárnami)")
    for i, (_, r) in enumerate(df.iterrows()):
        ax.text(r["lekaren"] + 0.3, i,
                f"{r['lekaren']}  ·  {r['obci']} obcí, "
                f"{r['obci_s_lekarnou']} s lékárnou",
                va="center", fontsize=8)
    ax.set_xlim(0, df["lekaren"].max() * 1.45)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# 2. Hlavní úloha: vzdálenosti k nejbližší lékárně
# ---------------------------------------------------------------------------

def graf_vzdalenosti(db):
    """
    Histogram vzdáleností + deset nejvzdálenějších obcí.

    Histogram ukazuje rozdělení všech 303 obcí bez lékárny, sloupcový graf
    vpravo pojmenovává konkrétní extrémy — samotný histogram by nechal
    otázku "a které to jsou?" nezodpovězenou.
    """
    vse = pd.DataFrame(dm.vzdalenosti_vsechny(db))
    top = pd.DataFrame(dm.nejvzdalenejsi_obce(db, 10)).sort_values("km")
    s = dm.souhrn_vzdalenosti(db)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5),
                                   gridspec_kw={"width_ratios": [1, 1.15]})

    ax1.hist(vse["km"], bins=25, color=BARVA_HLAVNI, edgecolor="white")
    ax1.axvline(s["median_km"], color=BARVA_VYSTRAHA, linestyle="-",
                linewidth=2, label=f"medián {s['median_km']} km")
    ax1.axvline(s["prumer_km"], color="black", linestyle=":",
                linewidth=1.5, label=f"průměr {s['prumer_km']} km")
    ax1.set_xlabel("vzdálenost k nejbližší lékárně [km]")
    ax1.set_ylabel("počet obcí")
    ax1.set_title(f"Rozdělení vzdáleností\n{s['obci']} obcí bez lékárny")
    ax1.legend(fontsize=9)

    y = range(len(top))
    ax2.barh(list(y), top["km"], color=BARVA_VYSTRAHA)
    ax2.set_yticks(list(y))
    ax2.set_yticklabels([f"{r['obec']}\n({r['okres']})"
                         for _, r in top.iterrows()], fontsize=8)
    ax2.set_xlabel("vzdálenost k nejbližší lékárně [km]")
    ax2.set_title("Deset nejvzdálenějších obcí")
    for i, (_, r) in enumerate(top.iterrows()):
        ax2.text(r["km"] + 0.2, i,
                 f"{r['km']} km → {r['lekarna_v']}  "
                 f"({r['populace'] or '?'} obyv.)",
                 va="center", fontsize=7.5)
    ax2.set_xlim(0, top["km"].max() * 1.6)

    fig.suptitle("Dostupnost lékáren pro obce bez vlastní lékárny",
                 fontsize=14, fontweight="bold")
    fig.tight_layout()
    return fig


def graf_pustina(db):
    """
    Lékárenská pustina: osobokilometry vs. samotná vzdálenost.

    Ukazuje, že vážení populací přeskládá pořadí — Brandov je nejdál, ale
    má 249 obyvatel, zatímco Chlumec je 4 km od lékárny se 4 170 obyvateli.
    """
    df = pd.DataFrame(dm.lekarenska_pustina(db, 12)).sort_values("osobokm")

    fig, ax = plt.subplots(figsize=(11, 6))
    y = range(len(df))
    ax.barh(list(y), df["osobokm"], color=BARVA_DOPLNEK)
    ax.set_yticks(list(y))
    ax.set_yticklabels([f"{r['obec']} ({r['okres']})"
                        for _, r in df.iterrows()], fontsize=9)
    ax.set_xlabel("osobokilometry = obyvatelé × vzdálenost k lékárně")
    ax.set_title("Kde je nedostupnost lékáren nejcitelnější\n"
                 "(vážení počtem obyvatel místo samotné vzdálenosti)")
    for i, (_, r) in enumerate(df.iterrows()):
        ax.text(r["osobokm"] + 250, i,
                f"{int(r['populace'])} obyv. × {r['km']} km",
                va="center", fontsize=8)
    ax.set_xlim(0, df["osobokm"].max() * 1.35)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# 3. Mapa
# ---------------------------------------------------------------------------

def graf_mapa(db):
    """
    Mapa kraje: lékárny a obce obarvené vzdáleností k nejbližší lékárně.

    Bez podkladové mapy (žádná externí služba), ale tvar kraje je z bodů
    obcí patrný. Kdyby byla záměna [lng, lat], body by ležely mimo ČR —
    mapa je tak zároveň kontrolou správnosti souřadnic.
    """
    vzdal = pd.DataFrame(dm.vzdalenosti_vsechny(db))
    # Souřadnice nejsou ve výstupu pipeline, dotáhnou se podle kódu obce.
    souradnice = {o["_id"]: o["loc"]["coordinates"]
                  for o in db.obce.find({"loc": {"$ne": None}}, {"loc": 1})}
    vzdal["lng"] = vzdal["_id"].map(lambda k: souradnice[k][0])
    vzdal["lat"] = vzdal["_id"].map(lambda k: souradnice[k][1])

    lek = pd.DataFrame([
        {"lng": l["loc"]["coordinates"][0], "lat": l["loc"]["coordinates"][1],
         "retezec": l["retezec"], "geo_zdroj": l["geo_zdroj"]}
        for l in db.lekarny.find({"loc": {"$ne": None}},
                                 {"loc": 1, "retezec": 1, "geo_zdroj": 1})])

    s_lekarnou = pd.DataFrame([
        {"lng": o["loc"]["coordinates"][0], "lat": o["loc"]["coordinates"][1]}
        for o in db.obce.find({"ma_lekarnu": True, "loc": {"$ne": None}},
                              {"loc": 1})])

    fig, ax = plt.subplots(figsize=(13, 8))

    # Obce bez lékárny: barva = vzdálenost.
    sc = ax.scatter(vzdal["lng"], vzdal["lat"], c=vzdal["km"],
                    cmap="YlOrRd", s=45, edgecolor="gray", linewidth=0.4,
                    zorder=2, label="obec bez lékárny")
    # Obce s lékárnou: prázdné kroužky.
    ax.scatter(s_lekarnou["lng"], s_lekarnou["lat"], facecolor="none",
               edgecolor=BARVA_HLAVNI, s=110, linewidth=1.6, zorder=3,
               label="obec s lékárnou")
    # Lékárny: křížky.
    ax.scatter(lek["lng"], lek["lat"], marker="+", c="black", s=45,
               linewidth=1.1, zorder=4, label=f"lékárna ({len(lek)})")

    # Nejvzdálenější obce pojmenovat. Popisky se v Krušných horách
    # tísní na malé ploše, proto se odsazují na střídavé strany a vede
    # k nim šipka — jinak se text překryje a je nečitelný.
    nej = vzdal.nlargest(5, "km").sort_values("lng").reset_index(drop=True)
    odsazeni = [(-90, 34), (-60, -46), (16, 40), (18, -44), (60, 26)]
    for i, r in nej.iterrows():
        ax.annotate(
            f"{r['obec']} · {r['km']} km",
            (r["lng"], r["lat"]),
            textcoords="offset points", xytext=odsazeni[i % len(odsazeni)],
            fontsize=8.5, fontweight="bold", ha="center", zorder=6,
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray",
                      alpha=0.95),
            arrowprops=dict(arrowstyle="-", color="gray", linewidth=0.9,
                            shrinkA=1, shrinkB=3))

    fig.colorbar(sc, ax=ax, label="vzdálenost k nejbližší lékárně [km]",
                 shrink=0.8)
    ax.set_xlabel("zeměpisná délka [°]")
    ax.set_ylabel("zeměpisná šířka [°]")
    ax.set_title("Lékárny a dostupnost v Ústeckém kraji\n"
                 "nejvzdálenější obce leží v krušnohorském hřebeni",
                 fontsize=13, fontweight="bold")
    ax.legend(loc="upper left", fontsize=9, framealpha=0.95)
    # Stejné měřítko obou os, aby tvar kraje nebyl zdeformovaný.
    ax.set_aspect("equal", adjustable="datalim")
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# 4. Vlastní zpracování: řetězce a kostra
# ---------------------------------------------------------------------------

def graf_retezce(db):
    """Koncentrace lékárenských sítí po okresech jako skládaný graf."""
    data = dm.retezce_po_okresech(db)
    radky = []
    for r in data:
        zaznam = {"okres": r["okres"]}
        for x in r["retezce"]:
            zaznam[x["retezec"]] = x["pocet"]
        radky.append(zaznam)
    df = pd.DataFrame(radky).fillna(0).set_index("okres")
    poradi = df.sum().sort_values(ascending=False).index
    df = df[poradi].sort_values(poradi[0])

    fig, ax = plt.subplots(figsize=(11, 5.5))
    spodek = pd.Series(0.0, index=df.index)
    barvy = [BARVA_SVETLA, BARVA_HLAVNI, BARVA_DOPLNEK, BARVA_VYSTRAHA]
    for i, sit in enumerate(df.columns):
        ax.barh(df.index, df[sit], left=spodek, label=sit,
                color=barvy[i % len(barvy)])
        spodek += df[sit]
    ax.set_xlabel("počet lékáren")
    ax.set_title("Zastoupení lékárenských sítí v okresech\n"
                 "nezávislé lékárny drží 62–67 %, jen v Mostě 39 %")
    ax.legend(loc="lower right", fontsize=9)
    fig.tight_layout()
    return fig


def graf_kostra():
    """
    Minimální kostra dostupnosti z Neo4j: rozdělení délek hran.

    Doplňuje vizualizaci grafu v Neo4j Browseru číselným pohledem —
    Browser ukáže topologii, tenhle graf ukáže, že většina hran je
    krátká a extrémy jsou v horách.
    """
    import dotazy_neo4j as dn

    drv = dn.pripoj()
    try:
        dn.vytvor_projekci(drv)
        souhrn = dn.kostra_souhrn(drv)
        hrany = pd.DataFrame(dn.kostra_hrany(drv, limit=1000))
    finally:
        drv.close()

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5),
                                   gridspec_kw={"width_ratios": [1, 1.1]})

    ax1.hist(hrany["km"], bins=30, color=BARVA_HLAVNI, edgecolor="white")
    ax1.axvline(souhrn["prumer_km"], color=BARVA_VYSTRAHA, linewidth=2,
                label=f"průměr {souhrn['prumer_km']} km")
    ax1.set_xlabel("délka hrany [km]")
    ax1.set_ylabel("počet hran")
    ax1.set_title(f"Délky hran minimální kostry\n"
                  f"{souhrn['hran']} hran, celkem {souhrn['celkem_km']} km")
    ax1.legend(fontsize=9)

    top = hrany.nlargest(10, "km").sort_values("km")
    y = range(len(top))
    ax2.barh(list(y), top["km"], color=BARVA_VYSTRAHA)
    ax2.set_yticks(list(y))
    ax2.set_yticklabels([f"{r['obec']} – {r['soused']}"
                         for _, r in top.iterrows()], fontsize=8)
    ax2.set_xlabel("délka hrany [km]")
    ax2.set_title("Nejdelší hrany = kritická spojení\n"
                  "jejich ztráta rozdělí síť na dvě části")
    for i, v in enumerate(top["km"]):
        ax2.text(v + 0.1, i, f"{v} km", va="center", fontsize=8)
    ax2.set_xlim(0, top["km"].max() * 1.25)

    fig.suptitle("Minimální kostra dostupnosti (Neo4j, GDS spanningTree)",
                 fontsize=14, fontweight="bold")
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------

GRAFY = {
    "01_okresy": ("Počty lékáren za okresy", lambda db: graf_okresy(db)),
    "02_orp": ("Počty lékáren za ORP", lambda db: graf_orp(db)),
    "03_vzdalenosti": ("Vzdálenosti k nejbližší lékárně",
                       lambda db: graf_vzdalenosti(db)),
    "04_mapa": ("Mapa kraje", lambda db: graf_mapa(db)),
    "05_pustina": ("Lékárenská pustina", lambda db: graf_pustina(db)),
    "06_retezce": ("Koncentrace sítí", lambda db: graf_retezce(db)),
    "07_kostra": ("Minimální kostra", lambda db: graf_kostra()),
}


def vyrob_vse(db=None, out=OUT):
    """Vyrobí všechny grafy do PNG. Vrací seznam cest."""
    matplotlib.use("Agg")           # bez displeje, jen do souborů
    nastav_styl()
    if db is None:
        db = dm.pripoj()
    out.mkdir(exist_ok=True)
    cesty = []
    for nazev, (popis, f) in GRAFY.items():
        fig = f(db)
        cesta = out / f"{nazev}.png"
        fig.savefig(cesta, dpi=110, bbox_inches="tight")
        plt.close(fig)
        cesty.append((cesta, popis))
        print(f"   {cesta.name:<22} {popis}")
    return cesty


if __name__ == "__main__":
    print("vyrábím grafy do out/ ...")
    vyrob_vse()
    print("hotovo")
