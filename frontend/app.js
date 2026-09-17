const state = {
  playerId: null,
  nickname: null,
  roomCode: null,
  hostPlayerId: null,
  rings: 0,
  cards: [],
  selectedDeck: [],
  ws: null,
};

function showScreen(name) {
  document.querySelectorAll(".screen").forEach((el) => el.classList.add("hidden"));
  document.getElementById(`screen-${name}`).classList.remove("hidden");
}

function setPlayerInfoVisible(visible) {
  const el = document.getElementById("playerInfo");
  el.classList.toggle("hidden", !visible);
}

function updatePlayerInfoBar() {
  document.getElementById("playerNickname").textContent = state.nickname ?? "";
  document.getElementById("playerRings").textContent = state.rings;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `요청 실패 (${res.status})`);
  }
  return res.json();
}

async function refreshRings() {
  const player = await api(`/players/${state.playerId}`);
  state.rings = player.rings;
  updatePlayerInfoBar();
}

// ---------------------------------------------------------------------------
// 입장 화면
// ---------------------------------------------------------------------------

document.getElementById("btnCreateRoom").addEventListener("click", async () => {
  const nickname = document.getElementById("nicknameInput").value.trim();
  const errorEl = document.getElementById("entryError");
  errorEl.textContent = "";
  if (!nickname) {
    errorEl.textContent = "닉네임을 입력하세요.";
    return;
  }
  try {
    const res = await api("/rooms", { method: "POST", body: JSON.stringify({ nickname }) });
    enterRoom(res);
  } catch (e) {
    errorEl.textContent = e.message;
  }
});

document.getElementById("btnJoinRoom").addEventListener("click", async () => {
  const nickname = document.getElementById("nicknameInput").value.trim();
  const code = document.getElementById("joinCodeInput").value.trim().toUpperCase();
  const errorEl = document.getElementById("entryError");
  errorEl.textContent = "";
  if (!nickname || !code) {
    errorEl.textContent = "닉네임과 방 코드를 모두 입력하세요.";
    return;
  }
  try {
    const res = await api(`/rooms/${code}/join`, { method: "POST", body: JSON.stringify({ nickname }) });
    enterRoom(res);
  } catch (e) {
    errorEl.textContent = e.message;
  }
});

function enterRoom(res) {
  state.playerId = res.player_id;
  state.nickname = res.nickname;
  state.roomCode = res.room_code;
  setPlayerInfoVisible(true);
  updatePlayerInfoBar();
  refreshRings();
  connectWebSocket();
  document.getElementById("roomCodeLabel").textContent = state.roomCode;
  showScreen("lobby");
}

// ---------------------------------------------------------------------------
// 웹소켓 (로비 + 배틀 결과)
// ---------------------------------------------------------------------------

