#!/usr/bin/env python3
# Basket TV - updater 2026/27
#
# PRIORITA' DELLE FONTI:
#   - LNP A2/B: pagine web ufficiali LNP + articoli ufficiali LNP
#   - LBA: calendario ufficiale + pagine ufficiali squadre/gare + FIP + news LBA
#   - EuroLeague/EuroCup: feed ufficiale Euroleague Basketball
#
# Obiettivo:
#   se una gara esiste gia' con ORARIO DA DEFINIRE, appena la fonte ufficiale
#   pubblica l'orario il valore viene sostituito automaticamente senza duplicare
#   la partita.

import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

DATA = Path("data.json")
TIMEOUT = 10
USER_AGENT = (
    "Mozilla/5.0 (compatible; BasketTV/3.0; "
    "+https://github.com/archiviodragone-ops/basket-tv)"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ---------------------------------------------------------------------------
# FONTI UFFICIALI WEB
# ---------------------------------------------------------------------------
LNP_A2_CALENDAR = "https://www.legapallacanestro.com/serie/1/calendario"
LNP_B_CALENDAR = "https://www.legapallacanestro.com/serie/4/calendario"
LNP_A2_NEWS = "https://www.legapallacanestro.com/news?field_area_articolo_value=serie_a2&lnp_news_filter=All&page=1"
LNP_B_NEWS = "https://www.legapallacanestro.com/news?field_area_articolo_value=serie_b&lnp_news_filter=All&page=1"
LNP_NEWS = "https://www.legapallacanestro.com/news?field_area_articolo_value=lnp_news&lnp_news_filter=All&page=1"
LNP_NEWS_PAGE2 = "https://www.legapallacanestro.com/news?field_area_articolo_value=lnp_news&lnp_news_filter=All&page=2"

LBA_CALENDAR = "https://www.legabasket.it/calendario/1/serie-a"
LBA_NEWS = "https://www.legabasket.it/news?categoryId=all&filtersDate=&filtersSearchString=&page=1&teamId=all"
LBA_HOME = "https://www.legabasket.it/"

EURO_API = "https://api-live.euroleague.net/v2/competitions/{competition}/seasons/{season}/games"

# ---------------------------------------------------------------------------
# SOLO FONTI WEB UFFICIALI.
# ---------------------------------------------------------------------------
LNP_A2_TEAMS_PAGE = "https://www.legapallacanestro.com/serie/1/squadre"
LNP_B_TEAMS_PAGE = "https://www.legapallacanestro.com/serie/4/squadre"
FIP_RESULTS = "https://fip.it/risultati/"
LBA_TEAMS_PAGE = "https://www.legabasket.it/protagonisti/squadre"

def ensure_import(module, package=None):
    try:
        return __import__(module)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", package or module])
        return __import__(module)


requests = ensure_import("requests")
bs4 = ensure_import("bs4", "beautifulsoup4")
BeautifulSoup = bs4.BeautifulSoup


def clean(value):
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def parse_date(value):
    s = clean(value)
    m = re.search(r"\b(\d{1,2})[./-](\d{1,2})[./-](2026|2027)\b", s)
    if m:
        d, mo, y = map(int, m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.search(r"\b(2026|2027)-(\d{1,2})-(\d{1,2})\b", s)
    if m:
        y, mo, d = map(int, m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"
    return None


def parse_time(value):
    m = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", clean(value))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""


def make_game(date, time, home, away, comp, label, watch="", source=""):
    home, away = clean(home), clean(away)
    if not date or not home or not away:
        return None
    if home.casefold() in {"casa", "ospite", "home", "away"}:
        return None
    if away.casefold() in {"casa", "ospite", "home", "away"}:
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


def fetch(url, timeout=TIMEOUT):
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response


# ---------------------------------------------------------------------------
# NOMI / ALIAS
# ---------------------------------------------------------------------------
A2_TEAMS = [
    "Halley Campania Avellino Basket", "Flats Service Fortitudo Bologna",
    "Valtur Brindisi", "Paperdi Juvecaserta 2021", "ProValue Juvecaserta 2021",
    "Juvecaserta 2021", "Sella Cento", "UEB Gesteco Cividale",
    "Ferraroni Juvi Cremona 1952", "Unieuro Forlì", "Libertas Livorno 1947",
    "Gemini Mestre", "Wegreenit Urania Milano", "La T Tecnica Gema Montecatini",
    "CMT Orange Tools Pesaro", "Victoria Libertas Pesaro", "Lumos Pistoia Basket",
    "RSR Sebastiani Rieti", "Dole Basket Rimini", "Crifo Wines Ruvo di Puglia",
    "Banco di Sardegna Sassari", "Reale Mutua Torino", "Elachem Vigevano 1955",
    "ELAchem Vigevano 1955",
]

B_TEAMS = [
    "Moncada Energy Agrigento", "A2A Leonessa Brescia", "Infodrive Capo d'Orlando",
    "Rimadesio Desio", "Adamant Ferrara", "Fiorenzuola Bees", "Andrea Costa Imola",
    "SAE Scientifica-Soevis Legnano Knights", "SAE Scientifica Soevis Legnano Knights",
    "LuxArm Lumezzane", "Luxarm Lumezzane", "Paffoni Fulgor Basket Omegna",
    "Logiman Orzinuovi", "UCC Assigeco Piacenza", "Siaz Basket Piazza Armerina",
    "Pallacanestro Viola Reggio Calabria", "Myenergy Reggio Calabria", "Redel Reggio Calabria",
    "LTC Group Sangiorgese Basket", "Rucker San Vendemiano", "TAV Treviglio Brianza Basket",
    "S4 Energia Vicenza", "Felice Scandone Avellino", "Umana San Giobbe Chiusi",
    "Ristopro Fabriano", "Tema Sinergie Faenza", "Benacquista Assicurazioni Latina",
    "Pielle Livorno", "Verodol CBD Pielle Livorno", "Basketball Club Lucca",
    "FABO Herons Montecatini", "Fabo Herons Montecatini", "PSA Napoli Est",
    "Consultinvest Loreto Pesaro", "Solbat Golfo Piombino", "Consorzio Leonardo Dany Quarrata",
    "OraSì Ravenna", "Luiss Roma", "Virtus GVM Roma 1960", "Liofilchem Roseto",
    "Allianz Pazienza Cestistica San Severo", "Mens Sana Basketball Siena",
    "Sendero Mens Sana Siena",
]

LBA_TEAMS = [
    "Acqua S.Bernardo Cantù", "APU Old Wild West Udine", "Armani Olimpia Milano",
    "Nutribullet Treviso Basket", "Dolomiti Energia Trentino", "Napoli Basketball",
    "UNA Hotels Reggio Emilia", "BC Roma", "Bertram Derthona Tortona",
    "Longobardi Scafati Basket", "Openjobmetis Varese", "Pallacanestro Trieste",
    "Umana Reyer Venezia", "Virtus Costa Bologna", "Maxima Roma", "Tezenis Verona",
]

ALIASES = {
    "Paperdi Juvecaserta 2021": "Juvecaserta 2021",
    "ProValue Juvecaserta 2021": "Juvecaserta 2021",
    "Ferraroni JuVi Cremona 1952": "Ferraroni Juvi Cremona 1952",
    "Elachem Vigevano 1955": "ELAchem Vigevano 1955",
    "LuxArm Lumezzane": "Luxarm Lumezzane",
    "SAE Scientifica Soevis Legnano Knights": "SAE Scientifica-Soevis Legnano Knights",
    "Fabo Herons Montecatini": "FABO Herons Montecatini",
    "Verodol CBD Pielle Livorno": "Pielle Livorno",
    "Sendero Mens Sana Siena": "Mens Sana Basketball Siena",
    "Myenergy Reggio Calabria": "Redel Reggio Calabria",
    "Pallacanestro Viola Reggio Calabria": "Pallacanestro Viola Reggio Calabria",
    # Nomi abbreviati/societari usati da FIP.
    "OLD WILD WEST UDINE": "APU Old Wild West Udine",
    "APU IFISSPORT UDINE": "APU Old Wild West Udine",
    "COSTA BOLOGNA": "Virtus Costa Bologna",
    "NAPOLIBASKET": "Napoli Basketball",
    "UMANA VENEZIA MESTRE": "Umana Reyer Venezia",
    "NUTRIBULLET TREVISO": "Nutribullet Treviso Basket",
    "BERTRAM TORTONA": "Bertram Derthona Tortona",
    "DOLOMITI ENERGIA TRENTO": "Dolomiti Energia Trentino",
    "OLIMPIA MILANO": "Armani Olimpia Milano",
    "PALLACANESTRO TRIESTE 2004": "Pallacanestro Trieste",
    "UNAHOTELS REGGIO EMILIA": "UNA Hotels Reggio Emilia",
    "TEZENIS VERONA": "Tezenis Verona",
    "BC ROMA S.P.Q.R.": "BC Roma",
    "S.BERNARDO CANTU'": "Acqua S.Bernardo Cantù",
    "S.BERNARDO CANTU’": "Acqua S.Bernardo Cantù",
    "MAXIMA ROMA BASKET": "Maxima Roma",
    "OPENJOBMETIS VARESE": "Openjobmetis Varese",
    "LONGOBARDI SCAFATI": "Longobardi Scafati Basket",
    "PAPERDI JUVECASERTA 2021": "Juvecaserta 2021",
    "ELA CHEM VIGEVANO 1955": "ELAchem Vigevano 1955",
}

MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5,
    "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
    "novembre": 11, "dicembre": 12,
}


def canonical_team(name):
    name = clean(name)
    return ALIASES.get(name, name)


def norm_team(name):
    s = canonical_team(name).casefold()
    s = re.sub(r"[^a-z0-9àèéìòù' ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def game_key(game):
    return (
        game.get("competition", ""),
        game.get("date", ""),
        norm_team(game.get("home", "")),
        norm_team(game.get("away", "")),
    )


def source_priority(source):
    s = clean(source).casefold()
    if "lnp crawler" in s:
        return 125
    if "lnp web" in s or "lnp news" in s:
        return 120
    if "lnp pagina squadra" in s:
        return 115
    if "fip risultati" in s:
        return 110
    if "lba crawler" in s:
        return 125
    if "lba pagina squadra" in s:
        return 120
    if "lba pagina gara" in s:
        return 115
    if "lba preview" in s or "lba web" in s:
        return 110
    if "lba calendario" in s:
        return 100
    if "euroleague" in s:
        return 100
    if "eurocup" in s:
        return 100
    return 50


def merge_games(base, updates):
    """Unisce gare per competizione/data/casa/ospite mantenendo la fonte piu' affidabile."""
    out = {}
    for game in base or []:
        if game and game_key(game)[1]:
            g = dict(game)
            g["_priority"] = source_priority(g.get("source", ""))
            out[game_key(g)] = g

    for game in updates or []:
        if not game:
            continue
        key = game_key(game)
        if not key[1]:
            continue
        incoming = dict(game)
        incoming["_priority"] = source_priority(incoming.get("source", ""))
        current = out.get(key)
        if current is None:
            out[key] = incoming
            continue

        cp = current.get("_priority", 0)
        ip = incoming.get("_priority", 0)

        # Un orario gia' noto non viene sovrascritto da una fonte meno affidabile.
        if incoming.get("time") and (not current.get("time") or ip >= cp):
            current["time"] = incoming["time"]
            current["source"] = incoming.get("source", current.get("source", ""))
            current["_priority"] = max(cp, ip)
        elif incoming.get("source") and ip > cp:
            current["source"] = incoming["source"]
            current["_priority"] = ip

        if incoming.get("watch") and incoming.get("watch") != "Programmazione TV da definire":
            if (not current.get("watch") or ip >= cp or current.get("watch") == "Programmazione TV da definire"):
                current["watch"] = incoming["watch"]
        if incoming.get("competition_label"):
            current["competition_label"] = incoming["competition_label"]

    for g in out.values():
        g.pop("_priority", None)
    return list(out.values())


# ---------------------------------------------------------------------------
# CRAWLER STRUTTURALE DEI SITI UFFICIALI
# ---------------------------------------------------------------------------
# Non dipendiamo da un singolo URL "magico": partiamo dai nodi ufficiali
# (calendario, squadre, news, risultati), seguiamo i link interni pertinenti
# e interpretiamo tabelle/pagine che contengono coppie di squadre + data/ora.
# Il crawler e' volutamente limitato al dominio ufficiale e a percorsi utili,
# cosi' un aggiornamento ogni 5 minuti non diventa una scansione infinita.

def crawl_official_site(seeds, domain, path_keywords, max_pages=140, max_depth=2):
    queue = [(u, 0) for u in seeds]
    seen = set()
    pages = []
    while queue and len(pages) < max_pages:
        url, depth = queue.pop(0)
        url = url.split('#', 1)[0]
        if url in seen or depth > max_depth:
            continue
        if not url.startswith(domain):
            continue
        seen.add(url)
        try:
            response = fetch(url)
            soup = BeautifulSoup(response.text, 'html.parser')
        except Exception:
            continue
        pages.append((url, soup))
        if depth >= max_depth:
            continue
        for a in soup.find_all('a', href=True):
            href = urljoin(url, a.get('href')).split('#', 1)[0]
            if not href.startswith(domain) or href in seen:
                continue
            path = href.casefold()
            label = clean(a.get_text(' ', strip=True)).casefold()
            if any(k in path or k in label for k in path_keywords):
                queue.append((href, depth + 1))
    return pages


def generic_page_games(soup, comp, label, teams, source):
    games = []
    # Prima le righe strutturate: sono le piu' affidabili.
    for tr in soup.select('tr'):
        cells = [clean(x.get_text(' ', strip=True)) for x in tr.select('th,td')]
        if len(cells) < 2:
            continue
        joined = ' | '.join(cells)
        date = parse_date(joined)
        if not date:
            continue
        pair = find_pair(joined, teams)
        if len(pair) != 2:
            continue
        g = make_game(date, parse_time(joined), pair[0], pair[1], comp, label,
                      lnp_watch(joined) if comp in {'A2','B'} else lba_watch(joined), source)
        if g:
            games.append(g)
    # Poi il testo completo, utile per preview/news/articoli.
    text = clean(soup.get_text(' ', strip=True))
    if comp == 'LBA':
        games.extend(parse_lba_text(text))
    else:
        games.extend(parse_lnp_article_text(text, comp, teams))
    return merge_games([], games)


def crawl_lnp_relevant(comp):
    if comp == 'A2':
        seeds = [LNP_A2_CALENDAR, LNP_A2_TEAMS_PAGE, LNP_A2_NEWS, LNP_NEWS]
        keywords = ['serie/1/', '/serie-a2', 'calendario', 'squadre', '/news', 'a2', 'fortitudo', 'forli']
        teams = A2_TEAMS
        label = 'Serie A2'
    else:
        seeds = [LNP_B_CALENDAR, LNP_B_TEAMS_PAGE, LNP_B_NEWS, LNP_NEWS]
        keywords = ['serie/4/', '/serie-b', 'calendario', 'squadre', '/news', 'serie b', 'nazionale']
        teams = B_TEAMS
        label = 'Serie B Nazionale'
    pages = crawl_official_site(seeds, 'https://www.legapallacanestro.com/', keywords,
                                max_pages=150, max_depth=2)
    games = []
    for url, soup in pages:
        games.extend(generic_page_games(soup, comp, label, teams, 'LNP crawler ufficiale'))
    return merge_games([], games), len(pages)


def crawl_lba_relevant():
    seeds = [LBA_CALENDAR, LBA_TEAMS_PAGE, LBA_NEWS, LBA_HOME]
    keywords = ['calendario', 'protagonisti/squadre/', '/game/', '/news', 'serie-a', '2026', '2027']
    pages = crawl_official_site(seeds, 'https://www.legabasket.it/', keywords,
                                max_pages=180, max_depth=2)
    games = []
    for url, soup in pages:
        games.extend(generic_page_games(soup, 'LBA', 'LBA Serie A', LBA_TEAMS,
                                         'LBA crawler ufficiale'))
    return merge_games([], games), len(pages)

# ---------------------------------------------------------------------------
# LNP WEB: calendario diretto + articoli ufficiali recenti
# ---------------------------------------------------------------------------
def find_pair(block, teams):
    found = []
    low = block.casefold()
    for team in sorted(set(teams), key=len, reverse=True):
        pos = low.find(team.casefold())
        if pos >= 0:
            found.append((pos, canonical_team(team)))
    found.sort(key=lambda item: item[0])
    result = []
    for _, team in found:
        if team not in result:
            result.append(team)
        if len(result) == 2:
            break
    return result


def lnp_watch(text):
    low = clean(text).casefold()
    values = []
    if "raisport" in low:
        values.append("RaiSport HD")
    if "rai play" in low or "raiplay" in low:
        values.append("Rai Play")
    if "lnp pass" in low:
        values.append("LNP Pass")
    if "twitch" in low:
        values.append("Twitch Italbasket")
    if "youtube" in low and "lnp" in low:
        values.append("YouTube LNP")
    return " · ".join(dict.fromkeys(values)) or "LNP Pass"


def parse_lnp_article_text(text, comp, teams):
    text = clean(text)
    label = "Serie A2" if comp == "A2" else "Serie B Nazionale"
    games = []

    # Formato attuale LNP: 11/10/2026 18:00 Squadra-Squadra ...
    date_times = list(re.finditer(r"\b(\d{1,2}/\d{1,2}/202[67])\s+([01]?\d|2[0-3])[:.]([0-5]\d)\b", text))
    for i, match in enumerate(date_times):
        date = parse_date(match.group(1))
        time = f"{int(match.group(2)):02d}:{match.group(3)}"
        end = date_times[i + 1].start() if i + 1 < len(date_times) else min(len(text), match.end() + 900)
        block = text[match.end():end]
        pair = find_pair(block, teams)
        if len(pair) == 2:
            game = make_game(date, time, pair[0], pair[1], comp, label, lnp_watch(block), "LNP web")
            if game:
                games.append(game)

    # Formato editoriale: Domenica 11 ottobre, ore 18:00 ...
    pattern = re.compile(
        r"\b(?:Lunedì|Martedì|Mercoledì|Giovedì|Venerdì|Sabato|Domenica)\s+"
        r"(\d{1,2})\s+([A-Za-zÀ-ÿ]+),?\s*(?:ore\s*)?(\d{1,2}[:.]\d{2})",
        re.I,
    )
    for match in pattern.finditer(text):
        month = MONTHS.get(match.group(2).casefold())
        if not month:
            continue
        year = 2026 if month >= 9 else 2027
        date = f"{year:04d}-{month:02d}-{int(match.group(1)):02d}"
        time = parse_time(match.group(3))
        block = text[match.end():min(len(text), match.end() + 900)]
        pair = find_pair(block, teams)
        if len(pair) == 2:
            game = make_game(date, time, pair[0], pair[1], comp, label, lnp_watch(block), "LNP web")
            if game:
                games.append(game)

    return merge_games([], games)


def discover_lnp_team_urls(index_url, prefix):
    """Scopre le pagine ufficiali delle squadre direttamente dall'indice LNP."""
    try:
        soup = BeautifulSoup(fetch(index_url).text, "html.parser")
    except Exception as exc:
        print(f"LNP {prefix} squadre: ERRORE {type(exc).__name__}: {exc}")
        return []
    urls = []
    seen = set()
    base = "https://www.legapallacanestro.com/"
    for a in soup.find_all("a", href=True):
        href = urljoin(index_url, a.get("href"))
        if not href.startswith(base):
            continue
        path = href.split("#", 1)[0].rstrip("/")
        if f"/{prefix}/" not in path or path.endswith("/squadre"):
            continue
        if "/squadre/" not in path:
            # Team pages are commonly /serie/{id}/{slug}; accept only pages
            # whose URL belongs to the requested competition.
            if not re.search(rf"/serie/(1|4)/[^/]+$", path):
                continue
        if href not in seen:
            seen.add(href)
            urls.append(href)
    return urls


def parse_lnp_team_page(url, comp, teams):
    """Legge la tabella gare della pagina ufficiale di una squadra LNP."""
    try:
        soup = BeautifulSoup(fetch(url).text, "html.parser")
    except Exception:
        return []
    label = "Serie A2" if comp == "A2" else "Serie B Nazionale"
    games = []
    for tr in soup.select("tr"):
        cells = [clean(x.get_text(" ", strip=True)) for x in tr.select("th,td")]
        if len(cells) < 3:
            continue
        joined = " | ".join(cells)
        date = parse_date(joined)
        if not date:
            continue
        # La pagina ufficiale squadra LNP ha una tabella strutturata:
        # Data | Casa | Ospite | Risultato | Impianto.
        # Usiamo direttamente le colonne, senza cercare i nomi dentro il testo.
        home = away = ""
        if len(cells) >= 3:
            home = canonical_team(cells[1])
            away = canonical_team(cells[2])
        if not home or not away or home.casefold() in {"casa", "home"} or away.casefold() in {"ospite", "away"}:
            pair = find_pair(joined, teams)
            if len(pair) != 2:
                continue
            home, away = pair
        time = parse_time(cells[0]) or parse_time(joined)
        watch = lnp_watch(joined)
        g = make_game(date, time, home, away, comp, label, watch, "LNP pagina squadra ufficiale")
        if g:
            games.append(g)
    return merge_games([], games)


def lnp_team_pages(comp, index_url, teams):
    prefix = "serie-a2" if comp == "A2" else "serie-b"
    urls = discover_lnp_team_urls(index_url, prefix)
    # L'indice LNP è la fonte autorevole per i link; se il markup cambia,
    # il calendario ufficiale resta comunque attivo come seconda fonte.
    games = []
    if urls:
        with ThreadPoolExecutor(max_workers=min(10, len(urls))) as pool:
            futures = [pool.submit(parse_lnp_team_page, u, comp, teams) for u in urls]
            for f in as_completed(futures):
                try:
                    games.extend(f.result())
                except Exception:
                    pass
    return merge_games([], games)


def parse_lnp_calendar(url, comp, teams):
    """Legge il calendario HTML ufficiale LNP.."""
    try:
        response = fetch(url)
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception as exc:
        print(f"LNP {comp} calendario: ERRORE {type(exc).__name__}: {exc}")
        return []

    label = "Serie A2" if comp == "A2" else "Serie B Nazionale"
    games = []

    for tr in soup.select("tr"):
        cells = [clean(td.get_text(" ", strip=True)) for td in tr.select("th,td")]
        if len(cells) < 3:
            continue
        joined = " | ".join(cells)
        date = parse_date(joined)
        if not date:
            continue

        # Calendario ufficiale LNP: Data | Casa | Ospite | ...
        # Prima scelta = colonne della tabella; il riconoscimento per nome è solo fallback.
        home = away = ""
        if len(cells) >= 3:
            candidates = [c for c in cells if c]
            # La prima cella contiene normalmente data+ora; casa/ospite sono la 2a/3a.
            home = canonical_team(candidates[1]) if len(candidates) > 1 else ""
            away = canonical_team(candidates[2]) if len(candidates) > 2 else ""
        if not home or not away or parse_date(home) or parse_date(away):
            pair = find_pair(joined, teams)
            if len(pair) != 2:
                continue
            home, away = pair

        time = parse_time(cells[0]) or parse_time(joined)
        watch = lnp_watch(joined)
        game = make_game(date, time, home, away, comp, label, watch, "LNP calendario web")
        if game:
            games.append(game)

    # Se il calendario viene servito senza righe <tr>, proviamo il testo della pagina.
    if not games:
        games.extend(parse_lnp_article_text(clean(soup.get_text(" ", strip=True)), comp, teams))

    return merge_games([], games)


def recent_lnp_articles(index_url, comp, teams):
    """Legge sia le news specifiche sia le LNP News generali.

    Le variazioni di orario e gli articoli "prossimo turno" vengono spesso
    pubblicati nella sezione LNP News generale: non bisogna quindi affidarsi
    solo al filtro Serie A2/Serie B.
    """
    indexes = [index_url, LNP_NEWS, LNP_NEWS_PAGE2]
    candidates = []
    seen = set()

    for idx in indexes:
        try:
            soup = BeautifulSoup(fetch(idx).text, "html.parser")
        except Exception as exc:
            print(f"LNP {comp} indice news: ERRORE {type(exc).__name__}: {exc}")
            continue
        for a in soup.find_all("a", href=True):
            href = urljoin(idx, a.get("href"))
            title = clean(a.get_text(" ", strip=True))
            if not href.startswith("https://www.legapallacanestro.com/"):
                continue
            if href in seen or not title:
                continue
            key = (title + " " + href).casefold()
            # Teniamo solo articoli 2026/27 o articoli chiaramente legati a
            # programma, variazioni, anticipi/rinvii.
            relevant_title = any(t in key for t in (
                "2026/27", "202627", "prossimo turno", "giornata",
                "variazione", "anticipo", "rinvio", "posticipo",
            ))
            if not relevant_title:
                continue
            if comp == "A2" and not any(t in key for t in ("serie a2", "a2", "2026/27")):
                continue
            if comp == "B" and not any(t in key for t in ("serie b", "b nazionale", "2026/27")):
                continue
            seen.add(href)
            candidates.append((href, title))

    # Gli articoli piu' recenti sono quelli utili per variazioni/orari.
    candidates = candidates[:18]

    def read(item):
        href, title = item
        try:
            r = fetch(href)
            soup = BeautifulSoup(r.text, "html.parser")
            body = clean(soup.get_text(" ", strip=True))
            parsed = parse_lnp_article_text(body, comp, teams)
            for g in parsed:
                g["source"] = "LNP news ufficiali"
            return parsed
        except Exception as exc:
            print(f"LNP {comp} articolo: ERRORE {type(exc).__name__}: {exc}")
            return []

    games = []
    if candidates:
        with ThreadPoolExecutor(max_workers=min(6, len(candidates))) as pool:
            futures = [pool.submit(read, item) for item in candidates]
            for future in as_completed(futures):
                try:
                    games.extend(future.result())
                except Exception:
                    pass
    return merge_games([], games)


# ---------------------------------------------------------------------------
# LBA WEB
# ---------------------------------------------------------------------------
def lba_watch(text):
    low = clean(text).casefold()
    tv = []
    if "sky sport" in low or "skysportbasket" in low:
        tv.append("Sky Sport")
    if "cielo" in low:
        tv.append("Cielo")
    if "dazn" in low:
        tv.append("DAZN")
    if "lbatv" in low or "lba tv" in low:
        tv.append("LBA TV")
    return " · ".join(dict.fromkeys(tv)) or "LBA TV"


def next_weekday_date(reference_date, weekday_name):
    """Restituisce la prossima data con il giorno indicato, rispetto a publication date."""
    names = {
        "lunedì": 0, "lunedi": 0, "martedì": 1, "martedi": 1,
        "mercoledì": 2, "mercoledi": 2, "giovedì": 3, "giovedi": 3,
        "venerdì": 4, "venerdi": 4, "sabato": 5, "domenica": 6,
    }
    target = names.get(weekday_name.casefold())
    if target is None:
        return None
    try:
        base = datetime.strptime(reference_date, "%Y-%m-%d").date()
    except ValueError:
        return None
    delta = (target - base.weekday()) % 7
    # Nei Preview LBA "sabato" normalmente indica il giorno successivo della settimana.
    if delta == 0:
        delta = 7
    from datetime import timedelta
    d = base + timedelta(days=delta)
    return d.isoformat()


def extract_lba_pair(text):
    """Trova una coppia LBA usando l'elenco ufficiale delle squadre."""
    low = clean(text).casefold()
    found = []
    for team in sorted(LBA_TEAMS, key=len, reverse=True):
        pos = low.find(team.casefold())
        if pos >= 0:
            found.append((pos, team))
    found.sort(key=lambda item: item[0])
    unique = []
    for pos, team in found:
        if team not in unique:
            unique.append(team)
        if len(unique) == 2:
            break
    return unique


def parse_lba_text(text, reference_date=None):
    text = clean(text)
    games = []

    # 1) Formato esplicito con data:
    #    "11/10/2026 ... Acqua S.Bernardo Cantù - Napoli Basketball ... 15:00"
    explicit = re.compile(
        r"\b(\d{1,2}/\d{1,2}/202[67])\b.{0,220}?"
        r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b",
        re.I,
    )
    for match in explicit.finditer(text):
        date = parse_date(match.group(1))
        time = f"{int(match.group(2)):02d}:{match.group(3)}"
        block = text[match.start():min(len(text), match.end() + 260)]
        pair = extract_lba_pair(block)
        if len(pair) == 2:
            game = make_game(date, time, pair[0], pair[1], "LBA", "LBA Serie A", lba_watch(block), "LBA web")
            if game:
                games.append(game)

    # 2) Preview LBA: "Umana Reyer Venezia - Acqua S.Bernardo Cantù sabato alle 20.00"
    preview = re.compile(
        r"\b(sabato|domenica|lunedì|lunedi|martedì|martedi|mercoledì|mercoledi|"
        r"giovedì|giovedi|venerdì|venerdi)\b.{0,45}?\b(?:alle|ore)\s*(\d{1,2}[:.]\d{2})",
        re.I,
    )
    for match in preview.finditer(text):
        time = parse_time(match.group(2))
        window_start = max(0, match.start() - 220)
        window_end = min(len(text), match.end() + 180)
        block = text[window_start:window_end]
        pair = extract_lba_pair(block)
        if len(pair) != 2:
            continue
        date = None
        prefix = text[max(0, match.start() - 260):match.start()]
        date = parse_date(prefix)
        if not date and reference_date:
            date = next_weekday_date(reference_date, match.group(1))
        if not date:
            continue
        game = make_game(date, time, pair[0], pair[1], "LBA", "LBA Serie A", lba_watch(block), "LBA Preview web")
        if game:
            games.append(game)

    return merge_games([], games)


def parse_lba_calendar():
    try:
        response = fetch(LBA_CALENDAR)
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception as exc:
        print(f"LBA calendario: ERRORE {type(exc).__name__}: {exc}")
        return []

    games = []
    # Tabella HTML, se disponibile.
    for tr in soup.select("tr"):
        cells = [clean(td.get_text(" ", strip=True)) for td in tr.select("th,td")]
        joined = " | ".join(cells)
        date = parse_date(joined)
        if not date:
            continue
        pair = find_pair(joined, LBA_TEAMS)
        if len(pair) != 2:
            continue
        time = parse_time(joined)
        game = make_game(date, time, pair[0], pair[1], "LBA", "LBA Serie A", lba_watch(joined), "LBA calendario web")
        if game:
            games.append(game)

    if games:
        return merge_games([], games)

    return parse_lba_text(clean(soup.get_text(" ", strip=True)))


def parse_lba_recent_news():
    urls = [LBA_NEWS, LBA_HOME]
    games = []
    article_urls = []
    article_refs = {}

    for url in urls:
        try:
            r = fetch(url)
            soup = BeautifulSoup(r.text, "html.parser")
        except Exception as exc:
            print(f"LBA pagina: ERRORE {type(exc).__name__}: {exc}")
            continue

        # Anche il testo della pagina puo' contenere gia' le Preview con orario.
        page_text = clean(soup.get_text(" ", strip=True))
        games.extend(parse_lba_text(page_text))

        for a in soup.find_all("a", href=True):
            href = urljoin(url, a.get("href"))
            title = clean(a.get_text(" ", strip=True))
            if not href.startswith("https://www.legabasket.it/"):
                continue
            if not title:
                continue
            # Risali al contenitore dell'articolo per recuperare la data di pubblicazione.
            container = a
            for _ in range(4):
                if container.parent is None:
                    break
                container = container.parent
            block = clean(container.get_text(" ", strip=True))
            key = (title + " " + block).casefold()
            if "preview" not in key and "alle " not in key and "ore " not in key:
                continue
            # La data di pubblicazione LBA appare spesso come 24/09/2026 14:00.
            pub = re.search(r"\b(\d{1,2}/\d{1,2}/202[67])\b", block)
            ref = parse_date(pub.group(1)) if pub else None
            if href not in article_refs:
                article_refs[href] = ref

    article_urls = list(article_refs.items())[:12]

    def read(item):
        href, ref = item
        try:
            r = fetch(href)
            soup = BeautifulSoup(r.text, "html.parser")
            body = clean(soup.get_text(" ", strip=True))
            return parse_lba_text(body, reference_date=ref)
        except Exception as exc:
            print(f"LBA articolo: ERRORE {type(exc).__name__}: {exc}")
            return []

    with ThreadPoolExecutor(max_workers=min(6, len(article_urls) or 1)) as pool:
        futures = [pool.submit(read, item) for item in article_urls]
        for future in as_completed(futures):
            games.extend(future.result())
    return merge_games([], games)


# ---------------------------------------------------------------------------
# FIP WEB - controllo incrociato
# ---------------------------------------------------------------------------
def parse_fip_text(text, comp, label, teams):
    """Fallback testuale per FIP quando la tabella HTML non viene esposta."""
    text = clean(text)
    games = []
    matches = list(re.finditer(
        r"\b(\d{1,2}[ .](?:[A-Za-zÀ-ÿ]+|\d{1,2}[./-]202[67])[ .]?(?:202[67])?|\d{1,2}/\d{1,2}/202[67])\b.{0,40}?(?:ore\s*)?([01]?\d|2[0-3])[:.]([0-5]\d)",
        text, re.I,
    ))
    for i, m in enumerate(matches):
        date = parse_date(m.group(1))
        if not date:
            # Cerca una data numerica immediatamente prima dell'orario.
            prefix = text[max(0, m.start()-60):m.start()]
            dm = re.search(r"\b(\d{1,2}/\d{1,2}/202[67])\b", prefix)
            if dm:
                date = parse_date(dm.group(1))
        if not date:
            continue
        time = f"{int(m.group(2)):02d}:{m.group(3)}"
        block_end = matches[i+1].start() if i+1 < len(matches) else min(len(text), m.end()+260)
        block = text[max(0,m.start()-160):block_end]
        pair = find_pair(block, teams)
        if len(pair) == 2:
            g = make_game(date, time, pair[0], pair[1], comp, label, "", "FIP risultati ufficiali")
            if g:
                games.append(g)
    return merge_games([], games)


def parse_fip_page(url, comp, label, teams):
    try:
        soup = BeautifulSoup(fetch(url).text, "html.parser")
    except Exception as exc:
        print(f"FIP {comp}: ERRORE {type(exc).__name__}: {exc}")
        return []

    games = []
    for tr in soup.select("tr"):
        cells = [clean(x.get_text(" ", strip=True)) for x in tr.select("th,td")]
        if len(cells) < 3:
            continue
        joined = " | ".join(cells)
        date = parse_date(joined)
        if not date:
            continue
        pair = find_pair(joined, teams)
        if len(pair) != 2 and len(cells) >= 3:
            # FIP usa spesso il nome breve nelle colonne Casa/Ospite.
            possible = [canonical_team(c) for c in cells if c and not parse_date(c) and not parse_time(c)]
            possible = [c for c in possible if norm_team(c) not in {"casa", "ospite", "risultato"}]
            if len(possible) >= 2:
                pair = possible[:2]
        if len(pair) != 2:
            continue
        game = make_game(date, parse_time(joined), pair[0], pair[1], comp, label, "", "FIP risultati ufficiali")
        if game:
            games.append(game)

    if not games:
        games = parse_fip_text(clean(soup.get_text(" ", strip=True)), comp, label, teams)
    return merge_games([], games)


def parse_fip_results():
    """FIP per A e A2, interrogando le giornate della stagione con i parametri pubblici."""
    specs = [
        ("A1/M", "LBA", "LBA Serie A", LBA_TEAMS, 30),
        ("A2/M", "A2", "Serie A2", A2_TEAMS, 36),
    ]
    jobs = []
    for code, comp, label, teams, rounds in specs:
        for giornata in range(1, rounds + 1):
            q = {
                "codice_campionato": code,
                "comitato_codice": "",
                "group": "campionati-nazionali-maschili",
                "sesso": "M",
                "giornata": str(giornata),
            }
            query = requests.compat.urlencode(q)
            jobs.append((f"{FIP_RESULTS}?{query}", comp, label, teams))

    games = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(parse_fip_page, *job) for job in jobs]
        for future in as_completed(futures):
            try:
                games.extend(future.result())
            except Exception as exc:
                print(f"FIP giornata: ERRORE {type(exc).__name__}: {exc}")
    return merge_games([], games)

def discover_lba_game_urls():
    """Scopre i link /game/ dal calendario/news ufficiali LBA."""
    urls = []
    seen = set()
    for page in (LBA_CALENDAR, LBA_NEWS, LBA_HOME):
        try:
            soup = BeautifulSoup(fetch(page).text, "html.parser")
        except Exception:
            continue
        for a in soup.find_all("a", href=True):
            href = urljoin(page, a.get("href"))
            if not href.startswith("https://www.legabasket.it/game/"):
                continue
            href = href.split("?",1)[0].rstrip("/")
            if href in seen:
                continue
            seen.add(href)
            urls.append(href)
    return urls


def parse_lba_game_page(url):
    try:
        soup = BeautifulSoup(fetch(url).text, "html.parser")
    except Exception:
        return []
    text = clean(soup.get_text(" ", strip=True))
    pair = extract_lba_pair(text)
    date = parse_date(text)
    if len(pair) != 2 or not date:
        return []
    time = parse_time(text)
    # Limitiamo la ricerca dell'orario alla zona iniziale della pagina per
    # non prendere un orario appartenente a una news/video correlato.
    head = clean(text[:1800])
    time = parse_time(head) or time
    g = make_game(date, time, pair[0], pair[1], "LBA", "LBA Serie A", lba_watch(head), "LBA pagina gara ufficiale")
    return [g] if g else []


def parse_lba_official_game_pages():
    urls = discover_lba_game_urls()
    games = []
    # Il calendario completo puo' contenere molte gare: per l'aggiornamento
    # ogni 5 minuti bastano le pagine recentemente esposte dai link ufficiali.
    urls = urls[:80]
    if urls:
        with ThreadPoolExecutor(max_workers=min(10, len(urls))) as pool:
            futures = [pool.submit(parse_lba_game_page, u) for u in urls]
            for f in as_completed(futures):
                try:
                    games.extend(f.result())
                except Exception:
                    pass
    return merge_games([], games)


def discover_lba_team_urls():
    try:
        soup = BeautifulSoup(fetch(LBA_TEAMS_PAGE).text, "html.parser")
    except Exception as exc:
        print(f"LBA squadre: ERRORE {type(exc).__name__}: {exc}")
        return []
    out=[]; seen=set()
    for a in soup.find_all("a", href=True):
        href=urljoin(LBA_TEAMS_PAGE,a.get("href"))
        if not href.startswith("https://www.legabasket.it/protagonisti/squadre/"):
            continue
        if href.rstrip("/").endswith("/squadre") or href in seen:
            continue
        seen.add(href); out.append(href)
    return out


def parse_lba_team_page(url):
    try:
        soup=BeautifulSoup(fetch(url).text,"html.parser")
    except Exception:
        return []
    games=[]
    text=clean(soup.get_text(" ",strip=True))
    games.extend(parse_lba_text(text))
    for tr in soup.select("tr"):
        cells=[clean(x.get_text(" ",strip=True)) for x in tr.select("th,td")]
        joined=" | ".join(cells)
        date=parse_date(joined)
        if not date: continue
        pair=extract_lba_pair(joined)
        if len(pair)!=2: continue
        g=make_game(date,parse_time(joined),pair[0],pair[1],"LBA","LBA Serie A",lba_watch(joined),"LBA pagina squadra ufficiale")
        if g: games.append(g)
    return merge_games([],games)


def parse_lba_official_team_pages():
    urls=discover_lba_team_urls()
    games=[]
    if urls:
        with ThreadPoolExecutor(max_workers=min(10,len(urls))) as pool:
            futures=[pool.submit(parse_lba_team_page,u) for u in urls]
            for f in as_completed(futures):
                try: games.extend(f.result())
                except Exception: pass
    return merge_games([],games)


# ---------------------------------------------------------------------------
# EUROLEGUE / EUROCUP - feed ufficiale
# ---------------------------------------------------------------------------
def deep_find(obj, names):
    wanted = {n.casefold() for n in names}
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).casefold() in wanted and value not in (None, ""):
                return value
        for value in obj.values():
            found = deep_find(value, names)
            if found not in (None, ""):
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = deep_find(value, names)
            if found not in (None, ""):
                return found
    return None


def euro_team(value):
    if isinstance(value, dict):
        return value.get("name") or value.get("clubName") or value.get("teamName") or value.get("shortName")
    return value


def parse_euro_api(comp, season, label):
    url = EURO_API.format(competition=comp, season=season)
    try:
        response = fetch(url)
        payload = response.json()
    except Exception as exc:
        print(f"{label}: ERRORE {type(exc).__name__}: {exc}")
        return []

    rows = payload
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("games") or payload.get("results") or payload
    if isinstance(rows, dict):
        rows = rows.get("games") or rows.get("items") or []
    if not isinstance(rows, list):
        return []

    games = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        home = euro_team(row.get("home") or row.get("local") or row.get("homeTeam"))
        away = euro_team(row.get("away") or row.get("road") or row.get("awayTeam"))
        home = home or deep_find(row, ["homeName", "localName", "homeTeamName"])
        away = away or deep_find(row, ["awayName", "roadName", "awayTeamName"])
        date_value = deep_find(row, ["date", "gameDate", "gameDateTime", "startDate", "startTime"])
        date = parse_date(date_value)
        if not date and isinstance(date_value, str):
            iso = re.match(r"(2026|2027)-\d{2}-\d{2}", date_value)
            date = iso.group(0) if iso else None
        time_value = deep_find(row, ["time", "gameTime", "startTime", "startTimeLocal"])
        time = parse_time(time_value or date_value)
        if home and away and date:
            game = make_game(date, time, home, away, "EUROLEAGUE" if comp == "E" else "EUROCUP", label, "Programmazione TV da definire", "Euroleague Basketball API")
            if game:
                games.append(game)
    return merge_games([], games)


def validate_updater(final):
    """Controlli interni: nessun duplicato e nessun orario valido perso.
    Restituisce contatori utili nel log GitHub Actions.
    """
    keys = set()
    duplicates = 0
    for g in final:
        k = game_key(g)
        if k in keys:
            duplicates += 1
        keys.add(k)
    counts = {}
    timed = {}
    for g in final:
        comp = g.get("competition", "")
        counts[comp] = counts.get(comp, 0) + 1
        if g.get("time"):
            timed[comp] = timed.get(comp, 0) + 1
    return counts, timed, duplicates


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    try:
        old = json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else {}
    except Exception:
        old = {}

    old_games = old.get("games", [])
    final = list(old_games)
    report = []

    # 1) FIP: base calendario/orari per Serie A e Serie A2, tutte le giornate.
    fip_games = parse_fip_results()
    final = merge_games(final, fip_games)
    fip_counts = {}
    fip_timed = {}
    for g in fip_games:
        c = g.get("competition")
        fip_counts[c] = fip_counts.get(c, 0) + 1
        if g.get("time"):
            fip_timed[c] = fip_timed.get(c, 0) + 1
    report.append(f"FIP Serie A: {fip_counts.get('LBA',0)} gare, orari={fip_timed.get('LBA',0)}")
    report.append(f"FIP A2: {fip_counts.get('A2',0)} gare, orari={fip_timed.get('A2',0)}")

    # 2) A2: FIP + scansione strutturale delle sezioni ufficiali LNP.
    a2_cal = parse_lnp_calendar(LNP_A2_CALENDAR, "A2", A2_TEAMS)
    a2_teams = lnp_team_pages("A2", LNP_A2_TEAMS_PAGE, A2_TEAMS)
    a2_news = recent_lnp_articles(LNP_A2_NEWS, "A2", A2_TEAMS)
    a2_crawl, a2_pages = crawl_lnp_relevant("A2")
    a2_games = a2_cal + a2_teams + a2_news + a2_crawl
    final = merge_games(final, a2_games)
    report.append(f"LNP A2: calendario={len(a2_cal)} squadre={len(a2_teams)} news={len(a2_news)} crawler={len(a2_crawl)} pagine={a2_pages}")

    # 3) Serie B: calendario + squadre + news + scansione strutturale LNP.
    b_cal = parse_lnp_calendar(LNP_B_CALENDAR, "B", B_TEAMS)
    b_teams = lnp_team_pages("B", LNP_B_TEAMS_PAGE, B_TEAMS)
    b_news = recent_lnp_articles(LNP_B_NEWS, "B", B_TEAMS)
    b_crawl, b_pages = crawl_lnp_relevant("B")
    b_games = b_cal + b_teams + b_news + b_crawl
    final = merge_games(final, b_games)
    report.append(f"LNP B: calendario={len(b_cal)} squadre={len(b_teams)} news={len(b_news)} crawler={len(b_crawl)} pagine={b_pages}")

    # 4) LBA: FIP + calendario attuale /1/serie-a + squadre/gare/news + crawler.
    lba_calendar = parse_lba_calendar()
    lba_teams = parse_lba_official_team_pages()
    lba_games_pages = parse_lba_official_game_pages()
    lba_news = parse_lba_recent_news()
    lba_crawl, lba_pages = crawl_lba_relevant()
    lba_games = lba_calendar + lba_teams + lba_games_pages + lba_news + lba_crawl
    final = merge_games(final, lba_games)
    report.append(f"LBA: calendario={len(lba_calendar)} squadre={len(lba_teams)} gare={len(lba_games_pages)} news={len(lba_news)} crawler={len(lba_crawl)} pagine={lba_pages}")

    # 3) EuroLeague / EuroCup: feed ufficiale.
    euroleague = parse_euro_api("E", "E2026", "EuroLeague")
    eurocup = parse_euro_api("U", "U2026", "EuroCup")
    final = merge_games(final, euroleague)
    final = merge_games(final, eurocup)
    report.append(f"EuroLeague ufficiale: {len(euroleague)} gare")
    report.append(f"EuroCup ufficiale: {len(eurocup)} gare")

    report.append("Fonti web ufficiali: FIP A/A2 + LNP A2/B (calendario, squadre, news) + LBA (FIP, calendario, squadre, gare, news) + EuroLeague/EuroCup")

    counts, timed, duplicates = validate_updater(final)
    report.append(f"Controllo duplicati: {duplicates}")
    report.append("Orari acquisiti: " + ", ".join(f"{k}={timed.get(k,0)}/{counts.get(k,0)}" for k in ("LBA","A2","B","EUROLEAGUE","EUROCUP")))
    today_local = datetime.now().astimezone().date().isoformat()
    for comp in ("LBA", "A2", "B"):
        missing = [g for g in final if g.get("competition") == comp and g.get("date", "") >= today_local and not g.get("time")]
        report.append(f"ATTENZIONE {comp}: gare future senza orario={len(missing)}")

    final.sort(key=lambda game: (
        game.get("date", "9999-99-99"),
        game.get("time") or "99:99",
        game.get("competition", ""),
        game.get("home", ""),
    ))

    out = {
        "season": "2026/27",
        "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "games": final,
        "source_report": report,
    }
    DATA.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    for line in report:
        print(line)
    print(f"Totale gare nel database: {len(final)}")


if __name__ == "__main__":
    main()
