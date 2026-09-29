# Basket TV — Beta definitiva

La pagina `index.html` è una web app: mostra giorni, filtri, partite e piattaforme.
`data.json` contiene il palinsesto.
`update.py` controlla le fonti.
`.github/workflows/update.yml` predispone due controlli giornalieri alle 23:00 e alle 10:00 (orario italiano CEST).

## Per avere l'aggiornamento automatico
Pubblicare questa cartella in un repository GitHub con GitHub Pages attivo.
Il workflow aggiornerà `data.json`; la pagina leggerà il file aggiornato ogni volta che viene aperta.

Nota: i siti ufficiali non offrono tutti la stessa struttura e alcuni cambiano il palinsesto senza preavviso. Per questo l'updater beta non inventa dati quando una fonte non è leggibile. I parser specifici possono essere estesi per ogni fonte.
