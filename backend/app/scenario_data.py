"""시나리오(싱글 캠페인) 데이터.

12개의 역사적 전투가 있고, 각 전투는 Lv1~Lv5로 이어진다. 난이도는 레벨이 오를수록
반드시 올라가야 하므로, 스테이지 60개의 적 덱을 손으로 다 적지 않고
"전투별 장수 풀 + 레벨별 등급 사다리"로 조합해서 만든다.

  - 적 장수 풀: 그 전투에 어울리는 장수 명단. 맨 앞이 주장이라 모든 레벨에 나온다.
  - 등급 사다리: 레벨이 오르면 등급이 E -> S 방향으로만 올라간다.
  - 적 보정: 고레벨에서는 적 진영에 공격/방어 배수를 얹는다 (핸디캡).

덱은 플레이어의 보유 덱을 쓰는 것이 기본이고, 원하면 전투마다 준비된 고정덱을
고를 수 있다. 고정덱은 카드가 없어도 무난하게 깰 수 있는 안전한 선택지이므로
보상이 더 적다 (SCENARIO_FIXED_DECK_RATIO).
"""

# (레벨별) 적 덱 5장의 등급. 앞 3개가 핵심 장수(주장 + 부장 2) 몫이라 더 높다.
LEVEL_ENEMY_RARITIES = {
    1: ["D", "D", "D", "E", "E"],
    2: ["C", "C", "C", "D", "D"],
    3: ["B", "B", "B", "C", "C"],
    4: ["A", "A", "A", "B", "B"],
    5: ["S", "S", "S", "A", "A"],
}

# 스테이지가 목표로 하는 난이도. "고정덱 + AI 위임"으로 붙었을 때의 승률이다.
# 직접 대상을 고르면 이보다 쉽게 느껴진다.
TARGET_WIN_RATES = {1: 0.85, 2: 0.78, 3: 0.70, 4: 0.62, 5: 0.55}

# (전투별 x 레벨별) 적 진영 전투력 배수.
#
# 등급 사다리만으로는 난이도를 통제할 수 없다. 등급을 똑같이 맞춰도 장수 개개인의
# 스탯·스킬 궁합 때문에 전투마다 고정덱 승률이 0%에서 100%까지 튄다 (합비전투는
# 고정덱이 구조적으로 불리해 한 판도 못 이겼고, 한중공방전은 전 레벨 100%였다).
# 그래서 이 표는 손으로 쓴 값이 아니라, 실제 전투 엔진을 돌려 TARGET_WIN_RATES에
# 맞춘 결과다. 장수 스탯이나 전투 공식을 건드리면 다시 뽑아야 한다:
#
#     python dev_scripts/calibrate_scenario.py
#
STAGE_ENEMY_POWER = {
    "yellowturban": [1.09, 1.15, 1.04, 1.04, 1.22],   # 황건적의 난
    "hulaoguan":    [0.80, 0.95, 1.11, 1.08, 0.91],   # 반동탁 연합
    "guandu":       [0.89, 0.93, 0.96, 1.00, 1.01],   # 관도대전
    "changban":     [0.93, 0.98, 1.08, 1.30, 1.66],   # 장판파
    "redcliffs":    [0.97, 1.01, 1.01, 1.04, 1.04],   # 적벽대전
    "huarong":      [1.13, 1.15, 1.22, 1.54, 1.84],   # 화용도
    "hefei":        [0.65, 0.76, 0.78, 0.79, 0.71],   # 합비전투
    "hanzhong":     [1.26, 1.28, 1.25, 1.36, 1.52],   # 한중공방전
    "dingjun":      [1.05, 1.08, 1.10, 1.13, 1.14],   # 정군산
    "fancheng":     [0.86, 0.88, 0.90, 0.94, 0.95],   # 번성전투
    "yiling":       [1.08, 1.19, 1.17, 1.13, 1.14],   # 이릉대전
    "wuzhang":      [1.56, 1.50, 1.51, 1.14, 1.44],   # 오장원
}


def stage_enemy_mods(battle_key: str, level: int) -> dict:
    """적 진영에 걸 보정. run_team_battle(side_mods=...)에 그대로 넘긴다."""
    power = STAGE_ENEMY_POWER[battle_key][level - 1]
    return {"atk": power, "def": power}

