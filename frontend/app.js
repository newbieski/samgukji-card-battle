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

// ---------------------------------------------------------------------------
// 싱글/멀티 모드 선택
// ---------------------------------------------------------------------------

function setEntryMode(mode) {
  document.getElementById("tabModeSingle").classList.toggle("active", mode === "single");
  document.getElementById("tabModeMulti").classList.toggle("active", mode === "multi");
  document.getElementById("singleModeBox").classList.toggle("hidden", mode !== "single");
  document.getElementById("multiModeBox").classList.toggle("hidden", mode !== "multi");
  document.getElementById("entryError").textContent = "";
}

document.getElementById("tabModeSingle").addEventListener("click", () => setEntryMode("single"));
document.getElementById("tabModeMulti").addEventListener("click", () => setEntryMode("multi"));
setEntryMode("single");

document.getElementById("btnStartSingle").addEventListener("click", async () => {
  const nickname = document.getElementById("nicknameInput").value.trim();
  const errorEl = document.getElementById("entryError");
  errorEl.textContent = "";
  if (!nickname) {
    errorEl.textContent = "닉네임을 입력하세요.";
    return;
  }
  try {
    const res = await api("/rooms", {
      method: "POST",
      body: JSON.stringify({ nickname, title: `${nickname}의 연습 대결` }),
    });
    await api(`/rooms/${res.room_code}/ai_opponent`, { method: "POST" });
    enterRoom(res);
  } catch (e) {
    errorEl.textContent = e.message;
  }
});

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
    } else if (data.type === "battle_event") {
      queueBattleEvent(data);
    } else if (data.type === "await_target") {
      showTargetPrompt(data);
    } else if (data.type === "battle_result") {
      onBattleResult(data);
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
    if (p.auto_target) tags += `<span class="tag tag-auto">AI 위임</span>`;
    li.innerHTML = `<span>${p.nickname}${p.player_id === state.playerId ? " (나)" : ""}</span><span>${tags}</span>`;
    list.appendChild(li);

    if (p.player_id === state.playerId) {
      document.getElementById("chkAutoTarget").checked = !!p.auto_target;
    }
  });

  document.getElementById("lobbyStatus").textContent =
    data.players.length < 2 ? "다른 플레이어를 기다리는 중..." : "2명이 덱을 제출하면 전투가 시작됩니다.";
}

document.getElementById("btnToggleReady").addEventListener("click", () => {
  state.ws?.send(JSON.stringify({ type: "ready" }));
});

document.getElementById("chkAutoTarget").addEventListener("change", (e) => {
  state.ws?.send(JSON.stringify({ type: "set_auto", auto: e.target.checked }));
});

document.getElementById("btnGoCards").addEventListener("click", async () => {
  await Promise.all([loadCollection(), loadGachaInfo()]);
  showScreen("cards");
});

document.getElementById("btnCardsBack").addEventListener("click", () => {
  showScreen("lobby");
});

// ---------------------------------------------------------------------------
// 링 구매 (임시 mock 결제)
// ---------------------------------------------------------------------------

let shopCooldownTimer = null;

async function openShop() {
  const box = document.getElementById("shopPackages");
  box.innerHTML = `<p class="hint">불러오는 중...</p>`;
  document.getElementById("shopOverlay").classList.remove("hidden");
  clearInterval(shopCooldownTimer);
  try {
    const [packages, player] = await Promise.all([
      api("/ring-packages"),
      api(`/players/${state.playerId}`),
    ]);
    renderShopPackages(packages, player.purchase_cooldown_sec);
  } catch (e) {
    box.innerHTML = `<p class="error-text">상품 목록을 불러오지 못했습니다.</p>`;
  }
}

function renderShopPackages(packages, cooldownSec) {
  const box = document.getElementById("shopPackages");
  box.innerHTML = "";
  clearInterval(shopCooldownTimer);

  if (cooldownSec > 0) {
    const notice = document.createElement("p");
    notice.className = "hint";
    notice.textContent = `다음 구매까지 ${cooldownSec}초 남았습니다.`;
    box.appendChild(notice);

    let remaining = cooldownSec;
    shopCooldownTimer = setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        clearInterval(shopCooldownTimer);
        renderShopPackages(packages, 0);
      } else {
        notice.textContent = `다음 구매까지 ${remaining}초 남았습니다.`;
      }
    }, 1000);
  }

  packages.forEach((pkg) => {
    const btn = document.createElement("button");
    btn.className = "btn shop-package-btn";
    btn.disabled = cooldownSec > 0;
    btn.innerHTML = `<span>${pkg.rings}링</span><span class="shop-price">${pkg.price_label}</span>`;
    btn.addEventListener("click", () => purchaseRings(pkg.package_id));
    box.appendChild(btn);
  });
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
    try {
      const [packages, player] = await Promise.all([
        api("/ring-packages"),
        api(`/players/${state.playerId}`),
      ]);
      renderShopPackages(packages, player.purchase_cooldown_sec);
    } catch (_) {
      // 상점이 열려있는 동안만 보여주는 보조 정보라 실패해도 무시
    }
  }
}

