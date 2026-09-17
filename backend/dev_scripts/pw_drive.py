"""임시 브라우저 구동 스크립트 (Playwright). 프론트엔드 화면 흐름을 눈으로 확인하기 위한 용도."""

import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8031"
SHOT_DIR = "C:/Users/SDS/AppData/Local/Temp/claude/pw_shots"

import os
os.makedirs(SHOT_DIR, exist_ok=True)


def shot(page, name):
    path = f"{SHOT_DIR}/{name}.png"
    page.screenshot(path=path)
    print("screenshot ->", path)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 480, "height": 900})
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        page.goto(BASE)
        page.wait_for_selector("#screen-entry")
        shot(page, "01_entry")

        page.fill("#nicknameInput", "테스터")
        page.fill("#roomTitleInput", "테스터의 방")
        page.click("#btnCreateRoom")

        page.wait_for_selector("#screen-lobby:not(.hidden)")
        page.wait_for_function("document.querySelector('#roomCodeLabel').textContent !== '------'")
        shot(page, "02_lobby")

        page.click("#btnGoCards")
        page.wait_for_selector("#screen-cards:not(.hidden)")
        page.click("#btnDraw")
        page.wait_for_selector("#drawResult:not(.hidden)")
        shot(page, "03_gacha_result")

        page.wait_for_selector(".card-tile")
        shot(page, "04_collection_before_select")

        tiles = page.query_selector_all(".card-tile")
        print("card tile count:", len(tiles))
        for tile in tiles[:5]:
            tile.click()
        shot(page, "05_collection_selected")

        submit_btn = page.query_selector("#btnSubmitDeck")
        print("submit disabled:", submit_btn.is_disabled())

        page.click("#btnOpenShop")
        page.wait_for_selector("#shopOverlay:not(.hidden)")
        page.wait_for_selector(".shop-package-btn")
        shot(page, "06_shop")
        page.click(".shop-package-btn")
        page.wait_for_selector("#shopOverlay", state="hidden")

        print("console errors:", console_errors)
        browser.close()


if __name__ == "__main__":
    sys.exit(main())
