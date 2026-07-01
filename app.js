/* === MKT FIX === === REBRAND v4 === цвета Deep Ocean применены */
/* =====================================================================
   TuVPN Admin v3 — Linear-style, command-palette, keyboard-first
   ===================================================================== */

/* ===================== CONFIG ===================== */
const PROXY_URL = 'https://admin.tuvpn.ru';
const PAGE_SIZE = 50;
/* ===================== STATE ===================== */
const state = {
  myPermissions: [],
  isSuperadmin: false,
  adminUsers: [],
  adminRoles: [],
  financeExpenses: [],
  financeInvestments: [],
  financePlanned: [],
  financeSummary: null,
  users: [], subs: [], payments: [], promos: [], promoUses: [],
  refs: [], tickets: [], supportAdmins: [], servers: [],
  currentChart: 'revenue',
  chartInstance: null,
  currentPage: 'dashboard',
  usersPage: 0,
  subsPage: 0,
  cmdActiveIdx: 0,
  cmdItems: [],
  loaded: false,
  keySeq: '',
  keySeqTimer: null,
};

/* === PAGINATION STATE === */
const pagination = {
  users: { limit: 50, offset: 0, total: 0, loading: false, hasMore: true },
  subs: { limit: 50, offset: 0, total: 0, loading: false, hasMore: true },
  payments: { limit: 50, offset: 0, total: 0, loading: false, hasMore: true },
  promos: { limit: 50, offset: 0, total: 0, loading: false, hasMore: true },
  refs: { limit: 50, offset: 0, total: 0, loading: false, hasMore: true },
  tickets: { limit: 50, offset: 0, total: 0, loading: false, hasMore: true }
};

function resetPagination(type) {
  pagination[type].offset = 0;
  pagination[type].hasMore = true;
  state[type] = [];
}

function updatePaginationState(type, data) {
  const pag = pagination[type];
  pag.total = data.total || 0;
  pag.loading = false;
  
  // Проверяем есть ли еще данные для загрузки
  if (pag.offset + data.data.length >= pag.total) {
    pag.hasMore = false;
  } else {
    pag.hasMore = true;
  }
  
  // Добавляем новые данные к существующим
  if (pag.offset === 0) {
    state[type] = data.data; // Первая загрузка - заменяем
  } else {
    state[type] = [...state[type], ...data.data]; // Дополнительная загрузка - добавляем
  }
}

function showLoadMoreButton(type, containerSelector) {
  const container = document.querySelector(containerSelector);
  if (!container) return;
  
  let loadMoreDiv = container.querySelector('.load-more-section');
  if (!loadMoreDiv) {
    loadMoreDiv = document.createElement('div');
    loadMoreDiv.className = 'load-more-section';
    loadMoreDiv.style.cssText = 'text-align: center; padding: 20px; margin-top: 20px;';
    container.appendChild(loadMoreDiv);
  }
  
  const pag = pagination[type];
  if (pag.hasMore && !pag.loading) {
    loadMoreDiv.innerHTML = `
      <button class="btn btn-ghost" onclick="loadMore('${type}')" style="min-width: 140px;">
        ${ICONS.arrowDown} Загрузить еще
      </button>
      <div style="margin-top: 8px; color: var(--text-muted); font-size: 12px;">
        Показано ${state[type].length} из ${pag.total}
      </div>
    `;
  } else if (pag.loading) {
    loadMoreDiv.innerHTML = `
      <div class="loading-indicator" style="display: flex; align-items: center; justify-content: center; gap: 8px;">
        <div class="spinner"></div>
        <span style="color: var(--text-muted);">Загрузка...</span>
      </div>
    `;
  } else {
    loadMoreDiv.innerHTML = `
      <div style="color: var(--text-muted); font-size: 12px;">
        Показаны все записи (${state[type].length})
      </div>
    `;
  }
}

function loadMore(type) {
  const pag = pagination[type];
  if (pag.loading || !pag.hasMore) return;
  
  pag.offset += pag.limit;
  
  if (type === 'users') {
    loadUsers(true);
  } else if (type === 'subs') {
    loadSubs(true);
  }
}

window.loadMore = loadMore;

function renderPaginationControls(page, totalPages, total, type) {
  if (totalPages <= 1) return '';
  const start = page * PAGE_SIZE + 1;
  const end = Math.min((page + 1) * PAGE_SIZE, total);
  return `
    <div class="pagination">
      <button class="btn btn-ghost btn-sm" data-pg-prev data-pg-type="${type}" ${page === 0 ? 'disabled' : ''}>← Пред.</button>
      <span class="pagination-info">${start}–${end} из ${total}</span>
      <button class="btn btn-ghost btn-sm" data-pg-next data-pg-type="${type}" ${page >= totalPages - 1 ? 'disabled' : ''}>След. →</button>
    </div>`;
}

function bindPaginationClicks(containerId, type, renderFn) {
  const el = $(`#${containerId}`);
  if (!el) return;
  const prev = el.querySelector('[data-pg-prev]');
  const next = el.querySelector('[data-pg-next]');
  if (prev) prev.addEventListener('click', () => { state[`${type}Page`]--; renderFn(); });
  if (next) next.addEventListener('click', () => { state[`${type}Page`]++; renderFn(); });
}

/* ============================================================ */
/* === RBAC v2 — единая логика прав ========================== */
/* ============================================================ */

// Грузится с /admin-api/my-permissions при старте.
// state.me — текущий админ; state.isSuperadmin; state.myPermissions Set;
// state.sections — реестр разделов с реестром прав; state.allPermissions — все возможные права.

async function loadMyPermissions() {
  try {
    const r = await fetch('/admin-api/my-permissions', { credentials: 'include' });
    if (!r.ok) { console.warn('my-permissions HTTP', r.status); return; }
    const data = await r.json();
    state.me = { user_id: data.user_id };
    state.isSuperadmin = !!data.is_superadmin;
    state.myPermissions = new Set(data.permissions || []);
    state.sections = data.sections || {};
    state.allPermissions = data.all_permissions || [];
    // Берём имя из users (для KPI «Суперадмин: ...»)
    try {
      const u = (state.users || []).find(x => x.user_id === data.user_id);
      if (u) state.me.name = [u.first_name, u.last_name].filter(Boolean).join(' ') || u.username;
    } catch(e){}
  } catch(e) {
    console.warn('loadMyPermissions:', e);
  }
}

function hasPermission(perm) {
  if (!perm) return true;
  if (state.isSuperadmin) return true;
  return state.myPermissions && state.myPermissions.has(perm);
}

function canViewSection(pageKey) {
  if (state.isSuperadmin) return true;
  const map = {
    dashboard: 'view_dashboard', users: 'view_users', subs: 'view_subs',
    payments: 'view_payments', promos: 'view_promos', marketing: 'view_marketing',
    referrals: 'view_referrals', analytics: 'view_analytics', broadcast: 'view_broadcast',
    monitor: 'view_monitor', tickets: 'view_tickets', servers: 'view_servers',
    settings: 'view_settings', finance: 'view_finance', roles: 'view_roles',
    audit: 'superadmin', watchlist: 'superadmin',
  };
  const perm = map[pageKey];
  if (!perm) return true;
  return hasPermission(perm);
}

// Скрытие nav-пунктов в зависимости от прав
function applyNavVisibility() {
  document.querySelectorAll('.nav-item[data-page]').forEach(el => {
    const page = el.dataset.page;
    if (canViewSection(page)) {
      el.style.display = '';
    } else {
      el.style.display = 'none';  // мягкое скрытие, не удаляем — на случай если права обновятся
    }
  });
}

// Глобальный перехват кликов: кнопки с data-perm проверяются
function installPermClickGuard() {
  if (window._permGuardInstalled) return;
  window._permGuardInstalled = true;
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-perm]');
    if (!btn) return;
    const perm = btn.dataset.perm;
    if (hasPermission(perm)) return;
    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();
    showNoPermModal(perm);
  }, true);  // capture phase, чтобы перехватить раньше других обработчиков
}

function showNoPermModal(perm) {
  // подставляем красивое название действия из state.sections
  let actionLabel = perm;
  if (state.sections) {
    for (const sec of Object.values(state.sections)) {
      if (sec.actions && sec.actions[perm]) { actionLabel = sec.actions[perm]; break; }
      if (sec.view_perm === perm) { actionLabel = sec.title; break; }
    }
  }
  const lbl = document.getElementById('noPermAction');
  if (lbl) lbl.textContent = actionLabel;
  const key = document.getElementById('noPermKey');
  if (key) key.textContent = perm;
  openModal('noPermModal');
}
window.showNoPermModal = showNoPermModal;
window.hasPermission = hasPermission;
window.canViewSection = canViewSection;
window.applyNavVisibility = applyNavVisibility;
window.loadMyPermissions = loadMyPermissions;
window.installPermClickGuard = installPermClickGuard;

/* === END RBAC v2 === */

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

// Скоринг рефералов: главный вес — оплатили, второй — конверсия, третий — привёл

// Загружаем права текущего админа



function referralScore(r) {
  const brought = r.brought || 0;
  const paid = r.paid || 0;
  if (brought === 0) return 0;
  const conversion = paid / brought;
  return (paid * 1000) + (conversion * 100) + (brought * 0.1);
}

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

/* ===================== AUTH (OTP) ===================== */
let _otpTgId = null;  // tg_id введённый на шаге 1
let _otpCooldownTimer = null;

async function checkAuth() {
  try {
    const r = await fetch(PROXY_URL + '/admin-api/auth/me', { credentials: 'include' });
    if (r.status === 200) {
      const data = await r.json();
      if (data.success) return data;
    }
  } catch (e) {}
  return null;
}

async function requestOTPCode() {
  const inp = $('#loginTgIdInput');
  const tgId = (inp && inp.value.trim()) || '';
  if (!tgId || !/^\d+$/.test(tgId)) {
    showLoginError('Введите числовой Telegram ID');
    return;
  }
  hideLoginError();
  const btn = $('#loginRequestBtn');
  if (btn) { btn.disabled = true; btn.textContent = 'Отправляем...'; }
  try {
    const r = await fetch(PROXY_URL + '/admin-api/auth/request_code', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tg_id: parseInt(tgId, 10) }),
    });
    const d = await r.json();
    if (r.status === 429) {
      const wait = d.wait_seconds || 60;
      showLoginError(`Подождите ${wait} сек. перед повторным запросом`);
      startCooldown(wait);
      return;
    }
    if (!d.success) {
      showLoginError('Пользователь не найден');
      return;
    }
    _otpTgId = parseInt(tgId, 10);
    $('#loginStep1').style.display = 'none';
    $('#loginStep2').style.display = 'block';
    const ci = $('#loginCodeInput');
    if (ci) { ci.value = ''; ci.focus(); }
  } catch (e) {
    showLoginError('Ошибка сети: ' + e.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Получить код'; }
  }
}

async function verifyOTPCode() {
  const code = ($('#loginCodeInput') && $('#loginCodeInput').value.trim()) || '';
  if (code.length !== 6) {
    showLoginError('Код должен состоять из 6 цифр');
    return;
  }
  if (!_otpTgId) { goLoginStep1(); return; }
  hideLoginError();
  const btn = $('#loginVerifyBtn');
  if (btn) { btn.disabled = true; btn.textContent = 'Проверяем...'; }
  try {
    const r = await fetch(PROXY_URL + '/admin-api/auth/verify_code', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tg_id: _otpTgId, code }),
    });
    const data = await r.json();
    if (data.success) {
      showApp();
    } else {
      const msgs = {
        expired: 'Код истёк. Запросите новый.',
        too_many_attempts: 'Слишком много попыток. Запросите новый код.',
        invalid_code: data.remaining != null ? `Неверный код. Осталось попыток: ${data.remaining}` : 'Неверный код.',
        db_error: 'Ошибка сервера. Попробуйте снова.',
      };
      showLoginError(msgs[data.error] || 'Ошибка входа');
      if (data.error === 'expired' || data.error === 'too_many_attempts') goLoginStep1();
    }
  } catch (e) {
    showLoginError('Ошибка сети: ' + e.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Войти'; }
  }
}

function goLoginStep1() {
  _otpTgId = null;
  hideLoginError();
  if (_otpCooldownTimer) { clearInterval(_otpCooldownTimer); _otpCooldownTimer = null; }
  $('#loginStep1').style.display = 'block';
  $('#loginStep2').style.display = 'none';
  const btn = $('#loginRequestBtn');
  if (btn) { btn.disabled = false; btn.textContent = 'Получить код'; }
}

function startCooldown(seconds) {
  if (_otpCooldownTimer) clearInterval(_otpCooldownTimer);
  const btn = $('#loginRequestBtn');
  let left = seconds;
  if (btn) { btn.disabled = true; btn.textContent = `Повторить через ${left} сек`; }
  _otpCooldownTimer = setInterval(() => {
    left--;
    if (left <= 0) {
      clearInterval(_otpCooldownTimer);
      _otpCooldownTimer = null;
      if (btn) { btn.disabled = false; btn.textContent = 'Получить код'; }
    } else {
      if (btn) btn.textContent = `Повторить через ${left} сек`;
    }
  }, 1000);
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
  if (!await showConfirm({ title: 'Выход', message: 'Выйти из админки?', okText: 'Выйти', danger: true })) return;
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


// ============================================================
// РАЗДЕЛ: РОЛИ И ДОСТУПЫ (только суперадмин)
// ============================================================

const PERMISSION_LABELS = {
  view_users: '👁 Пользователи',
  view_subscriptions: '👁 Подписки',
  view_payments: '👁 Платежи',
  view_referrals: '👁 Рефералы',
  view_promocodes: '👁 Промокоды',
  view_campaigns: '👁 Кампании',
  view_tickets: '👁 Тикеты',
  view_servers: '👁 Серверы',
  view_analytics: '👁 Аналитика',
  view_finance: '💰 Финансы',
  view_broadcasts: '👁 Рассылки',
  view_settings: '👁 Настройки',
  grant_subscription: '✅ Выдать подписку',
  revoke_subscription: '❌ Отозвать подписку',
  send_broadcast: '📢 Отправить рассылку',
  manage_promocodes: '🏷 Управлять промокодами',
  manage_servers: '🖥 Управлять серверами',
  close_ticket: '🎫 Закрыть тикет',
  assign_ticket: '🎫 Взять тикет',
  edit_finance: '💰 Редактировать финансы',
  manage_roles: '🔑 Управлять ролями',
};









function editAdminPerms(userId) {
  const admin = state.adminUsers.find(a=>a.user_id===userId);
  if (!admin) return;
  const rolePerms = state.adminRoles.find(r=>r.id===admin.role_id)?.permissions || [];
  const added = admin.added_permissions || [];
  const removed = admin.removed_permissions || [];

  let groupsHtml = '';
  for (const [groupName, perms] of Object.entries(PERM_GROUPS)) {
    groupsHtml += `<div class="perm-group"><div class="perm-group-title">${groupName}</div><div class="perm-checkboxes">`;
    for (const perm of perms) {
      const fromRole = rolePerms.includes(perm);
      const isAdded = added.includes(perm);
      const isRemoved = removed.includes(perm);
      const effective = (fromRole && !isRemoved) || isAdded;
      const label = PERMISSION_LABELS[perm]||perm;
      const hint = fromRole ? ' (из роли)' : '';
      groupsHtml += `<label class="perm-check ${fromRole?'from-role':''}"><input type="checkbox" value="${perm}" ${effective?'checked':''}> ${label}<span class="perm-hint">${hint}</span></label>`;
    }
    groupsHtml += '</div></div>';
  }

  const roleOptions = state.adminRoles.map(r =>
    `<option value="${r.id}" ${r.id===admin.role_id?'selected':''}>${r.name}</option>`
  ).join('');

  showModal(`
    <div class="modal-header">⚙️ Права: ${admin.full_name||admin.username}</div>
    <div class="modal-body">
      <div class="form-group">
        <label>Роль</label>
        <select id="admin-role-select" class="input-field">
          <option value="">— Без роли —</option>
          ${roleOptions}
        </select>
      </div>
      <div class="form-group">
        <label>Права (итоговые, с учётом роли и доп. прав)</label>
        <div id="admin-perms-container">${groupsHtml}</div>
      </div>
      <div class="form-group">
        <label>
          <input type="checkbox" id="admin-active-check" ${admin.is_active?'checked':''}> Активен
        </label>
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Отмена</button>
      <button class="btn btn-primary" onclick="saveAdminPerms(${userId})">Сохранить</button>
    </div>
  `);
}


// === END TG ADMIN AUTH ===

/* ===================== DATA LOAD ===================== */
async function loadAll() {
  // RBAC v2: грузим права + строим видимость nav + ставим click-guard
  try { await loadMyPermissions(); } catch(e) { console.warn('loadMyPermissions failed:', e); }
  try { applyNavVisibility(); } catch(e) {}
  try { installPermClickGuard(); } catch(e) {}
  if (state.isSuperadmin) {
    document.querySelectorAll('.superadmin-only').forEach(el => el.style.display = '');
  }

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
    updateSidebarProfile();
    fetchAlerts();
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
  broadcast:  { sec: 'Маркетинг', title: 'Рассылка' },
  
  monitor:    { sec: 'Инфраструктура', title: 'Мониторинг' },
  analytics:  { sec: 'Маркетинг', title: 'Аналитика' },
  finance:    { sec: 'Система', title: 'Финансы' },
  roles:      { sec: 'Система', title: 'Роли и доступы' },
  audit:      { sec: 'Инструменты', title: 'Диагностика' },
  watchlist:  { sec: 'Инструменты', title: 'VIP-мониторинг' },
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
  if (page === 'broadcast') { renderBroadcast(); return; }
  if (page === 'monitor') { renderMonitor(); return; }
  if (page === 'analytics') { renderAnalytics(); return; }
  if (page === 'finance') { if (typeof renderFinancePage === 'function') renderFinancePage(); return; }
  if (page === 'roles') { if (typeof renderRolesPage === 'function') renderRolesPage(); return; }
  if (page === 'audit') { /* audit_frontend.js handles this */ return; }
  if (page === 'watchlist') { /* audit_frontend.js handles this */ return; }
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
  const openTickets = state.tickets.filter(t => t.status === 'open' || t.status === 'in_progress').length;
  const tc = $('#navTicketsCount');
  tc.textContent = openTickets;
  tc.classList.toggle('nav-count-alert-active', openTickets > 0);
  $('#navServersCount').textContent = state.servers.length;
}

function updateSidebarProfile() {
  const me = state.me;
  if (!me) return;
  let name = me.name;
  if (!name && state.users) {
    const u = state.users.find(x => x.user_id === me.user_id);
    if (u) name = [u.first_name, u.last_name].filter(Boolean).join(' ') || u.username;
  }
  if (!name) name = 'Admin';
  const initial = (name[0] || 'A').toUpperCase();
  const avatarEl = $('#sidebarAvatar');
  const nameEl = $('#sidebarName');
  if (avatarEl) avatarEl.textContent = initial;
  if (nameEl) nameEl.textContent = name;
  if (state.isSuperadmin) {
    const subEl = $('#sidebarSub');
    if (subEl) subEl.textContent = 'суперадмин';
  }
}

async function fetchAlerts() {
  try {
    const r = await proxy('/admin-api/alerts');
    if (!r.success) return;
    const alerts = r.alerts || [];
    const badge = $('#bellBadge');
    const list = $('#alertsList');
    if (!badge || !list) return;
    const total = r.total || 0;
    if (total > 0) {
      badge.textContent = total;
      badge.style.display = '';
    } else {
      badge.style.display = 'none';
    }
    list.innerHTML = alerts.length
      ? alerts.map(a => {
          const icons = { tickets: '💬', receipt: '🧾', expiring: '⏰' };
          return `<div class="alert-item" onclick="goPage('${esc(a.page)}');closeAlertsDrop()">
            <span class="alert-ico">${icons[a.type] || '⚠️'}</span>
            <span class="alert-title">${esc(a.title)}</span>
            <svg class="alert-arr" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m9 18 6-6-6-6"/></svg>
          </div>`;
        }).join('')
      : '<div class="alerts-empty">Всё хорошо 👍</div>';
  } catch (e) {}
}

function closeAlertsDrop() {
  const d = $('#alertsDrop');
  if (d) d.style.display = 'none';
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

function showConfirm({ title = 'Подтвердить', message = '', okText = 'Подтвердить', cancelText = 'Отмена', danger = false } = {}) {
  return new Promise(resolve => {
    const modal = document.getElementById('confirmModal');
    document.getElementById('confirmTitle').textContent = title;
    document.getElementById('confirmMessage').textContent = message;
    const okBtn = document.getElementById('confirmOk');
    const cancelBtn = document.getElementById('confirmCancel');
    okBtn.textContent = okText;
    okBtn.className = 'btn ' + (danger ? 'btn-danger' : 'btn-primary');
    cancelBtn.textContent = cancelText;

    let _mdTarget = null;
    function cleanup(result) {
      modal.classList.remove('open');
      okBtn.removeEventListener('click', onOk);
      cancelBtn.removeEventListener('click', onCancel);
      modal.removeEventListener('mousedown', onMd);
      modal.removeEventListener('click', onBd);
      document.removeEventListener('keydown', onKey);
      resolve(result);
    }
    function onOk() { cleanup(true); }
    function onCancel() { cleanup(false); }
    function onMd(e) { _mdTarget = e.target; }
    function onBd(e) { if (e.target === modal && _mdTarget === modal) cleanup(false); _mdTarget = null; }
    function onKey(e) { if (e.key === 'Escape') cleanup(false); }

    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
    modal.addEventListener('mousedown', onMd);
    modal.addEventListener('click', onBd);
    document.addEventListener('keydown', onKey);
    modal.classList.add('open');
    setTimeout(() => cancelBtn.focus(), 50);
  });
}

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

  });
}

