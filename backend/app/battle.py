"""
라운드제 5:5 팀 전투 엔진.

규칙 요약 (기획 확정 사항):
- 덱은 5장. 양쪽 덱 전체가 전장에 동시에 나와 있다 (죽을 때까지 계속 참여).
- 라운드마다: 그 순간 살아있는 카드를 전부 모아 무력(war_stat) 내림차순으로 행동 순서를
  정하고, 그 순서대로 한 카드씩 딱 한 번의 행동(기본 공격 또는 스킬)을 한다.
- 기본 공격/단일 대상 스킬은 대상을 골라야 한다. 실제 사람 대상이면 choose_target
  콜백이 호출되고(웹소켓으로 물어봄), AI 위임 상태면 그 콜백 내부에서 알아서 고른다 -
  이 파일은 "누가 사람이고 누가 AI인지"를 모른다.
- 기본 공격을 할 때마다 MP가 차오르고, MP가 가득 차면 그 턴엔 기본 공격 대신
  고유 스킬이 자동으로 발동한다 (게이지 타입, 기존과 동일).
- 방어력 스탯은 별도로 두지 않고 통솔력(leadership)을 방어력으로 사용한다.
- 고유 스킬은 9가지 효과로 단순화되어 있다:
    damage/heal/buff/debuff (기존) +
    extra_turn(자기 턴을 한 번 더) / stun(최대 3턴 무력화) /
    swap(적 카드와 진영 위치 교체) / mp_drain(적 MP 감소) /
    plague(적 하나를 감염시켜 매 라운드 피해 + 같은 편으로 전염)
  (자세한 배경은 seed_data.py 상단 주석 참고)

수치(피해 공식, MP 충전량, 명중률, 역병 확산 확률 등)는 모두 placeholder이며 이 파일
상단의 상수만 조정하면 전체 밸런스를 다시 맞출 수 있다.

전투는 이벤트를 하나씩 만들 때마다 emit(event) 콜백으로 즉시 흘려보낸다 (실시간 진행).
과거처럼 한 번에 다 계산해서 통째로 돌려주고 클라이언트가 재생하는 방식이 아니다.
"""

import random
from dataclasses import dataclass, field

ENHANCE_STEP = 0.05          # 강화 1레벨당 스탯 +5%
MP_FILL_ATTACKS = 3          # 기본 공격 약 3회면 MP가 가득 참
BASE_HIT_CHANCE = 0.95
DEF_DAMAGE_FACTOR = 0.35     # 피해 = atk - def * DEF_DAMAGE_FACTOR
ENEMY_TEAM_DAMAGE_BONUS = 1.2  # '전체 공격' 스킬은 단일 대상보다 더 강하게 처리
MAX_ROUNDS = 30

PLAGUE_DURATION = 3           # 역병 지속 라운드
PLAGUE_SPREAD_CHANCE = 0.5    # 매 라운드 감염자가 같은 편 미감염 카드에게 옮길 확률

# 라운드 제한에 걸리면 각 진영 대표 한 명씩 뽑아 일기토(데스매치)로 승부를 낸다.
DEATHMATCH_MAX_EXCHANGES = 40  # 안전장치 (아래 가중치 때문에 실제로는 훨씬 빨리 끝난다)
DEATHMATCH_ESCALATION = 0.12   # 합을 주고받을 때마다 피해가 이만큼씩 세진다 - 반드시 끝나도록


@dataclass
class BattleCard:
    name: str
    rarity: str
    skill_name: str
    skill_effect_type: str   # damage | heal | buff | debuff | extra_turn | stun | swap | mp_drain | plague
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
    stun_turns: int = field(default=0, init=False)
    plague_turns: int = field(default=0, init=False)
    plague_dmg: int = field(default=0, init=False)

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


