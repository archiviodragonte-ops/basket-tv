#!/usr/bin/env python3
# Basket TV - updater
#
# Aggiorna data.json usando fonti ufficiali:
#   - LBA: calendario HTML ufficiale
#   - LNP A2: PDF calendario ufficiale
#   - LNP B Nazionale: PDF ufficiali girone A/B
#
# Nota: se una fonte non è leggibile, lo script NON cancella i dati già presenti
# e NON inventa partite.

import json
import re
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin

DATA = Path("data.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BasketTV/1.0; +https://github.com/archiviodragone-ops/basket-tv)"
}

LBA_URL = "https://www.legabasket.it/calendario"
A2_PAGE = "https://www.legapallacanestro.com/il-calendario-della-serie-a2-old-wild-west-202627"
A2_PDF = "https://static.legapallacanestro.com/sites/default/files/editor/calendario_serie_a2_oww_2026-27.pdf"
B_PAGE = "https://www.legapallacanestro.com/i-calendari-della-serie-b-nazionale-old-wild-west-202627"
B_A_PDF = "https://static.legapallacanestro.com/sites/default/files/editor/calendario_b_naz._gir._a_2026-27.pdf"
B_B_PDF = "https://static.legapallacanestro.com/sites/default/files/editor/calendario_b_naz._gir._b_2026-27.pdf"

EUROLEAGUE_URL = "https://www.euroleaguebasketball.net/euroleague/"
EUROCUP_URL = "https://www.euroleaguebasketball.net/eurocup/"

def ensure_import(module, package=None):
    try:
        return __import__(module)
    except ImportError:
        pkg = package or module
        print(f"Installo {pkg}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pkg])
        return __import__(module)

requests = ensure_import("requests")
bs4 = ensure_import("bs4", "beautifulsoup4")
BeautifulSoup = bs4.BeautifulSoup
pypdf = ensure_import("pypdf")
PdfReader = pypdf.PdfReader

def clean(s):
    s = s or ""
    s = s.replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()

def iso_date(day, month, year):
    try:
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    except Exception:
        return None

def parse_date(text):
    text = clean(text)
    # 26/09/2026, 26-09-2026, 26.09.2026
    m = re.search(r"\b(\d{1,2})[./-](\d{1,2})[./-](2026|2027)\b", text)
    if m:
        return iso_date(*m.groups())
    # ISO date
    m = re.search(r"\b(2026|2027)-(\d{1,2})-(\d{1,2})\b", text)
    if m:
        y, mo, d = m.groups()
        return iso_date(d, mo, y)
    return None

def parse_time(text):
    m = re.search(r"\b([01]?\d|2[0-3])[:.][0-5]\d\b", clean(text))
    return m.group(0).replace(".", ":") if m else ""

def make_game(date, time, home, away, comp, label, watch="", source=""):
    home, away = clean(home), clean(away)
    if not date or not home or not away:
        return None
    # Scarta righe palesemente non sportive.
    bad = ("casa", "ospite", "home", "away", "squadra di casa", "squadra ospite")
    if home.lower() in bad or away.lower() in bad:
        return None
    return {
        "date": date,
        "time": time or "",
        "home": home,
        "away": away,
        "competition": comp,
        "competition_label": label,
        "watch": watch or "Programmazione TV da definire",
        "source": source or label,
    }

def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=45)
    r.raise_for_status()
    return r

