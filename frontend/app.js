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
  await loadCollection();
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
      ${rarityBadgesHtml(card.rarity)}
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

function resetBattleUI() {
  battle.decks = { A: [], B: [] };
  battle.queue = [];
  battle.playing = false;
  battle.fastForward = false;
  clearTargetPrompt();
  document.getElementById("battleLog").innerHTML = "";
  document.getElementById("battleEventText").textContent = "전투 시작!";
  document.getElementById("btnBattleSkip").classList.remove("hidden");
  document.getElementById("btnBattleBack").classList.add("hidden");
  updateSkipButton();
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
    if (!battle.fastForward && ev.kind !== "battle_start") {
      await new Promise((resolve) => setTimeout(resolve, EVENT_DELAY_MS));
    }
  }
  battle.playing = false;
}

function cardSlotHtml(side, pos, card) {
  if (!card) return `<div class="battle-slot empty"></div>`;
  const dead = card.hp <= 0;
  const hpPct = card.max_hp ? Math.max(0, Math.min(100, (card.hp / card.max_hp) * 100)) : 0;
  const mpPct = card.max_mp ? Math.max(0, Math.min(100, (card.mp / card.max_mp) * 100)) : 0;
  const badges = [
    card.stunned ? `<span class="status-badge" title="무력화">💫</span>` : "",
    card.infected ? `<span class="status-badge" title="역병">☠️</span>` : "",
  ].join("");
  return `
    <div class="battle-slot rarity-${card.rarity}${dead ? " dead" : ""}" data-side="${side}" data-pos="${pos}">
      ${rarityBadgesHtml(card.rarity)}
      <img class="battle-slot-portrait" src="${portraitSrc(card.name)}" alt=""
           onerror="this.onerror=null;this.src='${FALLBACK_PORTRAIT}';">
      <div class="battle-slot-info">
        <div class="battle-slot-name">${card.name}<span class="battle-slot-badges">${badges}</span></div>
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

const FLASH_CLASSES = ["flash-hit", "flash-skill-hit", "flash-heal", "flash-buff", "flash-debuff", "flash-miss"];

function flashSlot(side, pos, kind) {
  const el = document.querySelector(`.battle-slot[data-side="${side}"][data-pos="${pos}"]`);
  if (!el) return;
  el.classList.remove(...FLASH_CLASSES);
  void el.offsetWidth; // 강제 리플로우로 애니메이션 재시작
  el.classList.add(`flash-${kind}`);
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
    case "swap": {
      const a = battle.decks[ev.actor_side][ev.actor_pos];
      const b = battle.decks[ev.target_side][ev.target_pos];
      battle.decks[ev.actor_side][ev.actor_pos] = b;
      battle.decks[ev.target_side][ev.target_pos] = a;
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
  switch (ev.kind) {
    case "attack":
      flashSlot(ev.target_side, ev.target_pos, "hit");
      break;
    case "skill_damage":
      flashSlot(ev.target_side, ev.target_pos, "skill-hit");
      break;
    case "skill_cast":
      showSkillBanner(ev.actor, ev.skill_name);
      break;
    case "miss":
      flashSlot(ev.target_side, ev.target_pos, "miss");
      break;
    case "skill_heal":
    case "skill_heal_mp":
      flashSlot(ev.target_side, ev.target_pos, "heal");
      break;
    case "skill_buff":
    case "extra_turn":
      flashSlot(ev.actor_side, ev.actor_pos, "buff");
      break;
    case "skill_debuff":
      if (ev.team_wide) {
        const enemySide = ev.actor_side === "A" ? "B" : "A";
        (battle.decks[enemySide] || []).forEach((_, i) => flashSlot(enemySide, i, "debuff"));
      } else {
        flashSlot(ev.target_side, ev.target_pos, "debuff");
      }
      break;
    case "stun":
    case "mp_drain":
      flashSlot(ev.target_side, ev.target_pos, "debuff");
      break;
    case "plague_tick":
      flashSlot(ev.side, ev.pos, "hit");
      break;
  }
}

function applyBattleEvent(ev) {
  if (ev.kind === "battle_start") {
    battle.decks.A = ev.deck_a.map((c) => ({ ...c }));
    battle.decks.B = ev.deck_b.map((c) => ({ ...c }));
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
  appendLogLine(ev.text, ev.kind === "round_start" ? "round-line" : "event-line");

  if (ev.kind !== "battle_start") {
    document.getElementById("battleEventText").textContent = ev.text;
  }
}

function highlightTargets() {
  const ctx = battle.targetContext;
  if (!ctx) return;
  ctx.targets.forEach((t) => {
    const slot = document.querySelector(`.battle-slot[data-side="${t.side}"][data-pos="${t.pos}"]`);
    if (!slot) return;
    slot.classList.add("targetable");
    slot.onclick = () => chooseTarget(t.pos);
  });
}

function clearTargetPrompt() {
  battle.targetContext = null;
  document.getElementById("targetPrompt").classList.add("hidden");
  document.querySelectorAll(".battle-slot.targetable").forEach((el) => {
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

function onBattleResult(data) {
  // battle_result는 마지막 battle_event 이후에 도착하지만, 이 시점에 아직 큐에 남아
  // 재생 대기 중인 이벤트가 있을 수 있다. 승자 배너가 나중에 덮어써지지 않도록
  // 남은 이벤트를 지연 없이 즉시 다 반영해버린 뒤에 배너를 띄운다.
  battle.fastForward = true;
  while (battle.queue.length > 0) {
    applyBattleEvent(battle.queue.shift());
  }

  document.getElementById("battleTitle").textContent = `${data.player_a} vs ${data.player_b}`;
  clearTargetPrompt();
  document.getElementById("btnBattleSkip").classList.add("hidden");
  document.getElementById("btnBattleBack").classList.remove("hidden");
  document.getElementById("battleEventText").textContent = `🏆 승자: ${data.winner_nickname}`;
  appendLogLine(`🏆 승자: ${data.winner_nickname}`, "winner-line");
  if (data.rings_earned) {
    appendLogLine(
      `${data.player_a} +${data.rings_earned.A}링 · ${data.player_b} +${data.rings_earned.B}링`,
      "event-line",
    );
  }
  refreshRings();
}

document.getElementById("btnBattleSkip").addEventListener("click", () => {
  battle.fastForward = true;
  updateSkipButton();
});

document.getElementById("btnBattleBack").addEventListener("click", () => {
  showScreen("lobby");
});
