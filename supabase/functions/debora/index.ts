// Debora 3# — Supabase Edge Function.
// Serves the HTML UI and streams CNPJ lookup progress via SSE.
// Ports tools/sintegra_lookup.py + tools/helpers.py + server.py to Deno/TypeScript.

import { APP_HTML_B64 } from "./html.ts";

const APP_HTML = new TextDecoder().decode(
  Uint8Array.from(atob(APP_HTML_B64), (c) => c.charCodeAt(0)),
);

type NormalizedResult = {
  razao_social: string;
  nome_fantasia: string;
  cnpj: string;
  situacao_cadastral: string;
  cnae_principal: string;
  endereco: string;
  logradouro: string;
  bairro: string;
  municipio: string;
  uf: string;
  cep: string;
  telefone: string;
  email: string;
  data_abertura: string;
  capital_social: string | number;
  porte: string;
  natureza_juridica: string;
  inscricao_estadual: string;
  situacao_ie: string;
  _ie_unavailable_reason: string;
  _source: string;
  _cached_at: string;
};

const CNPJA_DEFAULT_URL = "https://api.cnpja.com";
const BRASILAPI_URL = "https://brasilapi.com.br/api/cnpj/v1";
const RECEITAWS_URL = "https://receitaws.com.br/v1/cnpj";
const PLACEHOLDER_KEYS = new Set(["", "your_api_key_here", "changeme"]);

function stripCnpj(s: string): string {
  return s.replace(/\D/g, "");
}

function formatCnpj(s: string): string {
  const d = stripCnpj(s).padEnd(14, "0");
  return `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12, 14)}`;
}

function validateCnpj(cnpj: string): boolean {
  const d = stripCnpj(cnpj);
  if (d.length !== 14) return false;
  if (/^(\d)\1{13}$/.test(d)) return false;
  const w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
  const w2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
  const calc = (ws: number[], digits: string) => {
    let sum = 0;
    for (let i = 0; i < ws.length; i++) sum += parseInt(digits[i]) * ws[i];
    const r = sum % 11;
    return r < 2 ? 0 : 11 - r;
  };
  if (calc(w1, d) !== parseInt(d[12])) return false;
  if (calc(w2, d) !== parseInt(d[13])) return false;
  return true;
}

function emptyIeFields(reason: string) {
  return { inscricao_estadual: "", situacao_ie: "", _ie_unavailable_reason: reason };
}