/* ===================== MODAL BACKDROP CLICKS & CLOSE BUTTONS ===================== */
function bindModalClicks() {
  $$('.modal-bg').forEach(bg => {
    let _mdTarget = null;
    bg.addEventListener('mousedown', (e) => { _mdTarget = e.target; });
    bg.addEventListener('click', (e) => {
      // закрываем только если mousedown тоже был на фоне (не drag из модалки)
      if (e.target === bg && _mdTarget === bg) bg.classList.remove('open');
      _mdTarget = null;
    });
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
  // Login OTP
  const _lrb = $('#loginRequestBtn'); if (_lrb) _lrb.addEventListener('click', requestOTPCode);
  const _lvb = $('#loginVerifyBtn'); if (_lvb) _lvb.addEventListener('click', verifyOTPCode);
  const _lbb = $('#loginBackBtn'); if (_lbb) _lbb.addEventListener('click', goLoginStep1);
  // Enter → submit на обоих шагах
  const _lid = $('#loginTgIdInput');
  if (_lid) _lid.addEventListener('keydown', e => { if (e.key === 'Enter') requestOTPCode(); });
  const _lci = $('#loginCodeInput');
  if (_lci) {
    _lci.addEventListener('keydown', e => { if (e.key === 'Enter') verifyOTPCode(); });
    // Автосабмит при вводе 6 цифр
    _lci.addEventListener('input', e => {
      const v = e.target.value.replace(/\D/g, '').slice(0, 6);
      e.target.value = v;
      if (v.length === 6) verifyOTPCode();
    });
  }

  // Sidebar nav
  $$('.nav-item').forEach(n => n.addEventListener('click', () => goPage(n.dataset.page)));

  // Top actions
  $('#reloadBtn').addEventListener('click', () => { loadAll(); toast('Обновляем...', 'success', { duration: 1500 }); });
  $('#logoutBtn').addEventListener('click', doLogout);
  $('#quickGrantBtn').addEventListener('click', () => { $('#grantUid').value = ''; $('#grantUserHint').textContent = 'Пользователь должен сначала запустить бот.'; openModal('grantModal'); });
  $('#cmdTrigger').addEventListener('click', openCmd);

  // Колокольчик алертов
  const bellBtn = $('#bellBtn');
  const alertsDrop = $('#alertsDrop');
  if (bellBtn && alertsDrop) {
    bellBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const isOpen = alertsDrop.style.display !== 'none';
      alertsDrop.style.display = isOpen ? 'none' : '';
      if (!isOpen) fetchAlerts();
    });
    document.addEventListener('click', (e) => {
      if (!$('#bellWrap').contains(e.target)) alertsDrop.style.display = 'none';
    });
  }

  // Cmd palette
  $('#cmdInput').addEventListener('input', renderCmdList);

  // Modals
  bindModalClicks();
  bindShortcuts();

  // Grant modal handlers
  $('#grantSubmit').addEventListener('click', grantSubscription);

  // Пресеты устройств
  document.addEventListener('click', e => {
    if (e.target.classList.contains('grant-dev-preset') && !e.target.disabled) {
      $('#grantDevices').value = e.target.dataset.val;
      document.querySelectorAll('.grant-dev-preset').forEach(b => b.classList.remove('btn-accent'));
      e.target.classList.add('btn-accent');
    }
    if (e.target.classList.contains('grant-days-preset') && !e.target.disabled) {
      $('#grantDays').value = e.target.dataset.val;
      document.querySelectorAll('.grant-days-preset').forEach(b => b.classList.remove('btn-accent'));
      e.target.classList.add('btn-accent');
    }
  });

  // Включаем/выключаем пресеты устройств вместе с чекбоксом
  const _gde = $('#grantDevicesEnable');
  if (_gde) _gde.addEventListener('change', function() {
    const dis = !this.checked;
    $('#grantDevices').disabled = dis;
    document.querySelectorAll('.grant-dev-preset').forEach(b => b.disabled = dis);
  });

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

    <div id="pulseBlock"></div>
    <div id="todayStatsBlock"></div>

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
  sparkline($('#sparkUsers'), sparkUsers, '#4fc4cf');
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

  // Live-пульс + сегодняшняя статистика
  renderDashboardPulse();
  renderTodayStats();
}

async function renderTodayStats() {
  const host = $('#todayStatsBlock');
  if (!host) return;
  host.innerHTML = '<div class="today-row today-row-loading"><span class="muted" style="font-size:12px">Загрузка статистики дня...</span></div>';
  try {
    const d = await proxy('/admin-api/analytics/today');
    if (!d.success) { host.innerHTML = ''; return; }

    function pctDelta(today, yesterday) {
      if (!yesterday) return today > 0 ? '+100%' : null;
      const delta = Math.round((today - yesterday) / yesterday * 100);
      return (delta >= 0 ? '+' : '') + delta + '%';
    }
    function deltaClass(today, yesterday) {
      if (!yesterday && today === 0) return 'flat';
      if (!yesterday) return 'up';
      return today >= yesterday ? 'up' : 'dn';
    }

    const revDelta = pctDelta(d.revenue_today, d.revenue_yesterday);
    const usersDelta = pctDelta(d.new_users_today, d.new_users_yesterday);

    host.innerHTML = `
      <div class="today-row">
        <div class="today-label">Сегодня</div>
        <div class="today-kpi">
          <div class="today-cell">
            <div class="today-val">${money(d.revenue_today)}</div>
            <div class="today-sub">выручка ${revDelta ? `<span class="kpi-delta-sm ${deltaClass(d.revenue_today, d.revenue_yesterday)}">${revDelta}</span>` : ''}</div>
          </div>
          <div class="today-cell">
            <div class="today-val">${d.payments_today}</div>
            <div class="today-sub">платежей</div>
          </div>
          <div class="today-cell">
            <div class="today-val">${d.new_users_today}</div>
            <div class="today-sub">новых юзеров ${usersDelta ? `<span class="kpi-delta-sm ${deltaClass(d.new_users_today, d.new_users_yesterday)}">${usersDelta}</span>` : ''}</div>
          </div>
          <div class="today-cell ${d.open_tickets > 0 ? 'today-cell-warn' : ''}">
            <div class="today-val">${d.open_tickets}</div>
            <div class="today-sub">открытых тикетов</div>
          </div>
          <div class="today-cell ${d.servers_offline > 0 ? 'today-cell-err' : ''}">
            <div class="today-val">${d.servers_offline}</div>
            <div class="today-sub">серверов offline</div>
          </div>
        </div>
      </div>`;
  } catch (e) { host.innerHTML = ''; }
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
  const color = kind === 'revenue' ? '#4fc4cf' : kind === 'payments' ? '#67e8f9' : '#c084fc';
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
          backgroundColor: '#0b1428', borderColor: 'rgba(120,160,220,0.18)', borderWidth: 1, padding: 8,
          titleColor: '#ecf3ff', bodyColor: '#afc3e0',
          titleFont: { family: 'Geist Mono', size: 11 },
          bodyFont: { family: 'Geist', size: 12, weight: 600 },
          callbacks: { label: ctx => kind === 'revenue' ? money(ctx.parsed.y) : num(ctx.parsed.y) },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: '#7290b8', font: { family: 'Geist Mono', size: 10 }, maxRotation: 0, autoSkipPadding: 30 }},
        y: { grid: { color: 'rgba(120,160,220,0.08)', drawBorder: false }, ticks: { color: '#7290b8', font: { family: 'Geist Mono', size: 10 }, callback: v => kind === 'revenue' ? (v >= 1000 ? (v/1000)+'k' : v) : v }},
      },
    },
  });
}

/* =====================================================================
   ====================== PAGE: USERS ============================
   ===================================================================== */
function renderUsers() {
  const campOptions = (state.campaigns || []).map(c =>
    `<option value="${esc(c.code)}">${esc(c.name || c.code)}</option>`).join('');

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
        <option value="active">Активная подписка</option>
        <option value="none">Без подписки</option>
        <option value="paid">Платящие</option>
        <option value="trial_only">Только триал</option>
        <option value="no_device">Без устройств</option>
        <option value="new_7d">Новые (7 дней)</option>
        <option value="is_referrer">Привлекли рефералов</option>
        <option value="referred">Пришли по реф.ссылке</option>
        <option value="bonus">С бонусными днями</option>
      </select>
      <select class="filter" id="usersCampaignFilter">
        <option value="all">Все источники</option>
        <option value="direct">Прямые (без UTM)</option>
        ${campOptions}
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
      <div class="tbl-pagination" id="usersPagination"></div>
    </div>
  `;
  $('#usersSearch').addEventListener('input', () => { state.usersPage = 0; renderUsersTable(); });
  $('#usersFilter').addEventListener('change', () => { state.usersPage = 0; renderUsersTable(); });
  $('#usersCampaignFilter').addEventListener('change', () => { state.usersPage = 0; renderUsersTable(); });
  renderUsersTable();
}

function renderUsersTable() {
  const filter = $('#usersFilter').value;
  const campFilter = ($('#usersCampaignFilter') || {}).value || 'all';
  const search = ($('#usersSearch').value || '').toLowerCase().trim();
  let users = state.users.slice();

  const now = new Date();
  const ago7d = new Date(now - 7 * 86400000);
  const paidSet = new Set(
    (state.payments || []).filter(p => p.status === 'succeeded').map(p => Number(p.user_id))
  );
  const deviceSet = new Set(
    (state.userDevices || []).filter(d => d.is_active).map(d => Number(d.user_id))
  );
  const referrerSet = new Set(
    (state.refs || []).map(r => Number(r.referrer_id))
  );

  users = users.filter(u => {
    const uid = Number(u.user_id);
    if (filter === 'active') return state.subs.some(s => Number(s.user_id) === uid && s.status === 'active' && new Date(s.expires_at) > now);
    if (filter === 'none') return !state.subs.some(s => Number(s.user_id) === uid && s.status === 'active');
    if (filter === 'paid') return paidSet.has(uid);
    if (filter === 'trial_only') return !paidSet.has(uid);
    if (filter === 'no_device') return !deviceSet.has(uid);
    if (filter === 'new_7d') return new Date(u.created_at) >= ago7d;
    if (filter === 'is_referrer') return referrerSet.has(uid);
    if (filter === 'referred') return u.referrer_id != null;
    if (filter === 'bonus') return (u.bonus_days || 0) > 0;
    return true;
  });

  if (campFilter !== 'all') {
    if (campFilter === 'direct') {
      users = users.filter(u => !u.campaign_code);
    } else {
      users = users.filter(u => u.campaign_code === campFilter);
    }
  }

  if (search) {
    users = users.filter(u => {
      const hay = [u.username, u.first_name, u.last_name, u.user_id].filter(Boolean).join(' ').toLowerCase();
      return hay.includes(search);
    });
  }

  const total = users.length;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (state.usersPage >= totalPages) state.usersPage = totalPages - 1;
  const page = state.usersPage;
  const pageUsers = users.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  $('#usersCounter').textContent = total + ' из ' + state.users.length;
  const tbody = $('#usersTbody');
  if (!users.length) {
    tbody.innerHTML = '<tr><td colspan="8"><div class="empty"><span class="emoji">🔍</span><div class="title">Ничего не найдено</div></div></td></tr>';
    const pg = $('#usersPagination'); if (pg) pg.innerHTML = '';
    return;
  }
  tbody.innerHTML = pageUsers.map(u => {
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

  // pagination controls
  const pg = $('#usersPagination');
  if (pg) pg.innerHTML = renderPaginationControls(page, totalPages, total, 'users');
  bindPaginationClicks('usersPagination', 'users', renderUsersTable);
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
      <div class="search">
        <svg class="ico" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.35-4.35"/></svg>
        <input id="subsSearch" placeholder="Поиск по имени, username, ID..." />
      </div>
      <select class="filter" id="subsFilter">
        <option value="active">Активные</option>
        <option value="today">Истекают сегодня</option>
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
      <select class="filter" id="subsExtraFilter">
        <option value="all">Доп. фильтр</option>
        <option value="no_device">Без устройств</option>
        <option value="long_term">Долгосрочные (90+ дн)</option>
        <option value="multi">Продлевались (2+)</option>
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
      <div class="tbl-pagination" id="subsPagination"></div>
    </div>
  `;
  $('#subsSearch').addEventListener('input', () => { state.subsPage = 0; renderSubsTable(); });
  $('#subsFilter').addEventListener('change', () => { state.subsPage = 0; renderSubsTable(); });
  $('#subsDevFilter').addEventListener('change', () => { state.subsPage = 0; renderSubsTable(); });
  $('#subsExtraFilter').addEventListener('change', () => { state.subsPage = 0; renderSubsTable(); });
  renderSubsTable();
}