# 고정덱은 5장 모두 이 등급. 같은 레벨의 적 덱보다 조금 위라서 "안전한 선택"이 된다.
LEVEL_FIXED_DECK_RARITY = {1: "D", 2: "C", 3: "B", 4: "A", 5: "S"}

MAX_LEVEL = 5

# 보상 (링). 최초 클리어는 (전투, 레벨, 덱 모드)별로 따로 기록해서,
# 고정덱으로 먼저 깬 뒤에 내 덱으로 다시 깨도 보너스를 받을 수 있게 한다.
SCENARIO_CLEAR_RING_BASE = 40
SCENARIO_CLEAR_RING_PER_LEVEL = 20
SCENARIO_FIXED_DECK_RATIO = 0.6
SCENARIO_FIRST_CLEAR_MULTIPLIER = 2
SCENARIO_LOSE_RING = 10


# key, 이름, 연도, 배경 이미지 키, 한 줄 소개,
# 적 장수 풀(맨 앞이 주장), 고정덱 5명
SCENARIO_BATTLES = [
    {
        "key": "yellowturban",
        "name": "황건적의 난",
        "year": 184,
        "scene": "guandu",          # 전용 배경 생성 전까지 임시
        "intro": "창천은 이미 죽었고 황천이 서리라. 태평도의 깃발이 중원을 뒤덮었다.",
        "enemy_pool": ["장각", "장보", "장량", "관정", "한수", "기령", "장훈"],
        "fixed_deck": ["유비", "관우", "장비", "공손찬", "조조"],
    },
    {
        "key": "hulaoguan",
        "name": "반동탁 연합",
        "year": 190,
        "scene": "changban",        # 전용 배경 생성 전까지 임시
        "intro": "십팔로 제후가 모였으나, 호뢰관 앞에 선 것은 천하무쌍의 여포였다.",
        "enemy_pool": ["동탁", "여포", "화웅", "초선", "장수", "가후", "한수"],
        "fixed_deck": ["원소", "조조", "유비", "관우", "장비"],
    },
    {
        "key": "guandu",
        "name": "관도대전",
        "year": 200,
        "scene": "guandu",
        "intro": "십만 대군의 원소와 일만의 조조. 오소의 군량이 불타오른다.",
        "enemy_pool": ["원소", "안량", "문추", "고람", "저수", "전풍", "심배", "곽도", "봉기"],
        "fixed_deck": ["조조", "하후돈", "허저", "장료", "서황"],
    },
    {
        "key": "changban",
        "name": "장판파",
        "year": 208,
        "scene": "changban",
        "intro": "백성을 버리지 못한 행군은 느렸다. 조운이 홀로 적진을 일곱 번 드나든다.",
        "enemy_pool": ["조조", "하후돈", "조인", "조홍", "문빙", "장합", "악진", "이전"],
        "fixed_deck": ["조운", "장비", "유비", "제갈량", "감부인"],
    },
    {
        "key": "redcliffs",
        "name": "적벽대전",
        "year": 208,
        "scene": "redcliffs",
        "intro": "동남풍이 불어온다. 연환으로 묶인 조조의 함대에 불화살이 쏟아진다.",
        "enemy_pool": ["조조", "장료", "서황", "악진", "이전", "문빙", "하후돈", "조인"],
        "fixed_deck": ["주유", "제갈량", "황개", "감녕", "정보"],
    },
    {
        "key": "huarong",
        "name": "화용도",
        "year": 208,
        "scene": "huarong",
        "intro": "패주하는 조조 앞을 막아선 것은, 옛 은혜를 아는 관우였다.",
        "enemy_pool": ["조조", "장료", "허저", "서황", "장합", "조인", "조홍"],
        "fixed_deck": ["관우", "관평", "요화", "장비", "조운"],
    },
    {
        "key": "hefei",
        "name": "합비전투",
        "year": 215,
        "scene": "hefei",
        "intro": "팔백의 결사대가 십만을 흔든다. 강동의 아이들이 장료의 이름에 울음을 그쳤다.",
        "enemy_pool": ["장료", "이전", "악진", "조인", "조휴", "문빙", "하후상"],
        "fixed_deck": ["손권", "감녕", "능통", "태사자", "여몽"],
    },
    {
        "key": "hanzhong",
        "name": "한중공방전",
        "year": 219,
        "scene": "hanzhong",
        "intro": "계륵이라 하였다. 먹자니 살이 없고 버리자니 아까운 땅, 한중.",
        "enemy_pool": ["조조", "하후연", "장합", "서황", "조홍", "조진", "곽회"],
        "fixed_deck": ["유비", "법정", "황충", "조운", "마초"],
    },
    {
        "key": "dingjun",
        "name": "정군산",
        "year": 219,
        "scene": "dingjun",
        "intro": "늙었다 비웃던 자들 앞에서, 노장의 칼이 하후연의 목을 베었다.",
        "enemy_pool": ["하후연", "장합", "조진", "곽회", "조홍", "서황"],
        "fixed_deck": ["황충", "법정", "엄안", "유비", "위연"],
    },
    {
        "key": "fancheng",
        "name": "번성전투",
        "year": 219,
        "scene": "fancheng",
        "intro": "수공으로 칠군을 삼키며 위세가 화하를 떨쳤으나, 등 뒤에서 형주가 무너진다.",
        "enemy_pool": ["조인", "서황", "방덕", "여몽", "육손", "장료", "서성"],
        "fixed_deck": ["관우", "관평", "요화", "마량", "유비"],
    },
    {
        "key": "yiling",
        "name": "이릉대전",
        "year": 222,
        "scene": "yiling",
        "intro": "의형제의 원수를 갚겠다며 나선 칠백 리 영채가, 하룻밤 불길에 사라진다.",
        # 손권은 총사령이 아니라 후방에 있었으므로 핵심 3인이 아닌 뒤쪽에 둔다
        "enemy_pool": ["육손", "한당", "주태", "감녕", "정봉", "서성", "반장", "손권"],
        "fixed_deck": ["유비", "황충", "마량", "조운", "요화"],
    },
    {
        "key": "wuzhang",
        "name": "오장원",
        "year": 234,
        "scene": "wuzhang",
        "intro": "죽은 제갈량이 산 중달을 쫓는다. 별이 떨어지고 북벌은 끝났다.",
        "enemy_pool": ["사마의", "사마사", "사마소", "곽회", "등애", "진태", "종회", "하후패"],
        "fixed_deck": ["제갈량", "강유", "위연", "왕평", "마대"],
    },
]

