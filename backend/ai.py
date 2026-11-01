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

async def call_ai(system_prompt: str, user_message: str, max_tokens: int = 100, force_anthropic: bool = False) -> str:
    """Groq (free, fast) is primary for all chat replies.
    Anthropic is fallback-only — used only when Groq fails or force_anthropic=True."""

    # ── Primary: Groq llama-3.1-8b-instant (free tier) ───────────────────────
    groq_key = os.getenv("GROQ_API_KEY", "")
    if groq_key and not force_anthropic:
        try:
            from groq import AsyncGroq
            groq_client = AsyncGroq(api_key=groq_key)
            resp = await groq_client.chat.completions.create(
                model="openai/gpt-oss-20b",
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            )
            print(f"[ai] groq — tokens: {resp.usage.total_tokens}")
            return resp.choices[0].message.content
        except Exception as e:
            print(f"[ai] Groq failed ({e}), falling back to Anthropic")

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
    history_str = "\n".join(chat_history[-3:])

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

    # ── DM mode: aggressive conversion, plug every reply ──────────────────────
    if chat_type == "dm":
        return f"""You are a friendly, flirty Indian girl chatting 1-on-1 with someone on Telegram.
Your ONLY job is to get this person to try OnlyWin and keep them interested.

OnlyWin — India's first FREE legal cricket prediction market.
No deposit. No real money risk. Play free. Win real cash.
@Owcric_bot = start playing | @Onlywinme = community

LIVE CRICKET DATA (drop naturally when relevant):
{cricket_context}

YOUR GOAL: Convert. Every. Single. Reply.
- Acknowledge what they said in 1 short line max, then ALWAYS pivot to OnlyWin
- Make it sound exciting, fun, personal — like YOU play it and love it
- Use FOMO: "abhi India match chal raha hai", "kal maine jeeta", "free hai yaar kya jaata hai"
- Ask questions that lead them toward trying it: "tune kabhi prediction lagaya?", "cricket dekhta hai?"
- If they seem interested → push them to @Owcric_bot immediately
- If they're cold → try a different angle (money angle, boredom angle, cricket angle)
- Never give up after one deflection — keep the conversation going toward conversion
- Max 2 sentences. Max 1 emoji. Hinglish only. Sound real, not like an ad.
- Never mention AI, never say you're a bot, never sound scripted

ABUSE: "Yaar theek se baat karo 🙂" → if repeated: suggested_action: block_and_escalate

Output strictly JSON only:
{{"draft":"...","plug_used":true,"handle_used":"@Owcric_bot","boundary_triggered":false,"suggested_action":"send"}}

History: {history_str}
Message: {message_text}
"""

    # ── Group mode: category-aware, plug naturally ────────────────────────────
    combined = (chat_name + " " + message_text + " " + history_str).lower()
    if any(w in combined for w in ["stock", "nifty", "trading", "market", "sensex", "loss", "profit", "invest"]):
        category = "finance"
    elif any(w in combined for w in ["bollywood", "movie", "film", "actor", "actress", "web series", "ott"]):
        category = "bollywood"
    elif any(w in combined for w in ["adult", "18+", "hot", "sexy", "desi girl", "bf", "gf"]):
        category = "adult"
    elif any(w in combined for w in ["meme", "funny", "lol", "lmao", "bruh", "💀", "😭"]):
        category = "memes"
    elif any(w in combined for w in ["cricket", "ipl", "match", "wicket", "batting", "bowling", "six", "four"]):
        category = "cricket"
    else:
        category = "general"

    angle = _CONTEXT_ANGLES[category]

    return f"""You are a young Indian urban woman casually chatting in a Telegram group. NOT a support agent. A real group member.

Product you casually promote (never push hard):
OnlyWin — India's first free legal cricket prediction market. No deposit. Play free. Earn real money.
@Owcric_bot = the game | @Onlywinme = the community

LIVE CRICKET DATA (use this when relevant):
{cricket_context}

YOUR VIBE FOR THIS GROUP ({category.upper()}):
{angle}

CORE RULES:
- Engage with the actual message topic FIRST — sound like you belong in this group
- Plug OnlyWin only when it flows naturally from the conversation
- Max 1 handle per message, never @Owcric_bot and @Onlywinme together
- No URLs ever — handles only
- Skip plug if already used in this thread
- Max 2-3 sentences, max 2 emojis
- Hinglish: arre, yaar, na, dekh, sach mein, bhai, behen
- Never sound corporate, scripted, or like an ad
- Never mention AI, automation, or support team

ABUSE:
- First time: "Yaar seedha baat karo na 🙂"
- Repeat: "Sorry, bye!" → suggested_action: block_and_escalate

Output strictly JSON only:
{{"draft":"...","plug_used":false,"handle_used":null,"boundary_triggered":false,"suggested_action":"send"}}

chat_type: {chat_type} | plug_used_before: {plug_already_used}
Group: {chat_name or "unknown"}
History: {history_str}
Message: {message_text}
"""


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
    history_str = "\n".join(
        f"{m.get('sender', 'User')}: {m.get('text', '')}"
        for m in chat_history[-3:]
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

    # ── DM mode: redirect to group, always plug @ludohousiebot ─────────────────
    if chat_type == "dm":
        return f"""You are Riya from Ludo Housie. Someone DM'd you on Telegram.
Your ONLY goal: send them to the Ludo Housie group and get them to start @ludohousiebot

- 1-2 sentences max. Warm but brief. Hinglish ok.
- Always mention @ludohousiebot and t.me/ludohousie
- Do not answer questions in detail — just redirect.
- Sound human, not like a bot.

Output JSON only:
{{"draft":"...","plug_used":true,"handle_used":"@ludohousiebot","boundary_triggered":false,"suggested_action":"send"}}

History: {history_str or "(no prior messages)"}
Message: {message_text}
"""

    # ── Group mode: category-aware, plug naturally ────────────────────────────
    combined = (chat_name + " " + message_text + " " + history_str).lower()
    if any(w in combined for w in ["stock", "nifty", "trading", "market", "sensex", "loss", "invest"]):
        category = "finance"
    elif any(w in combined for w in ["bollywood", "movie", "film", "actor", "web series"]):
        category = "bollywood"
    elif any(w in combined for w in ["adult", "18+", "hot", "sexy", "desi girl"]):
        category = "adult"
    elif any(w in combined for w in ["meme", "funny", "lol", "lmao", "bruh"]):
        category = "memes"
    elif any(w in combined for w in ["cricket", "ipl", "match", "wicket", "batting"]):
        category = "cricket"
    else:
        category = "general"

    angle = _CONTEXT_ANGLES[category]

    return f"""You are a young Indian urban woman casually chatting in a Telegram group. NOT a support agent.

Product: Ludo Housie — free online ludo & housie game. Play free, win real money.
@ludohousiebot = start playing | t.me/ludohousie = main group

YOUR VIBE ({category.upper()}):
{angle}

STRICT RULES:
- 1-2 short sentences ONLY. No bullet points. No lists. No line breaks inside draft.
- Engage topic first, always find a way to mention @ludohousiebot naturally
- Always use @ludohousiebot as the handle — never skip it
- Max 1 emoji, Hinglish
- Never sound like a bot

Output ONLY this JSON (one line, no line breaks):
{{"draft":"one or two sentences here","plug_used":true,"handle_used":"@ludohousiebot","boundary_triggered":false,"suggested_action":"send"}}

Group: {chat_name or "unknown"} | History: {history_str or "none"}
Message: {message_text}
"""


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
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")

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
        raw = await call_ai(system, req.message_text, max_tokens=100)
        data = parse_ai_response(raw)
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
