#!/usr/bin/env python3
import json, re, sys, subprocess
from pathlib import Path
from datetime import datetime, timezone

DATA = Path('data.json')
HEADERS = {'User-Agent':'Mozilla/5.0 (compatible; BasketTV/2.0)'}

# Calendari completi
LBA_CALENDAR = 'https://www.pianetabasket.com/legabasket-serie-a/legabasket-serie-a-ecco-il-calendario-202627-le-principali-date-della-stagione'
LBA_TV = 'https://www.legabasket.it/news/139386/programmazione-televisiva-cinque-giornate'
A2_PDF = 'https://static.legapallacanestro.com/sites/default/files/editor/calendario_serie_a2_oww_2026-27.pdf'
B_A_PDF = 'https://static.legapallacanestro.com/sites/default/files/editor/calendario_b_naz._gir._a_2026-27.pdf'
B_B_PDF = 'https://static.legapallacanestro.com/sites/default/files/editor/calendario_b_naz._gir._b_2026-27.pdf'
EUROLEAGUE_PDF = 'https://ftpserver.euroleague.net/media/2026-27_EL_RS_CALENDAR_PRINTABLE.pdf'
EUROCUP_PDF = 'https://ftpserver.euroleague.net/media/2026-27_EC_RS_CALENDAR_PRINTABLE.pdf'


def dep(name, package=None):
    try: return __import__(name)
    except ImportError:
        subprocess.check_call([sys.executable,'-m','pip','install','-q',package or name])
        return __import__(name)

requests = dep('requests')
bs4 = dep('bs4','beautifulsoup4')
BeautifulSoup = bs4.BeautifulSoup
pypdf = dep('pypdf')
PdfReader = pypdf.PdfReader


def clean(s):
    return re.sub(r'\s+',' ',str(s or '').replace('\xa0',' ')).strip()


def fetch(url):
    r=requests.get(url,headers=HEADERS,timeout=45)
    r.raise_for_status()
    return r


def date_iso(s):
    s=clean(s)
    m=re.search(r'\b(\d{1,2})[./-](\d{1,2})[./-](2026|2027)\b',s)
    if m:
        d,mo,y=m.groups(); return f'{int(y):04d}-{int(mo):02d}-{int(d):02d}'
    m=re.search(r'\b(2026|2027)-(\d{1,2})-(\d{1,2})\b',s)
    if m:
        y,mo,d=m.groups(); return f'{int(y):04d}-{int(mo):02d}-{int(d):02d}'
    return ''


def make_game(date,time,home,away,comp,label,watch=''):
    home,away=clean(home),clean(away)
    if not date or not home or not away: return None
    if home.casefold() in {'casa','squadra casa','home'} or away.casefold() in {'ospite','squadra ospite','away'}: return None
    return {'date':date,'time':clean(time),'home':home,'away':away,'competition':comp,'competition_label':label,'watch':clean(watch)}


def dedupe(games):
    out={}
    for g in games:
        key=(g['date'],g['home'].casefold(),g['away'].casefold(),g['competition'])
        if key not in out:
            out[key]=g
        else:
            old=out[key]
            if g.get('time'): old['time']=g['time']
            if g.get('watch') and 'definire' not in g['watch'].lower(): old['watch']=g['watch']
    return list(out.values())

# ---------- LBA ----------
def parse_lba_calendar():
    """Calendario completo 30 giornate. Fonte secondaria che ripubblica il calendario ufficiale LBA."""
    soup=BeautifulSoup(fetch(LBA_CALENDAR).text,'html.parser')
    lines=[clean(x) for x in soup.get_text('\n').splitlines() if clean(x)]
    games=[]; current_date=''
    for line in lines:
        m=re.search(r'\b(?:Dom|Sab|Ven|Gio|Mer|Mar|Lun)\s+(\d{2}/\d{2}/\d{2})\b',line)
        if m:
            dd,mm,yy=m.group(1).split('/'); current_date=f'20{yy}-{mm}-{dd}'
            continue
        # Anche se la data è separata dalla partita, i titoli GIORNATA restano prima delle righe.
        if current_date and ' vs ' in line:
            pair=[clean(x) for x in line.split(' vs ',1)]
            if len(pair)==2:
                g=make_game(current_date,'',pair[0],pair[1],'LBA','LBA Serie A','LBA TV')
                if g: games.append(g)
    return dedupe(games)


