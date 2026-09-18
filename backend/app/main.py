import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from db import get_connection, init_db
from gacha import (
    GACHA_COST, MULTI_DRAW_BONUS, MULTI_DRAW_COST, MULTI_DRAW_PAID,
    MULTI_DRAW_TOTAL, RARITY_RATES, perform_draw,
)
from battle import build_battle_card, card_snapshot, run_team_battle, skill_summary
from rooms import manager as room_manager, RoomPlayer, Room, MAX_PLAYERS_PER_ROOM
import scenario
from scenario_data import BATTLES_BY_KEY, MAX_LEVEL, build_enemy_lineup, build_fixed_lineup

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


@app.get("/gacha/info")
def gacha_info():
    """뽑기 비용/확률/패키지 구성. 프론트가 하드코딩하지 않고 여기서 받아 쓴다."""
    return {
        "cost": GACHA_COST,
        "rates": [
            {"rarity": rarity, "percent": round(rate * 100, 2)}
            for rarity, rate in sorted(RARITY_RATES.items(), key=lambda kv: kv[1])
        ],
        "multi": {
            "paid": MULTI_DRAW_PAID,
            "bonus": MULTI_DRAW_BONUS,
            "total": MULTI_DRAW_TOTAL,
            "cost": MULTI_DRAW_COST,
        },
    }


def _draw_payload(card) -> dict:
    return {
        "general_name": card["name"],
        "faction": card["faction"],
        "rarity": card["rarity"],
        "skill_name": card["skill_name"],
        "skill_description": card["skill_description"],
        "skill_effect_type": card["skill_effect_type"],
        "skill_effect_text": skill_summary(
            card["skill_effect_type"], card["skill_scope"],
            card["skill_stat"], card["skill_potency"],
        ),
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
    }


def _spend_and_draw(player_id: int, cost: int, draw_count: int) -> tuple[list[dict], int]:
    """링을 먼저 차감하고 draw_count장을 뽑아 보유 카드에 넣는다."""
    conn = get_connection()
    player = conn.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
    if player is None:
        conn.close()
        raise HTTPException(status_code=404, detail="플레이어를 찾을 수 없습니다.")
    if player["rings"] < cost:
        conn.close()
        raise HTTPException(status_code=400, detail="링이 부족합니다.")

    conn.execute("UPDATE players SET rings = rings - ? WHERE id = ?", (cost, player_id))

    drawn = []
    for _ in range(draw_count):
        card = perform_draw(conn)
        conn.execute(
            "INSERT INTO player_cards (player_id, general_card_id) VALUES (?, ?)",
            (player_id, card["id"]),
        )
        drawn.append(_draw_payload(card))

    conn.commit()
    remaining = conn.execute("SELECT rings FROM players WHERE id = ?", (player_id,)).fetchone()["rings"]
    conn.close()
    return drawn, remaining


@app.post("/gacha/draw")
def gacha_draw(player_id: int):
    drawn, remaining = _spend_and_draw(player_id, GACHA_COST, 1)
    return {**drawn[0], "remaining_rings": remaining}


@app.post("/gacha/draw_multi")
def gacha_draw_multi(player_id: int):
    """패키지 뽑기 - 10장 값으로 11장을 뽑는다."""
    drawn, remaining = _spend_and_draw(player_id, MULTI_DRAW_COST, MULTI_DRAW_TOTAL)
    return {
        "cards": drawn,
        "paid": MULTI_DRAW_PAID,
        "bonus": MULTI_DRAW_BONUS,
        "remaining_rings": remaining,
    }


