# Workflow: CNPJ Lookup (SintegraWS primary, BrasilAPI/ReceitaWS fallback)

## Objective

Given a CNPJ, return full cadastral data plus **Inscrição Estadual (IE)** from
SintegraWS — a single authoritative source across all 27 Brazilian states.
If Sintegra is unavailable or unconfigured, return cadastral data only and
leave IE empty with an explicit `_ie_unavailable_reason`. **Never synthesize an IE.**

## Inputs

- **CNPJ**: 14 digits, raw or formatted (XX.XXX.XXX/XXXX-XX)

## Pipeline Steps

| Step | Action | Function |
|------|--------|----------|
| 1 | Validate CNPJ checksum | `helpers.validate_cnpj()` |
| 2 | Check local cache (`.tmp/cnpj_*.json`, 24h TTL) | `sintegra_lookup._check_cache()` |
| 3 | Call SintegraWS (if key configured) | `sintegra_lookup._call_sintegraws()` |
| 4a | On success → normalize + return (cadastral + IE) | `sintegra_lookup._normalize_sintegraws()` |
| 4b | On failure → fall back to BrasilAPI, then ReceitaWS | `_fetch_brasilapi` → `_fetch_receitaws` |
| 5 | Cache result to `.tmp/cnpj_<digits>.json` | `helpers.save_json()` |
| 6 | Stream progress + final payload to UI via SSE | `server.py` / `app.html` |

## IE rules (non-negotiable)

- `inscricao_estadual` is populated **only** from SintegraWS's
  `inscricao_estadual` field, and only when it is a non-empty, non-sentinel value.
- Sentinel / empty responses (`""`, `"ISENTO"`, `"NAO CONSTA"`, `"-"`) → IE is
  left empty and `_ie_unavailable_reason` carries the API's exact message.
- BrasilAPI / ReceitaWS **never** contribute to IE. They only fill cadastral
  fields (razão social, endereço, CNAE, etc.) when Sintegra is down.
- No regex parsing of IE from HTML anywhere in the codebase.

## Edge Cases

| Scenario | Handling |
|----------|----------|
| Invalid CNPJ (bad checksum) | Reject client-side + server-side |
| CNPJ not found on Sintegra | API message shown verbatim in IE card |
| CNPJ without IE (MEI, etc.) | IE card shows Sintegra's message (e.g. "não consta") |
| `SINTEGRA_API_KEY` missing / placeholder | Cadastral via BrasilAPI; IE card shows "Fonte de IE indisponível - configure SINTEGRA_API_KEY" |
| Network timeout on Sintegra | Fall back to BrasilAPI for cadastral; IE unavailable |
| Cached result available | Return from cache |

## Env vars

- `SINTEGRA_API_KEY` — token from sintegraws.com.br
- `SINTEGRA_API_URL` — default `https://sintegraws.com.br/api/v1/execute-api.php`

## Rules

1. **Never delete cached data** — `.tmp/cnpj_*.json` files are backed up, never overwritten
2. **Never fabricate IE** — empty string + reason is always preferable to a guess
3. **One IE source** — SintegraWS only; no CADESP, no per-state scrapers
