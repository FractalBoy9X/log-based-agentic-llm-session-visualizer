# Codex Log Tool v2

Ulepszona wersja narzedzia do wizualizacji logow agentow LLM.

## Co nowego w v2.2

- **Lepsza jakosc danych** — tool calle (np. `apply_patch`, `shell`) pokazuja teraz podglad komendy/patcha zamiast samej nazwy narzedzia
- **Stats bar** w tabeli eventow — kolorowe pigulki z liczba eventow per typ; klikniecie ukrywa/pokazuje dany typ
- **Wyszukiwarka** nad tabela — filtruje wiersze po tresci label/detail w czasie rzeczywistym
- **Rozwijane wiersze** — klikniecie wiersza otwiera panel ze pelna trescia (label, detail, thinking, metadane)
- **Uproszczona tabela** — 7 → 5 kolumn (Detail i Thinking przeniesione do panelu expand)
- **Wiekszy hover tooltip** w spirali 3D (label 80→120, detail 120→300 znakow)

## Co nowego w v2.1

- **Wsparcie dla starszych formatow JSONL** — automatyczne wykrywanie i parsowanie 3 wersji logow Codex CLI (wrzesien 2025, pazdziernik–styczen 2026, luty 2026+)
- **Naprawa pustych sesji** — wszystkie importy z 0 eventami zostaly naprawione

## Co nowego w v2.0

- **Log Manager** (`/logs/`) - nowa strona do zarzadzania logami:
  - Skanowanie katalogu z `CODEX_SESSIONS_DIR` (domyslnie `~/.codex/sessions/`) i wyswietlanie dostepnych plikow JSONL
  - Grupowanie wg miesiecy z checkboxami
  - Import wybranych lub WSZYSTKICH sesji jednym kliknieciem
  - Oznaczanie juz zaimportowanych plikow
- **Lepsza organizacja plikow** - JSONy w `visualization/data/sessions_json/`
- **Nowe opcje CLI** - `--all` (import wszystkich) i `--file=NAZWA` (import konkretnego)

## Struktura

```text
codex_log_tool_v2/
├── run_prettify.sh          # Glowny skrypt (--serve, --all, --file=...)
├── codex_prettify.py         # Parser i konwerter JSONL -> JSON
├── jsonl_deminify.py         # Pomocniczy deminifikator
├── requirements.txt
├── json_downloader/
│   ├── download_jsons.sh     # Pobieranie (wrapper na run_prettify.sh)
│   └── raw_jsonl/            # Surowe pliki JSONL
└── agentic-llm-session-visualizer-main/
    ├── manage.py
    ├── agentic_app/          # Konfiguracja Django
    ├── templates/            # Szablony HTML
    │   ├── base.html
    │   ├── home.html
    │   ├── agentic_thinking_visualization.html
    │   ├── log_manager.html  # NOWY - zarzadzanie logami
    │   └── instructions.html
    └── visualization/
        ├── loader.py         # Ladowanie danych JSON
        ├── views.py          # Widoki Django
        ├── log_manager.py    # NOWY - skanowanie i import logow
        ├── data/
        │   └── sessions_json/  # Przetworzone JSONy (wizualizacja czyta stad)
        └── instructions/
```

## Szybki start

```bash
cd codex_log_tool_v2
cp .env.example .env
./run_prettify.sh --serve
```

Nastepnie otworz: `http://127.0.0.1:8000/`

## Konfiguracja przez zmienne srodowiskowe

Projekt korzysta z env (bez hardcoded sciezek/secrets).

Najwygodniej:

```bash
cp .env.example .env
```

Najwazniejsze zmienne:

- `CODEX_SESSIONS_DIR` - katalog z plikami `.jsonl` (domyslnie `~/.codex/sessions`)
- `DJANGO_HOST` - host serwera dev (`127.0.0.1`)
- `DJANGO_PORT` - port serwera dev (`8000`)
- `DJANGO_DEBUG` - `true/false`
- `DJANGO_ALLOWED_HOSTS` - lista hostow rozdzielona przecinkami
- `DJANGO_SECRET_KEY` - klucz Django (zmien obowiazkowo poza lokalnym dev)

## Import logow

### Przez interfejs webowy (zalecane)

1. Otworz `http://127.0.0.1:8000/logs/`
2. Zaznacz checkboxami sesje do importu (wg miesiecy lub pojedynczo)
3. Kliknij **Import Selected** lub **Import All New**

### Przez CLI

```bash
# Import najnowszego loga (domyslne zachowanie)
./run_prettify.sh

# Import WSZYSTKICH logow
./run_prettify.sh --all

# Import konkretnego pliku
./run_prettify.sh --file=2026/02/14/rollout-2026-02-14T14-00-36-019c5c3d.jsonl

# Import + uruchom serwer
./run_prettify.sh --all --serve
```

### Przez dedykowany skrypt

```bash
./json_downloader/download_jsons.sh          # najnowszy
./json_downloader/download_jsons.sh --all    # wszystkie
```

## Reczne uruchomienie wizualizera

```bash
cd codex_log_tool_v2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd agentic-llm-session-visualizer-main
python manage.py runserver
```

## Strony

| URL | Opis |
|-----|------|
| `/` | Strona glowna z lista sesji |
| `/visualization/` | Wizualizacja 3D spirali |
| `/logs/` | **NOWY** - zarzadzanie logami (import, checkboxy) |
| `/instructions/` | Instrukcje uzytkowania |