def parse_lba_tv():
    """Arricchisce le prime 5 giornate con gli orari/canali ufficiali LBA."""
    soup=BeautifulSoup(fetch(LBA_TV).text,'html.parser')
    text='\n'.join(clean(x) for x in soup.get_text('\n').splitlines() if clean(x))
    games=[]
    # Cerca blocchi data -> righe partita; la pagina ufficiale contiene 'ore HH.MM canale'.
    current_date=''
    for raw in text.split('\n'):
        line=clean(raw)
        m=re.search(r'(?:Sabato|Domenica|Lunedì)\s+(\d{1,2})\s+([A-Za-zà]+)\s+2026',line,re.I)
        if m:
            months={'settembre':'09','ottobre':'10','novembre':'11','dicembre':'12'}
            mo=months.get(m.group(2).lower())
            if mo: current_date=f'2026-{mo}-{int(m.group(1)):02d}'
            continue
        if current_date and '–' in line and re.search(r'ore\s+\d{1,2}[.:]\d{2}',line,re.I):
            tm=re.search(r'ore\s+(\d{1,2})[.:](\d{2})',line,re.I)
            pair=re.split(r'\s*[–-]\s*',line,1)
            if tm and len(pair)==2:
                watch=[]
                low=line.lower()
                if 'lbatv' in low: watch.append('LBA TV')
                if 'sky sport basket' in low: watch.append('Sky Sport Basket')
                if 'cielo' in low: watch.append('Cielo')
                g=make_game(current_date,f'{int(tm.group(1)):02d}:{tm.group(2)}',pair[0],pair[1],'LBA','LBA Serie A',' · '.join(watch))
                if g: games.append(g)
    return dedupe(games)

# ---------- LNP PDFs ----------
A2_TEAMS=[
'Halley Campania Avellino Basket','Flats Service Fortitudo Bologna','Valtur Brindisi','Paperdi Juvecaserta 2021','Sella Cento','UEB Gesteco Cividale','Ferraroni Juvi Cremona 1952','Unieuro Forlì','Libertas Livorno 1947','Gemini Mestre','Wegreenit Urania Milano','La T Tecnica Gema Montecatini','Victoria Libertas Pesaro','Lumos Pistoia Basket','RSR Sebastiani Rieti','Dole Basket Rimini','Crifo Wines Ruvo di Puglia','Banco di Sardegna Sassari','Reale Mutua Torino','ELAchem Vigevano 1955']
B_A_TEAMS=['Moncada Energy Agrigento','A2A Leonessa Brescia',"Infodrive Capo d'Orlando",'Rimadesio Desio','Adamant Ferrara','Fiorenzuola Bees','Andrea Costa Imola','SAE Scientifica-Soevis Legnano Knights','Luxarm Lumezzane','Paffoni Fulgor Basket Omegna','Logiman Orzinuovi','UCC Assigeco Piacenza','Siaz Basket Piazza Armerina','Pallacanestro Viola Reggio Calabria','LTC Group Sangiorgese Basket','Rucker San Vendemiano','TAV Treviglio Brianza Basket','S4 Energia Vicenza']
B_B_TEAMS=['Felice Scandone Avellino','Umana San Giobbe Chiusi','Ristopro Fabriano','Tema Sinergie Faenza','Benacquista Assicurazioni Latina','Pielle Livorno','Basketball Club Lucca','FABO Herons Montecatini','PSA Napoli Est','Consultinvest Loreto Pesaro','Solbat Golfo Piombino','Consorzio Leonardo Dany Quarrata','OraSì Ravenna','Luiss Roma','Virtus GVM Roma 1960','Liofilchem Roseto','Allianz Pazienza Cestistica San Severo','Mens Sana Basketball Siena']


def pdf_text(url):
    r=fetch(url); tmp=Path('_tmp_basket.pdf'); tmp.write_bytes(r.content)
    try:
        reader=PdfReader(str(tmp)); return '\n'.join(p.extract_text() or '' for p in reader.pages)
    finally:
        try: tmp.unlink()
        except OSError: pass


def find_teams(segment,teams):
    low=segment.casefold(); found=[]
    for t in teams:
        p=low.find(t.casefold())
        if p>=0: found.append((p,t))
    found.sort(); return [t for _,t in found[:2]]


def parse_lnp_pdf(url,comp,label,teams):
    text=pdf_text(url).replace('\r','\n')
    dates=list(re.finditer(r'\b\d{1,2}/\d{1,2}/(?:2026|2027)\b',text))
    games=[]
    for i,m in enumerate(dates):
        date=date_iso(m.group())
        end=dates[i+1].start() if i+1<len(dates) else len(text)
        seg=clean(text[m.end():end])
        pair=find_teams(seg,teams)
        if len(pair)!=2: continue
        tm=re.search(r'\b(?:[01]?\d|2[0-3])[:.]\d{2}\b',seg)
        time=tm.group().replace('.',':') if tm else ''
        games.append(make_game(date,time,pair[0],pair[1],comp,label,'LNP Pass'))
    return dedupe([g for g in games if g])

