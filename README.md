# Basket TV — versione definitiva

Pagina web continua per LBA, Serie A2, Serie B Nazionale, EuroLeague ed EuroCup.

## Aggiornamento automatico
GitHub Actions esegue `update.py` ogni giorno alle **10:00** e alle **23:00** con fuso `Europe/Rome`. GitHub supporta i cron con timezone IANA. citeturn6search0

## Pulsante nella pagina
`AGGIORNA DATI` forza il caricamento del `data.json` più recente, bypassando la cache del browser. Non contiene token GitHub e quindi non espone credenziali.

## Fonti
- LBA: calendario/competizioni ufficiali.
- LNP: PDF ufficiali A2 e B Nazionale.
- EuroLeague/EuroCup: feed ufficiale Euroleague Basketball, quando disponibile.

LBA espone nel calendario ufficiale data, ora e canali TV; per esempio la pagina ufficiale mostra ore e LBATV/Sky/Cielo per le gare programmate. citeturn0search0turn0search1
LNP pubblica i calendari completi 2026/27 di A2 e B Nazionale. citeturn0search2turn1search0
