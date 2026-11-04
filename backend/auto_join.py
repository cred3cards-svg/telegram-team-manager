"""
Auto Group Join/Leave System

Join loop  (every 6h): picks top suggested_groups not yet joined,
           distributes across accounts, joins up to 5 per account per run.

Eval loop  (every 1h): checks auto-joined groups older than 2 days.
           Scores each group by unique-sender ratio + text diversity.
           score < HUMAN_THRESHOLD  → spammy → send final plug, then leave
           score >= HUMAN_THRESHOLD → real humans → keep forever
"""
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.errors import (
    FloodWaitError, UserAlreadyParticipantError,
    ChannelPrivateError, InviteHashExpiredError, ChatWriteForbiddenError,
)
from database import get_conn, now_ist
from accounts import _clients

_IST = ZoneInfo("Asia/Kolkata")

MAX_JOINS_PER_ACCOUNT = 5    # per run
JOIN_INTERVAL   = 6 * 3600  # 6 hours
EVAL_INTERVAL   = 3600       # 1 hour
LEAVE_AFTER_DAYS = 2
HUMAN_THRESHOLD  = 0.28      # unique-sender ratio below this = spammy

FINAL_PROMO = (
    "🎲 Dosto, aakhri baar yaad dila do — @ludohousiebot pe free ludo aur housie khelo, "
    "real cash jeeto! Bilkul free, koi deposit nahi → t.me/ludohousie 🏆"
)


# ── Activity scorer ───────────────────────────────────────────────────────────

async def _score_group(chat_row_id: int) -> float:
    """Return 0.0 (pure bot spam) → 1.0 (all real humans). 0.5 = not enough data."""
    with get_conn() as conn:
        msgs = conn.execute(
            "SELECT sender, text FROM messages "
            "WHERE chat_id=? AND is_outgoing=0 ORDER BY id DESC LIMIT 60",
            (chat_row_id,),
        ).fetchall()

    if len(msgs) < 8:
        return 0.5  # insufficient data — don't decide yet

    senders = [m["sender"] for m in msgs]
    unique_sender_ratio = len(set(senders)) / len(senders)

    texts = [m["text"][:60] for m in msgs]
    unique_text_ratio = len(set(texts)) / len(texts)

    return round(unique_sender_ratio * 0.6 + unique_text_ratio * 0.4, 3)


# ── Join helpers ──────────────────────────────────────────────────────────────

