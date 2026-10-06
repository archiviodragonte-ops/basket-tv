#!/usr/bin/env python3
# Basket TV - updater
# Fonti principali: pagine web ufficiali LBA e LNP.
# I PDF LNP vengono usati SOLO come fallback per mantenere il calendario completo.

import json
import re
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

DATA = Path("data.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BasketTV/2.0; +https://github.com/archiviodragone-ops/basket-tv)",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}
TIMEOUT = 12

LBA_CALENDAR_URL = "https://www.legabasket.it/calendario/calendar?selectedTab=schedule&selectedTeamId=all"
LBA_NEWS_URL = "https://www.legabasket.it/news"
LNP_NEWS_URL = "https://www.legapallacanestro.com/news?field_area_articolo_value=lnp_news&lnp_news_filter=All"

A2_PDF = "https://static.legapallacanestro.com/sites/default/files/editor/calendario_serie_a2_oww_2026-27.pdf"
B_A_PDF = "https://static.legapallacanestro.com/sites/default/files/editor/calendario_b_naz._gir._a_2026-27.pdf"
B_B_PDF = "https://static.legapallacanestro.com/sites/default/files/editor/calendario_b_naz._gir._b_2026-27.pdf"

EUROLEAGUE_URL = "https://www.euroleaguebasketball.net/euroleague/"
EUROCUP_URL = "https://www.euroleaguebasketball.net/eurocup/"


def ensure_import(module, package=None):
    try:
        return __import__(module)
    except ImportError:
        pkg = package or module
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


