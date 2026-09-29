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
A2_PDF="https://static.legapallacanestro.com/sites/default/files/editor/calendario_serie_a2_oww_2026-27.pdf"
B_A_PDF="https://static.legapallacanestro.com/sites/default/files/editor/calendario_b_naz._gir._a_2026-27.pdf"
B_B_PDF="https://static.legapallacanestro.com/sites/default/files/editor/calendario_b_naz._gir._b_2026-27.pdf"
A2_CAL="https://www.legapallacanestro.com/serie/1/calendario"
B_CAL_A="https://www.legapallacanestro.com/serie/4/calendario"
B_CAL_B="https://www.legapallacanestro.com/serie/4/calendario?qt-campionato-selector=1"

A2_TEAMS=[
"Halley Campania Avellino Basket","Flats Service Fortitudo Bologna","Valtur Brindisi","Juvecaserta 2021","Sella Cento","UEB Gesteco Cividale","Ferraroni Juvi Cremona 1952","Unieuro Forlì","Libertas Livorno 1947","Gemini Mestre","Wegreenit Urania Milano","La T Tecnica Gema Montecatini","CMT Orange Tools Pesaro","Lumos Pistoia Basket","RSR Sebastiani Rieti","Dole Basket Rimini","Crifo Wines Ruvo di Puglia","Banco di Sardegna Sassari","Reale Mutua Torino","Elachem Vigevano 1955"]
B_TEAMS=[
"Moncada Energy Agrigento","A2A Leonessa Brescia","Infodrive Capo d'Orlando","Rimadesio Desio","Adamant Ferrara","Fiorenzuola Bees","Andrea Costa Imola","SAE Scientifica-Soevis Legnano Knights","LuxArm Lumezzane","Paffoni Fulgor Basket Omegna","Logiman Orzinuovi","UCC Assigeco Piacenza","Siaz Basket Piazza Armerina","Redel Reggio Calabria","LTC Group Sangiorgese Basket","Rucker San Vendemiano","TAV Treviglio Brianza Basket","S4 Energia Vicenza",
"Felice Scandone Avellino","Umana San Giobbe Chiusi","Ristopro Fabriano","Tema Sinergie Faenza","Benacquista Assicurazioni Latina","Verodol CBD Pielle Livorno","Basketball Club Lucca","Fabo Herons Montecatini","PSA Napoli Est","Consultinvest Loreto Pesaro","Solbat Golfo Piombino","Consorzio Leonardo Dany Quarrata","OraSì Ravenna","Luiss Roma","Virtus GVM Roma 1960","Liofilchem Roseto","Allianz Pazienza Cestistica San Severo","Sendero Mens Sana Siena"]

def normalize_team(s):
    s=clean(s)
    repl={
      "ELAchem":"Elachem","Luxarm":"LuxArm","FABO":"Fabo","Pielle Livorno":"Verodol CBD Pielle Livorno",
      "Pallacanestro Viola Reggio Calabria":"Redel Reggio Calabria","Mens Sana Basketball Siena":"Sendero Mens Sana Siena",
      "Paperdi JuveCaserta 2021":"Juvecaserta 2021","Victoria Libertas Pesaro":"CMT Orange Tools Pesaro"
    }
    return repl.get(s,s)

def parse_lnp_rows(url, comp, label, teams):
    soup=BeautifulSoup(get(url).text,'html.parser')
    out=[]
    team_patterns=[(normalize_team(t), re.compile(re.escape(t),re.I)) for t in sorted(teams,key=len,reverse=True)]
    for tr in soup.select('tr'):
        cells=[clean(c.get_text(' ',strip=True)) for c in tr.select('th,td')]
        if len(cells)<3: continue
        row=' | '.join(cells)
        date=date_from(row)
        if not date: continue
        tm=time_from(row)
        found=[]
        for team,pat in team_patterns:
            if pat.search(row): found.append(team)
        # preserve table order using positions
        positions=[]
        for team,pat in team_patterns:
            m=pat.search(row)
            if m: positions.append((m.start(),team))
        positions.sort()
        if len(positions)>=2:
            home,away=positions[0][1],positions[1][1]
            watch='LNP Pass'
            low=row.lower()
            if 'rai' in low or 'raisport' in low: watch='LNP Pass · RaiSport HD'
            out.append(make(date,tm,home,away,comp,label,watch,'LNP'))
    return dedupe([g for g in out if g])

