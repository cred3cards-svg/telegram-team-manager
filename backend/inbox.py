import asyncio
import json
import time
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from telethon import events
from telethon.tl.types import User, Channel, Chat
from database import get_conn, rows_to_list, row_to_dict
from accounts import get_client_for_account, _clients

router = APIRouter()

# Connected WebSocket clients: project_id -> list of WebSocket
_ws_clients: dict[int, list[WebSocket]] = {}

# Per-group cooldown: one AI reply per group every 5 minutes
GROUP_COOLDOWN = 300  # seconds
_group_last_processed: dict[str, float] = {}

# Buffer of recent group messages per chat_id — accumulated between replies
# so the AI gets the full conversation context, not just one trigger message
_group_message_buffer: dict[str, list[str]] = {}
GROUP_BUFFER_MAX = 20  # keep at most N messages in buffer

# Max auto-replies per DM per away session before going silent
DM_MAX_REPLIES = 2


class SendMessageRequest(BaseModel):
    account_id: int
    chat_id: str
    text: str


def _upsert_chat(conn, account_id: int, chat_id: str, chat_name: str, chat_type: str, last_message: str):
    conn.execute(
        """INSERT INTO chats (account_id, chat_id, chat_name, type, last_message, unread_count)
           VALUES (?,?,?,?,?,1)
           ON CONFLICT(account_id, chat_id) DO UPDATE SET
             last_message=excluded.last_message,
             unread_count=unread_count+1,
             chat_name=excluded.chat_name""",
        (account_id, chat_id, chat_name, chat_type, last_message),
    )
    return conn.execute(
        "SELECT * FROM chats WHERE account_id=? AND chat_id=?", (account_id, chat_id)
    ).fetchone()


def _insert_message(conn, chat_row_id: int, sender: str, text: str, is_outgoing: bool):
    ts = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO messages (chat_id, sender, text, timestamp, is_outgoing) VALUES (?,?,?,?,?)",
        (chat_row_id, sender, text, ts, 1 if is_outgoing else 0),
    )
    row = conn.execute(
        "SELECT id FROM messages WHERE chat_id=? AND timestamp=? AND sender=? ORDER BY id DESC LIMIT 1",
        (chat_row_id, ts, sender),
    ).fetchone()
    return row["id"] if row else None


async def _broadcast(project_id: int, payload: dict):
    dead = []
    for ws in _ws_clients.get(project_id, []):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients[project_id].remove(ws)


async def register_event_handlers(account_id: int, project_id: int):
    """Attach Telethon new-message handler to a connected client."""
    with get_conn() as conn:
        row = conn.execute("SELECT phone FROM accounts WHERE id=?", (account_id,)).fetchone()
    if not row:
        return
    phone = row["phone"]
    client = _clients.get(phone)
    if not client:
        return

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        msg = event.message
        if not msg.text:
            return

        sender_entity = await event.get_sender()
        chat_entity = await event.get_chat()

        # Ignore bots entirely — no storage, no reply
        if getattr(sender_entity, "bot", False):
            return

        is_group = isinstance(chat_entity, (Channel, Chat))
        chat_type = "group" if is_group else "dm"
        chat_id = str(chat_entity.id)
        chat_name = getattr(chat_entity, "title", None) or getattr(chat_entity, "first_name", "Unknown")
        sender_name = getattr(sender_entity, "first_name", None) or getattr(sender_entity, "username", "Unknown")

        # Look up current project_id live — supports re-assigning accounts to projects
        with get_conn() as conn:
            acc_row = conn.execute("SELECT project_id FROM accounts WHERE id=?", (account_id,)).fetchone()
        current_project_id = acc_row["project_id"] if acc_row else project_id

        # For groups, only store if monitored; skip write-restricted groups for replies
        with get_conn() as conn:
            existing_chat = conn.execute(
                "SELECT * FROM chats WHERE account_id=? AND chat_id=?", (account_id, chat_id)
            ).fetchone()

            if is_group and existing_chat and not existing_chat["monitored"]:
                return

            chat_row = _upsert_chat(conn, account_id, chat_id, chat_name, chat_type, msg.text[:100])
            msg_id = _insert_message(conn, chat_row["id"], sender_name, msg.text, False)

        await _broadcast(current_project_id, {
            "type": "new_message",
            "account_id": account_id,
            "chat_id": chat_id,
            "chat_name": chat_name,
            "chat_type": chat_type,
            "sender": sender_name,
            "text": msg.text,
            "message_id": msg_id,
            "timestamp": msg.date.isoformat(),
        })

        # Buffer group messages so the AI gets full conversation context per window
        if is_group:
            buf = _group_message_buffer.setdefault(chat_id, [])
            buf.append(f"{sender_name}: {msg.text}")
            if len(buf) > GROUP_BUFFER_MAX:
                buf.pop(0)

        # Away mode: auto-reply to both DMs and groups
        # Use input_chat (already-resolved InputPeer) to avoid PeerUser lookup errors
        try:
            input_chat = await event.get_input_chat()
        except Exception:
            input_chat = None
        asyncio.create_task(
            _maybe_away_reply(client, account_id, current_project_id, chat_entity, chat_id, msg.text, msg_id, chat_type, input_chat=input_chat)
        )



