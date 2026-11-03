import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

print("[boot] version=2026-11-03-v2 qwen-no-thinking-param")

from database import init_db, prune_messages, _DB_PATH
from accounts import router as accounts_router, restore_all_sessions, keepalive_all_sessions
from groups import router as groups_router
from inbox import router as inbox_router
from ai import router as ai_router
from away import router as away_router
from discovery import router as discovery_router, run_discovery_loop


async def _periodic_prune():
    """Prune messages older than 24h every 30 minutes."""
    while True:
        await asyncio.sleep(1800)
        prune_messages()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await restore_all_sessions()
    asyncio.create_task(keepalive_all_sessions())
    asyncio.create_task(run_discovery_loop())
    asyncio.create_task(_periodic_prune())

    yield


app = FastAPI(title="Telegram Team Manager", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts_router)
app.include_router(groups_router)
app.include_router(inbox_router)
app.include_router(ai_router)
app.include_router(away_router)
app.include_router(discovery_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/admin/clear-messages")
async def admin_clear_messages():
    """Emergency endpoint: wipe messages and shrink DB even on a 100%-full volume."""
    import sqlite3 as _sq, shutil as _sh, os as _os
    tmp_path = "/tmp/_app_compact.db"
    try:
        c = _sq.connect(_DB_PATH)
        c.execute("PRAGMA journal_mode=MEMORY")
        c.execute("DELETE FROM ai_drafts")
        c.execute("DELETE FROM messages")
        c.execute("INSERT OR IGNORE INTO applied_migrations (name) VALUES ('clear_messages_v1')")
        c.commit()
        if _os.path.exists(tmp_path):
            _os.unlink(tmp_path)
        c.execute(f"VACUUM INTO '{tmp_path}'")
        c.close()
        with open(tmp_path, "rb") as src, open(_DB_PATH, "wb") as dst:
            _sh.copyfileobj(src, dst)
        _os.unlink(tmp_path)
        return {"status": "cleared", "detail": "messages deleted and DB compacted"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.delete("/projects/{project_id}")
async def delete_project(project_id: int):
    """Delete a project and all its associated data."""
    import sqlite3 as _sq
    try:
        c = _sq.connect(_DB_PATH)
        c.row_factory = _sq.Row
        # Cascade: messages → chats → accounts → project_groups → away data → project
        account_ids = [r[0] for r in c.execute(
            "SELECT id FROM accounts WHERE project_id=?", (project_id,)
        ).fetchall()]
        if account_ids:
            placeholders = ",".join("?" * len(account_ids))
            chat_ids = [r[0] for r in c.execute(
                f"SELECT id FROM chats WHERE account_id IN ({placeholders})", account_ids
            ).fetchall()]
            if chat_ids:
                cp = ",".join("?" * len(chat_ids))
                c.execute(f"DELETE FROM ai_drafts WHERE message_id IN (SELECT id FROM messages WHERE chat_id IN ({cp}))", chat_ids)
                c.execute(f"DELETE FROM messages WHERE chat_id IN ({cp})", chat_ids)
                c.execute(f"DELETE FROM chats WHERE id IN ({cp})", chat_ids)
            c.execute(f"DELETE FROM accounts WHERE id IN ({placeholders})", account_ids)
        c.execute("DELETE FROM project_groups WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM away_log WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM away_sessions WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM projects WHERE id=?", (project_id,))
        c.commit()
        c.close()
        return {"status": "deleted", "project_id": project_id}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
