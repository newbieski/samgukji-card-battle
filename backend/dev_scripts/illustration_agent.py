"""
Bedrock 기반 일러스트 생성 에이전트.

장수(및 앞으로 필요한 다른 게임 이미지)의 도트 아트를 AWS Bedrock으로 생성한다.
2단계로 동작:

  1) 텍스트 모델 여러 개를 순서대로 시도해 (쓰로틀링 시 다음 모델로 전환) 영어 이미지
     프롬프트를 만든다.
  2) 그 프롬프트로 Nova Canvas를 호출해 실제 이미지를 생성하고, 다운샘플 -> 색상 제한
     -> 최근접보간 업샘플로 후처리해 도트 느낌을 강제한다.

Nova Canvas가 계속 실패하면(쿼터 없음/쓰로틀링 등) generate_portraits.py의 절차적
렌더러로 자동 대체한다 - 항상 뭔가는 생성되도록.

사용법:
    python illustration_agent.py --only 관우          # 한 명만 테스트
    python illustration_agent.py --limit 10           # 10명만 생성 (이어하기 가능)
    python illustration_agent.py                       # 전체 장수 생성
    python illustration_agent.py --kind scene --prompt "..." --out ../../frontend/assets/scenes/x.png
"""

import argparse
import base64
import io
import json
import os
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from dotenv import load_dotenv
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from seed_data import GENERALS  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_portraits as procedural  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

# 쓰로틀링 시 이 순서대로 다음 모델을 시도한다.
TEXT_MODELS = [
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "us.amazon.nova-pro-v1:0",
    "us.amazon.nova-2-lite-v1:0",
    "global.amazon.nova-2-lite-v1:0",
    "us.amazon.nova-lite-v1:0",
]
IMAGE_MODEL = "amazon.nova-canvas-v1:0"

OUT_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "assets" / "portraits"
MANIFEST_PATH = OUT_DIR / "_manifest.json"

PROMPT_SYSTEM = (
    "You write short, vivid English prompts for a text-to-image model. "
    "The output must describe ONE character in a cute 16-bit pixel art "
    "video game style: chibi proportions, big head, flat colors, limited palette, "
    "clean black outlines, plain dark navy background, no text, no watermark. "
    "Always a FULL-BODY character, standing pose, facing forward or three-quarter view, "
    "feet visible, centered in frame, game trading-card icon composition (not a close-up "
    "face portrait). "
    "Reply with ONLY the prompt text, no preamble, under 60 words."
)


def _client():
    try:
        return boto3.client("bedrock-runtime", region_name=REGION)
    except NoCredentialsError as e:
        raise SystemExit(
            "AWS 자격증명을 찾을 수 없습니다. backend/.env 를 backend/.env.example 참고해서 "
            "채워주세요."
        ) from e


def _is_throttling(err: ClientError) -> bool:
    code = err.response.get("Error", {}).get("Code", "")
    return code in ("ThrottlingException", "TooManyRequestsException", "ServiceUnavailableException")


def _is_transient_access_error(err: ClientError) -> bool:
    """이 Bedrock 계정에서 Nova Canvas가 LEGACY로 표시되어 있어 리전 백엔드에 따라
    간헐적으로 'Access denied ... Legacy' 형태의 ResourceNotFoundException이 뜬다.
    같은 호출을 다시 시도하면 성공하는 경우가 많아 재시도 대상으로 취급한다."""
    error = err.response.get("Error", {})
    code = error.get("Code", "")
    message = error.get("Message", "")
    return code == "ResourceNotFoundException" and "legacy" in message.lower()


def craft_prompt(client, user_text: str, system_text: str = PROMPT_SYSTEM) -> str:
    """텍스트 모델을 순서대로 시도해 이미지 프롬프트를 만든다."""
    last_error = None
    for model_id in TEXT_MODELS:
        try:
            resp = client.converse(
                modelId=model_id,
                system=[{"text": system_text}],
                messages=[{"role": "user", "content": [{"text": user_text}]}],
                inferenceConfig={"maxTokens": 200, "temperature": 0.7},
            )
            return resp["output"]["message"]["content"][0]["text"].strip()
        except ClientError as e:
            last_error = e
            if _is_throttling(e):
                print(f"    [{model_id}] 쓰로틀링 -> 다음 모델")
                continue
            print(f"    [{model_id}] 오류: {e}")
            continue
    raise RuntimeError(f"모든 텍스트 모델이 실패했습니다: {last_error}")


