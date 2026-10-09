#!/usr/bin/env python3
"""Basket TV updater corretto.

Il file storico viene conservato come update_legacy.py perché contiene i PDF
ufficiali incorporati e i parser originari. Questo file corregge la scansione,
la normalizzazione, l'abbinamento PDF, la lettura dinamica LBA e la validazione.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from urllib.parse import urljoin, urlparse

try:
    import update_legacy as legacy
except Exception as exc:
    print("ERRORE: manca update_legacy.py, la copia del precedente update.py che contiene i PDF incorporati.")
    print(f"Dettaglio: {type(exc).__name__}: {exc}")
    sys.exit(1)

# I timeout e i limiti sono volutamente più bassi: il vecchio crawler visitava
# fino a 500 pagine per dominio, seguendo anche intere sitemap.
legacy.TIMEOUT = 10
legacy.CRAWL_MAX_PAGES = 35
legacy.CRAWL_MAX_DEPTH = 2

_original_fetch = legacy.fetch
_original_merge_games = legacy.merge_games
_original_source_priority = legacy.source_priority
_original_canonical_team = legacy.canonical_team
_original_parse_lba_calendar = legacy.parse_lba_calendar
_original_validate_updater = legacy.validate_updater

EXTRA_ALIASES = {
    "BC Roma SPQR": "BC Roma",
    "Virtus Bologna": "Virtus Costa Bologna",
    "Napoli Basket": "Napoli Basketball",
    "Napolibasket": "Napoli Basketball",
    "Aquila Trento": "Dolomiti Energia Trentino",
    "Reyer Venezia": "Umana Reyer Venezia",
    "Olimpia Milano": "Armani Olimpia Milano",
    "Old Wild West Udine": "APU Old Wild West Udine",
    "S. Bernardo Cantù": "Acqua S.Bernardo Cantù",
    "Nutribullet Treviso": "Nutribullet Treviso Basket",
    "Bertram Tortona": "Bertram Derthona Tortona",
    "Reggio Emilia": "UNA Hotels Reggio Emilia",
    "Scafati": "Longobardi Scafati Basket",
    "Umana Venezia Mestre": "Umana Reyer Venezia",
}
ALL_ALIASES = dict(getattr(legacy, "ALIASES", {}))
ALL_ALIASES.update(EXTRA_ALIASES)


def _ascii_key(value: str) -> str:
    value = legacy.clean(value).casefold()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", value)


_ALIAS_LOOKUP = {_ascii_key(k): v for k, v in ALL_ALIASES.items()}


def canonical_team(value):
    cleaned = legacy.clean(value)
    target = _ALIAS_LOOKUP.get(_ascii_key(cleaned))
    if target:
        # Applica una seconda volta gli alias già presenti, se necessario.
        return _ALIAS_LOOKUP.get(_ascii_key(target), target)
    return _original_canonical_team(cleaned)


def norm_team(value):
    return _ascii_key(canonical_team(value))


legacy.canonical_team = canonical_team
legacy.norm_team = norm_team


def fetch(url, timeout=10):
    return _original_fetch(url, timeout=min(int(timeout or 10), 10))


legacy.fetch = fetch


def source_priority(source):
    s = legacy.clean(source).casefold()
    if "lba calendario browser" in s:
        return 145
    if "fip browser" in s:
        return 135
    return _original_source_priority(source)


legacy.source_priority = source_priority


def _obviously_not_a_team(name):
    s = legacy.clean(name).casefold()
    bad_fragments = (
        "live ", "diretta", "preview", "interrotta", "intervallo",
        "primo quarto", "secondo quarto", "terzo quarto", "quarto quarto",
        "dove in tv", "ore 20:", "ore 21:", "ore 18:", "ore 19:",
    )
    return any(fragment in s for fragment in bad_fragments)


def merge_games(base, updates):
    merged = _original_merge_games(base, updates)
    result = []
    lba_allowed = {norm_team(x) for x in getattr(legacy, "LBA_TEAMS", [])}
    for game in merged:
        home = game.get("home", "")
        away = game.get("away", "")
        nh, na = norm_team(home), norm_team(away)
        if not nh or not na or nh == na:
            continue
        if _obviously_not_a_team(home) or _obviously_not_a_team(away):
            continue
        # In LBA erano entrati titoli di articoli/live di altre competizioni.
        # Per la massima serie accettiamo solo nomi ufficiali o alias noti.
        if game.get("competition") == "LBA" and (nh not in lba_allowed or na not in lba_allowed):
            continue
        result.append(game)
    return result


legacy.merge_games = merge_games


def crawl_official_site(seeds, domain, path_keywords, max_pages=None, max_depth=None):
    """Crawler mirato: ignora sitemap e limita profondità e numero di pagine."""
    page_limit = min(int(max_pages or legacy.CRAWL_MAX_PAGES), 35)
    depth_limit = min(int(max_depth or legacy.CRAWL_MAX_DEPTH), 2)
    queue = []
    for url in seeds:
        if "sitemap" not in urlparse(url).path.casefold():
            queue.append((url, 0))
    seen, pages = set(), []
    domain_host = urlparse(domain).netloc.casefold()
    keywords = [str(k).casefold() for k in path_keywords]

    while queue and len(pages) < page_limit:
        url, depth = queue.pop(0)
        url = url.split("#", 1)[0]
        parsed = urlparse(url)
        if url in seen or depth > depth_limit or parsed.netloc.casefold() != domain_host:
            continue
        if "sitemap" in parsed.path.casefold():
            continue
        seen.add(url)
        try:
            response = fetch(url)
            soup = legacy.BeautifulSoup(response.text, "html.parser")
        except Exception as exc:
            print(f"Crawler salta {url}: {type(exc).__name__}")
            continue
        pages.append((url, soup))
        if depth >= depth_limit:
            continue
        for a in soup.find_all("a", href=True):
            href = urljoin(url, a.get("href", "")).split("#", 1)[0]
            hp = urlparse(href)
            if hp.netloc.casefold() != domain_host or href in seen or "sitemap" in hp.path.casefold():
                continue
            searchable = (hp.path + " " + legacy.clean(a.get_text(" ", strip=True))).casefold()
            if any(k in searchable for k in keywords):
                queue.append((href, depth + 1))
    print(f"Crawler {domain_host}: {len(pages)} pagine mirate")
    return pages


legacy.crawl_official_site = crawl_official_site


def discover_lnp_team_urls(index_url, prefix):
    """Scopre le pagine squadra da /serie/1/... (A2) o /serie/4/... (B)."""
    try:
        soup = legacy.BeautifulSoup(fetch(index_url).text, "html.parser")
    except Exception as exc:
        print(f"LNP {prefix} squadre: {type(exc).__name__}: {exc}")
        return []
    target_id = "1" if prefix == "serie-a2" else "4"
    base_host = urlparse("https://www.legapallacanestro.com/").netloc
    urls, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(index_url, a["href"]).split("#", 1)[0]
        parsed = urlparse(href)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if parsed.netloc != base_host or len(parts) != 3:
            continue
        if parts[0] != "serie" or parts[1] != target_id:
            continue
        if parts[2].casefold() in {"squadre", "calendario", "classifica", "girone"}:
            continue
        if href not in seen:
            seen.add(href)
            urls.append(href)
    print(f"LNP {prefix}: trovate {len(urls)} pagine squadra")
    return urls


legacy.discover_lnp_team_urls = discover_lnp_team_urls


def _team_similarity(a, b):
    ka, kb = norm_team(a), norm_team(b)
    if not ka or not kb:
        return 0.0
    if ka == kb:
        return 1.0
    seq = SequenceMatcher(None, ka, kb).ratio()
    ta = set(re.findall(r"[a-z0-9]+", ka))
    tb = set(re.findall(r"[a-z0-9]+", kb))
    overlap = len(ta & tb) / max(1, len(ta | tb))
    containment = 0.92 if ka in kb or kb in ka else 0.0
    return max(seq, overlap, containment)


def merge_pdf_only_for_missing_times(final, pdf_games):
    """Completa i soli orari mancanti con un abbinamento prudente per data e squadre.

    Prima cerca l'abbinamento esatto dopo la normalizzazione; poi prova il
    confronto fuzzy solo se entrambe le squadre coincidono con alta confidenza
    e la migliore partita è chiaramente separata dalle alternative.
    """
    by_comp_date = defaultdict(list)
    for game in final:
        if game.get("date") and game.get("competition"):
            by_comp_date[(game["competition"], game["date"])].append(game)

    filled = 0
    ambiguous = 0
    for pdf in pdf_games or []:
        if not pdf.get("time") or not pdf.get("date") or not pdf.get("competition"):
            continue
        ph, pa = pdf.get("home", ""), pdf.get("away", "")
        candidates = []
        for current in by_comp_date.get((pdf["competition"], pdf["date"]), []):
            if current.get("time"):
                continue
            ch, ca = current.get("home", ""), current.get("away", "")
            direct = (_team_similarity(ph, ch), _team_similarity(pa, ca))
            reverse = (_team_similarity(ph, ca), _team_similarity(pa, ch))
            scores = direct if sum(direct) >= sum(reverse) else reverse
            low, avg = min(scores), sum(scores) / 2
            if low >= 0.68 and avg >= 0.78:
                candidates.append((avg + low * 0.05, current, low))
        candidates.sort(key=lambda x: x[0], reverse=True)
        if not candidates:
            continue
        if len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 0.08:
            ambiguous += 1
            continue
        _, current, _ = candidates[0]
        current["time"] = pdf["time"]
        current["source"] = pdf.get("source", "PDF fallback")
        filled += 1

    print(f"PDF fallback: recuperati {filled} orari mancanti; abbinamenti ambigui ignorati: {ambiguous}")
    return filled


legacy.merge_pdf_only_for_missing_times = merge_pdf_only_for_missing_times


def _parse_lba_rendered_html(html, body_text=""):
    soup = legacy.BeautifulSoup(html or "", "html.parser")
    games = []
    for tr in soup.select("tr"):
        cells = [legacy.clean(x.get_text(" ", strip=True)) for x in tr.select("th,td")]
        if len(cells) < 2:
            continue
        joined = " | ".join(cells)
        date = legacy.parse_date(joined)
        if not date:
            continue
        pair = legacy.extract_lba_pair(joined)
        if len(pair) != 2:
            continue
        game = legacy.make_game(date, legacy.parse_time(joined), pair[0], pair[1],
                                "LBA", "LBA Serie A", legacy.lba_watch(joined),
                                "LBA calendario browser")
        if game:
            games.append(game)
    visible_text = body_text or legacy.clean(soup.get_text(" ", strip=True))
    try:
        games.extend(legacy.parse_lba_text(visible_text))
    except Exception:
        pass
    return merge_games([], games)


def parse_lba_calendar():
    """Legge il calendario LBA e le pagine calendario delle singole squadre con Chromium.

    Il calendario generale spesso mostra solo la giornata selezionata; le pagine
    ufficiali delle squadre permettono di recuperare anche gli orari delle giornate
    successive. Le 23:00 sulle gare future sono un segnaposto LBA, non un orario reale.
    """
    static_games = []
    try:
        static_games = _original_parse_lba_calendar()
    except Exception as exc:
        print(f"LBA calendario statico: {type(exc).__name__}: {exc}")

    dynamic_games = []
    team_calendar_urls = set()
    calendar_url = getattr(legacy, "LBA_CALENDAR", "https://www.legabasket.it/calendario/1/serie-a")
    team_index_url = getattr(legacy, "LBA_TEAMS_PAGE", "https://www.legabasket.it/protagonisti/squadre")

    try:
        from urllib.parse import urljoin, urlparse
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(locale="it-IT")
            for url in (calendar_url, team_index_url):
                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=18000)
                    if response is not None and response.status >= 400:
                        print(f"LBA browser salta {url}: HTTP {response.status}")
                        continue
                    page.wait_for_timeout(400)
                    html = page.content()
                    try:
                        body_text = page.locator("body").inner_text(timeout=4000)
                    except Exception:
                        body_text = ""
                    dynamic_games.extend(_parse_lba_rendered_html(html, body_text))

                    if url == team_index_url:
                        soup = legacy.BeautifulSoup(html, "html.parser")
                        for a in soup.find_all("a", href=True):
                            href = urljoin(team_index_url, a.get("href", "")).split("?", 1)[0]
                            parsed = urlparse(href)
                            if parsed.netloc.casefold() != "www.legabasket.it":
                                continue
                            path = parsed.path.rstrip("/")
                            marker = "/protagonisti/squadre/"
                            if marker not in path or path.endswith("/squadre"):
                                continue
                            tail = path.split(marker, 1)[1].split("/")
                            if len(tail) < 3 or not tail[0].isdigit() or not tail[1].isdigit():
                                continue
                            if not path.endswith("/calendario"):
                                path += "/calendario"
                            team_calendar_urls.add(f"https://www.legabasket.it{path}")
                except Exception as exc:
                    print(f"LBA browser salta {url}: {type(exc).__name__}")

            # Ogni calendario squadra contiene anche le prossime giornate, non solo quella corrente.
            for url in sorted(team_calendar_urls)[:20]:
                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=12000)
                    if response is not None and response.status >= 400:
                        continue
                    page.wait_for_timeout(250)
                    html = page.content()
                    try:
                        body_text = page.locator("body").inner_text(timeout=3000)
                    except Exception:
                        body_text = ""
                    dynamic_games.extend(_parse_lba_rendered_html(html, body_text))
                except Exception as exc:
                    print(f"LBA calendario squadra salta {url}: {type(exc).__name__}")
            browser.close()
    except Exception as exc:
        print(f"LBA browser non disponibile/non riuscito: {type(exc).__name__}: {exc}")

    # La LBA usa 23:00 come segnaposto in alcune righe future ancora da programmare.
    today = datetime.now().astimezone().date().isoformat()
    for game in dynamic_games:
        if game.get("competition") == "LBA" and game.get("date", "") >= today and game.get("time") == "23:00":
            game["time"] = ""

    result = merge_games(static_games, dynamic_games)
    horizon = (datetime.now().astimezone().date() + timedelta(days=14)).isoformat()
    upcoming = [g for g in result if g.get("competition") == "LBA" and today <= g.get("date", "") <= horizon]
    timed = sum(bool(g.get("time")) for g in upcoming)
    print(f"LBA calendario/team browser: {len(dynamic_games)} gare grezze; calendari squadre={len(team_calendar_urls)}; prossime 14gg={timed}/{len(upcoming)} con orario")
    return result

legacy.parse_lba_calendar = parse_lba_calendar
def _fip_parse_rendered(html, comp, label, teams):
    soup = legacy.BeautifulSoup(html or "", "html.parser")
    games = []
    for tr in soup.select("tr"):
        cells = [legacy.clean(x.get_text(" ", strip=True)) for x in tr.select("th,td")]
        if len(cells) < 3:
            continue
        joined = " | ".join(cells)
        date = legacy.parse_date(joined)
        if not date:
            continue
        pair = legacy.find_pair(joined, teams)
        if len(pair) != 2:
            possible = [canonical_team(c) for c in cells if c and not legacy.parse_date(c) and not legacy.parse_time(c)]
            possible = [c for c in possible if norm_team(c) not in {"casa", "ospite", "risultato"}]
            if len(possible) >= 2:
                pair = possible[:2]
        if len(pair) != 2:
            continue
        g = legacy.make_game(date, legacy.parse_time(joined), pair[0], pair[1], comp, label,
                             "", "FIP browser risultati ufficiali")
        if g:
            games.append(g)
    if not games:
        body = legacy.clean(soup.get_text(" ", strip=True))
        try:
            games = legacy.parse_fip_text(body, comp, label, teams)
            for game in games:
                game["source"] = "FIP browser risultati ufficiali"
        except Exception:
            games = []
    return merge_games([], games)


def parse_fip_results():
    """Usa il parser HTTP esistente e il browser solo come recupero mirato.

    Le 66 giornate restano interrogate via HTTP in parallelo. Se le prime
    giornate future non espongono dati in HTML statico, vengono verificate con
    un unico browser riutilizzato, senza avviare un browser per ogni pagina.
    """
    static_games = _original_parse_fip_results_impl()
    # Per le sole giornate iniziali, riprova in modalità browser le pagine che
    # non hanno restituito gare o orari; il resto resta coperto dal parser HTTP.
    specs = [
        ("A1/M", "LBA", "LBA Serie A", legacy.LBA_TEAMS, 6),
        ("A2/M", "A2", "Serie A2", legacy.A2_TEAMS, 8),
    ]
    jobs = []
    for code, comp, label, teams, rounds in specs:
        for giornata in range(1, rounds + 1):
            q = {"codice_campionato": code, "comitato_codice": "",
                 "group": "campionati-nazionali-maschili", "sesso": "M",
                 "giornata": str(giornata)}
            query = legacy.requests.compat.urlencode(q)
            url = f"{legacy.FIP_RESULTS}?{query}"
            today = datetime.now().astimezone().date()
            horizon = (today + timedelta(days=14)).isoformat()
            near = [g for g in static_games if g.get("competition") == comp
                    and today.isoformat() <= g.get("date", "") <= horizon]
            near_timed = sum(bool(g.get("time")) for g in near)
            # Se la copertura delle sole gare imminenti è già buona, non serve
            # ripetere le stesse pagine con Chromium.
            if len(near) >= 6 and near_timed / len(near) >= 0.65:
                continue
            jobs.append((url, comp, label, teams))
    if not jobs:
        return static_games
    try:
        from playwright.sync_api import sync_playwright
        supplements = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(locale="it-IT")
            try:
                for url, comp, label, teams in jobs:
                    try:
                        response = page.goto(url, wait_until="domcontentloaded", timeout=12000)
                        if response is not None and response.status >= 400:
                            continue
                        try:
                            page.wait_for_timeout(300)
                            html = page.content()
                        except Exception:
                            continue
                        supplements.extend(_fip_parse_rendered(html, comp, label, teams))
                    except Exception as exc:
                        print(f"FIP browser salta una pagina: {type(exc).__name__}")
            finally:
                browser.close()
        print(f"FIP browser: recuperate {len(supplements)} gare supplementari")
        return merge_games(static_games, supplements)
    except Exception as exc:
        print(f"FIP browser non disponibile: {type(exc).__name__}: {exc}")
        return static_games


# Salva la funzione prima di sostituirla, così non c'è ricorsione.
_original_parse_fip_results_impl = legacy.parse_fip_results
legacy._original_parse_fip_results = _original_parse_fip_results_impl
legacy.parse_fip_results = parse_fip_results


def validate_updater(final):
    counts, timed, duplicates = _original_validate_updater(final)
    if duplicates:
        raise RuntimeError(f"Aggiornamento annullato: rilevati {duplicates} duplicati.")
    today = datetime.now().astimezone().date()
    limit = today + timedelta(days=14)
    failures = []
    for comp, minimum in (("LBA", 0.65), ("A2", 0.65), ("B", 0.65)):
        upcoming = [g for g in final if g.get("competition") == comp and g.get("date")]
        upcoming = [g for g in upcoming if today.isoformat() <= g["date"] <= limit.isoformat()]
        # Non bloccare per una singola gara rinviata o non ancora calendarizzata.
        if len(upcoming) < 6:
            continue
        with_time = sum(bool(g.get("time")) for g in upcoming)
        ratio = with_time / len(upcoming)
        if ratio < minimum:
            failures.append(f"{comp}: {with_time}/{len(upcoming)} gare dei prossimi 14 giorni hanno l'orario")
    if failures:
        raise RuntimeError("Pubblicazione bloccata: copertura orari insufficiente nelle prossime due settimane. " + "; ".join(failures))
    return counts, timed, duplicates


legacy.validate_updater = validate_updater

if __name__ == "__main__":
    legacy.main()