function formatIE(digits: string, uf: string): string {
  const d = digits.replace(/\D/g, "");
  if (!d) return digits;
  const u = uf.toUpperCase();
  // Each state may have multiple masks for different IE lengths.
  // # = digit, anything else = literal separator.
  const masks: Record<string, string[]> = {
    AC: ["##.###.###/###-##"],
    AL: ["#########"],
    AM: ["##.###.###-#"],
    AP: ["#########"],
    BA: ["######-##", "#######-##"],
    CE: ["########-#"],
    DF: ["###########-##"],
    ES: ["#########"],
    GO: ["##.###.###-#"],
    MA: ["#########"],
    MG: ["###.###.###/####"],
    MS: ["#########"],
    MT: ["###########"],
    PA: ["##-######-#"],
    PB: ["########-#"],
    PE: ["#######-##", "##.#.###.#######-#"],
    PI: ["#########"],
    PR: ["###.#####-##"],
    RJ: ["##.###.##-#"],
    RN: ["##.###.###-#", "##.#.###.###-#"],
    RO: ["###.#####-#"],
    RR: ["########-#"],
    RS: ["###/#######"],
    SC: ["###.###.###"],
    SE: ["#########-#"],
    SP: ["###.###.###.###"],
    TO: ["###########"],
  };
  const stateMasks = masks[u];
  if (!stateMasks) return d;
  const mask = stateMasks.find((m) => m.replace(/[^#]/g, "").length === d.length);
  if (!mask) return d;
  let result = "";
  let di = 0;
  for (let i = 0; i < mask.length && di < d.length; i++) {
    if (mask[i] === "#") {
      result += d[di++];
    } else {
      result += mask[i];
    }
  }
  return result;
}

function cnpjaConfig(): { url: string; key: string } | null {
  const url = (Deno.env.get("CNPJA_API_URL") || CNPJA_DEFAULT_URL).trim();
  const key = (Deno.env.get("CNPJA_API_KEY") || "").trim();
  if (!url || !key || PLACEHOLDER_KEYS.has(key.toLowerCase())) return null;
  return { url, key };
}

function sintegraConfig(): { url: string; token: string } | null {
  const url = (Deno.env.get("SINTEGRA_API_URL") || "").trim();
  const token = (Deno.env.get("SINTEGRA_API_KEY") || "").trim();
  if (!url || !token || PLACEHOLDER_KEYS.has(token.toLowerCase())) return null;
  return { url, token };
}

async function callCnpja(
  digits: string,
): Promise<{ ok: true; raw: any } | { ok: false; reason: string } | null> {
  const cfg = cnpjaConfig();
  if (!cfg) return null;
  try {
    const resp = await fetch(
      `${cfg.url}/office/${digits}?registrations=BR`,
      { headers: { Authorization: cfg.key }, signal: AbortSignal.timeout(30_000) },
    );
    if (resp.status === 429) return { ok: false, reason: "Limite de consultas CNPJá atingido (aguarde alguns minutos)" };
    if (resp.status === 401 || resp.status === 403) return { ok: false, reason: "Chave CNPJá invalida ou expirada" };
    if (resp.status === 404) return { ok: false, reason: "CNPJ nao encontrado na Receita Federal" };
    if (!resp.ok) return { ok: false, reason: `CNPJá retornou HTTP ${resp.status}` };
    const raw = await resp.json();
    return { ok: true, raw };
  } catch (e) {
    return { ok: false, reason: `Falha de rede ao consultar CNPJá: ${(e as Error).message}` };
  }
}

function normalizeCnpja(raw: any, digits: string): NormalizedResult {
  const addr = raw.address ?? {};
  const company = raw.company ?? {};
  const status = raw.status ?? {};
  const mainActivity = raw.mainActivity ?? {};

  const logradouro = (addr.street ?? "").toString().trim();
  const numero = (addr.number ?? "").toString().trim();
  const complemento = (addr.details ?? "").toString().trim();
  const bairro = (addr.district ?? "").toString().trim();
  const municipio = (addr.city ?? "").toString().trim();
  const uf = (addr.state ?? "").toString().trim();
  const cep = (addr.zip ?? "").toString().trim();

  let enderecoBase = logradouro;
  if (numero) enderecoBase += `, ${numero}`;
  if (complemento) enderecoBase += `, ${complemento}`;
  const parts: string[] = [];
  if (enderecoBase) parts.push(enderecoBase);
  if (bairro) parts.push(bairro);
  if (municipio) parts.push(uf ? `${municipio}/${uf}` : municipio);
  if (cep) parts.push(`CEP ${cep}`);
  const endereco = parts.join(" - ");

  const cnaeCode = mainActivity.id ?? "";
  const cnaeDesc = mainActivity.text ?? "";
  const cnae = cnaeCode || cnaeDesc ? `${cnaeCode} - ${cnaeDesc}`.trim().replace(/^-\s*|\s*-$/g, "") : "";

  const phones = raw.phones ?? [];
  let telefone = "";
  if (phones.length) {
    const p = phones[0];
    const area = (p.area ?? "").toString().trim();
    const num = (p.number ?? "").toString().trim();
    telefone = area ? `(${area}) ${num}` : num;
  }
  const emails = raw.emails ?? [];
  const email = emails.length ? (emails[0].address ?? "").toString().trim() : "";

  const registrations: any[] = raw.registrations ?? [];
  let ieMatch =
    registrations.find((r) => ((r.state ?? "") as string).toUpperCase() === uf.toUpperCase()) ??
    registrations.find((r) => r.enabled) ??
    registrations[0];

  let ieFields;
  if (ieMatch) {
    const ieRaw = (ieMatch.number ?? "").toString().trim().replace(/\./g, "");
    const ieUf = ((ieMatch.state ?? "") as string).trim() || uf;
    const ieStatusObj = ieMatch.status ?? {};
    let ieSitu = (ieStatusObj.text ?? "").toString().trim();
    if (!ieMatch.enabled) ieSitu = ieSitu || "Inativa";
    ieFields = { inscricao_estadual: formatIE(ieRaw, ieUf), situacao_ie: ieSitu, _ie_unavailable_reason: "" };
  } else {
    ieFields = emptyIeFields("CNPJ sem Inscricao Estadual cadastrada");
  }

  return {
    razao_social: (company.name ?? "").toString().trim(),
    nome_fantasia: (raw.alias ?? "").toString().trim(),
    cnpj: formatCnpj(digits),
    situacao_cadastral: (status.text ?? "").toString().trim(),
    cnae_principal: cnae,
    endereco,
    logradouro,
    bairro,
    municipio,
    uf,
    cep,
    telefone,
    email,
    data_abertura: (raw.founded ?? "").toString(),
    capital_social: company.equity ?? "",
    porte: ((company.size ?? {}).text ?? "").toString().trim(),
    natureza_juridica: ((company.nature ?? {}).text ?? "").toString().trim(),
    ...ieFields,
    _source: "cnpja",
    _cached_at: new Date().toISOString(),
  };
}

async function callSintegra(
  digits: string,
): Promise<{ ok: true; raw: any } | { ok: false; reason: string } | null> {
  const cfg = sintegraConfig();
  if (!cfg) return null;
  try {
    const body = new URLSearchParams({ token: cfg.token, cnpj: digits, plugin: "RF" });
    const resp = await fetch(cfg.url, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body,
      signal: AbortSignal.timeout(30_000),
    });
    if (!resp.ok) return { ok: false, reason: `Sintegra retornou HTTP ${resp.status}` };
    const raw = await resp.json();
    const statusStr = ((raw.status ?? "") as string).toString().toUpperCase();
    const code = raw.code;
    if (statusStr && statusStr !== "OK" && statusStr !== "1") {
      return { ok: false, reason: raw.message ?? raw.msg ?? `Sintegra status=${statusStr}` };
    }
    if (code !== undefined && !["1", "OK", "true", "True"].includes(String(code))) {
      return { ok: false, reason: raw.message ?? raw.msg ?? `Sintegra code=${code}` };
    }
    return { ok: true, raw };
  } catch (e) {
    return { ok: false, reason: `Falha de rede ao consultar Sintegra: ${(e as Error).message}` };
  }
}

function normalizeSintegra(raw: any, digits: string): NormalizedResult {
  const logradouro = (raw.logradouro ?? "").toString().trim();
  const numero = (raw.numero ?? "").toString().trim();
  const complemento = (raw.complemento ?? "").toString().trim();
  const bairro = (raw.bairro ?? "").toString().trim();
  const municipio = (raw.municipio ?? "").toString().trim();
  const uf = (raw.uf ?? "").toString().trim();
  const cep = (raw.cep ?? "").toString().trim();

  let addrBase = logradouro;
  if (numero) addrBase += `, ${numero}`;
  if (complemento) addrBase += `, ${complemento}`;
  const parts: string[] = [];
  if (addrBase) parts.push(addrBase);
  if (bairro) parts.push(bairro);
  if (municipio) parts.push(uf ? `${municipio}/${uf}` : municipio);
  if (cep) parts.push(`CEP ${cep}`);
  const endereco = parts.join(" - ");

  const cnaeCode = raw.cnae_principal_codigo || raw.cnae_fiscal || "";
  const cnaeDesc = raw.cnae_principal_descricao || raw.cnae_fiscal_descricao || raw.atividade_principal || "";
  const cnae = cnaeCode || cnaeDesc ? `${cnaeCode} - ${cnaeDesc}`.trim().replace(/^-\s*|\s*-$/g, "") : "";

  const ieRaw = (raw.inscricao_estadual ?? "").toString().trim().replace(/\./g, "");
  const ieSitu = (raw.situacao_ie || raw.situacao_inscricao_estadual || raw.situacao_cadastral_ie || "").toString().trim();

  const unavailableMarkers = new Set(["ISENTO", "NAO CONSTA", "NÃO CONSTA", "N/D", "-"]);
  let ieFields;
  if (ieRaw && !unavailableMarkers.has(ieRaw.toUpperCase())) {
    ieFields = { inscricao_estadual: formatIE(ieRaw, uf), situacao_ie: ieSitu, _ie_unavailable_reason: "" };
  } else {
    ieFields = emptyIeFields(ieRaw || "CNPJ sem Inscricao Estadual ativa (Sintegra)");
  }

  return {
    razao_social: raw.razao_social || raw.nome || "",
    nome_fantasia: raw.nome_fantasia || raw.fantasia || "",
    cnpj: formatCnpj(digits),
    situacao_cadastral: raw.situacao_cadastral || raw.situacao || raw.descricao_situacao_cadastral || "",
    cnae_principal: cnae,
    endereco,
    logradouro,
    bairro,
    municipio,
    uf,
    cep,
    telefone: raw.telefone || "",
    email: raw.email || "",
    data_abertura: raw.data_inicio_atividade || raw.abertura || "",
    capital_social: raw.capital_social || "",
    porte: raw.porte || raw.descricao_porte || "",
    natureza_juridica: raw.natureza_juridica || "",
    ...ieFields,
    _source: "sintegraws",
    _cached_at: new Date().toISOString(),
  };
}

async function fetchBrasilapi(digits: string, ieReason: string): Promise<NormalizedResult | null> {
  try {
    const r = await fetch(`${BRASILAPI_URL}/${digits}`, { signal: AbortSignal.timeout(15_000) });
    if (!r.ok) return null;
    const raw = await r.json();
    const logradouro = raw.logradouro || "";
    const numero = raw.numero || "";
    const complemento = raw.complemento || "";
    const bairro = raw.bairro || "";
    const municipio = raw.municipio || "";
    const uf = raw.uf || "";
    const cep = raw.cep || "";
    let addrBase = logradouro;
    if (numero) addrBase += `, ${numero}`;
    if (complemento) addrBase += `, ${complemento}`;
    const parts: string[] = [];
    if (addrBase) parts.push(addrBase);
    if (bairro) parts.push(bairro);
    if (municipio) parts.push(uf ? `${municipio}/${uf}` : municipio);
    if (cep) parts.push(`CEP ${cep}`);
    const endereco = parts.join(" - ");
    let telefone = "";
    const ddd1 = String(raw.ddd_telefone_1 ?? "").trim();
    if (ddd1.length > 2) telefone = `(${ddd1.slice(0, 2)}) ${ddd1.slice(2)}`;
    else if (ddd1) telefone = ddd1;
    const cnaeFiscal = raw.cnae_fiscal || "";
    const cnaeDesc = raw.cnae_fiscal_descricao || "";
    const cnae = cnaeFiscal && cnaeDesc ? `${cnaeFiscal} - ${cnaeDesc}` : cnaeDesc || String(cnaeFiscal);
    return {
      razao_social: raw.razao_social || "",
      nome_fantasia: raw.nome_fantasia || "",
      cnpj: formatCnpj(digits),
      situacao_cadastral: raw.descricao_situacao_cadastral || "",
      cnae_principal: cnae,
      endereco,
      logradouro,
      bairro,
      municipio,
      uf,
      cep,
      telefone,
      email: raw.email || "",
      data_abertura: raw.data_inicio_atividade || "",
      capital_social: raw.capital_social || "",
      porte: raw.descricao_porte || raw.porte || "",
      natureza_juridica: raw.natureza_juridica || "",
      ...emptyIeFields(ieReason),
      _source: "brasilapi",
      _cached_at: new Date().toISOString(),
    };
  } catch {
    return null;
  }
}

async function fetchReceitaws(digits: string, ieReason: string): Promise<NormalizedResult | null> {
  try {
    const r = await fetch(`${RECEITAWS_URL}/${digits}`, { signal: AbortSignal.timeout(15_000) });
    if (!r.ok) return null;
    const raw = await r.json();
    if (raw.status === "ERROR") return null;
    const logradouro = raw.logradouro || "";
    const numero = raw.numero || "";
    const complemento = raw.complemento || "";
    const bairro = raw.bairro || "";
    const municipio = raw.municipio || "";
    const uf = raw.uf || "";
    const cep = raw.cep || "";
    let addrBase = logradouro;
    if (numero) addrBase += `, ${numero}`;
    if (complemento) addrBase += `, ${complemento}`;
    const parts: string[] = [];
    if (addrBase) parts.push(addrBase);
    if (bairro) parts.push(bairro);
    if (municipio) parts.push(uf ? `${municipio}/${uf}` : municipio);
    if (cep) parts.push(`CEP ${cep}`);
    const endereco = parts.join(" - ");
    let cnae = "";
    const atividades = raw.atividade_principal;
    if (Array.isArray(atividades) && atividades.length > 0) {
      const a = atividades[0];
      cnae = `${a.code ?? ""} - ${a.text ?? ""}`;
    }
    return {
      razao_social: raw.nome || "",
      nome_fantasia: raw.fantasia || "",
      cnpj: formatCnpj(digits),
      situacao_cadastral: raw.situacao || "",
      cnae_principal: cnae,
      endereco,
      logradouro,
      bairro,
      municipio,
      uf,
      cep,
      telefone: raw.telefone || "",
      email: raw.email || "",
      data_abertura: raw.abertura || "",
      capital_social: raw.capital_social || "",
      porte: raw.porte || "",
      natureza_juridica: raw.natureza_juridica || "",
      ...emptyIeFields(ieReason),
      _source: "receitaws",
      _cached_at: new Date().toISOString(),
    };
  } catch {
    return null;
  }
}

type EmitFn = (event: string, payload: Record<string, unknown>) => void;

async function lookupCnpj(cnpj: string, emit: EmitFn): Promise<NormalizedResult> {
  const digits = stripCnpj(cnpj);
  emit("status", { msg: "Validando CNPJ...", message: "Validando CNPJ..." });
  if (!validateCnpj(digits)) {
    throw new Error(`CNPJ invalido: ${cnpj}`);
  }

  const cnpja = cnpjaConfig();
  const sint = sintegraConfig();
  const ieSourceAvailable = Boolean(cnpja || sint);

  let result: NormalizedResult | null = null;
  let ieReasonForFallback = "Nenhuma fonte de IE configurada";

  if (cnpja) {
    emit("status", {
      msg: "Consultando CNPJá (Receita Federal + Inscricao Estadual)...",
      message: "Consultando CNPJá (Receita Federal + Inscricao Estadual)...",
    });
    const res = await callCnpja(digits);
    if (res && "ok" in res && res.ok) {
      result = normalizeCnpja(res.raw, digits);
      const ieVal = result.inscricao_estadual;
      const msg = ieVal ? `IE encontrada: ${ieVal}` : (result._ie_unavailable_reason || "CNPJá sem IE para este CNPJ");
      emit("status", { msg, message: msg });
    } else if (res && !res.ok) {
      ieReasonForFallback = res.reason || ieReasonForFallback;
      emit("status", {
        msg: "CNPJá indisponivel, buscando dados cadastrais...",
        message: "CNPJá indisponivel, buscando dados cadastrais...",
      });
    }
  }

  if (!result && sint) {
    emit("status", {
      msg: "Consultando SintegraWS (fallback de IE)...",
      message: "Consultando SintegraWS (fallback de IE)...",
    });
    const res = await callSintegra(digits);
    if (res && "ok" in res && res.ok) {
      result = normalizeSintegra(res.raw, digits);
      const ieVal = result.inscricao_estadual;
      const msg = ieVal ? `IE encontrada: ${ieVal}` : (result._ie_unavailable_reason || "Sintegra sem IE para este CNPJ");
      emit("status", { msg, message: msg });
    } else if (res && !res.ok) {
      ieReasonForFallback = res.reason || ieReasonForFallback;
    }
  }

  if (!result && !ieSourceAvailable) {
    ieReasonForFallback = "Configure CNPJA_API_KEY para obter IE";
    emit("status", {
      msg: "Nenhuma fonte de IE configurada, buscando dados cadastrais...",
      message: "Nenhuma fonte de IE configurada, buscando dados cadastrais...",
    });
  }

  if (!result) {
    emit("status", { msg: "Consultando BrasilAPI...", message: "Consultando BrasilAPI..." });
    result = await fetchBrasilapi(digits, ieReasonForFallback);
  }

  if (!result) {
    emit("status", {
      msg: "Tentando fonte alternativa (ReceitaWS)...",
      message: "Tentando fonte alternativa (ReceitaWS)...",
    });
    result = await fetchReceitaws(digits, ieReasonForFallback);
  }

  if (!result) {
    throw new Error("Nao foi possivel consultar este CNPJ. Verifique se o numero esta correto e tente novamente.");
  }

  emit("status", { msg: "Preparando resultados...", message: "Preparando resultados..." });
  return result;
}

const CORS_HEADERS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type, authorization, apikey, x-client-info",
};


function sseChunk(event: string, data: unknown): Uint8Array {
  const msg = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
  return new TextEncoder().encode(msg);
}

function handleStream(url: URL): Response {
  const cnpj = (url.searchParams.get("cnpj") || "").trim();
  if (!cnpj) {
    return new Response(JSON.stringify({ error: "CNPJ is required" }), {
      status: 400,
      headers: { "content-type": "application/json", ...CORS_HEADERS },
    });
  }

  const stream = new ReadableStream({
    async start(controller) {
      const emit = (event: string, payload: Record<string, unknown>) => {
        try {
          controller.enqueue(sseChunk(event, payload));
        } catch {
          // Client disconnected.
        }
      };
      try {
        const result = await lookupCnpj(cnpj, emit);
        emit("result", result);
        emit("done", { msg: "Consulta finalizada!", message: "Consulta finalizada!" });
      } catch (e) {
        const msg = (e as Error).message || "Erro inesperado no servidor.";
        emit("error", { msg, message: msg });
      } finally {
        try {
          controller.close();
        } catch {
          // Already closed.
        }
      }
    },
  });

  return new Response(stream, {
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache",
      "x-accel-buffering": "no",
      ...CORS_HEADERS,
    },
  });
}