def skill_summary(effect_type: str, scope: str, stat: str | None, potency: int) -> str:
    """스킬이 무슨 일을 하는지 한 줄로 요약한다 (배너/카드 표시용)."""
    target = {
        "enemy": "적 하나",
        "enemy_team": "적 전체",
        "self": "자신",
        "team": "아군 전체",
    }.get(scope, scope)
    stat_label = {"atk": "공격력", "def": "방어력", "acc": "명중률", "hp": "HP", "mp": "MP"}.get(stat, "")

    if effect_type == "damage":
        return f"{target}에게 피해 +{potency}%"
    if effect_type == "heal":
        return f"{target} {stat_label or 'HP'} {potency}% 회복"
    if effect_type == "buff":
        return f"{target} {stat_label or '능력치'} {potency}% 상승"
    if effect_type == "debuff":
        return f"{target} {stat_label or '능력치'} {potency}% 하락"
    if effect_type == "extra_turn":
        return "곧바로 한 번 더 행동"
    if effect_type == "stun":
        return f"{target} {_stun_duration(potency)}턴 무력화"
    if effect_type == "swap":
        return f"{target}와 진영 위치 교체"
    if effect_type == "mp_drain":
        return f"{target} MP {potency}% 흡수"
    if effect_type == "plague":
        return f"{target} 감염 - 매 라운드 피해, 옆으로 전염"
    return effect_type


def card_snapshot(card: BattleCard) -> dict:
    return {
        "name": card.name,
        "rarity": card.rarity,
        "hp": max(card.hp, 0),
        "max_hp": card.max_hp,
        "mp": card.mp,
        "max_mp": card.max_mp,
        "atk": card.atk,
        "skill_name": card.skill_name,
        "skill_effect_type": card.skill_effect_type,
        "skill_effect_text": skill_summary(
            card.skill_effect_type, card.skill_scope, card.skill_stat, card.skill_potency
        ),
        "stunned": card.stun_turns > 0,
        "infected": card.plague_turns > 0,
    }


def _deck_snapshot(deck: list[BattleCard]) -> list[dict]:
    return [card_snapshot(c) for c in deck]


def _alive_with_index(deck: list[BattleCard]) -> list[tuple[int, BattleCard]]:
    return [(i, c) for i, c in enumerate(deck) if c.hp > 0]


def _stun_duration(potency_pct: int) -> int:
    """등급이 오를수록 1 -> 2 -> 3턴. (스킬 위력표 E15/D22/C30/B40/A55/S75 기준)"""
    if potency_pct >= 55:
        return 3
    if potency_pct >= 30:
        return 2
    return 1


def _build_turn_order(deck_a: list[BattleCard], deck_b: list[BattleCard]) -> list[tuple[str, BattleCard]]:
    """양 진영이 한 명씩 번갈아 행동하도록 순서를 짠다.

    진영 안에서는 무력이 높은 카드가 먼저 나서고, 선공은 가장 빠른 카드를 가진
    쪽이 가져간다. 한쪽 인원이 더 많으면 남는 카드는 뒤에 이어서 행동한다.
    (스킬로 얻는 추가 행동만 이 번갈아 규칙의 예외다.)
    """
    queue_a = [("A", c) for _, c in _alive_with_index(deck_a)]
    queue_b = [("B", c) for _, c in _alive_with_index(deck_b)]
    queue_a.sort(key=lambda t: t[1].war_stat, reverse=True)
    queue_b.sort(key=lambda t: t[1].war_stat, reverse=True)

    a_lead = queue_a[0][1].war_stat if queue_a else -1
    b_lead = queue_b[0][1].war_stat if queue_b else -1
    first, second = (queue_a, queue_b) if a_lead >= b_lead else (queue_b, queue_a)

    order = []
    for i in range(max(len(first), len(second))):
        if i < len(first):
            order.append(first[i])
        if i < len(second):
            order.append(second[i])
    return order


async def _pick_target(side: str, actor: BattleCard, targets: list[tuple[int, BattleCard]], choose_target):
    """targets가 하나뿐이면 그냥 그걸 쓰고, 여럿이면 choose_target 콜백에 물어본다."""
    if len(targets) == 1:
        return targets[0]
    return await choose_target(side, actor, targets)


