"""
방(로비) 관리.

방 코드로 만들고 초대해서 들어오는 멀티플레이 구조 (기획 확정 사항).
방 상태(플레이어 목록, 웹소켓 연결)는 서버 프로세스의 메모리에만 두고,
플레이어/카드/전투 결과 같은 영속 데이터만 SQLite에 남긴다.

방 최대 인원은 4명(추후 PvE 협동전 대비)이지만, 배틀 엔진은 아직 PvP 1:1만
지원하므로 정확히 2명이 덱을 제출했을 때만 전투가 실행된다.
"""

import random
import string
from dataclasses import dataclass, field

MAX_PLAYERS_PER_ROOM = 4


def _generate_room_code(existing: set) -> str:
    # 친구에게 말로 불러줄 때 헷갈리는 0/O, 1/I 는 제외
    alphabet = "".join(c for c in string.ascii_uppercase + string.digits if c not in "0O1I")
    while True:
        code = "".join(random.choices(alphabet, k=6))
        if code not in existing:
            return code


@dataclass
class RoomPlayer:
    player_id: int
    nickname: str
    websocket: object = None
    ready: bool = False
    deck: list | None = None
    auto_target: bool = False       # true면 대상 선택을 AI에게 위임
    pending_target: object = None   # 대상 응답을 기다리는 asyncio.Future (있을 때만)


@dataclass
class Room:
    code: str
    host_player_id: int
    title: str = "이름없는 방"
    players: dict = field(default_factory=dict)  # player_id -> RoomPlayer
    is_solo: bool = False  # true면 AI 상대가 낀 싱글 플레이 방 - 공개 목록에서 숨김

    def is_full(self) -> bool:
        return len(self.players) >= MAX_PLAYERS_PER_ROOM


class RoomManager:
    def __init__(self):
        self.rooms: dict[str, Room] = {}

    def create_room(self, host_player_id: int, host_nickname: str, title: str) -> Room:
        code = _generate_room_code(set(self.rooms.keys()))
        room = Room(code=code, host_player_id=host_player_id, title=title.strip() or "이름없는 방")
        room.players[host_player_id] = RoomPlayer(player_id=host_player_id, nickname=host_nickname)
        self.rooms[code] = room
        return room

    def get_room(self, code: str) -> Room | None:
        return self.rooms.get(code)

    def list_rooms(self) -> list[Room]:
        return list(self.rooms.values())

    def drop_room_if_empty(self, code: str) -> None:
        room = self.rooms.get(code)
        if room is not None and not room.players:
            del self.rooms[code]


manager = RoomManager()