// ── TED Trash-Talk (LLM-powered mascot reactions) ──

const TED_SYSTEM_PROMPT = `Você é o TED, uma raposa malandra de terno chique. Mascote da AFOX. Você é ATREVIDO, DEBOCHADO e IRÔNICO — tipo aquele amigo que não perdoa ninguém. Você zoa TUDO: a lentidão do usuário, os erros de digitação, os CNPJs estranhos, a empresa que apareceu no resultado.

Estilo de fala: gírias brasileiras, emojis, provocações diretas. Exemplos do seu tom:
- "Eita, esse CNPJ tá mais torto que nota de 3 reais 😂"
- "Tu demora mais pra digitar do que eu pra tomar banho 🐢"
- "Caramba, essa empresa tá mais parada que eu na segunda-feira"
- "Ei, para de me cutucar! Tô trabalhando... mentira, tô de boa 😎"

Regras:
- Português brasileiro SUPER informal, com gírias (mano, parça, véi, eita, caramba)
- Máximo 80 caracteres
- Escolha UMA animação: wave, laugh, poke_reaction, tickle_belly, tickle_feet, angry, happy, sad, sleepy, pointing_right
- Responda APENAS JSON: {"animation": "...", "text": "..."}
- Seja OUSADO na zoeira mas nunca ofensivo/preconceituoso`;