async def _basic_attack(side: str, attacker: BattleCard, decks: dict, sides: dict, emit, choose_target) -> None:
    enemy_side = "B" if side == "A" else "A"
    actor_pos = decks[side].index(attacker)
    targets = _alive_with_index(decks[enemy_side])
    if not targets:
        return
    t_idx, defender = await _pick_target(side, attacker, targets, choose_target)

    hit_chance = min(0.99, BASE_HIT_CHANCE * attacker.acc_mult)
    if random.random() < hit_chance:
        atk_val = attacker.effective_atk * sides[side].atk_mult
        def_val = defender.effective_def * sides[enemy_side].def_mult
        dmg = _calc_damage(atk_val, def_val)
        defender.hp -= dmg
        await emit({
            "kind": "attack",
            "actor_side": side, "actor_pos": actor_pos, "actor": attacker.name,
            "target_side": enemy_side, "target_pos": t_idx, "target": defender.name, "amount": dmg,
            "target_hp": max(defender.hp, 0), "target_max_hp": defender.max_hp,
            "text": f"{attacker.name}의 공격! {defender.name}에게 {dmg}의 피해. (HP {max(defender.hp, 0)}/{defender.max_hp})",
        })
        if defender.hp <= 0:
            await emit({
                "kind": "faint", "side": enemy_side, "pos": t_idx, "name": defender.name,
                "text": f"{defender.name} 쓰러짐!",
            })
    else:
        await emit({
            "kind": "miss",
            "actor_side": side, "actor_pos": actor_pos, "actor": attacker.name,
            "target_side": enemy_side, "target_pos": t_idx, "target": defender.name,
            "text": f"{attacker.name}의 공격이 빗나갔다.",
        })
    attacker.mp = min(attacker.max_mp, attacker.mp + attacker.mp_gain_per_attack)