function renderSubsTable() {
  const f = $('#subsFilter').value;
  const dev = $('#subsDevFilter').value;
  const extra = ($('#subsExtraFilter') || {}).value || 'all';
  const searchEl = $('#subsSearch');
  const search = (searchEl ? searchEl.value || '' : '').toLowerCase().trim();
  let subs = state.subs.slice();
  const now = new Date();
  const today = now.toISOString().slice(0, 10);

  if (f === 'active') subs = subs.filter(s => s.status === 'active' && new Date(s.expires_at) > now);
  else if (f === 'today') subs = subs.filter(s => s.status === 'active' && s.expires_at.slice(0, 10) === today);
  else if (f === 'expiring') subs = subs.filter(s => s.status === 'active' && daysLeft(s.expires_at) >= 0 && daysLeft(s.expires_at) <= 3);
  else if (f === 'expired') subs = subs.filter(s => s.status !== 'active' || new Date(s.expires_at) <= now);
  if (dev !== 'all') subs = subs.filter(s => Number(s.devices) === Number(dev));

  if (extra !== 'all') {
    const deviceSet = new Set(
      (state.userDevices || []).filter(d => d.is_active).map(d => Number(d.user_id))
    );
    // для multi: считаем сколько записей в subs у каждого user_id
    const subCountMap = {};
    (state.subs || []).forEach(s => { subCountMap[s.user_id] = (subCountMap[s.user_id] || 0) + 1; });

    if (extra === 'no_device') subs = subs.filter(s => !deviceSet.has(Number(s.user_id)));
    else if (extra === 'long_term') subs = subs.filter(s => daysLeft(s.expires_at) >= 90);
    else if (extra === 'multi') subs = subs.filter(s => (subCountMap[s.user_id] || 0) >= 2);
  }
  if (search) {
    subs = subs.filter(s => {
      const u = userById(s.user_id);
      const hay = [u && u.username, u && u.first_name, u && u.last_name, s.user_id].filter(Boolean).join(' ').toLowerCase();
      return hay.includes(search);
    });
  }
  subs.sort((a, b) => new Date(a.expires_at) - new Date(b.expires_at));

  const total = subs.length;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (state.subsPage >= totalPages) state.subsPage = totalPages - 1;
  const page = state.subsPage;
  const pageSubs = subs.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  $('#subsCounter').textContent = total + ' шт';
  const tbody = $('#subsTbody');
  if (!subs.length) {
    tbody.innerHTML = '<tr><td colspan="7"><div class="empty"><span class="emoji">📭</span><div class="title">Подписок нет</div></div></td></tr>';
    const pg = $('#subsPagination'); if (pg) pg.innerHTML = '';
    return;
  }
  tbody.innerHTML = pageSubs.map(s => {
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

  // pagination controls
  const pg = $('#subsPagination');
  if (pg) pg.innerHTML = renderPaginationControls(page, totalPages, total, 'subs');
  bindPaginationClicks('subsPagination', 'subs', renderSubsTable);
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
      <button class="btn btn-ghost btn-sm" id="exportCsvBtn" title="Скачать CSV">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg>
        <span class="label-desktop">CSV</span>
      </button>
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
  $('#exportCsvBtn').addEventListener('click', exportPaymentsCsv);
  renderPaymentsTable();
}

function exportPaymentsCsv() {
  const f = $('#paymentsFilter').value;
  const rf = $('#paymentsReceiptFilter').value;
  const search = ($('#paymentsSearch').value || '').toLowerCase().trim();
  let list = state.payments.slice();
  if (f !== 'all') list = list.filter(p => p.status === f);
  if (rf === 'pending') list = list.filter(p => p.receipt_status !== 'registered' && p.receipt_status !== 'not_required');
  if (rf === 'registered') list = list.filter(p => p.receipt_status === 'registered');
  if (search) {
    list = list.filter(p => {
      const u = state.users.find(x => x.user_id === p.user_id) || {};
      const name = [u.first_name, u.last_name].filter(Boolean).join(' ');
      return String(p.user_id).includes(search) || (u.username || '').toLowerCase().includes(search)
        || name.toLowerCase().includes(search) || (p.provider_payment_id || '').includes(search);
    });
  }
  const rows = [['Дата', 'user_id', 'Имя', 'Username', 'Сумма', 'Устройства', 'Месяцев', 'Провайдер', 'Статус', 'Email', 'Промо', 'Чек']];
  list.forEach(p => {
    const u = state.users.find(x => x.user_id === p.user_id) || {};
    const name = [u.first_name, u.last_name].filter(Boolean).join(' ');
    rows.push([
      (p.paid_at || p.created_at || '').slice(0, 10),
      p.user_id, name, u.username || '', p.amount,
      p.devices || '', p.months || '',
      p.provider || '', p.status || '',
      p.metadata?.email || '', p.promo_code || '', p.receipt_url || '',
    ]);
  });
  const csv = rows.map(r => r.map(v => '"' + String(v ?? '').replace(/"/g, '""') + '"').join(',')).join('\n');
  const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'payments_' + new Date().toISOString().slice(0, 10) + '.csv';
  a.click(); URL.revokeObjectURL(url);
  toast('CSV скачан', 'success');
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

  $$('#paymentsTbody [data-act="mark"]').forEach(b => b.addEventListener('click', () => openReceiptModal(Number(b.dataset.pid))));
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
  if (!await showConfirm({ title: 'Удалить промокод', message: `Удалить промокод ${code}? Это действие необратимо.`, okText: 'Удалить', danger: true })) return;
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
  })).sort((a, b) => (b.paid * 100 + b.referred) - (a.paid * 100 + a.referred));

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
    return `<tr class="clickable" data-tid="${t.id}" data-uid="${t.user_id}">
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
    openTicketChat(Number(r.dataset.tid));
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
      <button class="btn btn-primary btn-sm" id="addServerBtn">${ICONS.plus} Добавить сервер</button>
    </div>

    <div class="srv-grid" id="srvGrid"></div>

    <div style="margin-top: 24px">
      <div class="card">
        <div class="card-head"><div class="card-title">🔗 Внешние ресурсы</div><div class="card-sub">Быстрый доступ к инструментам</div></div>
        <div class="srv-ext-grid">
          <a class="srv-ext-link" href="https://supabase.com/dashboard/project/avjvojscvmsdzllaeise" target="_blank"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg> Supabase</a>
          <a class="srv-ext-link" href="https://yookassa.ru/my" target="_blank"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg> ЮКасса</a>
          <a class="srv-ext-link" href="https://t.me/MaxArtVPN_bot" target="_blank"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg> Основной бот</a>
          <a class="srv-ext-link" href="https://t.me/TuVPNSupport_bot" target="_blank"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg> Бот поддержки</a>
          <a class="srv-ext-link" href="https://github.com/effect110419/tuvpn-bot" target="_blank"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg> GitHub</a>
          <a class="srv-ext-link" href="https://my.adminvps.ru" target="_blank"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg> AdminVPS</a>
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

      <div class="srv-foot srv-foot-wrap">
        <button class="btn btn-ghost btn-sm" data-act="check">${ICONS.refresh} Проверить</button>
        <button class="btn btn-ghost btn-sm" data-act="sync">${ICONS.refresh} Синхр.</button>
        <button class="btn btn-ghost btn-sm" data-act="apply" title="Записать SNI/Reality из админки на сам сервер + рестарт">📡 Применить SNI</button>
        <button class="btn btn-ghost btn-sm" data-act="restart" title="Перезапустить Xray на сервере">♻️ Рестарт</button>
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
    const ab = card.querySelector('[data-act="apply"]'); if (ab) ab.addEventListener('click', () => applyReality(sid));
    const rb = card.querySelector('[data-act="restart"]'); if (rb) rb.addEventListener('click', () => restartXray(sid));
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
    if ($('#srvApiToken')) $('#srvApiToken').value = s.api_token || '';
    $('#srvSort').value = s.sort_order || 0;
    $('#srvActive').checked = !!s.is_active;
  } else {
    // Reset
    ['#srvFlag', '#srvCountry', '#srvCode', '#srvCountryCode', '#srvPanelUrl', '#srvPanelLogin', '#srvPanelPass', '#srvIp', '#srvPubKey', '#srvShortId', '#srvApiToken'].forEach(s => $(s) && ($(s).value = ''));
    $('#srvPort').value = 443;
    $('#srvInbound').value = 1;
    $('#srvSni').value = 'www.bing.com';
    $('#srvFlow').value = 'xtls-rprx-vision';
    $('#srvFp').value = 'chrome';
    $('#srvSort').value = state.servers.length;
    $('#srvActive').checked = true;
  }

  // автозаполнение country_code при выборе страны из селектора
  const flagSel = $('#srvFlag');
  if (flagSel && !flagSel.dataset.bound) {
    flagSel.dataset.bound = '1';
    flagSel.addEventListener('change', () => {
      const opt = flagSel.options[flagSel.selectedIndex];
      const cc = opt && opt.dataset ? opt.dataset.cc : '';
      const ccInput = $('#srvCountryCode');
      // подставляем код только если поле пустое или равно XX/прежнему авто
      if (cc && cc !== 'XX' && ccInput && !ccInput.value.trim()) {
        ccInput.value = cc;
      }
    });
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
      api_token: ($('#srvApiToken') ? $('#srvApiToken').value.trim() : ''),
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
  if (!await showConfirm({ title: 'Удалить сервер', message: `Удалить сервер ${s.country_flag} ${s.country_name}?\n\nЭто действие необратимо. Существующие клиенты на этом сервере останутся, но в новые подписки он попадать не будет.`, okText: 'Удалить', danger: true })) return;

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
  if (!await showConfirm({ title: 'Синхронизация сервера', message: `Синхронизировать ${s.country_flag || ''} ${s.country_name}?\n\nНа этот сервер будут добавлены все активные подписки, которых там ещё нет. Существующие — обновлены (срок действия).`, okText: 'Синхронизировать' })) return;

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
  if (!await showConfirm({ title: 'Синхронизировать все серверы', message: 'Синхронизировать все активные серверы?\n\nНа каждый сервер будут раскатаны все активные подписки. Это может занять минуту.', okText: 'Синхронизировать' })) return;
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
  const TARIFFS = [
    { devices: 1, label: '1 устройство', m1: 149, m3: 399, m12: 1399 },
    { devices: 2, label: '2 устройства',  m1: 249, m3: 649, m12: 2299 },
    { devices: 5, label: '5 устройств',   m1: 599, m3: 1599, m12: 5499 },
  ];
  const tariffRows = TARIFFS.map(t => `
    <tr>
      <td><b>${t.label}</b></td>
      <td class="text-r">${money(t.m1)}</td>
      <td class="text-r">${money(t.m3)}</td>
      <td class="text-r">${money(t.m12)}</td>
    </tr>
  `).join('');

  $('#page-settings').innerHTML = `
    <div class="page-title">Настройки</div>
    <div class="page-sub">Конфигурация и справка по системе</div>

    <div class="card" style="margin-bottom:14px">
      <div class="card-head"><div class="card-title">💳 Тарифная сетка</div><div class="card-sub">Актуальные цены бота</div></div>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr><th>Тариф</th><th class="text-r">1 месяц</th><th class="text-r">3 месяца</th><th class="text-r">12 месяцев</th></tr></thead>
          <tbody>${tariffRows}</tbody>
        </table>
      </div>
      <div style="padding:8px 18px 12px; font-size:12px; color:var(--fg-3)">Цены в ₽. Telegram Stars: отдельный прайс. Для изменения цен — правка <code>PRICES</code> в bot.py.</div>
    </div>

    <div class="grid-1-1">
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

      <div class="card">
        <div class="card-head"><div class="card-title">👤 Мой аккаунт</div></div>
        <div class="card-pad">
          <div class="info"><span class="info-k">Telegram ID</span><span class="info-v mono">${state.me ? state.me.user_id : '—'}</span></div>
          <div class="info"><span class="info-k">Сессия</span><span class="info-v">cookie (7 дней)</span></div>
          <div class="info"><span class="info-k">Быстрые команды</span><span class="info-v"><span class="kbd-key">⌘K</span> / <span class="kbd-key">Ctrl+K</span></span></div>
          <div class="info"><span class="info-k">Закрыть модалку</span><span class="info-v"><span class="kbd-key">ESC</span></span></div>
        </div>
      </div>
    </div>
  `;
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
  if (!uid) { toast('Введите Telegram ID', 'error'); return; }
  const changeDevices = $('#grantDevicesEnable').checked;
  const changeDays = $('#grantDaysEnable').checked;
  if (changeDevices) {
    const devVal = parseInt($('#grantDevices').value);
    if (isNaN(devVal) || devVal < 1 || devVal > 999) { toast('Некорректное число устройств (1-999)', 'error'); return; }
  }
  if (changeDays) {
    const daysVal = parseInt($('#grantDays').value);
    if (isNaN(daysVal) || daysVal < 1 || daysVal > 9999) { toast('Некорректное число дней (1-9999)', 'error'); return; }
  }
  if (!changeDevices && !changeDays) {
    toast('Включи хотя бы одну секцию: устройства или срок', 'error');
    return;
  }
  const body = { user_id: uid };
  if (changeDevices) body.set_devices = parseInt($('#grantDevices').value);
  if (changeDays) body.extend_days = parseInt($('#grantDays').value);
  const btn = $('#grantSubmit');
  btn.disabled = true;
  btn.innerHTML = '⏳ Применяем...';
  try {
    const r = await proxy('/admin-api/grant', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    if (r.success) {
      const parts = [];
      if (changeDevices) parts.push(`устройств: ${r.devices}`);
      if (changeDays) parts.push(`+${body.extend_days} дн`);
      toast(`Подписка обновлена · ${parts.join(' · ')} · ${r.servers || '?'} серверов`);
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
    btn.innerHTML = `${ICONS.check} Применить`;
  }
}

async function revokeSub(id) {
  if (!await showConfirm({ title: 'Отозвать подписку', message: 'Отозвать подписку? Пользователь потеряет доступ ко всем серверам.', okText: 'Отозвать', danger: true })) return;
  try {
    const data = await proxy('/admin-api/revoke/' + id, { method: 'POST' });
    if (!data.success) { toast('Ошибка отзыва: ' + (data.error || 'неизвестно'), 'error'); return; }
    const s = state.subs.find(x => x.id === id);
    if (s) s.status = 'inactive';
    renderPage(state.currentPage);
    const errs = (data.server_errors || []).length;
    toast(errs ? 'Отозвано (ошибки на ' + errs + ' серверах — см. консоль)' : 'Подписка отозвана — доступ к VPN закрыт');
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
  // === MARKETING FIXES 2026-05 === только реально оплаченные (succeeded)
  const organicPayments = state.payments.filter(p => !p.campaign_code && p.status === 'succeeded');
  const totalOrganicRevenue = organicPayments.reduce((sum, p) => sum + (parseFloat(p.amount) || 0), 0);

  // Campaign stats calculation
  const campaignStats = campaigns.map(campaign => {
    const clicks = campaignClicks.filter(c => c.campaign_code === campaign.code);
    const newUsers = clicks.filter(c => c.is_new_user);
    const campaignUsers = state.users.filter(u => u.campaign_code === campaign.code);
    const campaignPayments = state.payments.filter(p => p.campaign_code === campaign.code && p.status === 'succeeded');
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
        <button class="btn btn-primary" data-perm="marketing.manage_campaigns" onclick="openCampaignModal()" title="Создать (N)">
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
          <input type="search" id="campaignSearch" placeholder="Поиск кампаний..." class="input" style="max-width:220px">
        </div>
      </div>
      <div class="table-container">
        <table id="campaignsTable" class="tbl">
          <thead>
            <tr>
              <th>Кампания</th>
              <th>Источник</th>
              <th>Создана</th>
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
            <tr class="organic-row">
              <td data-label="Кампания">
                <div class="u-cell">
                  <div class="status-dot organic"></div>
                  <div>
                    <div style="font-weight:600">🌱 Прямой трафик</div>
                    <div class="text-muted" style="font-size:12px">Органические пользователи</div>
                  </div>
                </div>
              </td>
              <td data-label="Источник"><span class="pill pill-direct">organic</span></td>
              <td data-label="Создана">—</td>
              <td data-label="Расходы ₽" style="text-align:right">—</td>
              <td data-label="Клики" style="text-align:right">—</td>
              <td data-label="Рег-ции" style="text-align:right">${organicUsers.length}</td>
              <td data-label="Оплаты" style="text-align:right">${organicPayments.length}</td>
              <td data-label="Выручка ₽" style="text-align:right">${num(totalOrganicRevenue)}</td>
              <td data-label="ROI" style="text-align:right"><span class="roi-badge success">∞</span></td>
              <td data-label="Ср.чек ₽" style="text-align:right">${organicPayments.length > 0 ? num(totalOrganicRevenue / organicPayments.length) : '—'}</td>
            </tr>
            ${campaignStats.map(campaign => {
              const createdAt = campaign.created_at ? new Date(campaign.created_at).toLocaleDateString('ru-RU', { day:'2-digit', month:'short', year:'2-digit' }) : '—';
              return `<tr class="campaign-row clickable" data-code="${campaign.code}" onclick="showCampaignDetails('${campaign.code}')">
                <td data-label="Кампания">
                  <div class="u-cell">
                    <div class="status-dot ${campaign.is_active ? 'active' : 'inactive'}"></div>
                    <div>
                      <div style="font-weight:600">${esc(campaign.name)}</div>
                      <div class="text-muted mono" style="font-size:11px">${campaign.code}</div>
                    </div>
                  </div>
                </td>
                <td data-label="Источник"><span class="pill pill-${campaign.source || 'other'}">${getSourceIcon(campaign.source)} ${getSourceLabel(campaign.source)}</span></td>
                <td data-label="Создана"><span class="muted" style="font-size:12px">${createdAt}</span></td>
                <td data-label="Расходы ₽" style="text-align:right">${campaign.cost > 0 ? num(campaign.cost) : '—'}</td>
                <td data-label="Клики" style="text-align:right">${campaign.clicks || '—'}</td>
                <td data-label="Рег-ции" style="text-align:right">${campaign.registrations || '—'}</td>
                <td data-label="Оплаты" style="text-align:right">${campaign.payments || '—'}</td>
                <td data-label="Выручка ₽" style="text-align:right">${campaign.revenue > 0 ? num(campaign.revenue) : '—'}</td>
                <td data-label="ROI" style="text-align:right">
                  ${campaign.roi === Infinity ? '<span class="roi-badge success">∞</span>' :
                    campaign.roi > 50 ? `<span class="roi-badge success">+${campaign.roi.toFixed(0)}%</span>` :
                    campaign.roi > 0 ? `<span class="roi-badge warning">+${campaign.roi.toFixed(0)}%</span>` :
                    campaign.roi < -50 ? `<span class="roi-badge danger">${campaign.roi.toFixed(0)}%</span>` :
                    '<span class="roi-badge muted">0%</span>'
                  }
                </td>
                <td data-label="Ср.чек ₽" style="text-align:right">${campaign.avgTicket > 0 ? num(campaign.avgTicket) : '—'}</td>
              </tr>`;
            }).join('')}
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
/* === MARKETING FIXES 2026-05 === */
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

  // Устройства по пользователям: { user_id: [модели...] }
  const byUser = {};
  campDevices.forEach(d => {
    const m = d.device_model || (d.device_type === 'ios' ? 'iPhone/iPad' : d.device_type === 'android' ? 'Android' : 'Устройство');
    (byUser[d.user_id] = byUser[d.user_id] || []).push(m);
  });
  let devicesHtml;
  if (totalDevices === 0) {
    devicesHtml = '<div class="text-muted">Пока нет подключённых устройств</div>';
  } else {
    devicesHtml = Object.entries(byUser).map(([uid, models]) => {
      const u = (state.users || []).find(x => String(x.user_id) === String(uid));
      const name = displayName(u || { user_id: uid });
      const modelsLine = models.map(m => `<span class="pill pill-muted" style="margin:2px 4px 2px 0;display:inline-block">${esc(m)}</span>`).join('');
      return `<div style="padding:8px 0;border-bottom:1px solid var(--border-hi)">
        <div style="font-weight:600;margin-bottom:4px">${esc(name)} <span class="text-muted mono" style="font-size:11px">(${models.length})</span></div>
        <div>${modelsLine}</div>
      </div>`;
    }).join('');
  }

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
        <input class="input" id="cdName" value="${esc(c.name || '')}"></div>
    </div>
    <div class="field-row">
      <div class="field"><label class="label">Источник</label>
        <input class="input" value="${esc(getSourceLabel(c.source))}" disabled></div>
      <div class="field"><label class="label">Бонус дней</label>
        <input class="input mono" value="${c.bonus_days ?? ''}" disabled></div>
    </div>
    <div class="field-row">
      <div class="field"><label class="label">У кого купили</label>
        <input class="input" id="cdCreator" value="${esc(c.creator || '')}"></div>
      <div class="field"><label class="label">Стоимость, ₽</label>
        <input class="input mono" id="cdCost" type="number" min="0" step="100" value="${c.cost ?? 0}"></div>
    </div>
    <div class="field">
      <label class="label">UTM-ссылка для размещения</label>
      <div style="display:flex;gap:8px">
        <input class="input mono" id="cdTgLink" value="${tgLink}" readonly>
        <button class="btn btn-ghost" onclick="navigator.clipboard?.writeText('${tgLink}');toast('Ссылка скопирована')">Копировать</button>
      </div>
    </div>
    <div class="field">
      <label class="label">🔗 Ссылка на канал/группу</label>
      <div style="display:flex;gap:8px">
        <input class="input" id="cdSourceUrl" value="${esc(sourceUrl)}" placeholder="https://t.me/...">
        ${sourceUrl ? `<a class="btn btn-primary" href="${esc(sourceUrl)}" target="_blank" rel="noopener">Открыть →</a>` : ''}
      </div>
    </div>

    <div class="divider"></div>
    <div class="card-title" style="margin-bottom:8px">📊 Воронка</div>
    ${funnelRow('Перешли', clicks, clicks || registered, '#8a8f98')}
    ${funnelRow('Зарегались', registered, clicks || registered, 'var(--accent, #4c7be5)')}
    ${funnelRow('Подключили', connectedUsers, registered, '#2ecc71')}
    ${funnelRow('Оплатили', paidUsers, registered, '#f1c40f')}

    <div class="divider"></div>
    <div class="card-title" style="margin-bottom:8px">📱 Подключённые устройства · всего ${totalDevices} (юзеров: ${connectedUsers})</div>
    ${devicesHtml}

    ${c.welcome_text ? `<div class="divider"></div>
    <div class="field"><label class="label">Welcome-текст</label>
      <textarea class="textarea" rows="3" disabled>${esc(c.welcome_text)}</textarea></div>` : ''}
    ${c.note ? `<div class="field"><label class="label">Заметки</label>
      <textarea class="textarea" rows="2" disabled>${esc(c.note)}</textarea></div>` : ''}
  `;

  let modal = document.getElementById('campaignViewModal');
  if (!modal) {
    modal = document.createElement('div');
    modal.className = 'modal-bg';
    modal.id = 'campaignViewModal';
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
      <div class="modal-foot modal-foot-spread">
        <button class="btn btn-danger" data-perm="marketing.manage_campaigns" onclick="deleteCampaign('${esc(c.code)}')">🗑 Удалить</button>
        <div style="display:flex;gap:8px">
          <button class="btn btn-ghost" onclick="closeModal('campaignViewModal')">Закрыть</button>
          <button class="btn btn-primary" data-perm="marketing.manage_campaigns" onclick="updateCampaign('${esc(c.code)}')">💾 Сохранить</button>
        </div>
      </div>
    </div>`;
  openModal('campaignViewModal');
}

async function updateCampaign(code) {
  const c = (state.campaigns || []).find(x => x.code === code);
  if (!c) { toast('Кампания не найдена', 'error'); return; }
  const name = ($('#cdName')?.value || '').trim();
  const creator = ($('#cdCreator')?.value || '').trim() || null;
  const cost = parseFloat($('#cdCost')?.value) || 0;
  const sourceUrl = ($('#cdSourceUrl')?.value || '').trim() || null;
  if (!name) { toast('Название не может быть пустым', 'error'); return; }
  try {
    await sbUpdate('campaigns', `code=eq.${encodeURIComponent(code)}`, {
      name, creator, cost, source_url: sourceUrl,
    });
    // Обновляем в локальном state
    Object.assign(c, { name, creator, cost, source_url: sourceUrl });
    toast('Кампания обновлена', 'success');
    closeModal('campaignViewModal');
    renderMarketing();
  } catch (e) {
    toast('Ошибка сохранения: ' + e.message, 'error');
  }
}

async function deleteCampaign(code) {
  const c = (state.campaigns || []).find(x => x.code === code);
  if (!c) { toast('Кампания не найдена', 'error'); return; }
  if (!await showConfirm({ title: 'Удалить кампанию', message: `Удалить кампанию «${c.name || code}»?\n\nЭто действие нельзя отменить. Уже зарегистрированные по ней пользователи останутся, но статистика кампании пропадёт.`, okText: 'Удалить', danger: true })) return;
  try {
    await sbDelete('campaigns', `code=eq.${encodeURIComponent(code)}`);
    state.campaigns = (state.campaigns || []).filter(x => x.code !== code);
    toast('Кампания удалена', 'success');
    closeModal('campaignViewModal');
    renderMarketing();
  } catch (e) {
    toast('Ошибка удаления: ' + e.message, 'error');
  }
}


/* ==================== ЛОГИ ==================== */
const LOG_LEVEL_BADGE = {
  info:  '<span class="log-badge log-info">info</span>',
  warn:  '<span class="log-badge log-warn">warn</span>',
  error: '<span class="log-badge log-error">error</span>',
};
const LOG_CAT_LABEL = {
  subscription: 'Подписка', payment: 'Платёж', bot: 'Бот',
  server: 'Сервер', admin: 'Админ', broadcast: 'Рассылка',
};
const logState = { category: 'all', level: 'all', search: '' };


let _logsCache = [];
async function loadLogs() {
  const wrap = $('#logTableWrap');
  if (!wrap) return;
  try {
    let qs = `category=${logState.category}&level=${logState.level}`;
    if (logState.search) qs += `&search=${encodeURIComponent(logState.search)}`;
    const data = await proxy('/admin-api/logs?' + qs);
    _logsCache = data.logs || [];
    if (!_logsCache.length) { wrap.innerHTML = '<div class="empty-state">Нет записей</div>'; return; }
    let rows = _logsCache.map(l => {
      const t = new Date(l.created_at).toLocaleString('ru-RU');
      const det = l.details && Object.keys(l.details).length ? JSON.stringify(l.details) : '';
      const cat = LOG_CAT_LABEL[l.category] || l.category;
      return `<tr>
        <td class="log-time">${esc(t)}</td>
        <td>${LOG_LEVEL_BADGE[l.level] || esc(l.level)}</td>
        <td>${esc(cat)}</td>
        <td class="log-event">${esc(l.event)}${l.user_id ? ` <span class="log-uid">uid:${l.user_id}</span>` : ''}</td>
        <td class="log-details">${det ? `<code>${esc(det.slice(0,80))}</code>` : ''}</td>
        <td><button class="btn-copy" data-log='${esc(JSON.stringify(l))}' title="Копировать">⧉</button></td>
      </tr>`;
    }).join('');
    wrap.innerHTML = `<table class="data-table log-table">
      <thead><tr><th>Время</th><th>Уровень</th><th>Категория</th><th>Событие</th><th>Детали</th><th></th></tr></thead>
      <tbody>${rows}</tbody></table>`;
    $$('.btn-copy').forEach(b => b.addEventListener('click', () => {
      copyToClipboard(b.dataset.log); toast('Скопировано');
    }));
  } catch (e) {
    wrap.innerHTML = `<div class="empty-state">Ошибка загрузки логов</div>`;
  }
}

function copyAllLogs() {
  const text = _logsCache.map(l =>
    `[${new Date(l.created_at).toLocaleString('ru-RU')}] ${l.level.toUpperCase()} ${l.category}: ${l.event}` +
    (l.user_id ? ` (uid:${l.user_id})` : '') +
    (l.details && Object.keys(l.details).length ? ` ${JSON.stringify(l.details)}` : '')
  ).join('\n');
  copyToClipboard(text); toast('Все логи скопированы');
}

/* ==================== РАССЫЛКА ==================== */
const BC_TEMPLATES = {
  fix: "✅ Мы устранили неполадки — сервис снова работает стабильно.\n\nЕсли VPN не подключается, откройте приложение и нажмите 🔄 (обновить), затем выберите любую локацию. Спасибо за терпение! 🙌",
  apology: "🙏 Приносим извинения за недавние перебои в работе сервиса.\n\nВ качестве компенсации мы начислили вам бонусные дни подписки. Спасибо, что остаётесь с нами!\n\nЕсли возникнут вопросы — мы всегда на связи.",
  renew: "⏳ Ваша подписка скоро истекает.\n\nПродлите её заранее, чтобы доступ не прерывался. Telegram сейчас замедляют — с нашим VPN всё открывается без ограничений. Оформить продление можно прямо в боте.",
  news: "📣 У нас новости!\n\nМы постоянно улучшаем сервис: добавляем серверы, повышаем стабильность и скорость. Следите за обновлениями — впереди ещё больше полезного. 🚀",
  howto: "🛠 Если VPN не подключается:\n\n1. Откройте приложение Happ\n2. Нажмите 🔄 (обновить подписку)\n3. Выберите другую локацию\n4. Нажмите кнопку подключения\n\nЕсли не помогло — напишите в поддержку, поможем!",
};
const bcState = { audience: 'all', campaign: 'all', targetUserId: null };

async function renderBroadcast() {
  const host = getPageHost();
  host.innerHTML = `
    <div class="page-head">
      <h2>Рассылка</h2>
      <div class="page-sub">Массовые уведомления пользователям в Telegram-бот.</div>
    </div>
    <div class="toolbar">
      <button class="btn btn-primary" id="bcNewBtn">+ Новая рассылка</button>
      <span class="toolbar-grow"></span>
      <button class="btn btn-ghost btn-sm" id="bcHistRefresh">Обновить историю</button>
    </div>
    <div id="bcHistWrap"><div class="empty-state">Загрузка истории...</div></div>
  `;
  $('#bcNewBtn').addEventListener('click', openBroadcastModal);
  $('#bcHistRefresh').addEventListener('click', loadBroadcasts);
  loadBroadcasts();
}

async function loadBroadcasts() {
  const wrap = $('#bcHistWrap');
  if (!wrap) return;
  try {
    const data = await proxy('/admin-api/broadcasts');
    const list = data.broadcasts || [];
    if (!list.length) { wrap.innerHTML = '<div class="empty-state">Рассылок пока не было</div>'; return; }
    const audMeta = {
      all:               { label: '📢 Все пользователи',              cls: 'bc-aud-all' },
      active:            { label: '✅ С активной подпиской',           cls: 'bc-aud-active' },
      inactive:          { label: '⏸ Без активной подписки',          cls: 'bc-aud-inactive' },
      expires_6h:        { label: '⏰ Истекают через 6 часов',         cls: 'bc-aud-expire' },
      expired_unpaid_14d:{ label: '💤 Истекли · не платили 14д',       cls: 'bc-aud-inactive' },
      utm_no_device:     { label: '🎯 Рекл. трафик · не подключились', cls: 'bc-aud-utm' },
      utm_never_paid:    { label: '💸 Рекл. трафик · ни разу не платили', cls: 'bc-aud-utm' },
      utm_expired:       { label: '🔄 Рекл. трафик · подписка истекла', cls: 'bc-aud-utm' },
      custom_list:       { label: '👤 Список ID',                       cls: 'bc-aud-single' },
      single:            { label: '👤 Конкретный',                      cls: 'bc-aud-single' },
    };
    let rows = list.map(b => {
      const t = new Date(b.created_at);
      const date = t.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' });
      const time = t.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
      const am = audMeta[b.audience] || { label: b.audience, cls: '' };
      // расшифровка получателя
      let recipient = am.label;
      if (b.audience === 'single' && b.target_user_id) {
        const u = userById ? userById(b.target_user_id) : null;
        const name = u ? ([u.first_name, u.last_name].filter(Boolean).join(' ') || (u.username ? '@'+u.username : '')) : '';
        recipient = name ? `${esc(name)} (id:${b.target_user_id})` : `id:${b.target_user_id}`;
      } else if (b.campaign_filter) {
        const c = (state.campaigns || []).find(x => x.code === b.campaign_filter);
        recipient = `${am.label} · ${c ? esc(c.name || c.code) : esc(b.campaign_filter)}`;
      }
      const preview = (b.message_text || '').replace(/\n/g, ' ');
      const previewShort = preview.slice(0, 70) + (preview.length > 70 ? '…' : '');
      const deliveredPct = b.recipients_count ? Math.round(b.sent_count / b.recipients_count * 100) : 0;
      const statusBadge = b.status === 'completed' ? '<span class="bc-st bc-st-ok">доставлено</span>'
        : b.status === 'partial' ? '<span class="bc-st bc-st-partial">частично</span>'
        : '<span class="bc-st bc-st-fail">ошибка</span>';
      return `<tr class="bc-hist-row" title="${esc(preview)}">
        <td class="bc-hist-date"><div>${date}</div><div class="bc-hist-time">${time}</div></td>
        <td><span class="bc-aud-badge ${am.cls}">${esc(recipient)}</span></td>
        <td class="bc-hist-msg">${esc(previewShort)}</td>
        <td class="bc-hist-delivered">
          <div class="bc-deliv-num">${b.sent_count}/${b.recipients_count}</div>
          <div class="bc-deliv-bar"><div class="bc-deliv-fill" style="width:${deliveredPct}%"></div></div>
        </td>
        <td class="bc-hist-bonus">${b.bonus_days > 0 ? `<span class="bc-bonus-badge">+${b.bonus_days}д</span>` : '—'}</td>
        <td>${statusBadge}${b.blocked_count ? ` <span class="muted" title="заблокировали бота">🚫${b.blocked_count}</span>` : ''}</td>
      </tr>`;
    }).join('');
    wrap.innerHTML = `<div class="bc-hist-card"><table class="data-table bc-hist-table">
      <thead><tr><th>Дата</th><th>Кому</th><th>Сообщение</th><th>Доставлено</th><th>Бонус</th><th>Статус</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  } catch (e) {
    wrap.innerHTML = '<div class="empty-state">Ошибка загрузки истории</div>';
  }
}

function openBroadcastModal() {
  // переписана на новую логику v3 — просто открываем новую модалку
  if (typeof openBroadcastForm === 'function') {
    openBroadcastForm();
  } else {
    // фолбэк: открываем модалку и инициализируем
    if (typeof bcReset === 'function') bcReset();
    openModal('broadcastModal');
    setTimeout(() => {
      if (typeof bcBindModal === 'function') bcBindModal();
      if (typeof bcOnAudChange === 'function') bcOnAudChange();
      const r = document.querySelector('input[name="bcAud"][value="all"]');
      if (r) r.checked = true;
    }, 30);
  }
}

async function initBroadcastHandlers() {
  await loadMyPermissions();

  // аудитория
  document.addEventListener('click', e => {
    const b = e.target.closest('#bcAudience .seg-btn');
    if (b) {
      $$('#bcAudience .seg-btn').forEach(x => x.classList.remove('active'));
      b.classList.add('active'); bcState.audience = b.dataset.aud;
      const wrap = $('#bcSingleWrap');
      if (wrap) wrap.style.display = (b.dataset.aud === 'single') ? 'block' : 'none';
    }
  });
  // поиск юзера для 'конкретный'
  document.addEventListener('input', e => {
    if (e.target && e.target.id === 'bcUserSearch') bcRenderUserList(e.target.value);
  });
  document.addEventListener('click', e => {
    const it = e.target.closest('.bc-user-item');
    if (it) {
      bcState.targetUserId = Number(it.dataset.uid);
      $('#bcUserSearch').value = it.dataset.label;
      $('#bcUserList').innerHTML = '';
    }
  });
  // шаблон
  const tpl = $('#bcTemplate');
  if (tpl) tpl.addEventListener('change', e => {
    const v = e.target.value;
    if (v && BC_TEMPLATES[v]) $('#bcText').value = BC_TEMPLATES[v];
  });
  // бонус toggle
  const be = $('#bcBonusEnable');
  if (be) be.addEventListener('change', e => {
    $('#bcBonusWrap').style.display = e.target.checked ? 'block' : 'none';
  });
  // предпросмотр
  const pv = $('#bcPreviewBtn');
  if (pv) pv.addEventListener('click', doBroadcastPreview);
  // отправка
  const sb_ = $('#bcSendBtn');
  if (sb_) sb_.addEventListener('click', doBroadcastSend);
}

async function doBroadcastPreview() {
  const text = $('#bcText').value.trim();
  if (!text) { toast('Введите текст сообщения'); return; }
  bcState.campaign = $('#bcCampaign').value;
  if (bcState.audience === 'single' && !bcState.targetUserId) { toast('Выберите пользователя'); return; }
  const bonusEnabled = $('#bcBonusEnable').checked;
  const bonusDays = bonusEnabled ? parseInt($('#bcBonusDays').value || 0) : 0;
  try {
    const data = await proxy('/admin-api/broadcast/preview', {
      method: 'POST',
      body: JSON.stringify({ audience: bcState.audience, campaign_filter: bcState.campaign, target_user_id: bcState.targetUserId }),
    });
    if (!data.success) { toast('Ошибка предпросмотра'); return; }
    const audLabel = { all: 'Все', active: 'С подпиской', inactive: 'Без подписки' };
    $('#bcPreviewText').textContent = text;
    $('#bcPreviewCount').textContent = data.count;
    $('#bcPreviewAud').textContent = audLabel[bcState.audience] + (bcState.campaign !== 'all' ? ` · ${bcState.campaign}` : '');
    if (bonusDays > 0) {
      $('#bcPreviewBonusRow').style.display = 'flex';
      $('#bcPreviewBonus').textContent = `+${bonusDays} дней`;
    } else {
      $('#bcPreviewBonusRow').style.display = 'none';
    }
    // сохраним для отправки
    $('#bcSendBtn').dataset.payload = JSON.stringify({
      audience: bcState.audience, campaign_filter: bcState.campaign,
      message_text: text, bonus_days: bonusDays, target_user_id: bcState.targetUserId,
    });
    closeModal('broadcastModal');
    openModal('broadcastPreviewModal');
  } catch (e) { toast('Ошибка сети'); }
}

async function doBroadcastSend() {
  const btn = $('#bcSendBtn');
  const payload = btn.dataset.payload;
  if (!payload) return;
  btn.disabled = true; btn.textContent = 'Отправка...';
  try {
    const data = await proxy('/admin-api/broadcast/send', { method: 'POST', body: payload });
    if (data.success) {
      toast(`Отправлено: ${data.sent} из ${data.total}`);
      closeModal('broadcastPreviewModal');
      loadBroadcasts();
    } else {
      toast('Ошибка: ' + (data.error || 'неизвестно'));
    }
  } catch (e) {
    toast('Ошибка сети при отправке');
  } finally {
    btn.disabled = false; btn.textContent = 'Отправить рассылку';
  }
}


function bcRenderUserList(q) {
  const box = $('#bcUserList'); if (!box) return;
  q = (q || '').toLowerCase().trim();
  if (!q) { box.innerHTML = ''; return; }
  const matches = (state.users || []).filter(u => {
    const hay = [u.username, u.first_name, u.last_name, u.user_id].filter(Boolean).join(' ').toLowerCase();
    return hay.includes(q);
  }).slice(0, 8);
  box.innerHTML = matches.map(u => {
    const name = [u.first_name, u.last_name].filter(Boolean).join(' ') || (u.username ? '@'+u.username : 'id:'+u.user_id);
    const label = name + ' (id:' + u.user_id + ')';
    return `<div class="bc-user-item" data-uid="${u.user_id}" data-label="${esc(label)}">${esc(label)}</div>`;
  }).join('') || '<div class="bc-user-empty">Не найдено</div>';
}



/* ==================== МОНИТОРИНГ СЕРВЕРОВ ==================== */
const monState = { hours: 6, server: 'all', charts: {}, timer: null };
const INTERVAL_OPTIONS = [
  { v: 5, label: '5 сек' }, { v: 30, label: '30 сек' },
  { v: 60, label: '1 мин' }, { v: 300, label: '5 мин' }, { v: 600, label: '10 мин' },
];

async function renderMonitor() {
  const host = getPageHost();
  host.innerHTML = `
    <div class="lb-page-head">
      <h2>Мониторинг серверов</h2>
      <div class="lb-page-sub">Здоровье VPN-узлов в реальном времени. Доступность, задержка, клиенты, Reality-донор.</div>
    </div>
    <div class="toolbar">
      <label class="mon-ctl">Проверять каждые
        <select class="input" id="monInterval" style="max-width:130px">
          ${INTERVAL_OPTIONS.map(o => `<option value="${o.v}">${o.label}</option>`).join('')}
        </select>
      </label>
      <span class="toolbar-grow"></span>
      <label class="mon-ctl">Окно
        <select class="input" id="monWindow" style="max-width:120px">
          <option value="1">1 час</option>
          <option value="6" selected>6 часов</option>
          <option value="24">24 часа</option>
        </select>
      </label>
      <button class="btn btn-ghost btn-sm" id="monRefresh">Обновить</button>
    </div>
    <div id="monCards" class="mon-cards-grid"><div class="empty-state">Загрузка...</div></div>
    <div class="card" style="margin-top:20px;padding:18px 20px 12px">
      <div class="card-head" style="margin-bottom:8px"><div class="card-title">📈 Графики за период</div><div class="card-sub">Пунктир — разные серверы</div></div>
      <div class="mon-charts">
        <div class="mon-chart-box">
          <div class="mon-chart-title">Задержка (мс)</div>
          <div class="mon-chart-wrap"><canvas id="monChartLatency"></canvas></div>
        </div>
        <div class="mon-chart-box">
          <div class="mon-chart-title">Доступность</div>
          <div class="mon-chart-wrap"><canvas id="monChartUptime"></canvas></div>
        </div>
        <div class="mon-chart-box">
          <div class="mon-chart-title">Клиентов на сервере</div>
          <div class="mon-chart-wrap"><canvas id="monChartClients"></canvas></div>
        </div>
        <div class="mon-chart-box">
          <div class="mon-chart-title">Reality-донор (TLS)</div>
          <div class="mon-chart-wrap"><canvas id="monChartTarget"></canvas></div>
        </div>
      </div>
    </div>
  `;
  // загрузить текущий интервал
  try {
    const s = await proxy('/admin-api/monitor/settings');
    if (s.settings && s.settings.interval_sec) $('#monInterval').value = s.settings.interval_sec;
  } catch (e) {}

  $('#monInterval').addEventListener('change', async e => {
    try {
      await proxy('/admin-api/monitor/settings', { method: 'POST', body: JSON.stringify({ interval_sec: parseInt(e.target.value) }) });
      toast('Интервал обновлён: ' + e.target.options[e.target.selectedIndex].text);
    } catch (er) { toast('Ошибка сохранения интервала'); }
  });
  $('#monWindow').addEventListener('change', e => { monState.hours = parseInt(e.target.value); loadMonitorCharts(); });
  $('#monRefresh').addEventListener('click', () => { loadMonitorLatest(); loadMonitorCharts(); });

  loadMonitorLatest();
  loadMonitorCharts();

  // авто-обновление карточек каждые 30 сек пока на странице
  if (monState.timer) clearInterval(monState.timer);
  monState.timer = setInterval(() => {
    if (state.currentPage === 'monitor') { loadMonitorLatest(); }
    else { clearInterval(monState.timer); monState.timer = null; }
  }, 30000);
}

async function loadMonitorLatest() {
  const box = $('#monCards');
  if (!box) return;
  try {
    const data = await proxy('/admin-api/monitor/latest');
    const servers = data.servers || [];
    if (!servers.length) { box.innerHTML = '<div class="empty-state">Нет данных. Демон мониторинга ещё не собрал метрики.</div>'; return; }
    box.innerHTML = servers.map(s => {
      const h = s.health || {};
      const up = h.is_up;
      const dot = up ? 'mon-dot-up' : 'mon-dot-down';
      const statusText = up ? 'Работает' : 'Недоступен';
      const lat = h.latency_ms != null ? h.latency_ms + ' мс' : '—';
      const clients = h.clients_count != null ? h.clients_count : '—';
      const target = h.target_ok === true ? '🟢' : h.target_ok === false ? '🔴' : '—';
      const xray = h.xray_listening ? '🟢' : '🔴';
      const uptime = s.uptime_24h != null ? s.uptime_24h + '%' : '—';
      const checkedAt = h.checked_at ? new Date(h.checked_at).toLocaleTimeString('ru-RU') : '—';
      return `<div class="mon-card ${up ? '' : 'mon-card-down'}">
        <div class="mon-card-head">
          <span class="mon-dot ${dot}"></span>
          <span class="mon-card-name">${esc(s.flag || '')} ${esc(s.name || s.code)}</span>
          <span class="mon-card-status">${statusText}</span>
        </div>
        <div class="mon-card-ip">${esc(s.ip || '')}</div>
        <div class="mon-card-grid">
          <div class="mon-metric"><span>Задержка</span><b>${lat}</b></div>
          <div class="mon-metric"><span>Uptime 24ч</span><b>${uptime}</b></div>
          <div class="mon-metric"><span>Клиентов</span><b>${clients}</b></div>
          <div class="mon-metric"><span>Xray :443</span><b>${xray}</b></div>
          <div class="mon-metric"><span>Reality-донор</span><b>${target}</b></div>
          <div class="mon-metric"><span>SNI</span><b class="mon-sni">${esc(h.sni || s.sni || '—')}</b></div>
        </div>
        <div class="mon-card-foot">Проверено: ${checkedAt}${h.error ? ` · <span class="log-error">${esc(h.error.slice(0,40))}</span>` : ''}</div>
      </div>`;
    }).join('');
  } catch (e) {
    box.innerHTML = '<div class="empty-state">Ошибка загрузки состояния серверов</div>';
  }
}

const MON_COLORS = ['#4fc4cf', '#f97316', '#c084fc', '#4ade80', '#facc15', '#f87171'];
const MON_DASHES = [[0,0], [8,4], [4,4], [12,4,2,4], [6,3], [2,2]];

async function loadMonitorCharts() {
  try {
    const data = await proxy('/admin-api/monitor/health?hours=' + monState.hours);
    const rows = data.health || [];
    // группируем по серверам
    const byServer = {};
    rows.forEach(r => {
      (byServer[r.server_code] = byServer[r.server_code] || []).push(r);
    });
    const codes = Object.keys(byServer);
    // единые метки времени (берём все checked_at отсортированные уникальные — упрощённо по каждому серверу свои точки)
    drawMonChart('monChartLatency', 'latency', byServer, codes, v => v.latency_ms);
    drawMonChart('monChartUptime', 'uptime', byServer, codes, v => v.is_up ? 1 : 0);
    drawMonChart('monChartClients', 'clients', byServer, codes, v => v.clients_count);
    drawMonChart('monChartTarget', 'target', byServer, codes, v => v.target_ok ? 1 : 0);
  } catch (e) {
    console.error('monitor charts:', e);
  }
}

function createMonGradient(ctx, canvas, color) {
  // вертикальный градиент: цвет сверху (полупрозрачный) -> прозрачный снизу
  const h = canvas.height || 230;
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  // hex color -> rgba helper
  const hex = color.replace('#', '');
  const r = parseInt(hex.substring(0, 2), 16);
  const g = parseInt(hex.substring(2, 4), 16);
  const b = parseInt(hex.substring(4, 6), 16);
  grad.addColorStop(0, `rgba(${r},${g},${b},0.35)`);
  grad.addColorStop(0.5, `rgba(${r},${g},${b},0.12)`);
  grad.addColorStop(1, `rgba(${r},${g},${b},0.0)`);
  return grad;
}

function drawMonChart(canvasId, key, byServer, codes, valueFn) {
  const canvas = $('#' + canvasId);
  if (!canvas) return;
  if (monState.charts[canvasId]) monState.charts[canvasId].destroy();
  const ctx = canvas.getContext('2d');
  const isStep = (key === 'uptime' || key === 'target');

  const datasets = codes.map((code, i) => {
    const color = MON_COLORS[i % MON_COLORS.length];
    const dash = MON_DASHES[i % MON_DASHES.length];
    const pts = byServer[code].map(r => ({ x: new Date(r.checked_at).getTime(), y: valueFn(r) }));
    // первый сервер — утолщённая линия, остальные тоньше для разборчивости
    const bw = i === 0 ? 2.5 : 1.8;
    const pr = i === 0 ? 3 : 0;
    return {
      label: code, data: pts, borderColor: color,
      backgroundColor: createMonGradient(ctx, canvas, color),
      borderWidth: bw, borderDash: dash,
      pointRadius: pr, pointHoverRadius: 5,
      pointBackgroundColor: color, pointBorderColor: 'transparent',
      tension: isStep ? 0 : .35,
      stepped: isStep ? true : false, fill: true,
    };
  });

  monState.charts[canvasId] = new Chart(ctx, {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'nearest', intersect: false },
      plugins: {
        legend: { display: true, labels: { color: '#b4b9c8', font: { family: 'Geist Mono', size: 10 }, boxWidth: 10, boxHeight: 10, padding: 8 } },
        tooltip: {
          backgroundColor: '#0b1428', borderColor: 'rgba(120,160,220,0.18)', borderWidth: 1, padding: 8,
          titleColor: '#ecf3ff', bodyColor: '#afc3e0',
          titleFont: { family: 'Geist Mono', size: 11 }, bodyFont: { family: 'Geist', size: 12 },
          callbacks: {
            title: items => items.length ? new Date(items[0].parsed.x).toLocaleString('ru-RU') : '',
            label: c => {
              if (key === 'uptime') return c.dataset.label + ': ' + (c.parsed.y ? 'UP' : 'DOWN');
              if (key === 'target') return c.dataset.label + ': ' + (c.parsed.y ? 'доступен' : 'недоступен');
              if (key === 'latency') return c.dataset.label + ': ' + (c.parsed.y == null ? '—' : c.parsed.y + ' мс');
              return c.dataset.label + ': ' + (c.parsed.y == null ? '—' : c.parsed.y);
            },
          },
        },
      },
      scales: {
        x: { type: 'time', time: { tooltipFormat: 'HH:mm', displayFormats: { minute: 'HH:mm', hour: 'HH:mm' } },
             grid: { display: false }, ticks: { color: '#7290b8', font: { family: 'Geist Mono', size: 10 }, maxRotation: 0, autoSkipPadding: 40 } },
        y: isStep
          ? { min: -0.1, max: 1.1, grid: { color: 'rgba(120,160,220,0.08)' }, ticks: { color: '#7290b8', font: { family: 'Geist Mono', size: 10 }, stepSize: 1, callback: v => v === 1 ? 'UP' : v === 0 ? 'DOWN' : '' } }
          : { beginAtZero: true, grid: { color: 'rgba(120,160,220,0.08)' }, ticks: { color: '#7290b8', font: { family: 'Geist Mono', size: 10 } } },
      },
    },
  });
}

