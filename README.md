# Basket TV

Programmazione per LBA Serie A, Serie A2, Serie B Nazionale, EuroLeague ed EuroCup.

## Aggiornamento

GitHub Actions è configurato per tentare l'aggiornamento ogni 30 minuti. Un singolo avvio può subire ritardi dovuti alla disponibilità dei siti o della piattaforma GitHub.

## Fonti e controlli

- Siti ufficiali LBA, LNP e FIP per il calendario e i riscontri incrociati.
- Lettura del calendario LBA con browser headless quando l'HTML statico non espone gli orari.
- PDF già incorporati nello storico `update_legacy.py` usati come fallback per completare orari mancanti.
- Nessun abbinamento PDF viene effettuato quando le squadre/data/competizione non sono abbastanza simili o l'abbinamento è ambiguo.
- Controllo della copertura degli orari delle gare imminenti; se la copertura è insufficiente, l'aggiornamento si interrompe prima di scrivere `data.json`.

## Installazione

Estrarre il pacchetto nella cartella `Documenti\GitHub\basket-tv` e avviare `INSTALLA_BASKET_TV.bat`. Il programma ripristina i file pubblici correnti del repository e applica le correzioni. Non pubblica nulla su GitHub: le modifiche devono essere controllate in GitHub Desktop prima del commit.
