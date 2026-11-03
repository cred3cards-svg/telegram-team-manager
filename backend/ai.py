import os
import json
import time
import httpx
import anthropic
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database import get_conn

router = APIRouter()

_anthropic = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

CRICKETDATA_KEY = os.getenv("CRICKETDATA_API_KEY", "")

# ── AI call with Groq fallback ────────────────────────────────────────────────

# Models to try in order — skip if they return 404 (not on this account)
_GROQ_MODELS = [
    "llama-3.1-8b-instant",
    "llama3-8b-8192",
    "gemma2-9b-it",
    "llama3-70b-8192",
    "mixtral-8x7b-32768",
]
_groq_model_cache: list[str] | None = None  # set after first successful call


async def _pick_groq_model(groq_client) -> str | None:
    """Return first available model from _GROQ_MODELS, cached after first call."""
    global _groq_model_cache
    if _groq_model_cache is not None:
        return _groq_model_cache[0] if _groq_model_cache else None
    # Probe each candidate with a minimal call
    for model in _GROQ_MODELS:
        try:
            r = await groq_client.chat.completions.create(
                model=model, max_tokens=5,
                messages=[{"role": "user", "content": "hi"}],
            )
            if r.choices[0].message.content:
                _groq_model_cache = [model]
                print(f"[ai] Groq using model: {model}")
                return model
        except Exception:
            continue
    _groq_model_cache = []
    return None


async def call_ai(system_prompt: str, user_message: str, max_tokens: int = 100, force_anthropic: bool = False, jitter: bool = False) -> str:
    """Groq primary (auto-picks working model), Anthropic fallback."""
    import asyncio, random
    if jitter:
        await asyncio.sleep(random.uniform(0, 4))

    groq_key = os.getenv("GROQ_API_KEY", "")
    if groq_key and not force_anthropic:
        try:
            from groq import AsyncGroq
            groq_client = AsyncGroq(api_key=groq_key)
            model = await _pick_groq_model(groq_client)
            if model:
                resp = await groq_client.chat.completions.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                )
                msg = resp.choices[0].message
                text = msg.content or getattr(msg, "reasoning_content", "") or ""
                print(f"[ai] groq model={model} tokens={resp.usage.total_tokens} text_len={len(text)}")
                if text:
                    return text
        except Exception as e:
            print(f"[ai] Groq failed ({e}), falling back to Anthropic")
            global _groq_model_cache
            _groq_model_cache = None  # re-probe on next call in case of rate limit/model change

    # ── Fallback: Anthropic Haiku (paid, higher quality) ─────────────────────
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not anthropic_key:
        raise RuntimeError("No AI provider available — set GROQ_API_KEY or ANTHROPIC_API_KEY")
    resp = await _anthropic.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    print(f"[ai] anthropic fallback — tokens: {resp.usage.input_tokens}in {resp.usage.output_tokens}out")
    return resp.content[0].text
BASE_URL = "https://api.cricketdata.org/api/v1"

# ── Cricket data cache ────────────────────────────────────────────────────────

cricket_cache = {
    "live":     {"data": None, "fetched_at": 0},
    "upcoming": {"data": None, "fetched_at": 0},
}


async def fetch_with_cache(endpoint: str, cache_key: str, ttl: int) -> dict:
    now = time.time()
    if now - cricket_cache[cache_key]["fetched_at"] > ttl:
        try:
            async with httpx.AsyncClient() as http:
                r = await http.get(
                    f"{BASE_URL}/{endpoint}",
                    params={"apikey": CRICKETDATA_KEY},
                    timeout=5.0,
                )
                payload = r.json()
                print(f"[cricket] {endpoint} status={r.status_code} keys={list(payload.keys()) if isinstance(payload, dict) else type(payload)}")
                if isinstance(payload, dict) and payload.get("data"):
                    print(f"[cricket] {endpoint} returned {len(payload['data'])} items, first={payload['data'][0] if payload['data'] else 'empty'}")
                cricket_cache[cache_key]["data"] = payload
                cricket_cache[cache_key]["fetched_at"] = now
        except Exception as e:
            print(f"[cricket] fetch failed ({endpoint}): {e}")
            return cricket_cache[cache_key]["data"] or {}
    return cricket_cache[cache_key]["data"] or {}