def parse_lba():
    """Legge le gare visibili nella pagina calendario LBA."""
    r = fetch(LBA_URL)
    soup = BeautifulSoup(r.text, "html.parser")
    games = []

    # Primo tentativo: tabelle.
    for tr in soup.select("tr"):
        cells = [clean(x.get_text(" ", strip=True)) for x in tr.select("th,td")]
        joined = " | ".join(cells)
        date = parse_date(joined)
        if not date:
            continue
        time = parse_time(joined)
        # Le righe LBA possono avere casa e ospite in celle distinte.
        if len(cells) >= 3:
            candidates = []
            for c in cells:
                if c and not parse_date(c) and not parse_time(c):
                    candidates.append(c)
            if len(candidates) >= 2:
                home, away = candidates[0], candidates[1]
                g = make_game(date, time, home, away, "LBA", "LBA Serie A",
                               "LBA TV", "LBA")
                if g:
                    # Cerca i nomi delle emittenti nella riga.
                    low = joined.lower()
                    tv = []
                    if "skysportbasket" in low or "sky sport" in low:
                        tv.append("Sky Sport")
                    if "cielo" in low:
                        tv.append("Cielo")
                    if "dazn" in low:
                        tv.append("DAZN")
                    if "lbatv" in low or "lba tv" in low:
                        tv.append("LBA TV")
                    g["watch"] = " · ".join(dict.fromkeys(tv)) or "LBA TV"
                    games.append(g)

    # Secondo tentativo: testo della pagina, per strutture non tabellari.
    if not games:
        text = clean(soup.get_text(" ", strip=True))
        # pattern molto prudente: data + ora + due nomi prima della prossima data
        date_re = re.compile(
            r"(\d{2}/\d{2}/202[67])\s*(?:Ore\s*)?(\d{1,2}:\d{2})"
            r"(.*?)(?=\d{2}/\d{2}/202[67]|$)", re.I
        )
        for m in date_re.finditer(text):
            date = parse_date(m.group(1))
            time = m.group(2)
            block = clean(m.group(3))
            # Il sito LBA attuale presenta "Casa-Ospite".
            pair = re.search(r"([A-Za-zÀ-ÿ0-9'’().& -]{2,80})\s*[-–—]\s*([A-Za-zÀ-ÿ0-9'’().& -]{2,80})", block)
            if pair:
                g = make_game(date, time, pair.group(1), pair.group(2),
                              "LBA", "LBA Serie A", "LBA TV", "LBA")
                if g:
                    low = block.lower()
                    tv = []
                    if "skysportbasket" in low or "sky sport" in low:
                        tv.append("Sky Sport")
                    if "cielo" in low:
                        tv.append("Cielo")
                    if "dazn" in low:
                        tv.append("DAZN")
                    if "lbatv" in low or "lba tv" in low:
                        tv.append("LBA TV")
                    g["watch"] = " · ".join(dict.fromkeys(tv)) or "LBA TV"
                    games.append(g)

    return dedupe(games)

def pdf_text(url):
    r = fetch(url)
    tmp = Path("_basket_tv_tmp.pdf")
    tmp.write_bytes(r.content)
    try:
        reader = PdfReader(str(tmp))
        pages = []
        for p in reader.pages:
            pages.append(p.extract_text() or "")
        return "\n".join(pages)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass

A2_TEAMS = [
    "Halley Campania Avellino Basket","Flats Service Fortitudo Bologna",
    "Valtur Brindisi","Paperdi Juvecaserta 2021","ProValue Juvecaserta 2021","Juvecaserta 2021","Sella Cento",
    "UEB Gesteco Cividale","Ferraroni Juvi Cremona 1952","Unieuro Forlì",
    "Libertas Livorno 1947","Gemini Mestre","Wegreenit Urania Milano",
    "La T Tecnica Gema Montecatini","CMT Orange Tools Pesaro","Victoria Libertas Pesaro",
    "Lumos Pistoia Basket","RSR Sebastiani Rieti","Dole Basket Rimini",
    "Crifo Wines Ruvo di Puglia","Banco di Sardegna Sassari",
    "Reale Mutua Torino","ELAchem Vigevano 1955"
]

B_A_TEAMS = [
    "Moncada Energy Agrigento","A2A Leonessa Brescia","Infodrive Capo d'Orlando",
    "Rimadesio Desio","Adamant Ferrara","Fiorenzuola Bees","Andrea Costa Imola",
    "SAE Scientifica-Soevis Legnano Knights","Luxarm Lumezzane",
    "Paffoni Fulgor Basket Omegna","Logiman Orzinuovi","UCC Assigeco Piacenza",
    "Siaz Basket Piazza Armerina","Pallacanestro Viola Reggio Calabria","Redel Reggio Calabria",
    "LTC Group Sangiorgese Basket","Rucker San Vendemiano",
    "TAV Treviglio Brianza Basket","S4 Energia Vicenza"
]

