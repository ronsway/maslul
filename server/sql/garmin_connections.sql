-- Run once in the Supabase SQL editor for the "maslul" project
-- (https://supabase.com/dashboard/project/qvbdnaeewytfoolmubch/sql/new).
-- Not applied via migration tooling - this repo has none (see CLAUDE.md).
--
-- encrypted_token is `text`, not `bytea`: the backend stores
-- base64(nonce || AES-256-GCM ciphertext) as a plain string via Supabase's
-- PostgREST API, so a bytea column would need Postgres's `\x`-hex wire
-- format for no benefit - text keeps the REST calls simple.

create table public.garmin_connections (
  user_id uuid primary key references auth.users(id) on delete cascade,
  garmin_email text,
  encrypted_token text not null,
  status text not null default 'connected',   -- connected | needs_reauth | disconnected
  last_sync_at timestamptz,
  last_auth_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.garmin_connections enable row level security;

comment on table public.garmin_connections is
  'Per-user encrypted Garmin auth tokens. No client-facing RLS policies - only the backend (service-role key) reads/writes this table, unlike user_data which the frontend queries directly.';
