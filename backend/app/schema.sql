-- 장수 원본 정보 (이름, 소속, 고유 스킬)
-- 고유 스킬은 텍스트 설명과 별개로 전투 엔진이 실제로 해석할 수 있는
-- 효과 메타데이터(skill_effect_type/scope/stat/potency)를 함께 가진다.
CREATE TABLE IF NOT EXISTS generals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    faction TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    skill_description TEXT NOT NULL,
    skill_effect_type TEXT NOT NULL CHECK (skill_effect_type IN ('damage', 'heal', 'buff', 'debuff')),
    skill_scope TEXT NOT NULL CHECK (skill_scope IN ('enemy', 'enemy_team', 'self', 'team')),
    skill_stat TEXT CHECK (skill_stat IN ('atk', 'def', 'acc', 'hp', 'mp')),
    skill_potency INTEGER NOT NULL
);

-- 장수의 등급별 카드 (같은 장수라도 등급마다 스탯이 다름)
CREATE TABLE IF NOT EXISTS general_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    general_id INTEGER NOT NULL REFERENCES generals(id),
    rarity TEXT NOT NULL CHECK (rarity IN ('일반', '희귀', '영웅', '전설')),
    hp INTEGER NOT NULL,
    mp INTEGER NOT NULL,
    atk INTEGER NOT NULL,
    int_stat INTEGER NOT NULL,
    war_stat INTEGER NOT NULL,
    leadership INTEGER NOT NULL,
    charm INTEGER NOT NULL,
    politics INTEGER NOT NULL,
    UNIQUE(general_id, rarity)
);

-- 플레이어 (비로그인, 닉네임 기반)
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nickname TEXT NOT NULL,
    rings INTEGER NOT NULL DEFAULT 1000,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 플레이어가 보유한 카드 (뽑기 결과, 강화 레벨 포함)
CREATE TABLE IF NOT EXISTS player_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    general_card_id INTEGER NOT NULL REFERENCES general_cards(id),
    enhance_level INTEGER NOT NULL DEFAULT 0,
    obtained_at TEXT NOT NULL DEFAULT (datetime('now'))
);
