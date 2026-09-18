import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from db import get_connection, init_db
from gacha import GACHA_COST, perform_draw
from battle import build_battle_card, card_snapshot, run_team_battle
from rooms import manager as room_manager, RoomPlayer, Room, MAX_PLAYERS_PER_ROOM

TARGET_TIMEOUT_SEC = 20


def _ai_pick_target(targets: list[tuple[int, object]]) -> tuple[int, object]:
    """AI 위임 시 대상 선택: 체력이 가장 낮은 적을 집중 공격."""
    return min(targets, key=lambda t: t[1].hp)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="삼국지 카드 배틀 - Gacha API", lifespan=lifespan)


class CreatePlayerRequest(BaseModel):
    nickname: str


def _create_player_row(conn, nickname: str) -> dict:
    cur = conn.cursor()
    cur.execute("INSERT INTO players (nickname) VALUES (?)", (nickname,))
    conn.commit()
    player_id = cur.lastrowid
    row = conn.execute("SELECT id, nickname, rings FROM players WHERE id = ?", (player_id,)).fetchone()
    return dict(row)


@app.post("/players")
def create_player(req: CreatePlayerRequest):
    conn = get_connection()
    row = _create_player_row(conn, req.nickname)
    conn.close()
    return row


def _purchase_cooldown_remaining_sec(last_purchase_at: str | None) -> int:
    if last_purchase_at is None:
        return 0
    elapsed = (datetime.utcnow() - datetime.fromisoformat(last_purchase_at)).total_seconds()
    return max(0, round(RING_PURCHASE_COOLDOWN_SEC - elapsed))


@app.get("/players/{player_id}")
def get_player(player_id: int):
    conn = get_connection()
    row = conn.execute(
        "SELECT id, nickname, rings, last_ring_purchase_at FROM players WHERE id = ?",
        (player_id,),
    ).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="플레이어를 찾을 수 없습니다.")
    data = dict(row)
    data["purchase_cooldown_sec"] = _purchase_cooldown_remaining_sec(data.pop("last_ring_purchase_at"))
    return data


# 링(재화) 구매 - 지금은 실제 결제 없이 즉시 지급하는 임시(mock) 기능.
# 나중에 실제 결제(PG 연동)로 교체할 자리이며, 그때는 이 PACKAGES 구조와
# 엔드포인트 시그니처를 그대로 활용하면 된다.
RING_PACKAGES = {
    "small": {"rings": 500, "price_label": "₩1,200 (예시가)"},
    "medium": {"rings": 1200, "price_label": "₩2,900 (예시가)"},
    "large": {"rings": 3300, "price_label": "₩6,900 (예시가, 보너스 300링 포함)"},
}

# 무한 구매 방지용 쿨다운(초). placeholder 값 - 밸런스 조정 시 이 값만 바꾸면 된다.
RING_PURCHASE_COOLDOWN_SEC = 300

# 대전 종료 시 지급하는 링. 참여만 해도 최소 보상은 받고, 승리 시 더 많이 받는다.
BATTLE_WIN_REWARD = 80
BATTLE_LOSE_REWARD = 30


@app.get("/ring-packages")
def get_ring_packages():
    return [{"package_id": pid, **info} for pid, info in RING_PACKAGES.items()]


class PurchaseRingsRequest(BaseModel):
    package_id: str


@app.post("/players/{player_id}/purchase_rings")
def purchase_rings(player_id: int, req: PurchaseRingsRequest):
    package = RING_PACKAGES.get(req.package_id)
    if package is None:
        raise HTTPException(status_code=400, detail="존재하지 않는 상품입니다.")

    conn = get_connection()
    player = conn.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
    if player is None:
        conn.close()
        raise HTTPException(status_code=404, detail="플레이어를 찾을 수 없습니다.")

    cooldown_remaining = _purchase_cooldown_remaining_sec(player["last_ring_purchase_at"])
    if cooldown_remaining > 0:
        conn.close()
        raise HTTPException(
            status_code=429,
            detail=f"다음 구매까지 {cooldown_remaining}초 남았습니다.",
        )

    conn.execute(
        "UPDATE players SET rings = rings + ?, last_ring_purchase_at = ? WHERE id = ?",
        (package["rings"], datetime.utcnow().isoformat(), player_id),
    )
    conn.commit()
    remaining = conn.execute("SELECT rings FROM players WHERE id = ?", (player_id,)).fetchone()["rings"]
    conn.close()

    return {
        "purchased_rings": package["rings"],
        "remaining_rings": remaining,
        "purchase_cooldown_sec": RING_PURCHASE_COOLDOWN_SEC,
    }


