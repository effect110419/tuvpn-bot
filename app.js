/* =====================================================================
   TuVPN Admin v3 — Linear-style, command-palette, keyboard-first
   ===================================================================== */

/* ===================== CONFIG ===================== */
const PROXY_URL = 'https://admin.tuvpn.ru';
/* ===================== STATE ===================== */
const state = {
  users: [], subs: [], payments: [], promos: [], promoUses: [],
  refs: [], tickets: [], supportAdmins: [], servers: [],
  currentChart: 'revenue',
  chartInstance: null,
  currentPage: 'dashboard',
  cmdActiveIdx: 0,
  cmdItems: [],
  loaded: false,
  keySeq: '',
  keySeqTimer: null,
};

/* ===================== HELPERS ===================== */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

const esc = s => String(s == null ? '' : s)
  .replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const num = n => (n == null ? '—' : Number(n).toLocaleString('ru-RU'));
const money = n => (n == null ? '—' : Number(n).toLocaleString('ru-RU', { maximumFractionDigits: 2 }) + ' ₽');

const fmtDate = d => {
  if (!d) return '—';
  const dt = new Date(d);
  if (isNaN(dt)) return '—';
  return dt.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short', year: '2-digit' });
};
const fmtDateTime = d => {
  if (!d) return '—';
  const dt = new Date(d);
  if (isNaN(dt)) return '—';
  return dt.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' });
};
const fmtTimeAgo = d => {
  if (!d) return '—';
  const dt = new Date(d);
  if (isNaN(dt)) return '—';
  const s = (Date.now() - dt.getTime()) / 1000;
  if (s < 60) return Math.floor(s) + ' с назад';
  if (s < 3600) return Math.floor(s / 60) + ' мин назад';
  if (s < 86400) return Math.floor(s / 3600) + ' ч назад';
  return Math.floor(s / 86400) + ' дн назад';
};
const daysLeft = d => {
  if (!d) return 0;
  return Math.ceil((new Date(d) - Date.now()) / 1000 / 86400);
};

const displayName = u => {
  if (!u) return '—';
  if (u.username) return '@' + u.username;
  const fn = [u.first_name, u.last_name].filter(Boolean).join(' ');
  return fn || ('id:' + (u.user_id || u.id));
};
const avaInitial = u => {
  if (!u) return 'U';
  const s = u.username || u.first_name || String(u.user_id || u.id || '?');
  return s.replace('@', '').charAt(0).toUpperCase();
};
const avaColor = uid => {
  const palette = [
    ['#5b8def', '#67e8f9'], ['#c084fc', '#f472b6'], ['#4ade80', '#67e8f9'],
    ['#facc15', '#fb923c'], ['#f87171', '#f472b6'], ['#67e8f9', '#5b8def'],
    ['#a855f7', '#f472b6'], ['#34d399', '#4ade80'],
  ];
  const idx = (Number(uid) || 0) % palette.length;
  return `linear-gradient(135deg, ${palette[idx][0]}, ${palette[idx][1]})`;
};
const avaHtml = u => `<div class="u-ava" style="background:${avaColor(u && (u.user_id || u.id))}">${avaInitial(u)}</div>`;

const userById = id => state.users.find(u => Number(u.user_id) === Number(id));
const activeSubFor = uid => state.subs.find(s => Number(s.user_id) === Number(uid) && s.status === 'active');

/* SVG icons */
const ICONS = {
  check: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
  close: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>',
  plus: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14"/><path d="M5 12h14"/></svg>',
  edit: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>',
  trash: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
  copy: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>',
  arrowRight: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" x2="19" y1="12" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>',
  refresh: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>',
  gift: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12v10H4V12"/><path d="M2 7h20v5H2z"/><path d="M12 22V7"/><path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7Z"/><path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7Z"/></svg>',
  calendar: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/></svg>',
  zap: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
  ext: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" x2="21" y1="14" y2="3"/></svg>',
  globe: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" x2="22" y1="12" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>',
  server: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="8" x="2" y="2" rx="2" ry="2"/><rect width="20" height="8" x="2" y="14" rx="2" ry="2"/><line x1="6" x2="6.01" y1="6" y2="6"/><line x1="6" x2="6.01" y1="18" y2="18"/></svg>',
  activity: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
  arrowUp: '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" x2="12" y1="19" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>',
  arrowDown: '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" x2="12" y1="5" y2="19"/><polyline points="19 12 12 19 5 12"/></svg>',
};

/* ===================== TOAST ===================== */
let toastSeq = 0;
function toast(msg, type = 'success', opts = {}) {
  const id = ++toastSeq;
  const ico = type === 'success' ? ICONS.check
    : type === 'error' ? '⚠'
    : type === 'warning' ? '⚠' : 'ℹ';
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.dataset.id = id;
  let undoHtml = '';
  if (opts.undo) {
    undoHtml = `<button class="undo" data-undo="${id}">Отменить</button>`;
  }
  el.innerHTML = `<span class="ico">${ico}</span><span class="text">${esc(msg)}</span>${undoHtml}`;
  $('#toastWrap').appendChild(el);
  const remove = () => { el.style.transition = 'opacity .2s, transform .2s'; el.style.opacity = '0'; el.style.transform = 'translateX(20px)'; setTimeout(() => el.remove(), 250); };
  if (opts.undo) {
    el.querySelector('.undo').addEventListener('click', () => { opts.undo(); remove(); });
  }
  setTimeout(remove, opts.duration || 3500);
  return id;
}

/* ===================== DB PROXY ===================== */
// === DB PROXY (replaces direct Supabase) ===
// Frontend больше не ходит в Supabase напрямую. Все запросы идут через
// backend /admin-api/db/<table>/, защищённый cookie + admin whitelist.

async function sbGet(table, query = '') {
  const url = `${PROXY_URL}/admin-api/db/${table}${query ? '?' + query : ''}`;
  const r = await fetch(url, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
  });
  if (r.status === 401) {
    showLogin();
    return [];
  }
  const body = await r.json();
  if (!body.success) {
    console.error(`sbGet(${table}) failed:`, body);
    return [];
  }
  return body.data || [];
}

