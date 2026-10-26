-- Ejecutar UNA vez en Supabase: SQL Editor > New query > pegar > Run
create sequence if not exists sync_seq;
create table if not exists public.sync_records (
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  tabla   text not null,
  uid     text not null,
  data    jsonb,
  deleted boolean not null default false,
  mod_ts  text not null,
  seq     bigint not null default nextval('sync_seq'),
  primary key (user_id, tabla, uid)
);
create index if not exists sync_records_seq on public.sync_records (user_id, seq);
alter table public.sync_records enable row level security;
drop policy if exists "solo lo propio" on public.sync_records;
create policy "solo lo propio" on public.sync_records for all
  using (user_id = auth.uid()) with check (user_id = auth.uid());
create or replace function public.sync_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'UPDATE' then
    if new.mod_ts <= old.mod_ts then return null; end if;  -- gana el cambio más nuevo
    new.seq := nextval('sync_seq');
  end if;
  return new;
end $$;
drop trigger if exists sync_guard on public.sync_records;
create trigger sync_guard before update on public.sync_records
  for each row execute function public.sync_guard();