def parse_date(text):
    text = clean(text)
    m = re.search(r"\b(\d{1,2})[./-](\d{1,2})[./-](2026|2027)\b", text)
    if m:
        d, mo, y = map(int, m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.search(r"\b(2026|2027)-(\d{1,2})-(\d{1,2})\b", text)
    if m:
        y, mo, d = map(int, m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"
    return None


def parse_time(text):
    m = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", clean(text))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""


def make_game(date, time, home, away, comp, label, watch="", source=""):
    home, away = clean(home), clean(away)
    if not date or not home or not away:
        return None
    bad = {"casa", "ospite", "home", "away", "squadra di casa", "squadra ospite"}
    if home.casefold() in bad or away.casefold() in bad:
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
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r


# ---------------------------------------------------------------------------
# LNP: nomi ufficiali. Servono per riconoscere le due squadre negli articoli.
# ---------------------------------------------------------------------------
A2_TEAMS = [
    "Halley Campania Avellino Basket", "Flats Service Fortitudo Bologna",
    "Valtur Brindisi", "Paperdi Juvecaserta 2021", "ProValue Juvecaserta 2021",
    "Juvecaserta 2021", "Sella Cento", "UEB Gesteco Cividale",
    "Ferraroni Juvi Cremona 1952", "Unieuro Forlì", "Libertas Livorno 1947",
    "Gemini Mestre", "Wegreenit Urania Milano", "La T Tecnica Gema Montecatini",
    "CMT Orange Tools Pesaro", "Victoria Libertas Pesaro", "Lumos Pistoia Basket",
    "RSR Sebastiani Rieti", "Dole Basket Rimini", "Crifo Wines Ruvo di Puglia",
    "Banco di Sardegna Sassari", "Reale Mutua Torino", "ELAchem Vigevano 1955",
]

B_A_TEAMS = [
    "Moncada Energy Agrigento", "A2A Leonessa Brescia", "Infodrive Capo d'Orlando",
    "Rimadesio Desio", "Adamant Ferrara", "Fiorenzuola Bees", "Andrea Costa Imola",
    "SAE Scientifica-Soevis Legnano Knights", "LuxArm Lumezzane",
    "Paffoni Fulgor Basket Omegna", "Logiman Orzinuovi", "UCC Assigeco Piacenza",
    "Siaz Basket Piazza Armerina", "Pallacanestro Viola Reggio Calabria",
    "Myenergy Reggio Calabria", "Redel Reggio Calabria", "LTC Group Sangiorgese Basket",
    "Rucker San Vendemiano", "TAV Treviglio Brianza Basket", "S4 Energia Vicenza",
]

B_B_TEAMS = [
    "Felice Scandone Avellino", "Umana San Giobbe Chiusi", "Ristopro Fabriano",
    "Tema Sinergie Faenza", "Benacquista Assicurazioni Latina", "Pielle Livorno",
    "Verodol CBD Pielle Livorno", "Basketball Club Lucca", "FABO Herons Montecatini",
    "Fabo Herons Montecatini", "PSA Napoli Est", "Consultinvest Loreto Pesaro",
    "Solbat Golfo Piombino", "Consorzio Leonardo Dany Quarrata", "OraSì Ravenna",
    "Luiss Roma", "Virtus GVM Roma 1960", "Liofilchem Roseto",
    "Allianz Pazienza Cestistica San Severo", "Mens Sana Basketball Siena",
    "Sendero Mens Sana Siena",
]

ALIASES = {
    "Paperdi Juvecaserta 2021": "Juvecaserta 2021",
    "ProValue Juvecaserta 2021": "Juvecaserta 2021",
    "Ferraroni JuVi Cremona 1952": "Ferraroni Juvi Cremona 1952",
    "Elachem Vigevano 1955": "ELAchem Vigevano 1955",
    "LuxArm Lumezzane": "Luxarm Lumezzane",
    "SAE Scientifica Soevis Legnano Knights": "SAE Scientifica-Soevis Legnano Knights",
    "SAE Scientifica-Soevis Legnano Knights": "SAE Scientifica-Soevis Legnano Knights",
    "FABO Herons Montecatini": "FABO Herons Montecatini",
    "Fabo Herons Montecatini": "FABO Herons Montecatini",
    "Verodol CBD Pielle Livorno": "Verodol CBD Pielle Livorno",
    "Pielle Livorno": "Pielle Livorno",
    "OraSì Ravenna": "OraSì Ravenna",
}

MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5,
    "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
    "novembre": 11, "dicembre": 12,
}

WEEKDAYS = r"Lunedì|Martedì|Mercoledì|Giovedì|Venerdì|Sabato|Domenica"


def canonical_team(name):
    return ALIASES.get(name, name)


def find_team_pair(text, teams):
    found = []
    low = text.casefold()
    for name in sorted(set(teams), key=len, reverse=True):
        pos = low.find(name.casefold())
        if pos >= 0:
            found.append((pos, canonical_team(name)))
    found.sort(key=lambda x: x[0])
    out = []
    for pos, name in found:
        if name not in [x[1] for x in out]:
            out.append((pos, name))
        if len(out) == 2:
            break
    return [x[1] for x in out]


def watch_from_text(text, default="LNP Pass"):
    low = clean(text).lower()
    tv = []
    if "raisport" in low:
        tv.append("RaiSport HD")
    if "rai play" in low or "raiplay" in low:
        tv.append("Rai Play")
    if "lnp pass" in low:
        tv.append("LNP Pass")
    if "twitch" in low:
        tv.append("Twitch Italbasket")
    return " · ".join(dict.fromkeys(tv)) or default


def parse_lnp_date_time_blocks(text, comp, teams):
    """Legge direttamente le righe degli articoli LNP.

    Formato attuale tipico:
      11/10/2026 18:00 Squadra-Squadra - Diretta streaming...

    Supporta anche:
      Domenica 11 ottobre, ore 18:00 Squadra-Squadra
    """
    text = clean(text)
    games = []

    # Formato numerico: è quello usato negli articoli "risultati + prossimo turno".
    matches = list(re.finditer(r"\b(\d{1,2}/\d{1,2}/202[67])\s+([0-2]?\d:[0-5]\d)\b", text))
    for i, m in enumerate(matches):
        date = parse_date(m.group(1))
        time = parse_time(m.group(2))
        end = matches[i + 1].start() if i + 1 < len(matches) else min(len(text), m.end() + 700)
        block = text[m.end():end]
        pair = find_team_pair(block, teams)
        if len(pair) == 2:
            watch = watch_from_text(block)
            label = "Serie A2" if comp == "A2" else "Serie B Nazionale"
            g = make_game(date, time, pair[0], pair[1], comp, label, watch, "LNP web")
            if g:
                games.append(g)

    # Formato editoriale "Domenica 11 ottobre, ore 18:00".
    editorial = re.compile(
        rf"\b({WEEKDAYS})\s+(\d{{1,2}})\s+([a-zà]+),?\s*(?:ore\s*)?(\d{{1,2}}[:.]\d{{2}})",
        re.I,
    )
    for m in editorial.finditer(text):
        mo = MONTHS.get(m.group(3).lower())
        if not mo:
            continue
        year = 2026 if mo >= 9 else 2027
        date = f"{year:04d}-{mo:02d}-{int(m.group(2)):02d}"
        time = parse_time(m.group(4))
        end = min(len(text), m.end() + 700)
        block = text[m.end():end]
        pair = find_team_pair(block, teams)
        if len(pair) == 2:
            watch = watch_from_text(block)
            label = "Serie A2" if comp == "A2" else "Serie B Nazionale"
            g = make_game(date, time, pair[0], pair[1], comp, label, watch, "LNP web")
            if g:
                games.append(g)

    return games


def parse_lnp_web():
    """Fonte primaria LNP: articoli/pagine web ufficiali, non PDF."""
    games = []
    try:
        r = fetch(LNP_NEWS_URL)
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"LNP index ERRORE {type(e).__name__}: {e}")
        return []

    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(LNP_NEWS_URL, a.get("href"))
        title = clean(a.get_text(" ", strip=True))
        key = (title + " " + href).lower()
        if not href.startswith("https://www.legapallacanestro.com/"):
            continue
        if "202627" not in key:
            continue
        if "serie-a2" in key:
            links.append(("A2", href))
        elif "serie-b-nazionale" in key:
            links.append(("B", href))

    # Manteniamo soltanto gli articoli distinti e più recenti visibili nella pagina.
    links = list(dict.fromkeys(links))
    if not links:
        print("LNP web: nessun articolo stagione 2026/27 trovato")
        return []

    def read_article(item):
        comp, url = item
        try:
            rr = fetch(url)
            ss = BeautifulSoup(rr.text, "html.parser")
            title = clean(ss.title.get_text(" ", strip=True) if ss.title else "")
            body = clean(ss.get_text(" ", strip=True))
            teams = A2_TEAMS if comp == "A2" else (B_A_TEAMS + B_B_TEAMS)
            return parse_lnp_date_time_blocks(body, comp, teams)
        except Exception as e:
            print(f"LNP articolo ERRORE {type(e).__name__}: {e}")
            return []

    # Parallelizziamo: niente più attese seriali da 45 secondi.
    with ThreadPoolExecutor(max_workers=min(6, len(links))) as ex:
        futures = [ex.submit(read_article, x) for x in links]
        for f in as_completed(futures):
            games.extend(f.result())

    return merge_games([], games)