@app.get("/players/{player_id}/cards")
def get_player_cards(player_id: int):
    conn = get_connection()
    rows = conn.execute(
        "SELECT pc.id AS player_card_id, pc.enhance_level, pc.obtained_at, "
        "g.name, g.faction, g.skill_name, g.skill_description, "
        "g.skill_effect_type, g.skill_scope, g.skill_stat, "
        "gc.rarity, gc.hp, gc.mp, gc.atk, gc.skill_potency "
        "FROM player_cards pc "
        "JOIN general_cards gc ON gc.id = pc.general_card_id "
        "JOIN generals g ON g.id = gc.general_id "
        "WHERE pc.player_id = ? "
        "ORDER BY pc.obtained_at DESC",
        (player_id,),
    ).fetchall()
    conn.close()
    cards = []
    for row in rows:
        card = dict(row)
        card["skill_effect_text"] = skill_summary(
            card["skill_effect_type"], card["skill_scope"],
            card["skill_stat"], card["skill_potency"],
        )
        cards.append(card)
    return cards


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
            "in_battle": any(p.has_deck() for p in room.players.values()),
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


# ---------------------------------------------------------------------------
# 시나리오 (싱글 캠페인)
# ---------------------------------------------------------------------------

class ScenarioStartRequest(BaseModel):
    battle_key: str
    level: int
    deck_mode: str  # "own" | "fixed"


@app.get("/scenario/battles")
def scenario_battles(player_id: int):
    conn = get_connection()
    try:
        return {"battles": scenario.battle_list(conn, player_id)}
    finally:
        conn.close()


@app.get("/scenario/battles/{battle_key}/levels/{level}")
def scenario_stage(battle_key: str, level: int, player_id: int):
    if battle_key not in BATTLES_BY_KEY:
        raise HTTPException(status_code=404, detail="존재하지 않는 전투입니다.")
    if not 1 <= level <= MAX_LEVEL:
        raise HTTPException(status_code=400, detail=f"레벨은 1~{MAX_LEVEL}입니다.")
    conn = get_connection()
    try:
        return scenario.stage_detail(conn, player_id, battle_key, level)
    finally:
        conn.close()