@app.post("/gacha/draw")
def gacha_draw(player_id: int):
    conn = get_connection()
    player = conn.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
    if player is None:
        conn.close()
        raise HTTPException(status_code=404, detail="플레이어를 찾을 수 없습니다.")
    if player["rings"] < GACHA_COST:
        conn.close()
        raise HTTPException(status_code=400, detail="링이 부족합니다.")

    card = perform_draw(conn)

    conn.execute(
        "UPDATE players SET rings = rings - ? WHERE id = ?",
        (GACHA_COST, player_id),
    )
    conn.execute(
        "INSERT INTO player_cards (player_id, general_card_id) VALUES (?, ?)",
        (player_id, card["id"]),
    )
    conn.commit()

    remaining = conn.execute("SELECT rings FROM players WHERE id = ?", (player_id,)).fetchone()["rings"]
    conn.close()

    return {
        "general_name": card["name"],
        "faction": card["faction"],
        "rarity": card["rarity"],
        "skill_name": card["skill_name"],
        "skill_description": card["skill_description"],
        "stats": {
            "hp": card["hp"],
            "mp": card["mp"],
            "atk": card["atk"],
            "int": card["int_stat"],
            "war": card["war_stat"],
            "leadership": card["leadership"],
            "charm": card["charm"],
            "politics": card["politics"],
        },
        "remaining_rings": remaining,
    }


