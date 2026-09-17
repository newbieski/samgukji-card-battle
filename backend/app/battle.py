"""
턴제 자동전투 엔진 (PvP 1:1 순차 대결).

규칙 요약 (기획 확정 사항):
- 덱은 5장. 1번 장수끼리 붙어 한쪽이 쓰러지면 다음 장수로 넘어간다.
- 이긴 쪽은 남은 HP를 그대로 이어서 다음 상대와 싸운다 (누적).
- 선공은 무력(war_stat)이 높은 쪽이 가져간다.
- 기본 공격을 할 때마다 MP가 차오르고, MP가 가득 차면 그 턴엔 기본 공격 대신
  고유 스킬이 자동으로 발동한다 (게이지 타입).
- 방어력 스탯은 별도로 두지 않고 통솔력(leadership)을 방어력으로 사용한다.
- 고유 스킬은 damage / heal / buff / debuff 4가지 효과로 단순화되어 있다.
  (자세한 배경은 seed_data.py 상단 주석 참고)

수치(피해 공식, MP 충전량, 명중률 등)는 모두 placeholder이며 이 파일 상단의
상수만 조정하면 전체 밸런스를 다시 맞출 수 있다.
"""

import random
from dataclasses import dataclass, field

ENHANCE_STEP = 0.05          # 강화 1레벨당 스탯 +5%
MP_FILL_ATTACKS = 3          # 기본 공격 약 3회면 MP가 가득 참
BASE_HIT_CHANCE = 0.95
DEF_DAMAGE_FACTOR = 0.5      # 피해 = atk - def * DEF_DAMAGE_FACTOR
ENEMY_TEAM_DAMAGE_BONUS = 1.2  # '전체 공격' 스킬은 단일 대상보다 더 강하게 처리
MAX_TURNS_PER_DUEL = 60


@dataclass
class BattleCard:
    name: str
    rarity: str
    skill_name: str
    skill_effect_type: str   # damage | heal | buff | debuff
    skill_scope: str         # enemy | enemy_team | self | team
    skill_stat: str | None   # atk | def | acc | hp | mp | None
    skill_potency: int
    max_hp: int
    max_mp: int
    atk: int
    war_stat: int
    def_stat: int

    hp: int = field(init=False)
    mp: int = field(default=0, init=False)
    atk_mult: float = field(default=1.0, init=False)
    def_mult: float = field(default=1.0, init=False)
    acc_mult: float = field(default=1.0, init=False)

    def __post_init__(self):
        self.hp = self.max_hp

    @property
    def mp_gain_per_attack(self) -> int:
        return max(1, round(self.max_mp / MP_FILL_ATTACKS))

    @property
    def effective_atk(self) -> float:
        return self.atk * self.atk_mult

    @property
    def effective_def(self) -> float:
        return self.def_stat * self.def_mult


@dataclass
class SideState:
    atk_mult: float = 1.0
    def_mult: float = 1.0


def build_battle_card(row, enhance_level: int = 0) -> BattleCard:
    """DB의 general_cards + generals 조인 row로부터 BattleCard 생성."""
    growth = 1 + ENHANCE_STEP * enhance_level
    return BattleCard(
        name=row["name"],
        rarity=row["rarity"],
        skill_name=row["skill_name"],
        skill_effect_type=row["skill_effect_type"],
        skill_scope=row["skill_scope"],
        skill_stat=row["skill_stat"],
        skill_potency=row["skill_potency"],
        max_hp=round(row["hp"] * growth),
        max_mp=row["mp"],
        atk=round(row["atk"] * growth),
        war_stat=row["war_stat"],
        def_stat=round(row["leadership"] * growth),
    )


def _calc_damage(effective_atk: float, effective_def: float) -> int:
    return max(1, round(effective_atk - effective_def * DEF_DAMAGE_FACTOR))


