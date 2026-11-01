"""
Group Discovery Engine
Runs in background when accounts are idle.
Layer 1: @TgFinderBot — sends keywords, parses group links from replies
Layer 2: Telegram ContactsSearch — keyword scan via Telethon API
Both results merge into suggested_groups table.
"""
import asyncio
import re
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.functions.channels import JoinChannelRequest, GetFullChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import Channel, Chat
from database import get_conn, rows_to_list
from accounts import _clients, get_client_for_account

router = APIRouter()

# ── Keywords focused on Ludo Housie promotions ───────────────────────────────

KEYWORDS = [
    # Housie / Tambola (primary targets)
    "housie", "tambola", "housie india", "tambola india",
    "online housie", "online tambola", "kitty housie", "housie party",
    "tambola group", "bingo india",
    # Ludo
    "ludo india", "ludo online", "ludo earn", "ludo game india",
    "ludo king india", "ludo play",
    # Indian online gaming / earning
    "online earning india", "earn money india", "paise kamao",
    "gaming india", "indian gaming", "real cash games india",
    "fantasy gaming india", "money earning games",
    # Kitty / Club / Colony groups (housie-friendly audiences)
    "kitty party india", "ladies kitty", "colony group india",
    "apartment group", "society group india", "mohalla group",
    # General Indian money / entertainment groups
    "india fun", "india game", "desi game", "indian women group",
    "antakshari india", "teen patti india",
]

MIN_MEMBERS = 500          # lower bar — ludo/housie groups are often smaller
DISCOVERY_INTERVAL = 4 * 3600   # run every 4 hours per account
_last_run: dict[str, float] = {}  # phone -> last discovery timestamp


# ── DB helpers ────────────────────────────────────────────────────────────────

def _init_discovery_table():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS suggested_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT NOT NULL,
                username TEXT DEFAULT '',
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                members INTEGER DEFAULT 0,
                online_members INTEGER DEFAULT 0,
                category TEXT DEFAULT 'general',
                discovered_at TEXT NOT NULL,
                UNIQUE(group_id)
            )
        """) if False else None  # handled in init_db
        # Try creating — harmless if exists
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS suggested_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL UNIQUE,
                    username TEXT DEFAULT '',
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    members INTEGER DEFAULT 0,
                    online_members INTEGER DEFAULT 0,
                    category TEXT DEFAULT 'general',
                    discovered_at TEXT NOT NULL
                )
            """)
        except Exception:
            pass


def _categorise(name: str, description: str) -> str:
    text = (name + " " + description).lower()
    if any(w in text for w in ["housie", "tambola", "bingo", "ludo housie"]):
        return "housie"
    if any(w in text for w in ["ludo", "ludo king", "ludo play"]):
        return "ludo"
    if any(w in text for w in ["kitty", "ladies kitty", "colony", "apartment", "society", "mohalla", "antakshari"]):
        return "kitty-club"
    if any(w in text for w in ["earn", "paise", "kamao", "real cash", "online earning", "money game"]):
        return "earning"
    if any(w in text for w in ["fantasy", "gaming", "game india", "desi game"]):
        return "gaming"
    if any(w in text for w in ["cricket", "ipl", "t20", "prediction"]):
        return "cricket"
    if any(w in text for w in ["stock", "trading", "nifty", "finance"]):
        return "finance"
    return "general"


# ── Core discovery logic ──────────────────────────────────────────────────────

def _dynamic_keywords(account_id: int) -> list:
    """Merge base KEYWORDS with words from already-joined group names for targeted search."""
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT chat_name FROM chats WHERE account_id=? AND type='group' LIMIT 60",
                (account_id,)
            ).fetchall()
        stop = {"the", "and", "for", "chat", "group", "with", "your",
                "this", "that", "from", "have", "only", "like", "more", "will", "into"}
        extra = set()
        for r in rows:
            for word in r["chat_name"].lower().split():
                if len(word) > 3 and word not in stop:
                    extra.add(word)
        combined = list(set(KEYWORDS + list(extra)))
        return combined[:40]
    except Exception:
        return KEYWORDS