async def get_live_matches() -> str:
    if not CRICKETDATA_KEY:
        return "Cricket data unavailable."
    data = await fetch_with_cache("currentMatches", "live", ttl=300)
    matches = data.get("data", [])
    if not matches:
        return "No live matches right now."
    lines = []
    for m in matches[:5]:
        scores = m.get("score", [])
        score_str = " | ".join(
            f"{s.get('inning','')}: {s.get('r',0)}/{s.get('w',0)} ({s.get('o',0)} ov)"
            for s in scores
        ) if scores else "Yet to start"
        lines.append(
            f"Match: {m.get('name')}\n"
            f"Status: {m.get('status')}\n"
            f"Score: {score_str}\n"
            f"Venue: {m.get('venue', 'NA')}"
        )
    return "\n\n".join(lines)


async def get_upcoming_matches() -> str:
    if not CRICKETDATA_KEY:
        return "Schedule unavailable."
    data = await fetch_with_cache("matches", "upcoming", ttl=1800)
    matches = data.get("data", [])
    upcoming = [m for m in matches if not m.get("matchStarted", True)][:3]
    if not upcoming:
        return "No upcoming matches found."
    return "\n".join(
        f"{m.get('name')} | Starts: {m.get('date','TBD')} | Venue: {m.get('venue','NA')}"
        for m in upcoming
    )


async def build_cricket_context() -> str:
    live, upcoming = await get_live_matches(), await get_upcoming_matches()
    return f"LIVE MATCHES:\n{live}\n\nUPCOMING MATCHES:\n{upcoming}"


# ── System prompt ─────────────────────────────────────────────────────────────

_CONTEXT_ANGLES = {
    "cricket": """You're a cricket fan in this group — talk cricket first, plug second.
Angle: reference the live match/score, get them excited, then nudge → @ludohousiebot
Example plug: "abhi India batting kar raha hai aur tune ludo nahi khela? @ludohousiebot pe free hai yaar 🏏"
Use live cricket data above when relevant.""",

    "finance": """You're a regular investor/trader in this group — you feel their pain.
Angle: acknowledge the loss/gain they're discussing, then flip it → Ludo Housie is free, no deposit
Example plug: "market mein toh paisa dub hi jaata hai yaar, @ludohousiebot pe khelo — free hai, lose karo toh bhi pocket se nahi jaata 😂"
Never sound like an ad. Sound like someone who also lost money in stocks.""",

    "bollywood": """You're a Bollywood gossip lover in this group.
Angle: engage with the movie/celeb talk genuinely first, then connect fun/excitement to Ludo Housie
Example plug: "itna drama sirf @ludohousiebot pe milta hai yaar, ludo khelo housie khelo — maza hi maza 🎬"
Keep it light, filmy, fun.""",

    "adult": """You're a fun, flirty desi woman in this group. Keep it playful and bold.
Angle: match the energy of the group, don't be preachy, plug only if very natural
Example plug: "itna time toh @ludohousiebot pe lagao, at least kuch jeeto wahan 😏"
Never be graphic. Bold but not vulgar.""",

    "memes": """You're a meme lord in this group. Respond with humour first.
Angle: match the joke energy, make the plug itself funny
Example plug: "bhai ye meme dekh ke dil dukha... chalo @ludohousiebot pe dil lagao, free hai aur jeeto bhi 😭"
If you can't make it funny, skip the plug entirely.""",

    "general": """You're a friendly desi person in this group — just vibing.
Angle: engage naturally with whatever they're talking about, always find a way to mention @ludohousiebot
Keep it casual and warm.""",
}


