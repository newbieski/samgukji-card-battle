from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from db import get_connection, init_db
from gacha import GACHA_COST, perform_draw


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="삼국지 카드 배틀 - Gacha API", lifespan=lifespan)


class CreatePlayerRequest(BaseModel):
    nickname: str


@app.post("/players")
def create_player(req: CreatePlayerRequest):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO players (nickname) VALUES (?)", (req.nickname,))
    conn.commit()
    player_id = cur.lastrowid
    row = conn.execute("SELECT id, nickname, rings FROM players WHERE id = ?", (player_id,)).fetchone()
    conn.close()
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
        "g.name, gc.rarity, gc.hp, gc.mp, gc.atk "
        "FROM player_cards pc "
        "JOIN general_cards gc ON gc.id = pc.general_card_id "
        "JOIN generals g ON g.id = gc.general_id "
        "WHERE pc.player_id = ? "
        "ORDER BY pc.obtained_at DESC",
        (player_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
