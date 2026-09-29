import json,re,html,requests
from datetime import datetime,timezone
from pathlib import Path
from bs4 import BeautifulSoup
DATA=Path('data.json'); H={'User-Agent':'Mozilla/5.0 BasketTV'}
S=[('A2','Serie A2','https://www.legapallacanestro.com/serie/1/calendario'),('B','Serie B','https://www.legapallacanestro.com/serie/4/calendario'),('LBA','LBA Serie A','https://www.legabasket.it/competizioni')]
def clean(x):return re.sub(r'\s+',' ',html.unescape(x or '')).strip()
def dateof(x):
 m=re.search(r'(\d{1,2})[./-](\d{1,2})[./-](2026|2027)',clean(x));return f'{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}' if m else None
def lnp(url,code,label):
 s=BeautifulSoup(requests.get(url,headers=H,timeout=30).text,'html.parser');out=[]
 for tr in s.select('table tr'):
  c=[clean(x.get_text(' ',strip=True)) for x in tr.select('th,td')]
  if len(c)<3:continue
  d=dateof(c[0]);
  if not d:continue
  m=re.search(r'\b([01]\d|2[0-3]):[0-5]\d\b',c[0]);out.append({'date':d,'time':m.group(0) if m else '','home':c[1],'away':c[2],'competition':code,'competition_label':label,'watch':'LNP Pass','source':'LNP'})
 return out
def main():
 old=json.loads(DATA.read_text(encoding='utf8')); by={(g.get('date'),g.get('time'),g.get('home'),g.get('away'),g.get('competition')):g for g in old.get('games',[])};rep=[]
 for code,label,url in S:
  try:
   gs=lnp(url,code,label);rep.append(f'{label}: {len(gs)}');[by.update({(g['date'],g['time'],g['home'],g['away'],g['competition']):g}) for g in gs]
  except Exception as e:rep.append(f'{label}: ERRORE')
 out={'season':'2026/27','updated_at':datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),'games':sorted(by.values(),key=lambda g:(g.get('date',''),g.get('time',''),g.get('competition',''))),'source_report':rep};DATA.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8');print(' | '.join(rep))
if __name__=='__main__':main()