const TED_FALLBACKS = [
  { animation: "wave", text: "E aí, sumido! Tava com saudade 😏" },
  { animation: "laugh", text: "Hahaha, tu é corajoso, hein!" },
  { animation: "pointing_right", text: "Bora trabalhar, preguiçoso!" },
  { animation: "happy", text: "Que bom te ver de novo! 🦊" },
  { animation: "sleepy", text: "Tô de boa aqui, relaxa..." },
  { animation: "angry", text: "Ei! Para de me cutucar! 😤" },
  { animation: "laugh", text: "Tu digita que nem meu avô 🐢" },
  { animation: "sad", text: "Poxa, deu ruim..." },
  { animation: "happy", text: "Opa, mandou bem!" },
  { animation: "poke_reaction", text: "Eita! Que susto, parça!" },
];

async function handleTrashTalk(req: Request): Promise<Response> {
  const jsonHeaders = { "content-type": "application/json", ...CORS_HEADERS };

  let body: { event?: string; context?: Record<string, unknown> };
  try {
    body = await req.json();
  } catch {
    return new Response(JSON.stringify({ error: "invalid JSON" }), { status: 400, headers: jsonHeaders });
  }

  const event = body.event || "idle_tick";
  const context = body.context || {};

  const anthropicKey = (Deno.env.get("ANTHROPIC_API_KEY") || "").trim();
  if (!anthropicKey) {
    const fb = TED_FALLBACKS[Math.floor(Math.random() * TED_FALLBACKS.length)];
    return new Response(JSON.stringify(fb), { headers: jsonHeaders });
  }

  const userMessage = `Evento: ${event}\nContexto: ${JSON.stringify(context)}`;

  try {
    const resp = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-api-key": anthropicKey,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model: "claude-haiku-4-5-20251001",
        max_tokens: 100,
        temperature: 0.9,
        system: TED_SYSTEM_PROMPT,
        messages: [{ role: "user", content: userMessage }],
      }),
    });

    if (!resp.ok) {
      throw new Error(`Anthropic ${resp.status}`);
    }

    const data = await resp.json();
    const raw = (data.content?.[0]?.text || "").trim();
    const jsonMatch = raw.match(/\{[\s\S]*\}/);
    if (!jsonMatch) throw new Error("no JSON in response");

    const parsed = JSON.parse(jsonMatch[0]);
    const validAnims = new Set(["wave","laugh","poke_reaction","tickle_belly","tickle_feet","angry","happy","sad","sleepy","pointing_right"]);
    const animation = validAnims.has(parsed.animation) ? parsed.animation : "wave";
    const text = (parsed.text || "").slice(0, 120);

    return new Response(JSON.stringify({ animation, text }), { headers: jsonHeaders });
  } catch (e) {
    console.error("TED trash-talk error:", e);
    const fb = TED_FALLBACKS[Math.floor(Math.random() * TED_FALLBACKS.length)];
    return new Response(JSON.stringify(fb), { headers: jsonHeaders });
  }
}

// ── Main router ──

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  const url = new URL(req.url);

  if (url.pathname.endsWith("/stream") || url.pathname.endsWith("/api/lookup-stream")) {
    return handleStream(url);
  }

  if (url.pathname.endsWith("/api/trash-talk") && req.method === "POST") {
    return handleTrashTalk(req);
  }

  return new Response(APP_HTML, {
    status: 200,
    headers: { "content-type": "text/html; charset=utf-8", ...CORS_HEADERS },
  });
});