# ---------------------------------------------------------------------------
# PDF: SOLO fallback per non perdere partite. NON è la fonte degli orari.
# ---------------------------------------------------------------------------
def pdf_text(url):
    r = fetch(url)
    tmp = Path("_basket_tv_tmp.pdf")
    tmp.write_bytes(r.content)
    try:
        reader = PdfReader(str(tmp))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def find_two_teams(segment, teams):
    found = []
    low = segment.casefold()
    for team in sorted(set(teams), key=len, reverse=True):
        pos = low.find(team.casefold())
        if pos >= 0:
            found.append((pos, canonical_team(team)))
    found.sort(key=lambda x: x[0])
    out = []
    for pos, team in found:
        if team not in out:
            out.append(team)
        if len(out) == 2:
            break
    return out


def parse_lnp_pdf(url, comp, label, teams):
    try:
        text = pdf_text(url).replace("\r", "\n")
    except Exception as e:
        print(f"PDF {comp} ERRORE {type(e).__name__}: {e}")
        return []
    dates = list(re.finditer(r"\b\d{1,2}[./-]\d{1,2}[./-](?:2026|2027)\b", text))
    games = []
    for i, m in enumerate(dates):
        date = parse_date(m.group(0))
        end = dates[i + 1].start() if i + 1 < len(dates) else len(text)
        block = clean(text[m.end():end])
        pair = find_two_teams(block, teams)
        if len(pair) != 2:
            continue
        g = make_game(date, parse_time(block), pair[0], pair[1], comp, label, "LNP Pass", "LNP PDF fallback")
        if g:
            games.append(g)
    return merge_games([], games)