def _already_joined_ids(account_id: int) -> set:
    """Return chat_ids already joined by this account so we don't re-suggest them."""
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT chat_id FROM chats WHERE account_id=? AND type='group'", (account_id,)
            ).fetchall()
        return {r["chat_id"] for r in rows}
    except Exception:
        return set()


# ── Bot keywords sent to @TgFinderBot ────────────────────────────────────────

BOT_KEYWORDS = [
    "housie india", "tambola india", "online housie", "online tambola",
    "kitty housie", "housie party", "tambola group",
    "ludo india", "ludo online", "ludo earn money",
    "online earning india", "earn money india", "paise kamao",
    "gaming india", "real cash games india", "fantasy gaming india",
    "kitty party india", "ladies kitty group", "colony group india",
    "apartment group india", "society group india",
    "desi game india", "indian women group", "antakshari india",
]


def _extract_usernames_from_text(text: str) -> list[str]:
    """Pull t.me links and @handles out of a bot reply."""
    usernames = []
    # t.me/username or t.me/+hash (skip invite links with +)
    for m in re.finditer(r't\.me/([A-Za-z][A-Za-z0-9_]{3,})', text):
        usernames.append(m.group(1))
    # @username
    for m in re.finditer(r'@([A-Za-z][A-Za-z0-9_]{3,})', text):
        usernames.append(m.group(1))
    return list(dict.fromkeys(usernames))  # dedup, preserve order