def pdf_text(url):
    r=get(url); p=Path('_basket_tv.pdf'); p.write_bytes(r.content)
    try:return '\n'.join(page.extract_text() or '' for page in PdfReader(str(p)).pages)
    finally:
        try:p.unlink()
        except:pass

def lnp_pdf(url,comp,label,teams):
    text=pdf_text(url).replace('\r','\n')
    dates=list(re.finditer(r'\b(\d{1,2})[./-](\d{1,2})[./-](2026|2027)\b',text))
    pats=[(normalize_team(t),re.compile(re.escape(t),re.I)) for t in sorted(teams,key=len,reverse=True)]
    out=[]
    for i,m in enumerate(dates):
        d,mo,y=m.groups(); date=f'{int(y):04d}-{int(mo):02d}-{int(d):02d}'
        block=clean(text[m.end():(dates[i+1].start() if i+1<len(dates) else len(text))])
        found=[]
        for team,p in pats:
            z=p.search(block)
            if z: found.append((z.start(),team))
        found.sort()
        if len(found)>=2:
            g=make(date,time_from(block),found[0][1],found[1][1],comp,label,'LNP Pass','LNP')
            if g:out.append(g)
    return dedupe(out)

def lnp(comp,label,cal_urls,pdf_urls,teams):
    out=[]
    for url in cal_urls:
        try:
            gs=parse_lnp_rows(url,comp,label,teams)
            if gs: out.extend(gs)
        except Exception: pass
    # PDF guarantees the complete season even if the live calendar page changes.
    for url in pdf_urls:
        try:
            gs=lnp_pdf(url,comp,label,teams)
            if gs: out.extend(gs)
        except Exception: pass
    return dedupe(out)

# ---------- EuroLeague / EuroCup official PDFs ----------
EUROLEAGUE_PDF='https://ftpserver.euroleague.net/media/2026-27_EL_RS_CALENDAR_PRINTABLE.pdf'
EUROCUP_PDF='https://ftpserver.euroleague.net/media/2026-27_EC_RS_CALENDAR_PRINTABLE.pdf'