async def _use_skill(side: str, attacker: BattleCard, decks: dict, sides: dict, emit, choose_target) -> None:
    effect = attacker.skill_effect_type
    scope = attacker.skill_scope
    stat = attacker.skill_stat
    potency = attacker.skill_potency / 100
    enemy_side = "B" if side == "A" else "A"
    own_side, enemy_side_state = sides[side], sides[enemy_side]
    actor_pos = decks[side].index(attacker)

    effect_text = skill_summary(effect, scope, stat, attacker.skill_potency)
    await emit({
        "kind": "skill_cast",
        "actor_side": side, "actor_pos": actor_pos, "actor": attacker.name,
        "skill_name": attacker.skill_name,
        "skill_effect_type": effect,
        "skill_effect_text": effect_text,
        "text": f"{attacker.name}의 '{attacker.skill_name}' - {effect_text}",
    })

    if effect == "damage":
        multiplier = 1 + potency
        if scope == "enemy_team":
            multiplier *= ENEMY_TEAM_DAMAGE_BONUS
            for t_idx, defender in _alive_with_index(decks[enemy_side]):
                atk_val = attacker.effective_atk * own_side.atk_mult * multiplier
                def_val = defender.effective_def * enemy_side_state.def_mult
                dmg = _calc_damage(atk_val, def_val)
                defender.hp -= dmg
                await emit({
                    "kind": "skill_damage",
                    "actor_side": side, "actor_pos": actor_pos, "actor": attacker.name,
                    "skill_name": attacker.skill_name,
                    "target_side": enemy_side, "target_pos": t_idx, "target": defender.name, "amount": dmg,
                    "target_hp": max(defender.hp, 0), "target_max_hp": defender.max_hp,
                    "text": f"{defender.name}에게 {dmg}의 피해.",
                })
                if defender.hp <= 0:
                    await emit({"kind": "faint", "side": enemy_side, "pos": t_idx, "name": defender.name,
                                "text": f"{defender.name} 쓰러짐!"})
        else:
            targets = _alive_with_index(decks[enemy_side])
            if not targets:
                return
            t_idx, defender = await _pick_target(side, attacker, targets, choose_target)
            atk_val = attacker.effective_atk * own_side.atk_mult * multiplier
            def_val = defender.effective_def * enemy_side_state.def_mult
            dmg = _calc_damage(atk_val, def_val)
            defender.hp -= dmg
            await emit({
                "kind": "skill_damage",
                "actor_side": side, "actor_pos": actor_pos, "actor": attacker.name,
                "skill_name": attacker.skill_name,
                "target_side": enemy_side, "target_pos": t_idx, "target": defender.name, "amount": dmg,
                "target_hp": max(defender.hp, 0), "target_max_hp": defender.max_hp,
                "text": f"{defender.name}에게 {dmg}의 피해.",
            })
            if defender.hp <= 0:
                await emit({"kind": "faint", "side": enemy_side, "pos": t_idx, "name": defender.name,
                            "text": f"{defender.name} 쓰러짐!"})

    elif effect == "heal":
        targets = [(actor_pos, attacker)] if scope == "self" else _alive_with_index(decks[side])
        for t_idx, target in targets:
            if stat == "mp":
                amount = round(target.max_mp * potency)
                target.mp = min(target.max_mp, target.mp + amount)
                await emit({"kind": "skill_heal_mp", "actor_side": side, "actor_pos": actor_pos, "actor": attacker.name,
                            "target_side": side, "target_pos": t_idx, "target": target.name, "amount": amount,
                            "target_mp": target.mp, "target_max_mp": target.max_mp,
                            "text": f"{target.name} MP {amount} 회복."})
            else:
                amount = round(target.max_hp * potency)
                target.hp = min(target.max_hp, target.hp + amount)
                await emit({"kind": "skill_heal", "actor_side": side, "actor_pos": actor_pos, "actor": attacker.name,
                            "target_side": side, "target_pos": t_idx, "target": target.name, "amount": amount,
                            "target_hp": target.hp, "target_max_hp": target.max_hp,
                            "text": f"{target.name} HP {amount} 회복."})

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
        await emit({"kind": "skill_buff", "actor_side": side, "actor_pos": actor_pos, "actor": attacker.name,
                    "team_wide": is_team, "stat": stat,
                    "text": "아군 전체 강화." if is_team else "자신 강화."})

    elif effect == "debuff":
        is_team = scope == "enemy_team"
        if is_team:
            if stat == "atk":
                enemy_side_state.atk_mult *= (1 - potency)
            elif stat == "def":
                enemy_side_state.def_mult *= (1 - potency)
            else:
                for _, c in _alive_with_index(decks[enemy_side]):
                    c.acc_mult *= (1 - potency)
            await emit({"kind": "skill_debuff", "actor_side": side, "actor_pos": actor_pos, "actor": attacker.name,
                        "team_wide": True, "stat": stat, "text": "적 전체 약화."})
        else:
            targets = _alive_with_index(decks[enemy_side])
            if not targets:
                return
            t_idx, defender = await _pick_target(side, attacker, targets, choose_target)
            if stat == "atk":
                defender.atk_mult *= (1 - potency)
            elif stat == "def":
                defender.def_mult *= (1 - potency)
            else:
                defender.acc_mult *= (1 - potency)
            await emit({"kind": "skill_debuff", "actor_side": side, "actor_pos": actor_pos, "actor": attacker.name,
                        "target_side": enemy_side, "target_pos": t_idx, "target": defender.name,
                        "team_wide": False, "stat": stat, "text": f"{defender.name} 약화."})

    elif effect == "extra_turn":
        await emit({"kind": "extra_turn", "actor_side": side, "actor_pos": actor_pos, "actor": attacker.name,
                    "text": f"{attacker.name}, 한 번 더 움직인다!"})
        if _alive_with_index(decks[enemy_side]):
            await _basic_attack(side, attacker, decks, sides, emit, choose_target)

    elif effect == "stun":
        targets = _alive_with_index(decks[enemy_side])
        if not targets:
            return
        t_idx, defender = await _pick_target(side, attacker, targets, choose_target)
        duration = _stun_duration(attacker.skill_potency)
        defender.stun_turns = max(defender.stun_turns, duration)
        await emit({"kind": "stun", "actor_side": side, "actor_pos": actor_pos, "actor": attacker.name,
                    "target_side": enemy_side, "target_pos": t_idx, "target": defender.name,
                    "duration": duration,
                    "text": f"{defender.name}이(가) {duration}턴 동안 무력화됐다."})

    elif effect == "swap":
        targets = _alive_with_index(decks[enemy_side])
        if not targets:
            return
        t_idx, defender = await _pick_target(side, attacker, targets, choose_target)
        decks[side][actor_pos], decks[enemy_side][t_idx] = decks[enemy_side][t_idx], decks[side][actor_pos]
        await emit({"kind": "swap", "actor_side": side, "actor": attacker.name, "actor_pos": actor_pos,
                    "target_side": enemy_side, "target_pos": t_idx, "target": defender.name,
                    "text": f"{attacker.name}와(과) {defender.name}의 진영 위치가 뒤바뀌었다!"})

    elif effect == "mp_drain":
        targets = _alive_with_index(decks[enemy_side])
        if not targets:
            return
        t_idx, defender = await _pick_target(side, attacker, targets, choose_target)
        drained = round(defender.max_mp * potency)
        defender.mp = max(0, defender.mp - drained)
        await emit({"kind": "mp_drain", "actor_side": side, "actor_pos": actor_pos, "actor": attacker.name,
                    "target_side": enemy_side, "target_pos": t_idx, "target": defender.name,
                    "amount": drained, "target_mp": defender.mp, "target_max_mp": defender.max_mp,
                    "text": f"{defender.name}의 MP를 {drained}만큼 빼앗았다."})

    elif effect == "plague":
        targets = _alive_with_index(decks[enemy_side])
        if not targets:
            return
        t_idx, defender = await _pick_target(side, attacker, targets, choose_target)
        defender.plague_turns = PLAGUE_DURATION
        defender.plague_dmg = max(1, round(defender.max_hp * potency / PLAGUE_DURATION))
        await emit({"kind": "plague_infect", "actor_side": side, "actor_pos": actor_pos, "actor": attacker.name,
                    "target_side": enemy_side, "target_pos": t_idx, "target": defender.name,
                    "text": f"{defender.name}에게 역병이 퍼지기 시작했다."})