async def _bot_discover(client, phone: str, account_id: int, seen_ids: set) -> list[dict]:
    """
    Send keywords to @TgFinderBot one by one, collect all @usernames it replies with,
    then resolve each into a real Telegram entity and return enriched group dicts.
    """
    BOT = "TgFinderBot"
    enriched = []
    already_joined = _already_joined_ids(account_id)
    found_usernames: set[str] = set()

    # Use a rotating slice of keywords — each account covers a different chunk
    # so multiple accounts don't duplicate work
    with get_conn() as conn:
        acc_index = conn.execute(
            "SELECT COUNT(*) as n FROM accounts WHERE id <= ? AND status='active'",
            (account_id,)
        ).fetchone()["n"] - 1
    chunk_size = max(3, len(BOT_KEYWORDS) // 3)
    start = (acc_index * chunk_size) % len(BOT_KEYWORDS)
    keywords = (BOT_KEYWORDS + BOT_KEYWORDS)[start: start + chunk_size]

    print(f"[tgfinderbot] {phone}: querying bot with {len(keywords)} keywords")

    for keyword in keywords:
        try:
            await client.send_message(BOT, keyword)
            await asyncio.sleep(6)   # give bot time to respond

            # Read last 4 messages from the bot conversation
            msgs = await client.get_messages(BOT, limit=4)
            for msg in msgs:
                if not msg.text:
                    continue
                for uname in _extract_usernames_from_text(msg.text):
                    found_usernames.add(uname.lower())

            await asyncio.sleep(4)   # be polite between keywords
        except Exception as e:
            print(f"[tgfinderbot] '{keyword}' failed: {e}")
            await asyncio.sleep(10)

    print(f"[tgfinderbot] {phone}: found {len(found_usernames)} unique usernames, resolving...")

    for uname in found_usernames:
        if len(enriched) >= 40:
            break
        try:
            entity = await client.get_entity(uname)
            # Only groups — skip channels and bots
            is_group = (
                isinstance(entity, Channel) and getattr(entity, "megagroup", False)
            ) or isinstance(entity, Chat)
            if not is_group:
                continue
            gid = str(entity.id)
            if gid in seen_ids or gid in already_joined:
                continue
            seen_ids.add(gid)

            members = getattr(entity, "participants_count", 0) or 0
            if members < MIN_MEMBERS:
                continue

            username = getattr(entity, "username", "") or uname
            description = ""
            try:
                full = await client(GetFullChannelRequest(entity))
                description = getattr(full.full_chat, "about", "") or ""
                online = getattr(full.full_chat, "online_count", 0) or 0
            except Exception:
                online = 0

            enriched.append({
                "group_id": gid,
                "username": username,
                "name": getattr(entity, "title", uname),
                "description": description[:200],
                "members": members,
                "online_members": online,
                "category": _categorise(getattr(entity, "title", ""), description),
                "discovered_at": datetime.utcnow().isoformat(),
                "source": "tgfinderbot",
            })
            await asyncio.sleep(1.5)
        except Exception as e:
            print(f"[tgfinderbot] resolve {uname} failed: {e}")

    print(f"[tgfinderbot] {phone}: {len(enriched)} valid groups resolved")
    return enriched


async def _upsert_groups(groups: list[dict]):
    """Write a list of enriched group dicts into suggested_groups."""
    with get_conn() as conn:
        for g in groups:
            try:
                conn.execute(
                    """INSERT INTO suggested_groups
                       (group_id, username, name, description, members, online_members, category, discovered_at)
                       VALUES (?,?,?,?,?,?,?,?)
                       ON CONFLICT(group_id) DO UPDATE SET
                         members=EXCLUDED.members,
                         online_members=EXCLUDED.online_members,
                         discovered_at=EXCLUDED.discovered_at""",
                    (g["group_id"], g["username"], g["name"], g["description"],
                     g["members"], g["online_members"], g["category"], g["discovered_at"]),
                )
            except Exception:
                pass


async def _discover_for_client(client, phone: str, account_id: int = 0):
    seen_ids: set[str] = set()
    already_joined = _already_joined_ids(account_id)

    # ── Layer 1: @TgFinderBot ─────────────────────────────────────────────────
    try:
        bot_results = await _bot_discover(client, phone, account_id, seen_ids)
        await _upsert_groups(bot_results)
        print(f"[discovery] {phone}: TgFinderBot → {len(bot_results)} groups saved")
    except Exception as e:
        print(f"[discovery] {phone}: TgFinderBot layer failed: {e}")

    # ── Layer 2: Telegram ContactsSearch (existing keyword scan) ─────────────
    found = []
    keywords = _dynamic_keywords(account_id)

    for keyword in keywords:
        try:
            result = await client(SearchRequest(q=keyword, limit=50))
            for chat in result.chats:
                if not isinstance(chat, Channel):
                    continue
                if not getattr(chat, "megagroup", False):
                    continue
                if getattr(chat, "restricted", False) or getattr(chat, "private", False):
                    continue
                members = getattr(chat, "participants_count", 0) or 0
                if members < MIN_MEMBERS:
                    continue
                gid = str(chat.id)
                if gid in seen_ids or gid in already_joined:
                    continue
                seen_ids.add(gid)
                found.append(chat)
            await asyncio.sleep(2)
        except Exception as e:
            print(f"[discovery] keyword '{keyword}' failed: {e}")
            await asyncio.sleep(5)

    enriched = []
    for chat in found[:40]:
        try:
            full = await client(GetFullChannelRequest(chat))
            online = getattr(full.full_chat, "online_count", 0) or 0
        except Exception:
            online = 0

        username = getattr(chat, "username", "") or ""
        description = ""
        try:
            description = full.full_chat.about or ""
        except Exception:
            pass
        enriched.append({
            "group_id": str(chat.id),
            "username": username,
            "name": chat.title,
            "description": description[:200],
            "members": getattr(chat, "participants_count", 0) or 0,
            "online_members": online,
            "category": _categorise(chat.title, description),
            "discovered_at": datetime.utcnow().isoformat(),
        })
        await asyncio.sleep(1)

    await _upsert_groups(enriched)
    print(f"[discovery] {phone}: ContactsSearch → {len(enriched)} groups saved")


async def run_discovery_loop():
    """Background loop — runs discovery for each active account every 4 hours."""
    import time
    _init_discovery_table()
    # Clear old irrelevant suggestions once on startup
    try:
        with get_conn() as conn:
            conn.execute("DELETE FROM suggested_groups")
        print("[discovery] cleared old suggested_groups — fresh ludo/housie scan starting")
    except Exception:
        pass
    await asyncio.sleep(60)   # let accounts connect first

    while True:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id, phone FROM accounts WHERE status='active'"
            ).fetchall()


        for r in rows:
            phone = r["phone"]
            now = time.time()
            if now - _last_run.get(phone, 0) < DISCOVERY_INTERVAL:
                continue
            client = _clients.get(phone)
            if not client or not client.is_connected():
                continue
            _last_run[phone] = now
            print(f"[discovery] Starting group discovery for {phone}...")
            asyncio.create_task(_discover_for_client(client, phone, r["id"]))

        await asyncio.sleep(3600)   # check every hour, run every 6h per account


