# Codex Log Visualizer -- Setup

> Uwaga: aktualne instrukcje sa w `README.md` (ten sam folder).

Narzedzie do parsowania logow agenta Codex (GPT) i wizualizacji sesji jako interaktywna spirala 3D.

Sklada sie z dwoch czesci:
- **codex_prettify.py** -- parser/prettifier logow JSONL (ten folder)
- **agentic-llm-session-visualizer-main/** -- Django + Plotly 3D visualizer

## Szybki start

```bash
# Pobierz najnowszy log, sparsuj, eksportuj do wizualizera, odpal serwer
cp .env.example .env
./run_prettify.sh --serve
```

Otworz http://127.0.0.1:8000/visualization/ w przegladarce.

## Konfiguracja env

Skrypt i Django czytaja zmienne srodowiskowe (takze automatycznie z pliku `.env`).

Przyklad:

```bash
cp .env.example .env
```

Najwazniejsze:
- `CODEX_SESSIONS_DIR` (domyslnie `~/.codex/sessions`)
- `DJANGO_HOST`, `DJANGO_PORT`
- `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_SECRET_KEY`

## Instalacja

```bash
# 1. Stworz venv (jesli nie istnieje)
python3 -m venv .venv
source .venv/bin/activate

# 2. Zainstaluj zaleznosci
pip install -r requirements.txt
```

Wymagane pakiety: `Django>=4.2`, `plotly>=5.18.0`, `numpy>=1.24.0`.

Skrypt `run_prettify.sh` robi to automatycznie przy pierwszym uruchomieniu.

## Uzycie

### Pelny workflow (automatyczny)

```bash
./run_prettify.sh                # parsuj + eksportuj JSON do wizualizera
./run_prettify.sh --serve        # j.w. + odpal Django server
./run_prettify.sh --summary      # parsuj + eksportuj + pokaz statystyki
./run_prettify.sh --no-color     # bez kolorow ANSI
```

### Reczne uzycie parsera

```bash
source .venv/bin/activate

# Pretty output (domyslny)
python3 codex_prettify.py session.jsonl

# Eksport do wizualizera
python3 codex_prettify.py session.jsonl --viz-json agentic-llm-session-visualizer-main/visualization/data/

# Inne formaty
python3 codex_prettify.py session.jsonl --jsonl out.jsonl
python3 codex_prettify.py session.jsonl --summary
python3 codex_prettify.py session.jsonl --turn 2 --verbose
```

### Odpalenie wizualizera

```bash
source .venv/bin/activate
cd agentic-llm-session-visualizer-main
python manage.py runserver
```

http://127.0.0.1:8000/visualization/

## Struktura folderow

```
test_codex_logs/
  codex_prettify.py          # parser + prettifier + eksport viz JSON
  run_prettify.sh            # automatyzacja: log -> parse -> viz -> server
  requirements.txt           # Django, plotly, numpy
  json_base.jsonl            # przykladowy log sesji
  SETUP.md                   # ten plik
  .venv/                     # Python venv
  agentic-llm-session-visualizer-main/
    manage.py                # Django management
    agentic_app/             # Django config (settings, urls)
    visualization/
      loader.py              # ladowanie JSON + spirala 3D Plotly
      views.py               # Django views
      data/                  # <- tu trafiaja eksportowane logi
        session_*.json
    templates/
      agentic_thinking_visualization.html   # strona z wykresem 3D
```

## Mapowanie eventow Codex -> Visualizer

| Codex event                           | Viz event_type | Kolor     |
|---------------------------------------|----------------|-----------|
| User message                          | `command`      | zielony   |
| Agent message                         | `analyze`      | rozowy    |
| Reasoning                             | `note`         | szary     |
| Tool call (apply_patch)               | `edit`         | pomaranczowy |
| Tool result                           | `read`         | fioletowy |
| Task complete                         | `backup`       | czerwony  |

## Pliki

| Plik | Opis |
|------|------|
| `codex_prettify.py` | Parser/prettifier + eksporter JSON dla wizualizera |
| `run_prettify.sh` | Automatyzacja: znajdz log, kopiuj, parsuj, eksportuj, serwuj |
| `requirements.txt` | Zaleznosci Python (Django, plotly, numpy) |
| `json_base.jsonl` | Przykladowy log sesji Codex (36 eventow, 2 turny) |