/* helpers (если ещё не определены) */
function getPageHost() {
  // рендерим в div текущей страницы (.page#page-<name>)
  const p = state.currentPage;
  return $('#page-' + p) || $('#content') || document.querySelector('main');
}
function copyToClipboard(text) {
  if (navigator.clipboard) navigator.clipboard.writeText(text);
  else { const t = document.createElement('textarea'); t.value = text; document.body.appendChild(t); t.select(); document.execCommand('copy'); t.remove(); }
}
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

// инициализация обработчиков рассылки при загрузке
if (document.readyState !== 'loading') initBroadcastHandlers();
else document.addEventListener('DOMContentLoaded', initBroadcastHandlers);



/* === MOBILE SIDEBAR === Логика выезжающей шторки на мобилке */
(function initMobileSidebar() {
  function attach() {
    const burger = document.getElementById('mobileBurger');
    const backdrop = document.getElementById('sidebarBackdrop');
    if (!burger || !backdrop) { setTimeout(attach, 100); return; }

    const closeSidebar = () => document.body.classList.remove('sidebar-open');
    const toggleSidebar = () => document.body.classList.toggle('sidebar-open');

    burger.addEventListener('click', toggleSidebar);
    backdrop.addEventListener('click', closeSidebar);

    // Закрывать sidebar при клике на nav-item на мобиле
    document.querySelectorAll('.nav-item').forEach(item => {
      item.addEventListener('click', () => {
        if (window.matchMedia('(max-width: 768px)').matches) {
          // даём 80ms на анимацию подсветки, потом закрываем
          setTimeout(closeSidebar, 80);
        }
      });
    });

    // Закрывать sidebar по Escape
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && document.body.classList.contains('sidebar-open')) {
        closeSidebar();
      }
    });

    // При изменении размера окна — если стал десктоп, закрыть мобильный sidebar
    let resizeTimer;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        if (!window.matchMedia('(max-width: 768px)').matches) {
          closeSidebar();
        }
      }, 150);
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', attach);
  } else {
    attach();
  }
})();