async def _maybe_away_reply(client, account_id: int, project_id: int, chat_entity, chat_id: str, message_text: str, msg_id: int, chat_type: str = "dm", input_chat=None):
    from away import is_away_for_chat
    if not is_away_for_chat(project_id, account_id, chat_id):
        return

    # Groups: enforce cooldown — only reply once per window
    # Drain the message buffer when we do reply so AI sees the full conversation
    if chat_type == "group":
        now = time.time()
        last = _group_last_processed.get(chat_id, 0)
        if now - last < GROUP_COOLDOWN:
            return  # still in window — message already buffered, skip API call
        _group_last_processed[chat_id] = now

    with get_conn() as conn:
        away_row = conn.execute("SELECT enabled_at FROM away_sessions WHERE project_id=?", (project_id,)).fetchone()
        if not away_row:
            return
        enabled_at = away_row["enabled_at"]

        chat_row = conn.execute("SELECT * FROM chats WHERE account_id=? AND chat_id=?", (account_id, chat_id)).fetchone()
        if not chat_row:
            return

        # Skip write-restricted groups — we already know we can't send there
        if dict(chat_row).get("write_restricted", 0):
            print(f"[away] Skipping write-restricted chat {chat_id}")
            return

        # For DMs: stop after DM_MAX_REPLIES to avoid burning credits on nonsense
        # For groups: cooldown above already limits frequency
        reply_count = conn.execute(
            "SELECT COUNT(*) as n FROM messages WHERE chat_id=? AND is_outgoing=1 AND timestamp >= ?",
            (chat_row["id"], enabled_at),
        ).fetchone()["n"]

    cap = DM_MAX_REPLIES if chat_type == "dm" else 10
    if reply_count >= cap:
        return

    # Resolve chat name early so it's available for the AI prompt
    chat_name_str = getattr(chat_entity, "title", None) or getattr(chat_entity, "first_name", "") or chat_id

    # Fetch project context + custom system prompt
    with get_conn() as conn:
        project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        recent_msgs = conn.execute(
            "SELECT sender, text FROM messages WHERE chat_id=? ORDER BY timestamp DESC LIMIT 3",
            (chat_row["id"],),
        ).fetchall()

    project = dict(project) if project else {}
    history = [{"sender": r["sender"], "text": r["text"]} for r in reversed(recent_msgs)]

    # For groups, use buffered messages as conversation context (one API call covers all)
    if chat_type == "group":
        buffered = _group_message_buffer.pop(chat_id, [])
        # Build a compact conversation block for the AI
        effective_message = "\n".join(buffered) if buffered else message_text
    else:
        effective_message = message_text

    # Generate AI draft — uses project's custom prompt if set, else ludo default
    try:
        from ai import build_draft, parse_ai_response, call_ai
        system_prompt = build_draft(
            message_text=effective_message,
            chat_history=history,
            chat_type=chat_type,
            chat_name=chat_name_str,
            project_system_prompt=project.get("system_prompt", ""),
        )
        raw = await call_ai(system_prompt, effective_message, max_tokens=100)
        data = parse_ai_response(raw)
        draft_text = data.get("draft", "")
    except Exception as e:
        print(f"[away] AI draft failed: {e}")
        return

    if not draft_text:
        return

    # Send the reply — use input_chat (pre-resolved InputPeer) to avoid
    # "Could not find entity for PeerUser" errors on DMs with new users
    send_target = input_chat if input_chat is not None else chat_entity
    try:
        await client.send_message(send_target, draft_text)
    except Exception as e:
        err = str(e).lower()
        if any(x in err for x in ["write", "forbidden", "banned", "restrict", "right", "permission", "not allowed"]):
            print(f"[away] Write-restricted in {chat_id} — flagging, no future replies")
            with get_conn() as conn:
                conn.execute(
                    "UPDATE chats SET write_restricted=1 WHERE account_id=? AND chat_id=?",
                    (account_id, chat_id),
                )
                conn.execute(
                    "UPDATE project_groups SET write_restricted=1 WHERE group_id=?",
                    (chat_id,),
                )
        else:
            print(f"[away] Send failed: {e}")
        return

    # Store as outgoing message, log the away reply
    with get_conn() as conn:
        chat_row = conn.execute("SELECT * FROM chats WHERE account_id=? AND chat_id=?", (account_id, chat_id)).fetchone()
        if chat_row:
            _insert_message(conn, chat_row["id"], "You", draft_text, True)
            conn.execute(
                "INSERT INTO ai_drafts (message_id, draft_text, category, urgency, was_used) VALUES (?,?,?,?,1)",
                (msg_id, draft_text, data.get("category", "general"), data.get("urgency", "medium")),
            )
            conn.execute("UPDATE chats SET last_message=? WHERE id=?", (draft_text[:200], chat_row["id"]))
        conn.execute(
            """INSERT INTO away_log
               (project_id, account_id, chat_id, chat_name, incoming_text, reply_text, category, urgency, replied_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (project_id, account_id, chat_id, chat_name_str, message_text, draft_text,
             data.get("category", "general"), data.get("urgency", "medium"),
             datetime.utcnow().isoformat()),
        )

    await _broadcast(project_id, {
        "type": "away_reply_sent",
        "account_id": account_id,
        "chat_id": chat_id,
        "text": draft_text,
        "timestamp": datetime.utcnow().isoformat(),
    })
    print(f"[away] Auto-replied to {chat_id}: {draft_text[:60]}...")


@router.get("/inbox/{project_id}")
async def get_inbox(project_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT c.*, a.phone, a.project_id
               FROM chats c
               JOIN accounts a ON c.account_id = a.id
               WHERE a.project_id=?
               ORDER BY c.unread_count DESC, c.last_message DESC""",
            (project_id,),
        ).fetchall()
    return rows_to_list(rows)


