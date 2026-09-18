"""
장수 로스터의 도트(픽셀) 초상화를 절차적으로 생성한다.

손으로 그린 일러스트가 아니라, 이름을 시드로 한 결정론적 규칙으로
'세력 색상 + 유형별 무기 실루엣 + 등급'을 조합해 만드는 placeholder 아트다.
같은 이름은 항상 같은 그림이 나오므로 재실행해도 결과가 바뀌지 않는다.

결과물: frontend/assets/portraits/<장수이름>.png (16x20 픽셀 그리드, 투명 배경)
카드의 등급 테두리는 이미 CSS(rarity 색상)가 담당하므로 이미지에는 넣지 않는다.
"""

import hashlib
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from seed_data import GENERALS  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "assets" / "portraits"
BLOCK = 12
GRID_W, GRID_H = 16, 20

FACTION_COLORS = {
    "위": ("#3a6ea8", "#274b73"),
    "촉": ("#3a8a4a", "#1f5c2c"),
    "오": ("#b8432f", "#7a2c1e"),
    "군웅": ("#7a5aa8", "#4e3970"),
}
HAIR_COLORS = ["#2b2b2b", "#4a2f1a", "#1a1a2e", "#3a1f1f"]
SKIN_TONES = ["#e8c39a", "#d9a97a", "#c98a5a", "#f0d0a8"]


def _pick(options, seed_key):
    h = int(hashlib.md5(seed_key.encode("utf-8")).hexdigest(), 16)
    return options[h % len(options)]


def _chance(seed_key, threshold=0.5):
    h = int(hashlib.md5(seed_key.encode("utf-8")).hexdigest(), 16)
    return (h % 100) / 100 < threshold


def _rect(grid, r0, r1, c0, c1, color):
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            grid[(r, c)] = color


def _block(grid, r, c, color):
    grid[(r, c)] = color


def _draw_weapon(grid, archetype, faction_color, faction_shadow):
    if archetype == "무력형":
        for i, r in enumerate(range(4, 15)):
            c = 13 - (i // 4)
            _block(grid, r, c, "#c9c9c9")
        _rect(grid, 13, 13, 11, 13, "#c9a227")
        _rect(grid, 14, 16, 12, 12, "#5a3a1a")
    elif archetype == "지력형":
        _rect(grid, 6, 6, 12, 14, "#e8d8b0")
        _rect(grid, 7, 11, 12, 13, "#e8d8b0")
        _rect(grid, 7, 11, 12, 12, "#c9a227")
    elif archetype == "통솔형":
        _rect(grid, 2, 17, 13, 13, "#6b4a2a")
        _rect(grid, 3, 7, 13, 15, faction_color)
        _block(grid, 3, 15, faction_shadow)
    elif archetype == "매력형":
        _rect(grid, 3, 4, 11, 12, "#f4b8c6")
        _rect(grid, 8, 12, 13, 13, "#ffffff")
        _rect(grid, 8, 12, 12, 12, "#f4b8c6")
    elif archetype == "정치형":
        _rect(grid, 7, 11, 12, 14, "#e8d8b0")
        _block(grid, 9, 13, "#8a6a4a")
    else:  # 만능형
        _rect(grid, 3, 16, 13, 13, "#6b4a2a")
        _block(grid, 2, 13, "#ffcb47")


def build_grid(name: str, faction: str, archetype: str) -> dict:
    faction_color, faction_shadow = FACTION_COLORS.get(faction, ("#7a5aa8", "#4e3970"))
    hair_color = _pick(HAIR_COLORS, name + "hair")
    skin_tone = _pick(SKIN_TONES, name + "skin")
    has_beard = archetype in ("무력형", "통솔형") and _chance(name + "beard", 0.6)

    grid: dict = {}

    # 머리
    _rect(grid, 2, 3, 5, 10, hair_color)
    _rect(grid, 4, 6, 5, 5, hair_color)
    _rect(grid, 4, 6, 10, 10, hair_color)

    # 얼굴
    _rect(grid, 4, 7, 6, 9, skin_tone)
    _block(grid, 5, 6, "#1a1a1a")
    _block(grid, 5, 9, "#1a1a1a")

    # 턱수염 또는 턱
    _rect(grid, 8, 8, 6, 9, hair_color if has_beard else skin_tone)

    # 목
    _rect(grid, 9, 9, 7, 8, skin_tone)

    # 몸통 (세력 색상 로브)
    body_rows = {
        10: (6, 9), 11: (5, 10), 12: (5, 10),
        13: (4, 11), 14: (4, 11), 15: (3, 12), 16: (3, 12),
    }
    for r, (c0, c1) in body_rows.items():
        _rect(grid, r, r, c0, c1, faction_color)
    _rect(grid, 13, 13, 4, 11, "#c9a227")  # 허리띠
    for r in (15, 16):
        _block(grid, r, 3, faction_shadow)
        _block(grid, r, 12, faction_shadow)

    # 발
    _rect(grid, 17, 17, 5, 6, "#1c1c1c")
    _rect(grid, 17, 17, 9, 10, "#1c1c1c")

    # 무기/장식 (유형별)
    _draw_weapon(grid, archetype, faction_color, faction_shadow)

    return grid


def render(grid: dict) -> Image.Image:
    img = Image.new("RGBA", (GRID_W * BLOCK, GRID_H * BLOCK), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for (r, c), color in grid.items():
        if 0 <= r < GRID_H and 0 <= c < GRID_W:
            draw.rectangle(
                [c * BLOCK, r * BLOCK, (c + 1) * BLOCK - 1, (r + 1) * BLOCK - 1],
                fill=color,
            )
    return img


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for entry in GENERALS:
        name, faction, archetype = entry[0], entry[1], entry[2]
        grid = build_grid(name, faction, archetype)
        img = render(grid)
        img.save(OUT_DIR / f"{name}.png")

    # 이미지를 찾지 못했을 때 쓸 기본 실루엣
    fallback_grid = build_grid("_fallback_", "군웅", "만능형")
    render(fallback_grid).save(OUT_DIR / "_unknown.png")

    print(f"{len(GENERALS)}개 초상화 생성 완료 -> {OUT_DIR}")


if __name__ == "__main__":
    main()
