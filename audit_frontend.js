/* ═══════════════════════════════════════════════════════════════════
   AUDIT v2 — диагностика + починка + управление устройствами
   WATCHLIST — VIP-мониторинг, авто-проверка каждые 5 мин
   ═══════════════════════════════════════════════════════════════════ */

const _wl = {
  list: [],
  results: [],
  lastTs: null,
  timer: null,
  polling: false,
};

/* ── helpers ──────────────────────────────────────────────────────── */
function _auditScoreBadge(score) {
  if (score === 'ok')    return '<span class="tag tag-green">✓ OK</span>';
  if (score === 'warn')  return '<span class="tag tag-yellow">⚠ Внимание</span>';
  if (score === 'error') return '<span class="tag tag-red">✕ Проблема</span>';
  return '<span class="tag">?</span>';
}

function _auditServerRow(chk, uid) {
  const needFix = chk.error || !chk.found || chk.enabled === false || (chk.expire_diff_hours && chk.expire_diff_hours > 168);
  const fixBtn = needFix
    ? `<button class="btn btn-primary btn-sm aud-fix-btn"
         data-uid="${uid}" data-srvid="${chk.server_id}"
         title="Включить/добавить клиента на этом сервере" style="margin-left:auto">
         🔧 Починить
       </button>`
    : '';

  if (chk.error) {
    return `<div class="aud-srv-row aud-srv-error">
      <span class="aud-srv-name">${esc(chk.server_name)}</span>
      <span class="tag tag-red">Ошибка панели</span>
      <span class="aud-srv-detail" style="flex:1">${esc(chk.error.slice(0,80))}</span>
      ${fixBtn}
    </div>`;
  }
  if (!chk.found) {
    return `<div class="aud-srv-row aud-srv-error">
      <span class="aud-srv-name">${esc(chk.server_name)}</span>
      <span class="tag tag-red">Клиент не найден</span>
      <span style="flex:1"></span>
      ${fixBtn}
    </div>`;
  }
  const enBadge = chk.enabled === false
    ? '<span class="tag tag-red">Отключён</span>'
    : '<span class="tag tag-green">Активен</span>';
  const expColor = (() => {
    if (!chk.expiry_ms || chk.expiry_ms === 0) return '';
    const daysLeft = Math.floor((chk.expiry_ms - Date.now()) / 86400000);
    return daysLeft < 3 ? 'color:var(--red)' : '';
  })();
  return `<div class="aud-srv-row ${chk.enabled === false ? 'aud-srv-error' : 'aud-srv-ok'}">
    <span class="aud-srv-name">${esc(chk.server_name)}</span>
    ${enBadge}
    <span class="aud-srv-detail" style="flex:1;${expColor}">${chk.expiry_human ? esc(chk.expiry_human) : '—'} · ${chk.response_ms}ms</span>
    ${fixBtn}
  </div>`;
}

function _auditSubUrlRow(sc) {
  if (!sc) return '<span class="muted">—</span>';
  if (sc.error) return `<span class="tag tag-red">${esc(sc.error.slice(0,80))}</span>`;
  if (sc.note && sc.note.includes('Лимит устройств')) {
    return `<span class="tag tag-green">✓ Сервер доступен · ${sc.response_ms}ms</span>
            <span class="muted" style="font-size:11px;margin-left:8px">Лимит устройств достигнут — это норма (2/2)</span>`;
  }
  if (sc.valid_json) {
    return `<span class="tag tag-green">✓ ${sc.response_ms}ms${sc.note ? ' · ' + esc(sc.note) : ''}</span>`;
  }
  return `<span class="tag tag-yellow">${sc.status_code ? 'HTTP ' + sc.status_code : '?'} · ${sc.response_ms}ms${sc.note ? ' · ' + esc(sc.note) : ''}</span>`;
}

