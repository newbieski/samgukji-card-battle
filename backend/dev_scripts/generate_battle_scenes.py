"""
전투 배경 이미지 생성 (삼국지 유명 전투 12곳).

사용법:
    python generate_battle_scenes.py            # 아직 없는 것만 생성
    python generate_battle_scenes.py --force     # 전부 다시 생성
    python generate_battle_scenes.py --only guandu
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from illustration_agent import _client, generate_scene  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "assets" / "scenes"

STYLE_SUFFIX = (
    ", 16-bit pixel art style, wide battle scene background, limited color palette, "
    "flat shading, dramatic lighting, video game background art, no text, no watermark, no UI"
)

SCENES = {
    # 아래 둘은 폭력 묘사를 넣으면 Nova Canvas 콘텐츠 필터에 걸린다.
    # 인물·무기 대신 풍경과 깃발 위주로 분위기를 낸다.
    "yellowturban": "vast dry farmland plain at dawn in ancient China, countless yellow cloth banners and "
                    "streamers planted across the fields, distant earthen village and watchtower, "
                    "golden dust haze, wind-blown wheat",
    "hulaoguan": "massive ancient Chinese stone fortress gate built into a steep rocky mountain pass at dusk, "
                 "a wide plain below covered with many colorful army banners and rows of tents, "
                 "torches glowing, deep purple and orange sky",
    "guandu": "Battle of Guandu: burning grain supply wagons at night on a dusty northern Chinese plain, "
              "two ancient armies clashing, orange fire glow against dark sky",
    "redcliffs": "Battle of Red Cliffs: burning warships chained together on a wide river at night, "
                 "massive flames reflecting on dark water, smoke filling the sky",
    "huarong": "Huarong Trail ambush: narrow muddy forest path between steep cliffs, retreating soldiers, "
               "ambushers hidden among dense trees, overcast gray sky",
    "changban": "Battle of Changban: a lone armored warrior on horseback charging through a chaotic battlefield "
                "of torn banners and fleeing refugees, thick dust clouds",
    "yiling": "Battle of Yiling: wooden military camps engulfed in spreading wildfire through a forest at night, "
              "soldiers routed in chaos, orange flames and black smoke",
    "hanzhong": "Hanzhong campaign: a mountain fortress under siege, steep cliffside walls, siege ladders, "
                "banners on ramparts, misty blue-gray mountain valley",
    "hefei": "Battle of Hefei: a small cavalry force charging into a massive sleeping army camp at dawn, "
             "distant city walls, scattered banners, pale morning light",
    "dingjun": "Battle of Mount Dingjun: an ambush on a steep autumn mountain ridge, a veteran general charging "
               "downhill with sword raised, red and orange autumn trees",
    "wuzhang": "Wuzhang Plains stalemate: two ancient armies camped facing each other across a wide autumn field, "
               "banners fluttering in the wind, dramatic orange sunset sky",
    "fancheng": "Battle of Fancheng flood: rising flood waters submerging a military camp, soldiers escaping to "
                "higher ground, warships approaching across a flooded plain, gray stormy sky",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="이 키 하나만 생성 (예: guandu)")
    parser.add_argument("--force", action="store_true", help="이미 있어도 다시 생성")
    args = parser.parse_args()

    client = _client()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    targets = {args.only: SCENES[args.only]} if args.only else SCENES
    done = 0
    for key, prompt in targets.items():
        out_path = OUT_DIR / f"battle_{key}.png"
        if out_path.exists() and not args.force:
            print(f"[{key}] 이미 있음, 건너뜀")
            continue
        print(f"[{key}] 생성 중...")
        # 배경은 화면 전체를 덮어서 도트가 크게 확대된다. 장수 초상화와 도트 크기를
        # 비슷하게 맞추려고 캐릭터보다 촘촘한 격자(240x160)로 뽑는다.
        generate_scene(
            client, prompt + STYLE_SUFFIX, out_path,
            width=1152, height=768, grid=240, grid_h=160, final=960, final_h=640,
        )
        done += 1
    print(f"완료: {done}개 생성")


if __name__ == "__main__":
    main()
