#!/usr/bin/env python3
import json, re, sys, subprocess
from pathlib import Path
from datetime import datetime, timezone

DATA=Path("data.json")
HEADERS={"User-Agent":"Mozilla/5.0 BasketTV/1.0"}

LBA_URL="https://www.legabasket.it/competizioni"
A2_PDF="https://static.legapallacanestro.com/sites/default/files/editor/calendario_serie_a2_oww_2026-27.pdf"
B_A_PDF="https://static.legapallacanestro.com/sites/default/files/editor/calendario_b_naz._gir._a_2026-27.pdf"
B_B_PDF="https://static.legapallacanestro.com/sites/default/files/editor/calendario_b_naz._gir._b_2026-27.pdf"
LNP_HOME="https://www.legapallacanestro.com/"
EURO_API="https://api-live.euroleague.net/v2/competitions/{comp}/seasons/{season}/games"

def ensure(mod,pkg=None):
    try:return __import__(mod)
    except ImportError:
        subprocess.check_call([sys.executable,"-m","pip","install","-q",pkg or mod])
        return __import__(mod)
requests=ensure("requests")
bs4=ensure("bs4","beautifulsoup4")
BeautifulSoup=bs4.BeautifulSoup
pypdf=ensure("pypdf")
PdfReader=pypdf.PdfReader

def clean(x): return re.sub(r"\s+"," ",str(x or "").replace("\xa0"," ")).strip()
def date_from(x):
    s=clean(x)
    m=re.search(r"\b(\d{1,2})[./-](\d{1,2})[./-](2026|2027)\b",s)
    if m:
        d,mo,y=m.groups();return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    m=re.search(r"\b(2026|2027)-(\d{1,2})-(\d{1,2})\b",s)
    if m:
        y,mo,d=m.groups();return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return None
def time_from(x):
    m=re.search(r"\b([01]?\d|2[0-3])[:.][0-5]\d\b",clean(x))
    return m.group(0).replace(".",":") if m else ""
def make(date,time,home,away,comp,label,watch,source):
    if not date or not home or not away:return None
    return {"date":date,"time":time or "","home":clean(home),"away":clean(away),
            "competition":comp,"competition_label":label,"watch":watch,"source":source}
def dedupe(gs):
    d={}
    for g in gs:d[(g["date"],g["time"],g["home"],g["away"],g["competition"])]=g
    return list(d.values())
def get(url):
    r=requests.get(url,headers=HEADERS,timeout=60);r.raise_for_status();return r

# ---------- LBA ----------
def lba():
    soup=BeautifulSoup(get(LBA_URL).text,"html.parser");out=[]
    for tr in soup.select("tr"):
        cells=[clean(c.get_text(" ",strip=True)) for c in tr.select("th,td")]
        row=" | ".join(cells);date=date_from(row)
        if not date:continue
        tm=time_from(row)
        vals=[c for c in cells if c and not date_from(c) and not time_from(c)]
        if len(vals)<2:continue
        # In the current official LBA table the first two non-date/non-time
        # values are home and away.
        home,away=vals[0],vals[1]
        low=row.lower();tv=[]
        if "lbatv" in low or "lba tv" in low:tv.append("LBA TV")
        if "skysportbasket" in low or "sky sport" in low:tv.append("Sky Sport")
        if "cielo" in low:tv.append("Cielo")
        if "dazn" in low:tv.append("DAZN")
        g=make(date,tm,home,away,"LBA","LBA Serie A"," · ".join(tv) or "LBA TV","LBA")
        if g:out.append(g)
    return dedupe(out)

# ---------- LNP ----------
A2_TEAMS=[
"Halley Campania Avellino Basket","Flats Service Fortitudo Bologna","Valtur Brindisi",
"Paperdi JuveCaserta 2021","Sella Cento","UEB Gesteco Cividale","Ferraroni Juvi Cremona 1952",
"Unieuro Forlì","Libertas Livorno 1947","Gemini Mestre","Wegreenit Urania Milano",
"La T Tecnica Gema Montecatini","Victoria Libertas Pesaro","Lumos Pistoia Basket",
"RSR Sebastiani Rieti","Dole Basket Rimini","Crifo Wines Ruvo di Puglia",
"Banco di Sardegna Sassari","Reale Mutua Torino","ELAchem Vigevano 1955"]
B_TEAMS=[
"Moncada Energy Agrigento","A2A Leonessa Brescia","Infodrive Capo d'Orlando","Rimadesio Desio",
"Adamant Ferrara","Fiorenzuola Bees","Andrea Costa Imola","SAE Scientifica-Soevis Legnano Knights",
"Luxarm Lumezzane","Paffoni Fulgor Basket Omegna","Logiman Orzinuovi","UCC Assigeco Piacenza",
"Siaz Basket Piazza Armerina","Pallacanestro Viola Reggio Calabria","LTC Group Sangiorgese Basket",
"Rucker San Vendemiano","TAV Treviglio Brianza Basket","S4 Energia Vicenza",
"Felice Scandone Avellino","Umana San Giobbe Chiusi","Ristopro Fabriano","Tema Sinergie Faenza",
"Benacquista Assicurazioni Latina","Pielle Livorno","Basketball Club Lucca","FABO Herons Montecatini",
"PSA Napoli Est","Consultinvest Loreto Pesaro","Solbat Golfo Piombino","Consorzio Leonardo Dany Quarrata",
"OraSì Ravenna","Luiss Roma","Virtus GVM Roma 1960","Liofilchem Roseto",
"Allianz Pazienza Cestistica San Severo","Mens Sana Basketball Siena"]

def pdf_text(url):
    r=get(url);p=Path("_basket_tv.pdf");p.write_bytes(r.content)
    try:return "\n".join(page.extract_text() or "" for page in PdfReader(str(p)).pages)
    finally:
        try:p.unlink()
        except:pass