/* ==================== DASHBOARD PULSE ==================== */
let _pulseTimer = null;

async function renderDashboardPulse() {
  const host = $('#pulseBlock');
  if (!host) return;
  await loadPulse();
  if (_pulseTimer) clearInterval(_pulseTimer);
  _pulseTimer = setInterval(() => {
    if (state.currentPage === 'dashboard') loadPulse();
    else { clearInterval(_pulseTimer); _pulseTimer = null; }
  }, 30000);
}

async function loadPulse() {
  const host = $('#pulseBlock');
  if (!host) return;
  try {
    const data = await proxy('/admin-api/dashboard/pulse');
    if (!data.success) { host.innerHTML = ''; return; }
    const p = data.pulse || {};
    const servers = (p.servers || []).map(s => {
      const cls = s.is_up === true ? 'mon-dot-up' : s.is_up === false ? 'mon-dot-down' : '';
      const lat = s.latency_ms != null ? s.latency_ms + 'мс' : '—';
      return `<div class="pulse-srv">
        <span class="mon-dot ${cls}"></span>
        <span class="pulse-srv-flag">${esc(s.flag || '')}</span>
        <span class="pulse-srv-name">${esc(s.name || s.code)}</span>
        <span class="pulse-srv-lat">${lat}</span>
      </div>`;
    }).join('');

    const mrrDelta = p.mrr_delta_pct;
    const mrrDeltaHtml = mrrDelta == null
      ? '<span class="kpi-delta flat">—</span>'
      : `<span class="kpi-delta ${mrrDelta >= 0 ? 'up' : 'dn'}">${mrrDelta >= 0 ? '↑' : '↓'} ${Math.abs(mrrDelta)}%</span>`;

    const churnCls = p.churn_pct > 30 ? 'dn' : p.churn_pct > 10 ? 'flat' : 'up';
    const convCls = p.conversion_pct > 5 ? 'up' : p.conversion_pct > 1 ? 'flat' : 'dn';

    host.innerHTML = `
      <div class="pulse-grid">
        <div class="pulse-card pulse-card-wide">
          <div class="pulse-card-head">
            <span class="pulse-card-label">VPN-узлы</span>
            <span class="live-pulse-dot"></span>
          </div>
          <div class="pulse-srvs">${servers || '<span class="muted">нет данных</span>'}</div>
        </div>
        <div class="pulse-card">
          <div class="pulse-card-head">
            <span class="pulse-card-label">Активны за час</span>
            <svg class="pulse-card-ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg>
          </div>
          <div class="pulse-value">${num(p.live_users)}</div>
          <div class="pulse-foot">пользовались за час</div>
        </div>
        <div class="pulse-card">
          <div class="pulse-card-head">
            <span class="pulse-card-label">MRR (30д)</span>
            ${mrrDeltaHtml}
          </div>
          <div class="pulse-value">${money(p.mrr)}</div>
          <div class="pulse-foot">${p.expiring_soon || 0} истекают за 48ч</div>
        </div>
        <div class="pulse-card">
          <div class="pulse-card-head">
            <span class="pulse-card-label">Конверсия 7д</span>
            <span class="kpi-delta ${convCls}">${p.paid_users_7d}/${p.new_users_7d}</span>
          </div>
          <div class="pulse-value">${p.conversion_pct || 0}%</div>
          <div class="pulse-foot">регистрация → оплата</div>
        </div>
        <div class="pulse-card">
          <div class="pulse-card-head">
            <span class="pulse-card-label">Отток 7д</span>
            <span class="kpi-delta ${churnCls}">${p.churned_count}/${p.expired_count}</span>
          </div>
          <div class="pulse-value">${p.churn_pct || 0}%</div>
          <div class="pulse-foot">истекли и не продлили</div>
        </div>
      </div>
    `;
  } catch (e) {
    host.innerHTML = '';
  }
}

/* ==================== WORLD MAP ==================== */
/* ===== MAP POINT MODAL — список юзеров в точке ===== */

function ruPlural(n, one, few, many) {
  const mod10 = n % 10, mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
  return many;
}


/* ==================== ANALYTICS ==================== */
const analyticsState = { funnelChart: null, period: 30, campaign: 'all' };

async function renderAnalytics() {
  const host = $('#page-analytics');
  host.innerHTML = `
    <div class="lb-page-head">
      <h2>📊 Аналитика</h2>
      <div class="lb-page-sub">Воронка конверсии, когортный анализ LTV и календарь продлений.</div>
    </div>

    <div class="card" style="margin-bottom:18px">
      <div class="card-head">
        <div class="card-title">Воронка конверсии</div>
        <div class="table-actions">
          <select class="filter" id="funnelPeriod">
            <option value="7">7 дней</option>
            <option value="30" selected>30 дней</option>
            <option value="90">90 дней</option>
            <option value="365">Год</option>
          </select>
          <select class="filter" id="funnelCampaign"><option value="all">Все источники</option></select>
        </div>
      </div>
      <div class="card-pad">
        <div id="funnelBars" class="funnel-bars"><div class="empty"><div class="title">Загрузка...</div></div></div>
      </div>
    </div>

    <div class="grid-1-1">
      <div class="card">
        <div class="card-head"><div class="card-title">Когорты по месяцам</div></div>
        <div class="tbl-wrap"><table class="tbl" id="cohortTable"></table></div>
      </div>
      <div class="card">
        <div class="card-head"><div class="card-title">Источники: LTV / CAC / ROI</div></div>
        <div class="tbl-wrap"><table class="tbl" id="utmCohortTable"></table></div>
      </div>
    </div>

    <div class="card" style="margin-top:18px">
      <div class="card-head">
        <div class="card-title">📅 Календарь продлений (30 дней)</div>
        <div class="card-sub" id="calSummary">—</div>
      </div>
      <div class="card-pad">
        <div id="renewalCalendar" class="renewal-cal"><div class="empty"><div class="title">Загрузка...</div></div></div>
      </div>
    </div>
  `;

  // заполнить кампании в фильтр
  const campSel = $('#funnelCampaign');
  (state.campaigns || []).forEach(c => {
    const o = document.createElement('option');
    o.value = c.code; o.textContent = c.name || c.code;
    campSel.appendChild(o);
  });

  $('#funnelPeriod').addEventListener('change', e => { analyticsState.period = e.target.value; loadFunnel(); });
  $('#funnelCampaign').addEventListener('change', e => { analyticsState.campaign = e.target.value; loadFunnel(); });

  loadFunnel();
  loadCohorts();
  loadCalendar();
}

async function loadFunnel() {
  const host = $('#funnelBars');
  try {
    const q = `?period=${analyticsState.period}&campaign=${encodeURIComponent(analyticsState.campaign)}`;
    const data = await proxy('/admin-api/analytics/funnel' + q);
    if (!data.success) { host.innerHTML = '<div class="empty"><div class="title">Ошибка</div></div>'; return; }
    const f = data.funnel || [];
    const maxCount = Math.max(...f.map(s => s.count), 1);
    const colors = ['#4fc4cf', '#6366f1', '#c084fc', '#4ade80'];
    host.innerHTML = f.map((s, i) => {
      const widthPct = s.count === 0 ? 0 : Math.max(4, s.count / maxCount * 100);
      const dropFromPrev = i > 0 && f[i-1].count > 0
        ? Math.round((1 - s.count / f[i-1].count) * 100) : 0;
      return `
        <div class="funnel-step">
          <div class="funnel-step-info">
            <span class="funnel-step-label">${esc(s.step)}</span>
            <span class="funnel-step-vals"><b>${num(s.count)}</b> · ${s.pct}%</span>
          </div>
          <div class="funnel-bar-track">
            <div class="funnel-bar-fill" style="width:${widthPct}%;background:linear-gradient(90deg, ${colors[i]}, ${colors[i]}aa)"></div>
          </div>
          ${i > 0 && dropFromPrev > 0 ? `<div class="funnel-drop">↓ потеря ${dropFromPrev}% с прошлого шага</div>` : ''}
        </div>`;
    }).join('');
  } catch (e) {
    host.innerHTML = '<div class="empty"><div class="title">Ошибка сети</div></div>';
  }
}

async function loadCohorts() {
  try {
    const data = await proxy('/admin-api/analytics/cohorts');
    if (!data.success) return;

    // Когорты по месяцам
    const ct = $('#cohortTable');
    const cohorts = data.cohorts || [];
    if (!cohorts.length) {
      ct.innerHTML = '<tbody><tr><td class="empty"><div class="sub">Нет данных</div></td></tr></tbody>';
    } else {
      ct.innerHTML = `
        <thead><tr>
          <th>Месяц</th><th class="text-r">Юзеры</th><th class="text-r">Платят</th><th class="text-r">%</th><th class="text-r">LTV/юзер</th>
        </tr></thead>
        <tbody>
          ${cohorts.map(c => `
            <tr>
              <td data-label="Месяц"><span class="mono">${monthName(c.month)}</span></td>
              <td data-label="Юзеры" class="text-r num">${c.new_users}</td>
              <td data-label="Платят" class="text-r num">${c.paid_users}</td>
              <td data-label="%" class="text-r"><span class="tag ${c.paid_pct >= 10 ? 'tag-green' : c.paid_pct >= 3 ? 'tag-yellow' : 'tag-gray'}">${c.paid_pct}%</span></td>
              <td data-label="LTV/юзер" class="text-r num">${money(c.ltv_per_user)}</td>
            </tr>`).join('')}
        </tbody>`;
    }

    // UTM-когорты
    const ut = $('#utmCohortTable');
    const utm = data.utm_cohorts || [];
    if (!utm.length) {
      ut.innerHTML = '<tbody><tr><td class="empty"><div class="sub">Нет кампаний с данными</div></td></tr></tbody>';
    } else {
      ut.innerHTML = `
        <thead><tr>
          <th>Источник</th><th class="text-r">Юзеры</th><th class="text-r">LTV/ю</th><th class="text-r">CAC</th><th class="text-r">ROI</th>
        </tr></thead>
        <tbody>
          ${utm.map(c => {
            let roiTag = '<span class="tag tag-gray">—</span>';
            if (c.roi_pct !== null) {
              const cls = c.roi_pct > 50 ? 'tag-green' : c.roi_pct > 0 ? 'tag-yellow' : 'tag-red';
              roiTag = `<span class="tag ${cls}">${c.roi_pct > 0 ? '+' : ''}${c.roi_pct}%</span>`;
            }
            return `
            <tr>
              <td data-label="Источник">${esc(c.name)}</td>
              <td data-label="Юзеры" class="text-r num">${c.new_users}</td>
              <td data-label="LTV/ю" class="text-r num">${money(c.ltv_per_user)}</td>
              <td data-label="CAC" class="text-r num">${c.cac > 0 ? money(c.cac) : '—'}</td>
              <td data-label="ROI" class="text-r">${roiTag}</td>
            </tr>`;
          }).join('')}
        </tbody>`;
    }
  } catch (e) {}
}

async function loadCalendar() {
  const host = $('#renewalCalendar');
  try {
    const data = await proxy('/admin-api/analytics/calendar');
    if (!data.success) { host.innerHTML = '<div class="empty"><div class="title">Ошибка</div></div>'; return; }
    const days = data.days || [];
    const sum = data.summary || {};
    $('#calSummary').innerHTML = `Всего <b>${sum.total || 0}</b> · 7д <b>${sum.next7 || 0}</b> · 3д <b>${sum.next3 || 0}</b>`;
    if (!days.length) {
      host.innerHTML = '<div class="empty"><span class="emoji">📭</span><div class="title">Нет продлений в ближайшие 30 дней</div></div>';
      return;
    }
    host.innerHTML = days.map(d => {
      const urgency = d.items[0].days_left <= 1 ? 'urgent' : d.items[0].days_left <= 3 ? 'soon' : '';
      return `
        <div class="cal-day ${urgency}">
          <div class="cal-day-head">
            <span class="cal-day-date">${calDate(d.date)}</span>
            <span class="cal-day-count">${d.items.length}</span>
          </div>
          <div class="cal-day-users">
            ${d.items.map(it => {
              const name = it.username ? '@' + it.username : [it.first_name, it.last_name].filter(Boolean).join(' ') || ('id:' + it.user_id);
              return `<div class="cal-user" onclick="openUserSheet('${it.user_id}')">
                <span class="cal-user-name">${esc(name)}</span>
                <span class="cal-user-dev">${it.devices || 1}📱</span>
              </div>`;
            }).join('')}
          </div>
        </div>`;
    }).join('');
  } catch (e) {
    host.innerHTML = '<div class="empty"><div class="title">Ошибка сети</div></div>';
  }
}

function monthName(ym) {
  const [y, m] = ym.split('-');
  const months = ['Янв','Фев','Мар','Апр','Май','Июн','Июл','Авг','Сен','Окт','Ноя','Дек'];
  return `${months[parseInt(m)-1]} ${y}`;
}
function calDate(ds) {
  const d = new Date(ds + 'T00:00:00');
  const days = ['Вс','Пн','Вт','Ср','Чт','Пт','Сб'];
  const months = ['янв','фев','мар','апр','мая','июн','июл','авг','сен','окт','ноя','дек'];
  return `${d.getDate()} ${months[d.getMonth()]}, ${days[d.getDay()]}`;
}


/* ==================== MAP v2: LIVE MODE ==================== */



/* ==================== SERVER MGMT: apply Reality + restart ==================== */
async function applyReality(sid) {
  const srv = (state.servers || []).find(s => String(s.id) === String(sid));
  const name = srv ? (srv.country_name || srv.code) : ('#' + sid);
  const sni = srv ? srv.sni : '?';
  if (!await showConfirm({ title: 'Применить Reality', message: `Применить настройки Reality на сервер "${name}"?\n\nНа сервер будет записан SNI = "${sni}" (из админки), затем Xray перезапустится.\n\nВ момент рестарта подключения на короткое время прервутся.`, okText: 'Применить' })) return;

  const card = document.querySelector(`.srv[data-sid="${sid}"]`);
  const btn = card && card.querySelector('[data-act="apply"]');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Применяю...'; }
  try {
    const r = await proxy(`/admin-api/servers/${sid}/apply_reality`, { method: 'POST', body: '{}' });
    if (r.success) {
      toast(`✅ ${r.message}. ${r.restarted ? 'Xray перезапущен.' : 'Рестарт: ' + (r.restart_msg || '?')}`, 'success');
    } else {
      toast('Ошибка: ' + (r.error || 'неизвестно'), 'error');
    }
  } catch (e) {
    toast('Ошибка сети', 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '📡 Применить SNI'; }
  }
}

async function restartXray(sid) {
  const srv = (state.servers || []).find(s => String(s.id) === String(sid));
  const name = srv ? (srv.country_name || srv.code) : ('#' + sid);
  if (!await showConfirm({ title: 'Перезапустить Xray', message: `Перезапустить Xray на сервере "${name}"?\n\nПодключения на короткое время прервутся.`, okText: 'Перезапустить' })) return;
  const card = document.querySelector(`.srv[data-sid="${sid}"]`);
  const btn = card && card.querySelector('[data-act="restart"]');
  if (btn) { btn.disabled = true; btn.textContent = '⏳...'; }
  try {
    const r = await proxy(`/admin-api/servers/${sid}/restart_xray`, { method: 'POST', body: '{}' });
    if (r.success) toast('♻️ ' + (r.message || 'Перезапущено'), 'success');
    else toast('Ошибка: ' + (r.message || r.error || '?'), 'error');
  } catch (e) {
    toast('Ошибка сети', 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '♻️ Рестарт'; }
  }
}


/* ==================== V3 UPDATE — TICKETS MESSENGER + BROADCAST V2 + RECEIPT ==================== */

if (typeof window.ticketState === 'undefined') {
  window.ticketState = { currentId: null, lastMsgId: 0, pollTimer: null };
}

async function openTicketChat(ticketId) {
  ticketState.currentId = ticketId;
  ticketState.lastMsgId = 0;
  $('#ticketChatNum').textContent = '#' + ticketId;
  $('#ticketChatStatus').innerHTML = '<span class="tag tag-gray">загрузка...</span>';
  $('#ticketChatUser').textContent = '—';
  $('#ticketChatMeta').textContent = '—';
  $('#ticketChatMsgs').innerHTML = '<div class="empty"><div class="title">Загрузка...</div></div>';
  $('#ticketChatActions').innerHTML = '';
  $('#ticketChatInput').value = '';
  openModal('ticketChatModal');
  await loadTicketChat(ticketId);
  if (!$('#ticketChatSendBtn').dataset.bound) {
    $('#ticketChatSendBtn').dataset.bound = '1';
    $('#ticketChatSendBtn').addEventListener('click', sendTicketReply);
    $('#ticketChatInput').addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendTicketReply(); }
    });
  }
  if (ticketState.pollTimer) clearInterval(ticketState.pollTimer);
  ticketState.pollTimer = setInterval(() => {
    if (ticketState.currentId === ticketId && $('#ticketChatModal').classList.contains('open')) {
      pollTicketMessages(ticketId);
    } else { clearInterval(ticketState.pollTimer); ticketState.pollTimer = null; }
  }, 5000);
  const modal = $('#ticketChatModal');
  const stopPoll = () => {
    if (ticketState.pollTimer) { clearInterval(ticketState.pollTimer); ticketState.pollTimer = null; }
    ticketState.currentId = null;
  };
  modal.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', stopPoll, { once: true }));
  modal.addEventListener('click', e => { if (e.target === modal) stopPoll(); }, { once: true });
}

async function loadTicketChat(ticketId) {
  try {
    const data = await proxy(`/admin-api/tickets/${ticketId}`);
    if (!data.success) {
      $('#ticketChatMsgs').innerHTML = `<div class="empty"><div class="title">Ошибка: ${esc(data.error || '?')}</div></div>`;
      return;
    }
    const t = data.ticket;
    const msgs = data.messages || [];
    renderTicketChatHead(t);
    renderTicketChatMsgs(msgs, true);
    renderTicketChatActions(t);
    if (msgs.length) ticketState.lastMsgId = Math.max(...msgs.map(m => m.id));
  } catch (e) {
    $('#ticketChatMsgs').innerHTML = '<div class="empty"><div class="title">Ошибка сети</div></div>';
  }
}

