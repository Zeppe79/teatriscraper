# TeatriScraper - Piano di Progetto

Aggregatore di eventi teatrali del Trentino. Scraping automatizzato via GitHub Actions,
frontend statico su GitHub Pages con gate password.

## Siti sorgente

### 1. cultura.trentino.it (API REST - priorità alta)

**Endpoint**: `https://www.cultura.trentino.it/calendar/search/node/(id)/298848`

Parametri:
- `what=30734` → categoria "Teatro"
- `when=today|week|month` → filtro temporale (da esplorare valori possibili)

Restituisce JSON strutturato con:
- `name` → titolo evento
- `fromDateTime` / `toDateTime` → date inizio/fine
- `orario_svolgimento` → orario testuale (es. "ore 10.00")
- `comune[].name` → città (es. "Trento")
- `luogo_della_cultura[].name` → venue (es. "Teatro Cuminetti")
- `luogo_della_cultura[].indirizzo` → indirizzo
- `href` → link pagina evento
- `iniziativa[].name` → rassegna/stagione di appartenenza
- `costi` → info prezzo (spesso vuoto)

**Strategia**: richiesta diretta HTTP, parsing JSON. Sorgente più affidabile e ricca.
Iterare sui giorni per coprire un range di ~60 giorni futuri.

### 2. centrosantachiara.it

**URL**: `https://www.centrosantachiara.it/spettacoli/calendariospettacoli`

**Strategia**: HTTP + BeautifulSoup. Da esplorare la struttura HTML.
Probabile CMS custom. Potrebbe richiedere User-Agent browser.

### 3. teatrodivillazzano.it

**URL**: `https://www.teatrodivillazzano.it/archivio/`

**Strategia**: WordPress, parsing HTML standard. Probabilmente paginato
(`/archivio/page/2/`).

### 4. teatrodipergine.it (Joomla)

**URL stagione**: `https://www.teatrodipergine.it/stagione-2013-2014-3`
(URL storico ma con eventi correnti)

**URL calendario**: `https://www.teatrodipergine.it/component/blog_calendar/YYYY/MM/DD?Itemid=`

**Strategia**: usare il componente blog_calendar iterando per mese/giorno
per estrarre gli eventi. Da verificare se il calendario restituisce HTML
parsabile o se c'è un endpoint JSON.

### 5. trentinospettacoli.it

**URL**: `https://www.trentinospettacoli.it/tag_eventi/teatro/`

**Strategia**: WordPress tag archive. Parsing HTML standard.
Paginazione probabile (`/page/2/`).

### 6. crushsite.it

**URL**: `https://www.crushsite.it/it/soggetti/danza-teatro/`

**Strategia**: CMS custom, parsing HTML. Da esplorare se include
anche eventi di sola danza (potrebbe servire filtro aggiuntivo).

---

## Architettura

```
teatriscraper/
├── scrapers/                     # Un modulo per ogni sito
│   ├── __init__.py
│   ├── base.py                   # Classe base BaseScraper
│   ├── cultura_trentino.py       # API REST (JSON)
│   ├── centrosantachiara.py      # HTML scraping
│   ├── teatrodivillazzano.py     # HTML scraping (WordPress)
│   ├── teatrodipergine.py        # HTML scraping (Joomla calendar)
│   ├── trentinospettacoli.py     # HTML scraping (WordPress)
│   └── crushsite.py              # HTML scraping
├── models.py                     # Dataclass Event
├── dedup.py                      # Deduplicazione eventi
├── main.py                       # Orchestratore
├── docs/                         # GitHub Pages
│   ├── index.html                # Frontend con filtri e gate password
│   ├── style.css
│   ├── app.js
│   └── events.json               # Generato automaticamente dallo scraper
├── .github/
│   └── workflows/
│       └── scrape.yml            # Cron 2x/giorno → scrape → commit
├── requirements.txt
└── PLAN.md                       # Questo file
```

## Data model (Event)

```python
@dataclass
class Event:
    title: str              # "S.L.O.I. machine - Arditodesìo"
    date: str               # "2026-02-09" (ISO 8601)
    time: str | None        # "20:30" o None
    venue: str              # "Teatro Cuminetti"
    location: str           # "Trento"
    description: str | None # Breve descrizione
    source_url: str         # Link alla pagina originale dell'evento
    source_name: str        # "cultura.trentino.it"

    # Campi derivati
    id: str                 # Hash deterministico per dedup
    is_past: bool           # Calcolato: date < today
```

Il campo `id` è un hash di `(date, venue_normalizzato, title_normalizzato)`.

## Deduplicazione

Lo stesso evento può apparire su più siti (es. uno spettacolo al Centro S. Chiara
listato sia su centrosantachiara.it che su cultura.trentino.it).

Strategia:
1. Normalizzazione: lowercase, strip punteggiatura, strip spazi extra
2. Chiave primaria: `(data, venue_normalizzato)`
3. Confronto titolo: `difflib.SequenceMatcher` con soglia ≥ 0.80
4. Se match → merge: si tiene l'evento con più dettagli, si aggiungono
   tutti i source_url come lista (per attribuzione multipla)

## Frontend

### Gate password (client-side)
- All'apertura, overlay con input password
- Password hardcoded nel JS (sufficiente come deterrente)
- Salvata in `localStorage` per non richiederla ogni volta
- `<meta name="robots" content="noindex, nofollow">` per escludere motori di ricerca

### Filtri
- **Data**: Oggi / Questa settimana / Questo mese / Tutti
- **Luogo/Venue**: dropdown dinamico basato sui dati
- **Toggle "Mostra eventi passati"**: off di default

### Lista eventi
- Ordinati cronologicamente (prossimi prima)
- Ogni card mostra: data, ora, titolo, venue, città, link fonte
- Espandibile per mostrare descrizione completa
- Mobile-first (responsive)

## GitHub Actions

```yaml
name: Scrape Theater Events
on:
  schedule:
    - cron: '0 5,17 * * *'  # 06:00 e 18:00 CET
  workflow_dispatch:          # Trigger manuale

jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: python main.py
      - name: Commit and push events.json
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add docs/events.json
          git diff --staged --quiet || git commit -m "Update events $(date -I)"
          git push
```

## Dipendenze Python

- `requests` — HTTP client
- `beautifulsoup4` — HTML parsing
- `lxml` — parser veloce per BS4 (opzionale, fallback a html.parser)

Nessun browser headless necessario: cultura.trentino.it ha API REST,
gli altri siti servono HTML statico. Se qualche sito richiedesse JS rendering,
si aggiungerà `playwright` solo per quello.

## Piano di implementazione (ordine)

1. **models.py + dedup.py** — strutture dati e logica dedup
2. **cultura_trentino.py** — primo scraper (API JSON, più facile, più dati)
3. **main.py** — orchestratore base
4. **Frontend (docs/)** — pagina HTML con filtri
5. **GitHub Actions** — workflow schedulato
6. **Scraper aggiuntivi** — uno alla volta, testando su ogni sito:
   - centrosantachiara.py
   - teatrodivillazzano.py
   - teatrodipergine.py
   - trentinospettacoli.py
   - crushsite.py
