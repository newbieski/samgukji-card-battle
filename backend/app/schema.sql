-- 장수 원본 정보 (이름, 소속, 고유 스킬)
-- 고유 스킬은 텍스트 설명과 별개로 전투 엔진이 실제로 해석할 수 있는
-- 효과 메타데이터(skill_effect_type/scope/stat)를 함께 가진다.
-- 스킬 위력(potency)은 등급마다 달라지므로 general_cards 쪽에 둔다.
CREATE TABLE IF NOT EXISTS generals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    faction TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    skill_description TEXT NOT NULL,
    skill_effect_type TEXT NOT NULL CHECK (skill_effect_type IN (
        'damage', 'heal', 'buff', 'debuff',
        'extra_turn', 'stun', 'discord', 'mp_drain', 'plague'
    )),
    skill_scope TEXT NOT NULL CHECK (skill_scope IN ('enemy', 'enemy_team', 'self', 'team')),
    skill_stat TEXT CHECK (skill_stat IN ('atk', 'def', 'acc', 'hp', 'mp'))
);

-- 장수의 등급별 카드 (모든 장수가 S/A/B/C/D/E 6개 등급 카드를 각각 가짐)
CREATE TABLE IF NOT EXISTS general_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    general_id INTEGER NOT NULL REFERENCES generals(id),
    rarity TEXT NOT NULL CHECK (rarity IN ('S', 'A', 'B', 'C', 'D', 'E')),
    hp INTEGER NOT NULL,
    mp INTEGER NOT NULL,
    atk INTEGER NOT NULL,
    int_stat INTEGER NOT NULL,
    war_stat INTEGER NOT NULL,
    leadership INTEGER NOT NULL,
    charm INTEGER NOT NULL,
    politics INTEGER NOT NULL,
    skill_potency INTEGER NOT NULL,
    UNIQUE(general_id, rarity)
);

-- 플레이어 (비로그인, 닉네임 기반)
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nickname TEXT NOT NULL,
    rings INTEGER NOT NULL DEFAULT 1000,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_ring_purchase_at TEXT
);

-- 플레이어가 보유한 카드 (뽑기 결과, 강화 레벨 포함)
CREATE TABLE IF NOT EXISTS player_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    general_card_id INTEGER NOT NULL REFERENCES general_cards(id),
    enhance_level INTEGER NOT NULL DEFAULT 0,
    obtained_at TEXT NOT NULL DEFAULT (datetime('now'))
);