function renderTicketChatHead(t) {
  const statusMap = { open: { cls: 'tag-yellow', text: 'Открыт' }, in_progress: { cls: 'tag-blue', text: 'В работе' }, closed: { cls: 'tag-gray', text: 'Закрыт' } };
  const st = statusMap[t.status] || { cls: 'tag-gray', text: t.status };
  $('#ticketChatStatus').innerHTML = `<span class="tag ${st.cls} dot">${st.text}</span>`;
  const u = t.user || {};
  const name = [u.first_name, u.last_name].filter(Boolean).join(' ') || ('id:' + t.user_id);
  const handle = u.username ? '@' + u.username : '';
  $('#ticketChatUser').innerHTML = `<b>${esc(name)}</b> ${handle ? `<span class="muted">${esc(handle)}</span>` : ''} <span class="mono muted">${t.user_id}</span>`;
  let meta = '';
  if (t.subject) meta += `<span>📝 ${esc(t.subject)}</span>`;
  if (t.assigned_admin) {
    const aname = t.assigned_admin.full_name || t.assigned_admin.username || ('id:' + t.assigned_admin_id);
    meta += ` <span>· 👤 ${esc(aname)}</span>`;
  }
  meta += ` <span class="muted">· создан ${fmtDateShort(t.created_at)}</span>`;
  if (t.closed_at) meta += ` <span class="muted">· закрыт ${fmtDateShort(t.closed_at)}</span>`;
  $('#ticketChatMeta').innerHTML = meta;
}

function renderTicketChatMsgs(msgs, scrollToBottom) {
  const host = $('#ticketChatMsgs');
  if (!msgs.length) { host.innerHTML = '<div class="empty"><div class="title">Сообщений нет</div></div>'; return; }
  host.innerHTML = msgs.map(m => {
    const isUser = m.sender_type === 'user';
    return `<div class="msg ${isUser ? 'msg-user' : 'msg-admin'}"><div class="msg-bubble"><div class="msg-name">${esc(m.sender_name || (isUser ? 'Пользователь' : 'Поддержка'))}</div><div class="msg-text">${escMsg(m.message_text || '')}</div><div class="msg-time">${fmtTimeShort(m.created_at)}</div></div></div>`;
  }).join('');
  if (scrollToBottom) requestAnimationFrame(() => { host.scrollTop = host.scrollHeight; });
}

function renderTicketChatActions(t) {
  const me = state.currentAdminId;
  const isMine = me && t.assigned_admin_id && Number(t.assigned_admin_id) === Number(me);
  const isClosed = t.status === 'closed';
  let html = '';
  if (isClosed) {
    html = `<button class="btn btn-ghost btn-sm" id="actReopen">↻ Переоткрыть</button>`;
  } else {
    if (!t.assigned_admin_id) html += `<button class="btn btn-primary btn-sm" id="actTake">✋ Взять в работу</button>`;
    else if (!isMine) {
      const aname = (t.assigned_admin && (t.assigned_admin.full_name || t.assigned_admin.username)) || ('id:' + t.assigned_admin_id);
      html += `<button class="btn btn-ghost btn-sm" id="actTake" title="Перехватить">✋ Взять (у ${esc(aname)})</button>`;
    }
    html += `<button class="btn btn-success btn-sm" id="actClose">✓ Закрыть</button>`;
  }
  $('#ticketChatActions').innerHTML = html;
  const tb = $('#actTake'); if (tb) tb.addEventListener('click', () => takeTicket(t.id, t.assigned_admin_id, t.assigned_admin));
  const cb = $('#actClose'); if (cb) cb.addEventListener('click', () => closeTicket(t.id));
  const rb = $('#actReopen'); if (rb) rb.addEventListener('click', () => reopenTicket(t.id));
}