async function sbInsert(table, data) {
  const r = await fetch(`${PROXY_URL}/admin-api/db/${table}`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (r.status === 401) { showLogin(); return null; }
  const body = await r.json();
  if (!body.success) {
    console.error(`sbInsert(${table}) failed:`, body);
    return null;
  }
  return body.data;
}

async function sbUpdate(table, filter, data) {
  const r = await fetch(`${PROXY_URL}/admin-api/db/${table}?${filter}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (r.status === 401) { showLogin(); return null; }
  const body = await r.json();
  if (!body.success) {
    console.error(`sbUpdate(${table}) failed:`, body);
    return null;
  }
  return body.data;
}

async function sbDelete(table, filter) {
  const r = await fetch(`${PROXY_URL}/admin-api/db/${table}?${filter}`, {
    method: 'DELETE',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
  });
  if (r.status === 401) { showLogin(); return null; }
  const body = await r.json();
  if (!body.success) {
    console.error(`sbDelete(${table}) failed:`, body);
    return null;
  }
  return body.data;
}
// === END DB PROXY ===
/* Proxy fetcher (for /admin-api/*) */
async function proxy(path, opts = {}) {
  const r = await fetch(PROXY_URL + path, {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    ...opts,
  });
  if (r.status === 401) {
    // Сессия истекла — на экран логина
    showLogin();
    return { success: false, error: 'unauthorized' };
  }
  return r.json();
}

/* ===================== AUTH (Telegram) ===================== */
// === TG ADMIN AUTH ===
let _tgLoginToken = null;
let _tgPollTimer = null;
let _tgCountdownTimer = null;
let _tgExpiresAt = null;

async function checkAuth() {
  try {
    const r = await fetch(PROXY_URL + '/admin-api/auth/me', {
      credentials: 'include',
    });
    if (r.status === 200) {
      const data = await r.json();
      if (data.success) return data;
    }
  } catch (e) {}
  return null;
}

async function startTgLogin() {
  hideLoginError();
  try {
    const r = await fetch(PROXY_URL + '/admin-api/auth/start', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
    });
    const data = await r.json();
    if (!data.success) {
      showLoginError(data.error || 'Не удалось начать вход');
      return;
    }
    _tgLoginToken = data.login_token;
    _tgExpiresAt = Date.now() + (data.expires_in_minutes || 10) * 60 * 1000;

    // Переключаем UI
    $('#loginIdle').style.display = 'none';
    $('#loginPending').style.display = 'block';
    const dl = $('#loginDeeplink');
    dl.href = data.deeplink;
    // Открываем deeplink сразу
    window.open(data.deeplink, '_blank');

    // Стартуем polling
    startPollLoop();
    startCountdown();
  } catch (e) {
    showLoginError('Ошибка сети: ' + e.message);
  }
}

function startPollLoop() {
  stopPollLoop();
  _tgPollTimer = setInterval(pollOnce, 2000);
}

function stopPollLoop() {
  if (_tgPollTimer) {
    clearInterval(_tgPollTimer);
    _tgPollTimer = null;
  }
}

async function pollOnce() {
  if (!_tgLoginToken) return;
  try {
    const r = await fetch(PROXY_URL + '/admin-api/auth/poll?token=' + encodeURIComponent(_tgLoginToken), {
      credentials: 'include',
    });
    const data = await r.json();
    if (data.status === 'confirmed') {
      stopPollLoop();
      stopCountdown();
      showApp();
      return;
    }
    if (data.status === 'rejected') {
      stopPollLoop();
      stopCountdown();
      cancelTgLogin();
      showLoginError('Вход отклонён');
      return;
    }
    if (data.status === 'expired' || data.status === 'not_found') {
      stopPollLoop();
      stopCountdown();
      cancelTgLogin();
      showLoginError('Срок ссылки истёк. Попробуйте снова.');
      return;
    }
    // pending — продолжаем
  } catch (e) {
    // молча — следующий поллинг попробует ещё раз
  }
}

function startCountdown() {
  stopCountdown();
  _tgCountdownTimer = setInterval(() => {
    const ms = _tgExpiresAt - Date.now();
    if (ms <= 0) {
      stopCountdown();
      $('#loginCountdown').textContent = '0:00';
      return;
    }
    const sec = Math.floor(ms / 1000);
    const mm = Math.floor(sec / 60);
    const ss = sec % 60;
    $('#loginCountdown').textContent = `${mm}:${String(ss).padStart(2, '0')}`;
  }, 500);
}

function stopCountdown() {
  if (_tgCountdownTimer) {
    clearInterval(_tgCountdownTimer);
    _tgCountdownTimer = null;
  }
}

function cancelTgLogin() {
  stopPollLoop();
  stopCountdown();
  _tgLoginToken = null;
  $('#loginIdle').style.display = 'block';
  $('#loginPending').style.display = 'none';
}

function showLoginError(msg) {
  const el = $('#loginError');
  if (!el) return;
  el.textContent = msg;
  el.style.display = 'block';
}
function hideLoginError() {
  const el = $('#loginError');
  if (el) el.style.display = 'none';
}

async function doLogout() {
  if (!confirm('Выйти из админки?')) return;
  try {
    await fetch(PROXY_URL + '/admin-api/auth/logout', {
      method: 'POST',
      credentials: 'include',
    });
  } catch (e) {}
  location.reload();
}

function showApp() {
  $('#loginScreen').classList.remove('show');
  $('#loginScreen').style.display = 'none';
  $('#app').style.display = 'flex';
  loadAll();
}

function showLogin() {
  $('#loginScreen').style.display = 'flex';
  $('#loginScreen').classList.add('show');
  $('#app').style.display = 'none';
  cancelTgLogin();
}

// === END TG ADMIN AUTH ===

/* ===================== DATA LOAD ===================== */
async function loadAll() {
  try {
    const [users, subs, payments, promos, promoUses, refs, tickets, supportAdmins, campaigns, campaignClicks, userDevices] = await Promise.all([
      sbGet('users', 'select=*&order=created_at.desc'),
      sbGet('subscriptions', 'select=*&order=created_at.desc'),
      sbGet('payments', 'select=*&order=created_at.desc'),
      sbGet('promocodes', 'select=*&order=created_at.desc'),
      sbGet('promocode_uses', 'select=*'),
      sbGet('referrals', 'select=*'),
      sbGet('support_tickets', 'select=*&order=created_at.desc'),
      sbGet('support_admins', 'select=*'),
      sbGet('campaigns', 'select=*&order=created_at.desc'),
      sbGet('campaign_clicks', 'select=*&order=created_at.desc'),
      sbGet('user_devices', 'select=*&is_active=eq.true'),
    ]);
    Object.assign(state, { users, subs, payments, promos, promoUses, refs, tickets, supportAdmins, campaigns, campaignClicks, userDevices, loaded: true });

    // Servers via proxy
    try {
      const srvRes = await proxy('/admin-api/servers');
      state.servers = srvRes.servers || [];
    } catch (e) {
      console.warn('Servers fetch failed:', e);
      state.servers = [];
    }

    renderAll();
    $('#liveDot').textContent = 'обновлено ' + new Date().toLocaleTimeString('ru-RU');
  } catch (e) {
    console.error(e);
    toast('Ошибка загрузки: ' + e.message, 'error');
  }
}

/* ===================== NAVIGATION ===================== */
const PAGE_META = {
  dashboard:  { sec: 'Главное', title: 'Дашборд' },
  users:      { sec: 'Главное', title: 'Пользователи' },
  subs:       { sec: 'Главное', title: 'Подписки' },
  payments:   { sec: 'Главное', title: 'Платежи' },
  promos:     { sec: 'Маркетинг', title: 'Промокоды' },
  marketing:  { sec: 'Маркетинг', title: 'UTM-кампании' },
  referrals:  { sec: 'Маркетинг', title: 'Рефералы' },
  tickets:    { sec: 'Поддержка', title: 'Тикеты' },
  servers:    { sec: 'Инфраструктура', title: 'Серверы' },
  settings:   { sec: 'Инфраструктура', title: 'Настройки' },
};

function goPage(page) {
  if (!PAGE_META[page]) return;
  state.currentPage = page;
  $$('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.page === page));
  $$('.page').forEach(p => p.classList.toggle('active', p.id === 'page-' + page));
  $('#crumbSec').textContent = PAGE_META[page].sec;
  $('#crumbNow').textContent = PAGE_META[page].title;
  // Re-render the active page (cheap, ensures fresh data)
  renderPage(page);
}

function renderPage(page) {
  const fns = {
    dashboard: renderDashboard,
    users: renderUsers,
    subs: renderSubs,
    payments: renderPayments,
    promos: renderPromos,
    marketing: renderMarketing,
    referrals: renderReferrals,
    tickets: renderTickets,
    servers: renderServers,
    settings: renderSettings,
  };
  try { fns[page] && fns[page](); } catch (e) { console.error(`render ${page}:`, e); }
}

function renderAll() {
  renderNavCounts();
  renderPage(state.currentPage);
}

function renderNavCounts() {
  $('#navUsersCount').textContent = state.users.length;
  $('#navSubsCount').textContent = state.subs.filter(s => s.status === 'active').length;
  $('#navPaymentsCount').textContent = state.payments.length;
  $('#navPromosCount').textContent = state.promos.filter(p => p.is_active).length;
  $('#navRefsCount').textContent = state.refs.length;
  $('#navTicketsCount').textContent = state.tickets.filter(t => t.status === 'open' || t.status === 'in_progress').length;
  $('#navServersCount').textContent = state.servers.length;
}

/* ===================== MODAL HELPERS ===================== */
function openModal(id) {
  const m = $('#' + id);
  if (!m) return;
  m.classList.add('open');
  // Focus first input
  setTimeout(() => {
    const inp = m.querySelector('input:not([type=hidden]):not([disabled]), select, textarea');
    if (inp) inp.focus();
  }, 50);
}
function closeModal(id) { $('#' + id).classList.remove('open'); }
function closeAnyModal() {
  $$('.modal-bg.open').forEach(m => m.classList.remove('open'));
  $('#cmdPalette').classList.remove('open');
}

/* ===================== SHEET ===================== */
function closeSheet() {
  $('#sheetBg').classList.remove('open');
  $('#userSheet').classList.remove('open');
}

/* ===================== COMMAND PALETTE ===================== */
function buildCmdItems(query = '') {
  const q = query.toLowerCase().trim();
  const items = [];

  // Static commands
  const staticCmds = [
    { kind: 'action', icon: ICONS.plus, label: 'Выдать подписку', kbd: 'N',
      run: () => { closeAnyModal(); $('#grantUid').value = ''; $('#grantUserHint').textContent = 'Пользователь должен сначала запустить бот.'; openModal('grantModal'); } },
    { kind: 'action', icon: ICONS.gift, label: 'Создать промокод', kbd: 'P',
      run: () => { closeAnyModal(); resetPromoModal(); openModal('promoModal'); } },
    { kind: 'action', icon: ICONS.server, label: 'Добавить сервер',
      run: () => { closeAnyModal(); openServerModal(); } },
    { kind: 'action', icon: ICONS.refresh, label: 'Обновить данные', kbd: 'R',
      run: () => { closeAnyModal(); loadAll(); toast('Обновляем...'); } },
  ];

  // Pages
  const pageCmds = Object.entries(PAGE_META).map(([key, meta]) => ({
    kind: 'page', icon: ICONS.arrowRight, label: `Перейти: ${meta.title}`,
    run: () => { closeAnyModal(); goPage(key); },
  }));

  // Users (filtered)
  let userCmds = [];
  if (q.length >= 2) {
    userCmds = state.users
      .filter(u => {
        const hay = [u.username, u.first_name, u.last_name, u.user_id].filter(Boolean).join(' ').toLowerCase();
        return hay.includes(q);
      })
      .slice(0, 8)
      .map(u => ({
        kind: 'user',
        iconHtml: avaHtml(u),
        label: displayName(u),
        sub: 'id:' + u.user_id,
        run: () => { closeAnyModal(); openUserSheet(u.user_id); },
      }));
  }

  // Build sections
  const filtered = (arr) => arr.filter(c => !q || c.label.toLowerCase().includes(q));

  return { actions: filtered(staticCmds), pages: filtered(pageCmds), users: userCmds };
}

function renderCmdList() {
  const q = $('#cmdInput').value;
  const groups = buildCmdItems(q);
  const allItems = [...groups.actions, ...groups.pages, ...groups.users];
  state.cmdItems = allItems;

  const list = $('#cmdList');
  if (!allItems.length) {
    list.innerHTML = '<div class="cmd-empty">Ничего не найдено</div>';
    return;
  }

  let html = '';
  if (groups.actions.length) {
    html += '<div class="cmd-section">Действия</div>';
    groups.actions.forEach((c, i) => html += cmdItemHtml(c, allItems.indexOf(c)));
  }
  if (groups.pages.length) {
    html += '<div class="cmd-section">Страницы</div>';
    groups.pages.forEach((c) => html += cmdItemHtml(c, allItems.indexOf(c)));
  }
  if (groups.users.length) {
    html += '<div class="cmd-section">Пользователи</div>';
    groups.users.forEach((c) => html += cmdItemHtml(c, allItems.indexOf(c)));
  }
  list.innerHTML = html;

  if (state.cmdActiveIdx >= allItems.length) state.cmdActiveIdx = 0;
  highlightCmdActive();
  // Click handlers
  $$('.cmd-item', list).forEach((el, idx) => {
    el.addEventListener('mouseenter', () => { state.cmdActiveIdx = Number(el.dataset.idx); highlightCmdActive(); });
    el.addEventListener('click', () => {
      const i = Number(el.dataset.idx);
      if (state.cmdItems[i]) state.cmdItems[i].run();
    });
  });
}

function cmdItemHtml(c, idx) {
  const ico = c.iconHtml ? c.iconHtml : `<span class="ico">${c.icon || ''}</span>`;
  const sub = c.sub ? `<span class="muted" style="font-size:11px;margin-left:6px">${esc(c.sub)}</span>` : '';
  const kbd = c.kbd ? `<span class="kbd">${c.kbd}</span>` : '';
  return `<div class="cmd-item" data-idx="${idx}">${ico}<span class="label">${esc(c.label)}${sub}</span>${kbd}</div>`;
}

function highlightCmdActive() {
  $$('.cmd-item').forEach(el => el.classList.toggle('active', Number(el.dataset.idx) === state.cmdActiveIdx));
  const active = $('.cmd-item.active');
  if (active) active.scrollIntoView({ block: 'nearest' });
}

function openCmd() {
  $('#cmdPalette').classList.add('open');
  $('#cmdInput').value = '';
  state.cmdActiveIdx = 0;
  renderCmdList();
  setTimeout(() => $('#cmdInput').focus(), 50);
}
function closeCmd() { $('#cmdPalette').classList.remove('open'); }

/* ===================== KEYBOARD ===================== */
function bindShortcuts() {
  document.addEventListener('keydown', (e) => {
    const target = e.target;
    const inField = target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable);

    // Cmd+K / Ctrl+K — open palette
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      openCmd();
      return;
    }

    // ESC — close everything
    if (e.key === 'Escape') {
      if ($('#cmdPalette').classList.contains('open')) { closeCmd(); return; }
      if ($('#userSheet').classList.contains('open')) { closeSheet(); return; }
      const openModalEl = $('.modal-bg.open');
      if (openModalEl) { openModalEl.classList.remove('open'); return; }
    }

    // Inside cmd palette
    if ($('#cmdPalette').classList.contains('open')) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (state.cmdActiveIdx < state.cmdItems.length - 1) state.cmdActiveIdx++;
        highlightCmdActive();
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (state.cmdActiveIdx > 0) state.cmdActiveIdx--;
        highlightCmdActive();
        return;
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        const c = state.cmdItems[state.cmdActiveIdx];
        if (c) c.run();
        return;
      }
      return;
    }

    // Skip if typing in a field
    if (inField) return;

    // "/" — focus first .search input on current page
    if (e.key === '/') {
      const s = $('.page.active .search input');
      if (s) { e.preventDefault(); s.focus(); }
      return;
    }

    // R — reload
    if (e.key.toLowerCase() === 'r' && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      loadAll();
      toast('Обновляем...', 'success', { duration: 1500 });
      return;
    }

    // N — new (context-aware: на promos -> создать промо; иначе -> выдать подписку)
    if (e.key.toLowerCase() === 'n') {
      e.preventDefault();
      if (state.currentPage === 'promos') { resetPromoModal(); openModal('promoModal'); }
      else if (state.currentPage === 'servers') openServerModal();
      else { $('#grantUid').value = ''; openModal('grantModal'); }
      return;
    }

    // G prefix — go-to
    if (e.key.toLowerCase() === 'g') {
      state.keySeq = 'g';
      clearTimeout(state.keySeqTimer);
      state.keySeqTimer = setTimeout(() => state.keySeq = '', 1200);
      return;
    }

    if (state.keySeq === 'g') {
      const map = { d: 'dashboard', u: 'users', s: 'subs', p: 'payments', m: 'marketing', o: 'promos', r: 'referrals', t: 'tickets', v: 'servers', x: 'settings' };
      const tgt = map[e.key.toLowerCase()];
      if (tgt) {
        e.preventDefault();
        goPage(tgt);
      }
      state.keySeq = '';
      return;
    }
  });
}

/* ===================== MODAL BACKDROP CLICKS & CLOSE BUTTONS ===================== */
function bindModalClicks() {
  $$('.modal-bg').forEach(bg => {
    bg.addEventListener('click', (e) => { if (e.target === bg) bg.classList.remove('open'); });
  });
  document.addEventListener('click', (e) => {
    const closeBtn = e.target.closest('[data-close]');
    if (closeBtn) {
      const bg = closeBtn.closest('.modal-bg');
      if (bg) bg.classList.remove('open');
    }
  });
  $('#sheetClose').addEventListener('click', closeSheet);
  $('#sheetBg').addEventListener('click', closeSheet);
}

/* ===================== SPARKLINE (mini chart) ===================== */
function sparkline(svg, values, color = '#5b8def') {
  if (!values.length) return;
  const w = 60, h = 22;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = max - min || 1;
  const step = w / Math.max(values.length - 1, 1);
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(h - ((v - min) / range) * h).toFixed(1)}`).join(' ');
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.innerHTML = `
    <defs>
      <linearGradient id="sg-${Math.random().toString(36).slice(2, 7)}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${color}" stop-opacity=".4"/>
        <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
      </linearGradient>
    </defs>
    <polyline fill="none" stroke="${color}" stroke-width="1.5" points="${pts}"/>
  `;
}

/* ===================== BOOT ===================== */
document.addEventListener('DOMContentLoaded', () => {
  // Login
  const ltb = $('#loginTgBtn'); if (ltb) ltb.addEventListener('click', startTgLogin);
  const lcb = $('#loginCancelBtn'); if (lcb) lcb.addEventListener('click', cancelTgLogin);

  // Sidebar nav
  $$('.nav-item').forEach(n => n.addEventListener('click', () => goPage(n.dataset.page)));

  // Top actions
  $('#reloadBtn').addEventListener('click', () => { loadAll(); toast('Обновляем...', 'success', { duration: 1500 }); });
  $('#logoutBtn').addEventListener('click', doLogout);
  $('#quickGrantBtn').addEventListener('click', () => { $('#grantUid').value = ''; $('#grantUserHint').textContent = 'Пользователь должен сначала запустить бот.'; openModal('grantModal'); });
  $('#cmdTrigger').addEventListener('click', openCmd);

  // Cmd palette
  $('#cmdInput').addEventListener('input', renderCmdList);

  // Modals
  bindModalClicks();
  bindShortcuts();

  // Grant modal handlers
  $('#grantSubmit').addEventListener('click', grantSubscription);

  // Promo modal handlers
  $('#promoGenBtn').addEventListener('click', genPromoCode);
  $('#promoType').addEventListener('change', updatePromoHelp);
  $('#promoSubmit').addEventListener('click', savePromo);

  // Bonus modal
  $('#bonusSubmit').addEventListener('click', grantBonusDays);

  // Server modal
  $('#serverSubmit').addEventListener('click', saveServer);
  $('#srvDeleteBtn').addEventListener('click', deleteServerFromModal);

  // Campaign modal
  $('#campaignSubmit').addEventListener('click', saveCampaign);

  // Boot
  checkAuth().then(s => { if (s) showApp(); else showLogin(); });
});

/* =====================================================================
   ====================== PAGE: DASHBOARD ============================
   ===================================================================== */
function renderDashboard() {
  const now = Date.now();
  const dayMs = 86400000;
  const succeeded = state.payments.filter(p => p.status === 'succeeded');
  const succeeded30d = succeeded.filter(p => (now - new Date(p.paid_at || p.created_at)) < 30 * dayMs);
  const succeeded30dPrev = succeeded.filter(p => {
    const t = new Date(p.paid_at || p.created_at).getTime();
    return (now - t) >= 30 * dayMs && (now - t) < 60 * dayMs;
  });
  const revenue30d = succeeded30d.reduce((s, p) => s + Number(p.amount || 0), 0);
  const revenue30dPrev = succeeded30dPrev.reduce((s, p) => s + Number(p.amount || 0), 0);
  const revenueDelta = revenue30dPrev > 0 ? Math.round((revenue30d - revenue30dPrev) / revenue30dPrev * 100) : null;

  const receiptPending = succeeded.filter(p => p.receipt_status !== 'registered' && p.receipt_status !== 'not_required').length;
  const activeSubs = state.subs.filter(s => s.status === 'active' && new Date(s.expires_at) > new Date()).length;

  const users30d = state.users.filter(u => (now - new Date(u.created_at)) < 30 * dayMs).length;
  const users30dPrev = state.users.filter(u => {
    const t = new Date(u.created_at).getTime();
    return (now - t) >= 30 * dayMs && (now - t) < 60 * dayMs;
  }).length;
  const usersDelta = users30dPrev > 0 ? Math.round((users30d - users30dPrev) / users30dPrev * 100) : null;

  // 7-day sparkline data
  const sparkRev = []; const sparkUsers = []; const sparkPay = []; const sparkSubs = [];
  for (let i = 6; i >= 0; i--) {
    const dStart = new Date(); dStart.setHours(0,0,0,0); dStart.setDate(dStart.getDate() - i);
    const dEnd = new Date(dStart); dEnd.setHours(23,59,59,999);
    sparkRev.push(state.payments.filter(p => p.status === 'succeeded' && new Date(p.paid_at || p.created_at) >= dStart && new Date(p.paid_at || p.created_at) <= dEnd).reduce((s, p) => s + Number(p.amount || 0), 0));
    sparkUsers.push(state.users.filter(u => new Date(u.created_at) >= dStart && new Date(u.created_at) <= dEnd).length);
    sparkPay.push(state.payments.filter(p => new Date(p.created_at) >= dStart && new Date(p.created_at) <= dEnd).length);
    sparkSubs.push(state.subs.filter(s => new Date(s.created_at) >= dStart && new Date(s.created_at) <= dEnd).length);
  }

  // Expiring soon
  const expiring = state.subs
    .filter(s => s.status === 'active')
    .map(s => ({ ...s, dl: daysLeft(s.expires_at) }))
    .filter(s => s.dl >= 0 && s.dl <= 3)
    .sort((a, b) => a.dl - b.dl);

  // Recent payments
  const recent = state.payments.slice(0, 6);

  // Open tickets
  const openTickets = state.tickets.filter(t => t.status === 'open' || t.status === 'in_progress').slice(0, 6);

  $('#page-dashboard').innerHTML = `
    <div class="page-title">Дашборд</div>
    <div class="page-sub">Общая картина по системе TuVPN</div>

    <div class="kpi-grid">
      <div class="kpi">
        <div class="kpi-head"><span class="kpi-label">Пользователи</span><span class="kpi-ico">${ICONS.activity}</span></div>
        <div class="kpi-value num">${num(state.users.length)}</div>
        <div class="kpi-foot">
          <span class="kpi-delta ${usersDelta == null ? 'flat' : usersDelta >= 0 ? 'up' : 'dn'}">${usersDelta == null ? '+' + users30d : (usersDelta >= 0 ? '↑' : '↓') + ' ' + Math.abs(usersDelta) + '%'}</span>
          <svg class="kpi-spark" id="sparkUsers"></svg>
        </div>
      </div>
      <div class="kpi">
        <div class="kpi-head"><span class="kpi-label">Активных подписок</span><span class="kpi-ico">${ICONS.calendar}</span></div>
        <div class="kpi-value num">${num(activeSubs)}</div>
        <div class="kpi-foot">
          <span class="kpi-delta flat">${expiring.length} истекают за 3 дн</span>
          <svg class="kpi-spark" id="sparkSubs"></svg>
        </div>
      </div>
      <div class="kpi">
        <div class="kpi-head"><span class="kpi-label">Доход за 30 дней</span><span class="kpi-ico">${ICONS.zap}</span></div>
        <div class="kpi-value num">${money(revenue30d)}</div>
        <div class="kpi-foot">
          <span class="kpi-delta ${revenueDelta == null ? 'flat' : revenueDelta >= 0 ? 'up' : 'dn'}">${revenueDelta == null ? '—' : (revenueDelta >= 0 ? '↑' : '↓') + ' ' + Math.abs(revenueDelta) + '%'}</span>
          <svg class="kpi-spark" id="sparkRev"></svg>
        </div>
      </div>
      <div class="kpi">
        <div class="kpi-head"><span class="kpi-label">Чеков оформить</span><span class="kpi-ico">${ICONS.check}</span></div>
        <div class="kpi-value num">${num(receiptPending)}</div>
        <div class="kpi-foot">
          <span class="kpi-delta ${receiptPending > 0 ? 'dn' : 'flat'}">${receiptPending > 0 ? 'в Мой Налог' : 'всё оформлено'}</span>
          <svg class="kpi-spark" id="sparkPay"></svg>
        </div>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-head">
          <div>
            <div class="card-title">Доход за 30 дней</div>
            <div class="card-sub" id="chartSubtitle">— ₽ итого</div>
          </div>
          <div class="seg">
            <button class="on" data-chart="revenue">Доход</button>
            <button data-chart="payments">Платежи</button>
            <button data-chart="users">Регистрации</button>
          </div>
        </div>
        <div class="card-pad" style="padding:14px 16px 6px">
          <div style="height:260px; position:relative"><canvas id="mainChart"></canvas></div>
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          <div class="card-title">Истекают за 3 дня</div>
          <span class="card-sub">${expiring.length} шт</span>
        </div>
        <div class="card-pad" style="padding:8px 8px">
          <div class="lst" id="expiringList">
            ${!expiring.length ? '<div class="empty"><span class="emoji">✓</span><div class="title">Никто не истекает</div><div class="sub">Напомним когда что-то изменится</div></div>'
              : expiring.slice(0, 8).map(s => {
                const u = userById(s.user_id);
                const cls = s.dl <= 1 ? 'red' : 'yellow';
                return `<div class="lst-row" data-uid="${s.user_id}">
                  <div class="lst-ico ${cls}">${ICONS.calendar}</div>
                  <div class="lst-main">
                    <div class="lst-title">${esc(displayName(u))}</div>
                    <div class="lst-sub">${s.devices} уст · до ${fmtDate(s.expires_at)}</div>
                  </div>
                  <div class="lst-end" style="color:var(--${cls === 'red' ? 'red' : 'yellow'})">${s.dl} дн</div>
                </div>`;
              }).join('')}
          </div>
        </div>
      </div>
    </div>

    <div class="grid-1-1">
      <div class="card">
        <div class="card-head">
          <div class="card-title">Последние платежи</div>
          <button class="btn btn-ghost btn-sm" id="goPayments">Все →</button>
        </div>
        <div class="card-pad" style="padding:8px 8px">
          <div class="lst">
            ${!recent.length ? '<div class="empty"><span class="emoji">💸</span><div class="title">Платежей пока нет</div></div>'
              : recent.map(p => {
                const u = userById(p.user_id);
                const cls = p.status === 'succeeded' ? 'green' : p.status === 'pending' ? 'yellow' : 'red';
                const ico = p.status === 'succeeded' ? '✓' : p.status === 'pending' ? '⏳' : '✕';
                return `<div class="lst-row" data-uid="${p.user_id}">
                  <div class="lst-ico ${cls}">${ico}</div>
                  <div class="lst-main">
                    <div class="lst-title">${esc(displayName(u))} · ${p.months || '?'} мес / ${p.devices || '?'} уст</div>
                    <div class="lst-sub">${fmtTimeAgo(p.created_at)} · ${esc(p.email || '—')}</div>
                  </div>
                  <div class="lst-end">${money(p.amount)}</div>
                </div>`;
              }).join('')}
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          <div class="card-title">Открытые тикеты</div>
          <button class="btn btn-ghost btn-sm" id="goTickets">Все →</button>
        </div>
        <div class="card-pad" style="padding:8px 8px">
          <div class="lst">
            ${!openTickets.length ? '<div class="empty"><span class="emoji">✓</span><div class="title">Открытых тикетов нет</div></div>'
              : openTickets.map(t => {
                const u = { user_id: t.user_id, username: t.username, first_name: t.first_name };
                const cls = t.status === 'open' ? 'yellow' : 'blue';
                return `<div class="lst-row" data-uid="${t.user_id}">
                  <div class="lst-ico ${cls}">💬</div>
                  <div class="lst-main">
                    <div class="lst-title">${esc(displayName(u))} · #${t.id}</div>
                    <div class="lst-sub">${esc((t.subject || '').slice(0, 50))}</div>
                  </div>
                  <div class="lst-end"><span class="tag tag-${cls}">${t.status === 'open' ? 'open' : 'work'}</span></div>
                </div>`;
              }).join('')}
          </div>
        </div>
      </div>
    </div>
  `;

  // Sparklines
  sparkline($('#sparkUsers'), sparkUsers, '#5b8def');
  sparkline($('#sparkSubs'), sparkSubs, '#4ade80');
  sparkline($('#sparkRev'), sparkRev, '#c084fc');
  sparkline($('#sparkPay'), sparkPay, '#facc15');

  // Chart
  renderMainChart('revenue');

  // Event bindings
  $$('#page-dashboard .seg button').forEach(b => b.addEventListener('click', () => {
    $$('#page-dashboard .seg button').forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    renderMainChart(b.dataset.chart);
  }));
  $$('#page-dashboard .lst-row[data-uid]').forEach(r => r.addEventListener('click', () => openUserSheet(r.dataset.uid)));
  $('#goPayments').addEventListener('click', () => goPage('payments'));
  $('#goTickets').addEventListener('click', () => goPage('tickets'));
}

function renderMainChart(kind) {
  state.currentChart = kind;
  const labels = []; const data = [];
  const dayMs = 86400000;
  const today = new Date(); today.setHours(23,59,59,999);

  for (let i = 29; i >= 0; i--) {
    const d = new Date(today.getTime() - i * dayMs);
    labels.push(d.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' }));
    const dStart = new Date(d); dStart.setHours(0,0,0,0);
    const dEnd = new Date(d); dEnd.setHours(23,59,59,999);
    let v = 0;
    if (kind === 'revenue') {
      v = state.payments.filter(p => p.status === 'succeeded')
        .filter(p => { const t = new Date(p.paid_at || p.created_at); return t >= dStart && t <= dEnd; })
        .reduce((s, p) => s + Number(p.amount || 0), 0);
    } else if (kind === 'payments') {
      v = state.payments.filter(p => { const t = new Date(p.created_at); return t >= dStart && t <= dEnd; }).length;
    } else {
      v = state.users.filter(u => { const t = new Date(u.created_at); return t >= dStart && t <= dEnd; }).length;
    }
    data.push(v);
  }

  const total = data.reduce((s, v) => s + v, 0);
  $('#chartSubtitle').textContent = kind === 'revenue'
    ? money(total) + ' итого'
    : kind === 'payments' ? num(total) + ' платежей' : num(total) + ' регистраций';

  if (state.chartInstance) state.chartInstance.destroy();
  const canvas = $('#mainChart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const color = kind === 'revenue' ? '#5b8def' : kind === 'payments' ? '#67e8f9' : '#c084fc';
  const grad = ctx.createLinearGradient(0, 0, 0, 260);
  grad.addColorStop(0, color + '40');
  grad.addColorStop(1, color + '00');

  state.chartInstance = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [{
      data, fill: true, backgroundColor: grad, borderColor: color, borderWidth: 1.8,
      pointRadius: 0, pointHoverRadius: 4, pointHoverBackgroundColor: color,
      pointHoverBorderColor: '#fff', pointHoverBorderWidth: 1.5, tension: .35,
    }]},
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#12141c', borderColor: '#2a2f42', borderWidth: 1, padding: 8,
          titleColor: '#f0f2f7', bodyColor: '#b4b9c8',
          titleFont: { family: 'Geist Mono', size: 11 },
          bodyFont: { family: 'Geist', size: 12, weight: 600 },
          callbacks: { label: ctx => kind === 'revenue' ? money(ctx.parsed.y) : num(ctx.parsed.y) },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: '#4a4f60', font: { family: 'Geist Mono', size: 10 }, maxRotation: 0, autoSkipPadding: 30 }},
        y: { grid: { color: '#1e2230', drawBorder: false }, ticks: { color: '#4a4f60', font: { family: 'Geist Mono', size: 10 }, callback: v => kind === 'revenue' ? (v >= 1000 ? (v/1000)+'k' : v) : v }},
      },
    },
  });
}

