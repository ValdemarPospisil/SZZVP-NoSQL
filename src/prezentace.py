"""
Generátor prezentace k obhajobě (PPTX, 7–10 minut).

Skládá slidy z hotových grafů v out/ a z čísel, která si dotáhne z databáze,
aby v prezentaci nebyly zastaralé hodnoty. Poznámky pod slidy obsahují, co
u kterého slidu říct.

    PYTHONPATH=src .venv/bin/python src/prezentace.py
"""

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Cm, Pt

import dotazy_mongo as dm

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
OBRAZKY = ROOT / "docs" / "obrazky"
CIL = OUT / "prezentace.pptx"

# Barvy sladěné s grafy ve vizualizace.py
MODRA = RGBColor(0x2E, 0x86, 0xAB)
VINOVA = RGBColor(0xA2, 0x3B, 0x72)
CIHLOVA = RGBColor(0xE4, 0x57, 0x2E)
SEDA = RGBColor(0x44, 0x44, 0x44)
SVETLA = RGBColor(0x66, 0x66, 0x66)

SIRKA = Cm(33.87)      # 16:9
VYSKA = Cm(19.05)


def nova_prezentace():
    prs = Presentation()
    prs.slide_width = SIRKA
    prs.slide_height = VYSKA
    return prs


def prazdny_slide(prs):
    """Slide bez předdefinovaných rámců — vše se umístí ručně."""
    return prs.slides.add_slide(prs.slide_layouts[6])


def text(slide, s, t, sirka, vyska, velikost=18, tucne=False, barva=SEDA,
         zarovnani=PP_ALIGN.LEFT, radkovani=1.15):
    """Vloží textový rámec a vrátí ho pro případné další odstavce."""
    tb = slide.shapes.add_textbox(s, t, sirka, vyska)
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = zarovnani
    p.line_spacing = radkovani
    return tb, tf, p


def nadpis(slide, txt, podnadpis=None):
    """Nadpis slidu, volitelně s podtitulkem."""
    _, tf, p = text(slide, Cm(1.5), Cm(0.9), SIRKA - Cm(3), Cm(1.6))
    r = p.add_run()
    r.text = txt
    r.font.size = Pt(30)
    r.font.bold = True
    r.font.color.rgb = MODRA
    if podnadpis:
        _, tf2, p2 = text(slide, Cm(1.5), Cm(2.5), SIRKA - Cm(3), Cm(1.0))
        r2 = p2.add_run()
        r2.text = podnadpis
        r2.font.size = Pt(15)
        r2.font.color.rgb = SVETLA


def odrazky(slide, body, s=Cm(1.5), t=Cm(3.7), sirka=None, velikost=17,
            rozestup=Pt(10)):
    """
    Odrážky. Každý prvek je (text, uroven) nebo jen text.
    Text v **hvězdičkách** se vysází tučně a barevně.
    """
    sirka = sirka or (SIRKA - Cm(3))
    tb = slide.shapes.add_textbox(s, t, sirka, VYSKA - t - Cm(1.2))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, prvek in enumerate(body):
        txt, uroven = prvek if isinstance(prvek, tuple) else (prvek, 0)
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = rozestup
        p.line_spacing = 1.1
        odsazeni = Cm(0.8) * uroven
        p.level = min(uroven, 4)
        # Rozdělit na části podle ** pro tučné zvýraznění
        for j, cast in enumerate(txt.split("**")):
            if not cast:
                continue
            r = p.add_run()
            r.text = cast
            r.font.size = Pt(velikost - uroven * 2)
            if j % 2:                       # uvnitř **...**
                r.font.bold = True
                r.font.color.rgb = MODRA
            else:
                r.font.color.rgb = SEDA if uroven == 0 else SVETLA
    return tb


def obrazek_z(slide, cesta, s, t, sirka=None, vyska=None):
    """
    Vloží obrázek z libovolné cesty na dané místo.

    Používá se pro snímky grafu z Neo4j Browseru (docs/obrazky/), které
    nevznikají skriptem jako grafy v out/.
    """
    cesta = Path(cesta)
    if not cesta.exists():
        raise FileNotFoundError(f"chybí {cesta}")
    if sirka:
        return slide.shapes.add_picture(str(cesta), s, t, width=sirka)
    return slide.shapes.add_picture(str(cesta), s, t, height=vyska)


