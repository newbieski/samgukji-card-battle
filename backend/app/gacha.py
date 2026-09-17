"""
링(가챠) 시스템.

확률/비용은 초기 placeholder 값이며, 밸런스 조정 시 이 값들만 바꾸면 됨.
천장(페이백) 시스템은 아직 없음 - 추후 필요 시 추가.
"""

import random
import sqlite3

RARITY_RATES = {
    "일반": 0.60,
    "희귀": 0.30,
    "영웅": 0.08,
    "전설": 0.02,
}

GACHA_COST = 100


def draw_rarity() -> str:
    rarities = list(RARITY_RATES.keys())
    weights = list(RARITY_RATES.values())
    return random.choices(rarities, weights=weights, k=1)[0]


def draw_general_card(conn: sqlite3.Connection, rarity: str) -> sqlite3.Row:
    cur = conn.cursor()
    cur.execute(
        "SELECT gc.*, g.name, g.faction, g.skill_name, g.skill_description "
        "FROM general_cards gc "
        "JOIN generals g ON g.id = gc.general_id "
        "WHERE gc.rarity = ?",
        (rarity,),
    )
    candidates = cur.fetchall()
    if not candidates:
        raise ValueError(f"'{rarity}' 등급에 해당하는 카드가 없습니다. 시드 데이터를 확인하세요.")
    return random.choice(candidates)


def perform_draw(conn: sqlite3.Connection) -> sqlite3.Row:
    rarity = draw_rarity()
    return draw_general_card(conn, rarity)