/* =====================================================================
   ====================== PAGE: USERS ============================
   ===================================================================== */
function renderUsers() {
  $('#page-users').innerHTML = `
    <div class="page-title">Пользователи</div>
    <div class="page-sub">Все, кто запустил бот</div>

    <div class="toolbar">
      <div class="search">
        <svg class="ico" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.35-4.35"/></svg>
        <input id="usersSearch" placeholder="Поиск по имени, username, ID..." />
      </div>
      <select class="filter" id="usersFilter">
        <option value="all">Все</option>
        <option value="active">С активной подпиской</option>
        <option value="none">Без подписки</option>
        <option value="referred">Пришли по реф.ссылке</option>
        <option value="bonus">С бонусными днями</option>
      </select>
      <div class="toolbar-grow"></div>
      <span class="counter" id="usersCounter">—</span>
    </div>

    <div class="card">
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr>
            <th>Пользователь</th><th>Telegram ID</th><th>Подписка</th><th>Истекает</th>
            <th>Уст.</th><th>Бонус</th><th>Регистрация</th><th class="text-r"></th>
          </tr></thead>
          <tbody id="usersTbody"><tr><td colspan="8"><div class="empty"><div class="title">Загрузка...</div></div></td></tr></tbody>
        </table>
      </div>
    </div>
  `;
  $('#usersSearch').addEventListener('input', renderUsersTable);
  $('#usersFilter').addEventListener('change', renderUsersTable);
  renderUsersTable();
}

function renderUsersTable() {
  const filter = $('#usersFilter').value;
  const search = ($('#usersSearch').value || '').toLowerCase().trim();
  let users = state.users.slice();

  users = users.filter(u => {
    if (filter === 'active') return state.subs.some(s => Number(s.user_id) === Number(u.user_id) && s.status === 'active' && new Date(s.expires_at) > new Date());
    if (filter === 'none') return !state.subs.some(s => Number(s.user_id) === Number(u.user_id) && s.status === 'active');
    if (filter === 'referred') return u.referrer_id != null;
    if (filter === 'bonus') return (u.bonus_days || 0) > 0;
    return true;
  });
  if (search) {
    users = users.filter(u => {
      const hay = [u.username, u.first_name, u.last_name, u.user_id].filter(Boolean).join(' ').toLowerCase();
      return hay.includes(search);
    });
  }

  $('#usersCounter').textContent = users.length + ' из ' + state.users.length;
  const tbody = $('#usersTbody');
  if (!users.length) {
    tbody.innerHTML = '<tr><td colspan="8"><div class="empty"><span class="emoji">🔍</span><div class="title">Ничего не найдено</div></div></td></tr>';
    return;
  }
  tbody.innerHTML = users.map(u => {
    const sub = activeSubFor(u.user_id);
    const dl = sub ? daysLeft(sub.expires_at) : null;
    const subStatus = sub
      ? (dl > 0 ? `<span class="tag tag-green dot">актив.</span>` : `<span class="tag tag-red dot">истёк</span>`)
      : `<span class="tag tag-gray dot">нет</span>`;
    const dlCell = sub
      ? (dl > 0 ? `<span class="mono">${fmtDate(sub.expires_at)}</span> <span class="muted">(${dl} дн)</span>` : '<span class="muted">—</span>')
      : '<span class="muted">—</span>';
    return `<tr class="clickable" data-uid="${u.user_id}">
      <td><div class="u-cell">${avaHtml(u)}<div><div class="u-name">${esc(displayName(u))}</div><div class="u-handle">${esc([u.first_name, u.last_name].filter(Boolean).join(' ') || '')}</div></div></div></td>
      <td><span class="mono">${u.user_id}</span></td>
      <td>${subStatus}</td>
      <td>${dlCell}</td>
      <td>${sub ? `<span class="tag tag-blue">${sub.devices}</span>` : '<span class="muted">—</span>'}</td>
      <td>${(u.bonus_days || 0) > 0 ? `<span class="tag tag-purple">+${u.bonus_days}</span>` : '<span class="muted">0</span>'}</td>
      <td><span class="mono">${fmtDate(u.created_at)}</span></td>
      <td><div class="row-acts">
        <button class="btn btn-ghost btn-sm" data-act="grant" title="Выдать/продлить">${ICONS.calendar}</button>
        <button class="btn btn-ghost btn-sm" data-act="bonus" title="Бонусные дни">${ICONS.gift}</button>
      </div></td>
    </tr>`;
  }).join('');

  $$('#usersTbody tr.clickable').forEach(r => {
    r.addEventListener('click', e => {
      if (e.target.closest('button')) return;
      openUserSheet(r.dataset.uid);
    });
  });
  $$('#usersTbody [data-act]').forEach(b => b.addEventListener('click', e => {
    e.stopPropagation();
    const uid = b.closest('tr').dataset.uid;
    if (b.dataset.act === 'grant') quickGrant(uid);
    if (b.dataset.act === 'bonus') openBonusModal(uid);
  }));
}