# ---------- EuroLeague / EuroCup official PDFs ----------
EUROLEAGUE_TEAMS=[
'CRVENA ZVEZDA MERIDIANBET BELGRADE','ZALGIRIS KAUNAS','DUBAI BASKETBALL','REAL MADRID','HAPOEL IBI TEL AVIV','FC BAYERN MUNICH','FC BARCELONA','ANADOLU EFES ISTANBUL','KOSNER BASKONIA VITORIA-GASTEIZ','OLYMPIACOS PIRAEUS','LDLC ASVEL VILLEURBANNE','MACCABI RAPYD TEL AVIV','PANATHINAIKOS AKTOR ATHENS','PARIS BASKETBALL','BESIKTAS ISTANBUL','VALENCIA BASKET','FENERBAHCE ISTANBUL','VIRTUS BOLOGNA','PARTIZAN MOZZART BET BELGRADE','ARMANI OLIMPIA MILAN']
EUROCUP_TEAMS=[
'RECOLETAS SALUD SAN PABLO BURGOS','CEDEVITA OLIMPIJA LJUBLJANA','HAPOEL MIDTOWN JERUSALEM','ROSTOCK SEAWOLVES','RIGA ZELLI','BAGLIETTO DERTHONA TORTONA','LE MANS SARTHE BASKET','ARIS THESSALONIKI BETSSON','LA LAGUNA TENERIFE','TURK TELEKOM ANKARA','MAXIMA ROMA','U-BT CLUJ-NAPOCA','UMANA REYER VENICE','SKYLINERS FRANKFURT','SIAULIAI BASKETBALL','LONDON LIONS','SLASK WROCLAW','BUDUCNOST VOLI PODGORICA','NAPOLI BASKETBALL','COSEA JL BOURG-EN-BRESSE','TOFAS BURSA','NINERS CHEMNITZ','NEPTUNAS KLAIPEDA','DOLOMITI ENERGIA TRENTO','LIETKABELIS PANEVEZYS','AS MONACO','PAOK THESSALONIKI','KIDS&US MANRESA','RATIOPHARM ULM','BALKAN BOTEVGRAD','BAHCESEHIR COLLEGE ISTANBUL','ROMA BASKETBALL']

def parse_euro_pdf(url,comp,label):
    text=pdf_text(url).replace('\r','\n')
    games=[]
    teams=EUROLEAGUE_TEAMS if comp=='EUROLEAGUE' else EUROCUP_TEAMS
    months={m.lower():i for i,m in enumerate(['January','February','March','April','May','June','July','August','September','October','November','December'],1)}
    line_re=re.compile(r'^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+(\d{1,2})\s+([A-Za-z]+)\s+(2026|2027)\s+(\d{1,2}:\d{2})\s+(\d{1,2}:\d{2})\s+(.+)$')
    for raw in text.split('\n'):
        line=clean(raw)
        m=line_re.match(line)
        if not m: continue
        d,mon,y,tm,_,rest=m.groups(); mo=months.get(mon.lower())
        if not mo: continue
        found=[]; low=rest.casefold()
        for team in teams:
            pos=low.find(team.casefold())
            if pos>=0: found.append((pos,team))
        found.sort(key=lambda x:x[0])
        if len(found)<2: continue
        home,away=found[0][1],found[1][1]
        games.append(make_game(f'{y}-{mo:02d}-{int(d):02d}',tm,home,away,comp,label,'Sky / NOW'))
    return dedupe([g for g in games if g])

def merge(old,new):
    oldmap={ (g.get('date'),g.get('home','').casefold(),g.get('away','').casefold(),g.get('competition')):g for g in old }
    for g in new:
        k=(g['date'],g['home'].casefold(),g['away'].casefold(),g['competition'])
        prev=oldmap.get(k)
        if prev:
            if not g.get('time'): g['time']=prev.get('time','')
            if (not g.get('watch') or 'definire' in g.get('watch','').lower()) and prev.get('watch'): g['watch']=prev['watch']
        oldmap[k]=g
    return list(oldmap.values())


def main():
    old=json.loads(DATA.read_text(encoding='utf-8')) if DATA.exists() else {}
    old_games=old.get('games',[])
    all_new=[]; report=[]
    sources=[
        ('LBA',lambda: merge(parse_lba_calendar(),parse_lba_tv())),
        ('A2',lambda: parse_lnp_pdf(A2_PDF,'A2','Serie A2',A2_TEAMS)),
        ('B',lambda: parse_lnp_pdf(B_A_PDF,'B','Serie B Nazionale',B_A_TEAMS)+parse_lnp_pdf(B_B_PDF,'B','Serie B Nazionale',B_B_TEAMS)),
        ('EUROLEAGUE',lambda: parse_euro_pdf(EUROLEAGUE_PDF,'EUROLEAGUE','EuroLeague')),
        ('EUROCUP',lambda: parse_euro_pdf(EUROCUP_PDF,'EUROCUP','EuroCup')),
    ]
    for code,fn in sources:
        try:
            gs=dedupe(fn()); all_new.extend(gs); report.append(f'{code}: {len(gs)} gare'); print(report[-1])
        except Exception as e:
            report.append(f'{code}: ERRORE {type(e).__name__}: {e}'); print(report[-1])

    # Una fonte guasta non deve mai cancellare il calendario precedente.
    final=merge(old_games,all_new)
    final=dedupe(final)
    final.sort(key=lambda g:(g.get('date',''),g.get('time') or '99:99',g.get('competition',''),g.get('home','')))
    out={'season':'2026/27','updated_at':datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),'games':final,'source_report':report}
    DATA.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Totale gare:',len(final))
    for comp in ['LBA','A2','B','EUROLEAGUE','EUROCUP']:
        print(comp,sum(1 for g in final if g.get('competition')==comp))

if __name__=='__main__': main()