function _deviceRow(d, uid) {
  const icon = d.device_type === 'ios' ? '🍏' : d.device_type === 'android' ? '🤖' : '💻';
  return `<div class="aud-dev-row" data-devid="${d.id}">
    <span class="aud-dev-ico">${icon}</span>
    <div style="flex:1;min-width:0">
      <div style="font-size:12px;font-weight:600">${esc(d.device_name || d.device_type || '?')}</div>
      <div style="font-size:11px;color:var(--fg-3)">${esc(d.ip_address || '?')} · ${fmtDateTime(d.last_seen)}</div>
    </div>
    <span class="tag ${d.is_active ? 'tag-green' : 'tag-red'}" style="font-size:10px;margin-right:6px">${d.is_active ? 'active' : 'off'}</span>
    ${d.is_active ? `<button class="btn btn-ghost btn-sm aud-dev-del"
       data-uid="${uid}" data-devid="${d.id}" data-devname="${esc(d.device_name || String(d.id))}"
       title="Удалить устройство из подписки" style="color:var(--fg-3);padding:3px 6px">✕</button>` : ''}
  </div>`;
}

/* ════════════════════════════════════════════════════════════════════
   СТРАНИЦА АУДИТА
   ════════════════════════════════════════════════════════════════════ */
function renderAudit() {
  const host = $('#page-audit');
  if (!host) return;
  host.innerHTML = `
    <div class="page-header">
      <div>
        <div class="page-title">🔍 Диагностика пользователя</div>
        <div class="page-sub">Полная проверка: БД · все серверы · устройства — точные данные в реальном времени</div>
      </div>
    </div>
    <div class="card" style="max-width:560px;margin-bottom:20px">
      <div class="card-body" style="padding:18px">
        <div class="field" style="margin-bottom:12px">
          <label class="label">Пользователь</label>
          <input id="auditUidInput" class="input mono" placeholder="Telegram ID или @username" list="auditUserList" style="width:100%">
          <datalist id="auditUserList">
            ${(state.users || []).slice(0, 200).map(u =>
              `<option value="${u.user_id}">${esc(displayName(u))} · ${u.user_id}</option>`
            ).join('')}
          </datalist>
        </div>
        <button class="btn btn-primary" id="auditRunBtn" style="width:100%">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.35-4.35"/></svg>
          Запустить диагностику
        </button>
      </div>
    </div>
    <div id="auditResult"></div>
  `;
  $('#auditRunBtn').addEventListener('click', runAudit);
  $('#auditUidInput').addEventListener('keydown', e => { if (e.key === 'Enter') runAudit(); });
}