# ---------------------------------------------------------------------------
# LBA web. La fonte primaria è il sito LBA; il parser legge news/preview
# pubblicate dalla Lega. Il calendario precedente resta come salvagente.
# ---------------------------------------------------------------------------
LBA_TEAMS = [
    "Acqua S.Bernardo Cantù", "APU Old Wild West Udine", "Armani Olimpia Milano",
    "Nutribullet Treviso Basket", "Dolomiti Energia Trentino", "Napoli Basketball",
    "UNA Hotels Reggio Emilia", "BC Roma", "Bertram Derthona Tortona",
    "Longobardi Scafati Basket", "Openjobmetis Varese", "Pallacanestro Trieste",
    "Umana Reyer Venezia", "Virtus Costa Bologna", "Maxima Roma", "Tezenis Verona",
]


def parse_lba_web():
    games = []
    try:
        r = fetch(LBA_NEWS_URL)
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"LBA index ERRORE {type(e).__name__}: {e}")
        return []

    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(LBA_NEWS_URL, a.get("href"))
        title = clean(a.get_text(" ", strip=True))
        key = (title + " " + href).lower()
        if href.startswith("https://www.legabasket.it/") and "/news?id=" in href:
            links.append(href)
    links = list(dict.fromkeys(links))[:30]

    # Oltre alla lista news, il sito LBA espone pagine squadra con il calendario
    # completo. Se troviamo link squadra nella pagina news, li leggiamo.
    for a in soup.find_all("a", href=True):
        href = urljoin(LBA_NEWS_URL, a.get("href"))
        if "/protagonisti/squadre/" in href and "/dettaglio" in href:
            links.append(href)
    links = list(dict.fromkeys(links))[:40]

    def read(url):
        try:
            rr = fetch(url)
            ss = BeautifulSoup(rr.text, "html.parser")
            body = clean(ss.get_text(" ", strip=True))
            out = []
            # Le pagine squadra LBA usano: 11/10/2026 Ore 15:00 Squadra Squadra
            for m in re.finditer(r"\b(\d{1,2}/\d{1,2}/202[67])\s+(?:Ore\s*)?(\d{1,2}[:.]\d{2})", body, re.I):
                date = parse_date(m.group(1)); time = parse_time(m.group(2))
                block = body[m.end():m.end()+350]
                pair = find_two_teams(block, LBA_TEAMS)
                if len(pair) == 2:
                    g = make_game(date, time, pair[0], pair[1], "LBA", "LBA Serie A", "LBA TV", "LBA web")
                    if g: out.append(g)
            # Preview/headline format: "Squadra - Squadra ... alle 20.30 (live su LBATV)"
            for team1 in LBA_TEAMS:
                for team2 in LBA_TEAMS:
                    if team1 == team2: continue
                    pat = re.compile(re.escape(team1) + r"\s*[-–—]\s*" + re.escape(team2) + r".{0,180}?\b(?:alle\s*)?(\d{1,2}[.:]\d{2})\b", re.I)
                    for m in pat.finditer(body):
                        around = body[max(0,m.start()-100):m.end()+120]
                        dm = re.search(r"(\d{1,2})\s+(?:ottobre|novembre|dicembre|gennaio|febbraio|marzo|aprile|maggio)\b", around, re.I)
                        if not dm: continue
                        mo_name = re.search(r"ottobre|novembre|dicembre|gennaio|febbraio|marzo|aprile|maggio", dm.group(0), re.I).group(0).lower()
                        mo = MONTHS[mo_name]; year = 2026 if mo >= 9 else 2027
                        date = f"{year:04d}-{mo:02d}-{int(dm.group(1)):02d}"
                        watch = "LBA TV" if "lbatv" in around.lower() or "lba tv" in around.lower() else "Programmazione TV da definire"
                        g = make_game(date, parse_time(m.group(1)), team1, team2, "LBA", "LBA Serie A", watch, "LBA web")
                        if g: out.append(g)
            return out
        except Exception:
            return []

    if links:
        with ThreadPoolExecutor(max_workers=min(8, len(links))) as ex:
            for f in as_completed([ex.submit(read, u) for u in links]):
                games.extend(f.result())
    return merge_games([], games)


