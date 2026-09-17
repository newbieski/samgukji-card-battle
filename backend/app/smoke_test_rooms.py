"""임시 스모크 테스트: 방 생성 -> 입장 -> 웹소켓 로비 -> 덱 제출 -> 배틀 결과."""

import asyncio
import json
import urllib.request

import websockets

BASE = "http://127.0.0.1:8010"


def post(path, body):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def get(path):
    with urllib.request.urlopen(BASE + path) as resp:
        return json.loads(resp.read())


async def main():
    host = post("/rooms", {"nickname": "host_kim"})
    print("room created:", host)
    room_code = host["room_code"]

    guest = post(f"/rooms/{room_code}/join", {"nickname": "guest_lee"})
    print("guest joined:", guest)

    for _ in range(5):
        post(f"/gacha/draw?player_id={host['player_id']}", {})
        post(f"/gacha/draw?player_id={guest['player_id']}", {})

    host_cards = [c["player_card_id"] for c in get(f"/players/{host['player_id']}/cards")]
    guest_cards = [c["player_card_id"] for c in get(f"/players/{guest['player_id']}/cards")]
    print("host deck:", host_cards)
    print("guest deck:", guest_cards)

    async with websockets.connect(f"ws://127.0.0.1:8010/ws/rooms/{room_code}?player_id={host['player_id']}") as ws_host, \
               websockets.connect(f"ws://127.0.0.1:8010/ws/rooms/{room_code}?player_id={guest['player_id']}") as ws_guest:

        print("host recv:", await ws_host.recv())
        print("guest recv:", await ws_guest.recv())

        await ws_host.send(json.dumps({"type": "submit_deck", "deck": host_cards}))
        print("host recv:", await ws_host.recv())
        print("guest recv:", await ws_guest.recv())

        await ws_guest.send(json.dumps({"type": "submit_deck", "deck": guest_cards}))

        # lobby_update (deck submitted) + battle_result 순서로 옴
        for _ in range(2):
            print("host recv:", await ws_host.recv())
        for _ in range(2):
            print("guest recv:", await ws_guest.recv())


asyncio.run(main())