async def _deathmatch_skill(side: str, fighter: BattleCard, foe_side: str, foe: BattleCard,
                             power: float, emit) -> None:
    """일기토에서의 스킬. 팀 단위 효과는 1:1에 맞게 단순화해서 적용한다."""
    effect = fighter.skill_effect_type
    potency = fighter.skill_potency / 100
    effect_text = skill_summary(fighter.skill_effect_type, fighter.skill_scope,
                                fighter.skill_stat, fighter.skill_potency)

    await emit({
        "kind": "deathmatch_skill",
        "side": side, "name": fighter.name, "skill_name": fighter.skill_name,
        "skill_effect_type": effect, "skill_effect_text": effect_text,
        "text": f"{fighter.name}의 '{fighter.skill_name}'!",
    })

    async def strike(multiplier: float, label: str) -> None:
        dmg = _calc_damage(fighter.effective_atk * power * multiplier, foe.effective_def)
        foe.hp -= dmg
        await emit({
            "kind": "deathmatch_attack", "is_skill": True,
            "side": side, "name": fighter.name,
            "target_side": foe_side, "target": foe.name, "amount": dmg,
            "target_hp": max(foe.hp, 0), "target_max_hp": foe.max_hp,
            "text": f"{label} {foe.name}에게 {dmg}의 피해. (HP {max(foe.hp, 0)}/{foe.max_hp})",
        })

    if effect == "damage":
        await strike(1 + potency, "필살의 일격!")
    elif effect == "heal":
        amount = round(fighter.max_hp * potency)
        fighter.hp = min(fighter.max_hp, fighter.hp + amount)
        await emit({"kind": "deathmatch_heal", "side": side, "name": fighter.name, "amount": amount,
                    "target_hp": fighter.hp, "target_max_hp": fighter.max_hp,
                    "text": f"{fighter.name}이(가) HP {amount} 회복."})
    elif effect == "buff":
        fighter.atk_mult *= (1 + potency)
        await emit({"kind": "deathmatch_buff", "side": side, "name": fighter.name,
                    "text": f"{fighter.name}의 기세가 올랐다! (공격력 상승)"})
    elif effect == "debuff":
        foe.atk_mult *= (1 - potency)
        await emit({"kind": "deathmatch_debuff", "side": foe_side, "name": foe.name,
                    "text": f"{foe.name}의 기세가 꺾였다. (공격력 하락)"})
    elif effect == "extra_turn":
        await strike(1.0, "연격!")
    elif effect == "stun":
        foe.stun_turns = max(foe.stun_turns, 1)
        await emit({"kind": "deathmatch_stun", "side": foe_side, "name": foe.name,
                    "text": f"{foe.name}이(가) 다음 합을 놓친다!"})
    elif effect == "swap":
        foe.acc_mult *= (1 - potency)
        await emit({"kind": "deathmatch_debuff", "side": foe_side, "name": foe.name,
                    "text": f"{foe.name}이(가) 교란당했다. (명중률 하락)"})
    elif effect == "mp_drain":
        foe.mp = 0
        await strike(0.5, "기력을 빼앗으며")
    elif effect == "plague":
        foe.plague_turns = PLAGUE_DURATION
        foe.plague_dmg = max(1, round(foe.max_hp * potency / PLAGUE_DURATION))
        await emit({"kind": "deathmatch_plague", "side": foe_side, "name": foe.name,
                    "text": f"{foe.name}에게 역병이 퍼졌다."})
    else:
        await strike(1 + potency, "일격!")


