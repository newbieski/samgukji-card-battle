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
  const title = document.getElementById("roomTitleInput").value.trim();
  const errorEl = document.getElementById("entryError");
  errorEl.textContent = "";
  if (!nickname) {
    errorEl.textContent = "닉네임을 입력하세요.";
    return;
  }
  if (!title) {
    errorEl.textContent = "방 제목을 입력하세요.";
    return;
  }
  try {
    const res = await api("/rooms", { method: "POST", body: JSON.stringify({ nickname, title }) });
    enterRoom(res);
  } catch (e) {
    errorEl.textContent = e.message;
  }
});

async function joinRoomByCode(code) {
  const nickname = document.getElementById("nicknameInput").value.trim();
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
}

document.getElementById("btnJoinRoom").addEventListener("click", () => {
  const code = document.getElementById("joinCodeInput").value.trim().toUpperCase();
  joinRoomByCode(code);
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
  document.getElementById("roomTitleLabel").textContent = res.title ?? "";
  showScreen("lobby");
}

// ---------------------------------------------------------------------------
// 참가 가능한 방 목록
// ---------------------------------------------------------------------------

async function loadRoomList() {
  const listEl = document.getElementById("roomList");
  try {
    const rooms = await api("/rooms");
    listEl.innerHTML = "";
    if (rooms.length === 0) {
      listEl.innerHTML = `<li class="room-list-empty">참가 가능한 방이 없습니다.</li>`;
      return;
    }
    rooms.forEach((room) => {
      const li = document.createElement("li");
      li.className = "room-list-item";
      li.innerHTML = `
        <span class="room-list-title">${room.title}</span>
        <span class="room-list-count">(${room.player_count}/${room.max_players})</span>
      `;
      li.addEventListener("click", () => joinRoomByCode(room.room_code));
      listEl.appendChild(li);
    });
  } catch (e) {
    listEl.innerHTML = `<li class="room-list-empty">방 목록을 불러오지 못했습니다.</li>`;
  }
}

document.getElementById("btnRefreshRooms").addEventListener("click", loadRoomList);
loadRoomList();

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
  document.getElementById("roomTitleLabel").textContent = data.title ?? "";
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

document.getElementById("btnGoCards").addEventListener("click", async () => {
  await loadCollection();
  showScreen("cards");
});

document.getElementById("btnCardsBack").addEventListener("click", () => {
  showScreen("lobby");
});

// ---------------------------------------------------------------------------
// 링 구매 (임시 mock 결제)
// ---------------------------------------------------------------------------

async function openShop() {
  const box = document.getElementById("shopPackages");
  box.innerHTML = `<p class="hint">불러오는 중...</p>`;
  document.getElementById("shopOverlay").classList.remove("hidden");
  try {
    const packages = await api("/ring-packages");
    box.innerHTML = "";
    packages.forEach((pkg) => {
      const btn = document.createElement("button");
      btn.className = "btn shop-package-btn";
      btn.innerHTML = `<span>${pkg.rings}링</span><span class="shop-price">${pkg.price_label}</span>`;
      btn.addEventListener("click", () => purchaseRings(pkg.package_id));
      box.appendChild(btn);
    });
  } catch (e) {
    box.innerHTML = `<p class="error-text">상품 목록을 불러오지 못했습니다.</p>`;
  }
}

async function purchaseRings(packageId) {
  try {
    const result = await api(`/players/${state.playerId}/purchase_rings`, {
      method: "POST",
      body: JSON.stringify({ package_id: packageId }),
    });
    state.rings = result.remaining_rings;
    updatePlayerInfoBar();
    document.getElementById("shopOverlay").classList.add("hidden");
  } catch (e) {
    alert(e.message);
  }
}

document.getElementById("btnOpenShop").addEventListener("click", openShop);
document.getElementById("btnCloseShop").addEventListener("click", () => {
  document.getElementById("shopOverlay").classList.add("hidden");
});

// ---------------------------------------------------------------------------
// 뽑기
// ---------------------------------------------------------------------------

const RARITY_ORDER = { 일반: 0, 희귀: 1, 영웅: 2, 전설: 3 };

document.getElementById("btnDraw").addEventListener("click", async () => {
  try {
    const result = await api(`/gacha/draw?player_id=${state.playerId}`, { method: "POST" });
    state.rings = result.remaining_rings;
    updatePlayerInfoBar();
    renderDrawResult(result);
    await loadCollection();
  } catch (e) {
    alert(e.message);
  }
});

const FALLBACK_PORTRAIT = "assets/portraits/_unknown.png";

function portraitSrc(name) {
  return `assets/portraits/${encodeURIComponent(name)}.png`;
}

function renderDrawResult(result) {
  const box = document.getElementById("drawResult");
  const card = document.getElementById("drawCard");
  card.className = `card rarity-${result.rarity}`;
  card.innerHTML = `
    <img class="card-portrait" src="${portraitSrc(result.general_name)}" alt="${result.general_name}"
         onerror="this.onerror=null;this.src='${FALLBACK_PORTRAIT}';">
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
  const validIds = new Set(state.cards.map((c) => c.player_card_id));
  state.selectedDeck = state.selectedDeck.filter((id) => validIds.has(id));
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
      <img class="tile-portrait" src="${portraitSrc(card.name)}" alt="${card.name}"
           onerror="this.onerror=null;this.src='${FALLBACK_PORTRAIT}';">
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

document.getElementById("btnResetDeck").addEventListener("click", () => {
  state.selectedDeck = [];
  renderCardGrid();
});

// ---------------------------------------------------------------------------
// 배틀 화면 (이벤트를 한 번에 하나씩 재생)
// ---------------------------------------------------------------------------

const battle = {
  data: null,
  index: 0,
  fighters: { A: null, B: null },
};

function renderBattleResult(data) {
  document.getElementById("battleTitle").textContent = `${data.player_a} vs ${data.player_b}`;

  battle.data = data;
  battle.index = 0;
  battle.fighters = { A: null, B: null };

  document.getElementById("battleLog").innerHTML = "";
  document.getElementById("battleEventText").textContent = "전투 시작!";
  document.getElementById("btnBattleNext").classList.remove("hidden");
  document.getElementById("btnBattleSkip").classList.remove("hidden");
  document.getElementById("btnBattleBack").classList.add("hidden");

  showScreen("battle");
  refreshRings();
}

function setFighterUI(side, fighter) {
  const nameEl = document.getElementById(`fighter${side}Name`);
  const skillEl = document.getElementById(`fighter${side}Skill`);
  const portraitEl = document.getElementById(`fighter${side}Portrait`);
  const hpFillEl = document.getElementById(`fighter${side}HpFill`);
  const hpTextEl = document.getElementById(`fighter${side}HpText`);
  const mpFillEl = document.getElementById(`fighter${side}MpFill`);
  const mpTextEl = document.getElementById(`fighter${side}MpText`);
  const atkEl = document.getElementById(`fighter${side}Atk`);

  if (!fighter) {
    nameEl.textContent = "-";
    skillEl.textContent = "-";
    portraitEl.src = "";
    hpFillEl.style.width = "0%";
    hpTextEl.textContent = "-/-";
    mpFillEl.style.width = "0%";
    mpTextEl.textContent = "-/-";
    atkEl.textContent = "ATK -";
    return;
  }

  nameEl.textContent = fighter.name;
  skillEl.textContent = fighter.skill_name ? `「${fighter.skill_name}」` : "";
  portraitEl.src = portraitSrc(fighter.name);
  portraitEl.onerror = () => { portraitEl.onerror = null; portraitEl.src = FALLBACK_PORTRAIT; };

  const hpPct = Math.max(0, Math.min(100, (fighter.hp / fighter.max_hp) * 100));
  hpFillEl.style.width = `${hpPct}%`;
  hpFillEl.classList.toggle("low", hpPct <= 30);
  hpTextEl.textContent = `${Math.max(fighter.hp, 0)}/${fighter.max_hp}`;

  const mpPct = fighter.max_mp ? Math.max(0, Math.min(100, (fighter.mp / fighter.max_mp) * 100)) : 0;
  mpFillEl.style.width = `${mpPct}%`;
  mpFillEl.classList.toggle("full", mpPct >= 100);
  mpTextEl.textContent = `${Math.max(fighter.mp ?? 0, 0)}/${fighter.max_mp ?? 0}`;

  atkEl.textContent = `ATK ${fighter.atk ?? "-"}`;
}

const FLASH_CLASSES = ["flash-hit", "flash-skill-hit", "flash-heal", "flash-buff", "flash-debuff", "flash-miss"];

function flashFighter(side, kind) {
  const el = document.querySelector(`.fighter-${side.toLowerCase()}`);
  if (!el) return;
  const cls = kind === "heal" ? "flash-heal" : kind === "buff" ? "flash-buff"
    : kind === "debuff" ? "flash-debuff" : kind === "miss" ? "flash-miss"
    : kind === "skill-hit" ? "flash-skill-hit" : "flash-hit";
  el.classList.remove(...FLASH_CLASSES);
  // 강제 리플로우로 애니메이션 재시작
  void el.offsetWidth;
  el.classList.add(cls);
}

function lungeFighter(side) {
  const el = document.querySelector(`.fighter-${side.toLowerCase()}`);
  if (!el) return;
  const cls = side === "A" ? "lunge-right" : "lunge-left";
  el.classList.remove("lunge-right", "lunge-left");
  void el.offsetWidth;
  el.classList.add(cls);
}

function spawnSpark(side, isSkill) {
  const el = document.querySelector(`.fighter-${side.toLowerCase()}`);
  if (!el) return;
  const spark = document.createElement("div");
  spark.className = isSkill ? "hit-spark hit-spark-skill" : "hit-spark";
  el.appendChild(spark);
  spark.addEventListener("animationend", () => spark.remove());
}

let skillBannerTimer = null;

function showSkillBanner(actorName, skillName) {
  const banner = document.getElementById("skillBanner");
  banner.textContent = `⚡ ${actorName}의 「${skillName}」 발동!`;
  banner.classList.remove("show");
  void banner.offsetWidth;
  banner.classList.add("show");
  clearTimeout(skillBannerTimer);
  skillBannerTimer = setTimeout(() => banner.classList.remove("show"), 1200);
}

function appendLogLine(text, cls) {
  const logEl = document.getElementById("battleLog");
  const span = document.createElement("span");
  span.className = cls;
  span.textContent = text;
  logEl.appendChild(span);
  logEl.scrollTop = logEl.scrollHeight;
}

function applyBattleEvent(ev) {
  const isSkill = ev.kind?.startsWith("skill_");

  // 행동 주체의 MP 게이지는 공격/스킬 이벤트마다 서버가 계산해서 넘겨준다
  if (ev.actor_side && ev.actor_mp !== undefined && battle.fighters[ev.actor_side]) {
    battle.fighters[ev.actor_side].mp = ev.actor_mp;
  }

  switch (ev.kind) {
    case "duel_start":
      battle.fighters.A = { ...ev.a };
      battle.fighters.B = { ...ev.b };
      appendLogLine(ev.text, "duel-line");
      break;

    case "attack":
    case "skill_damage": {
      const targetSide = ev.target_side;
      battle.fighters[targetSide].hp = ev.target_hp;
      lungeFighter(ev.actor_side);
      flashFighter(targetSide, isSkill ? "skill-hit" : "hit");
      spawnSpark(targetSide, isSkill);
      if (isSkill) showSkillBanner(ev.actor, ev.skill_name);
      appendLogLine(ev.text, "event-line");
      break;
    }

    case "miss": {
      lungeFighter(ev.actor_side);
      flashFighter(ev.target_side, "miss");
      appendLogLine(ev.text, "event-line");
      break;
    }

    case "skill_heal": {
      battle.fighters[ev.actor_side].hp = ev.actor_hp;
      flashFighter(ev.actor_side, "heal");
      showSkillBanner(ev.actor, ev.skill_name);
      appendLogLine(ev.text, "event-line");
      break;
    }

    case "skill_heal_mp":
      showSkillBanner(ev.actor, ev.skill_name);
      appendLogLine(ev.text, "event-line");
      break;

    case "skill_buff":
      flashFighter(ev.actor_side, "buff");
      showSkillBanner(ev.actor, ev.skill_name);
      appendLogLine(ev.text, "event-line");
      break;

    case "skill_debuff": {
      const targetSide = ev.team_wide ? (ev.actor_side === "A" ? "B" : "A") : ev.target_side;
      flashFighter(targetSide, "debuff");
      showSkillBanner(ev.actor, ev.skill_name);
      appendLogLine(ev.text, "event-line");
      break;
    }

    case "faint":
      battle.fighters[ev.side].hp = 0;
      appendLogLine(ev.text, "event-line");
      break;

    case "battle_end": {
      appendLogLine(`🏆 승자: ${battle.data.winner_nickname}`, "winner-line");
      document.getElementById("battleEventText").textContent = `🏆 승자: ${battle.data.winner_nickname}`;
      document.getElementById("btnBattleNext").classList.add("hidden");
      document.getElementById("btnBattleSkip").classList.add("hidden");
      document.getElementById("btnBattleBack").classList.remove("hidden");
      break;
    }
  }

  setFighterUI("A", battle.fighters.A);
  setFighterUI("B", battle.fighters.B);
  if (ev.kind !== "battle_end") {
    document.getElementById("battleEventText").textContent = ev.text;
  }
}

document.getElementById("btnBattleNext").addEventListener("click", () => {
  if (!battle.data || battle.index >= battle.data.events.length) return;
  applyBattleEvent(battle.data.events[battle.index]);
  battle.index += 1;
});

document.getElementById("btnBattleSkip").addEventListener("click", () => {
  if (!battle.data) return;
  while (battle.index < battle.data.events.length) {
    applyBattleEvent(battle.data.events[battle.index]);
    battle.index += 1;
  }
});

document.getElementById("btnBattleBack").addEventListener("click", () => {
  showScreen("lobby");
});