B_B_TEAMS = [
    "Felice Scandone Avellino","Umana San Giobbe Chiusi","Ristopro Fabriano",
    "Tema Sinergie Faenza","Benacquista Assicurazioni Latina","Pielle Livorno",
    "Basketball Club Lucca","FABO Herons Montecatini","PSA Napoli Est",
    "Consultinvest Loreto Pesaro","Solbat Golfo Piombino",
    "Consorzio Leonardo Dany Quarrata","OraSì Ravenna","Luiss Roma",
    "Virtus GVM Roma 1960","Liofilchem Roseto",
    "Allianz Pazienza Cestistica San Severo","Mens Sana Basketball Siena"
]

def _find_two_teams(segment, teams):
    """Trova due squadre note nel segmento, rispettando la loro posizione."""
    found = []
    low = segment.casefold()
    for team in teams:
        pos = low.find(team.casefold())
        if pos >= 0:
            found.append((pos, team))
    found.sort(key=lambda x: x[0])
    # elimina eventuali sovrapposizioni duplicate
    out=[]
    for pos,team in found:
        if not any(abs(pos-p2) < max(len(team),len(t2)) and team.casefold()==t2.casefold()
                   for p2,t2 in out):
            out.append((pos,team))
    return [x[1] for x in out[:2]]

def parse_lnp_pdf(url, comp, label, teams):
    """Parser per i PDF LNP 2026/27: i PDF espongono data + due nomi squadra
    separati da spazi, non da un trattino. Usa l'elenco ufficiale delle squadre
    per dividere correttamente Casa e Ospite."""
    text = pdf_text(url).replace("\r", "\n")
    # Ogni data apre un nuovo record. Questo gestisce anche righe concatenate
    # dal parser PDF (es. "... Knights6 01/11/2026 Adamant ...").
    matches = list(re.finditer(r"\b\d{1,2}[./-]\d{1,2}[./-](?:2026|2027)\b", text))
    games=[]
    for idx,m in enumerate(matches):
        date=parse_date(m.group(0))
        if not date:
            continue
        end = matches[idx+1].start() if idx+1 < len(matches) else len(text)
        segment = clean(text[m.end():end])
        pair=_find_two_teams(segment, teams)
        if len(pair)!=2:
            continue
        time=parse_time(segment)
        g=make_game(date,time,pair[0],pair[1],comp,label,"LNP Pass","LNP")
        if g:
            games.append(g)
    return dedupe(games)