@app.get("/players/{player_id}/cards")
def get_player_cards(player_id: int):
    conn = get_connection()
    rows = conn.execute(
        "SELECT pc.id AS player_card_id, pc.enhance_level, pc.obtained_at, "
        "g.name, g.faction, g.skill_name, gc.rarity, gc.hp, gc.mp, gc.atk "
        "FROM player_cards pc "
        "JOIN general_cards gc ON gc.id = pc.general_card_id "
        "JOIN generals g ON g.id = gc.general_id "
        "WHERE pc.player_id = ? "
        "ORDER BY pc.obtained_at DESC",
        (player_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


class BattleRequest(BaseModel):
    deck_a: list[int]  # player_card_id 5개
    deck_b: list[int]  # player_card_id 5개


def _load_deck(conn, player_card_ids: list[int]):
    cards = []
    for pcid in player_card_ids:
        row = conn.execute(
            "SELECT pc.enhance_level, gc.*, "
            "g.name, g.skill_name, g.skill_description, "
            "g.skill_effect_type, g.skill_scope, g.skill_stat "
            "FROM player_cards pc "
            "JOIN general_cards gc ON gc.id = pc.general_card_id "
            "JOIN generals g ON g.id = gc.general_id "
            "WHERE pc.id = ?",
            (pcid,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"player_card_id {pcid}를 찾을 수 없습니다.")
        cards.append(build_battle_card(row, row["enhance_level"]))
    return cards


@app.post("/battle/simulate")
async def battle_simulate(req: BattleRequest):
    """대상 선택을 전부 AI에게 맡기는 자동 시뮬레이션 (테스트/디버그용)."""
    if len(req.deck_a) != 5 or len(req.deck_b) != 5:
        raise HTTPException(status_code=400, detail="덱은 반드시 5장이어야 합니다.")

    conn = get_connection()
    deck_a = _load_deck(conn, req.deck_a)
    deck_b = _load_deck(conn, req.deck_b)
    conn.close()

    events: list[dict] = []

    async def emit(event):
        events.append(event)

    async def choose_target(side, actor, targets):
        return _ai_pick_target(targets)

    result = await run_team_battle(deck_a, deck_b, emit, choose_target)
    return {**result, "events": events}


# ---------------------------------------------------------------------------
# 방(로비) - 방 코드 생성/초대 기반 멀티플레이
# ---------------------------------------------------------------------------

class CreateRoomRequest(BaseModel):
    nickname: str
    title: str


class JoinRoomRequest(BaseModel):
    nickname: str


@app.get("/rooms")
def list_rooms():
    return [
        {
            "room_code": room.code,
            "title": room.title,
            "player_count": len(room.players),
            "max_players": MAX_PLAYERS_PER_ROOM,
            "in_battle": any(p.deck is not None for p in room.players.values()),
        }
        for room in room_manager.list_rooms()
        if not room.is_full() and not room.is_solo
    ]


@app.post("/rooms")
def create_room(req: CreateRoomRequest):
    conn = get_connection()
    player = _create_player_row(conn, req.nickname)
    conn.close()

    room = room_manager.create_room(player["id"], player["nickname"], req.title)
    return {
        "room_code": room.code,
        "title": room.title,
        "player_id": player["id"],
        "nickname": player["nickname"],
    }


@app.post("/rooms/{room_code}/join")
def join_room(room_code: str, req: JoinRoomRequest):
    room = room_manager.get_room(room_code)
    if room is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 방입니다.")
    if room.is_solo:
        raise HTTPException(status_code=400, detail="싱글 플레이 방에는 참가할 수 없습니다.")
    if room.is_full():
        raise HTTPException(status_code=400, detail="방 인원이 가득 찼습니다.")

    conn = get_connection()
    player = _create_player_row(conn, req.nickname)
    conn.close()

    room.players[player["id"]] = RoomPlayer(player_id=player["id"], nickname=player["nickname"])
    return {
        "room_code": room.code,
        "title": room.title,
        "player_id": player["id"],
        "nickname": player["nickname"],
    }


AI_NICKNAME = "AI"


def _draw_ai_deck(conn, ai_player_id: int) -> list[int]:
    """무작위 장수 카드 5장을 AI 소유로 만들어서 player_card_id 목록을 반환."""
    cur = conn.cursor()
    card_rows = cur.execute("SELECT id FROM general_cards ORDER BY RANDOM() LIMIT 5").fetchall()
    deck_ids = []
    for row in card_rows:
        cur.execute(
            "INSERT INTO player_cards (player_id, general_card_id) VALUES (?, ?)",
            (ai_player_id, row["id"]),
        )
        deck_ids.append(cur.lastrowid)
    conn.commit()
    return deck_ids


@app.post("/rooms/{room_code}/ai_opponent")
def add_ai_opponent(room_code: str):
    """싱글 플레이용 - 방에 AI 상대를 추가하고 무작위 장수 카드 5장으로 덱을 바로 채워준다."""
    room = room_manager.get_room(room_code)
    if room is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 방입니다.")
    if room.is_full():
        raise HTTPException(status_code=400, detail="방 인원이 가득 찼습니다.")

    conn = get_connection()
    ai_player = _create_player_row(conn, AI_NICKNAME)
    deck_ids = _draw_ai_deck(conn, ai_player["id"])
    conn.close()

    room.players[ai_player["id"]] = RoomPlayer(
        player_id=ai_player["id"], nickname=AI_NICKNAME,
        ready=True, deck=deck_ids, auto_target=True,
    )
    room.is_solo = True
    return {"room_code": room.code, "ai_player_id": ai_player["id"]}


def _lobby_payload(room: Room) -> dict:
    return {
        "type": "lobby_update",
        "room_code": room.code,
        "title": room.title,
        "host_player_id": room.host_player_id,
        "players": [
            {
                "player_id": p.player_id,
                "nickname": p.nickname,
                "ready": p.ready,
                "deck_submitted": p.deck is not None,
                "auto_target": p.auto_target,
            }
            for p in room.players.values()
        ],
    }


async def _broadcast(room: Room, payload: dict) -> None:
    for player in list(room.players.values()):
        if player.websocket is not None:
            try:
                await player.websocket.send_json(payload)
            except Exception:
                pass


async def _maybe_run_battle(room: Room) -> None:
    contenders = [p for p in room.players.values() if p.deck is not None]
    if len(contenders) < 2:
        return
    if len(contenders) > 2:
        await _broadcast(room, {
            "type": "error",
            "message": "지금은 2명 대결(PvP)만 지원합니다. 협동전은 준비 중입니다.",
        })
        return
    if room.battle_running:
        return
    room.battle_running = True

    try:
        p1, p2 = contenders
        players_by_side = {"A": p1, "B": p2}
        conn = get_connection()
        try:
            deck_a = _load_deck(conn, p1.deck)
            deck_b = _load_deck(conn, p2.deck)
        finally:
            conn.close()

        async def emit(event: dict) -> None:
            await _broadcast(room, {"type": "battle_event", **event})

        async def choose_target(side, actor, targets):
            player = players_by_side[side]
            if player.auto_target or player.websocket is None:
                return _ai_pick_target(targets)

            enemy_side = "B" if side == "A" else "A"
            await emit({
                "kind": "waiting_choice",
                "text": f"{actor.name}의 대상 선택을 기다리는 중... (최대 {TARGET_TIMEOUT_SEC}초)",
            })
            future = asyncio.get_running_loop().create_future()
            player.pending_target = future
            try:
                await player.websocket.send_json({
                    "type": "await_target",
                    "actor": actor.name,
                    "targets": [
                        {**card_snapshot(c), "side": enemy_side, "pos": idx} for idx, c in targets
                    ],
                    "timeout_sec": TARGET_TIMEOUT_SEC,
                })
                target_pos = await asyncio.wait_for(future, timeout=TARGET_TIMEOUT_SEC)
                for idx, c in targets:
                    if idx == target_pos:
                        return idx, c
                return _ai_pick_target(targets)
            except Exception:
                return _ai_pick_target(targets)
            finally:
                player.pending_target = None

        result = await run_team_battle(
            deck_a, deck_b, emit, choose_target,
            names={"A": p1.nickname, "B": p2.nickname},
        )
        winner_nickname = p1.nickname if result["winner"] == "A" else p2.nickname

        p1_reward = BATTLE_WIN_REWARD if result["winner"] == "A" else BATTLE_LOSE_REWARD
        p2_reward = BATTLE_WIN_REWARD if result["winner"] == "B" else BATTLE_LOSE_REWARD
        conn = get_connection()
        conn.execute("UPDATE players SET rings = rings + ? WHERE id = ?", (p1_reward, p1.player_id))
        conn.execute("UPDATE players SET rings = rings + ? WHERE id = ?", (p2_reward, p2.player_id))
        conn.commit()
        conn.close()

        await _broadcast(room, {
            "type": "battle_result",
            "player_a": p1.nickname,
            "player_b": p2.nickname,
            "winner_nickname": winner_nickname,
            "rings_earned": {"A": p1_reward, "B": p2_reward},
            **result,
        })

        for p in room.players.values():
            p.deck = None
            p.ready = False

        if room.is_solo:
            ai_player = next((p for p in room.players.values() if p.nickname == AI_NICKNAME), None)
            if ai_player is not None:
                conn = get_connection()
                ai_player.deck = _draw_ai_deck(conn, ai_player.player_id)
                conn.close()
                ai_player.ready = True
                await _broadcast(room, _lobby_payload(room))
    finally:
        room.battle_running = False


@app.websocket("/ws/rooms/{room_code}")
async def room_websocket(websocket: WebSocket, room_code: str, player_id: int):
    room = room_manager.get_room(room_code)
    if room is None or player_id not in room.players:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    player = room.players[player_id]
    player.websocket = websocket
    await _broadcast(room, _lobby_payload(room))

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "ready":
                player.ready = not player.ready
                await _broadcast(room, _lobby_payload(room))

            elif msg_type == "submit_deck":
                deck = data.get("deck")
                if not isinstance(deck, list) or len(deck) != 5:
                    await websocket.send_json({"type": "error", "message": "덱은 5장이어야 합니다."})
                    continue
                player.deck = deck
                await _broadcast(room, _lobby_payload(room))
                # 별도 태스크로 띄운다 - 이 커넥션의 수신 루프 안에서 그대로 await하면
                # 이 플레이어 자신이 전투 중 대상을 골라야 할 때 그 응답(choose_target)을
                # 받을 수신 루프 자체가 막혀 있어 자기 선택이 계속 타임아웃되는 문제가 있었다.
                asyncio.create_task(_maybe_run_battle(room))

            elif msg_type == "set_auto":
                player.auto_target = bool(data.get("auto"))
                await _broadcast(room, _lobby_payload(room))

            elif msg_type == "choose_target":
                future = player.pending_target
                if future is not None and not future.done():
                    future.set_result(data.get("pos"))

    except WebSocketDisconnect:
        room.players.pop(player_id, None)
        await _broadcast(room, _lobby_payload(room))
        room_manager.drop_room_if_empty(room_code)


# ---------------------------------------------------------------------------
# 프론트엔드 정적 파일 서빙 (반드시 API 라우트들보다 아래에 위치)
# ---------------------------------------------------------------------------

class NoCacheStaticFiles(StaticFiles):
    """개발 중에는 브라우저가 옛날 app.js/style.css를 계속 들고 있어서 수정이 반영이
    안 된 것처럼 보이는 일이 잦다. no-cache를 붙여 매번 서버에 물어보게 한다
    (내용이 그대로면 304로 끝나서 비용은 거의 없다)."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
app.mount("/", NoCacheStaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
