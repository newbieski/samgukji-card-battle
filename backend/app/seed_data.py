"""
샘플 장수 시드 데이터.

초기 구조 검증용 12명 샘플이며, 실제 100명 이상 규모 데이터는
이 파일의 GENERALS 리스트에 계속 추가하면 됨.

스탯 순서: hp, mp, atk, int_stat(지력), war_stat(무력), leadership(통솔력), charm(매력), politics(정치력)
"""

from db import get_connection

# (name, faction, skill_name, skill_description, rarity, stats)
GENERALS = [
    ("관우", "촉", "청룡언월참", "적 단일 대상에게 무력 기반 큰 피해를 입히고 출혈을 부여한다.",
     "전설", (300, 140, 65, 70, 110, 95, 80, 60)),
    ("제갈량", "촉", "팔진도", "아군 전체 방어력을 증가시키고 적 전체를 둔화시킨다.",
     "전설", (260, 160, 55, 115, 40, 100, 85, 105)),

    ("여포", "군웅", "적토쌍극", "적 단일 대상을 연속 2회 공격한다.",
     "영웅", (230, 100, 50, 40, 112, 60, 75, 30)),
    ("장비", "촉", "장판교의 일갈", "적 전체에게 공포를 부여하여 공격력을 감소시킨다.",
     "영웅", (240, 90, 45, 35, 100, 70, 40, 25)),
    ("조운", "촉", "단기천리", "자신의 회피율을 증가시키고 적 단일 대상을 공격한다.",
     "영웅", (210, 100, 42, 55, 96, 75, 65, 45)),

    ("황충", "촉", "노장의 활", "적 단일 대상을 확정 치명타로 공격한다.",
     "희귀", (150, 70, 32, 45, 80, 55, 45, 40)),
    ("태사자", "오", "신궁", "적 후열을 저격하여 피해를 입힌다.",
     "희귀", (150, 70, 30, 50, 78, 58, 50, 42)),
    ("감녕", "오", "야습", "전투 첫 턴에 공격력이 크게 증가한다.",
     "희귀", (155, 65, 33, 42, 75, 50, 40, 35)),

    ("정보", "오", "돌격", "적 단일 대상에게 무력 기반 피해를 입힌다.",
     "일반", (100, 50, 20, 35, 55, 45, 35, 40)),
    ("하후연", "위", "속사", "적 단일 대상을 2회 약한 공격으로 공격한다.",
     "일반", (105, 50, 19, 30, 58, 42, 30, 30)),
    ("우금", "위", "방어태세", "자신의 방어력을 일시적으로 증가시킨다.",
     "일반", (120, 45, 16, 32, 50, 48, 30, 35)),
    ("전위", "위", "악귀분전", "자신의 체력이 낮을수록 공격력이 증가한다.",
     "일반", (110, 45, 22, 28, 60, 40, 25, 25)),
]


def seed() -> None:
    conn = get_connection()
    cur = conn.cursor()

    for name, faction, skill_name, skill_desc, rarity, stats in GENERALS:
        cur.execute(
            "SELECT id FROM generals WHERE name = ?", (name,),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO generals (name, faction, skill_name, skill_description) "
                "VALUES (?, ?, ?, ?)",
                (name, faction, skill_name, skill_desc),
            )
            general_id = cur.lastrowid
        else:
            general_id = row["id"]

        hp, mp, atk, int_stat, war_stat, leadership, charm, politics = stats
        cur.execute(
            "INSERT OR IGNORE INTO general_cards "
            "(general_id, rarity, hp, mp, atk, int_stat, war_stat, leadership, charm, politics) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (general_id, rarity, hp, mp, atk, int_stat, war_stat, leadership, charm, politics),
        )

    conn.commit()
    conn.close()
    print(f"{len(GENERALS)}명의 장수 카드를 시드했습니다.")


if __name__ == "__main__":
    from db import init_db

    init_db()
    seed()
