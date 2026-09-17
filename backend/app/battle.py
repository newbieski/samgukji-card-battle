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

전투 결과는 문자열 로그가 아니라 구조화된 이벤트 목록(events)으로 반환한다.
프론트엔드가 이 이벤트를 한 번에 하나씩 재생하며(사용자 입력으로 다음 진행)
HP바/공격 연출을 그릴 수 있도록 하기 위함이다. 각 이벤트는 표시용 한국어
문장(text)도 함께 담고 있어, 별도 문구 조합 로직 없이도 바로 로그로 쓸 수 있다.
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


def _card_snapshot(card: BattleCard) -> dict:
    return {
        "name": card.name,
        "rarity": card.rarity,
        "hp": max(card.hp, 0),
        "max_hp": card.max_hp,
    }


def _apply_skill(attacker: BattleCard, defender: BattleCard, attacker_side: str,
                  own_side: SideState, enemy_side: SideState, events: list) -> None:
    effect = attacker.skill_effect_type
    scope = attacker.skill_scope
    stat = attacker.skill_stat
    potency = attacker.skill_potency / 100
    defender_side = "B" if attacker_side == "A" else "A"

    if effect == "damage":
        multiplier = 1 + potency
        if scope == "enemy_team":
            multiplier *= ENEMY_TEAM_DAMAGE_BONUS
        atk_val = attacker.effective_atk * own_side.atk_mult * multiplier
        def_val = defender.effective_def * enemy_side.def_mult
        dmg = _calc_damage(atk_val, def_val)
        defender.hp -= dmg
        events.append({
            "kind": "skill_damage",
            "actor_side": attacker_side, "actor": attacker.name, "skill_name": attacker.skill_name,
            "target_side": defender_side, "target": defender.name, "amount": dmg,
            "target_hp": max(defender.hp, 0), "target_max_hp": defender.max_hp,
            "text": f"{attacker.name}의 '{attacker.skill_name}'! {defender.name}에게 {dmg}의 피해.",
        })

    elif effect == "heal":
        if stat == "mp":
            heal_mp = round(attacker.max_mp * potency)
            attacker.mp = min(attacker.max_mp, attacker.mp + heal_mp)
            events.append({
                "kind": "skill_heal_mp",
                "actor_side": attacker_side, "actor": attacker.name, "skill_name": attacker.skill_name,
                "amount": heal_mp,
                "text": f"{attacker.name}의 '{attacker.skill_name}'! MP {heal_mp} 회복.",
            })
        else:
            heal_hp = round(attacker.max_hp * potency)
            attacker.hp = min(attacker.max_hp, attacker.hp + heal_hp)
            events.append({
                "kind": "skill_heal",
                "actor_side": attacker_side, "actor": attacker.name, "skill_name": attacker.skill_name,
                "amount": heal_hp, "actor_hp": attacker.hp, "actor_max_hp": attacker.max_hp,
                "text": f"{attacker.name}의 '{attacker.skill_name}'! HP {heal_hp} 회복.",
            })

    elif effect == "buff":
        is_team = scope == "team"
        if is_team:
            if stat == "atk":
                own_side.atk_mult *= (1 + potency)
            else:
                own_side.def_mult *= (1 + potency)
        else:
            if stat == "atk":
                attacker.atk_mult *= (1 + potency)
            else:
                attacker.def_mult *= (1 + potency)
        events.append({
            "kind": "skill_buff",
            "actor_side": attacker_side, "actor": attacker.name, "skill_name": attacker.skill_name,
            "team_wide": is_team, "stat": stat,
            "text": f"{attacker.name}의 '{attacker.skill_name}'! " + ("아군 전체 강화." if is_team else "자신 강화."),
        })

    elif effect == "debuff":
        is_team = scope == "enemy_team"
        if is_team:
            if stat == "atk":
                enemy_side.atk_mult *= (1 - potency)
            elif stat == "def":
                enemy_side.def_mult *= (1 - potency)
            else:
                defender.acc_mult *= (1 - potency)
        else:
            if stat == "atk":
                defender.atk_mult *= (1 - potency)
            elif stat == "def":
                defender.def_mult *= (1 - potency)
            else:
                defender.acc_mult *= (1 - potency)
        events.append({
            "kind": "skill_debuff",
            "actor_side": attacker_side, "actor": attacker.name, "skill_name": attacker.skill_name,
            "target_side": defender_side, "target": defender.name, "team_wide": is_team, "stat": stat,
            "text": f"{attacker.name}의 '{attacker.skill_name}'! " + ("적 전체 약화." if is_team else f"{defender.name} 약화."),
        })