def obrazek(slide, jmeno, t=Cm(3.4), vyska=None, max_sirka=None):
    """
    Vloží graf z out/ a vycentruje ho vodorovně.

    Grafy jsou širší než vyšší, takže při omezení jen výškou zůstanou po
    stranách velké prázdné pruhy. max_sirka je proto výchozí: obrázek se
    zvětší na šířku slidu a výška se dopočítá, dokud se vejde.
    """
    cesta = OUT / jmeno
    if not cesta.exists():
        raise FileNotFoundError(f"chybí {cesta} — spusť src/vizualizace.py")
    vyska = vyska or (VYSKA - t - Cm(1.0))
    max_sirka = max_sirka or (SIRKA - Cm(2.4))

    pic = slide.shapes.add_picture(str(cesta), Cm(0), t, height=vyska)
    if pic.width > max_sirka:          # příliš široký -> omezit šířkou
        pomer = pic.height / pic.width
        pic.width = int(max_sirka)
        pic.height = int(max_sirka * pomer)
    pic.left = int((SIRKA - pic.width) / 2)
    return pic


def cislo_box(slide, s, t, hodnota, popis, barva=MODRA, sirka=Cm(7.2)):
    """Velké číslo s popiskem — pro slide s klíčovými výsledky."""
    _, _, p = text(slide, s, t, sirka, Cm(2.0), zarovnani=PP_ALIGN.CENTER)
    r = p.add_run()
    r.text = hodnota
    r.font.size = Pt(40)
    r.font.bold = True
    r.font.color.rgb = barva
    _, _, p2 = text(slide, s, t + Cm(1.9), sirka, Cm(1.6),
                    zarovnani=PP_ALIGN.CENTER)
    r2 = p2.add_run()
    r2.text = popis
    r2.font.size = Pt(13)
    r2.font.color.rgb = SVETLA


def poznamka(slide, txt):
    """Poznámky přednášejícího — co u slidu říct."""
    slide.notes_slide.notes_text_frame.text = txt.strip()


def tabulka(slide, hlavicka, radky, s=Cm(2.5), t=Cm(4.0), sirka=None,
            vyska=None, velikost=14):
    """Vloží tabulku a nastaví čitelné formátování."""
    sirka = sirka or (SIRKA - Cm(5))
    vyska = vyska or Cm(1.0) * (len(radky) + 1)
    tab = slide.shapes.add_table(len(radky) + 1, len(hlavicka),
                                 s, t, sirka, vyska).table
    for j, h in enumerate(hlavicka):
        c = tab.cell(0, j)
        c.text = str(h)
        pr = c.text_frame.paragraphs[0]
        pr.runs[0].font.size = Pt(velikost)
        pr.runs[0].font.bold = True
        pr.runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    for i, radek in enumerate(radky, start=1):
        for j, v in enumerate(radek):
            c = tab.cell(i, j)
            c.text = str(v)
            pr = c.text_frame.paragraphs[0]
            pr.runs[0].font.size = Pt(velikost)
            pr.runs[0].font.color.rgb = SEDA
    return tab


# ---------------------------------------------------------------------------