@app.post("/rooms/{room_code}/scenario")
async def start_scenario_stage(room_code: str, req: ScenarioStartRequest):
    """방을 시나리오 스테이지로 바꾼다.

    AI 상대에게 그 스테이지의 적 진용을 들려주고, 고정덱을 골랐다면 플레이어 덱도
    여기서 바로 채워준다(그 경우 덱 편성 화면을 거칠 필요가 없다).
    같은 방에서 다른 스테이지에 다시 도전할 수 있도록, 이미 있는 AI는 재사용한다.
    """
    room = room_manager.get_room(room_code)
    if room is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 방입니다.")
    if room.battle_running:
        raise HTTPException(status_code=409, detail="이미 전투가 진행 중입니다.")
    battle = BATTLES_BY_KEY.get(req.battle_key)
    if battle is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 전투입니다.")
    if not 1 <= req.level <= MAX_LEVEL:
        raise HTTPException(status_code=400, detail=f"레벨은 1~{MAX_LEVEL}입니다.")
    if req.deck_mode not in scenario.DECK_MODES:
        raise HTTPException(status_code=400, detail="덱 모드는 own 또는 fixed 입니다.")

    human = room.players.get(room.host_player_id)
    if human is None:
        raise HTTPException(status_code=400, detail="방에 플레이어가 없습니다.")

    conn = get_connection()
    try:
        if not scenario.is_playable(scenario.cleared_modes(conn, human.player_id),
                                    req.battle_key, req.level):
            raise HTTPException(status_code=403, detail="아직 잠겨 있는 레벨입니다.")

        ai = next((p for p in room.players.values() if p.nickname == AI_NICKNAME), None)
        if ai is None:
            if room.is_full():
                raise HTTPException(status_code=400, detail="방 인원이 가득 찼습니다.")
            ai_row = _create_player_row(conn, AI_NICKNAME)
            ai = RoomPlayer(player_id=ai_row["id"], nickname=AI_NICKNAME, auto_target=True)
            room.players[ai.player_id] = ai
    finally:
        conn.close()

    ai.ready = True
    ai.deck = None
    ai.lineup = build_enemy_lineup(battle, req.level)

    human.ready = True
    human.deck = None
    human.lineup = build_fixed_lineup(battle, req.level) if req.deck_mode == "fixed" else None

    room.is_solo = True
    room.scenario = {
        "battle_key": req.battle_key, "level": req.level, "deck_mode": req.deck_mode,
        "human_player_id": human.player_id, "ai_player_id": ai.player_id,
    }
    await _broadcast(room, _lobby_payload(room))

    # 고정덱이면 양쪽 덱이 이미 다 찼으니 바로 전투를 띄운다.
    # 내 덱이면 플레이어가 submit_deck 을 보낼 때 거기서 시작된다.
    if req.deck_mode == "fixed":
        asyncio.create_task(_maybe_run_battle(room))

    return {
        "room_code": room.code,
        "battle_key": req.battle_key, "battle_name": battle["name"],
        "level": req.level, "deck_mode": req.deck_mode,
        "scene": battle["scene"], "intro": battle["intro"],
        # 고정덱이면 덱을 짤 필요 없이 바로 시작할 수 있다
        "needs_deck": req.deck_mode == "own",
    }


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
                "deck_submitted": p.has_deck(),
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
    contenders = [p for p in room.players.values() if p.has_deck()]
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
        # 시나리오 방에서는 사람이 항상 A, 적(AI)이 B가 되도록 고정한다.
        # 스테이지 보정을 어느 진영에 걸지가 여기에 달려 있다.
        if room.scenario is not None and p1.player_id == room.scenario["ai_player_id"]:
            p1, p2 = p2, p1
        players_by_side = {"A": p1, "B": p2}

        conn = get_connection()
        try:
            def load(player):
                # 시나리오가 내려준 명단이 있으면 보유 카드 대신 그걸 쓴다
                if player.lineup is not None:
                    return scenario.load_lineup(conn, player.lineup)
                return _load_deck(conn, player.deck)
            deck_a, deck_b = load(p1), load(p2)
        finally:
            conn.close()
        decks_by_side = {"A": deck_a, "B": deck_b}

        side_mods = None
        if room.scenario is not None:
            side_mods = {"B": scenario.stage_enemy_mods(
                room.scenario["battle_key"], room.scenario["level"])}

        async def emit(event: dict) -> None:
            await _broadcast(room, {"type": "battle_event", **event})

        async def ask(player, side: str, prompt: dict, waiting_text: str, actor_name=None):
            """사람에게 물어보고 답을 받아온다. AI 위임/타임아웃/오류면 None을 돌려준다.

            전투 중에 위임으로 바꾸면 기다리던 질문이 즉시 None으로 풀려 AI가 대신 정한다.
            질문에는 지금이 누구 차례인지(side)를 같이 실어 보낸다. 장수를 고르기 전에는
            아직 turn_start가 나가지 않아서, 이게 없으면 양쪽 화면의 차례 표시가
            직전 차례에 머물러 있다.
            """
            if player.auto_target or player.websocket is None:
                return None

            await emit({"kind": "waiting_choice", "side": side, "actor": actor_name,
                        "text": f"{waiting_text} (최대 {TARGET_TIMEOUT_SEC}초)"})
            future = asyncio.get_running_loop().create_future()
            player.pending_target = future
            try:
                await player.websocket.send_json({
                    **prompt, "side": side, "timeout_sec": TARGET_TIMEOUT_SEC})
                return await asyncio.wait_for(future, timeout=TARGET_TIMEOUT_SEC)
            except Exception:
                return None
            finally:
                player.pending_target = None

        async def choose_actor(side, candidates):
            """이번 차례에 내보낼 장수를 고른다. 자동이면 무력이 가장 높은 카드."""
            player = players_by_side[side]
            answer = await ask(
                player, side,
                {"type": "await_actor",
                 "candidates": [{**card_snapshot(c), "side": side, "pos": idx} for idx, c in candidates]},
                "행동할 장수 선택을 기다리는 중...",
            )
            for idx, c in candidates:
                if idx == answer:
                    return idx, c
            return max(candidates, key=lambda t: t[1].war_stat)

        async def choose_action(side, card):
            """MP가 다 찼을 때 스킬을 쓸지 아껴둘지. 자동이면 그냥 쓴다."""
            player = players_by_side[side]
            answer = await ask(
                player, side,
                {"type": "await_action",
                 "actor": {**card_snapshot(card), "side": side, "pos": decks_by_side[side].index(card)},
                 "skill_name": card.skill_name,
                 "skill_effect_type": card.skill_effect_type,
                 "skill_effect_text": skill_summary(card.skill_effect_type, card.skill_scope,
                                                    card.skill_stat, card.skill_potency)},
                f"{card.name}의 행동 선택을 기다리는 중...",
                actor_name=card.name,
            )
            return "attack" if answer == "attack" else "skill"

        async def choose_target(side, actor, targets):
            player = players_by_side[side]
            enemy_side = "B" if side == "A" else "A"
            answer = await ask(
                player, side,
                {"type": "await_target",
                 "actor": actor.name,
                 "targets": [{**card_snapshot(c), "side": enemy_side, "pos": idx} for idx, c in targets]},
                f"{actor.name}의 대상 선택을 기다리는 중...",
                actor_name=actor.name,
            )
            for idx, c in targets:
                if idx == answer:
                    return idx, c
            return _ai_pick_target(targets)

        stage_name = None
        if room.scenario is not None:
            battle_meta = BATTLES_BY_KEY[room.scenario["battle_key"]]
            stage_name = f"{battle_meta['name']} Lv{room.scenario['level']}"

        result = await run_team_battle(
            deck_a, deck_b, emit, choose_target,
            names={"A": p1.nickname, "B": stage_name or p2.nickname},
            choose_actor=choose_actor,
            choose_action=choose_action,
            side_mods=side_mods,
        )
        winner_nickname = p1.nickname if result["winner"] == "A" else p2.nickname

        extra: dict = {}
        conn = get_connection()
        try:
            if room.scenario is not None:
                # 시나리오는 사람 쪽만 정산한다 (해금·최초 클리어 보너스 포함)
                outcome = scenario.settle(
                    conn, p1.player_id, room.scenario["battle_key"],
                    room.scenario["level"], room.scenario["deck_mode"],
                    won=result["winner"] == "A",
                )
                p1_reward, p2_reward = outcome["rings"], 0
                extra = {
                    "scenario": {
                        **room.scenario, "stage_name": stage_name,
                        "battle_name": battle_meta["name"], **outcome,
                    }
                }
            else:
                p1_reward = BATTLE_WIN_REWARD if result["winner"] == "A" else BATTLE_LOSE_REWARD
                p2_reward = BATTLE_WIN_REWARD if result["winner"] == "B" else BATTLE_LOSE_REWARD
                conn.execute("UPDATE players SET rings = rings + ? WHERE id = ?",
                             (p1_reward, p1.player_id))
                conn.execute("UPDATE players SET rings = rings + ? WHERE id = ?",
                             (p2_reward, p2.player_id))
                conn.commit()
        finally:
            conn.close()

        await _broadcast(room, {
            "type": "battle_result",
            "player_a": p1.nickname,
            "player_b": stage_name or p2.nickname,
            "winner_nickname": winner_nickname,
            "rings_earned": {"A": p1_reward, "B": p2_reward},
            **extra,
            **result,
        })

        for p in room.players.values():
            p.deck = None
            p.lineup = None
            p.ready = False

        if room.scenario is not None:
            # 다음 스테이지는 프론트가 다시 골라서 /rooms/{code}/scenario 를 부른다
            room.scenario = None
            await _broadcast(room, _lobby_payload(room))
        elif room.is_solo:
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
                # 전투 도중에 위임으로 바꿨다면 지금 기다리고 있는 질문도 바로 풀어준다.
                # (그러지 않으면 이번 턴은 여전히 20초 타임아웃을 기다린다)
                future = player.pending_target
                if player.auto_target and future is not None and not future.done():
                    future.set_result(None)
                await _broadcast(room, _lobby_payload(room))

            elif msg_type in ("choose_target", "choose_actor"):
                future = player.pending_target
                if future is not None and not future.done():
                    future.set_result(data.get("pos"))

            elif msg_type == "choose_action":
                future = player.pending_target
                if future is not None and not future.done():
                    future.set_result(data.get("action"))

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