# ---------------------------------------------------------------------------
# EuroLeague / EuroCup: conserva il comportamento prudente precedente.
# ---------------------------------------------------------------------------
def parse_euro(url, comp, label):
    try:
        r = fetch(url)
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"{label} ERRORE {type(e).__name__}: {e}")
        return []
    games = []
    for sc in soup.select('script[type="application/ld+json"]'):
        raw = sc.string or sc.get_text()
        try: obj = json.loads(raw)
        except Exception: continue
        objs = obj if isinstance(obj, list) else [obj]
        for o in objs:
            if not isinstance(o, dict) or o.get("@type") not in ("SportsEvent", "Event"): continue
            start = str(o.get("startDate", ""))
            date = parse_date(start) or (re.match(r"(\d{4}-\d\d-\d\d)", start).group(1) if re.match(r"(\d{4}-\d\d-\d\d)", start) else None)
            if not date: continue
            tm = re.search(r"T(\d\d:\d\d)", start); time = tm.group(1) if tm else ""
            pair = re.split(r"\s+[-–—]\s+", clean(o.get("name", "")), maxsplit=1)
            if len(pair) == 2:
                g = make_game(date, time, pair[0], pair[1], comp, label, "Programmazione TV da definire", label)
                if g: games.append(g)
    return merge_games([], games)


# ---------------------------------------------------------------------------
# Merge intelligente: una partita è identificata da data + casa + ospite +
# competizione. Un nuovo orario sostituisce quello vuoto del PDF.
# ---------------------------------------------------------------------------
def norm_team(s):
    s = canonical_team(clean(s)).casefold()
    s = re.sub(r"[^a-z0-9àèéìòù' ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def game_key(g):
    return (g.get("competition", ""), g.get("date", ""), norm_team(g.get("home", "")), norm_team(g.get("away", "")))


def merge_games(base, updates):
    out = {game_key(g): dict(g) for g in base if g and game_key(g)[1]}
    for g in updates:
        if not g: continue
        k = game_key(g)
        if not k[1]: continue
        if k not in out:
            out[k] = dict(g)
            continue
        old = out[k]
        if g.get("time"):
            old["time"] = g["time"]
        if g.get("watch") and g.get("watch") != "Programmazione TV da definire":
            old["watch"] = g["watch"]
        if g.get("source"):
            old["source"] = g["source"]
        if g.get("competition_label"):
            old["competition_label"] = g["competition_label"]
    return list(out.values())


def dedupe(games):
    return merge_games([], games)


def main():
    try:
        old = json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else {}
    except Exception:
        old = {}
    old_games = old.get("games", [])

    # 1) Base calendario: PDF soltanto per avere tutte le gare anche quando
    #    LNP non ha ancora pubblicato l'orario sul web.
    pdf_games = []
    pdf_sources = [
        ("A2", "Serie A2", A2_PDF, A2_TEAMS),
        ("B", "Serie B Nazionale", B_A_PDF, B_A_TEAMS),
        ("B", "Serie B Nazionale", B_B_PDF, B_B_TEAMS),
    ]
    for comp, label, url, teams in pdf_sources:
        pdf_games.extend(parse_lnp_pdf(url, comp, label, teams))

    # 2) FONTI WEB UFFICIALI: hanno priorità assoluta sugli orari/TV.
    lnp_games = parse_lnp_web()
    lba_games = parse_lba_web()
    euroleague_games = parse_euro(EUROLEAGUE_URL, "EUROLEAGUE", "EuroLeague")
    eurocup_games = parse_euro(EUROCUP_URL, "EUROCUP", "EuroCup")

    # 3) Merge: vecchi dati -> calendario PDF -> aggiornamenti web.
    final_games = merge_games(old_games, pdf_games)
    final_games = merge_games(final_games, lnp_games)
    final_games = merge_games(final_games, lba_games)
    final_games = merge_games(final_games, euroleague_games)
    final_games = merge_games(final_games, eurocup_games)

    final_games.sort(key=lambda g: (
        g.get("date", "9999-99-99"),
        g.get("time") or "99:99",
        g.get("competition", ""),
        g.get("home", ""),
    ))

    report = [
        f"LNP web: {len(lnp_games)} aggiornamenti",
        f"LBA web: {len(lba_games)} aggiornamenti",
        f"A2 PDF fallback: {len([g for g in pdf_games if g.get('competition') == 'A2'])} gare",
        f"B PDF fallback: {len([g for g in pdf_games if g.get('competition') == 'B'])} gare",
        f"EuroLeague web: {len(euroleague_games)} gare",
        f"EuroCup web: {len(eurocup_games)} gare",
    ]
    for line in report: print(line)

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