def generate_with_nova_canvas(client, prompt: str, seed: int, retries: int = 5) -> Image.Image | None:
    body = {
        "taskType": "TEXT_IMAGE",
        "textToImageParams": {"text": prompt},
        "imageGenerationConfig": {
            "numberOfImages": 1,
            "height": 512,
            "width": 512,
            "cfgScale": 8.0,
            "seed": seed % 858993459,
        },
    }
    for attempt in range(retries):
        try:
            resp = client.invoke_model(modelId=IMAGE_MODEL, body=json.dumps(body))
            payload = json.loads(resp["body"].read())
            if "images" not in payload or not payload["images"]:
                print(f"    Nova Canvas 응답에 이미지 없음: {payload}")
                if attempt < retries - 1:
                    wait = min(1.5 * (attempt + 1), 6)
                    time.sleep(wait)
                    continue
                return None
            b64 = payload["images"][0]
            return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")
        except ClientError as e:
            retryable = _is_throttling(e) or _is_transient_access_error(e)
            if retryable and attempt < retries - 1:
                wait = min(1.5 * (attempt + 1), 6)
                reason = "쓰로틀링" if _is_throttling(e) else "일시적 Legacy 접근 오류"
                print(f"    Nova Canvas {reason}, {wait:.1f}s 후 재시도 ({attempt + 1}/{retries})")
                time.sleep(wait)
                continue
            print(f"    Nova Canvas 실패: {e}")
            return None
    return None


def pixelate(img: Image.Image, grid: int = 40, final: int = 200, colors: int = 20) -> Image.Image:
    """생성 이미지를 저해상도로 평균내 축소한 뒤(LANCZOS), 팔레트를 제한하고,
    최근접보간(NEAREST)으로 다시 확대해 블록이 살아있는 도트 느낌을 만든다."""
    small = img.convert("RGB").resize((grid, grid), Image.LANCZOS)
    small = small.quantize(colors=colors, method=Image.MEDIANCUT).convert("RGB")
    return small.resize((final, final), Image.NEAREST)


def _load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {}


def _save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_general_portrait(client, name: str, faction: str, archetype: str,
                               skill_name: str, skill_desc: str) -> str:
    """장수 한 명의 초상화를 생성해 저장하고 'ai' 또는 'procedural' 을 반환한다."""
    user_text = (
        f"Three Kingdoms general: {name} ({faction} faction). "
        f"Combat archetype: {archetype}. Signature skill '{skill_name}': {skill_desc}."
    )

    out_path = OUT_DIR / f"{name}.png"

    try:
        prompt = craft_prompt(client, user_text)
        print(f"    prompt: {prompt}")
        img = generate_with_nova_canvas(client, prompt, seed=abs(hash(name)))
        if img is not None:
            pixelate(img).save(out_path)
            return "ai"
    except Exception as e:  # noqa: BLE001 - 배치 진행이 중요, 실패해도 다음으로
        print(f"    실패, 절차적 렌더러로 대체: {e}")

    grid = procedural.build_grid(name, faction, archetype)
    procedural.render(grid).save(out_path)
    return "procedural"


def generate_scene(client, prompt: str, out_path: Path, grid: int = 64, final: int = 320) -> None:
    """장수 카드 외의 범용 이미지(배경/아이템 등) 생성용 진입점."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = generate_with_nova_canvas(client, prompt, seed=abs(hash(prompt)))
    if img is None:
        raise RuntimeError("Nova Canvas 생성 실패 (이 종류는 절차적 대체가 없습니다).")
    pixelate(img, grid=grid, final=final).save(out_path)
    print(f"저장: {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bedrock 기반 도트 일러스트 생성 에이전트")
    parser.add_argument("--only", help="이 이름의 장수 한 명만 생성")
    parser.add_argument("--limit", type=int, help="최대 N명만 생성 (이미 AI로 생성된 건 건너뜀)")
    parser.add_argument("--force", action="store_true", help="이미 생성된 것도 다시 생성")
    parser.add_argument("--kind", choices=["general", "scene"], default="general")
    parser.add_argument("--prompt", help="--kind scene 일 때 쓸 프롬프트")
    parser.add_argument("--out", help="--kind scene 일 때 저장 경로")
    args = parser.parse_args()

    client = _client()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.kind == "scene":
        if not args.prompt or not args.out:
            raise SystemExit("--kind scene 은 --prompt 와 --out 이 필요합니다.")
        generate_scene(client, args.prompt, Path(args.out))
        return

    manifest = _load_manifest()
    targets = [g for g in GENERALS if not args.only or g[0] == args.only]
    if not targets:
        raise SystemExit(f"'{args.only}' 장수를 찾을 수 없습니다.")

    done = 0
    for entry in targets:
        name, faction, rarity, archetype = entry[0], entry[1], entry[2], entry[3]
        skill_name, skill_desc = entry[4], entry[5]

        if not args.force and manifest.get(name) == "ai":
            continue
        if args.limit and done >= args.limit:
            break

        print(f"[{name}] ({faction}/{rarity}/{archetype}) 생성 중...")
        result = generate_general_portrait(client, name, faction, archetype, skill_name, skill_desc)
        manifest[name] = result
        _save_manifest(manifest)
        print(f"  -> {result}")
        done += 1

    print(f"완료: {done}명 처리 (manifest: {MANIFEST_PATH})")


if __name__ == "__main__":
    main()