async def _deathmatch_turn(side: str, fighter: BattleCard, foe_side: str, foe: BattleCard,
                            power: float, emit) -> None:
    if fighter.stun_turns > 0:
        fighter.stun_turns -= 1
        await emit({"kind": "deathmatch_stunned", "side": side, "name": fighter.name,
                    "text": f"{fighter.name}은(는) 움직이지 못했다."})
        return

    if fighter.mp >= fighter.max_mp:
        fighter.mp = 0
        await _deathmatch_skill(side, fighter, foe_side, foe, power, emit)
        return

    hit_chance = min(0.99, BASE_HIT_CHANCE * fighter.acc_mult)
    if random.random() < hit_chance:
        dmg = _calc_damage(fighter.effective_atk * power, foe.effective_def)
        foe.hp -= dmg
        await emit({
            "kind": "deathmatch_attack", "is_skill": False,
            "side": side, "name": fighter.name,
            "target_side": foe_side, "target": foe.name, "amount": dmg,
            "target_hp": max(foe.hp, 0), "target_max_hp": foe.max_hp,
            "text": f"{fighter.name}의 공격! {foe.name}에게 {dmg}의 피해. (HP {max(foe.hp, 0)}/{foe.max_hp})",
        })
    else:
        await emit({"kind": "deathmatch_miss", "side": side, "name": fighter.name,
                    "target_side": foe_side, "target": foe.name,
                    "text": f"{fighter.name}의 공격이 빗나갔다."})
    fighter.mp = min(fighter.max_mp, fighter.mp + fighter.mp_gain_per_attack)