document.getElementById("btnOpenShop").addEventListener("click", openShop);
document.getElementById("btnCloseShop").addEventListener("click", () => {
  document.getElementById("shopOverlay").classList.add("hidden");
});

// ---------------------------------------------------------------------------
// 뽑기
// ---------------------------------------------------------------------------

const RARITY_ORDER = { E: 0, D: 1, C: 2, B: 3, A: 4, S: 5 };

// 뽑기 비용/확률은 서버에서 받아온다 (하드코딩해두면 밸런스 바뀔 때 어긋난다)
async function loadGachaInfo() {
  try {
    const info = await api("/gacha/info");
    state.gachaInfo = info;
    const rates = info.rates
      .slice()
      .sort((a, b) => RARITY_ORDER[b.rarity] - RARITY_ORDER[a.rarity])
      .map((r) => `${r.rarity} ${r.percent}%`)
      .join(" / ");
    document.getElementById("gachaRates").textContent = `1회 ${info.cost}링 · ${rates}`;
    document.getElementById("btnDraw").textContent = `뽑기 (${info.cost}링)`;
    document.getElementById("btnDrawMulti").textContent =
      `패키지 뽑기 (${info.multi.cost}링)`;
    document.getElementById("gachaMultiHint").textContent =
      `패키지: ${info.multi.paid}장 값으로 ${info.multi.total}장 (+${info.multi.bonus}장 덤)`;
  } catch (e) {
    document.getElementById("gachaRates").textContent = "확률 정보를 불러오지 못했습니다.";
  }
}

document.getElementById("btnDraw").addEventListener("click", async () => {
  try {
    const result = await api(`/gacha/draw?player_id=${state.playerId}`, { method: "POST" });
    state.rings = result.remaining_rings;
    updatePlayerInfoBar();
    document.getElementById("multiDrawResult").classList.add("hidden");
    renderDrawResult(result);
    await loadCollection();
  } catch (e) {
    alert(e.message);
  }
});

document.getElementById("btnDrawMulti").addEventListener("click", async () => {
  try {
    const result = await api(`/gacha/draw_multi?player_id=${state.playerId}`, { method: "POST" });
    state.rings = result.remaining_rings;
    updatePlayerInfoBar();
    document.getElementById("drawResult").classList.add("hidden");
    renderMultiDrawResult(result);
    await loadCollection();
  } catch (e) {
    alert(e.message);
  }
});

function renderMultiDrawResult(result) {
  const box = document.getElementById("multiDrawResult");
  const grid = document.getElementById("multiDrawGrid");
  const best = result.cards.reduce(
    (top, c) => (RARITY_ORDER[c.rarity] > RARITY_ORDER[top.rarity] ? c : top),
    result.cards[0],
  );
  document.getElementById("multiDrawTitle").textContent =
    `패키지 뽑기 결과 ${result.cards.length}장 (${result.paid}장 + 덤 ${result.bonus}장) · 최고 등급 ${best.rarity} ${best.general_name}`;

  grid.innerHTML = result.cards
    .map((c, i) => {
      const role = skillRole(c.skill_effect_type);
      const isBonus = i >= result.paid;
      return `
        <div class="multi-draw-card card-tile rarity-${c.rarity}">
          ${rarityBadgesHtml(c.rarity)}
          ${isBonus ? `<div class="bonus-tag">덤</div>` : ""}
          <img class="tile-portrait" src="${portraitSrc(c.general_name)}" alt="${c.general_name}"
               onerror="this.onerror=null;this.src='${FALLBACK_PORTRAIT}';">
          <div class="name">${c.general_name}</div>
          <div>${c.faction} · <span class="tile-role">${role.icon} ${role.label}</span></div>
          <div class="tile-skill">${role.icon} ${c.skill_name}</div>
        </div>`;
    })
    .join("");
  box.classList.remove("hidden");
}

const FALLBACK_PORTRAIT = "assets/portraits/_unknown.png";

function portraitSrc(name) {
  return `assets/portraits/${encodeURIComponent(name)}.png`;
}

