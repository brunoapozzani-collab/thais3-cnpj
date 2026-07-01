-- ie_cache: cross-invocation cache for Inscrição Estadual lookups.
-- Written only for definitive results (a found IE, or a source that cleanly
-- reported "no IE"). Transient failures (HTTP 429 / network) are never cached,
-- so they retry. Reuse is permanent per product decision; the /api/ie endpoint
-- accepts ?refresh=1 to force a re-query for the rare "IE changed" case.
create table if not exists public.ie_cache (
  cnpj text primary key,
  uf text not null default '',
  inscricao_estadual text not null default '',
  situacao_ie text not null default '',
  reason text not null default '',
  source text not null default '',
  cached_at timestamptz not null default now()
);

comment on table public.ie_cache is 'Cached Inscrição Estadual lookups (CNPJá/SintegraWS). Definitive results only.';

-- Read/write is exclusively via the debora edge function using the service-role
-- key, which bypasses RLS. Enable RLS with no policies so nothing else can read
-- this table through the anon/public API.
alter table public.ie_cache enable row level security;
