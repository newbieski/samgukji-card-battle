"""임시 브라우저 구동 스크립트: 방 생성~참가~덱 제출~배틀 결과 화면까지 2인 플로우 확인."""

import os
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8031"
SHOT_DIR = "C:/Users/SDS/AppData/Local/Temp/claude/pw_shots"
os.makedirs(SHOT_DIR, exist_ok=True)


def draw_five(page):
    page.click("#btnGoGacha")
    page.wait_for_selector("#screen-gacha:not(.hidden)")
    for _ in range(5):
        page.click("#btnDraw")
        page.wait_for_selector("#drawResult:not(.hidden)")
    page.click("#btnGachaBack")
    page.wait_for_selector("#screen-lobby:not(.hidden)")


def submit_deck(page):
    page.click("#btnGoCollection")
    page.wait_for_selector("#screen-collection:not(.hidden)")
    tiles = page.query_selector_all(".card-tile")
    for tile in tiles[:5]:
        tile.click()
    page.click("#btnSubmitDeck")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()

        page_a = browser.new_page(viewport={"width": 480, "height": 900})
        page_a.goto(BASE)
        page_a.fill("#nicknameInput", "호스트")
        page_a.fill("#roomTitleInput", "테스트 방")
        page_a.click("#btnCreateRoom")
        page_a.wait_for_function("document.querySelector('#roomCodeLabel').textContent !== '------'")
        room_code = page_a.text_content("#roomCodeLabel")
        print("room_code:", room_code)

        page_b = browser.new_page(viewport={"width": 480, "height": 900})
        page_b.goto(BASE)
        page_b.fill("#nicknameInput", "게스트")
        page_b.fill("#joinCodeInput", room_code)
        page_b.click("#btnJoinRoom")
        page_b.wait_for_selector("#screen-lobby:not(.hidden)")

        page_a.wait_for_function("document.querySelectorAll('#playerList li').length === 2")
        page_a.screenshot(path=f"{SHOT_DIR}/battle_01_lobby_two_players.png")

        draw_five(page_a)
        draw_five(page_b)

        submit_deck(page_a)
        submit_deck(page_b)

        page_a.wait_for_selector("#screen-battle:not(.hidden)", timeout=10000)
        page_b.wait_for_selector("#screen-battle:not(.hidden)", timeout=10000)

        page_a.click("#btnBattleNext")
        page_a.screenshot(path=f"{SHOT_DIR}/battle_02_first_step.png")

        page_a.click("#btnBattleSkip")
        page_a.wait_for_selector("#btnBattleBack:not(.hidden)")
        page_a.screenshot(path=f"{SHOT_DIR}/battle_03_result_host.png")

        page_b.click("#btnBattleSkip")
        page_b.wait_for_selector("#btnBattleBack:not(.hidden)")
        page_b.screenshot(path=f"{SHOT_DIR}/battle_04_result_guest.png")

        print("battle title (host view):", page_a.text_content("#battleTitle"))
        print("event text (host view):", page_a.text_content("#battleEventText"))
        browser.close()


if __name__ == "__main__":
    main()