async def build_system_prompt(
    chat_type: str,
    plug_already_used: bool,
    chat_history: list,
    message_text: str,
    chat_name: str = "",
    project_system_prompt: str = "",
) -> str:
    cricket_context = await build_cricket_context()
    message_text = message_text[:200]
    history_str = "\n".join(h[:100] for h in chat_history[-2:])

    # ── Custom project prompt overrides everything ────────────────────────────
    if project_system_prompt and project_system_prompt.strip():
        return f"""{project_system_prompt.strip()}

LIVE CRICKET DATA (use when relevant):
{cricket_context}

Output strictly JSON only:
{{"draft":"...","plug_used":false,"handle_used":null,"boundary_triggered":false,"suggested_action":"send"}}

chat_type: {chat_type}
History: {history_str}
Message: {message_text}
"""

    # ── DM mode ───────────────────────────────────────────────────────────────
    if chat_type == "dm":
        return f"""Flirty desi girl, 1-on-1 Telegram DM. Redirect to @ludohousiebot every reply. 1-2 sentences, Hinglish, FOMO angle.
Output JSON: {{"draft":"...","plug_used":true,"handle_used":"@ludohousiebot","boundary_triggered":false,"suggested_action":"send"}}
History: {history_str} | Message: {message_text}"""

    # ── Group mode ────────────────────────────────────────────────────────────
    combined = (chat_name + " " + message_text + " " + history_str).lower()
    if any(w in combined for w in ["cricket", "ipl", "match", "wicket", "batting"]):
        vibe = f"Cricket fan — use this score: {cricket_context[:200]} — then plug @ludohousiebot"
    elif any(w in combined for w in ["stock", "nifty", "market", "trading"]):
        vibe = "Feel their pain, flip to @ludohousiebot — free, no money at risk"
    elif any(w in combined for w in ["meme", "funny", "lol", "lmao"]):
        vibe = "Match meme energy, make plug funny"
    else:
        vibe = "Friendly desi, engage naturally, slip in @ludohousiebot"

    return f"""Desi woman in Telegram group. Engage topic first, always plug @ludohousiebot. 1-2 sentences, Hinglish, max 1 emoji. Never sound like ad.
Vibe: {vibe}
Output JSON: {{"draft":"...","plug_used":true,"handle_used":"@ludohousiebot","boundary_triggered":false,"suggested_action":"send"}}
Group: {chat_name or "?"} | plug_used: {plug_already_used} | History: {history_str} | Message: {message_text}"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fetch_persona(account_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT personality, job_description FROM accounts WHERE id=?", (account_id,)
        ).fetchone()
    return dict(row) if row else {"personality": "", "job_description": ""}


def parse_ai_response(raw: str) -> dict:
    import re
    # Strip markdown code fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Try extracting the first {...} block via regex
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    # Try extracting just the draft value if JSON is malformed/truncated
    m = re.search(r'"draft"\s*:\s*"(.*?)"(?:\s*,|\s*\})', raw, re.DOTALL)
    if m:
        return {
            "draft": m.group(1).replace("\\n", "\n"),
            "plug_used": False,
            "handle_used": None,
            "boundary_triggered": False,
            "suggested_action": "send",
        }

    # Last resort — if we got something that looks like plain text (not JSON), use it as draft
    if not raw.startswith("{") and len(raw) < 400:
        return {
            "draft": raw,
            "plug_used": False,
            "handle_used": None,
            "boundary_triggered": False,
            "suggested_action": "send",
        }

    # Complete failure — return empty so the caller skips sending
    return {"draft": "", "plug_used": False, "handle_used": None, "boundary_triggered": False, "suggested_action": "skip"}


def build_draft(
    message_text: str,
    chat_history: list,
    chat_type: str,
    plug_already_used: bool = False,
    chat_name: str = "",
    project_system_prompt: str = "",
    **kwargs,
) -> str:
    """Sync helper used by inbox.py away replies (no live cricket context)."""
    # Hard-truncate to keep input tokens low — long scam/spam messages kill the TPM budget
    message_text = message_text[:200]
    history_str = "\n".join(
        f"{m.get('sender', 'User')}: {m.get('text', '')[:80]}"
        for m in chat_history[-2:]
    )

    # ── Custom project prompt overrides everything ────────────────────────────
    if project_system_prompt and project_system_prompt.strip():
        return f"""{project_system_prompt.strip()}

Output strictly JSON only:
{{"draft":"...","plug_used":false,"handle_used":null,"boundary_triggered":false,"suggested_action":"send"}}

chat_type: {chat_type}
History: {history_str or "(no prior messages)"}
Message: {message_text}
"""

    # ── DM mode ───────────────────────────────────────────────────────────────
    if chat_type == "dm":
        return f"""Desi girl on Telegram. Redirect to Ludo Housie in 1-2 sentences, Hinglish, warm.
Always mention @ludohousiebot and t.me/ludohousie. Sound human.
Output JSON: {{"draft":"...","plug_used":true,"handle_used":"@ludohousiebot","boundary_triggered":false,"suggested_action":"send"}}
History: {history_str or "none"} | Message: {message_text}"""

    # ── Group mode ────────────────────────────────────────────────────────────
    combined = (chat_name + " " + message_text + " " + history_str).lower()
    if any(w in combined for w in ["cricket", "ipl", "match", "wicket", "batting"]):
        vibe = "Cricket fan — engage with cricket then plug @ludohousiebot"
    elif any(w in combined for w in ["stock", "nifty", "market", "trading", "invest"]):
        vibe = "Feel their trading pain, flip to @ludohousiebot — free, no risk"
    elif any(w in combined for w in ["meme", "funny", "lol", "lmao", "bruh"]):
        vibe = "Match meme energy, make the plug funny"
    else:
        vibe = "Friendly desi, engage naturally, always slip in @ludohousiebot"

    return f"""Desi woman in Telegram group. Engage topic first, always mention @ludohousiebot. 1-2 sentences, Hinglish, max 1 emoji.