BATTLES_BY_KEY = {b["key"]: b for b in SCENARIO_BATTLES}


CORE_ENEMY_COUNT = 3   # 풀 앞쪽 3명(주장 + 부장 2)은 모든 레벨에 나온다


def build_enemy_lineup(battle: dict, level: int) -> list[tuple[str, str]]:
    """(장수 이름, 등급) 5쌍.

    앞 3명은 그 전투의 핵심이라 항상 출전하고, 남은 2자리만 레벨마다 돌아가며
    바뀐다. 5자리를 전부 돌리면 Lv5 관도대전에 안량/문추가 빠지고 문관만 남는 식으로
    최고 난이도가 오히려 물러지는 문제가 있었다.
    """
    rarities = LEVEL_ENEMY_RARITIES[level]
    core = battle["enemy_pool"][:CORE_ENEMY_COUNT]
    rest = battle["enemy_pool"][CORE_ENEMY_COUNT:]
    fill = len(rarities) - len(core)
    start = (level - 1) % len(rest)
    picked = [rest[(start + i) % len(rest)] for i in range(fill)]
    return list(zip(core + picked, rarities))


def build_fixed_lineup(battle: dict, level: int) -> list[tuple[str, str]]:
    """고정덱 5쌍. 5장 모두 같은 등급이라 레벨만 따라 올라간다."""
    rarity = LEVEL_FIXED_DECK_RARITY[level]
    return [(name, rarity) for name in battle["fixed_deck"]]


def clear_reward(level: int, use_fixed_deck: bool, first_clear: bool) -> int:
    """클리어 보상(링). 고정덱은 감액, 최초 클리어는 배수."""
    reward = SCENARIO_CLEAR_RING_BASE + SCENARIO_CLEAR_RING_PER_LEVEL * level
    if use_fixed_deck:
        reward = round(reward * SCENARIO_FIXED_DECK_RATIO)
    if first_clear:
        reward *= SCENARIO_FIRST_CLEAR_MULTIPLIER
    return reward
