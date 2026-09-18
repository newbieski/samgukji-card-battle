"""
장수 시드 데이터.

삼국지연의/정사에서 널리 알려진 장수 100명 이상을 위/촉/오/군웅 세력으로 정리했다.
장수 한 명당 등급(S/A/B/C/D/E) 카드를 6장씩 전부 생성한다 - 즉 "같은 장수라도
등급에 따라 스탯이 달라진다"는 컨셉을 그대로 구현한 것으로, 여포도 손상향도
S부터 E까지 6장의 카드로 존재한다.
스탯은 'C등급 기준치 x 등급 가중치 x 유형별 배율 + 이름 기반 편차'로 자동 계산되는
placeholder이며, 실제 밸런스는 BASE_STATS / RARITY_WEIGHT / ARCHETYPES 값만 조정하면
전체적으로 다시 맞출 수 있다. 등급 가중치가 곱해지므로 S등급은 항상 더 높고 E등급은
항상 더 낮다.

스탯 순서: hp, mp, atk, int_stat(지력), war_stat(무력), leadership(통솔력), charm(매력), politics(정치력)

고유 스킬은 설명 텍스트와 별개로 전투 엔진이 실제로 해석하는 4가지 효과로 단순화했다:
  - damage: 대상에게 추가 피해 (scope=enemy는 단일, enemy_team은 다단히트로 해석)
  - heal:   자신/팀의 HP 또는 MP 회복 (stat: hp|mp)
  - buff:   자신/팀의 공격력(atk) 또는 방어력(def) 상승, 전투가 끝날 때까지 유지
  - debuff: 적 단일/적 팀 전체의 능력치 하락 (stat: atk|def|acc)
potency(%)는 등급별로 고정 (E10/D16/C22/B30/A40/S55)이며 밸런스 조정 시 이 값만 바꾸면 된다.
"""

from db import get_connection

# 유형별로 5대 기본 스탯(지력/무력/통솔력/매력/정치력)에 곱하는 배율
ARCHETYPES = {
    "무력형": {"int": 0.50, "war": 1.00, "lead": 0.70, "charm": 0.50, "pol": 0.40},
    "지력형": {"int": 1.00, "war": 0.40, "lead": 0.55, "charm": 0.50, "pol": 0.75},
    "통솔형": {"int": 0.55, "war": 0.75, "lead": 1.00, "charm": 0.60, "pol": 0.55},
    "매력형": {"int": 0.50, "war": 0.45, "lead": 0.65, "charm": 1.00, "pol": 0.60},
    "정치형": {"int": 0.70, "war": 0.35, "lead": 0.50, "charm": 0.55, "pol": 1.00},
    "만능형": {"int": 0.75, "war": 0.75, "lead": 0.75, "charm": 0.75, "pol": 0.75},
}

# 전투용 스탯(hp/mp/atk)과 5대 스탯의 공통 기준치 (C등급 = 가중치 1.0 기준값).
BASE_STATS = {"hp": 145, "mp": 65, "atk": 27, "stat": 75}

# 등급 가중치. 기준치에 이 값을 곱해서 최종 스탯을 낸다 - 숫자 하나만 조정하면
# 그 등급의 hp/mp/atk/5대 스탯이 전부 같이 움직인다. S가 최상위, E가 최하위.
RARITY_WEIGHT = {"E": 0.65, "D": 0.82, "C": 1.00, "B": 1.25, "A": 1.55, "S": 2.00}

# 등급별 고유 스킬 위력(%) 기준값
SKILL_POTENCY = {"E": 10, "D": 16, "C": 22, "B": 30, "A": 40, "S": 55}


def _variance(key: str, scale: int) -> int:
    """이름 기반 결정론적 편차값 (-scale ~ +scale)."""
    h = sum(ord(c) for c in key)
    return (h % (scale * 2 + 1)) - scale


def build_stats(name: str, rarity: str, archetype: str):
    weight = RARITY_WEIGHT[rarity]
    mult = ARCHETYPES[archetype]
    stat = BASE_STATS["stat"] * weight

    hp = round(BASE_STATS["hp"] * weight) + _variance(name + "hp", 15)
    mp = round(BASE_STATS["mp"] * weight) + _variance(name + "mp", 8)
    atk = round(BASE_STATS["atk"] * weight) + _variance(name + "atk", 4)
    int_stat = round(stat * mult["int"]) + _variance(name + "int", 5)
    war_stat = round(stat * mult["war"]) + _variance(name + "war", 5)
    leadership = round(stat * mult["lead"]) + _variance(name + "lead", 5)
    charm = round(stat * mult["charm"]) + _variance(name + "charm", 5)
    politics = round(stat * mult["pol"]) + _variance(name + "pol", 5)

    return hp, mp, atk, int_stat, war_stat, leadership, charm, politics