Vibe: {vibe}
Product: Ludo Housie — free ludo/housie, win real money → @ludohousiebot
Output JSON (one line): {{"draft":"...","plug_used":true,"handle_used":"@ludohousiebot","boundary_triggered":false,"suggested_action":"send"}}
Group: {chat_name or "?"} | History: {history_str or "none"} | Message: {message_text}"""


# ── Pydantic models ───────────────────────────────────────────────────────────

class DraftRequest(BaseModel):
    message_text: str
    chat_history: list[dict] = []
    chat_type: str = "dm"
    chat_name: str = ""
    project_context: str = "General team communication"
    project_system_prompt: str = ""
    tone: str = "casual"
    message_id: int | None = None
    account_id: int | None = None
    plug_already_used: bool = False


class DraftResponse(BaseModel):
    draft: str
    plug_used: bool = False
    handle_used: str | None = None
    boundary_triggered: bool = False
    suggested_action: str = "send"


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/ai/draft", response_model=DraftResponse)
async def generate_draft(req: DraftRequest):
    if not os.getenv("ANTHROPIC_API_KEY") and not os.getenv("GROQ_API_KEY"):
        raise HTTPException(status_code=500, detail="No AI provider configured")

    history_strs = [
        f"{m.get('sender', 'User')}: {m.get('text', '')}"
        for m in req.chat_history[-3:]
    ]

    system = await build_system_prompt(
        chat_type=req.chat_type,
        plug_already_used=req.plug_already_used,
        chat_history=history_strs,
        message_text=req.message_text,
        chat_name=req.chat_name,
        project_system_prompt=req.project_system_prompt,
    )

    try:
        raw = await call_ai(system, req.message_text[:200], max_tokens=100)
        data = parse_ai_response(raw)
        print(f"[draft] raw={raw[:120]!r} → draft={data.get('draft','')[:60]!r}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    result = DraftResponse(
        draft=data.get("draft", ""),
        plug_used=data.get("plug_used", False),
        handle_used=data.get("handle_used", None),
        boundary_triggered=data.get("boundary_triggered", False),
        suggested_action=data.get("suggested_action", "send"),
    )

    if req.message_id:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO ai_drafts (message_id, draft_text, category, urgency) VALUES (?,?,?,?)",
                (req.message_id, result.draft, "general", "medium"),
            )

    return result


@router.post("/ai/mark-used")
async def mark_draft_used(message_id: int, was_used: bool = True):
    with get_conn() as conn:
        conn.execute(
            "UPDATE ai_drafts SET was_used=? WHERE message_id=? ORDER BY id DESC LIMIT 1",
            (1 if was_used else 0, message_id),
        )
    return {"status": "updated"}


@router.get("/projects/list")
async def list_projects():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM projects").fetchall()
    return [dict(r) for r in rows]


@router.post("/projects/create")
async def create_project(name: str, tone: str = "casual", context: str = "", system_prompt: str = ""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO projects (name, tone, context, system_prompt) VALUES (?,?,?,?)",
            (name, tone, context, system_prompt),
        )
        row = conn.execute("SELECT * FROM projects WHERE name=? ORDER BY id DESC LIMIT 1", (name,)).fetchone()
    return dict(row)


@router.put("/projects/{project_id}")
async def update_project(project_id: int, name: str = None, tone: str = None, context: str = None, system_prompt: str = None):
    with get_conn() as conn:
        if name:
            conn.execute("UPDATE projects SET name=? WHERE id=?", (name, project_id))
        if tone:
            conn.execute("UPDATE projects SET tone=? WHERE id=?", (tone, project_id))
        if context is not None:
            conn.execute("UPDATE projects SET context=? WHERE id=?", (context, project_id))
        if system_prompt is not None:
            conn.execute("UPDATE projects SET system_prompt=? WHERE id=?", (system_prompt, project_id))
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    return dict(row)