async def run_deathmatch(deck_a: list[BattleCard], deck_b: list[BattleCard], emit) -> str:
    """각 진영에서 무작위로 한 명씩 뽑아 쓰러질 때까지 1:1로 붙인다.

    새 판이므로 체력/MP/상태이상을 초기화하고 시작하며, 합을 주고받을수록
    피해가 세져서(DEATHMATCH_ESCALATION) 무한정 늘어지지 않는다.
    """
    champ_a = random.choice([c for c in deck_a if c.hp > 0])
    champ_b = random.choice([c for c in deck_b if c.hp > 0])

    for c in (champ_a, champ_b):
        c.hp = c.max_hp
        c.mp = 0
        c.stun_turns = 0
        c.plague_turns = 0
        c.atk_mult = 1.0
        c.def_mult = 1.0
        c.acc_mult = 1.0

    await emit({
        "kind": "deathmatch_start",
        "a": card_snapshot(champ_a), "b": card_snapshot(champ_b),
        "text": f"{MAX_ROUNDS}라운드 동안 승부가 나지 않았다! "
                f"{champ_a.name} vs {champ_b.name} - 일기토로 결판을 낸다!",
    })

    # 무력이 높은 쪽이 선공
    if champ_a.war_stat >= champ_b.war_stat:
        order = [("A", champ_a, "B", champ_b), ("B", champ_b, "A", champ_a)]
    else:
        order = [("B", champ_b, "A", champ_a), ("A", champ_a, "B", champ_b)]

    for exchange in range(DEATHMATCH_MAX_EXCHANGES):
        power = 1 + DEATHMATCH_ESCALATION * exchange
        if exchange > 0:
            await emit({"kind": "deathmatch_exchange", "exchange": exchange + 1,
                        "text": f"--- {exchange + 1}합 ---"})

        for side, fighter, foe_side, foe in order:
            if champ_a.hp <= 0 or champ_b.hp <= 0:
                break
            await _deathmatch_turn(side, fighter, foe_side, foe, power, emit)

        # 역병 피해는 합이 끝날 때 들어간다
        for side, fighter in (("A", champ_a), ("B", champ_b)):
            if fighter.hp > 0 and fighter.plague_turns > 0:
                fighter.plague_turns -= 1
                dmg = min(fighter.plague_dmg, fighter.hp)
                fighter.hp -= dmg
                await emit({"kind": "deathmatch_plague_tick", "side": side, "name": fighter.name,
                            "amount": dmg, "target_hp": max(fighter.hp, 0),
                            "target_max_hp": fighter.max_hp,
                            "text": f"역병으로 {fighter.name}이(가) {dmg}의 피해를 입었다."})

        if champ_a.hp <= 0 or champ_b.hp <= 0:
            break

    if champ_a.hp <= 0 and champ_b.hp <= 0:
        winner = "A" if champ_a.max_hp >= champ_b.max_hp else "B"
    elif champ_b.hp <= 0:
        winner = "A"
    elif champ_a.hp <= 0:
        winner = "B"
    else:  # 합 제한까지 갔을 때만 - 남은 체력 비율로
        winner = "A" if (champ_a.hp / champ_a.max_hp) >= (champ_b.hp / champ_b.max_hp) else "B"

    champ = champ_a if winner == "A" else champ_b
    await emit({
        "kind": "deathmatch_end", "winner_side": winner, "winner_name": champ.name,
        "text": f"일기토 승자 - {champ.name}!",
    })
    return winner