# ── API endpoints ─────────────────────────────────────────────────────────────

@router.get("/discovery/suggested")
async def get_suggested_groups(category: str = "all", limit: int = 50, project_id: int = 0):
    with get_conn() as conn:
        if category == "all":
            rows = conn.execute(
                "SELECT * FROM suggested_groups ORDER BY members DESC LIMIT ?",
                (limit,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM suggested_groups WHERE category=? ORDER BY members DESC LIMIT ?",
                (category, limit)
            ).fetchall()

        # Mark which ones have already been joined in this project
        joined_ids: set = set()
        if project_id:
            pg_rows = conn.execute(
                "SELECT group_id FROM project_groups WHERE project_id=?", (project_id,)
            ).fetchall()
            joined_ids = {r["group_id"] for r in pg_rows}

    result = rows_to_list(rows)
    for g in result:
        g["is_joined"] = g["group_id"] in joined_ids
    return result


class JoinSuggestedRequest(BaseModel):
    account_id: int
    group_id: str


@router.post("/discovery/join")
async def join_suggested_group(req: JoinSuggestedRequest):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM suggested_groups WHERE group_id=?", (req.group_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Group not found in suggestions")

    group = dict(row)
    client = await get_client_for_account(req.account_id)

    try:
        if group["username"]:
            entity = await client.get_entity(group["username"])
        else:
            entity = await client.get_entity(int(group["group_id"]))
        await client(JoinChannelRequest(entity))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to join: {e}")

    chat_name = group["name"]
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO chats (account_id, chat_id, chat_name, type, monitored)
               VALUES (?,?,?,'group',1)
               ON CONFLICT(account_id, chat_id) DO NOTHING""",
            (req.account_id, group["group_id"], chat_name),
        )
        # Persist at project level so it survives account changes
        acc_row = conn.execute("SELECT project_id FROM accounts WHERE id=?", (req.account_id,)).fetchone()
        if acc_row:
            from datetime import datetime
            conn.execute(
                """INSERT INTO project_groups
                       (project_id, account_id, group_id, group_name, username, category, monitored, joined_at)
                   VALUES (?,?,?,?,?,?,1,?)
                   ON CONFLICT(project_id, group_id) DO UPDATE SET
                     account_id=EXCLUDED.account_id""",
                (acc_row["project_id"], req.account_id, group["group_id"], chat_name,
                 group.get("username", ""), group.get("category", "general"),
                 datetime.utcnow().isoformat()),
            )

    return {"status": "joined", "group": chat_name}


@router.post("/discovery/run-now")
async def trigger_discovery_now(account_id: int):
    """Manually trigger discovery for one account."""
    from accounts import get_client_for_account as gca
    client = await gca(account_id)
    with get_conn() as conn:
        row = conn.execute("SELECT phone FROM accounts WHERE id=?", (account_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Account not found")
    asyncio.create_task(_discover_for_client(client, row["phone"], account_id))
    return {"status": "discovery started"}