/* =====================================================================
   ====================== USER SHEET ============================
   ===================================================================== */
function openUserSheet(uid) {
  const u = userById(uid);
  if (!u) { toast('Пользователь не найден', 'error'); return; }

  $('#sheetAva').style.background = avaColor(uid);
  $('#sheetAva').textContent = avaInitial(u);
  $('#sheetName').textContent = displayName(u);
  $('#sheetIdLine').textContent = `id ${u.user_id} · ${fmtDateTime(u.created_at)}`;

  const sub = activeSubFor(uid);
  const userSubs = state.subs.filter(s => Number(s.user_id) === Number(uid)).sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  const userPays = state.payments.filter(p => Number(p.user_id) === Number(uid)).sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  const totalSpent = userPays.filter(p => p.status === 'succeeded').reduce((s, p) => s + Number(p.amount || 0), 0);
  const referrer = u.referrer_id ? userById(u.referrer_id) : null;
  const broughtIn = state.users.filter(x => Number(x.referrer_id) === Number(uid));
  const broughtPaid = broughtIn.filter(x => state.payments.some(p => Number(p.user_id) === Number(x.user_id) && p.status === 'succeeded')).length;
  const tickets = state.tickets.filter(t => Number(t.user_id) === Number(uid));

  $('#sheetBody').innerHTML = `
    <div class="sh-sec">
      <div class="sh-sec-title">Сводка</div>
      <div class="info"><span class="info-k">Username</span><span class="info-v">${u.username ? '@' + esc(u.username) : '—'}</span></div>
      <div class="info"><span class="info-k">Имя</span><span class="info-v">${esc([u.first_name, u.last_name].filter(Boolean).join(' ') || '—')}</span></div>
      <div class="info"><span class="info-k">Telegram ID</span><span class="info-v mono">${u.user_id}</span></div>
      <div class="info"><span class="info-k">Регистрация</span><span class="info-v">${fmtDateTime(u.created_at)}</span></div>
      <div class="info"><span class="info-k">Бонусных дней</span><span class="info-v num">${u.bonus_days || 0}</span></div>
      <div class="info"><span class="info-k">Потратил всего</span><span class="info-v num">${money(totalSpent)}</span></div>
    </div>

    <div class="sh-sec">
      <div class="sh-sec-title">Активная подписка</div>
      ${sub ? `
        <div class="info"><span class="info-k">Тариф</span><span class="info-v">${sub.devices} уст.</span></div>
        <div class="info"><span class="info-k">Старт</span><span class="info-v">${fmtDateTime(sub.started_at)}</span></div>
        <div class="info"><span class="info-k">Истекает</span><span class="info-v">${fmtDateTime(sub.expires_at)} <span class="muted">(${daysLeft(sub.expires_at)} дн)</span></span></div>
        <div class="info"><span class="info-k">Ссылка</span><span class="info-v mono" style="font-size:11px">…${esc((sub.sub_url || '').slice(-32))}</span></div>
      ` : '<div class="empty" style="padding:18px 0"><div class="title" style="font-size:13px">Активной подписки нет</div></div>'}
      <div class="flex gap-2 mt-3">
        <button class="btn btn-success btn-sm" id="sheetGrant">${ICONS.calendar} Выдать/продлить</button>
        <button class="btn btn-ghost btn-sm" id="sheetBonus">${ICONS.gift} Бонусные дни</button>
        ${sub ? `<button class="btn btn-danger btn-sm" id="sheetRevoke">${ICONS.close} Отозвать</button>` : ''}
      </div>
    </div>

    <div class="sh-sec">
      <div class="sh-sec-title">Рефералы</div>
      <div class="info"><span class="info-k">Кто пригласил</span><span class="info-v">${referrer ? esc(displayName(referrer)) : '—'}</span></div>
      <div class="info"><span class="info-k">Привёл</span><span class="info-v num">${broughtIn.length} (оплатили: ${broughtPaid})</span></div>
      <div class="info"><span class="info-k">Реф.ссылка</span><span class="info-v mono" style="font-size:11px">t.me/MaxArtVPN_bot?start=${uid}</span></div>
    </div>

    ${userPays.length ? `
    <div class="sh-sec">
      <div class="sh-sec-title">История платежей · ${userPays.length}</div>
      <div class="lst">
        ${userPays.slice(0, 10).map(p => `
          <div class="lst-row">
            <div class="lst-ico ${p.status === 'succeeded' ? 'green' : p.status === 'pending' ? 'yellow' : 'red'}">${p.status === 'succeeded' ? '✓' : p.status === 'pending' ? '⏳' : '✕'}</div>
            <div class="lst-main">
              <div class="lst-title">${money(p.amount)} · ${p.months || '?'} мес / ${p.devices || '?'} уст</div>
              <div class="lst-sub">${fmtDateTime(p.created_at)}</div>
            </div>
            <div class="lst-end"><span class="tag tag-${p.status === 'succeeded' ? 'green' : p.status === 'pending' ? 'yellow' : 'red'}">${p.status}</span></div>
          </div>
        `).join('')}
      </div>
    </div>` : ''}

    ${tickets.length ? `
    <div class="sh-sec">
      <div class="sh-sec-title">Тикеты · ${tickets.length}</div>
      <div class="lst">
        ${tickets.slice(0, 5).map(t => `
          <div class="lst-row">
            <div class="lst-ico ${t.status === 'closed' ? 'green' : t.status === 'in_progress' ? 'blue' : 'yellow'}">💬</div>
            <div class="lst-main">
              <div class="lst-title">#${t.id} · ${esc((t.subject || '').slice(0, 40))}</div>
              <div class="lst-sub">${fmtDateTime(t.created_at)}</div>
            </div>
            <div class="lst-end"><span class="tag tag-${t.status === 'closed' ? 'green' : t.status === 'in_progress' ? 'blue' : 'yellow'}">${t.status}</span></div>
          </div>
        `).join('')}
      </div>
    </div>` : ''}
  `;

  $('#sheetBg').classList.add('open');
  $('#userSheet').classList.add('open');

  // Bind sheet buttons
  const grantBtn = $('#sheetGrant'); if (grantBtn) grantBtn.addEventListener('click', () => quickGrant(uid));
  const bonusBtn = $('#sheetBonus'); if (bonusBtn) bonusBtn.addEventListener('click', () => openBonusModal(uid));
  const revokeBtn = $('#sheetRevoke'); if (revokeBtn) revokeBtn.addEventListener('click', () => revokeSub(sub.id));
}

/* =====================================================================
   ====================== PAGE: SUBSCRIPTIONS ============================
   ===================================================================== */
function renderSubs() {
  $('#page-subs').innerHTML = `
    <div class="page-title">Подписки</div>
    <div class="page-sub">Активные и истёкшие подписки</div>

    <div class="toolbar">
      <select class="filter" id="subsFilter">
        <option value="active">Активные</option>
        <option value="expiring">Истекают за 3 дня</option>
        <option value="expired">Истёкшие</option>
        <option value="all">Все</option>
      </select>
      <select class="filter" id="subsDevFilter">
        <option value="all">Все тарифы</option>
        <option value="1">1 устройство</option>
        <option value="2">2 устройства</option>
        <option value="5">5 устройств</option>
      </select>
      <div class="toolbar-grow"></div>
      <span class="counter" id="subsCounter">—</span>
    </div>

    <div class="card">
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr>
            <th>Пользователь</th><th>Тариф</th><th>Старт</th><th>Истекает</th>
            <th>Осталось</th><th>Статус</th><th class="text-r"></th>
          </tr></thead>
          <tbody id="subsTbody"></tbody>
        </table>
      </div>
    </div>
  `;
  $('#subsFilter').addEventListener('change', renderSubsTable);
  $('#subsDevFilter').addEventListener('change', renderSubsTable);
  renderSubsTable();
}