def euro_pdf(url,comp,label):
    text=pdf_text(url).replace('\r','\n')
    out=[]
    # Official PDF format: full date, local time, GMT time, HOME AWAY.
    pat=re.compile(r'^(?:LOCAL GMT\s*)?(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(2026|2027)\s+(\d{1,2}:\d{2})\s+\d{1,2}:\d{2}\s+(.+?)\s+(.+?)$',re.I)
    months={m.lower():i for i,m in enumerate(['January','February','March','April','May','June','July','August','September','October','November','December'],1)}
    # Team lists make the split reliable when names contain spaces.
    euro_teams=[
      'CRVENA ZVEZDA MERIDIANBET BELGRADE','ZALGIRIS KAUNAS','DUBAI BASKETBALL','REAL MADRID','HAPOEL IBI TEL AVIV','FC BAYERN MUNICH','FC BARCELONA','ANADOLU EFES ISTANBUL','KOSNER BASKONIA VITORIA-GASTEIZ','OLYMPIACOS PIRAEUS','LDLC ASVEL VILLEURBANNE','MACCABI RAPYD TEL AVIV','PANATHINAIKOS AKTOR ATHENS','PARIS BASKETBALL','BESIKTAS ISTANBUL','VALENCIA BASKET','FENERBAHCE ISTANBUL','VIRTUS BOLOGNA','PARTIZAN MOZZART BET BELGRADE','ARMANI OLIMPIA MILAN',
      'RECOLETAS SALUD SAN PABLO BURGOS','CEDEVITA OLIMPIJA LJUBLJANA','HAPOEL MIDTOWN JERUSALEM','ROSTOCK SEAWOLVES','RIGA ZELLI','BAGLIETTO DERTHONA TORTONA','LE MANS SARTHE BASKET','ARIS THESSALONIKI BETSSON','LA LAGUNA TENERIFE','TURK TELEKOM ANKARA','MAXIMA ROMA','SIAULIAI BASKETBALL','LONDON LIONS','UMANA REYER VENICE','SKYLINERS FRANKFURT','U-BT CLUJ-NAPOCA','SLASK WROCLAW','BUDUCNOST VOLI PODGORICA','NAPOLI BASKETBALL','COSEA JL BOURG-EN-BRESSE','NEPTUNAS KLAIPEDA','DOLOMITI ENERGIA TRENTO','TOFAS BURSA','NINERS CHEMNITZ','LIETKABELIS PANEVEZYS','AS MONACO','PAOK THESSALONIKI','KIDS&US MANRESA','RATIOPHARM ULM','BALKAN BOTEVGRAD','BAHCESEHIR COLLEGE ISTANBUL','ROMA BASKETBALL']
    teams=sorted(set(euro_teams),key=len,reverse=True)
    for line in text.splitlines():
        line=clean(line)
        m=re.match(r'^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+(\d{1,2})\s+(\w+)\s+(2026|2027)\s+(\d{1,2}:\d{2})\s+\d{1,2}:\d{2}\s+(.+)$',line,re.I)
        if not m: continue
        d,mon,y,tm,rest=m.groups(); mo=months.get(mon.lower())
        if not mo: continue
        # Find the first two known team names in the remaining string.
        positions=[]
        for t in teams:
            z=re.search(re.escape(t),rest,re.I)
            if z: positions.append((z.start(),t))
        positions.sort()
        if len(positions)>=2:
            home=positions[0][1].title(); away=positions[1][1].title()
            date=f'{y}-{mo:02d}-{int(d):02d}'
            out.append(make(date,tm,home,away,comp,label,'Sky Sport · NOW','Euroleague Basketball'))
    return dedupe(out)

def euro(comp,label,url):
    return euro_pdf(url,comp,label)

def main():
    try: old=json.loads(DATA.read_text(encoding='utf-8'))
    except Exception: old={}
    fetched=[]; report=[]
    jobs=[
      ('LBA','LBA Serie A',lba),
      ('A2','Serie A2',lambda:lnp('A2','Serie A2',[A2_CAL],[A2_PDF],A2_TEAMS)),
      ('B','Serie B Nazionale',lambda:lnp('B','Serie B Nazionale',[B_CAL_A,B_CAL_B],[B_A_PDF,B_B_PDF],B_TEAMS)),
      ('EUROLEAGUE','EuroLeague',lambda:euro('EUROLEAGUE','EuroLeague',EUROLEAGUE_PDF)),
      ('EUROCUP','EuroCup',lambda:euro('EUROCUP','EuroCup',EUROCUP_PDF)),
    ]
    for comp,label,fn in jobs:
        try:
            gs=fn(); fetched+=gs; report.append(f'{label}: {len(gs)} gare')
        except Exception as e:
            report.append(f'{label}: ERRORE {type(e).__name__}: {e}')
    old_by={}
    for g in old.get('games',[]): old_by.setdefault(g.get('competition'),[]).append(g)
    new_by={}
    for g in fetched: new_by.setdefault(g['competition'],[]).append(g)
    # Do not silently replace a good database with a partial fetch.
    expected={'LBA':8,'A2':200,'B':500,'EUROLEAGUE':300,'EUROCUP':180}
    final=[]
    for comp in ('LBA','A2','B','EUROLEAGUE','EUROCUP'):
        ng=dedupe(new_by.get(comp,[]))
        final += ng if len(ng)>=expected[comp] else old_by.get(comp,[])
    for comp,gs in old_by.items():
        if comp not in ('LBA','A2','B','EUROLEAGUE','EUROCUP'): final+=gs
    final=dedupe(final)
    final.sort(key=lambda g:(g.get('date',''),g.get('time','99:99'),g.get('competition',''),g.get('home','')))
    DATA.write_text(json.dumps({'season':'2026/27','updated_at':datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),'games':final,'source_report':report},ensure_ascii=False,indent=2))
    print('\n'.join(report)); print('Totale:',len(final))

if __name__=='__main__': main()