@router.get("/chat/{account_id}/{chat_id}")
async def get_chat_history(account_id: int, chat_id: str):
    with get_conn() as conn:
        chat_row = conn.execute(
            "SELECT * FROM chats WHERE account_id=? AND chat_id=?", (account_id, chat_id)
        ).fetchone()

    # Check if we have messages stored
    has_messages = False
    if chat_row:
        with get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) as n FROM messages WHERE chat_id=?", (chat_row["id"],)
            ).fetchone()["n"]
            has_messages = count > 0

    if not chat_row or not has_messages:
        # Fetch live from Telegram and cache
        client = await get_client_for_account(account_id)
        try:
            entity = await client.get_entity(int(chat_id))
            msgs = await client.get_messages(entity, limit=50)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        chat_name = getattr(entity, "title", None) or getattr(entity, "first_name", "Unknown")
        is_group = isinstance(entity, (Channel, Chat))
        chat_type = "group" if is_group else "dm"

        result = []
        with get_conn() as conn:
            chat_row = _upsert_chat(conn, account_id, chat_id, chat_name, chat_type, "")
            for m in reversed(msgs):
                if m.text:
                    sender_name = "You" if m.out else (getattr(m.sender, "first_name", "") or "Unknown")
                    _insert_message(conn, chat_row["id"], sender_name, m.text, m.out)
                    result.append({"sender": sender_name, "text": m.text, "timestamp": m.date.isoformat(), "is_outgoing": m.out})
        return result

    with get_conn() as conn:
        # Mark as read
        conn.execute(
            "UPDATE chats SET unread_count=0 WHERE account_id=? AND chat_id=?",
            (account_id, chat_id),
        )
        msgs = conn.execute(
            "SELECT * FROM messages WHERE chat_id=? ORDER BY timestamp ASC",
            (chat_row["id"],),
        ).fetchall()
    return rows_to_list(msgs)


@router.post("/messages/send")
async def send_message(req: SendMessageRequest):
    client = await get_client_for_account(req.account_id)

    try:
        # get_input_entity avoids the "Could not find PeerUser" error —
        # it resolves via the access hash already stored in the session
        try:
            target = await client.get_input_entity(int(req.chat_id))
        except Exception:
            target = await client.get_entity(int(req.chat_id))
        await client.send_message(target, req.text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    with get_conn() as conn:
        chat_row = conn.execute(
            "SELECT * FROM chats WHERE account_id=? AND chat_id=?",
            (req.account_id, req.chat_id),
        ).fetchone()
        if chat_row:
            msg_id = _insert_message(conn, chat_row["id"], "You", req.text, True)
            conn.execute(
                "UPDATE chats SET last_message=? WHERE id=?",
                (req.text[:100], chat_row["id"]),
            )
        else:
            msg_id = None

    return {"status": "sent", "message_id": msg_id}


@router.websocket("/ws/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: int):
    await websocket.accept()
    _ws_clients.setdefault(project_id, []).append(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep alive
    except WebSocketDisconnect:
        if project_id in _ws_clients:
            try:
                _ws_clients[project_id].remove(websocket)
            except ValueError:
                pass