def parse_lnp_news_schedule():
    """Arricchisce A2/B con gli orari pubblicati negli articoli ufficiali LNP.
    Non sostituisce il calendario PDF: aggiorna soltanto le gare per cui LNP
    ha pubblicato giorno e ora in un articolo/preview/risultati.
    """
    games=[]
    index_urls=[]
    for page in range(1, 7):
        index_urls.append("https://www.legapallacanestro.com/?did=NS5ob3RsaW5r&field_area_articolo_value=lnp_news&lnp_news_filter=All&page=%d" % page)
    article_urls=[]
    for url in index_urls:
        try:
            r=fetch(url); soup=BeautifulSoup(r.text,"html.parser")
            for a in soup.find_all("a", href=True):
                href=urljoin(url,a.get("href"))
                txt=clean(a.get_text(" ",strip=True))
                key=(txt+" "+href).lower()
                if ("serie-a2" in key or "serie-b-nazionale" in key) and "202627" in key:
                    if href.startswith("https://www.legapallacanestro.com/"):
                        article_urls.append(href)
        except Exception as e:
            print("LNP news index:",type(e).__name__)
    article_urls=list(dict.fromkeys(article_urls))
    if not article_urls:
        return []

    a2_names=A2_TEAMS
    b_names=B_A_TEAMS+B_B_TEAMS
    # Allow common current-name variants without changing the canonical output.
    aliases={
        "ProValue Juvecaserta 2021":"Juvecaserta 2021",
        "Paperdi Juvecaserta 2021":"Juvecaserta 2021",
        "Ferraroni JuVi Cremona 1952":"Ferraroni Juvi Cremona 1952",
        "Elachem Vigevano 1955":"ELAchem Vigevano 1955",
        "Redel Reggio Calabria":"Redel Reggio Calabria",
        "SAE Scientifica Soevis Legnano Knights":"SAE Scientifica-Soevis Legnano Knights",
        "LuxArm Lumezzane":"Luxarm Lumezzane",
    }
    all_names=a2_names+b_names+list(aliases.keys())
    pats=[(n,re.compile(re.escape(n),re.I)) for n in sorted(set(all_names),key=len,reverse=True)]

    # Examples in official LNP articles:
    # "Sabato 3 ottobre, ore 20:30" followed by "Unieuro Forlì-Sella Cento"
    date_time_re=re.compile(r"(?:Sabato|Domenica|Lunedì|Martedì|Mercoledì|Giovedì|Venerdì)\s+(\d{1,2})\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre),?\s*(?:ore\s*)?(\d{1,2}:\d{2})",re.I)
    months={"gennaio":1,"febbraio":2,"marzo":3,"aprile":4,"maggio":5,"giugno":6,"luglio":7,"agosto":8,"settembre":9,"ottobre":10,"novembre":11,"dicembre":12}
    for url in article_urls:
        try:
            r=fetch(url); soup=BeautifulSoup(r.text,"html.parser")
            title=clean(soup.title.get_text(" ",strip=True) if soup.title else "")
            whole=clean(soup.get_text(" ",strip=True))
            lowtitle=title.lower()+" "+url.lower()
            comp="A2" if "serie-a2" in lowtitle else ("B" if "serie-b-nazionale" in lowtitle else None)
            if not comp: continue
            names=a2_names if comp=="A2" else b_names
            # Scan text around each explicit date/time. This is deliberately
            # local so unrelated dates on the page do not get paired together.
            for m in date_time_re.finditer(whole):
                day=int(m.group(1)); tm=m.group(2)
                mon_name=re.search(r"(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)",m.group(0),re.I).group(0).lower()
                mo=months[mon_name]
                year=2026 if mo>=9 else 2027
                date=f"{year:04d}-{mo:02d}-{day:02d}"
                block=whole[m.end():m.end()+500]
                found=[]
                for n in sorted(names,key=len,reverse=True):
                    mm=re.search(re.escape(n),block,re.I)
                    if mm: found.append((mm.start(),n))
                found.sort()
                # Deduplicate same spelling and use first two names.
                uniq=[]
                for pos,n in found:
                    canonical=aliases.get(n,n)
                    if canonical not in [x[1] for x in uniq]: uniq.append((pos,canonical))
                if len(uniq)>=2:
                    h,a=uniq[0][1],uniq[1][1]
                    games.append(make_game(date,tm,h,a,comp,"Serie A2" if comp=="A2" else "Serie B Nazionale","LNP Pass","LNP news"))
        except Exception as e:
            print("LNP article:",type(e).__name__)
    return dedupe([g for g in games if g])

def parse_euro(url, comp, label):
    """Tentativo prudente per eventuali Event/JSON-LD esposti dal sito ufficiale."""
    r = fetch(url)
    soup = BeautifulSoup(r.text, "html.parser")
    games = []

    for sc in soup.select('script[type="application/ld+json"]'):
        raw = sc.string or sc.get_text()
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        objs = obj if isinstance(obj, list) else [obj]
        for o in objs:
            if not isinstance(o, dict):
                continue
            if o.get("@type") not in ("SportsEvent", "Event"):
                continue
            start = str(o.get("startDate", ""))
            date = parse_date(start)
            if not date:
                m = re.match(r"(\d{4}-\d\d-\d\d)", start)
                date = m.group(1) if m else None
            if not date:
                continue
            tm = re.search(r"T(\d\d:\d\d)", start)
            time = tm.group(1) if tm else ""
            name = clean(o.get("name", ""))
            pair = re.split(r"\s+[-–—]\s+", name, maxsplit=1)
            if len(pair) == 2:
                g = make_game(date, time, pair[0], pair[1], comp, label,
                              "Programmazione TV da definire", label)
                if g:
                    games.append(g)
    return dedupe(games)