function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${location.host}/ws/rooms/${state.roomCode}?player_id=${state.playerId}`);

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "lobby_update") {
      renderLobby(data);
    } else if (data.type === "battle_result") {
      renderBattleResult(data);
    } else if (data.type === "error") {
      document.getElementById("lobbyStatus").textContent = data.message;
    }
  };

  ws.onclose = () => {
    document.getElementById("lobbyStatus").textContent = "연결이 끊어졌습니다. 새로고침 후 다시 접속해주세요.";
  };

  state.ws = ws;
}

function renderLobby(data) {
  state.hostPlayerId = data.host_player_id;
  const list = document.getElementById("playerList");
  list.innerHTML = "";

  data.players.forEach((p) => {
    const li = document.createElement("li");
    let tags = "";
    if (p.player_id === data.host_player_id) tags += `<span class="tag tag-host">방장</span>`;
    if (p.ready) tags += `<span class="tag tag-ready">준비완료</span>`;
    if (p.deck_submitted) tags += `<span class="tag tag-deck">덱 제출됨</span>`;
    li.innerHTML = `<span>${p.nickname}${p.player_id === state.playerId ? " (나)" : ""}</span><span>${tags}</span>`;
    list.appendChild(li);
  });

  document.getElementById("lobbyStatus").textContent =
    data.players.length < 2 ? "다른 플레이어를 기다리는 중..." : "2명이 덱을 제출하면 전투가 시작됩니다.";
}

document.getElementById("btnToggleReady").addEventListener("click", () => {
  state.ws?.send(JSON.stringify({ type: "ready" }));
});

document.getElementById("btnGoGacha").addEventListener("click", () => {
  showScreen("gacha");
});

document.getElementById("btnGachaBack").addEventListener("click", () => {
  refreshRings();
  showScreen("lobby");
});

document.getElementById("btnGoCollection").addEventListener("click", async () => {
  await loadCollection();
  showScreen("collection");
});

document.getElementById("btnCollectionBack").addEventListener("click", () => {
  showScreen("lobby");
});

// ---------------------------------------------------------------------------
// 가챠 화면
// ---------------------------------------------------------------------------

const RARITY_ORDER = { 일반: 0, 희귀: 1, 영웅: 2, 전설: 3 };

document.getElementById("btnDraw").addEventListener("click", async () => {
  const errorEl = document.getElementById("entryError");
  try {
    const result = await api(`/gacha/draw?player_id=${state.playerId}`, { method: "POST" });
    state.rings = result.remaining_rings;
    updatePlayerInfoBar();
    renderDrawResult(result);
  } catch (e) {
    alert(e.message);
  }
});

function renderDrawResult(result) {
  const box = document.getElementById("drawResult");
  const card = document.getElementById("drawCard");
  card.className = `card rarity-${result.rarity}`;
  card.innerHTML = `
    <div class="card-name">${result.general_name}</div>
    <div class="card-rarity">${result.faction} · ${result.rarity}</div>
    <div class="card-skill"><strong>${result.skill_name}</strong><br>${result.skill_description}</div>
    <div class="card-stats">
      <span>HP ${result.stats.hp}</span><span>MP ${result.stats.mp}</span>
      <span>공격 ${result.stats.atk}</span><span>지력 ${result.stats.int}</span>
      <span>무력 ${result.stats.war}</span><span>통솔 ${result.stats.leadership}</span>
      <span>매력 ${result.stats.charm}</span><span>정치 ${result.stats.politics}</span>
    </div>
  `;
  box.classList.remove("hidden");
}

// ---------------------------------------------------------------------------
// 카드 보관함 / 덱 편성 화면
// ---------------------------------------------------------------------------

async function loadCollection() {
  state.cards = await api(`/players/${state.playerId}/cards`);
  state.selectedDeck = [];
  renderCardGrid();
}

function renderCardGrid() {
  const grid = document.getElementById("cardGrid");
  grid.innerHTML = "";

  const sorted = [...state.cards].sort(
    (a, b) => RARITY_ORDER[b.rarity] - RARITY_ORDER[a.rarity]
  );

  sorted.forEach((card) => {
    const tile = document.createElement("div");
    const selected = state.selectedDeck.includes(card.player_card_id);
    tile.className = `card-tile rarity-${card.rarity}${selected ? " selected" : ""}`;
    tile.innerHTML = `
      <div class="name">${card.name}</div>
      <div>${card.faction} · ${card.rarity}</div>
      <div>${card.skill_name}</div>
      <div>HP${card.hp} / MP${card.mp} / ATK${card.atk}</div>
      <div>강화 +${card.enhance_level}</div>
    `;
    tile.dataset.playerCardId = card.player_card_id;
    tile.addEventListener("click", () => toggleCardSelection(card.player_card_id, tile));
    grid.appendChild(tile);
  });

  updateDeckCounter();
}

function updateDeckCounter() {
  document.getElementById("deckCount").textContent = state.selectedDeck.length;
  document.getElementById("btnSubmitDeck").disabled = state.selectedDeck.length !== 5;
}

function toggleCardSelection(playerCardId, tile) {
  const idx = state.selectedDeck.indexOf(playerCardId);
  if (idx >= 0) {
    state.selectedDeck.splice(idx, 1);
    tile.classList.remove("selected");
  } else if (state.selectedDeck.length < 5) {
    state.selectedDeck.push(playerCardId);
    tile.classList.add("selected");
  }
  updateDeckCounter();
}

document.getElementById("btnSubmitDeck").addEventListener("click", () => {
  if (state.selectedDeck.length !== 5) return;
  state.ws?.send(JSON.stringify({ type: "submit_deck", deck: state.selectedDeck }));
  document.getElementById("lobbyStatus").textContent = "덱을 제출했습니다. 상대를 기다리는 중...";
  showScreen("lobby");
});

// ---------------------------------------------------------------------------
// 배틀 결과 화면
// ---------------------------------------------------------------------------

function renderBattleResult(data) {
  document.getElementById("battleTitle").textContent = `${data.player_a} vs ${data.player_b}`;

  const logEl = document.getElementById("battleLog");
  logEl.innerHTML = "";

  const winnerLine = document.createElement("span");
  winnerLine.className = "winner-line";
  winnerLine.textContent = `🏆 승자: ${data.winner_nickname}`;
  logEl.appendChild(winnerLine);

  data.log.forEach((line) => {
    const span = document.createElement("span");
    span.className = line.startsWith("---") ? "duel-line" : "event-line";
    span.textContent = line;
    logEl.appendChild(span);
  });

  showScreen("battle");
  refreshRings();
}

document.getElementById("btnBattleBack").addEventListener("click", () => {
  showScreen("lobby");
});
