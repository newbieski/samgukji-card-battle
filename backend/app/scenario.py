"""시나리오 진행도 조회/기록과 스테이지 덱 구성.

시나리오 덱은 플레이어의 보유 카드(player_cards)를 거치지 않고 general_cards에서
곧바로 BattleCard를 만든다. 고정덱은 물론이고 적 덱도 "누가 무슨 등급으로 나오는지"가
시나리오 데이터에 박혀 있기 때문이다.
"""

from battle import build_battle_card
from scenario_data import (
    BATTLES_BY_KEY, MAX_LEVEL, SCENARIO_BATTLES, SCENARIO_LOSE_RING,
    build_enemy_lineup, build_fixed_lineup, clear_reward, stage_enemy_mods,
)

DECK_MODES = ("own", "fixed")

_CARD_SQL = (
    "SELECT gc.*, g.name, g.skill_name, g.skill_description, "
    "g.skill_effect_type, g.skill_scope, g.skill_stat "
    "FROM general_cards gc JOIN generals g ON g.id = gc.general_id "
    "WHERE g.name = ? AND gc.rarity = ?"
)


def load_lineup(conn, lineup: list[tuple[str, str]]) -> list:
    """[(장수 이름, 등급)] -> [BattleCard]. 보유 카드와 무관하게 만든다."""
    cards = []
    for name, rarity in lineup:
        row = conn.execute(_CARD_SQL, (name, rarity)).fetchone()
        if row is None:
            raise LookupError(f"시나리오 카드 없음: {name} {rarity}등급")
        cards.append(build_battle_card(row, 0))
    return cards


def cleared_modes(conn, player_id: int) -> dict[tuple[str, int], set[str]]:
    """{(전투 key, 레벨): {깬 덱 모드들}}"""
    result: dict[tuple[str, int], set[str]] = {}
    for row in conn.execute(
        "SELECT battle_key, level, deck_mode FROM scenario_progress WHERE player_id = ?",
        (player_id,),
    ):
        result.setdefault((row["battle_key"], row["level"]), set()).add(row["deck_mode"])
    return result


def unlocked_level(cleared: dict, battle_key: str) -> int:
    """이 전투에서 도전할 수 있는 최고 레벨. Lv1은 언제나 열려 있다.

    해금은 덱 모드를 가리지 않는다 - 고정덱으로 깨도 다음 레벨이 열린다.
    """
    level = 1
    while level < MAX_LEVEL and cleared.get((battle_key, level)):
        level += 1
    return level


def is_playable(cleared: dict, battle_key: str, level: int) -> bool:
    return 1 <= level <= MAX_LEVEL and level <= unlocked_level(cleared, battle_key)


def battle_list(conn, player_id: int) -> list[dict]:
    """전투 목록 화면에 필요한 것 전부: 소개, 레벨별 해금/클리어 상태, 보상."""
    cleared = cleared_modes(conn, player_id)
    battles = []
    for b in SCENARIO_BATTLES:
        top = unlocked_level(cleared, b["key"])
        levels = []
        for lv in range(1, MAX_LEVEL + 1):
            done = cleared.get((b["key"], lv), set())
            levels.append({
                "level": lv,
                "unlocked": lv <= top,
                "cleared": bool(done),
                "cleared_modes": sorted(done),
                "rewards": {
                    mode: {
                        "clear": clear_reward(lv, mode == "fixed", first_clear=False),
                        "first_clear": clear_reward(lv, mode == "fixed", first_clear=True),
                        "already_cleared": mode in done,
                    }
                    for mode in DECK_MODES
                },
            })
        battles.append({
            "key": b["key"], "name": b["name"], "year": b["year"],
            "scene": b["scene"], "intro": b["intro"],
            "unlocked_level": top,
            "cleared_count": sum(1 for lv in levels if lv["cleared"]),
            "levels": levels,
        })
    return battles


def stage_detail(conn, player_id: int, battle_key: str, level: int) -> dict:
    """스테이지 하나의 상세: 적 진용과 고정덱을 미리 보여준다."""
    battle = BATTLES_BY_KEY[battle_key]
    cleared = cleared_modes(conn, player_id)
    done = cleared.get((battle_key, level), set())

    def preview(lineup):
        return [
            {**dict(conn.execute(
                "SELECT gc.rarity, gc.hp, gc.mp, gc.atk, gc.leadership, g.name, g.faction, "
                "g.skill_name, g.skill_effect_type "
                "FROM general_cards gc JOIN generals g ON g.id = gc.general_id "
                "WHERE g.name = ? AND gc.rarity = ?", (name, rarity)).fetchone())}
            for name, rarity in lineup
        ]

    return {
        "battle_key": battle_key, "name": battle["name"], "level": level,
        "intro": battle["intro"], "scene": battle["scene"],
        "playable": is_playable(cleared, battle_key, level),
        "cleared_modes": sorted(done),
        "enemy": preview(build_enemy_lineup(battle, level)),
        "fixed_deck": preview(build_fixed_lineup(battle, level)),
        "enemy_mods": stage_enemy_mods(battle_key, level),
        "rewards": {
            mode: {
                "clear": clear_reward(level, mode == "fixed", first_clear=False),
                "first_clear": clear_reward(level, mode == "fixed", first_clear=True),
                "already_cleared": mode in done,
            }
            for mode in DECK_MODES
        },
        "lose_reward": SCENARIO_LOSE_RING,
    }


def settle(conn, player_id: int, battle_key: str, level: int,
           deck_mode: str, won: bool) -> dict:
    """전투 결과를 반영하고 지급할 링을 정한다. 링 적립까지 여기서 한다."""
    if deck_mode not in DECK_MODES:
        raise ValueError(f"알 수 없는 덱 모드: {deck_mode}")

    if not won:
        conn.execute("UPDATE players SET rings = rings + ? WHERE id = ?",
                     (SCENARIO_LOSE_RING, player_id))
        conn.commit()
        return {"rings": SCENARIO_LOSE_RING, "first_clear": False, "cleared": False}

    # INSERT가 실제로 들어갔으면 이 덱 모드로는 처음 깬 것이다
    cur = conn.execute(
        "INSERT OR IGNORE INTO scenario_progress (player_id, battle_key, level, deck_mode) "
        "VALUES (?, ?, ?, ?)", (player_id, battle_key, level, deck_mode))
    first_clear = cur.rowcount > 0

    rings = clear_reward(level, deck_mode == "fixed", first_clear)
    conn.execute("UPDATE players SET rings = rings + ? WHERE id = ?", (rings, player_id))
    conn.commit()
    return {"rings": rings, "first_clear": first_clear, "cleared": True}