def dedupe(games):
    out = {}
    for g in games:
        key = (g["date"], g["time"], g["home"], g["away"], g["competition"])
        out[key] = g
    return list(out.values())

def main():
    if DATA.exists():
        try:
            old = json.loads(DATA.read_text(encoding="utf-8"))
        except Exception:
            old = {}
    else:
        old = {}

    old_games = old.get("games", [])
    all_new = []
    report = []

    sources = [
        ("LBA", "LBA Serie A", parse_lba),
        ("A2", "Serie A2", lambda: parse_lnp_pdf(A2_PDF, "A2", "Serie A2", A2_TEAMS)),
        ("B", "Serie B Nazionale", lambda: (
            parse_lnp_pdf(B_A_PDF, "B", "Serie B Nazionale", B_A_TEAMS)
            + parse_lnp_pdf(B_B_PDF, "B", "Serie B Nazionale", B_B_TEAMS)
        )),
        ("EUROLEAGUE", "EuroLeague", lambda: parse_euro(EUROLEAGUE_URL, "EUROLEAGUE", "EuroLeague")),
        ("EUROCUP", "EuroCup", lambda: parse_euro(EUROCUP_URL, "EUROCUP", "EuroCup")),
    ]

    for code, label, fn in sources:
        try:
            games = fn()
            games = dedupe(games)
            all_new.extend(games)
            report.append(f"{label}: {len(games)} gare")
            print(report[-1])
        except Exception as exc:
            msg = f"{label}: ERRORE {type(exc).__name__}: {exc}"
            report.append(msg)
            print(msg)

    # Arricchisce gli orari A2/B dagli articoli ufficiali LNP.
    try:
        news_games = parse_lnp_news_schedule()
        report.append(f"LNP news orari: {len(news_games)} gare")
        print(report[-1])
        # Gli orari pubblicati negli articoli hanno priorità su quelli del PDF.
        all_new.extend(news_games)
    except Exception as exc:
        report.append(f"LNP news orari: ERRORE {type(exc).__name__}: {exc}")
        print(report[-1])

    # Sostituisce le gare di una competizione SOLO se quella fonte ha prodotto
    # un numero plausibile di gare. In caso contrario mantiene i dati precedenti.
    old_by_comp = {}
    for g in old_games:
        old_by_comp.setdefault(g.get("competition"), []).append(g)

    new_by_comp = {}
    for g in all_new:
        new_by_comp.setdefault(g.get("competition"), []).append(g)

    final_games = []
    for comp in ("LBA", "A2", "B", "EUROLEAGUE", "EUROCUP"):
        ng = new_by_comp.get(comp, [])
        # Soglie minime prudenti: evitano di cancellare un calendario se una
        # pagina/PDF cambia struttura per qualche ora.
        minimum = {"LBA": 8, "A2": 50, "B": 80, "EUROLEAGUE": 10, "EUROCUP": 10}[comp]
        if len(ng) >= minimum:
            final_games.extend(ng)
        else:
            final_games.extend(old_by_comp.get(comp, []))

    # Mantieni anche eventuali competizioni future presenti nel file precedente.
    known = {"LBA", "A2", "B", "EUROLEAGUE", "EUROCUP"}
    final_games.extend(g for g in old_games if g.get("competition") not in known)

    final_games = dedupe(final_games)
    final_games.sort(key=lambda g: (g.get("date",""), g.get("time","99:99"), g.get("competition",""), g.get("home","")))

    out = {
        "season": "2026/27",
        "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "games": final_games,
        "source_report": report,
    }
    DATA.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Totale gare nel database: {len(final_games)}")

if __name__ == "__main__":
    main()