def resolve_duel(card_a: BattleCard, card_b: BattleCard,
                  side_a: SideState, side_b: SideState, events: list) -> None:
    events.append({
        "kind": "duel_start",
        "a": _card_snapshot(card_a),
        "b": _card_snapshot(card_b),
        "text": f"--- {card_a.name}({card_a.hp}hp) vs {card_b.name}({card_b.hp}hp) ---",
    })

    if card_a.war_stat >= card_b.war_stat:
        attacker, defender = card_a, card_b
        atk_side, def_side = side_a, side_b
        attacker_label = "A"
    else:
        attacker, defender = card_b, card_a
        atk_side, def_side = side_b, side_a
        attacker_label = "B"

    for _ in range(MAX_TURNS_PER_DUEL):
        defender_label = "B" if attacker_label == "A" else "A"

        if attacker.mp >= attacker.max_mp:
            _apply_skill(attacker, defender, attacker_label, atk_side, def_side, events)
            attacker.mp = 0
        else:
            hit_chance = min(0.99, BASE_HIT_CHANCE * attacker.acc_mult)
            if random.random() < hit_chance:
                atk_val = attacker.effective_atk * atk_side.atk_mult
                def_val = defender.effective_def * def_side.def_mult
                dmg = _calc_damage(atk_val, def_val)
                defender.hp -= dmg
                events.append({
                    "kind": "attack",
                    "actor_side": attacker_label, "actor": attacker.name,
                    "target_side": defender_label, "target": defender.name, "amount": dmg,
                    "target_hp": max(defender.hp, 0), "target_max_hp": defender.max_hp,
                    "text": f"{attacker.name}의 공격! {defender.name}에게 {dmg}의 피해. (HP {max(defender.hp, 0)}/{defender.max_hp})",
                })
            else:
                events.append({
                    "kind": "miss",
                    "actor_side": attacker_label, "actor": attacker.name,
                    "target_side": defender_label, "target": defender.name,
                    "text": f"{attacker.name}의 공격이 빗나갔다.",
                })
            attacker.mp = min(attacker.max_mp, attacker.mp + attacker.mp_gain_per_attack)

        if defender.hp <= 0:
            events.append({
                "kind": "faint",
                "side": defender_label, "name": defender.name,
                "text": f"{defender.name} 쓰러짐!",
            })
            break

        attacker, defender = defender, attacker
        atk_side, def_side = def_side, atk_side
        attacker_label = defender_label
    else:
        if card_a.hp / card_a.max_hp < card_b.hp / card_b.max_hp:
            card_a.hp = 0
            loser_side, loser_name = "A", card_a.name
        else:
            card_b.hp = 0
            loser_side, loser_name = "B", card_b.name
        events.append({
            "kind": "faint",
            "side": loser_side, "name": loser_name,
            "text": f"제한 턴 도달 - 체력 비율이 낮은 {loser_name} 패배 처리.",
        })


def simulate_deck_battle(deck_a: list[BattleCard], deck_b: list[BattleCard]) -> dict:
    side_a, side_b = SideState(), SideState()
    events: list[dict] = []
    ia, ib = 0, 0

    while ia < len(deck_a) and ib < len(deck_b):
        card_a, card_b = deck_a[ia], deck_b[ib]
        resolve_duel(card_a, card_b, side_a, side_b, events)
        if card_a.hp <= 0:
            ia += 1
        if card_b.hp <= 0:
            ib += 1

    winner = "A" if ib >= len(deck_b) else "B"
    events.append({
        "kind": "battle_end",
        "winner_side": winner,
        "text": "전투 종료.",
    })

    return {
        "winner": winner,
        "remaining_a": len(deck_a) - ia,
        "remaining_b": len(deck_b) - ib,
        "events": events,
    }
