#!/usr/bin/env python3
import json, re, os
from datetime import datetime
import requests
from bs4 import BeautifulSoup

DATA="data.json"
URLS=[
 "https://www.legabasket.it/calendario",
 "https://www.legapallacanestro.com/serie-a2-old-wild-west-202627-i-risultati-della-1-giornata",
 "https://www.legapallacanestro.com/serie-b-nazionale-old-wild-west-202627-cos%C3%AC-la-1-giornata",
 "https://programmi.sky.it/sport/basket/eurolega",
 "https://programmi.sky.it/sport/basket/eurocup",
]
def fetch(url):
    r=requests.get(url,timeout=30,headers={"User-Agent":"BasketTV/1.0"})
    r.raise_for_status()
    return BeautifulSoup(r.text,"html.parser").get_text(" ",strip=True)

# Beta updater: source availability check + timestamp.
# Competition parsers are intentionally kept conservative. A future parser may replace/add
# records only when a date/time/team tuple is unambiguous.
def main():
    old=json.load(open(DATA,encoding="utf-8"))
    ok=0
    for u in URLS:
        try:
            txt=fetch(u)
            if len(txt)>500: ok+=1
        except Exception as e:
            print("SOURCE ERROR",u,e)
    old["updated_at"]=datetime.now().astimezone().isoformat(timespec="seconds")
    old["sources_checked"]=ok
    json.dump(old,open(DATA,"w",encoding="utf-8"),ensure_ascii=False,indent=2)
    print("Basket TV update:",ok,"sources reachable")
if __name__=="__main__": main()
