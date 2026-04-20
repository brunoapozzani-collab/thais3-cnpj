# Projectos Taag — Consulta CNPJ + IE

Web app that looks up Brazilian companies by CNPJ. Displays full tax registration data (legal name, **Inscrição Estadual**, address, phone, email, tax status, etc.) with an animated Elsa-inspired mascot "Thais" that narrates the search progress.

IE comes from **CNPJá commercial API** (`api.cnpja.com`, free tier covers ~hundreds of queries/month; `registrations=BR` returns all states in one call). When CNPJá is unavailable or the key is unconfigured, the app falls back to BrasilAPI / ReceitaWS for cadastral data only — **IE is never synthesized**, the UI shows the API's exact "unavailable" reason instead of a number. SintegraWS is retained as an optional secondary fallback (set `SINTEGRA_API_KEY` to enable).

## Before working, read:

- **WAT framework:** `../../templates/docs/wat-framework.md`

## Quick Start

```bash
# 1. Create and activate virtual environment
python3 -m venv .venv && source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and fill in your API key
cp .env.example .env
# Edit .env with your CNPJA_API_KEY

# 4. Start the server
python server.py

# 5. Open http://localhost:8084 in your browser
# 6. Type a CNPJ and click CONSULTAR
```

## Architecture

**Local dev — Python:**
- **`server.py`** — Python HTTP server (port 8084) + SSE streaming; reads `supabase/functions/debora/app.html` as the single source of truth
- **`tools/helpers.py`** — CNPJ validation, .env loading, shared utilities
- **`tools/sintegra_lookup.py`** — Unified lookup: CNPJá (primary, includes IE) → SintegraWS (optional fallback) → BrasilAPI + ReceitaWS (cadastral-only fallbacks)
- **`workflows/cnpj_lookup.md`** — SOP documenting the lookup pipeline + IE rules
- **`.env`** — `CNPJA_API_KEY` + `CNPJA_API_URL` (required); `SINTEGRA_API_KEY` + `SINTEGRA_API_URL` (optional)

**Mascot — Thais (Elsa from Frozen):**
- **`Mascot/`** — Full generation pipeline (LoRA training, sprite generation, video animation)
- Videos served at `/mascot-assets/` from `Mascot/assets/videos/`
- Interactive widget embedded in `app.html` — click/touch zones trigger reactions

## How It Works

1. User types a CNPJ in the web interface (auto-formatted as they type)
2. Client validates CNPJ checksum before sending
3. Server streams progress events (SSE) — mascot Thais narrates each step
4. Backend calls CNPJá for cadastral + IE (checks local 24h file cache first)
5. If CNPJá is unavailable and `SINTEGRA_API_KEY` is set, SintegraWS is tried next; otherwise cadastral data comes from BrasilAPI/ReceitaWS and the IE card shows the exact reason it's unavailable
6. Results display as animated cards with color-coded tax status

## Rules

- **Never fabricate IE** — if no source returns a number, the IE card displays the API's message verbatim. No regex, no guessing, no substitution.
- **IE sources** — CNPJá (primary) and SintegraWS (optional). No CADESP scraping, no per-state SEFAZ crawlers.
- **Never delete cached data** — `.tmp/cnpj_*.json` files are backed up via `save_json` rename, never overwritten
- **Empty-IE cache re-queries** — if a cached entry has no IE but a source is configured, the lookup re-queries the source
- **No Firecrawl** — this project uses httpx + JSON APIs only
