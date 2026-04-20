#!/usr/bin/env python3
"""
Debora 3# — CNPJ Company Lookup Tool.

Primary source: SintegraWS (paid API, single call across all 27 states).
Returns full cadastral data + Inscrição Estadual.

Fallback (cadastral only, never IE): BrasilAPI + ReceitaWS.
When Sintegra is unconfigured or fails, IE is left empty with an explicit
`_ie_unavailable_reason` — never synthesized.

Usage:
    python tools/sintegra_lookup.py --cnpj 11222333000181
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.helpers import (
    validate_cnpj,
    format_cnpj,
    strip_cnpj,
    save_json,
    load_json,
    log,
    ensure_tmp,
    TMP_DIR,
)

CACHE_TTL_SECONDS = 86400

BRASILAPI_URL = "https://brasilapi.com.br/api/cnpj/v1"
RECEITAWS_URL = "https://receitaws.com.br/v1/cnpj"
CNPJA_DEFAULT_URL = "https://api.cnpja.com"

PLACEHOLDER_KEYS = {"", "your_api_key_here", "changeme"}


def _empty_ie_fields(reason: str) -> dict:
    return {
        "inscricao_estadual": "",
        "situacao_ie": "",
        "_ie_unavailable_reason": reason,
    }


def _check_cache(cnpj_digits: str):
    cache_file = TMP_DIR / f"cnpj_{cnpj_digits}.json"
    if not cache_file.exists():
        return None

    data = load_json(cache_file)
    if data is None:
        return None

    cached_at = data.get("_cached_at")
    if cached_at:
        try:
            cached_time = datetime.fromisoformat(cached_at)
            age = (datetime.now(timezone.utc) - cached_time).total_seconds()
            if age < CACHE_TTL_SECONDS:
                log(f"Cache hit for {cnpj_digits} (age: {int(age)}s)")
                return data
            log(f"Cache expired for {cnpj_digits} (age: {int(age)}s)")
        except ValueError:
            pass

    return None


def _sintegra_config():
    """Return (url, token) or (None, None) if not configured."""
    url = (os.environ.get("SINTEGRA_API_URL") or "").strip()
    token = (os.environ.get("SINTEGRA_API_KEY") or "").strip()
    if not url or token.lower() in PLACEHOLDER_KEYS:
        return None, None
    return url, token


def _cnpja_config():
    """Return (url, key) or (None, None) if not configured."""
    url = (os.environ.get("CNPJA_API_URL") or CNPJA_DEFAULT_URL).strip()
    key = (os.environ.get("CNPJA_API_KEY") or "").strip()
    if not url or key.lower() in PLACEHOLDER_KEYS:
        return None, None
    return url, key


def _call_cnpja(cnpj_digits: str) -> dict | None:
    """
    Call CNPJá commercial API. Returns:
      - {"_ok": True, "raw": <full response>}  → success
      - {"_ok": False, "reason": "<message>"}  → API error
      - None                                     → not configured
    """
    url, key = _cnpja_config()
    if not url or not key:
        return None

    try:
        resp = httpx.get(
            f"{url}/office/{cnpj_digits}",
            params={"registrations": "BR"},
            headers={"Authorization": key},
            timeout=30,
        )
    except Exception as e:
        log(f"CNPJá network error: {e}")
        return {"_ok": False, "reason": f"Falha de rede ao consultar CNPJá: {e}"}

    if resp.status_code == 429:
        return {"_ok": False, "reason": "Limite de consultas CNPJá atingido (aguarde alguns minutos)"}
    if resp.status_code == 401 or resp.status_code == 403:
        return {"_ok": False, "reason": "Chave CNPJá invalida ou expirada"}
    if resp.status_code == 404:
        return {"_ok": False, "reason": "CNPJ nao encontrado na Receita Federal"}
    if resp.status_code != 200:
        log(f"CNPJá HTTP {resp.status_code}: {resp.text[:200]}")
        return {"_ok": False, "reason": f"CNPJá retornou HTTP {resp.status_code}"}

    try:
        raw = resp.json()
    except Exception as e:
        log(f"CNPJá JSON parse error: {e}")
        return {"_ok": False, "reason": "Resposta do CNPJá nao pode ser lida"}

    return {"_ok": True, "raw": raw}


def _normalize_cnpja(raw: dict, cnpj_digits: str) -> dict:
    """Normalize CNPJá commercial API response into the unified schema."""
    addr = raw.get("address") or {}
    company = raw.get("company") or {}
    status = raw.get("status") or {}
    main_activity = raw.get("mainActivity") or {}

    logradouro = (addr.get("street") or "").strip()
    numero = str(addr.get("number") or "").strip()
    complemento = (addr.get("details") or "").strip()
    bairro = (addr.get("district") or "").strip()
    municipio = (addr.get("city") or "").strip()
    uf = (addr.get("state") or "").strip()
    cep = str(addr.get("zip") or "").strip()

    endereco_parts = logradouro
    if numero:
        endereco_parts += f", {numero}"
    if complemento:
        endereco_parts += f", {complemento}"
    parts = [p for p in [endereco_parts, bairro] if p]
    if municipio:
        parts.append(f"{municipio}/{uf}" if uf else municipio)
    if cep:
        parts.append(f"CEP {cep}")
    endereco = " - ".join(parts)

    cnae_code = main_activity.get("id") or ""
    cnae_desc = main_activity.get("text") or ""
    cnae = (
        f"{cnae_code} - {cnae_desc}".strip(" -")
        if (cnae_code or cnae_desc)
        else ""
    )

    phones = raw.get("phones") or []
    telefone = ""
    if phones:
        p = phones[0]
        area = str(p.get("area") or "").strip()
        num = str(p.get("number") or "").strip()
        telefone = f"({area}) {num}" if area else num

    emails = raw.get("emails") or []
    email = ""
    if emails:
        email = (emails[0].get("address") or "").strip()

    # Pick the IE for the HQ state. Fall back to first enabled if none matches.
    registrations = raw.get("registrations") or []
    ie_match = next((r for r in registrations if (r.get("state") or "").upper() == uf.upper()), None)
    if ie_match is None:
        ie_match = next((r for r in registrations if r.get("enabled")), None)
    if ie_match is None and registrations:
        ie_match = registrations[0]

    if ie_match:
        ie_raw = str(ie_match.get("number") or "").strip()
        ie_status_obj = ie_match.get("status") or {}
        ie_situ = (ie_status_obj.get("text") or "").strip()
        if not ie_match.get("enabled"):
            ie_situ = ie_situ or "Inativa"
        ie_fields = {
            "inscricao_estadual": ie_raw,
            "situacao_ie": ie_situ,
            "_ie_unavailable_reason": "",
        }
    else:
        ie_fields = _empty_ie_fields("CNPJ sem Inscricao Estadual cadastrada")

    return {
        "razao_social": (company.get("name") or "").strip(),
        "nome_fantasia": (raw.get("alias") or "").strip(),
        "cnpj": format_cnpj(cnpj_digits),
        "situacao_cadastral": (status.get("text") or "").strip(),
        "cnae_principal": cnae,
        "endereco": endereco,
        "logradouro": logradouro,
        "bairro": bairro,
        "municipio": municipio,
        "uf": uf,
        "cep": cep,
        "telefone": telefone,
        "email": email,
        "data_abertura": raw.get("founded") or "",
        "capital_social": company.get("equity") or "",
        "porte": ((company.get("size") or {}).get("text") or "").strip(),
        "natureza_juridica": ((company.get("nature") or {}).get("text") or "").strip(),
        **ie_fields,
        "_source": "cnpja",
        "_cached_at": datetime.now(timezone.utc).isoformat(),
    }


def _call_sintegraws(cnpj_digits: str) -> dict | None:
    """
    Call SintegraWS. Returns a dict with one of:
      - {"_ok": True, "raw": <api response>}  → success, parse for IE
      - {"_ok": False, "reason": "<message>"} → API error, IE unavailable
      - None                                    → not configured; caller falls back
    """
    url, token = _sintegra_config()
    if not url or not token:
        return None

    try:
        resp = httpx.post(
            url,
            data={"token": token, "cnpj": cnpj_digits, "plugin": "RF"},
            timeout=30,
        )
    except Exception as e:
        log(f"SintegraWS network error: {e}")
        return {"_ok": False, "reason": f"Falha de rede ao consultar Sintegra: {e}"}

    if resp.status_code != 200:
        log(f"SintegraWS HTTP {resp.status_code}")
        return {"_ok": False, "reason": f"Sintegra retornou HTTP {resp.status_code}"}

    try:
        raw = resp.json()
    except Exception as e:
        log(f"SintegraWS JSON parse error: {e}")
        return {"_ok": False, "reason": "Resposta do Sintegra nao pode ser lida"}

    # SintegraWS uses status/code to signal success. Accept common shapes.
    status = str(raw.get("status") or "").upper()
    code = raw.get("code")
    if status and status != "OK" and status != "1":
        msg = raw.get("message") or raw.get("msg") or f"Sintegra status={status}"
        log(f"SintegraWS not-ok: {msg}")
        return {"_ok": False, "reason": str(msg)}
    if code is not None and str(code) not in ("1", "OK", "true", "True"):
        msg = raw.get("message") or raw.get("msg") or f"Sintegra code={code}"
        log(f"SintegraWS not-ok: {msg}")
        return {"_ok": False, "reason": str(msg)}

    return {"_ok": True, "raw": raw}


def _normalize_sintegraws(raw: dict, cnpj_digits: str) -> dict:
    """Normalize SintegraWS response into the unified schema."""
    # SintegraWS returns a flat dict with lowercase keys. Common fields:
    # razao_social, nome_fantasia, inscricao_estadual, situacao_cadastral,
    # data_inicio_atividade, cnae_principal_codigo, cnae_principal_descricao,
    # logradouro, numero, complemento, bairro, municipio, uf, cep,
    # telefone, email, capital_social, porte, natureza_juridica, etc.

    logradouro = (raw.get("logradouro") or "").strip()
    numero = (raw.get("numero") or "").strip()
    complemento = (raw.get("complemento") or "").strip()
    bairro = (raw.get("bairro") or "").strip()
    municipio = (raw.get("municipio") or "").strip()
    uf = (raw.get("uf") or "").strip()
    cep = (raw.get("cep") or "").strip()

    addr = logradouro
    if numero:
        addr += f", {numero}"
    if complemento:
        addr += f", {complemento}"
    parts = [p for p in [addr, bairro] if p]
    if municipio:
        parts.append(f"{municipio}/{uf}" if uf else municipio)
    if cep:
        parts.append(f"CEP {cep}")
    endereco = " - ".join(parts)

    cnae_code = raw.get("cnae_principal_codigo") or raw.get("cnae_fiscal") or ""
    cnae_desc = (
        raw.get("cnae_principal_descricao")
        or raw.get("cnae_fiscal_descricao")
        or raw.get("atividade_principal")
        or ""
    )
    cnae = (
        f"{cnae_code} - {cnae_desc}".strip(" -")
        if (cnae_code or cnae_desc)
        else ""
    )

    ie_raw = (raw.get("inscricao_estadual") or "").strip()
    ie_situ = (
        raw.get("situacao_ie")
        or raw.get("situacao_inscricao_estadual")
        or raw.get("situacao_cadastral_ie")
        or ""
    ).strip()

    ie_fields: dict
    if ie_raw and ie_raw.upper() not in {"ISENTO", "NAO CONSTA", "NÃO CONSTA", "N/D", "-"}:
        ie_fields = {
            "inscricao_estadual": ie_raw,
            "situacao_ie": ie_situ,
            "_ie_unavailable_reason": "",
        }
    else:
        # API responded but did not provide a number — surface the exact signal.
        reason = ie_raw or "CNPJ sem Inscricao Estadual ativa (Sintegra)"
        ie_fields = _empty_ie_fields(reason)

    return {
        "razao_social": raw.get("razao_social") or raw.get("nome") or "",
        "nome_fantasia": raw.get("nome_fantasia") or raw.get("fantasia") or "",
        "cnpj": format_cnpj(cnpj_digits),
        "situacao_cadastral": (
            raw.get("situacao_cadastral")
            or raw.get("situacao")
            or raw.get("descricao_situacao_cadastral")
            or ""
        ),
        "cnae_principal": cnae,
        "endereco": endereco,
        "logradouro": logradouro,
        "bairro": bairro,
        "municipio": municipio,
        "uf": uf,
        "cep": cep,
        "telefone": raw.get("telefone") or "",
        "email": raw.get("email") or "",
        "data_abertura": raw.get("data_inicio_atividade") or raw.get("abertura") or "",
        "capital_social": raw.get("capital_social") or "",
        "porte": raw.get("porte") or raw.get("descricao_porte") or "",
        "natureza_juridica": raw.get("natureza_juridica") or "",
        **ie_fields,
        "_source": "sintegraws",
        "_cached_at": datetime.now(timezone.utc).isoformat(),
    }


def _normalize_brasilapi(raw: dict, cnpj_digits: str, ie_reason: str) -> dict:
    logradouro = raw.get("logradouro") or ""
    numero = raw.get("numero") or ""
    complemento = raw.get("complemento") or ""
    bairro = raw.get("bairro") or ""
    municipio = raw.get("municipio") or ""
    uf = raw.get("uf") or ""
    cep = raw.get("cep") or ""

    addr = logradouro
    if numero:
        addr += f", {numero}"
    if complemento:
        addr += f", {complemento}"
    parts = [p for p in [addr, bairro] if p and p.strip()]
    if municipio:
        parts.append(f"{municipio}/{uf}" if uf else municipio)
    if cep:
        parts.append(f"CEP {cep}")
    endereco = " - ".join(parts)

    telefone = ""
    ddd1 = str(raw.get("ddd_telefone_1") or "").strip()
    if ddd1 and len(ddd1) > 2:
        telefone = f"({ddd1[:2]}) {ddd1[2:]}"
    elif ddd1:
        telefone = ddd1

    cnae_fiscal = raw.get("cnae_fiscal") or ""
    cnae_desc = raw.get("cnae_fiscal_descricao") or ""
    cnae = (
        f"{cnae_fiscal} - {cnae_desc}"
        if cnae_fiscal and cnae_desc
        else cnae_desc or str(cnae_fiscal)
    )

    return {
        "razao_social": raw.get("razao_social") or "",
        "nome_fantasia": raw.get("nome_fantasia") or "",
        "cnpj": format_cnpj(cnpj_digits),
        "situacao_cadastral": raw.get("descricao_situacao_cadastral") or "",
        "cnae_principal": cnae,
        "endereco": endereco,
        "logradouro": logradouro,
        "bairro": bairro,
        "municipio": municipio,
        "uf": uf,
        "cep": cep,
        "telefone": telefone,
        "email": raw.get("email") or "",
        "data_abertura": raw.get("data_inicio_atividade") or "",
        "capital_social": raw.get("capital_social") or "",
        "porte": raw.get("descricao_porte") or raw.get("porte") or "",
        "natureza_juridica": raw.get("natureza_juridica") or "",
        **_empty_ie_fields(ie_reason),
        "_source": "brasilapi",
        "_cached_at": datetime.now(timezone.utc).isoformat(),
    }


def _normalize_receitaws(raw: dict, cnpj_digits: str, ie_reason: str) -> dict:
    logradouro = raw.get("logradouro") or ""
    numero = raw.get("numero") or ""
    complemento = raw.get("complemento") or ""
    bairro = raw.get("bairro") or ""
    municipio = raw.get("municipio") or ""
    uf = raw.get("uf") or ""
    cep = raw.get("cep") or ""

    addr = logradouro
    if numero:
        addr += f", {numero}"
    if complemento:
        addr += f", {complemento}"
    parts = [p for p in [addr, bairro] if p and p.strip()]
    if municipio:
        parts.append(f"{municipio}/{uf}" if uf else municipio)
    if cep:
        parts.append(f"CEP {cep}")
    endereco = " - ".join(parts)

    atividades = raw.get("atividade_principal") or []
    cnae = ""
    if atividades and isinstance(atividades, list) and len(atividades) > 0:
        a = atividades[0]
        cnae = f"{a.get('code', '')} - {a.get('text', '')}"

    return {
        "razao_social": raw.get("nome") or "",
        "nome_fantasia": raw.get("fantasia") or "",
        "cnpj": format_cnpj(cnpj_digits),
        "situacao_cadastral": raw.get("situacao") or "",
        "cnae_principal": cnae,
        "endereco": endereco,
        "logradouro": logradouro,
        "bairro": bairro,
        "municipio": municipio,
        "uf": uf,
        "cep": cep,
        "telefone": raw.get("telefone") or "",
        "email": raw.get("email") or "",
        "data_abertura": raw.get("abertura") or "",
        "capital_social": raw.get("capital_social") or "",
        "porte": raw.get("porte") or "",
        "natureza_juridica": raw.get("natureza_juridica") or "",
        **_empty_ie_fields(ie_reason),
        "_source": "receitaws",
        "_cached_at": datetime.now(timezone.utc).isoformat(),
    }


def _fetch_brasilapi(cnpj_digits: str, ie_reason: str):
    try:
        r = httpx.get(f"{BRASILAPI_URL}/{cnpj_digits}", timeout=15)
        if r.status_code == 200:
            return _normalize_brasilapi(r.json(), cnpj_digits, ie_reason)
        log(f"BrasilAPI: HTTP {r.status_code}")
    except Exception as e:
        log(f"BrasilAPI error: {e}")
    return None


def _fetch_receitaws(cnpj_digits: str, ie_reason: str):
    try:
        r = httpx.get(f"{RECEITAWS_URL}/{cnpj_digits}", timeout=15)
        if r.status_code == 200:
            raw = r.json()
            if raw.get("status") != "ERROR":
                return _normalize_receitaws(raw, cnpj_digits, ie_reason)
            log(f"ReceitaWS: {raw.get('message', 'error')}")
        else:
            log(f"ReceitaWS: HTTP {r.status_code}")
    except Exception as e:
        log(f"ReceitaWS error: {e}")
    return None


def lookup_cnpj(cnpj: str, callback=None):
    """
    Look up a CNPJ. SintegraWS is the primary and only source of IE.
    BrasilAPI / ReceitaWS are used only for cadastral data when Sintegra
    is unavailable; IE is left empty with an explicit reason.
    """

    def emit(msg):
        if callback:
            callback("status", msg)

    digits = strip_cnpj(cnpj)
    emit("Validando CNPJ...")
    time.sleep(0.2)

    if not validate_cnpj(digits):
        raise ValueError(f"CNPJ invalido: {cnpj}")

    formatted = format_cnpj(digits)
    log(f"Looking up CNPJ: {formatted}")

    emit("Verificando cache local...")
    cached = _check_cache(digits)
    cnpja_url, cnpja_key = _cnpja_config()
    sint_url, sint_token = _sintegra_config()
    ie_source_available = bool(cnpja_key or sint_token)

    if cached:
        cached.setdefault("inscricao_estadual", "")
        cached.setdefault("situacao_ie", "")
        cached.setdefault("_ie_unavailable_reason", "")
        if cached.get("inscricao_estadual") or not ie_source_available:
            # IE present, or no source to retry — serve from cache.
            emit("Cache encontrado! Carregando dados...")
            time.sleep(0.2)
            return cached
        # Cache has no IE but a source is configured — try a fresh lookup.
        emit("Cache sem IE. Consultando fonte atualizada...")

    result = None
    ie_reason_for_fallback = "Nenhuma fonte de IE configurada"

    if cnpja_key:
        emit("Consultando CNPJá (Receita Federal + Inscricao Estadual)...")
        cnpja = _call_cnpja(digits)
        if cnpja and cnpja.get("_ok"):
            result = _normalize_cnpja(cnpja["raw"], digits)
            ie_val = result.get("inscricao_estadual")
            if ie_val:
                emit(f"IE encontrada: {ie_val}")
            else:
                emit(result.get("_ie_unavailable_reason") or "CNPJá sem IE para este CNPJ")
        elif cnpja and not cnpja.get("_ok"):
            ie_reason_for_fallback = cnpja.get("reason") or ie_reason_for_fallback
            log(f"CNPJá unavailable: {ie_reason_for_fallback}")
            emit("CNPJá indisponivel, buscando dados cadastrais...")

    if result is None and sint_token:
        emit("Consultando SintegraWS (fallback de IE)...")
        sintegra = _call_sintegraws(digits)
        if sintegra and sintegra.get("_ok"):
            result = _normalize_sintegraws(sintegra["raw"], digits)
            ie_val = result.get("inscricao_estadual")
            if ie_val:
                emit(f"IE encontrada: {ie_val}")
            else:
                emit(result.get("_ie_unavailable_reason") or "Sintegra sem IE para este CNPJ")
        elif sintegra and not sintegra.get("_ok"):
            ie_reason_for_fallback = sintegra.get("reason") or ie_reason_for_fallback
            log(f"Sintegra unavailable: {ie_reason_for_fallback}")

    if result is None and not ie_source_available:
        ie_reason_for_fallback = "Configure CNPJA_API_KEY no .env para obter IE"
        emit("Nenhuma fonte de IE configurada, buscando dados cadastrais...")

    if result is None:
        emit("Consultando BrasilAPI...")
        result = _fetch_brasilapi(digits, ie_reason_for_fallback)

    if result is None:
        emit("Tentando fonte alternativa (ReceitaWS)...")
        time.sleep(0.3)
        result = _fetch_receitaws(digits, ie_reason_for_fallback)

    if result is None:
        raise RuntimeError(
            "Nao foi possivel consultar este CNPJ. "
            "Verifique se o numero esta correto e tente novamente."
        )

    emit("Preparando resultados...")
    save_json(f"cnpj_{digits}.json", result)
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Debora 3# — CNPJ Lookup")
    parser.add_argument("--cnpj", required=True, help="CNPJ to look up (14 digits)")
    args = parser.parse_args()

    def cli_callback(event_type, message):
        log(f"[{event_type}] {message}")

    try:
        result = lookup_cnpj(args.cnpj, callback=cli_callback)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except ValueError as e:
        log(f"Validation error: {e}")
        sys.exit(1)
    except RuntimeError as e:
        log(f"Lookup error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