def _apply_skill(attacker: BattleCard, defender: BattleCard,
                  own_side: SideState, enemy_side: SideState, log: list) -> None:
    effect = attacker.skill_effect_type
    scope = attacker.skill_scope
    stat = attacker.skill_stat
    potency = attacker.skill_potency / 100

    if effect == "damage":
        multiplier = 1 + potency
        if scope == "enemy_team":
            multiplier *= ENEMY_TEAM_DAMAGE_BONUS
        atk_val = attacker.effective_atk * own_side.atk_mult * multiplier
        def_val = defender.effective_def * enemy_side.def_mult
        dmg = _calc_damage(atk_val, def_val)
        defender.hp -= dmg
        log.append(f"{attacker.name}의 '{attacker.skill_name}'! {defender.name}에게 {dmg}의 피해.")

    elif effect == "heal":
        if stat == "mp":
            heal_mp = round(attacker.max_mp * potency)
            attacker.mp = min(attacker.max_mp, attacker.mp + heal_mp)
            log.append(f"{attacker.name}의 '{attacker.skill_name}'! MP {heal_mp} 회복.")
        else:
            heal_hp = round(attacker.max_hp * potency)
            attacker.hp = min(attacker.max_hp, attacker.hp + heal_hp)
            log.append(f"{attacker.name}의 '{attacker.skill_name}'! HP {heal_hp} 회복.")

    elif effect == "buff":
        target_state = own_side if scope == "team" else None
        if target_state is not None:
            if stat == "atk":
                target_state.atk_mult *= (1 + potency)
            else:
                target_state.def_mult *= (1 + potency)
            log.append(f"{attacker.name}의 '{attacker.skill_name}'! 아군 전체 강화.")
        else:
            if stat == "atk":
                attacker.atk_mult *= (1 + potency)
            else:
                attacker.def_mult *= (1 + potency)
            log.append(f"{attacker.name}의 '{attacker.skill_name}'! 자신 강화.")

    elif effect == "debuff":
        target_state = enemy_side if scope == "enemy_team" else None
        if target_state is not None:
            if stat == "atk":
                target_state.atk_mult *= (1 - potency)
            elif stat == "def":
                target_state.def_mult *= (1 - potency)
            else:
                defender.acc_mult *= (1 - potency)
            log.append(f"{attacker.name}의 '{attacker.skill_name}'! 적 전체 약화.")
        else:
            if stat == "atk":
                defender.atk_mult *= (1 - potency)
            elif stat == "def":
                defender.def_mult *= (1 - potency)
            else:
                defender.acc_mult *= (1 - potency)
            log.append(f"{attacker.name}의 '{attacker.skill_name}'! {defender.name} 약화.")


def resolve_duel(card_a: BattleCard, card_b: BattleCard,
                  side_a: SideState, side_b: SideState, log: list) -> None:
    log.append(f"--- {card_a.name}({card_a.hp}hp) vs {card_b.name}({card_b.hp}hp) ---")

    if card_a.war_stat >= card_b.war_stat:
        attacker, defender = card_a, card_b
        atk_side, def_side = side_a, side_b
    else:
        attacker, defender = card_b, card_a
        atk_side, def_side = side_b, side_a

    for _ in range(MAX_TURNS_PER_DUEL):
        if attacker.mp >= attacker.max_mp:
            _apply_skill(attacker, defender, atk_side, def_side, log)
            attacker.mp = 0
        else:
            hit_chance = min(0.99, BASE_HIT_CHANCE * attacker.acc_mult)
            if random.random() < hit_chance:
                atk_val = attacker.effective_atk * atk_side.atk_mult
                def_val = defender.effective_def * def_side.def_mult
                dmg = _calc_damage(atk_val, def_val)
                defender.hp -= dmg
                log.append(f"{attacker.name}의 공격! {defender.name}에게 {dmg}의 피해. (HP {max(defender.hp,0)}/{defender.max_hp})")
            else:
                log.append(f"{attacker.name}의 공격이 빗나갔다.")
            attacker.mp = min(attacker.max_mp, attacker.mp + attacker.mp_gain_per_attack)

        if defender.hp <= 0:
            log.append(f"{defender.name} 쓰러짐!")
            break

        attacker, defender = defender, attacker
        atk_side, def_side = def_side, atk_side
    else:
        log.append("제한 턴 도달 - 무승부 처리(체력 비율이 높은 쪽 승리).")
        if card_a.hp / card_a.max_hp < card_b.hp / card_b.max_hp:
            card_a.hp = 0
        else:
            card_b.hp = 0


def simulate_deck_battle(deck_a: list[BattleCard], deck_b: list[BattleCard]) -> dict:
    side_a, side_b = SideState(), SideState()
    log: list[str] = []
    ia, ib = 0, 0

    while ia < len(deck_a) and ib < len(deck_b):
        card_a, card_b = deck_a[ia], deck_b[ib]
        resolve_duel(card_a, card_b, side_a, side_b, log)
        if card_a.hp <= 0:
            ia += 1
        if card_b.hp <= 0:
            ib += 1

    winner = "A" if ib >= len(deck_b) else "B"
    return {
        "winner": winner,
        "remaining_a": len(deck_a) - ia,
        "remaining_b": len(deck_b) - ib,
        "log": log,
    }
