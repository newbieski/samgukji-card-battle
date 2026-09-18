# -*- coding: utf-8 -*-
"""시나리오 60개 스테이지의 적 전투력 배수를 목표 승률에 맞춰 뽑아낸다.

등급 사다리만으로는 난이도가 통제되지 않는다. 같은 등급이라도 장수의 스탯과
스킬 궁합에 따라 고정덱 승률이 0%~100%로 튀기 때문이다. 그래서 스테이지마다
적 진영 배수를 이분 탐색으로 찾아 TARGET_WIN_RATES에 맞춘다.

결과로 출력되는 STAGE_ENEMY_POWER 사전을 app/scenario_data.py에 붙여넣으면 된다.

    python dev_scripts/calibrate_scenario.py            # 전체
    python dev_scripts/calibrate_scenario.py hefei      # 한 전투만 (확인용)
"""
import asyncio
import random
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))

import battle as B                                    # noqa: E402
from db import get_connection                         # noqa: E402
from scenario_data import (                           # noqa: E402
    SCENARIO_BATTLES, MAX_LEVEL, TARGET_WIN_RATES,
    build_enemy_lineup, build_fixed_lineup,
)

RUNS = 400              # 스테이지 한 번 평가할 때 돌리는 전투 수
SEARCH_STEPS = 12       # 이분 탐색 횟수
POWER_MIN, POWER_MAX = 0.25, 3.0

conn = get_connection()
_rows = {}


def load(name: str, rarity: str):
    key = (name, rarity)
    if key not in _rows:
        _rows[key] = conn.execute(
            "SELECT gc.*, g.name, g.skill_name, g.skill_description, "
            "g.skill_effect_type, g.skill_scope, g.skill_stat "
            "FROM general_cards gc JOIN generals g ON g.id = gc.general_id "
            "WHERE g.name = ? AND gc.rarity = ?", (name, rarity)).fetchone()
        if _rows[key] is None:
            raise SystemExit(f"카드를 찾을 수 없음: {name} {rarity}등급")
    return B.build_battle_card(_rows[key], 0)


async def _noop(_event):
    pass


async def _ai_target(_side, _actor, targets):
    """AI 위임과 같은 규칙(체력이 가장 낮은 적)으로 붙인다."""
    return min(targets, key=lambda t: t[1].hp)


async def win_rate(battle: dict, level: int, power: float) -> float:
    fixed = build_fixed_lineup(battle, level)
    enemy = build_enemy_lineup(battle, level)
    mods = {"B": {"atk": power, "def": power}}
    wins = 0
    for i in range(RUNS):
        random.seed(hash((battle["key"], level, i)) & 0xFFFFFFFF)
        result = await B.run_team_battle(
            [load(*c) for c in fixed], [load(*c) for c in enemy],
            _noop, _ai_target, side_mods=mods,
        )
        wins += result["winner"] == "A"
    return wins / RUNS


async def calibrate(battle: dict, level: int) -> tuple[float, float]:
    """목표 승률에 가장 가까운 적 배수를 이분 탐색으로 찾는다.

    배수가 커질수록 적이 강해지므로 승률은 단조 감소한다.
    """
    target = TARGET_WIN_RATES[level]
    low, high = POWER_MIN, POWER_MAX
    best = (POWER_MIN, await win_rate(battle, level, POWER_MIN))
    for _ in range(SEARCH_STEPS):
        mid = (low + high) / 2
        rate = await win_rate(battle, level, mid)
        if abs(rate - target) < abs(best[1] - target):
            best = (mid, rate)
        if rate > target:       # 너무 쉬움 -> 적을 더 강하게
            low = mid
        else:
            high = mid
    return best


async def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    battles = [b for b in SCENARIO_BATTLES if only is None or b["key"] == only]
    if not battles:
        raise SystemExit(f"그런 전투가 없습니다: {only}")

    print(f"목표 승률: " + "  ".join(
        f"Lv{lv} {TARGET_WIN_RATES[lv]*100:.0f}%" for lv in range(1, MAX_LEVEL + 1)))
    print(f"스테이지당 {RUNS}전 x 탐색 {SEARCH_STEPS}회\n")
    header = "".join(f"{'Lv'+str(lv):>14}" for lv in range(1, MAX_LEVEL + 1))
    print(f"{'전투':<12}{header}")
    print("-" * (12 + 14 * MAX_LEVEL))

    table = {}
    for b in battles:
        cells, powers = [], []
        for lv in range(1, MAX_LEVEL + 1):
            power, rate = await calibrate(b, lv)
            powers.append(round(power, 3))
            flag = " " if abs(rate - TARGET_WIN_RATES[lv]) <= 0.06 else "!"
            cells.append(f"{power:7.2f}({rate*100:3.0f}%){flag}")
        table[b["key"]] = powers
        print(f"{b['name']:<12}" + "".join(cells))

    print("\n! = 목표 승률에서 6%p 넘게 벗어난 스테이지 (배수 한계에 걸린 경우)")
    print("\n--- app/scenario_data.py 의 STAGE_ENEMY_POWER 를 아래로 교체 ---\n")
    print("STAGE_ENEMY_POWER = {")
    for b in SCENARIO_BATTLES:
        if b["key"] in table:
            values = ", ".join(f"{v:.2f}" for v in table[b["key"]])
            print(f'    "{b["key"]}": [{values}],'.ljust(46) + f"# {b['name']}")
    print("}")


asyncio.run(main())
