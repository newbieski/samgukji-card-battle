from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from db import get_connection, init_db
from gacha import GACHA_COST, perform_draw
from battle import build_battle_card, simulate_deck_battle
from rooms import manager as room_manager, RoomPlayer, Room


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


@app.get("/players/{player_id}")
def get_player(player_id: int):
    conn = get_connection()
    row = conn.execute("SELECT id, nickname, rings FROM players WHERE id = ?", (player_id,)).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="플레이어를 찾을 수 없습니다.")
    return dict(row)


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
            "g.skill_effect_type, g.skill_scope, g.skill_stat, g.skill_potency "
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
def battle_simulate(req: BattleRequest):
    if len(req.deck_a) != 5 or len(req.deck_b) != 5:
        raise HTTPException(status_code=400, detail="덱은 반드시 5장이어야 합니다.")

    conn = get_connection()
    deck_a = _load_deck(conn, req.deck_a)
    deck_b = _load_deck(conn, req.deck_b)
    conn.close()

    return simulate_deck_battle(deck_a, deck_b)


# ---------------------------------------------------------------------------
# 방(로비) - 방 코드 생성/초대 기반 멀티플레이
# ---------------------------------------------------------------------------

class CreateRoomRequest(BaseModel):
    nickname: str


class JoinRoomRequest(BaseModel):
    nickname: str


@app.post("/rooms")
def create_room(req: CreateRoomRequest):
    conn = get_connection()
    player = _create_player_row(conn, req.nickname)
    conn.close()

    room = room_manager.create_room(player["id"], player["nickname"])
    return {"room_code": room.code, "player_id": player["id"], "nickname": player["nickname"]}


@app.post("/rooms/{room_code}/join")
def join_room(room_code: str, req: JoinRoomRequest):
    room = room_manager.get_room(room_code)
    if room is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 방입니다.")
    if room.is_full():
        raise HTTPException(status_code=400, detail="방 인원이 가득 찼습니다.")

    conn = get_connection()
    player = _create_player_row(conn, req.nickname)
    conn.close()

    room.players[player["id"]] = RoomPlayer(player_id=player["id"], nickname=player["nickname"])
    return {"room_code": room.code, "player_id": player["id"], "nickname": player["nickname"]}


def _lobby_payload(room: Room) -> dict:
    return {
        "type": "lobby_update",
        "room_code": room.code,
        "host_player_id": room.host_player_id,
        "players": [
            {
                "player_id": p.player_id,
                "nickname": p.nickname,
                "ready": p.ready,
                "deck_submitted": p.deck is not None,
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

    p1, p2 = contenders
    conn = get_connection()
    try:
        deck_a = _load_deck(conn, p1.deck)
        deck_b = _load_deck(conn, p2.deck)
    finally:
        conn.close()

    result = simulate_deck_battle(deck_a, deck_b)
    winner_nickname = p1.nickname if result["winner"] == "A" else p2.nickname

    await _broadcast(room, {
        "type": "battle_result",
        "player_a": p1.nickname,
        "player_b": p2.nickname,
        "winner_nickname": winner_nickname,
        **result,
    })

    for p in room.players.values():
        p.deck = None
        p.ready = False


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
                await _maybe_run_battle(room)

    except WebSocketDisconnect:
        room.players.pop(player_id, None)
        await _broadcast(room, _lobby_payload(room))
        room_manager.drop_room_if_empty(room_code)


# ---------------------------------------------------------------------------
# 프론트엔드 정적 파일 서빙 (반드시 API 라우트들보다 아래에 위치)
# ---------------------------------------------------------------------------

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