function renderSubsTable() {
  const f = $('#subsFilter').value;
  const dev = $('#subsDevFilter').value;
  let subs = state.subs.slice();
  const now = new Date();
  if (f === 'active') subs = subs.filter(s => s.status === 'active' && new Date(s.expires_at) > now);
  else if (f === 'expiring') subs = subs.filter(s => s.status === 'active' && daysLeft(s.expires_at) >= 0 && daysLeft(s.expires_at) <= 3);
  else if (f === 'expired') subs = subs.filter(s => s.status !== 'active' || new Date(s.expires_at) <= now);
  if (dev !== 'all') subs = subs.filter(s => Number(s.devices) === Number(dev));
  subs.sort((a, b) => new Date(a.expires_at) - new Date(b.expires_at));

  $('#subsCounter').textContent = subs.length + ' шт';
  const tbody = $('#subsTbody');
  if (!subs.length) {
    tbody.innerHTML = '<tr><td colspan="7"><div class="empty"><span class="emoji">📭</span><div class="title">Подписок нет</div></div></td></tr>';
    return;
  }
  tbody.innerHTML = subs.map(s => {
    const u = userById(s.user_id);
    const dl = daysLeft(s.expires_at);
    const isActive = s.status === 'active' && dl > 0;
    const dlClass = dl <= 1 ? 'red' : dl <= 3 ? 'yellow' : '';
    return `<tr class="clickable" data-uid="${s.user_id}">
      <td><div class="u-cell">${avaHtml(u)}<div class="u-name">${esc(displayName(u))}</div></div></td>
      <td><span class="tag tag-blue">${s.devices} уст</span></td>
      <td><span class="mono">${fmtDate(s.started_at)}</span></td>
      <td><span class="mono">${fmtDate(s.expires_at)}</span></td>
      <td><span class="num" style="${dlClass ? 'color:var(--' + dlClass + ');font-weight:700' : ''}">${dl > 0 ? dl + ' дн' : 'истекло'}</span></td>
      <td><span class="tag tag-${isActive ? 'green' : 'red'} dot">${isActive ? 'актив' : 'неакт'}</span></td>
      <td><div class="row-acts">
        <button class="btn btn-ghost btn-sm" data-act="grant">Продлить</button>
        ${isActive ? `<button class="btn btn-danger btn-sm" data-act="revoke" data-sid="${s.id}">${ICONS.close}</button>` : ''}
      </div></td>
    </tr>`;
  }).join('');

  $$('#subsTbody tr.clickable').forEach(r => {
    r.addEventListener('click', e => {
      if (e.target.closest('button')) return;
      openUserSheet(r.dataset.uid);
    });
  });
  $$('#subsTbody [data-act="grant"]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); quickGrant(b.closest('tr').dataset.uid); }));
  $$('#subsTbody [data-act="revoke"]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); revokeSub(Number(b.dataset.sid)); }));
}


/* =====================================================================
   ====================== PAGE: PAYMENTS ============================
   ===================================================================== */
function renderPayments() {
  const all = state.payments;
  const succeeded = all.filter(p => p.status === 'succeeded');
  const succSum = succeeded.reduce((s, p) => s + Number(p.amount || 0), 0);
  const pending = all.filter(p => p.status === 'pending').length;
  const canceled = all.filter(p => p.status === 'canceled' || p.status === 'failed').length;
  const receiptPending = succeeded.filter(p => p.receipt_status !== 'registered' && p.receipt_status !== 'not_required').length;

  $('#page-payments').innerHTML = `
    <div class="page-title">Платежи</div>
    <div class="page-sub">История транзакций и оформление чеков</div>

    <div class="kpi-grid">
      <div class="kpi"><div class="kpi-head"><span class="kpi-label">Успешных</span></div><div class="kpi-value num">${num(succeeded.length)}</div><div class="kpi-foot"><span class="kpi-delta up">${money(succSum)}</span></div></div>
      <div class="kpi"><div class="kpi-head"><span class="kpi-label">В ожидании</span></div><div class="kpi-value num">${num(pending)}</div><div class="kpi-foot"><span class="kpi-delta flat">платежи pending</span></div></div>
      <div class="kpi"><div class="kpi-head"><span class="kpi-label">Отменены</span></div><div class="kpi-value num">${num(canceled)}</div><div class="kpi-foot"><span class="kpi-delta flat">canceled / failed</span></div></div>
      <div class="kpi"><div class="kpi-head"><span class="kpi-label">Чеков оформить</span></div><div class="kpi-value num">${num(receiptPending)}</div><div class="kpi-foot"><span class="kpi-delta ${receiptPending > 0 ? 'dn' : 'flat'}">в Мой Налог</span></div></div>
    </div>

    <div class="toolbar">
      <div class="search">
        <svg class="ico" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.35-4.35"/></svg>
        <input id="paymentsSearch" placeholder="Email, ID платежа..." />
      </div>
      <select class="filter" id="paymentsFilter">
        <option value="all">Все статусы</option>
        <option value="succeeded">Успешные</option>
        <option value="pending">В ожидании</option>
        <option value="canceled">Отменены</option>
      </select>
      <select class="filter" id="paymentsReceiptFilter">
        <option value="all">Все чеки</option>
        <option value="pending">Чек не оформлен</option>
        <option value="registered">Чек оформлен</option>
      </select>
      <div class="toolbar-grow"></div>
      <span class="counter" id="paymentsCounter">—</span>
    </div>

    <div class="card">
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr>
            <th>Дата</th><th>Пользователь</th><th>Сумма</th><th>Тариф</th><th>Email</th>
            <th>Промо</th><th>Статус</th><th>Чек</th><th class="text-r"></th>
          </tr></thead>
          <tbody id="paymentsTbody"></tbody>
        </table>
      </div>
    </div>
  `;
  $('#paymentsSearch').addEventListener('input', renderPaymentsTable);
  $('#paymentsFilter').addEventListener('change', renderPaymentsTable);
  $('#paymentsReceiptFilter').addEventListener('change', renderPaymentsTable);
  renderPaymentsTable();
}

function renderPaymentsTable() {
  const f = $('#paymentsFilter').value;
  const rf = $('#paymentsReceiptFilter').value;
  const search = ($('#paymentsSearch').value || '').toLowerCase().trim();
  let list = state.payments.slice();
  if (f !== 'all') list = list.filter(p => p.status === f);
  if (rf === 'pending') list = list.filter(p => p.status === 'succeeded' && p.receipt_status !== 'registered' && p.receipt_status !== 'not_required');
  if (rf === 'registered') list = list.filter(p => p.receipt_status === 'registered');
  if (search) list = list.filter(p => [p.email, p.provider_payment_id, p.user_id].some(x => String(x || '').toLowerCase().includes(search)));

  $('#paymentsCounter').textContent = list.length + ' шт';
  const tbody = $('#paymentsTbody');
  if (!list.length) {
    tbody.innerHTML = '<tr><td colspan="9"><div class="empty"><span class="emoji">📭</span><div class="title">Платежей нет</div></div></td></tr>';
    return;
  }
  tbody.innerHTML = list.map(p => {
    const u = userById(p.user_id);
    const stCls = p.status === 'succeeded' ? 'green' : p.status === 'pending' ? 'yellow' : p.status === 'canceled' ? 'red' : 'orange';
    const promoInfo = p.metadata && p.metadata.promo_code ? `<span class="tag tag-purple">${esc(p.metadata.promo_code)}</span>` : '<span class="muted">—</span>';
    const receiptCell = p.status !== 'succeeded' ? '<span class="muted">—</span>'
      : p.receipt_status === 'registered' ? `<span class="tag tag-green">✓ оформлен</span>`
      : p.receipt_status === 'not_required' ? `<span class="tag tag-gray">не нужен</span>`
      : `<span class="tag tag-yellow">⏳ ждёт</span>`;
    return `<tr>
      <td><span class="mono">${fmtDateTime(p.created_at)}</span></td>
      <td><div class="u-cell">${avaHtml(u || { user_id: p.user_id })}<div class="u-name">${esc(u ? displayName(u) : ('id:' + p.user_id))}</div></div></td>
      <td><span class="num" style="font-weight:700">${money(p.amount)}</span></td>
      <td><span class="mono">${p.months || '?'} мес · ${p.devices || '?'} уст</span></td>
      <td><span class="mono">${esc(p.email || '—')}</span></td>
      <td>${promoInfo}</td>
      <td><span class="tag tag-${stCls} dot">${p.status}</span></td>
      <td>${receiptCell}</td>
      <td><div class="row-acts">
        ${p.status === 'succeeded' && p.receipt_status !== 'registered' && p.receipt_status !== 'not_required' ? `<button class="btn btn-success btn-sm" data-act="mark" data-pid="${p.id}">${ICONS.check}</button>` : ''}
        ${p.status === 'succeeded' && p.receipt_status === 'registered' ? `<button class="btn btn-ghost btn-sm" data-act="unmark" data-pid="${p.id}">↺</button>` : ''}
        ${p.confirmation_url && p.status === 'pending' ? `<a class="btn btn-ghost btn-sm" href="${esc(p.confirmation_url)}" target="_blank">${ICONS.ext}</a>` : ''}
      </div></td>
    </tr>`;
  }).join('');

  $$('#paymentsTbody [data-act="mark"]').forEach(b => b.addEventListener('click', () => markReceipt(Number(b.dataset.pid), 'registered')));
  $$('#paymentsTbody [data-act="unmark"]').forEach(b => b.addEventListener('click', () => markReceipt(Number(b.dataset.pid), 'pending')));
}

async function markReceipt(payId, statusVal) {
  try {
    const data = { receipt_status: statusVal };
    data.receipt_registered_at = statusVal === 'registered' ? new Date().toISOString() : null;
    await sbUpdate('payments', 'id=eq.' + payId, data);
    const p = state.payments.find(x => x.id === payId);
    if (p) Object.assign(p, data);
    renderPaymentsTable();
    toast(statusVal === 'registered' ? 'Чек отмечен оформленным' : 'Отметка снята');
  } catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

/* =====================================================================
   ====================== PAGE: PROMOS ============================
   ===================================================================== */
function promoStatus(p) {
  if (!p.is_active) return { key: 'inactive', label: 'отключён', cls: 'gray' };
  if (p.expires_at && new Date(p.expires_at) < new Date()) return { key: 'expired', label: 'просрочен', cls: 'red' };
  if (p.max_uses != null && (p.uses_count || 0) >= p.max_uses) return { key: 'exhausted', label: 'исчерпан', cls: 'orange' };
  return { key: 'active', label: 'активен', cls: 'green' };
}

function renderPromos() {
  $('#page-promos').innerHTML = `
    <div class="page-title">Промокоды</div>
    <div class="page-sub">Скидки и бонусные дни</div>

    <div class="toolbar">
      <div class="search">
        <svg class="ico" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.35-4.35"/></svg>
        <input id="promosSearch" placeholder="Поиск по коду..." />
      </div>
      <select class="filter" id="promosFilter">
        <option value="all">Все</option>
        <option value="active">Активные</option>
        <option value="inactive">Отключены</option>
        <option value="exhausted">Исчерпаны</option>
        <option value="expired">Просрочены</option>
      </select>
      <div class="toolbar-grow"></div>
      <button class="btn btn-primary btn-sm" id="newPromoBtn">${ICONS.plus} Новый промокод <span class="kbd-hint">N</span></button>
    </div>

    <div class="card">
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr>
            <th>Код</th><th>Тип</th><th>Значение</th><th>Использовано</th>
            <th>Действует до</th><th>Статус</th><th class="text-r"></th>
          </tr></thead>
          <tbody id="promosTbody"></tbody>
        </table>
      </div>
    </div>
  `;
  $('#promosSearch').addEventListener('input', renderPromosTable);
  $('#promosFilter').addEventListener('change', renderPromosTable);
  $('#newPromoBtn').addEventListener('click', () => { resetPromoModal(); openModal('promoModal'); });
  renderPromosTable();
}

function renderPromosTable() {
  const f = $('#promosFilter').value;
  const search = ($('#promosSearch').value || '').toLowerCase().trim();
  let list = state.promos.slice();
  if (search) list = list.filter(p => p.code.toLowerCase().includes(search) || (p.description || '').toLowerCase().includes(search));
  if (f !== 'all') list = list.filter(p => promoStatus(p).key === f);
  list.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

  const tbody = $('#promosTbody');
  if (!list.length) {
    tbody.innerHTML = '<tr><td colspan="7"><div class="empty"><span class="emoji">🎁</span><div class="title">Промокодов нет</div><div class="sub">Нажмите N или «Новый промокод»</div></div></td></tr>';
    return;
  }
  tbody.innerHTML = list.map(p => {
    const st = promoStatus(p);
    const max = p.max_uses == null ? '∞' : p.max_uses;
    const usedPct = p.max_uses == null ? 0 : Math.min(100, (p.uses_count || 0) / p.max_uses * 100);
    const valDisplay = p.type === 'percent' ? `−${p.value}%` : `+${p.value} дн`;
    return `<tr data-pid="${p.id}">
      <td><span class="mono" style="font-size:13px;font-weight:600;color:var(--accent-2);letter-spacing:.05em">${esc(p.code)}</span>${p.description ? `<div class="muted" style="font-size:11px;margin-top:2px">${esc(p.description)}</div>` : ''}</td>
      <td>${p.type === 'percent' ? '<span class="tag tag-blue">скидка %</span>' : '<span class="tag tag-purple">бонус дней</span>'}</td>
      <td><span class="num" style="font-weight:700">${valDisplay}</span></td>
      <td><span class="num">${p.uses_count || 0}</span> / <span class="num muted">${max}</span>${p.max_uses != null ? `<div class="progress mt-2"><i style="width:${usedPct}%"></i></div>` : ''}</td>
      <td><span class="mono">${p.expires_at ? fmtDate(p.expires_at) : '∞'}</span></td>
      <td><span class="tag tag-${st.cls} dot">${st.label}</span></td>
      <td><div class="row-acts">
        <button class="btn btn-ghost btn-sm btn-icon" data-act="copy" title="Копировать">${ICONS.copy}</button>
        <label class="toggle" title="Вкл/выкл"><input type="checkbox" ${p.is_active ? 'checked' : ''} data-act="toggle"><span class="toggle-slider"></span></label>
        <button class="btn btn-danger btn-sm btn-icon" data-act="del">${ICONS.trash}</button>
      </div></td>
    </tr>`;
  }).join('');

  $$('#promosTbody [data-act="copy"]').forEach(b => b.addEventListener('click', () => {
    const code = b.closest('tr').querySelector('.mono').textContent;
    navigator.clipboard.writeText(code);
    toast('Скопировано: ' + code);
  }));
  $$('#promosTbody [data-act="toggle"]').forEach(b => b.addEventListener('change', () => {
    togglePromo(Number(b.closest('tr').dataset.pid), b.checked);
  }));
  $$('#promosTbody [data-act="del"]').forEach(b => b.addEventListener('click', () => {
    const tr = b.closest('tr');
    deletePromo(Number(tr.dataset.pid), tr.querySelector('.mono').textContent);
  }));
}

async function togglePromo(id, val) {
  try {
    await sbUpdate('promocodes', 'id=eq.' + id, { is_active: val });
    const p = state.promos.find(x => x.id === id); if (p) p.is_active = val;
    renderPromosTable(); renderNavCounts();
    toast(val ? 'Промокод включён' : 'Промокод отключён');
  } catch (e) { toast('Ошибка: ' + e.message, 'error'); renderPromosTable(); }
}

async function deletePromo(id, code) {
  if (!confirm(`Удалить промокод ${code}? Это действие необратимо.`)) return;
  try {
    await sbDelete('promocodes', 'id=eq.' + id);
    state.promos = state.promos.filter(x => x.id !== id);
    renderPromosTable(); renderNavCounts();
    toast('Промокод удалён');
  } catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

function genPromoCode() {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  let s = '';
  for (let i = 0; i < 8; i++) s += chars[Math.floor(Math.random() * chars.length)];
  $('#promoCode').value = s;
}

function resetPromoModal() {
  $('#promoModalTitle').textContent = 'Создать промокод';
  $('#promoCode').value = '';
  $('#promoType').value = 'percent';
  $('#promoValue').value = '';
  $('#promoMax').value = '';
  $('#promoExpiry').value = '';
  $('#promoDesc').value = '';
  updatePromoHelp();
}

function updatePromoHelp() {
  const t = $('#promoType').value;
  if (t === 'percent') {
    $('#promoValueLabel').textContent = 'Размер скидки, %';
    $('#promoValue').placeholder = '20';
    $('#promoHelp').textContent = 'Скидка снижает итоговую сумму платежа. Один пользователь — одно использование.';
  } else {
    $('#promoValueLabel').textContent = 'Бонусных дней';
    $('#promoValue').placeholder = '7';
    $('#promoHelp').textContent = 'Дни добавляются к подписке (купил 30 — получил 37). Один пользователь — одно использование.';
  }
}

async function savePromo() {
  const code = $('#promoCode').value.trim().toUpperCase();
  const type = $('#promoType').value;
  const value = parseInt($('#promoValue').value);
  const max = parseInt($('#promoMax').value) || null;
  const expiry = $('#promoExpiry').value || null;
  const desc = $('#promoDesc').value.trim() || null;
  if (!code || code.length < 3) { toast('Введите код (минимум 3 символа)', 'error'); return; }
  if (!/^[A-Z0-9_-]+$/.test(code)) { toast('Только латиница, цифры, _ и -', 'error'); return; }
  if (!value || value < 1) { toast('Введите значение', 'error'); return; }
  if (type === 'percent' && value > 99) { toast('Скидка не может быть 100% и больше', 'error'); return; }
  if (state.promos.some(p => p.code === code)) { toast('Промокод с таким кодом уже есть', 'error'); return; }

  try {
    const created = await sbInsert('promocodes', {
      code, type, value, description: desc, max_uses: max,
      expires_at: expiry ? new Date(expiry + 'T23:59:59').toISOString() : null,
      is_active: true, uses_count: 0,
    });
    state.promos.unshift(created[0]);
    closeModal('promoModal');
    renderPromosTable(); renderNavCounts();
    toast('Промокод ' + code + ' создан');
  } catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

/* =====================================================================
   ====================== PAGE: REFERRALS ============================
   ===================================================================== */
function renderReferrals() {
  const total = state.refs.length;
  const referrers = {};
  state.users.filter(u => u.referrer_id).forEach(u => {
    referrers[u.referrer_id] = referrers[u.referrer_id] || { referred: [], paid: 0 };
    referrers[u.referrer_id].referred.push(u);
  });
  Object.keys(referrers).forEach(rid => {
    referrers[rid].paid = referrers[rid].referred.filter(u =>
      state.payments.some(p => Number(p.user_id) === Number(u.user_id) && p.status === 'succeeded')
    ).length;
  });
  const list = Object.entries(referrers).map(([rid, info]) => ({
    user: userById(rid) || { user_id: rid },
    referred: info.referred.length,
    paid: info.paid,
  })).sort((a, b) => b.referred - a.referred);

  const totalPaid = list.reduce((s, r) => s + r.paid, 0);
  const totalDays = state.refs.reduce((s, r) => s + (r.bonus_days || 0), 0);

  $('#page-referrals').innerHTML = `
    <div class="page-title">Рефералы</div>
    <div class="page-sub">Кто кого привёл и сколько получил бонусов</div>

    <div class="kpi-grid">
      <div class="kpi"><div class="kpi-head"><span class="kpi-label">Всего переходов</span></div><div class="kpi-value num">${num(total)}</div><div class="kpi-foot"><span class="kpi-delta flat">по реф.ссылке</span></div></div>
      <div class="kpi"><div class="kpi-head"><span class="kpi-label">Привели оплативших</span></div><div class="kpi-value num">${num(totalPaid)}</div><div class="kpi-foot"><span class="kpi-delta flat">конверсия в оплату</span></div></div>
      <div class="kpi"><div class="kpi-head"><span class="kpi-label">Активных рефереров</span></div><div class="kpi-value num">${num(list.length)}</div><div class="kpi-foot"><span class="kpi-delta flat">привели хотя бы 1</span></div></div>
      <div class="kpi"><div class="kpi-head"><span class="kpi-label">Дней начислено</span></div><div class="kpi-value num">${num(totalDays)}</div><div class="kpi-foot"><span class="kpi-delta flat">бонусом и тем и тем</span></div></div>
    </div>

    <div class="card">
      <div class="card-head">
        <div class="card-title">🏆 Топ рефереров</div>
        <span class="card-sub">по количеству приведённых</span>
      </div>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr><th>#</th><th>Реферер</th><th>Привёл</th><th>Оплатили</th><th>Конверсия</th></tr></thead>
          <tbody id="refTbody"></tbody>
        </table>
      </div>
    </div>
  `;

  const tbody = $('#refTbody');
  if (!list.length) {
    tbody.innerHTML = '<tr><td colspan="5"><div class="empty"><span class="emoji">🤝</span><div class="title">Рефералов пока нет</div></div></td></tr>';
    return;
  }
  tbody.innerHTML = list.slice(0, 30).map((r, i) => {
    const conv = r.referred ? Math.round(r.paid / r.referred * 100) : 0;
    const medal = i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : '#' + (i + 1);
    return `<tr class="clickable" data-uid="${r.user.user_id}">
      <td><span style="font-weight:700">${medal}</span></td>
      <td><div class="u-cell">${avaHtml(r.user)}<div class="u-name">${esc(displayName(r.user))}</div></div></td>
      <td><span class="num" style="font-weight:600">${r.referred}</span></td>
      <td><span class="num" style="color:var(--green);font-weight:600">${r.paid}</span></td>
      <td><span class="num">${conv}%</span></td>
    </tr>`;
  }).join('');
  $$('#refTbody tr.clickable').forEach(r => r.addEventListener('click', () => openUserSheet(r.dataset.uid)));
}

/* =====================================================================
   ====================== PAGE: TICKETS ============================
   ===================================================================== */
function renderTickets() {
  $('#page-tickets').innerHTML = `
    <div class="page-title">Тикеты поддержки</div>
    <div class="page-sub">Обращения пользователей</div>

    <div class="toolbar">
      <select class="filter" id="ticketsFilter">
        <option value="active">Открытые и в работе</option>
        <option value="open">Только открытые</option>
        <option value="in_progress">В работе</option>
        <option value="closed">Закрытые</option>
        <option value="all">Все</option>
      </select>
      <div class="toolbar-grow"></div>
      <span class="counter" id="ticketsCounter">—</span>
    </div>

    <div class="card">
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr><th>#</th><th>Пользователь</th><th>Тема</th><th>Статус</th><th>Назначен</th><th>Создан</th><th class="text-r"></th></tr></thead>
          <tbody id="ticketsTbody"></tbody>
        </table>
      </div>
    </div>
  `;
  $('#ticketsFilter').addEventListener('change', renderTicketsTable);
  renderTicketsTable();
}

function renderTicketsTable() {
  const f = $('#ticketsFilter').value;
  let list = state.tickets.slice();
  if (f === 'active') list = list.filter(t => t.status === 'open' || t.status === 'in_progress');
  else if (f !== 'all') list = list.filter(t => t.status === f);

  $('#ticketsCounter').textContent = list.length + ' шт';
  const tbody = $('#ticketsTbody');
  if (!list.length) {
    tbody.innerHTML = '<tr><td colspan="7"><div class="empty"><span class="emoji">💬</span><div class="title">Тикетов нет</div></div></td></tr>';
    return;
  }
  tbody.innerHTML = list.map(t => {
    const u = { user_id: t.user_id, username: t.username, first_name: t.first_name, last_name: t.last_name };
    const cls = t.status === 'open' ? 'yellow' : t.status === 'in_progress' ? 'blue' : 'green';
    const lab = t.status === 'open' ? 'open' : t.status === 'in_progress' ? 'work' : 'closed';
    const admin = t.assigned_admin_id ? state.supportAdmins.find(a => Number(a.user_id) === Number(t.assigned_admin_id)) : null;
    return `<tr class="clickable" data-uid="${t.user_id}">
      <td><span class="mono" style="font-weight:600">#${t.id}</span></td>
      <td><div class="u-cell">${avaHtml(u)}<div class="u-name">${esc(displayName(u))}</div></div></td>
      <td><span class="muted">${esc((t.subject || '').slice(0, 60))}</span></td>
      <td><span class="tag tag-${cls} dot">${lab}</span></td>
      <td>${admin ? esc(admin.full_name || ('@' + admin.username)) : '<span class="muted">—</span>'}</td>
      <td><span class="mono">${fmtDateTime(t.created_at)}</span></td>
      <td><a class="btn btn-ghost btn-sm" href="https://t.me/TuVPNSupport_bot" target="_blank">${ICONS.ext}</a></td>
    </tr>`;
  }).join('');
  $$('#ticketsTbody tr.clickable').forEach(r => r.addEventListener('click', e => {
    if (e.target.closest('a, button')) return;
    openUserSheet(r.dataset.uid);
  }));
}


/* =====================================================================
   ====================== PAGE: SERVERS ==============================
   Главное обновление: multi-server инфраструктура
   ===================================================================== */
function renderServers() {
  const servers = state.servers.slice().sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0));
  const active = servers.filter(s => s.is_active);
  const up = servers.filter(s => s.last_check_status === 'up').length;
  const down = servers.filter(s => s.last_check_status === 'down').length;

  $('#page-servers').innerHTML = `
    <div class="page-title">Серверы</div>
    <div class="page-sub">VPN-инфраструктура — мультисерверная архитектура</div>

    <div class="kpi-grid">
      <div class="kpi">
        <div class="kpi-head"><span class="kpi-label">Всего серверов</span><span class="kpi-ico">${ICONS.server}</span></div>
        <div class="kpi-value num">${servers.length}</div>
        <div class="kpi-foot"><span class="kpi-delta flat">${active.length} активных</span></div>
      </div>
      <div class="kpi">
        <div class="kpi-head"><span class="kpi-label">Онлайн</span></div>
        <div class="kpi-value num" style="color:var(--green)">${up}</div>
        <div class="kpi-foot"><span class="kpi-delta up">${servers.length ? Math.round(up / servers.length * 100) : 0}% доступно</span></div>
      </div>
      <div class="kpi">
        <div class="kpi-head"><span class="kpi-label">Недоступно</span></div>
        <div class="kpi-value num" style="color:${down ? 'var(--red)' : 'var(--fg-3)'}">${down}</div>
        <div class="kpi-foot"><span class="kpi-delta ${down ? 'dn' : 'flat'}">требуют внимания</span></div>
      </div>
      <div class="kpi">
        <div class="kpi-head"><span class="kpi-label">Активных подписок</span></div>
        <div class="kpi-value num">${state.subs.filter(s => s.status === 'active').length}</div>
        <div class="kpi-foot"><span class="kpi-delta flat">клиентов на каждом</span></div>
      </div>
    </div>

    <div class="toolbar">
      <span class="counter">Каждая новая подписка автоматически создаётся на всех активных серверах.</span>
      <div class="toolbar-grow"></div>
      <button class="btn btn-ghost btn-sm" id="syncAllBtn">${ICONS.refresh} Синхр. все</button>
      <button class="btn btn-ghost btn-sm" id="recheckAllBtn">${ICONS.refresh} Проверить все</button>
      <button class="btn btn-primary btn-sm" id="addServerBtn">${ICONS.plus} Добавить сервер <span class="kbd-hint">N</span></button>
    </div>

    <div class="srv-grid" id="srvGrid"></div>

    <div style="margin-top: 32px">
      <div class="card">
        <div class="card-head"><div class="card-title">Внешние ссылки</div></div>
        <div class="card-pad" style="display:grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap:8px; padding: 14px 16px">
          <a class="pill" href="https://supabase.com/dashboard/project/avjvojscvmsdzllaeise" target="_blank">${ICONS.ext} Supabase БД</a>
          <a class="pill" href="https://yookassa.ru/my" target="_blank">${ICONS.ext} ЮКасса</a>
          <a class="pill" href="https://t.me/MaxArtVPN_bot" target="_blank">${ICONS.ext} Основной бот</a>
          <a class="pill" href="https://t.me/TuVPNSupport_bot" target="_blank">${ICONS.ext} Бот поддержки</a>
          <a class="pill" href="https://github.com/effect110419/tuvpn-bot" target="_blank">${ICONS.ext} GitHub</a>
          <a class="pill" href="https://my.adminvps.ru" target="_blank">${ICONS.ext} AdminVPS</a>
        </div>
      </div>
    </div>
  `;
  renderServerGrid();
  $('#addServerBtn').addEventListener('click', () => openServerModal());
  $('#recheckAllBtn').addEventListener('click', recheckAllServers);
  const sab = $('#syncAllBtn'); if (sab) sab.addEventListener('click', syncAllServers);
}

function renderServerGrid() {
  const grid = $('#srvGrid');
  if (!grid) return;
  const servers = state.servers.slice().sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0));

  if (!servers.length) {
    grid.innerHTML = `
      <div class="card" style="grid-column:1/-1">
        <div class="empty" style="padding:48px 20px">
          <span class="emoji">🖥</span>
          <div class="title">Серверов пока нет</div>
          <div class="sub">Добавьте первый сервер — он сразу появится в подписках клиентов</div>
        </div>
      </div>
    `;
    return;
  }

  grid.innerHTML = servers.map(s => {
    const status = s.last_check_status === 'up' ? 'up'
      : s.last_check_status === 'down' ? 'dn'
      : 'idle';
    const statusLabel = status === 'up' ? 'онлайн' : status === 'dn' ? 'недоступен' : 'не проверен';
    const respMs = s.last_check_response_ms != null ? s.last_check_response_ms + ' ms' : '—';
    return `<div class="srv ${status === 'dn' ? 'is-down' : ''}" data-sid="${s.id}">
      <div class="srv-head">
        <div style="display:flex;gap:10px;align-items:center;min-width:0">
          <div class="srv-flag">${esc(s.country_flag || '🌍')}</div>
          <div style="min-width:0">
            <div class="srv-name">${esc(s.country_name || s.code)}</div>
            <div class="srv-code">${esc(s.code)} · ${esc(s.country_code || '')}</div>
          </div>
        </div>
        <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px">
          <span class="tag tag-${status === 'up' ? 'green' : status === 'dn' ? 'red' : 'gray'} dot">${statusLabel}</span>
          <label class="toggle" title="${s.is_active ? 'Активен' : 'Отключён'}"><input type="checkbox" ${s.is_active ? 'checked' : ''} data-act="toggle"><span class="toggle-slider"></span></label>
        </div>
      </div>

      <div class="srv-info">
        <div class="k">IP</div><div class="v">${esc(s.server_ip)}:${s.server_port || 443}</div>
        <div class="k">Inbound</div><div class="v">#${s.inbound_id ?? '—'}</div>
        <div class="k">SNI</div><div class="v">${esc(s.sni || '—')}</div>
        <div class="k">Отклик</div><div class="v">${respMs}</div>
        <div class="k">Проверено</div><div class="v">${s.last_check_at ? fmtTimeAgo(s.last_check_at) : 'никогда'}</div>
      </div>

      <div class="srv-foot">
        <button class="btn btn-ghost btn-sm" data-act="check">${ICONS.refresh} Проверить</button>
          <button class="btn btn-ghost btn-sm" data-act="sync">${ICONS.refresh} Синхр.</button>
        <div class="srv-acts">
          <button class="btn btn-ghost btn-sm btn-icon" data-act="edit" title="Редактировать">${ICONS.edit}</button>
        </div>
      </div>
    </div>`;
  }).join('');

  // Bind actions
  $$('.srv').forEach(card => {
    const sid = card.dataset.sid;
    card.querySelector('[data-act="toggle"]').addEventListener('change', e => toggleServerActive(sid, e.target.checked));
    card.querySelector('[data-act="check"]').addEventListener('click', () => checkServer(sid));
    const sb = card.querySelector('[data-act="sync"]'); if (sb) sb.addEventListener('click', () => syncServer(sid));
    card.querySelector('[data-act="edit"]').addEventListener('click', () => openServerModal(sid));
  });
}

function openServerModal(sid = null) {
  const isEdit = sid != null;
  $('#serverModalTitle').textContent = isEdit ? 'Редактировать сервер' : 'Добавить сервер';
  $('#srvDeleteBtn').style.display = isEdit ? 'inline-flex' : 'none';
  $('#srvId').value = sid || '';

  if (isEdit) {
    const s = state.servers.find(x => String(x.id) === String(sid));
    if (!s) { toast('Сервер не найден', 'error'); return; }
    $('#srvFlag').value = s.country_flag || '';
    $('#srvCountry').value = s.country_name || '';
    $('#srvCode').value = s.code || '';
    $('#srvCountryCode').value = s.country_code || '';
    $('#srvPanelUrl').value = s.panel_url || '';
    $('#srvPanelLogin').value = s.panel_login || '';
    $('#srvPanelPass').value = s.panel_password || '';
    $('#srvIp').value = s.server_ip || '';
    $('#srvPort').value = s.server_port || 443;
    $('#srvInbound').value = s.inbound_id ?? 1;
    $('#srvPubKey').value = s.public_key || '';
    $('#srvShortId').value = s.short_id || '';
    $('#srvSni').value = s.sni || 'www.bing.com';
    $('#srvFlow').value = s.flow || 'xtls-rprx-vision';
    $('#srvFp').value = s.fingerprint || 'chrome';
    $('#srvSort').value = s.sort_order || 0;
    $('#srvActive').checked = !!s.is_active;
  } else {
    // Reset
    ['#srvFlag', '#srvCountry', '#srvCode', '#srvCountryCode', '#srvPanelUrl', '#srvPanelLogin', '#srvPanelPass', '#srvIp', '#srvPubKey', '#srvShortId'].forEach(s => $(s).value = '');
    $('#srvPort').value = 443;
    $('#srvInbound').value = 1;
    $('#srvSni').value = 'www.bing.com';
    $('#srvFlow').value = 'xtls-rprx-vision';
    $('#srvFp').value = 'chrome';
    $('#srvSort').value = state.servers.length;
    $('#srvActive').checked = true;
  }

  openModal('serverModal');
}

async function saveServer() {
  const sid = $('#srvId').value;
  const isEdit = !!sid;

  const data = {
    code: $('#srvCode').value.trim(),
    country_name: $('#srvCountry').value.trim(),
    country_flag: $('#srvFlag').value.trim(),
    country_code: $('#srvCountryCode').value.trim().toUpperCase(),
    panel_url: $('#srvPanelUrl').value.trim().replace(/\/$/, ''),
    panel_login: $('#srvPanelLogin').value.trim(),
    panel_password: $('#srvPanelPass').value,
    server_ip: $('#srvIp').value.trim(),
    server_port: parseInt($('#srvPort').value) || 443,
    inbound_id: parseInt($('#srvInbound').value) || 1,
    public_key: $('#srvPubKey').value.trim(),
    short_id: $('#srvShortId').value.trim(),
    sni: $('#srvSni').value.trim() || 'www.bing.com',
    flow: $('#srvFlow').value.trim() || 'xtls-rprx-vision',
    fingerprint: $('#srvFp').value,
    sort_order: parseInt($('#srvSort').value) || 0,
    is_active: $('#srvActive').checked,
  };

  // Validate
  const required = ['code', 'country_name', 'panel_url', 'panel_login', 'panel_password', 'server_ip', 'public_key', 'short_id'];
  for (const f of required) {
    if (!data[f]) { toast(`Заполните поле: ${f}`, 'error'); return; }
  }

  const btn = $('#serverSubmit');
  btn.disabled = true;
  btn.textContent = isEdit ? 'Сохраняем...' : 'Создаём...';

  try {
    let r;
    if (isEdit) {
      r = await proxy(`/admin-api/servers/${sid}`, { method: 'PUT', body: JSON.stringify(data) });
    } else {
      r = await proxy('/admin-api/servers', { method: 'POST', body: JSON.stringify(data) });
    }
    if (!r.success) throw new Error(r.error || 'unknown');

    // Reload servers
    const fresh = await proxy('/admin-api/servers');
    state.servers = fresh.servers || [];
    closeModal('serverModal');
    renderServers(); renderNavCounts();
    toast(isEdit ? 'Сервер обновлён' : 'Сервер добавлен');
  } catch (e) {
    toast('Ошибка: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Сохранить';
  }
}

async function deleteServerFromModal() {
  const sid = $('#srvId').value;
  if (!sid) return;
  const s = state.servers.find(x => String(x.id) === String(sid));
  if (!s) return;
  if (!confirm(`Удалить сервер ${s.country_flag} ${s.country_name}?\n\nЭто действие необратимо. Существующие клиенты на этом сервере останутся, но в новые подписки он попадать не будет.`)) return;

  try {
    const r = await proxy(`/admin-api/servers/${sid}`, { method: 'DELETE' });
    if (!r.success) throw new Error(r.error || 'unknown');
    state.servers = state.servers.filter(x => String(x.id) !== String(sid));
    closeModal('serverModal');
    renderServers(); renderNavCounts();
    toast('Сервер удалён');
  } catch (e) {
    toast('Ошибка: ' + e.message, 'error');
  }
}

async function toggleServerActive(sid, val) {
  try {
    const r = await proxy(`/admin-api/servers/${sid}`, {
      method: 'PUT',
      body: JSON.stringify({ is_active: val }),
    });
    if (!r.success) throw new Error(r.error || 'unknown');
    const s = state.servers.find(x => String(x.id) === String(sid));
    if (s) s.is_active = val;
    renderServerGrid(); renderNavCounts();
    toast(val ? 'Сервер активирован' : 'Сервер отключён');
  } catch (e) {
    toast('Ошибка: ' + e.message, 'error');
  }
}


async function syncServer(sid) {
  const s = state.servers.find(x => String(x.id) === String(sid));
  if (!s) return;
  if (!confirm(`Синхронизировать ${s.country_flag || ''} ${s.country_name}?\n\nНа этот сервер будут добавлены все активные подписки, которых там ещё нет. Существующие — обновлены (срок действия).`)) return;

  toast('Синхронизация запущена...');
  try {
    const r = await proxy(`/admin-api/servers/${sid}/sync`, { method: 'POST' });
    if (r.success) {
      toast(`${s.country_flag || ''} ${s.country_name}: ${r.ok}/${r.total} подписок развёрнуто${r.failed ? `, ошибок: ${r.failed}` : ''}`);
      if (r.failed && r.failures && r.failures.length) {
        console.warn('Sync failures:', r.failures);
      }
    } else {
      toast('Ошибка: ' + (r.error || 'unknown'), 'error');
    }
  } catch (e) {
    toast('Ошибка: ' + e.message, 'error');
  }
}

async function syncAllServers() {
  if (!confirm('Синхронизировать все активные серверы?\n\nНа каждый сервер будут раскатаны все активные подписки. Это может занять минуту.')) return;
  toast('Синхронизация всех серверов...');
  try {
    const r = await proxy('/admin-api/servers/sync_all', { method: 'POST' });
    if (r.success) {
      const lines = (r.servers || []).map(x => {
        if (x.error) return `${x.code}: ошибка (${x.error})`;
        return `${x.code}: ${x.ok}/${x.total}${x.failed ? `, fail ${x.failed}` : ''}`;
      });
      toast(lines.join(' · '));
      console.log('Sync all result:', r);
    } else {
      toast('Ошибка: ' + (r.error || 'unknown'), 'error');
    }
  } catch (e) {
    toast('Ошибка: ' + e.message, 'error');
  }
}

async function checkServer(sid) {
  const card = $(`.srv[data-sid="${sid}"]`);
  if (card) {
    const btn = card.querySelector('[data-act="check"]');
    btn.disabled = true;
    btn.innerHTML = '⏳ Проверяем...';
  }
  try {
    const r = await proxy(`/admin-api/servers/${sid}/test`, { method: 'POST' });
    const s = state.servers.find(x => String(x.id) === String(sid));
    if (s) {
      s.last_check_status = r.status;
      s.last_check_response_ms = r.response_ms;
      s.last_check_at = new Date().toISOString();
    }
    renderServerGrid();
    if (r.success) toast(`✓ Сервер онлайн (${r.response_ms} ms)`);
    else toast(`✕ Сервер недоступен: ${r.error || 'unknown'}`, 'error');
  } catch (e) {
    toast('Ошибка: ' + e.message, 'error');
  }
}

async function recheckAllServers() {
  toast('Проверяем все серверы...', 'success', { duration: 1500 });
  for (const s of state.servers) {
    await checkServer(s.id);
  }
}

/* =====================================================================
   ====================== PAGE: SETTINGS ============================
   ===================================================================== */
function renderSettings() {
  $('#page-settings').innerHTML = `
    <div class="page-title">Настройки</div>
    <div class="page-sub">Конфигурация админки</div>

    <div class="grid-1-1">
      <div class="card">
        <div class="card-head"><div class="card-title">🔒 Смена пароля</div></div>
        <div class="card-pad">
          <div class="field">
            <label class="label">Текущий пароль</label>
            <input id="oldPass" type="password" class="input" placeholder="••••••">
          </div>
          <div class="field">
            <label class="label">Новый пароль</label>
            <input id="newPass" type="password" class="input" placeholder="••••••">
          </div>
          <button class="btn btn-primary" id="changePassBtn">Сменить пароль</button>
          <div class="help mt-3">Пароль хранится локально в этом браузере (localStorage). Чтобы войти с другого устройства — пароль нужен будет тот же.</div>
        </div>
      </div>

      <div class="card">
        <div class="card-head"><div class="card-title">📊 Состояние БД</div></div>
        <div class="card-pad">
          <div class="info"><span class="info-k">Пользователей</span><span class="info-v num">${num(state.users.length)}</span></div>
          <div class="info"><span class="info-k">Подписок</span><span class="info-v num">${num(state.subs.length)}</span></div>
          <div class="info"><span class="info-k">Платежей</span><span class="info-v num">${num(state.payments.length)}</span></div>
          <div class="info"><span class="info-k">Промокодов</span><span class="info-v num">${num(state.promos.length)}</span></div>
          <div class="info"><span class="info-k">Тикетов</span><span class="info-v num">${num(state.tickets.length)}</span></div>
          <div class="info"><span class="info-k">Рефералов</span><span class="info-v num">${num(state.refs.length)}</span></div>
          <div class="info"><span class="info-k">Серверов</span><span class="info-v num">${num(state.servers.length)}</span></div>
        </div>
      </div>
    </div>

    <div class="card mt-3">
      <div class="card-head"><div class="card-title">⌨️ Горячие клавиши</div></div>
      <div class="card-pad" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:8px;padding:14px 18px">
        <div class="info"><span class="info-k">Поиск/команды</span><span class="info-v"><span class="kbd-key">⌘K</span> / <span class="kbd-key">Ctrl+K</span></span></div>
        <div class="info"><span class="info-k">Обновить</span><span class="info-v"><span class="kbd-key">R</span></span></div>
        <div class="info"><span class="info-k">Создать (контекст)</span><span class="info-v"><span class="kbd-key">N</span></span></div>
        <div class="info"><span class="info-k">Поиск на странице</span><span class="info-v"><span class="kbd-key">/</span></span></div>
        <div class="info"><span class="info-k">Закрыть/отмена</span><span class="info-v"><span class="kbd-key">ESC</span></span></div>
        <div class="info"><span class="info-k">Дашборд</span><span class="info-v"><span class="kbd-key">G</span> <span class="kbd-key">D</span></span></div>
        <div class="info"><span class="info-k">Пользователи</span><span class="info-v"><span class="kbd-key">G</span> <span class="kbd-key">U</span></span></div>
        <div class="info"><span class="info-k">Подписки</span><span class="info-v"><span class="kbd-key">G</span> <span class="kbd-key">S</span></span></div>
        <div class="info"><span class="info-k">Платежи</span><span class="info-v"><span class="kbd-key">G</span> <span class="kbd-key">P</span></span></div>
        <div class="info"><span class="info-k">Маркетинг</span><span class="info-v"><span class="kbd-key">G</span> <span class="kbd-key">M</span></span></div>
        <div class="info"><span class="info-k">Промокоды</span><span class="info-v"><span class="kbd-key">G</span> <span class="kbd-key">O</span></span></div>
        <div class="info"><span class="info-k">Рефералы</span><span class="info-v"><span class="kbd-key">G</span> <span class="kbd-key">R</span></span></div>
        <div class="info"><span class="info-k">Тикеты</span><span class="info-v"><span class="kbd-key">G</span> <span class="kbd-key">T</span></span></div>
        <div class="info"><span class="info-k">Серверы</span><span class="info-v"><span class="kbd-key">G</span> <span class="kbd-key">V</span></span></div>
        <div class="info"><span class="info-k">Настройки</span><span class="info-v"><span class="kbd-key">G</span> <span class="kbd-key">X</span></span></div>
      </div>
    </div>
  `;
  $('#changePassBtn').addEventListener('click', changePass);
}

/* =====================================================================
   ====================== ACTIONS ============================
   ===================================================================== */
function quickGrant(uid) {
  $('#grantUid').value = uid;
  const u = userById(uid);
  $('#grantUserHint').textContent = u ? `Найден: ${displayName(u)}` : 'Пользователь не найден в БД, но можно попробовать выдать.';
  openModal('grantModal');
}

async function grantSubscription() {
  const uid = parseInt($('#grantUid').value);
  const devices = parseInt($('#grantDevices').value);
  const days = parseInt($('#grantDays').value);
  if (!uid) { toast('Введите Telegram ID', 'error'); return; }

  const btn = $('#grantSubmit');
  btn.disabled = true;
  btn.innerHTML = '⏳ Выдаём...';
  try {
    const r = await proxy('/admin-api/grant', {
      method: 'POST',
      body: JSON.stringify({ user_id: uid, devices, days }),
    });
    if (r.success) {
      toast(`Подписка ${r.action === 'extended' ? 'продлена' : 'создана'} на ${r.servers || '?'} серверах`);
      closeModal('grantModal');
      try { await sbUpdate('users', 'user_id=eq.' + uid, { client_uuid: r.uuid }); } catch (e) {}
      await loadAll();
    } else {
      toast('Ошибка: ' + (r.error || 'unknown'), 'error');
    }
  } catch (e) {
    toast('Ошибка: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = `${ICONS.check} Выдать`;
  }
}

async function revokeSub(id) {
  if (!confirm('Отозвать подписку? Пользователь потеряет доступ.')) return;
  try {
    await sbUpdate('subscriptions', 'id=eq.' + id, { status: 'inactive' });
    const s = state.subs.find(x => x.id === id);
    if (s) s.status = 'inactive';
    renderPage(state.currentPage);
    toast('Подписка отозвана');
  } catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

function openBonusModal(uid) {
  const u = userById(uid);
  $('#bonusUser').value = u ? `${displayName(u)} (${uid})` : 'id:' + uid;
  $('#bonusUser').dataset.uid = uid;
  $('#bonusDays').value = '';
  openModal('bonusModal');
}

async function grantBonusDays() {
  const uid = parseInt($('#bonusUser').dataset.uid);
  const days = parseInt($('#bonusDays').value);
  if (!days || days < 1) { toast('Введите количество дней', 'error'); return; }
  try {
    const sub = activeSubFor(uid);
    if (sub && daysLeft(sub.expires_at) > 0) {
      const r = await proxy('/admin-api/grant', {
        method: 'POST',
        body: JSON.stringify({ user_id: uid, devices: sub.devices, days }),
      });
      if (!r.success) throw new Error(r.error || 'unknown');
      toast(`Подписка продлена на ${days} дней`);
    } else {
      const u = userById(uid);
      const cur = (u && u.bonus_days) || 0;
      await sbUpdate('users', 'user_id=eq.' + uid, { bonus_days: cur + days });
      if (u) u.bonus_days = cur + days;
      toast(`+${days} дней в копилке (применятся при следующей оплате)`);
    }
    closeModal('bonusModal');
    await loadAll();
  } catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

/* =====================================================================
   ====================== PAGE: MARKETING ============================
   ===================================================================== */
function renderMarketing() {
  // Calculate marketing stats
  const campaigns = state.campaigns || [];
  const campaignClicks = state.campaignClicks || [];
  const organicUsers = state.users.filter(u => !u.campaign_code);
  const organicPayments = state.payments.filter(p => !p.campaign_code);
  const totalOrganicRevenue = organicPayments.reduce((sum, p) => sum + (parseFloat(p.amount) || 0), 0);

  // Campaign stats calculation
  const campaignStats = campaigns.map(campaign => {
    const clicks = campaignClicks.filter(c => c.campaign_code === campaign.code);
    const newUsers = clicks.filter(c => c.is_new_user);
    const campaignUsers = state.users.filter(u => u.campaign_code === campaign.code);
    const campaignPayments = state.payments.filter(p => p.campaign_code === campaign.code);
    const revenue = campaignPayments.reduce((sum, p) => sum + (parseFloat(p.amount) || 0), 0);
    const cost = parseFloat(campaign.cost) || 0;
    const roi = cost > 0 ? ((revenue - cost) / cost * 100) : (revenue > 0 ? Infinity : 0);

    return {
      ...campaign,
      clicks: clicks.length,
      registrations: newUsers.length,
      payments: campaignPayments.length,
      revenue,
      cost,
      roi,
      avgTicket: campaignPayments.length > 0 ? revenue / campaignPayments.length : 0
    };
  });

  // Sort by ROI desc
  campaignStats.sort((a, b) => (b.roi === Infinity ? 1 : b.roi) - (a.roi === Infinity ? 1 : a.roi));

  // Top KPI
  const totalCampaigns = campaigns.length;
  const activeCampaigns = campaigns.filter(c => c.is_active).length;
  const totalCost = campaigns.reduce((sum, c) => sum + (parseFloat(c.cost) || 0), 0);
  const totalRevenue = campaignStats.reduce((sum, c) => sum + c.revenue, 0);
  const totalROI = totalCost > 0 ? ((totalRevenue - totalCost) / totalCost * 100) : 0;

  // Sources breakdown
  const sourceStats = {};
  campaigns.forEach(c => {
    const source = c.source || 'other';
    if (!sourceStats[source]) sourceStats[source] = { campaigns: 0, cost: 0, revenue: 0 };
    sourceStats[source].campaigns++;
    sourceStats[source].cost += parseFloat(c.cost) || 0;
  });
  campaignStats.forEach(cs => {
    const source = cs.source || 'other';
    if (sourceStats[source]) sourceStats[source].revenue += cs.revenue;
  });

  $('#page-marketing').innerHTML = `
    <div class="page-head">
      <div class="page-title">📣 UTM-кампании</div>
      <div class="flex gap-2">
        <button class="btn btn-ghost" onclick="loadAll()" title="Обновить (R)">
          ${ICONS.refresh} Обновить
        </button>
        <button class="btn btn-primary" onclick="openCampaignModal()" title="Создать (N)">
          ${ICONS.plus} Новая кампания
        </button>
      </div>
    </div>

    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-val">${totalCampaigns}</div>
        <div class="kpi-label">Всего кампаний</div>
        <div class="kpi-note">${activeCampaigns} активных</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-val">${num(totalCost)}</div>
        <div class="kpi-label">Потрачено, ₽</div>
        <div class="kpi-note">на размещения</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-val">${num(totalRevenue)}</div>
        <div class="kpi-label">Выручка, ₽</div>
        <div class="kpi-note">от UTM-трафика</div>
      </div>
      <div class="kpi-card ${totalROI > 0 ? 'success' : totalROI < -10 ? 'danger' : ''}">
        <div class="kpi-val">${totalROI > 0 ? '+' : ''}${totalROI.toFixed(0)}%</div>
        <div class="kpi-label">ROI</div>
        <div class="kpi-note">${totalROI > 0 ? 'прибыль' : 'убыток'}</div>
      </div>
    </div>

    <div class="card">
      <div class="card-head">
        <div class="card-title">🎯 Кампании по эффективности</div>
        <div class="table-actions">
          <input type="search" id="campaignSearch" placeholder="Поиск кампаний..." class="search-input">
        </div>
      </div>
      <div class="table-container">
        <table id="campaignsTable">
          <thead>
            <tr>
              <th>Кампания</th>
              <th>Источник</th>
              <th style="text-align:right">Расходы ₽</th>
              <th style="text-align:right">Клики</th>
              <th style="text-align:right">Рег-ции</th>
              <th style="text-align:right">Оплаты</th>
              <th style="text-align:right">Выручка ₽</th>
              <th style="text-align:right">ROI</th>
              <th style="text-align:right">Ср.чек ₽</th>
            </tr>
          </thead>
          <tbody>
            <!-- Direct Traffic Row -->
            <tr class="organic-row" style="background:var(--bg-2);border-left:3px solid var(--accent-3)">
              <td>
                <div class="u-cell">
                  <div class="status-dot organic"></div>
                  <div>
                    <div style="font-weight:600">🌱 Прямой трафик</div>
                    <div class="text-muted" style="font-size:12px">Органические пользователи</div>
                  </div>
                </div>
              </td>
              <td><span class="pill pill-muted">organic</span></td>
              <td style="text-align:right">—</td>
              <td style="text-align:right">—</td>
              <td style="text-align:right">${organicUsers.length}</td>
              <td style="text-align:right">${organicPayments.length}</td>
              <td style="text-align:right">${num(totalOrganicRevenue)}</td>
              <td style="text-align:right"><span class="roi-badge success">∞</span></td>
              <td style="text-align:right">${organicPayments.length > 0 ? num(totalOrganicRevenue / organicPayments.length) : '—'}</td>
            </tr>
            ${campaignStats.map(campaign => `
              <tr class="campaign-row" data-code="${campaign.code}" onclick="showCampaignDetails('${campaign.code}')">
                <td>
                  <div class="u-cell">
                    <div class="status-dot ${campaign.is_active ? 'active' : 'inactive'}"></div>
                    <div>
                      <div style="font-weight:600">${esc(campaign.name)}</div>
                      <div class="text-muted mono" style="font-size:11px">${campaign.code}</div>
                    </div>
                  </div>
                </td>
                <td><span class="pill pill-${campaign.source || 'muted'}">${getSourceIcon(campaign.source)} ${getSourceLabel(campaign.source)}</span></td>
                <td style="text-align:right">${campaign.cost > 0 ? num(campaign.cost) : '—'}</td>
                <td style="text-align:right">${campaign.clicks || '—'}</td>
                <td style="text-align:right">${campaign.registrations || '—'}</td>
                <td style="text-align:right">${campaign.payments || '—'}</td>
                <td style="text-align:right">${campaign.revenue > 0 ? num(campaign.revenue) : '—'}</td>
                <td style="text-align:right">
                  ${campaign.roi === Infinity ? '<span class="roi-badge success">∞</span>' : 
                    campaign.roi > 50 ? `<span class="roi-badge success">+${campaign.roi.toFixed(0)}%</span>` :
                    campaign.roi > 0 ? `<span class="roi-badge warning">+${campaign.roi.toFixed(0)}%</span>` :
                    campaign.roi < -50 ? `<span class="roi-badge danger">${campaign.roi.toFixed(0)}%</span>` :
                    '<span class="roi-badge muted">0%</span>'
                  }
                </td>
                <td style="text-align:right">${campaign.avgTicket > 0 ? num(campaign.avgTicket) : '—'}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>

    ${Object.keys(sourceStats).length > 1 ? `
    <div class="card mt-3">
      <div class="card-head">
        <div class="card-title">📊 Источники трафика</div>
      </div>
      <div class="card-pad">
        <div class="source-grid">
          ${Object.entries(sourceStats).map(([source, stats]) => {
            const roi = stats.cost > 0 ? ((stats.revenue - stats.cost) / stats.cost * 100) : 0;
            return `
              <div class="source-card">
                <div class="source-icon">${getSourceIcon(source)}</div>
                <div class="source-label">${getSourceLabel(source)}</div>
                <div class="source-stats">
                  <div class="source-stat">${stats.campaigns} кампаний</div>
                  <div class="source-stat">${num(stats.cost)} ₽ / ${num(stats.revenue)} ₽</div>
                  <div class="source-stat roi-${roi > 0 ? 'positive' : 'negative'}">${roi > 0 ? '+' : ''}${roi.toFixed(0)}% ROI</div>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    </div>` : ''}
  `;

  // Add search functionality
  $('#campaignSearch').addEventListener('input', filterCampaigns);
}

function filterCampaigns() {
  const query = $('#campaignSearch').value.toLowerCase();
  const rows = $$('#campaignsTable tbody tr');
  rows.forEach(row => {
    const text = row.textContent.toLowerCase();
    row.style.display = text.includes(query) ? '' : 'none';
  });
}

function getSourceIcon(source) {
  const icons = {
    vk: '🔵',
    instagram: '🟣', 
    telegram: '🔷',
    youtube: '🔴',
    direct: '🌐',
    other: '📱'
  };
  return icons[source] || icons.other;
}

function getSourceLabel(source) {
  const labels = {
    vk: 'ВКонтакте',
    instagram: 'Instagram', 
    telegram: 'Telegram',
    youtube: 'YouTube',
    direct: 'Direct',
    other: 'Другое'
  };
  return labels[source] || 'Другое';
}

function openCampaignModal() {
  clearCampaignModal();
  openModal('campaignModal');
}

function clearCampaignModal() {
  $('#campaignModalTitle').textContent = 'Новая кампания';
  $('#campCode').value = '';
  $('#campName').value = '';
  $('#campSource').value = 'vk';
  $('#campType').value = 'post';
  $('#campCreator').value = '';
  if ($('#campSourceUrl')) $('#campSourceUrl').value = '';
  $('#campCost').value = '';
  $('#campBonusDays').value = '7';
  $('#campWelcome').value = '';
  $('#campNote').value = '';
  $('#campActive').checked = true;
}

async function saveCampaign() {
  const code = $('#campCode').value.trim().toLowerCase();
  const name = $('#campName').value.trim();
  const source = $('#campSource').value;
  const type = $('#campType').value;
  const creator = $('#campCreator').value.trim() || null;
  const cost = parseFloat($('#campCost').value) || 0;
  const bonusDays = parseInt($('#campBonusDays').value) || 7;
  const welcomeText = $('#campWelcome').value.trim() || null;
  const note = $('#campNote').value.trim() || null;
  const isActive = $('#campActive').checked;

  // Validation
  if (!code || code.length < 3) {
    toast('Введите код кампании (минимум 3 символа)', 'error');
    return;
  }
  if (!/^[a-z0-9_-]+$/.test(code)) {
    toast('Код может содержать только a-z, 0-9, _ и -', 'error');
    return;
  }
  if (!name) {
    toast('Введите название кампании', 'error');
    return;
  }
  if ((state.campaigns || []).some(c => c.code === code)) {
    toast('Кампания с таким кодом уже существует', 'error');
    return;
  }
  if (bonusDays < 1 || bonusDays > 365) {
    toast('Бонус дней должен быть от 1 до 365', 'error');
    return;
  }

  try {
    const sourceUrl = ($('#campSourceUrl')?.value || '').trim() || null;
    const campaignData = {
      code,
      name,
      source,
      type,
      creator,
      cost,
      bonus_days: bonusDays,
      welcome_text: welcomeText,
      note,
      is_active: isActive,
      source_url: sourceUrl,
    };

    const created = await sbInsert('campaigns', campaignData);
    if (!state.campaigns) state.campaigns = [];
    state.campaigns.unshift(created[0]);
    
    closeModal('campaignModal');
    renderMarketing();
    
    const testUrl = `https://t.me/MaxArtVPN_bot?start=${code}`;
    toast(`Кампания ${code} создана! Тестовая ссылка скопирована в буфер обмена`, 'success');
    navigator.clipboard?.writeText(testUrl);
    
  } catch (e) {
    toast('Ошибка создания кампании: ' + e.message, 'error');
  }
}

/* === CAMPAIGN DETAILS 2026-05 === */
function showCampaignDetails(campaignCode) {
  const c = (state.campaigns || []).find(x => x.code === campaignCode);
  if (!c) { toast('Кампания не найдена', 'error'); return; }

  // Воронка
  const campUsers = (state.users || []).filter(u => u.campaign_code === campaignCode);
  const userIds = new Set(campUsers.map(u => u.user_id));
  const clicks = (state.campaignClicks || []).filter(cl => cl.campaign_code === campaignCode).length;
  const registered = campUsers.length;

  const campDevices = (state.userDevices || []).filter(d => userIds.has(d.user_id));
  const connectedUserIds = new Set(campDevices.map(d => d.user_id));
  const connectedUsers = connectedUserIds.size;
  const totalDevices = campDevices.length;

  const campPayments = (state.payments || []).filter(p => p.campaign_code === campaignCode && p.status === 'succeeded');
  const paidUsers = new Set(campPayments.map(p => p.user_id)).size;

  // Разбивка устройств по моделям
  const modelCounts = {};
  campDevices.forEach(d => {
    const m = d.device_model || (d.device_type === 'ios' ? 'iPhone/iPad' : d.device_type === 'android' ? 'Android' : 'Устройство');
    modelCounts[m] = (modelCounts[m] || 0) + 1;
  });
  const modelsHtml = Object.keys(modelCounts).length
    ? Object.entries(modelCounts).sort((a,b)=>b[1]-a[1]).map(([m,n]) =>
        `<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--bd)">
           <span>${esc(m)}</span><span class="mono" style="color:var(--accent)">${n}</span>
         </div>`).join('')
    : '<div class="text-muted">Пока нет подключённых устройств</div>';

  const pct = (n, base) => base > 0 ? Math.round(n / base * 100) : 0;
  const funnelRow = (label, val, base, color) => `
    <div style="display:flex;align-items:center;gap:10px;padding:6px 0">
      <div style="width:130px;color:var(--fg-2)">${label}</div>
      <div style="flex:1;background:var(--bg-3);border-radius:6px;overflow:hidden;height:22px;position:relative">
        <div style="width:${base>0?pct(val,base):0}%;background:${color};height:100%;min-width:2px"></div>
        <div style="position:absolute;top:0;left:8px;line-height:22px;font-size:12px;font-weight:600">${val}${base>0?' ('+pct(val,base)+'%)':''}</div>
      </div>
    </div>`;

  const tgLink = `https://t.me/MaxArtVPN_bot?start=${c.code}`;
  const sourceUrl = c.source_url || '';

  const body = `
    <div class="field-row">
      <div class="field"><label class="label">Код кампании</label>
        <input class="input mono" value="${esc(c.code)}" disabled></div>
      <div class="field"><label class="label">Название</label>
        <input class="input" value="${esc(c.name || '')}" disabled></div>
    </div>
    <div class="field-row">
      <div class="field"><label class="label">Источник</label>
        <input class="input" value="${esc(getSourceLabel(c.source))}" disabled></div>
      <div class="field"><label class="label">Бонус дней</label>
        <input class="input mono" value="${c.bonus_days ?? ''}" disabled></div>
    </div>
    <div class="field-row">
      <div class="field"><label class="label">У кого купили</label>
        <input class="input" value="${esc(c.creator || '—')}" disabled></div>
      <div class="field"><label class="label">Стоимость, ₽</label>
        <input class="input mono" value="${c.cost ?? 0}" disabled></div>
    </div>
    <div class="field">
      <label class="label">UTM-ссылка для размещения</label>
      <div style="display:flex;gap:8px">
        <input class="input mono" id="cdTgLink" value="${tgLink}" readonly>
        <button class="btn btn-ghost" onclick="navigator.clipboard?.writeText('${tgLink}');toast('Ссылка скопирована')">Копировать</button>
      </div>
    </div>
    ${sourceUrl ? `
    <div class="field">
      <label class="label">Канал/группа размещения</label>
      <div style="display:flex;gap:8px">
        <input class="input" value="${esc(sourceUrl)}" disabled>
        <a class="btn btn-primary" href="${esc(sourceUrl)}" target="_blank" rel="noopener">Открыть →</a>
      </div>
    </div>` : ''}

    <div class="divider"></div>
    <div class="card-title" style="margin-bottom:8px">📊 Воронка</div>
    ${funnelRow('Перешли', clicks, clicks || registered, 'var(--accent-3, #888)')}
    ${funnelRow('Зарегались', registered, clicks || registered, 'var(--accent, #4c7be5)')}
    ${funnelRow('Подключили', connectedUsers, registered, '#2ecc71')}
    ${funnelRow('Оплатили', paidUsers, registered, '#f1c40f')}

    <div class="divider"></div>
    <div class="card-title" style="margin-bottom:8px">📱 Подключённые устройства (${totalDevices})</div>
    ${modelsHtml}

    ${c.welcome_text ? `<div class="divider"></div>
    <div class="field"><label class="label">Welcome-текст</label>
      <textarea class="textarea" rows="3" disabled>${esc(c.welcome_text)}</textarea></div>` : ''}
    ${c.note ? `<div class="field"><label class="label">Заметки</label>
      <textarea class="textarea" rows="2" disabled>${esc(c.note)}</textarea></div>` : ''}
  `;

  // Рисуем модал: обёртка modal-bg (id на ней) + вложенный .modal
  let modal = document.getElementById('campaignViewModal');
  if (!modal) {
    modal = document.createElement('div');
    modal.className = 'modal-bg';
    modal.id = 'campaignViewModal';
    // Закрытие по клику на фон (вне .modal)
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeModal('campaignViewModal');
    });
    document.body.appendChild(modal);
  }
  modal.innerHTML = `
    <div class="modal lg">
      <div class="modal-head">
        <div class="modal-title">👁 Кампания: ${esc(c.name || c.code)}</div>
        <button class="icon-btn" onclick="closeModal('campaignViewModal')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
        </button>
      </div>
      <div class="modal-body">${body}</div>
      <div class="modal-foot">
        <button class="btn btn-ghost" onclick="closeModal('campaignViewModal')">Закрыть</button>
      </div>
    </div>`;
  openModal('campaignViewModal');
}