// 스킬 효과 종류로 장수의 역할을 정한다. 아이콘은 전투 로그/배너/카드에서 공통으로 쓴다.
const SKILL_ROLES = {
  damage:     { icon: "⚔️", label: "공격형" },
  heal:       { icon: "✚",  label: "회복형" },
  buff:       { icon: "🛡️", label: "지원형" },
  debuff:     { icon: "🔻", label: "방해형" },
  extra_turn: { icon: "⚡", label: "속공형" },
  stun:       { icon: "💫", label: "제압형" },
  discord:    { icon: "🔀", label: "이간형" },
  mp_drain:   { icon: "🌀", label: "탈취형" },
  plague:     { icon: "☠️", label: "역병형" },
};

function skillRole(effectType) {
  return SKILL_ROLES[effectType] ?? { icon: "✦", label: "특수형" };
}

function rarityBadgesHtml(rarity) {
  const style = `color: var(--rarity-${rarity}); border-color: var(--rarity-${rarity});`;
  return `
    <span class="rarity-badge rarity-badge-tl" style="${style}">${rarity}</span>
    <span class="rarity-badge rarity-badge-br" style="${style}">${rarity}</span>
  `;
}

function renderDrawResult(result) {
  const box = document.getElementById("drawResult");
  const card = document.getElementById("drawCard");
  card.className = `card rarity-${result.rarity}`;
  card.innerHTML = `
    ${rarityBadgesHtml(result.rarity)}
    <img class="card-portrait" src="${portraitSrc(result.general_name)}" alt="${result.general_name}"
         onerror="this.onerror=null;this.src='${FALLBACK_PORTRAIT}';">
    <div class="card-name">${result.general_name}</div>
    <div class="card-rarity">${result.faction} · ${result.rarity} · ${skillRole(result.skill_effect_type).icon} ${skillRole(result.skill_effect_type).label}</div>
    <div class="card-skill">
      <strong>${skillRole(result.skill_effect_type).icon} ${result.skill_name}</strong><br>
      <span class="skill-effect">${result.skill_effect_text ?? ""}</span><br>
      ${result.skill_description}
    </div>
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
      ${rarityBadgesHtml(card.rarity)}
      <img class="tile-portrait" src="${portraitSrc(card.name)}" alt="${card.name}"
           onerror="this.onerror=null;this.src='${FALLBACK_PORTRAIT}';">
      <div class="name">${card.name}</div>
      <div>${card.faction} · <span class="tile-role">${skillRole(card.skill_effect_type).icon} ${skillRole(card.skill_effect_type).label}</span></div>
      <div class="tile-skill">${skillRole(card.skill_effect_type).icon} ${card.skill_name}</div>
      <div class="skill-effect">${card.skill_effect_text ?? ""}</div>
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

// ---------------------------------------------------------------------------
// 전투 (양 덱 5장씩 실시간 라운드제, 서버가 한 번에 이벤트 하나씩 흘려보냄)
// ---------------------------------------------------------------------------

const EVENT_DELAY_MS = 550;

const battle = {
  decks: { A: [], B: [] },   // 각 5칸: 카드 스냅샷 객체 또는 null
  queue: [],
  playing: false,
  fastForward: false,
  targetContext: null,       // {actor, targets:[{side,pos,...}]} - 내가 대상을 골라야 할 때
  pendingResult: null,       // 재생이 끝나면 띄울 전투 결과
  playerNames: { A: "A팀", B: "B팀" },
  currentActor: null,        // {side, pos} - 지금 행동하는 카드
};

function getBattleCard(side, pos) {
  return battle.decks[side]?.[pos] ?? null;
}

function updateSkipButton() {
  const btn = document.getElementById("btnBattleSkip");
  if (battle.fastForward) {
    btn.disabled = true;
    btn.textContent = "연출 생략 중";
    return;
  }
  const pending = battle.queue.length;
  btn.disabled = pending === 0;
  btn.textContent = pending > 0
    ? `연출 건너뛰기 (밀린 이벤트 ${pending}개)`
    : "연출 건너뛰기 (밀린 이벤트 없음)";
}

const BATTLE_SCENES = [
  "guandu", "redcliffs", "huarong", "changban", "yiling",
  "hanzhong", "hefei", "dingjun", "wuzhang", "fancheng",
];

function pickRandomBattleScene() {
  const key = BATTLE_SCENES[Math.floor(Math.random() * BATTLE_SCENES.length)];
  document.querySelector(".battle-stage").style.backgroundImage =
    `url("assets/scenes/battle_${key}.png")`;
}

function resetBattleUI() {
  battle.decks = { A: [], B: [] };
  battle.queue = [];
  battle.playing = false;
  battle.fastForward = false;
  battle.pendingResult = null;
  battle.currentActor = null;
  clearTargetPrompt();
  document.getElementById("turnIndicator").classList.add("hidden");
  document.getElementById("battleLog").innerHTML = "";
  document.getElementById("battleEventText").textContent = "전투 시작!";
  document.getElementById("btnBattleSkip").classList.remove("hidden");
  document.getElementById("btnBattleBack").classList.add("hidden");
  updateSkipButton();
  pickRandomBattleScene();
  showScreen("battle");
}

function queueBattleEvent(ev) {
  if (ev.kind === "battle_start") {
    resetBattleUI();
  }
  battle.queue.push(ev);
  updateSkipButton();
  if (!battle.playing) pumpBattleQueue();
}

async function pumpBattleQueue() {
  battle.playing = true;
  while (battle.queue.length > 0) {
    const ev = battle.queue.shift();
    applyBattleEvent(ev);
    updateSkipButton();
    // turn_start는 "누구 차례"만 알려주는 표시용이라 따로 텀을 두지 않는다
    if (!battle.fastForward && ev.kind !== "battle_start" && ev.kind !== "turn_start") {
      await new Promise((resolve) => setTimeout(resolve, EVENT_DELAY_MS));
    }
  }
  battle.playing = false;
  updateSkipButton();
  maybeShowBattleResult();
}

function cardSlotHtml(side, pos, card) {
  if (!card) return `<div class="battle-card empty"></div>`;
  const dead = card.hp <= 0;
  const hpPct = card.max_hp ? Math.max(0, Math.min(100, (card.hp / card.max_hp) * 100)) : 0;
  const mpPct = card.max_mp ? Math.max(0, Math.min(100, (card.mp / card.max_mp) * 100)) : 0;
  const badges = [
    card.stunned ? `<span class="status-badge" title="무력화">💫</span>` : "",
    card.infected ? `<span class="status-badge" title="역병">☠️</span>` : "",
    card.discorded ? `<span class="status-badge" title="이간 - 같은 편을 공격한다">🔀</span>` : "",
  ].join("");
  const acting = !dead && battle.currentActor
    && battle.currentActor.side === side && battle.currentActor.pos === pos;
  const role = skillRole(card.skill_effect_type);
  const skillReady = !dead && card.max_mp && card.mp >= card.max_mp;
  return `
    <div class="battle-card rarity-${card.rarity}${dead ? " dead" : ""}${acting ? " acting" : ""}" data-side="${side}" data-pos="${pos}">
      <div class="battle-card-body">
        ${rarityBadgesHtml(card.rarity)}
        <img class="battle-card-portrait" src="${portraitSrc(card.name)}" alt=""
             onerror="this.onerror=null;this.src='${FALLBACK_PORTRAIT}';">
        <div class="battle-card-name">${card.name}<span class="battle-card-badges">${badges}</span></div>
        <div class="battle-card-skill${skillReady ? " ready" : ""}"
             title="${role.label} · ${card.skill_effect_text ?? ""}">
          <span class="role-icon">${role.icon}</span>${card.skill_name ?? ""}
        </div>
        <div class="hp-bar-track small"><div class="hp-bar-fill${hpPct <= 30 ? " low" : ""}" style="width:${hpPct}%"></div></div>
        <div class="mp-bar-track small"><div class="mp-bar-fill${mpPct >= 100 ? " full" : ""}" style="width:${mpPct}%"></div></div>
      </div>
    </div>`;
}

function renderDeckColumn(side) {
  const el = document.getElementById(`deckColumn${side}`);
  el.innerHTML = battle.decks[side].map((c, i) => cardSlotHtml(side, i, c)).join("");
  if (battle.targetContext) highlightTargets();
}

const FLASH_CLASSES = [
  "flash-hit", "flash-skill-hit", "flash-heal", "flash-buff", "flash-debuff",
  "flash-miss", "flash-lunge-down", "flash-lunge-up", "flash-faint",
];

function battleCardEl(side, pos) {
  return document.querySelector(`.battle-card[data-side="${side}"][data-pos="${pos}"]`);
}

function flashSlot(side, pos, kind) {
  const el = battleCardEl(side, pos);
  if (!el) return;
  el.classList.remove(...FLASH_CLASSES);
  void el.offsetWidth; // 강제 리플로우로 애니메이션 재시작
  el.classList.add(`flash-${kind}`);
}

function spawnSpark(side, pos, isSkill) {
  const el = battleCardEl(side, pos);
  if (!el) return;
  const spark = document.createElement("div");
  spark.className = isSkill ? "hit-spark skill" : "hit-spark";
  el.appendChild(spark);
  spark.addEventListener("animationend", () => spark.remove());
}

function spawnPopup(side, pos, text, kind) {
  const el = battleCardEl(side, pos);
  if (!el) return;
  const popup = document.createElement("div");
  popup.className = `dmg-popup ${kind}`;
  popup.textContent = text;
  el.appendChild(popup);
  popup.addEventListener("animationend", () => popup.remove());
}

function flareStage() {
  const stage = document.querySelector(".battle-stage");
  if (!stage) return;
  const flare = document.createElement("div");
  flare.className = "stage-flare";
  stage.appendChild(flare);
  flare.addEventListener("animationend", () => flare.remove());
}

function shakeStage() {
  const stage = document.querySelector(".battle-stage");
  if (!stage) return;
  stage.classList.remove("shake");
  void stage.offsetWidth;
  stage.classList.add("shake");
}

/** 카드 위에 스킬 효과 종류별 오버레이를 한 번 덮어씌운다. */
function spawnFx(side, pos, fxClass, text) {
  const el = battleCardEl(side, pos);
  if (!el) return;
  const fx = document.createElement("div");
  fx.className = `fx-overlay ${fxClass}`;
  if (text) fx.textContent = text;
  el.appendChild(fx);
  fx.addEventListener("animationend", () => fx.remove());
}

function spawnSlash(side, pos) {
  const el = battleCardEl(side, pos);
  if (!el) return;
  const slash = document.createElement("div");
  slash.className = "fx-slash";
  el.appendChild(slash);
  slash.addEventListener("animationend", () => slash.remove());
}

/** 공격 측은 상대 줄을 향해 돌진한다 (A는 윗줄이라 아래로, B는 아랫줄이라 위로). */
function lungeToward(side, pos) {
  flashSlot(side, pos, side === "A" ? "lunge-down" : "lunge-up");
}

let skillBannerTimer = null;

function showSkillBanner(actorName, skillName, effectType, effectText) {
  const banner = document.getElementById("skillBanner");
  const role = skillRole(effectType);
  banner.innerHTML =
    `<span class="banner-skill">${role.icon} ${actorName}의 「${skillName}」</span>` +
    (effectText ? `<span class="banner-effect">${role.label} · ${effectText}</span>` : "");
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

function applyEventToState(ev) {
  switch (ev.kind) {
    case "attack":
    case "skill_damage":
    case "skill_heal": {
      const t = getBattleCard(ev.target_side, ev.target_pos);
      if (t) t.hp = ev.target_hp;
      break;
    }
    case "skill_heal_mp":
    case "mp_drain": {
      const t = getBattleCard(ev.target_side, ev.target_pos);
      if (t) t.mp = ev.target_mp;
      break;
    }
    case "stun": {
      const t = getBattleCard(ev.target_side, ev.target_pos);
      if (t) t.stunned = true;
      break;
    }
    case "discord": {
      const t = getBattleCard(ev.target_side, ev.target_pos);
      if (t) t.discorded = true;
      break;
    }
    case "discord_attack": {
      const t = getBattleCard(ev.target_side, ev.target_pos);
      if (t) t.hp = ev.target_hp;
      const actor = getBattleCard(ev.actor_side, ev.actor_pos);
      if (actor) actor.discorded = false;
      break;
    }
    case "plague_infect": {
      const t = getBattleCard(ev.target_side, ev.target_pos);
      if (t) t.infected = true;
      break;
    }
    case "plague_tick": {
      const t = getBattleCard(ev.side, ev.pos);
      if (t) t.hp = ev.target_hp;
      break;
    }
    case "plague_spread": {
      const t = getBattleCard(ev.side, ev.to_pos);
      if (t) t.infected = true;
      break;
    }
    case "faint": {
      const c = getBattleCard(ev.side, ev.pos);
      if (c) { c.hp = 0; c.stunned = false; c.infected = false; }
      break;
    }
  }
}

function playEventEffects(ev) {
  const enemyOf = (side) => (side === "A" ? "B" : "A");

  switch (ev.kind) {
    case "attack":
      lungeToward(ev.actor_side, ev.actor_pos);
      flashSlot(ev.target_side, ev.target_pos, "hit");
      spawnSlash(ev.target_side, ev.target_pos);
      spawnSpark(ev.target_side, ev.target_pos, false);
      spawnPopup(ev.target_side, ev.target_pos, `-${ev.amount}`, "damage");
      shakeStage();
      break;

    case "skill_damage":
      flashSlot(ev.target_side, ev.target_pos, "skill-hit");
      spawnSlash(ev.target_side, ev.target_pos);
      spawnSpark(ev.target_side, ev.target_pos, true);
      spawnPopup(ev.target_side, ev.target_pos, `-${ev.amount}`, "damage");
      shakeStage();
      break;

    case "skill_cast":
      showSkillBanner(ev.actor, ev.skill_name, ev.skill_effect_type, ev.skill_effect_text);
      flareStage();
      flashSlot(ev.actor_side, ev.actor_pos, "buff");
      break;

    case "miss":
      lungeToward(ev.actor_side, ev.actor_pos);
      flashSlot(ev.target_side, ev.target_pos, "miss");
      spawnPopup(ev.target_side, ev.target_pos, "MISS", "miss");
      break;

    case "skill_heal":
      spawnFx(ev.target_side, ev.target_pos, "fx-heal");
      spawnPopup(ev.target_side, ev.target_pos, `+${ev.amount}`, "heal");
      break;

    case "skill_heal_mp":
      spawnFx(ev.target_side, ev.target_pos, "fx-heal");
      spawnPopup(ev.target_side, ev.target_pos, `MP +${ev.amount}`, "mp");
      break;

    case "skill_buff":
      if (ev.team_wide) {
        (battle.decks[ev.actor_side] || []).forEach((c, i) => {
          if (c && c.hp > 0) spawnFx(ev.actor_side, i, "fx-buff");
        });
      } else {
        spawnFx(ev.actor_side, ev.actor_pos, "fx-buff");
      }
      break;

    case "extra_turn":
      spawnFx(ev.actor_side, ev.actor_pos, "fx-extra");
      spawnPopup(ev.actor_side, ev.actor_pos, "⚡ 한 번 더", "heal");
      break;

    case "skill_debuff":
      if (ev.team_wide) {
        const enemySide = enemyOf(ev.actor_side);
        (battle.decks[enemySide] || []).forEach((c, i) => {
          if (c && c.hp > 0) spawnFx(enemySide, i, "fx-debuff");
        });
      } else {
        spawnFx(ev.target_side, ev.target_pos, "fx-debuff");
      }
      break;

    case "stun":
      spawnFx(ev.target_side, ev.target_pos, "fx-stun", "💫");
      spawnPopup(ev.target_side, ev.target_pos, `${ev.duration}턴 무력화`, "debuff");
      break;

    case "mp_drain":
      spawnFx(ev.target_side, ev.target_pos, "fx-drain");
      spawnPopup(ev.target_side, ev.target_pos, `MP -${ev.amount}`, "mp");
      break;

    case "discord":
      spawnFx(ev.target_side, ev.target_pos, "fx-debuff");
      spawnPopup(ev.target_side, ev.target_pos, "🔀 이간", "debuff");
      flareStage();
      break;

    case "discord_attack":
      lungeToward(ev.actor_side, ev.actor_pos);
      flashSlot(ev.target_side, ev.target_pos, "hit");
      spawnSlash(ev.target_side, ev.target_pos);
      spawnPopup(ev.target_side, ev.target_pos, `-${ev.amount}`, "damage");
      shakeStage();
      break;

    case "plague_infect":
      spawnFx(ev.target_side, ev.target_pos, "fx-plague");
      spawnPopup(ev.target_side, ev.target_pos, "☠️ 역병", "debuff");
      break;

    case "plague_tick":
      spawnFx(ev.side, ev.pos, "fx-plague");
      spawnPopup(ev.side, ev.pos, `-${ev.amount}`, "damage");
      break;

    case "plague_spread":
      spawnFx(ev.side, ev.to_pos, "fx-plague");
      spawnPopup(ev.side, ev.to_pos, "☠️ 전염", "debuff");
      break;

    case "faint":
      flashSlot(ev.side, ev.pos, "faint");
      break;
  }
}

function showTurnIndicator(side, cardName) {
  const el = document.getElementById("turnIndicator");
  el.classList.remove("hidden", "side-a", "side-b");
  el.classList.add(side === "A" ? "side-a" : "side-b");
  el.innerHTML = `<span class="turn-player">${battle.playerNames[side] ?? side}</span> 차례 · ${cardName}`;
}

// ---------------------------------------------------------------------------
// 데스매치(일기토) - 라운드 제한에 걸리면 대표 1:1로 결판을 낸다
// ---------------------------------------------------------------------------

const deathmatch = { fighters: { A: null, B: null } };

function dmFighterHtml(card) {
  const hpPct = card.max_hp ? Math.max(0, Math.min(100, (card.hp / card.max_hp) * 100)) : 0;
  const mpPct = card.max_mp ? Math.max(0, Math.min(100, (card.mp / card.max_mp) * 100)) : 0;
  const role = skillRole(card.skill_effect_type);
  const ready = card.mp >= card.max_mp && card.hp > 0;
  return `
    ${rarityBadgesHtml(card.rarity)}
    <img class="dm-fighter-portrait" src="${portraitSrc(card.name)}" alt=""
         onerror="this.onerror=null;this.src='${FALLBACK_PORTRAIT}';">
    <div class="dm-fighter-name">${card.name}</div>
    <div class="dm-fighter-skill${ready ? " ready" : ""}">${role.icon} ${card.skill_name ?? ""}</div>
    <div class="hp-bar-track"><div class="hp-bar-fill${hpPct <= 30 ? " low" : ""}" style="width:${hpPct}%"></div></div>
    <div class="hp-text">HP ${Math.max(card.hp, 0)} / ${card.max_hp}</div>
    <div class="mp-bar-track"><div class="mp-bar-fill${mpPct >= 100 ? " full" : ""}" style="width:${mpPct}%"></div></div>`;
}

function renderDeathmatchFighter(side) {
  const card = deathmatch.fighters[side];
  if (!card) return;
  const el = document.getElementById(`dmFighter${side}`);
  el.className = `dm-fighter dm-fighter-${side.toLowerCase()}`
    + ` rarity-${card.rarity}${card.hp <= 0 ? " dm-dead" : ""}`;
  el.innerHTML = dmFighterHtml(card);
}

function flashDmFighter(side, kind) {
  const el = document.getElementById(`dmFighter${side}`);
  if (!el) return;
  el.classList.remove(...FLASH_CLASSES);
  void el.offsetWidth;
  el.classList.add(`flash-${kind}`);
}

function dmPopup(side, text, kind) {
  const el = document.getElementById(`dmFighter${side}`);
  if (!el) return;
  const popup = document.createElement("div");
  popup.className = `dmg-popup ${kind}`;
  popup.textContent = text;
  el.appendChild(popup);
  popup.addEventListener("animationend", () => popup.remove());
}

function applyDeathmatchEvent(ev) {
  switch (ev.kind) {
    case "deathmatch_start":
      deathmatch.fighters.A = { ...ev.a };
      deathmatch.fighters.B = { ...ev.b };
      document.getElementById("dmTitle").textContent =
        `일기토 · ${ev.a.name} vs ${ev.b.name}`;
      document.getElementById("dmIntro").textContent = ev.text;
      document.getElementById("dmLog").innerHTML = "";
      document.getElementById("btnDmBack").classList.add("hidden");
      renderDeathmatchFighter("A");
      renderDeathmatchFighter("B");
      showScreen("deathmatch");
      break;

    case "deathmatch_attack": {
      const t = deathmatch.fighters[ev.target_side];
      if (t) t.hp = ev.target_hp;
      renderDeathmatchFighter(ev.target_side);
      flashDmFighter(ev.target_side, ev.is_skill ? "skill-hit" : "hit");
      dmPopup(ev.target_side, `-${ev.amount}`, "damage");
      break;
    }

    case "deathmatch_heal": {
      const f = deathmatch.fighters[ev.side];
      if (f) f.hp = ev.target_hp;
      renderDeathmatchFighter(ev.side);
      flashDmFighter(ev.side, "heal");
      dmPopup(ev.side, `+${ev.amount}`, "heal");
      break;
    }

    case "deathmatch_plague_tick": {
      const f = deathmatch.fighters[ev.side];
      if (f) f.hp = ev.target_hp;
      renderDeathmatchFighter(ev.side);
      flashDmFighter(ev.side, "hit");
      dmPopup(ev.side, `-${ev.amount}`, "damage");
      break;
    }

    case "deathmatch_skill":
      showSkillBanner(ev.name, ev.skill_name, ev.skill_effect_type, ev.skill_effect_text);
      flashDmFighter(ev.side, "buff");
      break;

    case "deathmatch_buff":
      flashDmFighter(ev.side, "buff");
      break;

    case "deathmatch_debuff":
    case "deathmatch_stun":
    case "deathmatch_plague":
      flashDmFighter(ev.side, "debuff");
      break;

    case "deathmatch_miss":
      flashDmFighter(ev.target_side, "miss");
      dmPopup(ev.target_side, "MISS", "miss");
      break;

    case "deathmatch_end":
      document.getElementById("dmIntro").textContent = `🏆 ${ev.text}`;
      break;
  }

  appendDmLogLine(ev.text, ev.kind === "deathmatch_exchange" ? "round-line" : "event-line");
  if (ev.kind !== "deathmatch_start") {
    document.getElementById("dmEventText").textContent = ev.text;
  }
}

function appendDmLogLine(text, cls) {
  const logEl = document.getElementById("dmLog");
  const span = document.createElement("span");
  span.className = cls;
  span.textContent = text;
  logEl.appendChild(span);
  logEl.scrollTop = logEl.scrollHeight;
}

document.getElementById("btnDmBack").addEventListener("click", () => {
  showScreen("lobby");
});

function applyBattleEvent(ev) {
  if (ev.kind && ev.kind.startsWith("deathmatch")) {
    applyDeathmatchEvent(ev);
    return;
  }
  if (ev.kind === "battle_start") {
    battle.decks.A = ev.deck_a.map((c) => ({ ...c }));
    battle.decks.B = ev.deck_b.map((c) => ({ ...c }));
    if (ev.names) battle.playerNames = ev.names;
  } else if (ev.kind === "turn_start") {
    battle.currentActor = { side: ev.side, pos: ev.pos };
    showTurnIndicator(ev.side, ev.name);
  } else {
    // 방금 행동한 카드는 더 이상 무력화 상태가 아니다 (스턴이 그새 풀렸으니까 움직인 것)
    if (ev.actor_side !== undefined && ev.actor_pos !== undefined) {
      const actor = getBattleCard(ev.actor_side, ev.actor_pos);
      if (actor) actor.stunned = false;
    }
    applyEventToState(ev);
  }

  renderDeckColumn("A");
  renderDeckColumn("B");
  playEventEffects(ev);

  // 차례 표시는 위쪽 표시줄로 충분해서 로그/문구까지 채우진 않는다
  if (ev.kind !== "turn_start") {
    appendLogLine(ev.text, ev.kind === "round_start" ? "round-line" : "event-line");
    if (ev.kind !== "battle_start") {
      document.getElementById("battleEventText").textContent = ev.text;
    }
  }
}

function highlightTargets() {
  const ctx = battle.targetContext;
  if (!ctx) return;
  ctx.targets.forEach((t) => {
    const slot = battleCardEl(t.side, t.pos);
    if (!slot) return;
    slot.classList.add("targetable");
    slot.onclick = () => chooseTarget(t.pos);
  });
}

function clearTargetPrompt() {
  battle.targetContext = null;
  document.getElementById("targetPrompt").classList.add("hidden");
  document.querySelectorAll(".battle-card.targetable").forEach((el) => {
    el.classList.remove("targetable");
    el.onclick = null;
  });
}

function chooseTarget(pos) {
  state.ws?.send(JSON.stringify({ type: "choose_target", pos }));
  clearTargetPrompt();
}

function showTargetPrompt(data) {
  battle.targetContext = data;
  const prompt = document.getElementById("targetPrompt");
  prompt.textContent = `${data.actor}의 대상을 선택하세요 (${data.timeout_sec}초 안에 고르지 않으면 자동으로 선택됩니다)`;
  prompt.classList.remove("hidden");
  highlightTargets();
}

// AI끼리 붙는 전투는 서버가 순식간에 끝내고 battle_result까지 바로 보내버린다.
// 그때 큐를 강제로 비워버리면 전투 장면이 통째로 날아가므로, 결과는 들고만 있다가
// 재생이 다 끝난 뒤에 띄운다.
function onBattleResult(data) {
  battle.pendingResult = data;
  maybeShowBattleResult();
}

function maybeShowBattleResult() {
  const data = battle.pendingResult;
  if (!data || battle.playing || battle.queue.length > 0) return;
  battle.pendingResult = null;

  battle.currentActor = null;
  renderDeckColumn("A");
  renderDeckColumn("B");
  document.getElementById("turnIndicator").classList.add("hidden");
  document.getElementById("battleTitle").textContent = `${data.player_a} vs ${data.player_b}`;
  clearTargetPrompt();
  document.getElementById("btnBattleSkip").classList.add("hidden");

  // 일기토로 끝났으면 결과도 일기토 화면에서 보여준다 (그쪽에 시선이 가 있으므로)
  const byDeathmatch = data.decision === "deathmatch";
  const winLabel = byDeathmatch ? "일기토 승자" : "승자";
  const resultLine = `🏆 ${winLabel}: ${data.winner_nickname}`;
  const ringLine = data.rings_earned
    ? `${data.player_a} +${data.rings_earned.A}링 · ${data.player_b} +${data.rings_earned.B}링`
    : null;

  if (byDeathmatch) {
    document.getElementById("dmEventText").textContent = resultLine;
    document.getElementById("btnDmBack").classList.remove("hidden");
    appendDmLogLine(resultLine, "winner-line");
    if (ringLine) appendDmLogLine(ringLine, "event-line");
  } else {
    document.getElementById("btnBattleBack").classList.remove("hidden");
    document.getElementById("battleEventText").textContent = resultLine;
  }

  appendLogLine(resultLine, "winner-line");
  if (ringLine) appendLogLine(ringLine, "event-line");
  refreshRings();
}

document.getElementById("btnBattleSkip").addEventListener("click", () => {
  battle.fastForward = true;
  updateSkipButton();
});

document.getElementById("btnBattleBack").addEventListener("click", () => {
  showScreen("lobby");
});