async function takeTicket(id, curAdminId, curAdminObj) {
  const me = state.currentAdminId;
  if (curAdminId && Number(curAdminId) !== Number(me)) {
    const aname = (curAdminObj && (curAdminObj.full_name || curAdminObj.username)) || ('id:' + curAdminId);
    if (!await showConfirm({ title: 'Перехватить тикет', message: `Тикет сейчас в работе у ${aname}.\n\nПерехватить себе?`, okText: 'Перехватить' })) return;
  }
  const r = await proxy(`/admin-api/tickets/${id}/take`, { method: 'POST', body: JSON.stringify({ force: true }) });
  if (r.success) { toast('✋ Взято в работу', 'success'); loadTicketChat(id); if (state.currentPage === 'tickets') renderTicketsTable(); }
  else toast('Ошибка: ' + (r.error || '?'), 'error');
}
async function closeTicket(id) {
  if (!await showConfirm({ title: 'Закрыть тикет', message: 'Закрыть тикет?', okText: 'Закрыть' })) return;
  const r = await proxy(`/admin-api/tickets/${id}/close`, { method: 'POST', body: '{}' });
  if (r.success) { toast('✓ Закрыт', 'success'); loadTicketChat(id); if (state.currentPage === 'tickets') renderTicketsTable(); }
  else toast('Ошибка: ' + (r.error || '?'), 'error');
}
async function reopenTicket(id) {
  const r = await proxy(`/admin-api/tickets/${id}/reopen`, { method: 'POST', body: '{}' });
  if (r.success) { toast('↻ Переоткрыт', 'success'); loadTicketChat(id); if (state.currentPage === 'tickets') renderTicketsTable(); }
  else toast('Ошибка: ' + (r.error || '?'), 'error');
}
async function sendTicketReply() {
  const id = ticketState.currentId;
  if (!id) return;
  const inp = $('#ticketChatInput');
  const text = (inp.value || '').trim();
  if (!text) return;
  const btn = $('#ticketChatSendBtn');
  btn.disabled = true;
  try {
    const r = await proxy(`/admin-api/tickets/${id}/reply`, { method: 'POST', body: JSON.stringify({ text }) });
    if (r.success) { inp.value = ''; await pollTicketMessages(id); }
    else toast('Не отправлено: ' + (r.error || '?'), 'error');
  } catch (e) { toast('Ошибка сети', 'error'); }
  finally { btn.disabled = false; inp.focus(); }
}
async function pollTicketMessages(ticketId) {
  if (ticketState.currentId !== ticketId) return;
  try {
    const data = await proxy(`/admin-api/tickets/${ticketId}/messages?after=${ticketState.lastMsgId}`);
    if (data.success && data.messages && data.messages.length) {
      const full = await proxy(`/admin-api/tickets/${ticketId}`);
      if (full.success) {
        renderTicketChatHead(full.ticket);
        renderTicketChatMsgs(full.messages || [], true);
        renderTicketChatActions(full.ticket);
        const msgs = full.messages || [];
        if (msgs.length) ticketState.lastMsgId = Math.max(...msgs.map(m => m.id));
      }
    }
  } catch (e) {}
}
function escMsg(s) { return esc(String(s)).replace(/\n/g, '<br>'); }
function fmtTimeShort(iso) { try { return new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }); } catch (e) { return iso || ''; } }
function fmtDateShort(iso) { try { return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' }); } catch (e) { return iso || ''; } }


/* === BROADCAST V2 === */
if (typeof window.bcState === 'undefined' || !('customIds' in window.bcState)) {
  window.bcState = { audience: 'all', campaign: 'all', customIds: [], targetUserId: null };
}
function bcReset() {
  bcState.audience = 'all'; bcState.campaign = 'all'; bcState.customIds = []; bcState.targetUserId = null;
  const bb = $('#bcButton'); if (bb) bb.value = '';
}

const BC_AUDIENCE_TEMPLATES = {
  all: `📢 Привет!

Хотим поделиться с тобой новостью — мы постоянно работаем над улучшением TuVPN, чтобы тебе было удобнее.

[опиши что нового]

Спасибо что выбираете нас ❤️`,
  active: `❤️ Спасибо что ты с нами!

Ты — один из наших постоянных пользователей, и мы это очень ценим.

[опционально: какой-то бонус/подарок]

Хорошего тебе соединения 🚀`,
  inactive: `👋 Эй, привет!

Давно тебя не видели в TuVPN. Хотим вернуть тебя — лови персональную скидку.

🎁 Промокод PROMO20 — 20% на любую подписку

Жми → Подключиться`,
  utm_no_device: `👋 Привет!

Заметили, что ты заходил в наш бот, но VPN ещё не настроил. Может что-то пошло не так?

Если нужна помощь с настройкой — напиши в поддержку, поможем разобраться за 1 минуту.`,
  expired_unpaid_14d: `👋 Привет!

Твоя подписка TuVPN закончилась некоторое время назад. Хочешь вернуться?

🎁 Промокод PROMO40 — скидка 40% на любую подписку

Жми → Продлить`,
  expires_6h: `⏰ Привет!
Твоя подписка TuVPN скоро заканчивается. Самое время продлить, чтобы не остаться без VPN.
🎁 Промокод PROMO20 — скидка 20% на любую подписку
Жми → Продлить`,
  utm_never_paid: `👋 Привет!

Ты пришёл к нам, но ещё не попробовал TuVPN в деле. Предлагаем тебе попробовать — по специальной цене.

🎁 Промокод WELCOME30 — скидка 30% на первую подписку

Хочешь быстрый интернет без блокировок? Жми → Подключиться`,
  utm_expired: `👋 Привет!

Помним, что ты уже пользовался TuVPN. Хотим вернуть тебя обратно — со скидкой!

🎁 Промокод BACK20 — скидка 20% на продление

Жми → Продлить`,
  custom_list: '',
};

async function bcApplyTemplateForAudience(aud) {
  const tpl = BC_AUDIENCE_TEMPLATES[aud];
  if (tpl === undefined) return;
  const txt = document.getElementById('bcMessageText');
  if (!txt) return;
  const current = (txt.value || '').trim();
  // если текст уже не пустой и не совпадает ни с одним шаблоном — спрашиваем подтверждение
  if (current && !Object.values(BC_AUDIENCE_TEMPLATES).map(s => s.trim()).includes(current)) {
    if (!await showConfirm({ title: 'Заменить текст', message: 'У тебя уже введён свой текст. Заменить на шаблон для этой аудитории?', okText: 'Заменить' })) return;
  }
  txt.value = tpl;
}


async function bcOnAudChange() {
  const aud = bcState.audience;
  const utm = $('#bcExtraUtm'); const custom = $('#bcExtraCustom');
  const utmAuds = ['utm_no_device', 'utm_never_paid', 'utm_expired'];
  if (utm) utm.style.display = utmAuds.includes(aud) ? '' : 'none';
  if (custom) custom.style.display = (aud === 'custom_list') ? '' : 'none';
  // автоподстановка шаблона под когорту
  if (typeof bcApplyTemplateForAudience === 'function') {
    await bcApplyTemplateForAudience(aud);
  }
}
function bcBindModal() {
  document.querySelectorAll('input[name="bcAud"]').forEach(r => {
    r.addEventListener('change', e => { if (e.target.checked) { bcState.audience = e.target.value; bcOnAudChange(); } });
  });
  const cs = $('#bcCampaignFilter');
  if (cs) {
    cs.innerHTML = '<option value="all">Любая кампания</option>' + (state.campaigns || []).map(c => `<option value="${esc(c.code)}">${esc(c.name || c.code)}</option>`).join('');
    cs.addEventListener('change', e => { bcState.campaign = e.target.value; });
  }
  const search = $('#bcUserSearch');
  if (search && !search.dataset.bound) {
    search.dataset.bound = '1';
    let dt;
    search.addEventListener('input', () => { clearTimeout(dt); dt = setTimeout(() => bcRenderUserList(search.value.trim()), 200); });
    bcRenderUserList('');
  }
  const tpl = $('#bcTemplate');
  if (tpl && !tpl.dataset.bound) {
    tpl.dataset.bound = '1';
    tpl.addEventListener('change', () => { const t = bcTemplateText(tpl.value); if (t) $('#bcMessageText').value = t; });
  }
  const pb = $('#bcPreviewBtn');
  if (pb && !pb.dataset.bound) { pb.dataset.bound = '1'; pb.addEventListener('click', bcPreview); }
}
function bcTemplateText(name) {
  const m = {
    fix: '🔧 Привет! Мы починили технический сбой, и теперь VPN снова работает корректно. Спасибо за терпение!',
    apology: '❤️ Здравствуйте! Хотим извиниться за неудобства. В качестве компенсации даём бонусные дни к подписке.',
    renew: '⏰ Привет! Срок твоей подписки подходит к концу. Самое время продлить.',
    expire_soon: '⏰ Привет!\nТвоя подписка TuVPN скоро заканчивается. Самое время продлить, чтобы не остаться без VPN.\n🎁 Промокод PROMO20 — скидка 20% на любую подписку\nЖми → Продлить',
    news: '📢 Привет! Подключили новый сервер и ускорили все остальные.',
    howto: '📘 Инструкция: как настроить TuVPN на своём устройстве за 1 минуту.',
  };
  return m[name] || '';
}
function bcRenderUserListNew(query) {  // переименовываем чтоб не конфликтнуть со старой
  const host = $('#bcUserList');
  if (!host) return;
  const all = state.users || [];
  const q = (query || '').toLowerCase();
  const matched = q ? all.filter(u => {
    const name = ((u.first_name || '') + ' ' + (u.last_name || '')).toLowerCase();
    return name.includes(q) || (u.username || '').toLowerCase().includes(q) || String(u.user_id).includes(q);
  }).slice(0, 50) : all.slice(0, 30);
  if (!matched.length) { host.innerHTML = '<div class="bc-user-empty">никого не нашлось</div>'; return; }
  host.innerHTML = matched.map(u => {
    const name = [u.first_name, u.last_name].filter(Boolean).join(' ') || '—';
    const un = u.username ? '@' + u.username : '';
    const checked = bcState.customIds.includes(u.user_id);
    return `<label class="bc-user-row"><input type="checkbox" data-uid="${u.user_id}" ${checked ? 'checked' : ''}><span class="bc-user-row-name">${esc(name)}</span>${un ? `<span class="bc-user-row-handle">${esc(un)}</span>` : ''}<span class="bc-user-row-id muted">${u.user_id}</span></label>`;
  }).join('');
  host.querySelectorAll('input[type="checkbox"]').forEach(cb => {
    cb.addEventListener('change', e => {
      const uid = Number(e.target.dataset.uid);
      if (e.target.checked) { if (!bcState.customIds.includes(uid)) bcState.customIds.push(uid); }
      else bcState.customIds = bcState.customIds.filter(x => x !== uid);
      bcRenderSelectedList();
    });
  });
  bcRenderSelectedList();
}
// перенаправление если используется в HTML — старая (которая уже была в файле) тоже работает
window.bcRenderUserList = bcRenderUserListNew;

function bcRenderSelectedList() {
  const cnt = $('#bcSelectedCount'); if (cnt) cnt.textContent = bcState.customIds.length;
  const host = $('#bcSelectedList'); if (!host) return;
  if (!bcState.customIds.length) { host.innerHTML = '<div class="muted" style="font-size:12px">Никого не выбрано</div>'; return; }
  host.innerHTML = bcState.customIds.map(uid => {
    const u = (state.users || []).find(x => x.user_id === uid) || {};
    const name = [u.first_name, u.last_name].filter(Boolean).join(' ') || ('id:' + uid);
    return `<span class="bc-chip">${esc(name)} <button data-uid="${uid}">×</button></span>`;
  }).join('');
  host.querySelectorAll('button').forEach(b => {
    b.addEventListener('click', () => {
      const uid = Number(b.dataset.uid);
      bcState.customIds = bcState.customIds.filter(x => x !== uid);
      const cb = $('#bcUserList').querySelector(`input[data-uid="${uid}"]`);
      if (cb) cb.checked = false;
      bcRenderSelectedList();
    });
  });
}
const BC_BUTTON_LABELS = {
  buy: '💳 Продлить подписку',
  connect: '🔌 Подключиться',
  back: '🏠 Главное меню',
  howto: '📘 Инструкция',
};

async function bcPreview() {
  const text = ($('#bcMessageText').value || '').trim();
  if (!text) { toast('Введите текст', 'warning'); return; }
  if (bcState.audience === 'custom_list' && !bcState.customIds.length) { toast('Выберите хотя бы одного юзера', 'warning'); return; }
  const bonusDays = parseInt($('#bcBonusDays').value || '0', 10);
  const buttonAction = ($('#bcButton') && $('#bcButton').value) || '';
  try {
    const r = await proxy('/admin-api/broadcast/preview', {
      method: 'POST',
      body: JSON.stringify({
        audience: bcState.audience, campaign_filter: bcState.campaign,
        target_user_id: null, target_user_ids: bcState.audience === 'custom_list' ? bcState.customIds : null,
      })
    });
    if (!r.success) { toast('Ошибка: ' + (r.error || '?'), 'error'); return; }
    const audLabels = { all: '📢 Все', active: '✅ С подпиской', inactive: '⏸ Без подписки', utm_no_device: '🎯 UTM без устройства', expired_unpaid_14d: '💤 Истекли 14д', custom_list: `👤 Выбранные (${bcState.customIds.length})` };
    const _set = (sel, val) => { const el = $(sel); if (el) el.textContent = val; };
    _set('#bcPreviewAud', audLabels[bcState.audience] || bcState.audience);
    _set('#bcPreviewCount', r.count || 0);
    _set('#bcPreviewText', text);
    _set('#bcPreviewBonus', bonusDays > 0 ? bonusDays + ' дней' : '—');
    // кнопка в превью
    const btnWrap = $('#bcPreviewBtnWrap');
    const btnLabel = $('#bcPreviewBtnLabel');
    if (btnWrap && btnLabel) {
      if (buttonAction && BC_BUTTON_LABELS[buttonAction]) {
        btnLabel.textContent = BC_BUTTON_LABELS[buttonAction];
        btnWrap.style.display = '';
      } else {
        btnWrap.style.display = 'none';
      }
    }
    closeModal('broadcastModal');
    openModal('broadcastPreviewModal');
    const sb = $('#bcSendConfirmBtn') || $('#bcSendBtn') || document.querySelector('#broadcastPreviewModal .btn-primary');
    if (sb) {
      const fresh = sb.cloneNode(true);
      sb.parentNode.replaceChild(fresh, sb);
      fresh.addEventListener('click', () => bcSend(text, bonusDays, buttonAction));
    }
  } catch (e) { toast('Ошибка сети', 'error'); }
}
async function bcSend(text, bonusDays, buttonAction) {
  const sb = document.querySelector('#broadcastPreviewModal .btn-primary');
  if (sb) sb.disabled = true;
  try {
    const r = await proxy('/admin-api/broadcast/send', {
      method: 'POST',
      body: JSON.stringify({
        audience: bcState.audience, campaign_filter: bcState.campaign,
        message_text: text, bonus_days: bonusDays,
        button_action: buttonAction || null,
        target_user_id: null, target_user_ids: bcState.audience === 'custom_list' ? bcState.customIds : null,
      })
    });
    if (r.success) {
      toast(`📨 Отправлено: ${r.sent || 0}, ошибок: ${r.failed || 0}`, 'success');
      closeModal('broadcastPreviewModal');
      bcReset();
      if (state.currentPage === 'broadcast') renderBroadcast();
    } else toast('Ошибка: ' + (r.error || '?'), 'error');
  } catch (e) { toast('Ошибка сети', 'error'); }
  finally { if (sb) sb.disabled = false; }
}

// Перехват openModal('broadcastModal') — bind при первом открытии
(function() {
  if (window._bcInterceptInstalled) return;
  window._bcInterceptInstalled = true;
  const _origOpen = window.openModal;
  if (typeof _origOpen !== 'function') return;
  window.openModal = function(id) {
    if (id === 'broadcastModal') {
      bcReset();
      const result = _origOpen(id);
      setTimeout(() => {
        bcBindModal(); bcOnAudChange();
        const r = document.querySelector('input[name="bcAud"][value="all"]');
        if (r) r.checked = true;
      }, 30);
      return result;
    }
    return _origOpen(id);
  };
})();


/* === RECEIPT MODAL === */
let _receiptCurrentPayId = null;
function openReceiptModal(payId) {
  const p = (state.payments || []).find(x => Number(x.id) === Number(payId));
  if (!p) { toast('Платёж не найден', 'error'); return; }
  _receiptCurrentPayId = payId;
  const u = (state.users || []).find(x => x.user_id === p.user_id) || {};
  const name = [u.first_name, u.last_name].filter(Boolean).join(' ') || ('id:' + p.user_id);
  const handle = u.username ? '@' + u.username : '';
  const paidDate = p.paid_at ? fmtDateShort(p.paid_at) : (p.created_at ? fmtDateShort(p.created_at) : '—');
  $('#receiptInfoBlock').innerHTML = `<div class="info"><div class="info-k">Пользователь</div><div class="info-v">${esc(name)} ${esc(handle)}</div></div><div class="info"><div class="info-k">Платёж #</div><div class="info-v mono">${p.id}</div></div><div class="info"><div class="info-k">Сумма</div><div class="info-v"><b>${money(p.amount)}</b></div></div><div class="info"><div class="info-k">Дата</div><div class="info-v">${paidDate}</div></div>`;
  $('#receiptUrlInput').value = '';
  updateReceiptPreview();
  const inp = $('#receiptUrlInput');
  if (!inp.dataset.bound) { inp.dataset.bound = '1'; inp.addEventListener('input', updateReceiptPreview); }
  const sb = $('#receiptSendBtn');
  if (!sb.dataset.bound) { sb.dataset.bound = '1'; sb.addEventListener('click', sendReceipt); }
  openModal('receiptRegisterModal');
}
function updateReceiptPreview() {
  const url = ($('#receiptUrlInput').value || '').trim();
  const p = (state.payments || []).find(x => Number(x.id) === Number(_receiptCurrentPayId));
  if (!p) return;
  const paidDate = p.paid_at ? fmtDateShort(p.paid_at) : (p.created_at ? fmtDateShort(p.created_at) : '—');
  const urlPart = url ? `\n\n📄 Посмотреть чек: ${url}` : '\n\n📄 [ссылка появится после ввода]';
  $('#receiptPreviewBox').textContent = `✅ Спасибо за оплату подписки TuVPN!\n\nЧек на сумму ${p.amount}₽ от ${paidDate} оформлен через ФНС.${urlPart}\n\nСпасибо что выбираете нас! ❤️`;
}
async function sendReceipt() {
  const url = ($('#receiptUrlInput').value || '').trim();
  if (url && !url.startsWith('http://') && !url.startsWith('https://')) {
    toast('Ссылка должна начинаться с http:// или https://', 'warning'); return;
  }
  const btn = $('#receiptSendBtn');
  btn.disabled = true; btn.textContent = 'Сохраняю...';
  try {
    const sendNotif = document.getElementById('receiptSendSms')?.checked ?? false;
    const body = { send_sms: sendNotif };
    if (url) body.receipt_url = url;
    const r = await proxy(`/admin-api/payments/${_receiptCurrentPayId}/register_receipt`, { method: 'POST', body: JSON.stringify(body) });
    if (r.success) {
      if (sendNotif && r.delivered) toast('✅ Чек помечен, уведомление отправлено', 'success');
      else if (sendNotif && !r.delivered) toast('⚠️ Чек помечен, но уведомление не дошло', 'warning');
      else toast('✅ Чек помечен как оформленный', 'success');
      closeModal('receiptRegisterModal');
      const p = state.payments.find(x => Number(x.id) === Number(_receiptCurrentPayId));
      if (p) { p.receipt_status = 'registered'; if (url) p.receipt_url = url; }
      if (state.currentPage === 'payments') renderPaymentsTable();
    } else toast('Ошибка: ' + (r.error || '?'), 'error');
  } catch (e) { toast('Ошибка сети', 'error'); }
  finally { btn.disabled = false; btn.textContent = 'Пометить чек'; }
}


/* UI-FIX: старая кнопка "Новая рассылка" вызывала openBroadcastModal — направим её на openBroadcastForm */
if (typeof openBroadcastForm === 'function') {
  window.openBroadcastModal = openBroadcastForm;
}



/* ===================================================================== */
/* ============ FINANCE & ROLES ======================================== */
/* ===================================================================== */

/* hooks: привязка save-кнопок модалок (через делегирование, на всякий) */
(function() {
  document.addEventListener('click', (e) => {
    const id = e.target?.id;
    if (id === 'finExpenseSaveBtn') saveExpense();
    else if (id === 'finInvSaveBtn') saveInvestment();
    else if (id === 'finPlanSaveBtn') savePlanned();
    else if (id === 'roleSaveBtn') saveRole();
    else if (id === 'adminSaveBtn') saveAdmin();
  });
})();


/* ===================================================================== */
/* ============ FINANCE & ROLES — REBUILD в стиле проекта ============== */
/* ===================================================================== */

// Категории расходов
const EXPENSE_CATEGORIES = {
  servers: { label: '🖥 Серверы', color: '#4fc4cf' },
  domains: { label: '🌐 Домены', color: '#9b8fff' },
  ads:     { label: '📢 Реклама', color: '#ffb84f' },
  dev:     { label: '💻 Разработка', color: '#4fcf78' },
  other:   { label: '🔧 Прочее', color: '#94a3b8' },
};

// Группы прав для UI

// =========================================================
// FINANCE
// =========================================================


function renderFinExpensesTable(catFilter) {
  const tbody = $('#finExpensesTbody');
  if (!tbody) return;
  const canEdit = hasPermission('edit_finance');
  let list = state.finance.expenses.slice();
  if (catFilter && catFilter !== 'all') list = list.filter(e => e.category === catFilter);
  list.sort((a, b) => (b.expense_date || '').localeCompare(a.expense_date || ''));

  if (!list.length) {
    tbody.innerHTML = `<tr><td colspan="${canEdit ? 5 : 4}"><div class="empty"><div class="title">Нет расходов</div></div></td></tr>`;
    return;
  }
  tbody.innerHTML = list.map(e => {
    const cat = EXPENSE_CATEGORIES[e.category] || { label: e.category };
    return `<tr>
      <td><span class="mono">${esc(e.expense_date)}</span></td>
      <td>${cat.label}</td>
      <td>${esc(e.description || '')}</td>
      <td class="text-r"><span class="num" style="color:var(--red);font-weight:600">${money(e.amount)}</span></td>
      ${canEdit ? `<td class="text-r">
        <button class="btn btn-ghost btn-sm" data-act="ed" data-id="${e.id}">✎</button>
        <button class="btn btn-ghost btn-sm" data-act="del" data-id="${e.id}">🗑</button>
      </td>` : ''}
    </tr>`;
  }).join('');
  $$('#finExpensesTbody [data-act="ed"]').forEach(b => b.addEventListener('click', () =>
    openExpenseModal(state.finance.expenses.find(x => x.id == b.dataset.id))));
  $$('#finExpensesTbody [data-act="del"]').forEach(b => b.addEventListener('click', () =>
    confirmDeleteExpense(Number(b.dataset.id))));
}

function renderFinPlannedTable() {
  const tbody = $('#finPlannedTbody');
  if (!tbody) return;
  const canEdit = hasPermission('edit_finance');
  const list = state.finance.planned.slice().sort((a, b) => (a.planned_date || 'z').localeCompare(b.planned_date || 'z'));

  if (!list.length) {
    tbody.innerHTML = `<tr><td colspan="${canEdit ? 6 : 5}"><div class="empty"><div class="title">Нет плановых покупок</div></div></td></tr>`;
    return;
  }
  tbody.innerHTML = list.map(p => {
    const cat = EXPENSE_CATEGORIES[p.category] || { label: p.category };
    return `<tr class="${p.is_done ? 'row-done' : ''}">
      <td><input type="checkbox" ${p.is_done ? 'checked' : ''} ${canEdit ? `data-tog-id="${p.id}"` : 'disabled'}></td>
      <td><span class="mono">${esc(p.planned_date || '—')}</span></td>
      <td>${cat.label}</td>
      <td>${esc(p.description)}</td>
      <td class="text-r">${p.estimated_amount ? money(p.estimated_amount) : '—'}</td>
      ${canEdit ? `<td class="text-r">
        <button class="btn btn-ghost btn-sm" data-act="del-p" data-id="${p.id}">🗑</button>
      </td>` : ''}
    </tr>`;
  }).join('');
  $$('#finPlannedTbody [data-tog-id]').forEach(c => c.addEventListener('change', () =>
    togglePlanned(Number(c.dataset.togId), c.checked)));
  $$('#finPlannedTbody [data-act="del-p"]').forEach(b => b.addEventListener('click', () =>
    confirmDeletePlanned(Number(b.dataset.id))));
}

// ---- Модалки финансов ----

function openExpenseModal(existing) {
  const isEdit = !!existing;
  $('#finExpenseModalTitle').textContent = isEdit ? 'Редактировать расход' : 'Добавить расход';
  $('#finExpenseId').value = existing?.id || '';
  $('#finExpenseDate').value = existing?.expense_date || new Date().toISOString().slice(0, 10);
  $('#finExpenseCategory').value = existing?.category || 'servers';
  $('#finExpenseDesc').value = existing?.description || '';
  $('#finExpenseAmount').value = existing?.amount || '';
  $('#finExpenseRecurring').checked = !!existing?.is_recurring;
  $('#finExpensePeriod').value = existing?.recurring_period || 'monthly';
  openModal('finExpenseModal');
}


async function confirmDeleteExpense(id) {
  if (!await showConfirm({ title: 'Удалить расход', message: 'Удалить расход?', okText: 'Удалить', danger: true })) return;
  const r = await fetch(`/admin-api/finance/expenses/${id}`, { method: 'DELETE' });
  if (r.ok) { toast('Удалено', 'success'); renderFinancePage(); }
  else toast('Ошибка удаления', 'error');
}

function openInvestmentModal() {
  $('#finInvId').value = '';
  $('#finInvName').value = '';
  $('#finInvTgId').value = '';
  $('#finInvAmount').value = '';
  $('#finInvDate').value = new Date().toISOString().slice(0, 10);
  $('#finInvNote').value = '';
  openModal('finInvestmentModal');
}


function openPlannedModal() {
  $('#finPlanId').value = '';
  $('#finPlanDate').value = '';
  $('#finPlanCategory').value = 'servers';
  $('#finPlanDesc').value = '';
  $('#finPlanAmount').value = '';
  openModal('finPlannedModal');
}

async function savePlanned() {
  const body = {
    planned_date: $('#finPlanDate').value || null,
    category: $('#finPlanCategory').value,
    description: $('#finPlanDesc').value.trim(),
    estimated_amount: parseFloat($('#finPlanAmount').value || '0') || null,
  };
  if (!body.description) { toast('Заполни описание', 'error'); return; }
  const r = await fetch('/admin-api/finance/planned', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
  });
  if (r.ok) { toast('Добавлено', 'success'); closeModal('finPlannedModal'); renderFinancePage(); }
  else { const e = await r.json().catch(() => ({})); toast('Ошибка: ' + (e.error || r.status), 'error'); }
}

async function togglePlanned(id, isDone) {
  const r = await fetch(`/admin-api/finance/planned/${id}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_done: isDone })
  });
  if (!r.ok) toast('Ошибка', 'error');
}

async function confirmDeletePlanned(id) {
  if (!await showConfirm({ title: 'Удалить покупку', message: 'Удалить плановую покупку?', okText: 'Удалить', danger: true })) return;
  const r = await fetch(`/admin-api/finance/planned/${id}`, { method: 'DELETE' });
  if (r.ok) { toast('Удалено', 'success'); renderFinancePage(); }
  else toast('Ошибка', 'error');
}


// =========================================================
// ROLES & ADMINS — только для суперадмина
// =========================================================

async function renderRolesPage() {
  const host = $('#page-roles');
  if (!host) return;
  if (!state.isSuperadmin) {
    host.innerHTML = '<div class="empty"><span class="emoji">⛔</span><div class="title">Только для суперадмина</div></div>';
    return;
  }

  let roles = [], admins = [];
  try {
    const [r1, r2] = await Promise.all([
      fetch('/admin-api/roles', { credentials: 'include' }).then(r => r.json()),
      fetch('/admin-api/admin-users', { credentials: 'include' }).then(r => r.json()),
    ]);
    roles = Array.isArray(r1) ? r1 : (r1.roles || []);
    admins = Array.isArray(r2) ? r2 : (r2.admins || []);
  } catch (e) {
    host.innerHTML = '<div class="empty"><div class="title">Ошибка загрузки</div><div class="sub">' + esc(e.message || '') + '</div></div>';
    return;
  }
  state.roles = roles;
  state.admins = admins;

  // имя суперадмина — из state.me.name или из users
  let superName = state.me && state.me.name;
  if (!superName) {
    const u = (state.users || []).find(x => x.user_id === (state.me && state.me.user_id));
    if (u) superName = [u.first_name, u.last_name].filter(Boolean).join(' ') || u.username;
  }
  if (!superName) superName = 'ты';

  host.innerHTML = `
    <div class="page-title">Роли и доступы</div>
    <div class="page-sub">Управление правами админов</div>

    <div class="kpi-grid">
      <div class="kpi"><div class="kpi-head"><span class="kpi-label">Ролей</span></div><div class="kpi-value num">${roles.length}</div></div>
      <div class="kpi"><div class="kpi-head"><span class="kpi-label">Админов</span></div><div class="kpi-value num">${admins.filter(a => a.is_active).length}</div></div>
      <div class="kpi"><div class="kpi-head"><span class="kpi-label">Всего прав</span></div><div class="kpi-value num">${(state.allPermissions || []).length}</div></div>
      <div class="kpi"><div class="kpi-head"><span class="kpi-label">Суперадмин</span></div><div class="kpi-value num" style="color:var(--accent);font-size:14px">${esc(superName)}</div></div>
    </div>

    <div class="fin-grid">
      <div class="card">
        <div class="card-head">
          <div class="card-title">Роли</div>
          <button class="btn btn-primary btn-sm" id="roleAddBtn">+ Роль</button>
        </div>
        <div id="rolesList"></div>
      </div>
      <div class="card">
        <div class="card-head">
          <div class="card-title">Админы</div>
          <button class="btn btn-primary btn-sm" id="adminAddBtn">+ Админ</button>
        </div>
        <div id="adminsList"></div>
      </div>
    </div>
  `;

  renderRolesList();
  renderAdminsList();
  $('#roleAddBtn').addEventListener('click', () => openRoleModal());
  $('#adminAddBtn').addEventListener('click', () => openAdminModal());
}



// Строим UI чекбоксов прав из state.sections (один источник правды)
function buildPermissionsUI(currentPermsSet, tripleMode) {
  // tripleMode=false для ролей (один чекбокс)
  // tripleMode=true для админов (две колонки: +добавить / −отозвать)
  let html = '';
  for (const [secKey, sec] of Object.entries(state.sections)) {
    if (sec.superadmin_only) continue;  // суперадмин-only права НЕ показываем
    const items = [];
    if (sec.view_perm) {
      items.push([sec.view_perm, '👁 ' + (sec.title || secKey)]);
    }
    for (const [actKey, actLabel] of Object.entries(sec.actions || {})) {
      items.push([actKey, actLabel]);
    }
    if (!items.length) continue;
    html += `<div class="perm-group">
      <div class="perm-group-title">${esc(sec.title || secKey)}</div>
      <div class="perm-list">`;
    for (const [key, label] of items) {
      if (tripleMode) {
        const addedSet = currentPermsSet && currentPermsSet.added;
        const removedSet = currentPermsSet && currentPermsSet.removed;
        const a = addedSet && addedSet.has(key) ? 'checked' : '';
        const r = removedSet && removedSet.has(key) ? 'checked' : '';
        html += `<div class="perm-row-tri">
          <span class="perm-row-label">${esc(label)} <span class="mono muted">${esc(key)}</span></span>
          <label class="perm-mini" title="Дать сверх роли"><input type="checkbox" data-add="${esc(key)}" ${a}> <span style="color:var(--green)">+</span></label>
          <label class="perm-mini" title="Забрать из роли"><input type="checkbox" data-rem="${esc(key)}" ${r}> <span style="color:var(--red)">−</span></label>
        </div>`;
      } else {
        const checked = currentPermsSet && currentPermsSet.has(key) ? 'checked' : '';
        html += `<label class="perm-row">
          <input type="checkbox" value="${esc(key)}" ${checked}>
          <span>${esc(label)}</span>
          <span class="mono muted">${esc(key)}</span>
        </label>`;
      }
    }
    html += '</div></div>';
  }
  return html;
}





function renderRolesList() {
  const host = $('#rolesList');
  if (!state.roles.length) {
    host.innerHTML = '<div class="empty"><div class="title">Ролей пока нет</div></div>';
    return;
  }
  host.innerHTML = state.roles.map(r => `
    <div class="adm-item">
      <div class="adm-item-main">
        <div class="adm-item-name">${esc(r.name)}</div>
        <div class="adm-item-sub">${esc(r.description || '—')} · <b>${(r.permissions || []).length}</b> прав</div>
      </div>
      <div class="adm-item-acts">
        <button class="btn btn-ghost btn-sm" data-rid="${r.id}" data-act="ed-role">✎</button>
        <button class="btn btn-ghost btn-sm" data-rid="${r.id}" data-act="del-role">🗑</button>
      </div>
    </div>
  `).join('');
  $$('#rolesList [data-act="ed-role"]').forEach(b => b.addEventListener('click', () =>
    openRoleModal(state.roles.find(r => r.id == b.dataset.rid))));
  $$('#rolesList [data-act="del-role"]').forEach(b => b.addEventListener('click', async () => {
    if (!await showConfirm({ title: 'Удалить роль', message: 'Удалить роль?', okText: 'Удалить', danger: true })) return;
    const r = await fetch(`/admin-api/roles/${b.dataset.rid}`, { method: 'DELETE' });
    if (r.ok) { toast('Удалено', 'success'); renderRolesPage(); }
    else toast('Ошибка', 'error');
  }));
}

function renderAdminsList() {
  const host = $('#adminsList');
  if (!state.admins.length) {
    host.innerHTML = '<div class="empty"><div class="title">Админов нет</div></div>';
    return;
  }
  host.innerHTML = state.admins.map(a => {
    const role = state.roles.find(r => r.id == a.role_id);
    const cls = a.is_active ? '' : 'adm-item-off';
    return `<div class="adm-item ${cls}">
      <div class="adm-item-main">
        <div class="adm-item-name">${esc(a.full_name || a.username || ('id:' + a.user_id))}</div>
        <div class="adm-item-sub">
          ${a.username ? '<span class="mono">@' + esc(a.username) + '</span> · ' : ''}
          <span class="mono">${a.user_id}</span>
          ${role ? '<span class="tag tag-blue" style="margin-left:6px">' + esc(role.name) + '</span>' : '<span class="muted" style="margin-left:6px">без роли</span>'}
          ${(a.added_permissions || []).length ? '<span class="tag tag-green" style="margin-left:4px">+' + a.added_permissions.length + '</span>' : ''}
          ${(a.removed_permissions || []).length ? '<span class="tag tag-red" style="margin-left:4px">−' + a.removed_permissions.length + '</span>' : ''}
        </div>
      </div>
      <div class="adm-item-acts">
        <button class="btn btn-ghost btn-sm" data-uid="${a.user_id}" data-act="ed-admin">✎</button>
      </div>
    </div>`;
  }).join('');
  $$('#adminsList [data-act="ed-admin"]').forEach(b => b.addEventListener('click', () =>
    openAdminModal(state.admins.find(a => a.user_id == b.dataset.uid))));
}

// ---- Модалка роли ----

function openRoleModal(existing) {
  $('#roleModalTitle').textContent = existing ? 'Редактировать роль' : 'Новая роль';
  $('#roleId').value = existing?.id || '';
  $('#roleName').value = existing?.name || '';
  $('#roleDesc').value = existing?.description || '';
  const currentSet = new Set(existing?.permissions || []);
  $('#rolePermsHost').innerHTML = buildPermissionsUI(currentSet, false);
  openModal('roleModal');
}

async function saveRole() {
  const id = $('#roleId').value;
  const perms = Array.from($('#rolePermsHost').querySelectorAll('input:checked')).map(c => c.value);
  const body = {
    name: $('#roleName').value.trim(),
    description: $('#roleDesc').value.trim(),
    permissions: perms,
  };
  if (!body.name) { toast('Введи название', 'error'); return; }
  const url = id ? `/admin-api/roles/${id}` : '/admin-api/roles';
  const method = id ? 'PUT' : 'POST';
  const r = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (r.ok) { toast('Сохранено', 'success'); closeModal('roleModal'); renderRolesPage(); }
  else { const e = await r.json().catch(() => ({})); toast('Ошибка: ' + (e.error || r.status), 'error'); }
}

// ---- Модалка админа ----

function openAdminModal(existing) {
  const isEdit = !!existing;
  $('#adminModalTitle').textContent = isEdit ? 'Редактировать админа' : 'Новый админ';
  $('#adminUserId').value = existing?.user_id || '';
  $('#adminUserId').readOnly = !!isEdit;
  $('#adminFullName').value = existing?.full_name || '';
  $('#adminUsername').value = existing?.username || '';
  $('#adminActive').checked = existing ? !!existing.is_active : true;

  const sel = $('#adminRole');
  sel.innerHTML = '<option value="">— без роли —</option>' +
    state.roles.map(r => `<option value="${r.id}">${esc(r.name)}</option>`).join('');
  sel.value = existing?.role_id || '';

  const tripleSet = {
    added: new Set(existing?.added_permissions || []),
    removed: new Set(existing?.removed_permissions || []),
  };
  $('#adminPermsHost').innerHTML = buildPermissionsUI(tripleSet, true);
  openModal('adminModal');
}

async function saveAdmin() {
  const uid = parseInt($('#adminUserId').value || '0', 10);
  if (!uid) { toast('Введи Telegram ID', 'error'); return; }
  const added = Array.from($('#adminPermsHost').querySelectorAll('input[data-add]:checked')).map(c => c.dataset.add);
  const removed = Array.from($('#adminPermsHost').querySelectorAll('input[data-rem]:checked')).map(c => c.dataset.rem);
  const body = {
    user_id: uid,
    full_name: $('#adminFullName').value.trim(),
    username: $('#adminUsername').value.trim(),
    is_active: $('#adminActive').checked,
    role_id: parseInt($('#adminRole').value || '0', 10) || null,
    added_permissions: added,
    removed_permissions: removed,
  };
  const r = await fetch('/admin-api/admin-users', {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
  });
  if (r.ok) { toast('Сохранено', 'success'); closeModal('adminModal'); renderRolesPage(); }
  else { const e = await r.json().catch(() => ({})); toast('Ошибка: ' + (e.error || r.status), 'error'); }
}





/* ===================================================== */
/* === FINANCE v2 — sources & funding ================== */
/* ===================================================== */

async function loadFinanceSources() {
  try {
    const r = await fetch('/admin-api/finance/sources', { credentials: 'include' });
    if (!r.ok) return [];
    state.finSources = await r.json();
    return state.finSources;
  } catch(e) { return []; }
}

async function renderFinancePage() {
  const host = $('#page-finance');
  if (!host) return;
  if (!hasPermission('view_finance')) {
    host.innerHTML = '<div class="empty"><span class="emoji">⛔</span><div class="title">Нет доступа</div></div>';
    return;
  }
  // загружаем всё параллельно
  let summary={}, expenses=[], investments=[], planned=[], sources=[], breakdown={};
  try {
    const [s,e,i,p,src,br] = await Promise.all([
      fetch('/admin-api/finance/summary',     {credentials:'include'}).then(r=>r.json()),
      fetch('/admin-api/finance/expenses',    {credentials:'include'}).then(r=>r.json()),
      fetch('/admin-api/finance/investments', {credentials:'include'}).then(r=>r.json()),
      fetch('/admin-api/finance/planned',     {credentials:'include'}).then(r=>r.json()),
      fetch('/admin-api/finance/sources',     {credentials:'include'}).then(r=>r.json()),
      fetch('/admin-api/finance/breakdown',   {credentials:'include'}).then(r=>r.json()),
    ]);
    summary = s.summary || s || {};
    expenses = Array.isArray(e) ? e : (e.expenses || []);
    investments = Array.isArray(i) ? i : (i.investments || []);
    planned = Array.isArray(p) ? p : (p.planned || []);
    sources = Array.isArray(src) ? src : [];
    breakdown = br || {};
  } catch (err) {
    host.innerHTML = '<div class="empty"><div class="title">Ошибка загрузки</div><div class="sub">' + esc(String(err)) + '</div></div>';
    return;
  }
  state.finance = { summary, expenses, investments, planned };
  state.finSources = sources;
  state.finBreakdown = breakdown;

  const canEdit = hasPermission('edit_finance');
  const income = +(summary.total_income || 0);
  const totalExp = +(summary.total_expenses || 0);
  const totalInv = +(summary.total_invested || 0);
  const net = income - totalExp;

  // расходы по категориям
  const expByCat = {};
  expenses.forEach(e => { expByCat[e.category] = (expByCat[e.category] || 0) + (+e.amount || 0); });

  host.innerHTML = `
    <div class="page-title">Финансы</div>
    <div class="page-sub">Доходы, расходы, вложения и плановые покупки</div>

    <div class="kpi-grid">
      <div class="kpi">
        <div class="kpi-head"><span class="kpi-label">Доходы</span></div>
        <div class="kpi-value num">${money(income)}</div>
        <div class="kpi-foot"><span class="kpi-delta up">от продаж подписок</span></div>
      </div>
      <div class="kpi">
        <div class="kpi-head"><span class="kpi-label">Расходы</span></div>
        <div class="kpi-value num" style="color:var(--red)">${money(totalExp)}</div>
        <div class="kpi-foot"><span class="kpi-delta dn">все траты</span></div>
      </div>
      <div class="kpi">
        <div class="kpi-head"><span class="kpi-label">Вложено личных</span></div>
        <div class="kpi-value num" style="color:var(--accent)">${money(totalInv)}</div>
      </div>
      <div class="kpi">
        <div class="kpi-head"><span class="kpi-label">Чистый результат</span></div>
        <div class="kpi-value num" style="color:${net>=0?'var(--green)':'var(--red)'}">${net>=0?'+':'−'}${money(Math.abs(net))}</div>
      </div>
    </div>

    <div class="toolbar">
      ${canEdit ? `
        <button class="btn btn-primary btn-sm" id="finAddExpenseBtn">+ Расход</button>
        <button class="btn btn-ghost btn-sm" id="finAddInvBtn">+ Вложение</button>
        <button class="btn btn-ghost btn-sm" id="finAddPlanBtn">+ Плановый</button>
        <span class="toolbar-grow"></span>
        <button class="btn btn-ghost btn-sm" id="finManageSrcBtn">⚙ Источники</button>
      ` : ''}
    </div>

    <!-- Финансовая раскладка -->
    <div class="card" style="margin-top:14px">
      <div class="card-head"><div class="card-title">Финансовая раскладка</div><div class="card-sub">${money(breakdown.total_balance || 0)} — общий остаток</div></div>
      <div class="tbl-wrap">
        <table class="tbl fin-breakdown-tbl">
          <colgroup>
            <col style="width:45%">
            <col style="width:18%">
            <col style="width:18%">
            <col style="width:19%">
          </colgroup>
          <thead><tr>
            <th>Источник</th>
            <th class="text-r">Внесено</th>
            <th class="text-r">Потрачено</th>
            <th class="text-r">Остаток</th>
          </tr></thead>
          <tbody>
            ${(breakdown.sources || []).map(row => {
              const s = row.source || {};
              const balCol = row.balance >= 0 ? 'var(--green)' : 'var(--red)';
              return `<tr>
                <td><b>${esc(s.name)}</b> ${s.kind === 'service_pool' ? '<span class="muted" style="font-size:11px">(пул сервиса)</span>' : ''}</td>
                <td class="text-r"><span class="num">${money(row.contributed)}</span></td>
                <td class="text-r"><span class="num" style="color:var(--red)">${money(row.spent)}</span></td>
                <td class="text-r"><b class="num" style="color:${balCol}">${money(row.balance)}</b></td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>

    <div class="fin-grid" style="margin-top:14px">
      <div class="card">
        <div class="card-head"><div class="card-title">Расходы по категориям</div></div>
        <div class="fin-bars">
          ${Object.entries(EXPENSE_CATEGORIES).map(([cat,meta]) => {
            const amt = expByCat[cat] || 0;
            const total = totalExp || 1;
            const pct = Math.round(amt/total*100);
            return `<div class="fin-bar-row">
              <div class="fin-bar-label-wrap">
                <span class="fin-bar-ico">${meta.label.split(' ')[0]}</span>
                <span class="fin-bar-name">${meta.label.split(' ').slice(1).join(' ')}</span>
                <span class="fin-bar-pct">${pct}%</span>
              </div>
              <div class="fin-bar-track"><div class="fin-bar-fill" style="width:${pct}%;background:${meta.color}"></div></div>
              <div class="fin-bar-amount"><b>${money(amt)}</b></div>
            </div>`;
          }).join('')}
        </div>
      </div>
      <div class="card">
        <div class="card-head"><div class="card-title">История вложений</div></div>
        ${investments.length ? investments.map(inv => `
          <div class="fin-investor">
            <span class="fin-investor-name">${esc(inv.investor_name || '?')} <span class="muted" style="font-size:11px">${esc((inv.invested_at||'').slice(0,10))}</span>${inv.note ? ' <span class="muted" style="font-size:11px">· ' + esc(inv.note) + '</span>' : ''}</span>
            <span class="fin-investor-amount">${money(inv.amount)}</span>
            ${canEdit ? `<button class="btn btn-ghost btn-sm fin-inv-del" data-iid="${inv.id}" style="margin-left:8px" title="Удалить вложение">🗑</button>` : ''}
          </div>
        `).join('') : '<div class="empty"><div class="title">Нет вложений</div></div>'}
      </div>
    </div>

    <div class="card" style="margin-top:14px">
      <div class="card-head">
        <div class="card-title">История расходов</div>
        <div class="seg" id="finExpFilter">
          <button class="seg-btn active" data-cat="all">Все</button>
          ${Object.entries(EXPENSE_CATEGORIES).map(([cat,meta]) =>
            `<button class="seg-btn" data-cat="${cat}">${meta.label}</button>`
          ).join('')}
        </div>
      </div>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr><th>Дата</th><th>Категория</th><th>Описание</th><th>Источники</th><th class="text-r">Сумма</th>${canEdit ? '<th></th>' : ''}</tr></thead>
          <tbody id="finExpensesTbody"></tbody>
        </table>
      </div>
    </div>

    <div class="card" style="margin-top:14px">
      <div class="card-head"><div class="card-title">Плановые покупки</div></div>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr><th>Готово</th><th>Дата</th><th>Категория</th><th>Что</th><th class="text-r">Оценка</th>${canEdit ? '<th></th>' : ''}</tr></thead>
          <tbody id="finPlannedTbody"></tbody>
        </table>
      </div>
    </div>
  `;

  renderFinExpensesTable('all');
  renderFinPlannedTable();

  if (canEdit) {
    $('#finAddExpenseBtn').addEventListener('click', () => openExpenseModal());
    $('#finAddInvBtn').addEventListener('click', () => openInvestmentModal());
    $('#finAddPlanBtn').addEventListener('click', () => openPlannedModal());
    $('#finManageSrcBtn').addEventListener('click', openSourcesModal);
  }
    // удаление вложения
  $$('.fin-inv-del').forEach(b => b.addEventListener('click', async () => {
    if (!await showConfirm({ title: 'Удалить вложение', message: 'Удалить это вложение?', okText: 'Удалить', danger: true })) return;
    const r = await fetch('/admin-api/finance/investments/' + b.dataset.iid, {
      method: 'DELETE', credentials: 'include'
    });
    if (r.ok) { toast('Удалено', 'success'); renderFinancePage(); }
    else { const e = await r.json().catch(()=>({})); toast('Ошибка: ' + (e.error || r.status), 'error'); }
  }));
  $$('#finExpFilter .seg-btn').forEach(b => b.addEventListener('click', () => {
    $$('#finExpFilter .seg-btn').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    renderFinExpensesTable(b.dataset.cat);
  }));
}

// ---- Модалка расхода с funding[] ----

function openExpenseModal(existing) {
  $('#finExpenseModalTitle').textContent = existing ? 'Редактировать расход' : 'Добавить расход';
  $('#finExpenseId').value = existing?.id || '';
  $('#finExpenseDate').value = existing?.expense_date || new Date().toISOString().slice(0,10);
  $('#finExpenseCategory').value = existing?.category || 'servers';
  $('#finExpenseDesc').value = existing?.description || '';
  $('#finExpenseAmount').value = existing?.amount || '';
  $('#finExpenseRecurring').checked = !!existing?.is_recurring;
  $('#finExpensePeriod').value = existing?.recurring_period || 'monthly';

  // строим строки источников (по одной строке на каждый активный)
  const existingFunding = existing?.funding || [];
  const fundMap = new Map();
  for (const f of existingFunding) fundMap.set(f.source_id, +f.amount || 0);

  const sources = (state.finSources || []).filter(s => s.is_active);
  $('#finExpenseFunding').innerHTML = sources.map(s => `
    <div class="fund-row" data-sid="${s.id}">
      <label class="fund-label">${esc(s.name)}</label>
      <input type="number" step="0.01" min="0" class="input fund-amount" data-sid="${s.id}" value="${fundMap.get(s.id) || ''}" placeholder="0">
      <span class="muted">₽</span>
    </div>
  `).join('');
  // live-валидация
  $$('#finExpenseFunding .fund-amount').forEach(inp => inp.addEventListener('input', updateExpenseFundingTotal));
  $('#finExpenseAmount').addEventListener('input', updateExpenseFundingTotal);
  updateExpenseFundingTotal();

  openModal('finExpenseModal');
}

function updateExpenseFundingTotal() {
  const total = +($('#finExpenseAmount').value || 0);
  let sum = 0;
  $$('#finExpenseFunding .fund-amount').forEach(i => { sum += +(i.value || 0); });
  const diff = total - sum;
  const el = $('#finExpenseFundingTotal');
  if (!el) return;
  if (Math.abs(diff) < 0.005) {
    el.innerHTML = `<span style="color:var(--green)">✓ ${money(sum)} / ${money(total)}</span>`;
  } else if (sum === 0) {
    el.innerHTML = `<span class="muted">Сумма по источникам: ${money(0)} / ${money(total)}</span>`;
  } else {
    el.innerHTML = `<span style="color:var(--red)">⚠ Сумма по источникам: ${money(sum)} / ${money(total)} (разница ${money(diff)})</span>`;
  }
}

async function saveExpense() {
  const id = $('#finExpenseId').value;
  const amount = parseFloat($('#finExpenseAmount').value || '0');
  const desc = $('#finExpenseDesc').value.trim();
  if (!desc || amount <= 0) { toast('Заполни описание и сумму', 'error'); return; }

  const funding = [];
  $$('#finExpenseFunding .fund-amount').forEach(inp => {
    const v = parseFloat(inp.value || '0');
    if (v > 0) funding.push({ source_id: +inp.dataset.sid, amount: v });
  });
  // проверка суммы
  const sumFunding = funding.reduce((a,b)=>a+b.amount,0);
  if (Math.abs(sumFunding - amount) > 0.005 && funding.length) {
    if (!await showConfirm({ title: 'Несовпадение сумм', message: `Суммы по источникам (${money(sumFunding)}) не совпадают с общей суммой расхода (${money(amount)}). Сохранить как есть?`, okText: 'Сохранить' })) return;
  }

  const body = {
    expense_date: $('#finExpenseDate').value,
    category: $('#finExpenseCategory').value,
    description: desc,
    amount: amount,
    is_recurring: $('#finExpenseRecurring').checked,
    recurring_period: $('#finExpensePeriod').value,
    funding: funding,
  };
  const url = id ? `/admin-api/finance/expenses/${id}` : '/admin-api/finance/expenses';
  const method = id ? 'PUT' : 'POST';
  const r = await fetch(url, { method, credentials:'include', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
  if (r.ok) { toast(id ? 'Обновлено' : 'Добавлено', 'success'); closeModal('finExpenseModal'); renderFinancePage(); }
  else { const e = await r.json().catch(()=>({})); toast('Ошибка: ' + (e.error || r.status), 'error'); }
}

// ---- Модалка вложения с dropdown ----

function openInvestmentModal() {
  // dropdown по источникам person
  const sel = $('#finInvSourceId');
  const persons = (state.finSources || []).filter(s => s.kind === 'person' && s.is_active);
  sel.innerHTML = persons.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('');
  $('#finInvAmount').value = '';
  $('#finInvDate').value = new Date().toISOString().slice(0,10);
  $('#finInvNote').value = '';
  openModal('finInvestmentModal');
}

async function saveInvestment() {
  const source_id = parseInt($('#finInvSourceId').value || '0', 10);
  const amount = parseFloat($('#finInvAmount').value || '0');
  if (!source_id || amount <= 0) { toast('Выбери участника и сумму', 'error'); return; }
  const body = {
    source_id, amount,
    invested_at: $('#finInvDate').value,
    note: $('#finInvNote').value.trim(),
  };
  const r = await fetch('/admin-api/finance/investments', {
    method: 'POST', credentials:'include',
    headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)
  });
  if (r.ok) { toast('Вложение добавлено', 'success'); closeModal('finInvestmentModal'); renderFinancePage(); }
  else { const e = await r.json().catch(()=>({})); toast('Ошибка: ' + (e.error || r.status), 'error'); }
}

// ---- Модалка источников ----

function openSourcesModal() {
  renderSourcesList();
  $('#finSrcNewName').value = '';
  $('#finSrcNewCode').value = '';
  $('#finSrcNewTgId').value = '';
  openModal('finSourcesModal');
}

function renderSourcesList() {
  const host = $('#finSourcesList');
  const list = state.finSources || [];
  host.innerHTML = list.map(s => `
    <div class="adm-item ${s.is_active ? '' : 'adm-item-off'}">
      <div class="adm-item-main">
        <div class="adm-item-name">${esc(s.name)}</div>
        <div class="adm-item-sub">
          <span class="mono">${esc(s.code)}</span> · 
          ${s.kind === 'person' ? 'участник' : '🏦 пул сервиса'}
          ${s.tg_id ? '· <span class="mono">' + s.tg_id + '</span>' : ''}
        </div>
      </div>
      <div class="adm-item-acts">
        ${s.kind === 'person' ? `<button class="btn btn-ghost btn-sm" data-sid="${s.id}" data-act="toggle">${s.is_active ? '🚫' : '✓'}</button>` : ''}
      </div>
    </div>
  `).join('');
  $$('#finSourcesList [data-act="toggle"]').forEach(b => b.addEventListener('click', async () => {
    const s = state.finSources.find(x => x.id == b.dataset.sid);
    const r = await fetch(`/admin-api/finance/sources/${b.dataset.sid}`, {
      method:'PUT', credentials:'include',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({ is_active: !s.is_active })
    });
    if (r.ok) {
      await loadFinanceSources();
      renderSourcesList();
      toast('Обновлено', 'success');
    } else toast('Ошибка', 'error');
  }));
}

async function addFinSource() {
  const name = $('#finSrcNewName').value.trim();
  const code = $('#finSrcNewCode').value.trim().toLowerCase();
  const tgId = parseInt($('#finSrcNewTgId').value || '0', 10) || null;
  if (!name || !code) { toast('Заполни имя и код', 'error'); return; }
  const r = await fetch('/admin-api/finance/sources', {
    method:'POST', credentials:'include',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ name, code, kind: 'person', tg_id: tgId })
  });
  if (r.ok) {
    await loadFinanceSources();
    renderSourcesList();
    $('#finSrcNewName').value = '';
    $('#finSrcNewCode').value = '';
    $('#finSrcNewTgId').value = '';
    toast('Источник добавлен', 'success');
  } else { const e = await r.json().catch(()=>({})); toast('Ошибка: ' + (e.error || r.status), 'error'); }
}

// hook: кнопки save в новых модалках
(function() {
  document.addEventListener('click', (e) => {
    const id = e.target?.id;
    if (id === 'finSrcAddBtn') addFinSource();
  });
})();

// рендер таблицы расходов с колонкой Источники
function renderFinExpensesTable(catFilter) {
  const tbody = $('#finExpensesTbody');
  if (!tbody) return;
  const canEdit = hasPermission('edit_finance');
  let list = (state.finance.expenses || []).slice();
  if (catFilter && catFilter !== 'all') list = list.filter(e => e.category === catFilter);
  list.sort((a,b) => (b.expense_date || '').localeCompare(a.expense_date || ''));
  if (!list.length) {
    tbody.innerHTML = `<tr><td colspan="${canEdit ? 6 : 5}"><div class="empty"><div class="title">Нет расходов</div></div></td></tr>`;
    return;
  }
  tbody.innerHTML = list.map(e => {
    const cat = EXPENSE_CATEGORIES[e.category] || { label: e.category, color: '#888' };
    const funding = e.funding || [];
    const fundStr = funding.length
      ? funding.map(f => `<span class="tag tag-blue">${esc(f.source_name)}: ${money(f.amount)}</span>`).join(' ')
      : '<span class="muted" style="font-size:11px">—</span>';
    const ico = (cat.label || '').split(' ')[0];
    const name = (cat.label || e.category || '').split(' ').slice(1).join(' ') || e.category;
    return `<tr>
      <td><span class="mono" style="font-size:12px;color:var(--fg-3)">${esc(e.expense_date || '')}</span></td>
      <td>
        <span style="display:inline-flex;align-items:center;gap:5px;padding:2px 8px 2px 4px;border-radius:6px;background:${cat.color}18;border:1px solid ${cat.color}30">
          <span style="font-size:13px">${ico}</span>
          <span style="font-size:12px;color:${cat.color};font-weight:500">${esc(name)}</span>
        </span>
      </td>
      <td style="max-width:220px;"><span style="font-size:13px">${esc(e.description || '')}</span></td>
      <td>${fundStr}</td>
      <td class="text-r"><span class="num" style="color:var(--red);font-weight:700">${money(e.amount)}</span></td>
      ${canEdit ? `<td class="text-r" style="white-space:nowrap">
        <button class="btn btn-ghost btn-sm" data-act="ed" data-id="${e.id}" title="Редактировать">✎</button>
        <button class="btn btn-ghost btn-sm" data-act="del" data-id="${e.id}" title="Удалить">🗑</button>
      </td>` : ''}
    </tr>`;
  }).join('');
  $$('#finExpensesTbody [data-act="ed"]').forEach(b => b.addEventListener('click', () =>
    openExpenseModal(state.finance.expenses.find(x => x.id == b.dataset.id))));
  $$('#finExpensesTbody [data-act="del"]').forEach(b => b.addEventListener('click', () =>
    confirmDeleteExpense(Number(b.dataset.id))));
}


/* hook: enable/disable селектов grantModal */
(function() {
  document.addEventListener('change', (e) => {
    if (e.target?.id === 'grantDevicesEnable') {
      const sel = document.getElementById('grantDevices');
      if (sel) sel.disabled = !e.target.checked;
    }
    if (e.target?.id === 'grantDaysEnable') {
      const sel = document.getElementById('grantDays');
      if (sel) sel.disabled = !e.target.checked;
    }
  });
})();