async def _tick_plague(decks: dict, emit) -> None:
    for side, deck in decks.items():
        infected = [(i, c) for i, c in enumerate(deck) if c.hp > 0 and c.plague_turns > 0]
        for i, c in infected:
            dmg = min(c.plague_dmg, c.hp)
            c.hp -= dmg
            c.plague_turns -= 1
            await emit({
                "kind": "plague_tick", "side": side, "pos": i, "name": c.name, "amount": dmg,
                "target_hp": max(c.hp, 0), "target_max_hp": c.max_hp,
                "text": f"역병으로 {c.name}이(가) {dmg}의 피해를 입었다.",
            })
            if c.hp <= 0:
                await emit({"kind": "faint", "side": side, "pos": i, "name": c.name,
                            "text": f"{c.name} 쓰러짐!"})
                continue

            candidates = [j for j, cc in enumerate(deck) if cc.hp > 0 and cc.plague_turns == 0 and j != i]
            if candidates and random.random() < PLAGUE_SPREAD_CHANCE:
                j = random.choice(candidates)
                deck[j].plague_turns = c.plague_turns if c.plague_turns > 0 else PLAGUE_DURATION
                deck[j].plague_dmg = c.plague_dmg
                await emit({
                    "kind": "plague_spread", "side": side, "from_pos": i, "from_name": c.name,
                    "to_pos": j, "to_name": deck[j].name,
                    "text": f"역병이 {c.name}에게서 {deck[j].name}(으)로 옮겨붙었다.",
                })


async def run_team_battle(deck_a: list[BattleCard], deck_b: list[BattleCard], emit, choose_target,
                           names: dict | None = None) -> dict:
    """
    emit(event: dict) -> None (awaitable): 이벤트가 생길 때마다 즉시 호출됨 (실시간 중계용).
    choose_target(side, actor, targets) -> (idx, BattleCard) (awaitable): 대상이 둘 이상일 때
      호출됨. 사람 턴이면 웹소켓으로 물어보고, AI 위임이면 알아서 골라서 반환하면 된다.
    names: {"A": 닉네임, "B": 닉네임} - 차례 표시에 쓴다.
    """
    decks = {"A": deck_a, "B": deck_b}
    sides = {"A": SideState(), "B": SideState()}
    names = names or {"A": "A팀", "B": "B팀"}

    await emit({
        "kind": "battle_start",
        "deck_a": _deck_snapshot(deck_a), "deck_b": _deck_snapshot(deck_b),
        "names": names,
        "text": "전투 시작!",
    })

    round_no = 0
    while round_no < MAX_ROUNDS and deck_a and deck_b:
        if not _alive_with_index(deck_a) or not _alive_with_index(deck_b):
            break
        round_no += 1
        queue = _build_turn_order(deck_a, deck_b)
        await emit({"kind": "round_start", "round": round_no, "text": f"--- {round_no}라운드 ---"})

        for side, card in queue:
            if card.hp <= 0:
                continue
            enemy_side = "B" if side == "A" else "A"
            if not _alive_with_index(decks[enemy_side]) or not _alive_with_index(decks[side]):
                break

            await emit({
                "kind": "turn_start",
                "side": side, "pos": decks[side].index(card), "name": card.name,
                "text": f"{names[side]}의 차례 - {card.name}",
            })

            if card.stun_turns > 0:
                card.stun_turns -= 1
                await emit({"kind": "stunned", "side": side, "pos": decks[side].index(card), "name": card.name,
                            "text": f"{card.name}은(는) 무력화 상태라 움직이지 못했다."})
                continue

            if card.mp >= card.max_mp:
                await _use_skill(side, card, decks, sides, emit, choose_target)
                card.mp = 0
            else:
                await _basic_attack(side, card, decks, sides, emit, choose_target)

        if not _alive_with_index(deck_a) or not _alive_with_index(deck_b):
            break
        await _tick_plague(decks, emit)

    alive_a, alive_b = _alive_with_index(deck_a), _alive_with_index(deck_b)
    if alive_a and not alive_b:
        winner, decision = "A", "rout"
    elif alive_b and not alive_a:
        winner, decision = "B", "rout"
    else:
        # 라운드 제한에 걸리면 판정이 아니라 대표 한 명씩 뽑아 일기토로 결판
        winner = await run_deathmatch(deck_a, deck_b, emit)
        decision = "deathmatch"

    end_text = "전투 종료." if decision == "rout" else "일기토로 승부가 갈렸다!"
    await emit({
        "kind": "battle_end",
        "winner_side": winner, "decision": decision,
        "text": end_text,
    })
    return {"winner": winner, "decision": decision}
