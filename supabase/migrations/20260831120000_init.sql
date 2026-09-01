-- Migration: initial schema
-- Applied with `supabase db push` (see supabase/migrate.ps1 / migrate.sh).
--
-- Auth is handled by Supabase (the built-in `auth.users` table). The tables
-- below reference `auth.users(id)` for the signed-in user.
-- Vector data (embeddings, chunks) lives in Qdrant, NOT here.
--
-- Guards (`if not exists`, `drop policy if exists`) make this safe to apply
-- even if an earlier hand-run of the schema already created these objects.

-- ---------------------------------------------------------------------------
-- Books & chapters (catalog of ingested material) - public read
-- ---------------------------------------------------------------------------
create table if not exists books (
    id          uuid primary key default gen_random_uuid(),
    title       text not null,
    source_file text not null,
    created_at  timestamptz not null default now()
);

create table if not exists chapters (
    id          uuid primary key default gen_random_uuid(),
    book_id     uuid not null references books (id) on delete cascade,
    title       text not null,
    start_page  int,
    end_page    int
);

-- ---------------------------------------------------------------------------
-- Conversations & messages - owned by a user
-- ---------------------------------------------------------------------------
create table if not exists conversations (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references auth.users (id) on delete cascade,
    title       text,
    created_at  timestamptz not null default now()
);

create table if not exists messages (
    id               uuid primary key default gen_random_uuid(),
    conversation_id  uuid not null references conversations (id) on delete cascade,
    user_id          uuid not null references auth.users (id) on delete cascade,
    role             text not null check (role in ('user', 'assistant')),
    content          text not null,
    created_at       timestamptz not null default now()
);

create index if not exists idx_messages_conversation on messages (conversation_id, created_at);
create index if not exists idx_conversations_user on conversations (user_id, created_at);

-- ---------------------------------------------------------------------------
-- Row Level Security: each user only sees their own rows
-- ---------------------------------------------------------------------------
alter table conversations enable row level security;
alter table messages enable row level security;

drop policy if exists "own conversations" on conversations;
create policy "own conversations" on conversations
    for all
    using (user_id = auth.uid())
    with check (user_id = auth.uid());

drop policy if exists "own messages" on messages;
create policy "own messages" on messages
    for all
    using (user_id = auth.uid())
    with check (user_id = auth.uid());

-- ---------------------------------------------------------------------------
-- Optional: user learning progress (add later if needed)
-- ---------------------------------------------------------------------------
-- create table if not exists user_progress (
--     id         uuid primary key default gen_random_uuid(),
--     user_id    uuid not null references auth.users (id) on delete cascade,
--     topic      text not null,
--     score      numeric,
--     updated_at timestamptz not null default now()
-- );