async def _join_one(client, account_id: int, project_id: int,
                    username: str, group_name: str, category: str) -> bool:
    """Join a public group by username. Returns True if joined/already in."""
    try:
        entity = await client.get_entity(username)
        await client(JoinChannelRequest(entity))
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO project_groups
                   (project_id, account_id, group_id, group_name, username,
                    category, monitored, joined_at, auto_joined)
                   VALUES (?,?,?,?,?,?,1,?,1)
                   ON CONFLICT(project_id, group_id) DO NOTHING""",
                (project_id, account_id, str(entity.id),
                 group_name, username, category, now_ist()),
            )
        print(f"[auto-join] joined {group_name} (@{username}) account={account_id}")
        return True
    except UserAlreadyParticipantError:
        return True
    except FloodWaitError as e:
        print(f"[auto-join] FloodWait {e.seconds}s — pausing")
        await asyncio.sleep(min(e.seconds, 300))
        return False
    except (ChannelPrivateError, InviteHashExpiredError):
        return False
    except Exception as e:
        print(f"[auto-join] join {username} failed: {type(e).__name__}: {str(e)[:60]}")
        return False


async def _run_joins():
    """One join pass across all projects."""
    with get_conn() as conn:
        projects = conn.execute("SELECT id FROM projects").fetchall()

    for proj_row in projects:
        project_id = proj_row["id"]

        with get_conn() as conn:
            accounts = conn.execute(
                "SELECT id, phone FROM accounts WHERE project_id=? AND status='connected'",
                (project_id,),
            ).fetchall()
            if not accounts:
                continue

            already = {r["group_id"] for r in conn.execute(
                "SELECT group_id FROM project_groups WHERE project_id=?",
                (project_id,),
            ).fetchall()}

            # Candidates not yet joined, with a username, ordered by member count
            if already:
                placeholders = ",".join("?" * len(already))
                candidates = conn.execute(
                    f"SELECT group_id, username, name, category FROM suggested_groups "
                    f"WHERE username != '' AND group_id NOT IN ({placeholders}) "
                    f"ORDER BY members DESC LIMIT 60",
                    list(already),
                ).fetchall()
            else:
                candidates = conn.execute(
                    "SELECT group_id, username, name, category FROM suggested_groups "
                    "WHERE username != '' ORDER BY members DESC LIMIT 60"
                ).fetchall()

        if not candidates:
            continue

        for idx, acc in enumerate(accounts):
            client = _clients.get(acc["phone"])
            if not client or not client.is_connected():
                continue

            joined = 0
            # Round-robin: account i takes every Nth candidate
            for grp in candidates[idx::len(accounts)]:
                if joined >= MAX_JOINS_PER_ACCOUNT:
                    break
                ok = await _join_one(
                    client, acc["id"], project_id,
                    grp["username"], grp["name"], grp["category"],
                )
                if ok:
                    joined += 1
                await asyncio.sleep(8)  # pace between joins

            if joined:
                print(f"[auto-join] project={project_id} account={acc['phone']}: {joined} new groups joined")


# ── Eval / leave helpers ──────────────────────────────────────────────────────

async def _run_eval():
    """Evaluate auto-joined groups older than LEAVE_AFTER_DAYS. Leave spammy ones."""
    cutoff = (datetime.now(_IST) - timedelta(days=LEAVE_AFTER_DAYS)).isoformat()

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT pg.id, pg.group_id, pg.group_name, pg.account_id,
                      pg.human_score, pg.project_id,
                      c.id as chat_row_id
               FROM project_groups pg
               LEFT JOIN chats c
                 ON c.chat_id = pg.group_id AND c.account_id = pg.account_id
               WHERE pg.auto_joined = 1
                 AND pg.left_at IS NULL
                 AND pg.joined_at < ?""",
            (cutoff,),
        ).fetchall()

    if not rows:
        return

    print(f"[auto-join] evaluating {len(rows)} auto-joined groups")

    for row in rows:
        chat_row_id = row["chat_row_id"]
        score = await _score_group(chat_row_id) if chat_row_id else 0.3

        # Update score
        with get_conn() as conn:
            conn.execute(
                "UPDATE project_groups SET human_score=? WHERE id=?",
                (score, row["id"]),
            )

        if score >= HUMAN_THRESHOLD:
            print(f"[auto-join] KEEP {row['group_name']} score={score:.2f} (real humans)")
            continue

        # Spammy — plug once more then leave
        with get_conn() as conn:
            acc_row = conn.execute(
                "SELECT phone FROM accounts WHERE id=?", (row["account_id"],)
            ).fetchone()

        client = _clients.get(acc_row["phone"]) if acc_row else None
        if not client or not client.is_connected():
            continue

        try:
            entity = await client.get_entity(int(row["group_id"]))
        except Exception as e:
            print(f"[auto-join] get_entity failed for {row['group_name']}: {e}")
            with get_conn() as conn:
                conn.execute(
                    "UPDATE project_groups SET left_at=?, monitored=0 WHERE id=?",
                    (now_ist(), row["id"]),
                )
            continue

        # Final promo
        try:
            await client.send_message(entity, FINAL_PROMO)
            print(f"[auto-join] final promo sent → {row['group_name']}")
            await asyncio.sleep(5)
        except (ChatWriteForbiddenError, Exception):
            pass  # write-restricted — still leave

        # Leave
        try:
            await client(LeaveChannelRequest(entity))
            print(f"[auto-join] LEFT {row['group_name']} score={score:.2f} (spammy)")
        except Exception as e:
            print(f"[auto-join] leave failed {row['group_name']}: {e}")

        with get_conn() as conn:
            conn.execute(
                "UPDATE project_groups SET left_at=?, monitored=0 WHERE id=?",
                (now_ist(), row["id"]),
            )

        await asyncio.sleep(3)


# ── Background task entry points ──────────────────────────────────────────────

async def run_auto_join_loop():
    await asyncio.sleep(90)  # wait for accounts to restore
    while True:
        try:
            await _run_joins()
        except Exception as e:
            print(f"[auto-join] join loop error: {e}")
        await asyncio.sleep(JOIN_INTERVAL)


async def run_auto_eval_loop():
    await asyncio.sleep(180)  # start after join loop
    while True:
        try:
            await _run_eval()
        except Exception as e:
            print(f"[auto-join] eval loop error: {e}")
        await asyncio.sleep(EVAL_INTERVAL)