# (name, faction, archetype, skill_name, skill_desc,
#  skill_effect_type, skill_scope, skill_stat)
# 등급(rarity)은 여기 없다 - 장수마다 S/A/B/C/D/E 6장을 전부 만들기 때문에 seed()에서 순회한다.
GENERALS = [
    ("유비", "촉", "매력형", "인의를 저버리지 않는다", "백성과 아군을 저버리지 않는 인덕으로 아군 전체의 HP를 크게 회복시킨다.",
     "heal", "team", "hp"),
    ("손권", "오", "통솔형", "강동의 기반", "선대로부터 이어받은 강동의 기반으로 아군 전체의 방어력을 크게 높인다.",
     "buff", "team", "def"),
    ("관우", "촉", "무력형", "청룡언월참", "적 단일 대상에게 무력 기반 치명적 피해와 출혈을 입힌다.",
     "damage", "enemy", None),
    ("제갈량", "촉", "지력형", "팔진도", "아군 전체의 방어력을 크게 높이고 적 전체를 둔화시킨다.",
     "buff", "team", "def"),
    ("장비", "촉", "무력형", "장판교의 포효", "적 전체에게 공포를 부여해 공격력을 크게 낮춘다.",
     "debuff", "enemy_team", "atk"),
    ("조운", "촉", "무력형", "단기천리 필사호위", "아군 전체를 보호하며 적 단일 대상에게 연속 공격을 가한다.",
     "damage", "enemy", None),
    ("마초", "촉", "무력형", "서량철기 돌격", "적 전체를 관통 공격하며 방어력을 무시한다.",
     "damage", "enemy_team", None),
    ("여포", "군웅", "무력형", "방천화극 난무", "적 전체를 연속 공격하며 자신의 무력에 비례해 피해가 증폭된다.",
     "damage", "enemy_team", None),
    ("조조", "위", "통솔형", "패왕의 호령", "아군 전체의 공격력과 사기를 크게 높인다.",
     "buff", "team", "atk"),
    ("사마의", "위", "지력형", "인고의 계책", "자신에게 오는 피해를 감소시키고 적 전체의 속도를 늦춘다.",
     "buff", "self", "def"),
    ("손책", "오", "무력형", "소패왕의 위엄", "적 단일 대상에게 큰 피해를 입히고 적 전체를 위축시킨다.",
     "damage", "enemy", None),
    ("초선", "군웅", "매력형", "연환계", "적 전체를 이간질해 서로의 결속력을 크게 떨어뜨린다.",
     "debuff", "enemy_team", "atk"),

    ("황충", "촉", "무력형", "노장의 활", "적 단일 대상을 확정 치명타로 저격한다.",
     "damage", "enemy", None),
    ("위연", "촉", "무력형", "반골의 일격", "적 단일 대상에게 무력 비례 큰 피해를 입힌다.",
     "damage", "enemy", None),
    ("강유", "촉", "지력형", "병법전수", "아군 전체의 다음 스킬 피해를 증가시킨다.",
     "buff", "team", "atk"),
    ("관평", "촉", "무력형", "부친을 이을 용맹", "적 단일 대상을 공격하고 자신의 방어력을 높인다.",
     "damage", "enemy", None),
    ("장료", "위", "무력형", "소요진의 위명", "적 전체에게 공포를 부여해 다음 턴 행동을 늦춘다.",
     "debuff", "enemy_team", "atk"),
    ("서황", "위", "무력형", "정예부월", "적 단일 대상에게 방어 무시 피해를 입힌다.",
     "damage", "enemy", None),
    ("장합", "위", "통솔형", "노회한 용병술", "아군 전열의 방어력을 높인다.",
     "buff", "team", "def"),
    ("하후돈", "위", "무력형", "발안의 기개", "팽성 전투에서 화살에 맞아 한쪽 눈을 잃었으나 굴하지 않은 기개로, 체력이 낮을수록 공격력이 크게 증가한다.",
     "buff", "self", "atk"),
    ("허저", "위", "무력형", "호치의 힘", "적 단일 대상에게 강력한 일격을 가하고 피해의 일부를 흡수한다.",
     "damage", "enemy", None),
    ("전위", "위", "무력형", "악귀분전", "자신의 체력이 낮을수록 공격력이 크게 증가한다.",
     "buff", "self", "atk"),
    ("하후연", "위", "무력형", "신속행군 속사", "적 단일 대상을 2회 연속 공격한다.",
     "damage", "enemy", None),
    ("주유", "오", "지력형", "적벽의 화계", "적 전체에게 화상 피해를 입힌다.",
     "damage", "enemy_team", None),
    ("육손", "오", "지력형", "이릉의 화공", "적 전체에게 지속 화염 피해를 건다.",
     "damage", "enemy_team", None),
    ("여몽", "오", "통솔형", "백의도강", "적을 기습해 첫 공격의 치명타 확률을 높인다.",
     "buff", "self", "atk"),
    ("태사자", "오", "무력형", "신궁 일시", "적 후열을 저격해 방어력을 무시한다.",
     "damage", "enemy", None),
    ("감녕", "오", "무력형", "방울야습", "전투 첫 턴에 공격력이 크게 증가한다.",
     "buff", "self", "atk"),
    ("동탁", "군웅", "통솔형", "폭군의 공포", "적 전체의 사기를 저하시키고 아군 전체의 방어력을 높인다.",
     "debuff", "enemy_team", "def"),
    ("원소", "군웅", "매력형", "사세삼공의 위엄", "아군 전체의 사기를 높이고 통솔력에 비례해 방어력이 증가한다.",
     "buff", "team", "def"),
    ("손상향", "오", "무력형", "강동의 여걸", "적 단일 대상에게 연속 화살 공격을 가한다.",
     "damage", "enemy", None),

    ("마대", "촉", "무력형", "철기추격", "후퇴하는 적에게 추가 피해를 입힌다.",
     "damage", "enemy", None),
    ("관색", "촉", "무력형", "창술연화", "적 단일 대상을 연속 2회 공격한다.",
     "damage", "enemy", None),
    ("조루", "촉", "통솔형", "충절의 방패", "아군 단일 대상이 받는 피해를 대신 받는다.",
     "buff", "self", "def"),
    ("왕평", "촉", "통솔형", "엄정한 군율", "아군 전체의 방어력을 소폭 높인다.",
     "buff", "team", "def"),
    ("요화", "촉", "무력형", "노장의 집념", "체력이 낮을수록 받는 피해가 감소한다.",
     "buff", "self", "def"),
    ("장익", "촉", "통솔형", "철벽진", "자신과 인접 아군의 방어력을 높인다.",
     "buff", "team", "def"),
    ("엄안", "촉", "무력형", "노장의 기개", "쓰러지더라도 한 번 더 반격한다.",
     "buff", "self", "def"),
    ("법정", "촉", "지력형", "기책모략", "적 단일 대상의 방어력을 낮춘다.",
     "debuff", "enemy", "def"),
    ("방통", "촉", "지력형", "봉추지계", "적 전체의 명중률을 낮춘다.",
     "debuff", "enemy_team", "acc"),
    ("마량", "촉", "정치형", "백미의 지혜", "아군 전체의 회복량을 높인다.",
     "heal", "team", "hp"),
    ("이엄", "촉", "정치형", "치중보급", "아군 전체의 MP를 회복시킨다.",
     "heal", "team", "mp"),
    ("이전", "위", "지력형", "신중한 용병", "아군 단일 대상이 받는 피해를 낮춘다.",
     "buff", "self", "def"),
    ("악진", "위", "무력형", "용맹돌격", "적 단일 대상에게 돌진하여 공격한다.",
     "damage", "enemy", None),
    ("조인", "위", "통솔형", "강릉농성", "자신의 방어력을 크게 높인다.",
     "buff", "self", "def"),
    ("조홍", "위", "무력형", "종형제의 의리", "아군 단일 대상을 보호하며 공격한다.",
     "damage", "enemy", None),
    ("문빙", "위", "통솔형", "강하수비", "아군 후열을 보호한다.",
     "buff", "team", "def"),
    ("방덕", "위", "무력형", "관을 지고 나서다", "죽음을 각오하고 공격력을 크게 높인다.",
     "buff", "self", "atk"),
    ("장수", "위", "무력형", "완성야습", "전투 시작 시 기습 공격을 가한다.",
     "damage", "enemy", None),
    ("가후", "위", "지력형", "이독제독", "적 스킬의 효과 일부를 아군에게 되돌린다.",
     "debuff", "enemy", "atk"),
    ("곽회", "위", "통솔형", "옹량방어선", "아군 전체의 방어력을 소폭 높인다.",
     "buff", "team", "def"),
    ("등애", "위", "지력형", "음평 샛길", "적의 방어를 무시하고 기습 공격한다.",
     "damage", "enemy", None),
    ("종회", "위", "지력형", "검각공략", "적 단일 대상의 방어력을 크게 낮춘다.",
     "debuff", "enemy", "def"),
    ("조진", "위", "통솔형", "대사마의 위엄", "아군 전체의 사기를 높인다.",
     "buff", "team", "atk"),
    ("조휴", "위", "통솔형", "석정의 교훈", "패배 후 반격력이 증가한다.",
     "buff", "self", "atk"),
    ("사마사", "위", "지력형", "냉철한 숙청", "적 단일 대상의 지력을 낮춘다.",
     "debuff", "enemy", "atk"),
    ("사마소", "위", "지력형", "흑심야망", "자신의 공격력을 지속적으로 높인다.",
     "buff", "self", "atk"),
    ("황개", "오", "무력형", "고육계", "자신을 희생해 적 전체에게 화상 피해를 입힌다.",
     "damage", "enemy", None),
    ("정보", "오", "무력형", "원로의 돌격", "적 단일 대상에게 무력 기반 피해를 입힌다.",
     "damage", "enemy", None),
    ("한당", "오", "무력형", "충직한 수비", "아군 단일 대상을 보호한다.",
     "buff", "self", "def"),
    ("주태", "오", "무력형", "몸으로 막다", "아군을 대신해 피해를 받는다.",
     "buff", "self", "def"),
    ("정봉", "오", "무력형", "설중분투", "불리한 상황일수록 공격력이 증가한다.",
     "buff", "self", "atk"),
    ("서성", "오", "지력형", "위장성벽", "적의 다음 공격을 무효화한다.",
     "buff", "self", "def"),
    ("반장", "오", "무력형", "매복격살", "적 단일 대상을 기습해 큰 피해를 입힌다.",
     "damage", "enemy", None),
    ("능통", "오", "무력형", "용맹분전", "적 단일 대상에게 연속 공격을 가한다.",
     "damage", "enemy", None),
    ("제갈근", "오", "정치형", "온화한 사신", "적 전체의 공격력을 소폭 낮춘다.",
     "debuff", "enemy", "atk"),
    ("육항", "오", "지력형", "노련한 방어", "아군 전체의 방어력을 높이고 회복시킨다.",
     "buff", "self", "def"),
    ("대교", "오", "매력형", "강동교의 미소", "아군 전체의 사기를 북돋아 방어력을 높인다.",
     "buff", "team", "def"),
    ("소교", "오", "매력형", "거문고의 선율", "적 단일 대상의 공격 의지를 꺾어 공격력을 낮춘다.",
     "debuff", "enemy", "atk"),
    ("오국태", "오", "정치형", "국모의 위엄", "아군 전체의 방어력을 높이고 사기를 안정시킨다.",
     "buff", "team", "def"),
    ("서씨", "오", "지력형", "복수의 계책", "적 단일 대상의 방어력을 크게 낮춘다.",
     "debuff", "enemy", "def"),
    ("황월영", "촉", "지력형", "목우유마", "아군 전체의 공격력을 높인다.",
     "buff", "team", "atk"),
    ("관은병", "촉", "무력형", "부친을 닮은 청룡언월", "적 단일 대상에게 강한 일격을 가한다.",
     "damage", "enemy", None),
    ("견씨", "위", "매력형", "낙신의 아름다움", "적 전체의 명중률을 낮춘다.",
     "debuff", "enemy_team", "acc"),
    ("축융부인", "군웅", "무력형", "비도술", "적 단일 대상에게 표창을 연속으로 던져 공격한다.",
     "damage", "enemy", None),
    ("여령기", "군웅", "무력형", "쌍검무", "적 단일 대상을 연속 2회 공격한다.",
     "damage", "enemy", None),

    ("손광", "오", "만능형", "강동의 창", "적 단일 대상에게 창으로 공격한다.",
     "damage", "enemy", None),
    ("손익", "오", "만능형", "강동의 방패", "자신의 방어력을 높인다.",
     "buff", "self", "def"),
    ("진무", "오", "무력형", "돌진격", "적 단일 대상에게 돌격한다.",
     "damage", "enemy", None),
    ("동습", "오", "무력형", "수전숙련", "적 단일 대상을 공격하고 자신의 회피율을 높인다.",
     "damage", "enemy", None),
    ("반준", "오", "정치형", "후방보급", "아군 전체의 MP를 소폭 회복시킨다.",
     "heal", "team", "mp"),
    ("여범", "오", "정치형", "재무관리", "아군 전체의 방어력을 소폭 높인다.",
     "buff", "team", "def"),
    ("하제", "오", "정치형", "조정의 중신", "아군 단일 대상의 능력치를 소폭 높인다.",
     "buff", "self", "atk"),
    ("육개", "오", "정치형", "강직한 간언", "적 단일 대상의 공격력을 낮춘다.",
     "debuff", "enemy", "atk"),
    ("전종", "오", "통솔형", "수군지휘", "아군 전열의 방어력을 높인다.",
     "buff", "team", "def"),
    ("제갈각", "오", "지력형", "신동의 지략", "적 단일 대상의 지력을 낮춘다.",
     "debuff", "enemy", "atk"),
    ("유엽", "위", "지력형", "헌책", "적 단일 대상의 방어력을 낮춘다.",
     "debuff", "enemy", "def"),
    ("종예", "위", "정치형", "조정관리", "아군 전체가 정치력에 비례해 MP를 회복한다.",
     "heal", "team", "mp"),
    ("곽도", "군웅", "지력형", "원소의 모사", "적 단일 대상의 명중률을 낮춘다.",
     "debuff", "enemy", "acc"),
    ("심배", "군웅", "지력형", "업성고수", "자신의 방어력을 높인다.",
     "buff", "self", "def"),
    ("봉기", "군웅", "지력형", "기이한 계책", "적 단일 대상에게 혼란을 부여한다.",
     "debuff", "enemy", "atk"),
    ("저수", "군웅", "지력형", "충언", "아군 단일 대상의 방어력을 높인다.",
     "buff", "self", "def"),
    ("전풍", "군웅", "지력형", "직언", "적 전체의 공격력을 소폭 낮춘다.",
     "debuff", "enemy_team", "atk"),
    ("견초", "위", "무력형", "변경의 방패", "아군 전체의 방어력을 소폭 높인다.",
     "buff", "team", "def"),
    ("마준", "위", "통솔형", "농서방어", "자신의 방어력을 높인다.",
     "buff", "self", "def"),
    ("진태", "위", "통솔형", "옹주자사", "아군 전열을 보호한다.",
     "buff", "team", "def"),
    ("왕쌍", "위", "무력형", "용맹한 선봉", "적 단일 대상에게 강한 일격을 가한다.",
     "damage", "enemy", None),
    ("하후상", "위", "무력형", "명문의 자제", "적 단일 대상을 공격한다.",
     "damage", "enemy", None),
    ("하후패", "위", "무력형", "서량 망명", "적 단일 대상을 공격하고 회피율을 높인다.",
     "damage", "enemy", None),
    ("하후현", "위", "매력형", "청담의 명사", "아군 전체의 사기를 소폭 높인다.",
     "buff", "team", "atk"),
    ("조상", "위", "매력형", "권세의 그늘", "자신의 방어력을 소폭 높인다.",
     "buff", "self", "def"),
    ("장막", "군웅", "만능형", "반복무상", "적 단일 대상을 공격한다.",
     "damage", "enemy", None),
    ("안량", "군웅", "무력형", "하북의 명장", "적 단일 대상에게 강한 일격을 가한다.",
     "damage", "enemy", None),
    ("문추", "군웅", "무력형", "하북의 맹장", "적 단일 대상을 연속 공격한다.",
     "damage", "enemy", None),
    ("고람", "군웅", "무력형", "원소의 맹장", "적 단일 대상을 공격한다.",
     "damage", "enemy", None),
    ("화웅", "군웅", "무력형", "관 앞의 맹장", "적 단일 대상에게 강한 일격을 가한다.",
     "damage", "enemy", None),
    ("기령", "군웅", "무력형", "원술의 대장", "적 단일 대상을 공격한다.",
     "damage", "enemy", None),
    ("장훈", "군웅", "통솔형", "원술의 수비대장", "아군 전열의 방어력을 높인다.",
     "buff", "team", "def"),
    ("양송", "군웅", "정치형", "뇌물과 모략", "적 단일 대상의 사기를 저하시킨다.",
     "debuff", "enemy", "atk"),
    ("한수", "군웅", "통솔형", "서량의 노장", "아군 전체의 방어력을 소폭 높인다.",
     "buff", "team", "def"),
    ("공손찬", "군웅", "무력형", "백마의진", "적 전체에게 원거리 공격을 가한다.",
     "damage", "enemy_team", None),
    ("장각", "군웅", "지력형", "태평도 주술", "적 전체에게 혼란을 부여한다.",
     "debuff", "enemy_team", "atk"),
    ("장보", "군웅", "무력형", "황건의 장수", "적 단일 대상을 공격한다.",
     "damage", "enemy", None),
    ("장량", "군웅", "무력형", "황건의 장수", "적 단일 대상을 공격한다.",
     "damage", "enemy", None),
    ("관정", "군웅", "만능형", "산적출신", "적 단일 대상을 공격한다.",
     "damage", "enemy", None),
    ("요립", "촉", "정치형", "직언의 신하", "아군 단일 대상의 정치력을 소폭 높인다.",
     "buff", "self", "atk"),
    ("손노반", "오", "지력형", "이간의 혀", "적 단일 대상의 공격력을 낮춘다.",
     "debuff", "enemy", "atk"),
    ("반부인", "오", "정치형", "후궁의 총애", "자신의 방어력을 소폭 높인다.",
     "buff", "self", "def"),
    ("미씨", "촉", "매력형", "필사의 보호", "아군 단일 대상을 지키며 자신의 방어력을 높인다.",
     "buff", "self", "def"),
    ("감부인", "촉", "매력형", "인자한 보살핌", "아군 전체의 HP를 소폭 회복시킨다.",
     "heal", "team", "hp"),
    ("장황후", "촉", "정치형", "황후의 위엄", "아군 전체의 사기를 소폭 높인다.",
     "buff", "team", "atk"),
    ("채문희", "위", "지력형", "호가십팔박", "적 단일 대상의 사기를 꺾어 공격력을 낮춘다.",
     "debuff", "enemy", "atk"),
    ("곽여왕후", "위", "정치형", "황후의 책략", "적 단일 대상의 방어력을 낮춘다.",
     "debuff", "enemy", "def"),
    ("왕이", "위", "통솔형", "농성의 결의", "아군 전체의 방어력을 소폭 높인다.",
     "buff", "team", "def"),
    ("신헌영", "위", "지력형", "통찰의 예언", "적 단일 대상의 공격력을 낮춘다.",
     "debuff", "enemy", "atk"),
]