def lnp_pdf(url,comp,label,teams):
    text=pdf_text(url).replace("\r","\n")
    dates=list(re.finditer(r"\b(\d{1,2})[./-](\d{1,2})[./-](2026|2027)\b",text))
    pats=[(t,re.compile(re.escape(t),re.I)) for t in sorted(set(teams),key=len,reverse=True)]
    out=[]
    for i,m in enumerate(dates):
        d,mo,y=m.groups();date=f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        block=clean(text[m.end():(dates[i+1].start() if i+1<len(dates) else len(text))])
        found=[]
        for team,p in pats:
            z=p.search(block)
            if z:found.append((z.start(),team))
        found.sort()
        if len(found)<2:continue
        tm=time_from(block)
        g=make(date,tm,found[0][1],found[1][1],comp,label,"LNP Pass","LNP")
        if g:out.append(g)
    return dedupe(out)

def lnp_news_times(games):
    # LNP news frequently announces the definitive TV/time schedule.
    # We only change a game's time when an article explicitly contains both
    # team names and a clock; otherwise the PDF date remains unchanged.
    try:soup=BeautifulSoup(get(LNP_HOME).text,"html.parser")
    except Exception:return games
    texts=[clean(x.get_text(" ",strip=True)) for x in soup.find_all(["article","div","p","li"])]
    for g in games:
        if g["time"]:continue
        key1=g["home"].lower();key2=g["away"].lower()
        for t in texts:
            low=t.lower()
            if key1 in low and key2 in low:
                tm=time_from(t)
                if tm:g["time"]=tm;break
    return games

# ---------- EuroLeague / EuroCup ----------
def deep(obj,names):
    if isinstance(obj,dict):
        for k,v in obj.items():
            if k.lower() in {n.lower() for n in names} and v not in (None,""):return v
        for v in obj.values():
            z=deep(v,names)
            if z not in (None,""):return z
    elif isinstance(obj,list):
        for v in obj:
            z=deep(v,names)
            if z not in (None,""):return z
    return None
def team_name(v):
    if isinstance(v,str):return clean(v)
    if isinstance(v,dict):
        for k in ("name","clubPermanentName","clubName","teamName","displayName"):
            if v.get(k):return clean(v[k])
        return team_name(v.get("club") or v.get("team"))
    return ""
def euro(comp,season,label):
    r=get(EURO_API.format(comp=comp,season=season));payload=r.json()
    rows=payload.get("data",[]) if isinstance(payload,dict) else payload
    out=[]
    for x in rows if isinstance(rows,list) else []:
        if not isinstance(x,dict):continue
        local=x.get("local") or x.get("home") or x.get("homeTeam")
        road=x.get("road") or x.get("away") or x.get("awayTeam")
        home,away=team_name(local),team_name(road)
        if not home:home=clean(deep(x,["localName","homeName","localTeamName"]))
        if not away:away=clean(deep(x,["roadName","awayName","roadTeamName"]))
        dt=deep(x,["date","gameDate","startDate","startTime","dateTime"])
        date=date_from(dt)
        tm=time_from(dt) or time_from(deep(x,["time","gameTime","startTimeLocal"]))
        g=make(date,tm,home,away,comp,label,"Sky Sport / NOW","Euroleague Basketball")
        if g:out.append(g)
    return dedupe(out)

def main():
    try:old=json.loads(DATA.read_text(encoding="utf-8"))
    except Exception:old={}
    old_games=old.get("games",[])
    fetched=[];report=[]

    jobs=[
        ("LBA","LBA Serie A",lba),
        ("A2","Serie A2",lambda:lnp_pdf(A2_PDF,"A2","Serie A2",A2_TEAMS)),
        ("B","Serie B Nazionale",lambda:lnp_pdf(B_A_PDF,"B","Serie B Nazionale",B_TEAMS)+lnp_pdf(B_B_PDF,"B","Serie B Nazionale",B_TEAMS)),
        ("EUROLEAGUE","EuroLeague",lambda:euro("E","E2026","EuroLeague")),
        ("EUROCUP","EuroCup",lambda:euro("U","U2026","EuroCup")),
    ]
    for comp,label,fn in jobs:
        try:
            gs=fn()
            if comp in ("A2","B"):gs=lnp_news_times(gs)
            fetched+=gs;report.append(f"{label}: {len(gs)} gare")
        except Exception as e:
            report.append(f"{label}: ERRORE {type(e).__name__}: {e}")

    # Preserve the old competition data if a source temporarily fails.
    old_by={}
    for g in old_games:old_by.setdefault(g.get("competition"),[]).append(g)
    new_by={}
    for g in fetched:new_by.setdefault(g["competition"],[]).append(g)
    thresholds={"LBA":8,"A2":100,"B":300,"EUROLEAGUE":100,"EUROCUP":50}
    final=[]
    for comp in ("LBA","A2","B","EUROLEAGUE","EUROCUP"):
        ng=new_by.get(comp,[])
        final += ng if len(ng)>=thresholds[comp] else old_by.get(comp,[])
    # Keep any future/extra records not belonging to the five managed competitions.
    for comp,gs in old_by.items():
        if comp not in ("LBA","A2","B","EUROLEAGUE","EUROCUP"):final+=gs

    final=dedupe(final)
    final.sort(key=lambda g:(g.get("date",""),g.get("time","99:99"),g.get("competition",""),g.get("home","")))
    DATA.write_text(json.dumps({
        "season":"2026/27",
        "updated_at":datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "games":final,
        "source_report":report
    },ensure_ascii=False,indent=2))
    print("\n".join(report))
    print("Totale:",len(final))

if __name__=="__main__":main()