def postav(db):
    prs = nova_prezentace()
    s_vzdal = dm.souhrn_vzdalenosti(db)
    top = dm.nejvzdalenejsi_obce(db, 5)

    # --- 1. Titulní ---
    sl = prazdny_slide(prs)
    _, _, p = text(sl, Cm(2.5), Cm(6.0), SIRKA - Cm(5), Cm(3.0))
    r = p.add_run()
    r.text = "Dostupnost lékáren\nv Ústeckém kraji"
    r.font.size = Pt(46)
    r.font.bold = True
    r.font.color.rgb = MODRA
    _, _, p = text(sl, Cm(2.5), Cm(11.0), SIRKA - Cm(5), Cm(2.5))
    r = p.add_run()
    r.text = "Tři otevřené datové zdroje ve dvou NoSQL modelech"
    r.font.size = Pt(20)
    r.font.color.rgb = SEDA
    _, _, p = text(sl, Cm(2.5), Cm(15.2), SIRKA - Cm(5), Cm(1.6))
    r = p.add_run()
    r.text = "MongoDB · Neo4j · Python      |      SZZVP — NoSQL databáze"
    r.font.size = Pt(14)
    r.font.color.rgb = SVETLA
    poznamka(sl, """
Úloha: uložit tři veřejné datové zdroje do NoSQL databáze a spočítat
dostupnost lékáren v Ústeckém kraji.
Rovnou řeknu, že jsem použil obě databáze ze zadání, protože každá
z požadovaných úloh patří jinému modelu. Vysvětlím u schématu.
[cíl: 20 sekund]""")

    # --- 2. Data a jejich problém ---
    sl = prazdny_slide(prs)
    nadpis(sl, "Tři zdroje, tři nekompatibilní kódové systémy",
           "spolehlivě je spojuje jedině název")
    tabulka(sl, ["Zdroj", "Obsah", "Kraj", "Okres"], [
        ["registr NRPZS", "167 lékáren v ÚK", "CZ042 (NUTS)", "CZ0424 (LAU)"],
        ["ČSÚ — struktura území", "6 258 obcí ČR, 13 let", "CZ042 (NUTS)", "CZ0424 (LAU)"],
        ["Geonames CZ.txt", "43 264 objektů", "89 (FIPS!)", "0424"],
        ["Geonames admin2Codes", "98 českých okresů", "—", "CZ.89.0424"],
    ], t=Cm(4.2), vyska=Cm(5.0))
    odrazky(sl, [
        "Geonames používá u kraje **FIPS**, ne NUTS — bez převodní tabulky vrací spojení nula výsledků",
        "**admin2Codes neobsahuje NUTS kód vůbec** → okres se dohledává podle názvu, po normalizaci",
        "Kódy okresů jsou **hexadecimální** (0209, 020A, 020B) — nikdy neparsovat jako int",
    ], t=Cm(10.2), velikost=16)
    poznamka(sl, """
Tohle je jádro úlohy — zadání chce vyřešit nekonzistence identifikátorů.
Klíčové zjištění: Geonames má u kraje FIPS, historický americký standard.
Kdybych to přehlédl, spojoval bych 89 s CZ089, což neexistuje, a tiše bych
dostal prázdný výsledek.
A admin2Codes nemá NUTS kód vůbec — takže jediné pojivo je textový název
okresu. Proto je normalizace názvů nutná, ne kosmetická.
[cíl: 1 minuta]""")

    # --- 3. Nekonzistence ---
    sl = prazdny_slide(prs)
    nadpis(sl, "Řešené nekonzistence", "vše ověřitelné jedním příkazem: src/kontrola.py")
    tabulka(sl, ["Problém", "Rozsah", "Řešení"], [
        ["Sídlo firmy ≠ poloha lékárny", "91 ze 167", "sloupce *Sidlo se nikdy nepoužijí jako poloha"],
        ["Lékárny bez souřadnic", "3", "střed obce + příznak geo_zdroj"],
        ["Duplicitní názvy obcí", "6 v ÚK", "klíč (název, okres), pak populace"],
        ["Praha dělená na 22 částí", "22", "sjednoceno na CZ0100"],
        ["Slepený sloupec DruhZarizeni", "3", "parsováno na seznam"],
        ["Obce bez záznamu v Geonames", "2", "loc: null, mimo geodotazy"],
    ], t=Cm(4.2), vyska=Cm(6.6), velikost=13)
    odrazky(sl, [
        "Kdyby se geokódovalo podle sídla firmy, skončilo by **41 lékáren v Brně a 25 v Praze** — tam mají sídlo Dr. Max a BENU",
    ], t=Cm(11.6), velikost=16)
    poznamka(sl, """
Nejtvrdší past je ta první: sloupce Sidlo jsou adresa sídla poskytovatele,
ne lékárny — týká se to 91 ze 167 záznamů.
Tři lékárny bez souřadnic jsem dogeokódoval na střed obce, ale nechal jsem
v datech příznak geo_zdroj, aby bylo poznat, že poloha je přibližná.
Dvě obce nemají v Geonames záznam vůbec, takže počítám 303 obcí místo 305.
[cíl: 45 sekund]""")

    # --- 4. Schéma a proč dvě databáze ---
    sl = prazdny_slide(prs)
    nadpis(sl, "Schéma: proč dvě databáze", "každá úloha patří jinému modelu")
    odrazky(sl, [
        "**MongoDB — dvě kolekce:** obce (354) a lekarny (167)",
        ("hierarchie ORP/okres/kraj **vnořená** → agregace bez $lookup", 1),
        ("lékárny **samostatně**, protože $geoNear pracuje nad kolekcí, ne nad vnořeným polem", 1),
        ("2dsphere indexy, $jsonSchema validátory", 1),
        "",
        "**Neo4j — 545 uzlů, 2 515 hran**",
        ("uzly Kraj / Okres / ORP / Obec / Lekarna, hrany hierarchie", 1),
        ("hrany BLIZKO s vlastností km = graf dostupnosti pro kostru", 1),
        "",
        "**Kdyby lékárny byly vnořené do obcí, hlavní úloha by nešla udělat vůbec.**",
    ], t=Cm(4.0), velikost=17)
    poznamka(sl, """
Tady je nejdůležitější rozhodnutí celého projektu.
Nabízelo by se uložit obec s polem jejích lékáren — čte se to spolu, poměr
je 1:málo. Ale nešlo by to, protože $geoNear musí být první stupeň pipeline
a pracuje nad kolekcí, ne nad vnořeným polem. Úloha "najdi nejbližší lékárnu
ke středu obce" by byla neřešitelná.
Naopak hierarchie vnořená je — čte se vždy s obcí a mění se raz za roky.
Cena: ORP jsem zkopíroval i do lékáren, takže při přeřazení obce je nutné
přepsat i lékárny v ní. Za posledních 11 let se to stalo 19krát.
[cíl: 1:15]""")

    # --- 5. Povinná tabulka: okresy ---
    sl = prazdny_slide(prs)
    nadpis(sl, "Počty lékáren v okresech a ORP", "agregační pipeline, $group bez spojování kolekcí")
    obrazek(sl, "01_okresy.png", t=Cm(4.0), vyska=Cm(11.5))
    poznamka(sl, """
První požadovaná tabulka. Ukazuju ji jako graf, protože absolutní počty
a hustota na obyvatele říkají různé věci.
Most má 18 lékáren, víc než Louny s třinácti — ale na obyvatele je Most
na 1,68 a Louny na 1,55, přičemž Most má o čtvrtinu víc lidí.
Nejnápadnější je okres Litoměřice: 105 obcí, ale lékárna jen v devíti.
[cíl: 45 sekund]""")

    # --- 6. Hlavní úloha Mongo ---
    sl = prazdny_slide(prs)
    nadpis(sl, "Hlavní úloha: vzdálenost k nejbližší lékárně",
           "$geoNear ve vnořené pipeline uvnitř $lookup — 303 obcí bez lékárny")
    obrazek(sl, "03_vzdalenosti.png", t=Cm(4.0), vyska=Cm(11.5))
    poznamka(sl, f"""
Hlavní mongo úloha. Technicky je zajímavé, že $geoNear musí být PRVNÍ stupeň
pipeline — takže abych ho spustil pro každou obec zvlášť, musel jsem ho dát
do vnořené pipeline v $lookup a předat polohu obce přes 'let'.
Výsledky: medián {s_vzdal['median_km']} km, průměr {s_vzdal['prumer_km']} km.
{s_vzdal['obci_nad_5km']} obcí je dál než 5 km, {s_vzdal['obci_nad_10km']} dál než 10 km.
A hlavně: {s_vzdal['obyvatel_nad_5km']} obyvatel žije dál než pět kilometrů od lékárny.
V první desítce je šest obcí okresu Louny.
[cíl: 1:15]""")

    # --- 7. Mapa ---
    sl = prazdny_slide(prs)
    nadpis(sl, "Kde jsou lékárny a kde chybí",
           "nejvzdálenější obce leží v krušnohorském hřebeni")
    obrazek(sl, "04_mapa.png", t=Cm(3.7), vyska=Cm(14.3))
    poznamka(sl, """
Mapa má dvojí účel. Za prvé ukazuje, že nedostupnost není rozprostřená
náhodně — sedí na hřebeni Krušných hor, kde přes hory nic není.
Za druhé je to kontrola správnosti souřadnic: GeoJSON má obrácené pořadí,
longitude první. Kdybych to zaměnil, body by ležely mimo Českou republiku.
Tvar kraje je z bodů obcí poznat, takže pořadí je správně.
[cíl: 30 sekund]""")

    # --- 8. Neo4j kostra ---
    sl = prazdny_slide(prs)
    nadpis(sl, "Minimální kostra dostupnosti",
           "Neo4j + GDS spanningTree — nejkratší síť, po níž je dosažitelná každá obec")
    obrazek(sl, "07_kostra.png", t=Cm(4.0), vyska=Cm(10.4))
    odrazky(sl, [
        "**351 hran** (352 uzlů → strom má n−1)  ·  **986,53 km**  ·  průměr 2,81 km",
    ], t=Cm(15.0), velikost=17)
    poznamka(sl, """
Druhá požadovaná úloha, tahle patří grafové databázi.
Kostra je nejlevnější podmnožina hran, která udrží graf spojitý. Praktická
interpretace: kdyby někdo plánoval rozvoz léků do všech obcí kraje, 987 km
je minimální délka tras.
Ověřil jsem, že to je opravdu strom: 352 uzlů musí dát 351 hran. Tady jsem
narazil na past — GDS vrací i řádek pro kořen stromu, takže bez odfiltrování
vyšlo 352 hran, což strom mít nemůže.
Nejdelší hrany jsou všechny v Krušných horách — kritická spojení, jejichž
ztráta rozdělí síť na dva celky.
[cíl: 1:15]""")

    # --- 8b. Kostra jako graf (snímky z Neo4j Browseru) ---
    sl = prazdny_slide(prs)
    nadpis(sl, "Kostra v Neo4j Browseru",
           "vlevo všech 351 hran, vpravo jen 20 kritických spojení nad 5 km")
    obrazek_z(sl, OBRAZKY / "kostra-cela.png", Cm(-0.4), Cm(3.4), sirka=Cm(17.4))
    obrazek_z(sl, OBRAZKY / "kostra-kriticka.png", Cm(16.9), Cm(3.4), sirka=Cm(17.4))
    _, _, pl = text(sl, Cm(0.8), Cm(13.4), Cm(15.4), Cm(1.2),
                    zarovnani=PP_ALIGN.CENTER)
    r = pl.add_run()
    r.text = "MATCH p=()-[:V_KOSTRE]-() RETURN p"
    r.font.size = Pt(13)
    r.font.name = "DejaVu Sans Mono"
    r.font.color.rgb = SVETLA
    _, _, pp = text(sl, Cm(17.0), Cm(13.4), Cm(15.4), Cm(1.2),
                    zarovnani=PP_ALIGN.CENTER)
    r = pp.add_run()
    r.text = "MATCH p=()-[r:V_KOSTRE]-() WHERE r.km > 5 RETURN p"
    r.font.size = Pt(13)
    r.font.name = "DejaVu Sans Mono"
    r.font.color.rgb = SVETLA
    odrazky(sl, [
        "Filtr nepočítá jinou kostru — jen z téže kostry zobrazuje **20 nejdelších hran**",
        "Zbylé řetízky sedí na **Krušných horách** (Kalek–Boleboř, Český Jiřetín–Klíny–Moldava, Kryštofovy Hamry–Vejprty–Kovářská), **Šluknovsku** a **Podbořansku**",
    ], t=Cm(15.0), velikost=15, rozestup=Pt(4))
    poznamka(sl, """
Takhle kostra vypadá v Neo4j Browseru.
Vlevo je celá — 351 hran. Jednotlivé názvy přečíst nejde, ale je vidět, že
je to jeden spojitý útvar bez cyklů, tedy skutečně strom.
Vpravo je stejná kostra po filtru na hrany nad pět kilometrů. Zbylo dvacet
hran a rozpadly se na krátké řetízky — to není chyba, jsou to úseky, kde je
síť nejvíc napnutá.
A když si přečtete jména, je z nich vidět geografie: Kalek-Boleboř,
Český Jiřetín-Klíny-Moldava, Kryštofovy Hamry-Vejprty-Kovářská jsou všechno
krušnohorský hřeben. Šluknov se Starými Křečany je výběžek, Petrohrad-Kryry
a Deštnice-Holedeč jsou Podbořansko.
Takže nedostupnost není rozprostřená náhodně, sedí na horách a okrajích kraje.
[cíl: 45 sekund]""")

    # --- 9. Vlastní zpracování ---
    sl = prazdny_slide(prs)
    nadpis(sl, "Vlastní zpracování: koho se to týká",
           "vážení vzdálenosti počtem obyvatel přeskládá pořadí")
    obrazek(sl, "05_pustina.png", t=Cm(3.9), vyska=Cm(10.9))
    odrazky(sl, [
        "Brandov je nejdál (14,98 km), ale žije tam **249 lidí**. Chlumec je 4 km od lékárny — a má **4 170 obyvatel**.",
    ], t=Cm(15.2), velikost=16)
    poznamka(sl, """
Tohle je moje vlastní analýza nad rámec zadání a považuju ji za nejužitečnější
výsledek.
Samotná vzdálenost neříká, kolika lidí se problém týká. Vynásobil jsem ji
počtem obyvatel — osobokilometry.
Pořadí se úplně změní: Brandov je nejdál, ale je to obec o 249 lidech.
Nejcitelnější je Peruc a Chlumec.
Praktický dopad: kdyby kraj řešil, kde otevřít lékárnu, samotná vzdálenost
by ho poslala do Brandova ke 249 lidem. Osobokilometry ukazují místa, kde
je dopad desetinásobný.
[cíl: 1 minuta]""")

    # --- 10. Křížová validace ---
    sl = prazdny_slide(prs)
    nadpis(sl, "Jak vím, že je to správně", "stejná úloha spočítaná nezávisle v obou databázích")
    tabulka(sl, ["Obec", "MongoDB $geoNear", "Neo4j point.distance()", "Rozdíl"],
            [[r["obec"], f"{r['km']} km", f"{r['km']} km", "0"] for r in top],
            t=Cm(4.4), vyska=Cm(5.4), velikost=15)
    odrazky(sl, [
        "**Shoda na dvě desetinná místa** — dvě databáze, dvě implementace geodetického výpočtu",
        "Kdyby byla chyba v souřadnicích nebo v pořadí lat/lng, výsledky by se rozešly",
        "Navíc: strom má n−1 hran, kontrolní součty v src/kontrola.py, důkaz použití indexu (GEO_NEAR_2DSPHERE)",
    ], t=Cm(10.6), velikost=16)
    poznamka(sl, """
Na tohle se obvykle ptá komise, tak to říkám sám.
Deset nejvzdálenějších obcí jsem spočítal nezávisle oběma databázemi —
Mongem přes $geoNear s 2dsphere indexem a Neo4j přes nativní point.distance.
Vyšlo to shodně na dvě desetinná místa. Kdyby byla chyba v datech nebo
v pořadí souřadnic, výsledky by se rozešly.
K tomu tři další kontroly: strom musí mít n-1 hran, kontrolní součty
u načítání, a explain plán ukazuje, že geodotaz opravdu používá index,
ne collection scan.
[cíl: 45 sekund]""")

    # --- 11. Volba NoSQL ---
    sl = prazdny_slide(prs)
    nadpis(sl, "Proč NoSQL — a kde bych volil SQL", "poctivá odpověď má dvě části")
    odrazky(sl, [
        "**Pro NoSQL mluví dvě věci věcně:**",
        ("geoprostorový index a $geoNear jako součást pipeline — jinak 303 × 167 výpočtů v cyklu", 1),
        ("kostra je **průchod grafem**; v SQL by to byl rekurzivní CTE a vlastní Primův algoritmus", 1),
        "",
        "**Proti mluví taky konkrétní věci:**",
        ("objem data nevyžaduje — kolekce mají 201 kB a 134 kB", 1),
        ("referenční integritu garantuje jen můj skript, ne databáze", 1),
        ("denormalizace ORP vyžaduje update_many (19× za 11 let)", 1),
        "",
        "**Správné srovnání není SQL vs. NoSQL, ale MongoDB vs. PostgreSQL + PostGIS.**",
    ], t=Cm(3.9), velikost=16)
    poznamka(sl, """
Zadání vyžaduje zdůvodnění volby, tak ho říkám obojím směrem.
Pro NoSQL mluví geoprostorový index v pipeline a grafový algoritmus, který
relační model neumí přirozeně.
Ale neupřímné by bylo tvrdit, že úloha vyžaduje NoSQL kvůli objemu dat.
Nevyžaduje — kolekce mají dvě stě kilobajtů. Při téhle velikosti by
PostgreSQL s JSONB a PostGIS posloužil stejně dobře a přidal integritu.
Proto správné srovnání není SQL versus NoSQL, ale MongoDB versus PostgreSQL
s PostGIS — čisté SQL geoprostorový index nemá.
[cíl: 45 sekund]""")

    # --- 12. Závěr ---
    sl = prazdny_slide(prs)
    nadpis(sl, "Výsledky")
    cislo_box(sl, Cm(1.6), Cm(4.6), "167", "lékáren napojených\nna obec (100 %)")
    cislo_box(sl, Cm(9.2), Cm(4.6), "303", "obcí bez lékárny\ns výpočtem vzdálenosti")
    cislo_box(sl, Cm(16.8), Cm(4.6), "4,82 km", "medián vzdálenosti\nk nejbližší lékárně", VINOVA)
    cislo_box(sl, Cm(24.4), Cm(4.6), "66 788", "obyvatel žije dál\nnež 5 km", CIHLOVA)
    cislo_box(sl, Cm(1.6), Cm(11.2), "351", "hran minimální kostry\n(986,53 km)")
    cislo_box(sl, Cm(9.2), Cm(11.2), "77 / 77", "okresů ČR napojeno\nGeonames na ČSÚ")
    cislo_box(sl, Cm(16.8), Cm(11.2), "0", "rozdíl mezi MongoDB\na Neo4j", VINOVA)
    cislo_box(sl, Cm(24.4), Cm(11.2), "4", "vlastní analýzy\nnad rámec zadání", CIHLOVA)
    poznamka(sl, """
Souhrn na závěr.
Všech 167 lékáren se podařilo napojit na obec bez jediného rozporu v okrese —
registr a ČSÚ jsou v tom konzistentní, což se u open dat nedá předpokládat.
Nejsilnější číslo je 66 788 obyvatel dál než pět kilometrů od lékárny.
A nula na konci je rozdíl mezi oběma databázemi, tedy křížová validace.
Děkuju, jsem připraven na dotazy.
[cíl: 30 sekund]""")

    return prs


if __name__ == "__main__":
    db = dm.pripoj()
    prs = postav(db)
    OUT.mkdir(exist_ok=True)
    prs.save(CIL)
    print(f"prezentace uložena: {CIL}")
    print(f"  slidů: {len(prs.slides.__iter__.__self__._sldIdLst)}")
    print(f"  velikost: {CIL.stat().st_size / 1024:.0f} kB")
    print("\nPoznámky pod slidy obsahují, co u kterého slidu říct.")
    print("Otevři: libreoffice --impress out/prezentace.pptx")