async function runAudit() {
  const raw = ($('#auditUidInput') || {}).value || '';
  const trimmed = raw.trim().replace(/^@/, '');
  let uid = null;
  const byId = parseInt(trimmed, 10);
  if (!isNaN(byId) && byId > 0) {
    uid = byId;
  } else if (trimmed) {
    const found = (state.users || []).find(u =>
      u.username && u.username.toLowerCase() === trimmed.toLowerCase()
    );
    if (found) uid = found.user_id;
  }
  if (!uid) { toast('Введите Telegram ID пользователя', 'error'); return; }

  const btn = $('#auditRunBtn');
  const resultEl = $('#auditResult');
  if (!resultEl) return;
  btn.disabled = true;
  btn.textContent = '⏳ Проверяем…';
  resultEl.innerHTML = `<div class="aud-loading"><div class="spinner" style="width:22px;height:22px;border:2px solid var(--bg-3);border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite;display:inline-block;margin-right:10px"></div>Подключаемся к серверам…</div>`;

  try {
    const resp = await proxy(`/admin-api/user_audit/${uid}`);
    if (!resp.success) throw new Error(resp.error || 'unknown');
    renderAuditReport(resp.report, resultEl);
  } catch (e) {
    resultEl.innerHTML = `<div class="card" style="border-color:var(--red)"><div class="card-body" style="padding:18px;color:var(--red)">Ошибка: ${esc(e.message)}</div></div>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.35-4.35"/></svg> Запустить диагностику';
  }
}

function renderAuditReport(r, host) {
  const u = r.user || {};
  const sub = r.active_sub;
  const issues = r.issues || [];
  const srvOk   = (r.server_checks || []).filter(c => c.found && c.enabled !== false && !c.error).length;
  const srvTotal = (r.server_checks || []).length;
  const scoreColor = r.score === 'ok' ? 'var(--green,#50c878)' : r.score === 'warn' ? '#f5a623' : 'var(--red)';

  let daysLeft = null;
  if (sub && sub.expires_at) {
    try { daysLeft = Math.floor((new Date(sub.expires_at) - Date.now()) / 86400000); } catch(_) {}
  }

  host.innerHTML = `
    <!-- Статус-бар -->
    <div style="background:${scoreColor}18;border:1px solid ${scoreColor}44;border-radius:10px;padding:14px 18px;margin-bottom:18px;display:flex;align-items:center;gap:14px">
      <span style="font-size:28px">${r.score==='ok'?'✅':r.score==='warn'?'⚠️':'❌'}</span>
      <div style="flex:1">
        <div style="font-weight:700;font-size:15px">${esc(displayName(u)||String(r.uid))} · ID ${r.uid}</div>
        <div style="font-size:13px;color:var(--fg-2);margin-top:2px">
          Диагностика: ${new Date(r.ts).toLocaleString('ru-RU')}
          · ${issues.length===0?'<span style="color:var(--green,#50c878)">Проблем не обнаружено</span>':`<span style="color:${scoreColor}">${issues.length} проблем</span>`}
        </div>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn btn-success btn-sm" id="auditGrantBtn">📅 Выдать/продлить</button>
        <button class="btn btn-ghost btn-sm" id="auditRefreshBtn">↻ Перепроверить</button>
      </div>
    </div>

    ${issues.length ? `
    <div class="card" style="border-color:${scoreColor}55;margin-bottom:16px">
      <div class="card-head"><div class="card-title">⚠ Проблемы (${issues.length})</div></div>
      <div class="card-body" style="padding:12px 16px">
        ${issues.map(i => `<div class="aud-issue">• ${esc(i)}</div>`).join('')}
      </div>
    </div>` : ''}

    <div class="fin-grid" style="margin-bottom:16px">
      <!-- Пользователь -->
      <div class="card">
        <div class="card-head"><div class="card-title">👤 Пользователь</div></div>
        <div class="card-body" style="padding:12px 16px">
          <div class="info"><span class="info-k">TG ID</span><span class="info-v mono">${r.uid}</span></div>
          <div class="info"><span class="info-k">Username</span><span class="info-v">${u.username?'@'+esc(u.username):'—'}</span></div>
          <div class="info"><span class="info-k">Имя</span><span class="info-v">${esc([u.first_name,u.last_name].filter(Boolean).join(' ')||'—')}</span></div>
          <div class="info"><span class="info-k">Регистрация</span><span class="info-v">${fmtDateTime(u.created_at)}</span></div>
          <div class="info"><span class="info-k">Бонусных дней</span><span class="info-v num">${u.bonus_days||0}</span></div>
          <div class="info"><span class="info-k">client_uuid</span><span class="info-v mono" style="font-size:10px">${u.client_uuid?esc(u.client_uuid):'—'}</span></div>
          <div class="info"><span class="info-k">Кампания</span><span class="info-v">${u.campaign_code?esc(u.campaign_code):'—'}</span></div>
          <div class="info"><span class="info-k">Рефералов привёл</span><span class="info-v num">${r.referred_count}</span></div>
          ${r.referrer?`<div class="info"><span class="info-k">Кто пригласил</span><span class="info-v">${esc((r.referrer.first_name||'')+(r.referrer.last_name?' '+r.referrer.last_name:''))} (${r.referrer.user_id})</span></div>`:''}
        </div>
      </div>
      <!-- Подписка -->
      <div class="card">
        <div class="card-head"><div class="card-title">📋 Активная подписка</div></div>
        <div class="card-body" style="padding:12px 16px">
          ${sub ? `
            <div class="info"><span class="info-k">Статус</span><span class="info-v"><span class="tag tag-green">active</span></span></div>
            <div class="info"><span class="info-k">Лимит устройств</span><span class="info-v num">${sub.devices}</span></div>
            <div class="info"><span class="info-k">Устройств зарег.</span><span class="info-v num">${(r.devices||[]).filter(d=>d.is_active).length} / ${sub.devices}</span></div>
            <div class="info"><span class="info-k">Начало</span><span class="info-v">${fmtDateTime(sub.started_at)}</span></div>
            <div class="info"><span class="info-k">Истекает</span><span class="info-v" style="${daysLeft!==null&&daysLeft<3?'color:var(--red)':''}">${fmtDateTime(sub.expires_at)} <span class="muted">(${daysLeft} дн)</span></span></div>
            <div class="info"><span class="info-k">UUID</span><span class="info-v mono" style="font-size:10px">${esc((sub.sub_url||'').split('/sub/')[1]||'—')}</span></div>
            <div class="info"><span class="info-k">sub_url</span><span class="info-v mono" style="font-size:10px;word-break:break-all">${esc(sub.sub_url||'—')}</span></div>
          ` : '<div class="empty" style="padding:18px 0;text-align:center"><div style="font-size:13px;color:var(--fg-3)">Нет активной подписки</div></div>'}
        </div>
      </div>
    </div>

    <!-- Серверы -->
    <div class="card" style="margin-bottom:16px">
      <div class="card-head">
        <div class="card-title">🖥 Статус на серверах</div>
        <div style="font-size:12px;color:var(--fg-3)">${srvOk}/${srvTotal} OK</div>
      </div>
      <div class="card-body" style="padding:12px 16px" id="auditSrvList">
        ${r.server_checks.length===0
          ? '<div class="muted" style="text-align:center;padding:12px">Нет активных серверов или UUID не определён</div>'
          : r.server_checks.map(c => _auditServerRow(c, r.uid)).join('')}
      </div>
    </div>

    <!-- sub_url -->
    <div class="card" style="margin-bottom:16px">
      <div class="card-head"><div class="card-title">🔗 Проверка ссылки подписки</div></div>
      <div class="card-body" style="padding:12px 16px">
        ${_auditSubUrlRow(r.sub_url_check)}
        ${r.sub_url_check&&r.sub_url_check.url?`<div class="info" style="margin-top:8px"><span class="info-k">URL</span><span class="info-v mono" style="font-size:10px;word-break:break-all">${esc(r.sub_url_check.url)}</span></div>`:''}
      </div>
    </div>

    <div class="fin-grid" style="margin-bottom:16px">
      <!-- Устройства -->
      <div class="card">
        <div class="card-head">
          <div class="card-title">📱 Зарегистрированные устройства (${r.devices.length})</div>
          ${sub?`<div style="font-size:11px;color:var(--fg-3)">${(r.devices||[]).filter(d=>d.is_active).length}/${sub.devices} слотов занято</div>`:''}
        </div>
        <div class="card-body" style="padding:12px 16px" id="auditDevList">
          ${r.devices.length===0
            ? '<div class="muted" style="text-align:center;padding:8px">Нет устройств</div>'
            : [...r.devices].sort((a,b)=>(b.is_active?1:0)-(a.is_active?1:0)).slice(0,10).map(d => _deviceRow(d, r.uid)).join('')}
        </div>
        ${r.devices.length===0&&sub?`<div class="card-body" style="padding:0 16px 12px;font-size:12px;color:var(--fg-3)">Устройства регистрируются при первом обращении к sub_url</div>`:''}
      </div>
      <!-- Платежи -->
      <div class="card">
        <div class="card-head"><div class="card-title">💳 Платежи (${r.payments.length})</div></div>
        <div class="card-body" style="padding:12px 16px">
          ${r.payments.length===0
            ? '<div class="muted" style="text-align:center;padding:8px">Нет платежей</div>'
            : r.payments.slice(0,8).map(p=>`
              <div class="lst-row" style="padding:6px 0">
                <div class="lst-ico ${p.status==='succeeded'?'green':p.status==='pending'?'yellow':'red'}">${p.status==='succeeded'?'✓':'✕'}</div>
                <div class="lst-main">
                  <div class="lst-title" style="font-size:12px">${money(p.amount)} · ${p.months||'?'} мес / ${p.devices||'?'} уст</div>
                  <div class="lst-sub">${fmtDateTime(p.created_at)}</div>
                </div>
                <span class="tag tag-${p.status==='succeeded'?'green':'red'}" style="font-size:10px">${esc(p.status)}</span>
              </div>`).join('')}
        </div>
      </div>
    </div>

    ${r.subscriptions.length>1?`
    <div class="card" style="margin-bottom:16px">
      <div class="card-head"><div class="card-title">🗂 История подписок (${r.subscriptions.length})</div></div>
      <div class="card-body" style="padding:12px 16px">
        ${r.subscriptions.map(s=>`
          <div class="lst-row" style="padding:5px 0">
            <div class="lst-ico ${s.status==='active'?'green':'red'}">${s.status==='active'?'✓':'✕'}</div>
            <div class="lst-main">
              <div style="font-size:12px">${s.devices} уст · до ${fmtDate(s.expires_at)}</div>
              <div class="lst-sub" style="font-size:10px;word-break:break-all">${esc((s.sub_url||'').split('/sub/')[1]||'—')}</div>
            </div>
            <span class="tag tag-${s.status==='active'?'green':'red'}" style="font-size:10px">${esc(s.status)}</span>
          </div>`).join('')}
      </div>
    </div>` : ''}
  `;

  // Кнопки статус-бара
  const grantBtn = host.querySelector('#auditGrantBtn');
  if (grantBtn) grantBtn.addEventListener('click', () => quickGrant(String(r.uid)));
  const refreshBtn = host.querySelector('#auditRefreshBtn');
  if (refreshBtn) refreshBtn.addEventListener('click', () => {
    const inp = $('#auditUidInput');
    if (inp) inp.value = String(r.uid);
    runAudit();
  });

  // Кнопки 🔧 Починить
  host.querySelectorAll('.aud-fix-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const uid = btn.dataset.uid;
      const srvId = btn.dataset.srvid;
      btn.disabled = true; btn.textContent = '⏳';
      try {
        const resp = await proxy(`/admin-api/user_fix/${uid}/${srvId}`, { method: 'POST' });
        if (resp.success) {
          toast(resp.message || 'Готово', 'success');
          btn.textContent = '✓ Починено';
          btn.className = btn.className.replace('btn-primary', 'btn-success');
          // Перепроверяем через 2 секунды
          setTimeout(() => {
            const inp = $('#auditUidInput');
            if (inp) inp.value = uid;
            runAudit();
          }, 2000);
        } else {
          toast(resp.error || 'Ошибка', 'error');
          btn.disabled = false; btn.textContent = '🔧 Починить';
        }
      } catch(e) {
        toast('Ошибка: ' + e.message, 'error');
        btn.disabled = false; btn.textContent = '🔧 Починить';
      }
    });
  });

  // Кнопки ✕ Удалить устройство
  host.querySelectorAll('.aud-dev-del').forEach(btn => {
    btn.addEventListener('click', async () => {
      const uid = btn.dataset.uid;
      const devId = btn.dataset.devid;
      const devName = btn.dataset.devname;
      if (!confirm(`Удалить устройство «${devName}» из подписки пользователя?\nПользователь сможет добавить его снова при следующем подключении.`)) return;
      btn.disabled = true; btn.textContent = '⏳';
      try {
        const resp = await proxy(`/admin-api/user_devices/${uid}/${devId}`, { method: 'DELETE' });
        if (resp.success) {
          toast('Устройство удалено', 'success');
          // Убираем строку из DOM
          const row = btn.closest('[data-devid]');
          if (row) row.remove();
          // Перепроверяем через 1.5 сек
          setTimeout(() => {
            const inp = $('#auditUidInput');
            if (inp) inp.value = uid;
            runAudit();
          }, 1500);
        } else {
          toast(resp.error || 'Ошибка', 'error');
          btn.disabled = false; btn.textContent = '✕';
        }
      } catch(e) {
        toast('Ошибка: ' + e.message, 'error');
        btn.disabled = false; btn.textContent = '✕';
      }
    });
  });
}

/* ════════════════════════════════════════════════════════════════════
   WATCHLIST
   ════════════════════════════════════════════════════════════════════ */
async function renderWatchlist() {
  const host = $('#page-watchlist');
  if (!host) return;
  host.innerHTML = `
    <div class="page-header">
      <div>
        <div class="page-title">⭐ VIP-мониторинг</div>
        <div class="page-sub">Автоматическая проверка важных пользователей каждые 5 минут</div>
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        <span class="live-dot" id="wlLastTs">${_wl.lastTs?'обновлено '+new Date(_wl.lastTs).toLocaleTimeString('ru-RU'):'—'}</span>
        <button class="btn btn-ghost btn-sm" id="wlRefreshBtn">↻ Обновить сейчас</button>
        <button class="btn btn-primary btn-sm" id="wlAddBtn">+ Добавить</button>
      </div>
    </div>
    <div id="wlAddBlock" style="display:none;margin-bottom:16px">
      <div class="card" style="max-width:480px">
        <div class="card-body" style="padding:16px">
          <div class="field" style="margin-bottom:10px">
            <label class="label">Telegram ID</label>
            <input id="wlUidInput" class="input mono" placeholder="784871620" list="wlUserList">
            <datalist id="wlUserList">
              ${(state.users||[]).slice(0,200).map(u=>`<option value="${u.user_id}">${esc(displayName(u))} · ${u.user_id}</option>`).join('')}
            </datalist>
          </div>
          <div style="display:flex;gap:8px">
            <button class="btn btn-success btn-sm" id="wlAddConfirmBtn">Добавить</button>
            <button class="btn btn-ghost btn-sm" id="wlAddCancelBtn">Отмена</button>
          </div>
        </div>
      </div>
    </div>
    <div id="wlContent"><div class="loading-indicator"><div class="spinner"></div><span>Загрузка…</span></div></div>
  `;
  $('#wlAddBtn').addEventListener('click', () => { const b=$('#wlAddBlock'); b.style.display=b.style.display==='none'?'':'none'; });
  $('#wlAddCancelBtn').addEventListener('click', () => { $('#wlAddBlock').style.display='none'; });
  $('#wlAddConfirmBtn').addEventListener('click', wlAddUser);
  $('#wlRefreshBtn').addEventListener('click', () => loadWatchlistAudit(true));
  await loadWatchlistItems();
  // Если есть свежий кэш (< 4 мин) — показываем немедленно без нового аудита
  const _cacheAge = _wl.lastTs ? (Date.now() - new Date(_wl.lastTs).getTime()) : Infinity;
  if (_wl.results.length > 0 && _cacheAge < 4 * 60 * 1000) {
    renderWatchlistContent();
  } else if (_wl.list.length === 0) {
    renderWatchlistContent();
  } else {
    renderWatchlistContent(); // показываем скелет с пустыми карточками
    loadWatchlistAudit(false); // фоновый запрос без блокировки UI
  }
  wlStartAutoRefresh();
}

async function loadWatchlistItems() {
  try {
    const resp = await proxy('/admin-api/watchlist');
    _wl.list = resp.watchlist || [];
  } catch(e) { _wl.list = []; }
}

async function loadWatchlistAudit(showSpinner) {
  if (_wl.polling) return;
  _wl.polling = true;
  const btn = $('#wlRefreshBtn');
  if (btn) { btn.disabled=true; btn.textContent='⏳'; }
  try {
    const resp = await proxy('/admin-api/watchlist_batch_audit');
    if (resp.success) {
      _wl.results = resp.results || [];
      _wl.lastTs = resp.ts;
      const tsEl = $('#wlLastTs');
      if (tsEl) tsEl.textContent = 'обновлено ' + new Date(_wl.lastTs).toLocaleTimeString('ru-RU');
      renderWatchlistContent();
    }
  } catch(e) { console.warn('batch_audit error:', e); }
  finally {
    _wl.polling = false;
    if (btn) { btn.disabled=false; btn.textContent='↻ Обновить сейчас'; }
  }
}

function renderWatchlistContent() {
  const host = $('#wlContent');
  if (!host) return;
  if (_wl.list.length === 0) {
    host.innerHTML = `<div class="empty" style="padding:40px 0;text-align:center">
      <div style="font-size:32px;margin-bottom:12px">⭐</div>
      <div class="title" style="font-size:14px">Список пуст</div>
      <div class="sub" style="font-size:12px">Добавьте важных пользователей через кнопку «+ Добавить»</div>
    </div>`;
    return;
  }
  const counts = { ok:0, warn:0, error:0 };
  _wl.results.forEach(r => { counts[r.score] = (counts[r.score]||0)+1; });
  host.innerHTML = `
    <div class="kpi-grid" style="margin-bottom:16px">
      <div class="kpi"><div class="kpi-head"><span class="kpi-label">Всего</span></div><div class="kpi-value num">${_wl.list.length}</div></div>
      <div class="kpi"><div class="kpi-head"><span class="kpi-label">✓ OK</span></div><div class="kpi-value num" style="color:var(--green,#50c878)">${counts.ok}</div></div>
      <div class="kpi"><div class="kpi-head"><span class="kpi-label">⚠ Внимание</span></div><div class="kpi-value num" style="color:#f5a623">${counts.warn}</div></div>
      <div class="kpi"><div class="kpi-head"><span class="kpi-label">✕ Проблема</span></div><div class="kpi-value num" style="color:var(--red)">${counts.error}</div></div>
    </div>
    <div class="wl-grid">
      ${_wl.list.map(item => {
        const res = _wl.results.find(r=>r.user_id===item.user_id);
        const u = (state.users||[]).find(x=>Number(x.user_id)===Number(item.user_id));
        const name = u ? displayName(u) : (item.label||String(item.user_id));
        return renderWatchlistCard(item, res, name, u);
      }).join('')}
    </div>
  `;
  $$('#wlContent [data-act="wl-remove"]').forEach(b => b.addEventListener('click', e=>{e.stopPropagation();wlRemoveUser(Number(b.dataset.uid));}));
  $$('#wlContent [data-act="wl-audit"]').forEach(b => b.addEventListener('click', e=>{
    e.stopPropagation();
    goPage('audit');
    setTimeout(()=>{ const inp=$('#auditUidInput'); if(inp){inp.value=b.dataset.uid;} runAudit(); },80);
  }));
  $$('#wlContent [data-act="wl-grant"]').forEach(b=>b.addEventListener('click',e=>{e.stopPropagation();quickGrant(b.dataset.uid);}));
}

function renderWatchlistCard(item, res, name, u) {
  const uid = item.user_id;
  const score = res?res.score:'unknown';
  const issues = res?res.issues:[];
  const sub = res?res.active_sub:null;
  const srvChecks = res?(res.server_checks||[]):[];
  const srvOk = srvChecks.filter(c=>c.found&&c.enabled!==false&&!c.error).length;
  const srvTotal = srvChecks.length;
  const subChk = res?res.sub_url_check:null;
  const borderColor = score==='ok'?'rgba(80,200,120,.35)':score==='warn'?'rgba(245,166,35,.35)':score==='error'?'rgba(220,80,80,.35)':'var(--border)';
  let daysLeft=null;
  if(sub&&sub.expires_at){try{daysLeft=Math.floor((new Date(sub.expires_at)-Date.now())/86400000);}catch(_){}}
  return `<div class="wl-card" style="border-color:${borderColor}">
    <div class="wl-card-head">
      <div class="u-cell">
        <div class="u-ava" style="width:32px;height:32px;font-size:13px;background:${avaColor(uid)}">${u?avaInitial(u):name[0].toUpperCase()}</div>
        <div>
          <div style="font-weight:700;font-size:13px">${esc(name)}</div>
          <div style="font-size:11px;color:var(--fg-3)">id ${uid}${u&&u.username?' · @'+esc(u.username):''}</div>
        </div>
      </div>
      <div style="display:flex;gap:4px;align-items:center">
        ${_auditScoreBadge(score)}
        <button class="btn btn-ghost btn-sm" data-act="wl-audit" data-uid="${uid}" title="Детальный аудит">🔍</button>
        <button class="btn btn-ghost btn-sm" data-act="wl-remove" data-uid="${uid}" title="Удалить" style="color:var(--fg-3)">✕</button>
      </div>
    </div>
    <div class="wl-card-body">
      <div class="wl-row"><span class="wl-k">Подписка</span><span class="wl-v">${sub?`<span class="tag tag-green">active</span> ${sub.devices} уст · ${daysLeft!==null?daysLeft+' дн':'?'}`:'<span class="tag tag-red">нет</span>'}</span></div>
      <div class="wl-row"><span class="wl-k">Серверы</span><span class="wl-v">${srvTotal===0?'<span class="muted">—</span>':srvOk===srvTotal?`<span class="tag tag-green">✓ ${srvOk}/${srvTotal}</span>`:`<span class="tag tag-red">✕ ${srvOk}/${srvTotal}</span>`}</span></div>
      <div class="wl-row"><span class="wl-k">sub_url</span><span class="wl-v">${subChk?(subChk.valid_json?`<span class="tag tag-green">✓ ${subChk.response_ms}ms</span>`:`<span class="tag tag-red">✕</span>`):'<span class="muted">—</span>'}</span></div>
      ${issues.length?`<div class="wl-issues">${issues.slice(0,3).map(i=>`<div class="aud-issue">• ${esc(i)}</div>`).join('')}${issues.length>3?`<div class="muted" style="font-size:11px">+${issues.length-3} ещё</div>`:''}</div>`:''}
    </div>
    <div class="wl-card-foot">
      ${res?`<span style="font-size:10px;color:var(--fg-3)">проверено ${new Date(res.ts).toLocaleTimeString('ru-RU')}</span>`:'<span style="font-size:10px;color:var(--fg-3)">ожидание…</span>'}
      <button class="btn btn-ghost btn-sm" data-act="wl-grant" data-uid="${uid}">📅 Продлить</button>
    </div>
  </div>`;
}

async function wlAddUser() {
  const raw=($('#wlUidInput')||{}).value||'';
  const uid=parseInt(raw.trim(),10);
  if(!uid||isNaN(uid)){toast('Введите Telegram ID','error');return;}
  const btn=$('#wlAddConfirmBtn');
  btn.disabled=true;btn.textContent='⏳';
  try {
    const resp=await proxy('/admin-api/watchlist',{method:'POST',body:JSON.stringify({user_id:uid})});
    if(resp.success){toast('Добавлен в watchlist','success');$('#wlAddBlock').style.display='none';$('#wlUidInput').value='';await loadWatchlistItems();await loadWatchlistAudit(false);}
    else toast(resp.error||'Ошибка','error');
  }catch(e){toast('Ошибка: '+e.message,'error');}
  finally{btn.disabled=false;btn.textContent='Добавить';}
}

async function wlRemoveUser(uid) {
  if(!confirm(`Удалить пользователя ${uid} из watchlist?`))return;
  try{
    const resp=await proxy(`/admin-api/watchlist/${uid}`,{method:'DELETE'});
    if(resp.success){toast('Удалён','success');_wl.list=_wl.list.filter(x=>x.user_id!==uid);_wl.results=_wl.results.filter(x=>x.user_id!==uid);renderWatchlistContent();}
    else toast(resp.error||'Ошибка','error');
  }catch(e){toast('Ошибка: '+e.message,'error');}
}

function wlStartAutoRefresh() {
  if(_wl.timer)clearInterval(_wl.timer);
  _wl.timer=setInterval(()=>{if(state.currentPage==='watchlist')loadWatchlistAudit(false);},5*60*1000);
}

/* ── регистрация страниц ─────────────────────────────────────────── */
(function() {
  PAGE_META['audit']     = { sec:'Инструменты', title:'Диагностика' };
  PAGE_META['watchlist'] = { sec:'Инструменты', title:'VIP-мониторинг' };
  const _orig = window.renderPage || (typeof renderPage !== 'undefined' ? renderPage : null);
  window.renderPage = function(page) {
    if(page==='audit')    { renderAudit();    return; }
    if(page==='watchlist'){ renderWatchlist(); return; }
    if(_orig) return _orig(page);
  };
})();

/* ── CSS ──────────────────────────────────────────────────────────── */
(function() {
  const style = document.createElement('style');
  style.textContent = `
    .aud-loading{display:flex;align-items:center;padding:32px;color:var(--fg-2);font-size:14px}
    .aud-issue{font-size:12px;color:var(--fg-2);padding:3px 0;border-bottom:1px solid var(--border)}
    .aud-issue:last-child{border-bottom:none}
    .aud-srv-row{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--border)}
    .aud-srv-row:last-child{border-bottom:none}
    .aud-srv-name{min-width:130px;font-size:13px;font-weight:600}
    .aud-srv-detail{font-size:11px;color:var(--fg-3)}
    .aud-dev-row{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--border)}
    .aud-dev-row:last-child{border-bottom:none}
    .aud-dev-ico{font-size:16px;width:20px;text-align:center}
    .wl-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}
    .wl-card{background:var(--bg-2);border:1px solid var(--border);border-radius:10px;overflow:hidden}
    .wl-card-head{padding:14px 16px 10px;display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--border)}
    .wl-card-head .u-cell{flex:1;min-width:0}
    .wl-card-body{padding:10px 16px}
    .wl-card-foot{padding:8px 16px;border-top:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;background:var(--bg-3)}
    .wl-row{display:flex;align-items:center;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border)}
    .wl-row:last-child{border-bottom:none}
    .wl-k{font-size:11px;color:var(--fg-3)}
    .wl-v{font-size:12px}
    .wl-issues{margin-top:8px;padding:6px 8px;background:rgba(220,80,80,.08);border-radius:6px}
    .wl-issues .aud-issue{border-bottom:none;padding:1px 0}
    .tag-yellow{background:rgba(245,166,35,.18);color:#f5a623;border:1px solid rgba(245,166,35,.35)}
  `;
  document.head.appendChild(style);
})();