def seed() -> None:
    conn = get_connection()
    cur = conn.cursor()

    for entry in GENERALS:
        (name, faction, archetype, skill_name, skill_desc,
         effect_type, scope, stat) = entry

        cur.execute("SELECT id FROM generals WHERE name = ?", (name,))
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO generals "
                "(name, faction, skill_name, skill_description, "
                "skill_effect_type, skill_scope, skill_stat) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, faction, skill_name, skill_desc, effect_type, scope, stat),
            )
            general_id = cur.lastrowid
        else:
            general_id = row["id"]

        for rarity in RARITY_WEIGHT:
            potency = SKILL_POTENCY[rarity]
            hp, mp, atk, int_stat, war_stat, leadership, charm, politics = build_stats(
                name, rarity, archetype
            )
            cur.execute(
                "INSERT OR IGNORE INTO general_cards "
                "(general_id, rarity, hp, mp, atk, int_stat, war_stat, leadership, charm, "
                "politics, skill_potency) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (general_id, rarity, hp, mp, atk, int_stat, war_stat, leadership, charm,
                 politics, potency),
            )

    conn.commit()
    conn.close()
    print(f"{len(GENERALS)}명의 장수 x 6등급 = {len(GENERALS) * len(RARITY_WEIGHT)}장의 카드를 시드했습니다.")


if __name__ == "__main__":
    from db import init_db

    init_db()
    seed()
