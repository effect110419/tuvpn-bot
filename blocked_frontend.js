/* =====================================================================
   БЛОКИРОВКИ БОТА — тихая проверка доступности + полная очистка
   Раздел только для суперадмина. Проверка через chat action:
   пользователи НЕ получают сообщений и не узнают о проверке.
   ===================================================================== */

const _blk = {
  rows: [],          // недостижимые пользователи из /blocked/results
  summary: {},
  meta: {},
  selected: new Set(),
  polling: null,
};

const _BLK_STATUS = {
  blocked:     { label: '🚫 Заблокировал бота', cls: 'blk-tag-red' },
  deactivated: { label: '👻 Аккаунт удалён',    cls: 'blk-tag-gray' },
  no_chat:     { label: '❔ Чат не найден',      cls: 'blk-tag-gray' },
  ok:          { label: '✅ Доступен',           cls: 'blk-tag-green' },
  unknown:     { label: '⚠️ Не удалось проверить', cls: 'blk-tag-yellow' },
};

const _BLK_BLOCKERS = {
  active_sub:    '🟢 Активная подписка',
  recent_device: '📱 Устройство активно за 7 дней',
  watchlist:     '⭐ В VIP-watchlist',
  admin:         '🛡 Администратор',
  superadmin:    '👑 Суперадмин',
};

/* ── страница ─────────────────────────────────────────────────────── */
function renderBlocked() {
  const host = $('#page-blocked');
  if (!host) return;
  host.innerHTML = `
    <div class="page-header">
      <div>
        <div class="page-title">🚫 Заблокировавшие бота</div>
        <div class="page-sub">Тихая проверка через chat action — пользователи не получают сообщений и не видят проверку. Очистка удаляет пользователя полностью: со всех VPN-серверов и из всех таблиц БД.</div>
      </div>
    </div>

    <div class="card" style="max-width:640px;margin-bottom:16px">
      <div class="card-body" style="padding:18px">
        <div class="field" style="margin-bottom:12px">
          <label class="label">Кого проверить</label>
          <select id="blkAudience" class="input" style="width:100%">
            <option value="all">Все пользователи</option>
            <option value="inactive">Без активной подписки</option>
            <option value="active">С активной подпиской</option>
            <option value="single">Один пользователь (ID)</option>
            <option value="custom_list">Список ID</option>
          </select>
        </div>
        <div class="field" id="blkSingleWrap" style="display:none;margin-bottom:12px">
          <label class="label">Telegram ID</label>
          <input id="blkSingleUid" class="input mono" placeholder="784871620" style="width:100%">
        </div>
        <div class="field" id="blkListWrap" style="display:none;margin-bottom:12px">
          <label class="label">Список ID (через запятую или с новой строки)</label>
          <textarea id="blkListIds" class="input mono" rows="3" style="width:100%;resize:vertical"></textarea>
        </div>
        <button class="btn btn-primary" id="blkCheckBtn" style="width:100%">Запустить тихую проверку</button>
        <div id="blkCheckProgress" style="display:none;margin-top:12px">
          <div class="blk-progress"><div class="blk-progress-fill" id="blkProgressFill" style="width:0%"></div></div>
          <div class="blk-progress-txt" id="blkProgressTxt">0 / 0</div>
        </div>
      </div>
    </div>

    <div id="blkSummary"></div>
    <div id="blkResults"></div>
  `;
  $('#blkAudience').addEventListener('change', () => {
    const v = $('#blkAudience').value;
    $('#blkSingleWrap').style.display = v === 'single' ? '' : 'none';
    $('#blkListWrap').style.display = v === 'custom_list' ? '' : 'none';
  });
  $('#blkCheckBtn').addEventListener('click', blkStartCheck);
  blkLoadResults(); // показать результаты предыдущей проверки, если есть
}

/* ── запуск проверки ──────────────────────────────────────────────── */
async function blkStartCheck() {
  const audience = $('#blkAudience').value;
  const body = { audience };
  if (audience === 'single') {
    const uid = parseInt(($('#blkSingleUid').value || '').trim(), 10);
    if (!uid) { toast('Введите Telegram ID', 'error'); return; }
    body.target_user_id = uid;
  }
  if (audience === 'custom_list') {
    const ids = ($('#blkListIds').value || '').split(/[\s,;]+/).map(x => parseInt(x, 10)).filter(x => x > 0);
    if (!ids.length) { toast('Введите хотя бы один ID', 'error'); return; }
    body.target_user_ids = ids;
  }
  const btn = $('#blkCheckBtn');
  btn.disabled = true;
  btn.textContent = '⏳ Проверяем…';
  try {
    const resp = await proxy('/admin-api/blocked/check', { method: 'POST', body: JSON.stringify(body) });
    if (!resp.success) throw new Error(resp.error || 'unknown');
    $('#blkCheckProgress').style.display = '';
    await blkPollJob(resp.job_id, resp.total, () => {
      $('#blkCheckProgress').style.display = 'none';
      blkLoadResults();
      toast('Проверка завершена', 'success');
    });
  } catch (e) {
    toast('Ошибка: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Запустить тихую проверку';
  }
}

function blkPollJob(jobId, total, onDone) {
  return new Promise((resolve) => {
    if (_blk.polling) clearInterval(_blk.polling);
    _blk.polling = setInterval(async () => {
      try {
        const j = await proxy(`/admin-api/sync_status/${jobId}`);
        const prog = j.progress || 0;
        const tot = j.total || total || 1;
        const fill = $('#blkProgressFill');
        const txt = $('#blkProgressTxt');
        if (fill) fill.style.width = Math.round(prog / tot * 100) + '%';
        if (txt) txt.textContent = `${prog} / ${tot}`;
        if (j.status === 'done' || j.status === 'error' || j.status === 'not_found') {
          clearInterval(_blk.polling);
          _blk.polling = null;
          if (j.status === 'error') toast('Ошибка задачи: ' + (j.error || '?'), 'error');
          if (onDone) onDone(j);
          resolve(j);
        }
      } catch (e) { /* сеть мигнула — продолжаем поллить */ }
    }, 1500);
  });
}

/* ── результаты ───────────────────────────────────────────────────── */
async function blkLoadResults() {
  try {
    const resp = await proxy('/admin-api/blocked/results');
    if (!resp.success) throw new Error(resp.error || 'unknown');
    _blk.rows = resp.unreachable || [];
    _blk.summary = resp.summary || {};
    _blk.meta = resp.meta || {};
    _blk.selected = new Set(_blk.rows.filter(r => r.deletable).map(r => r.user_id));
    blkRenderSummary();
    blkRenderTable();
  } catch (e) {
    const el = $('#blkResults');
    if (el) el.innerHTML = `<div class="card" style="border-color:var(--red)"><div class="card-body" style="padding:16px;color:var(--red)">Ошибка загрузки: ${esc(e.message)}</div></div>`;
  }
}

function blkRenderSummary() {
  const el = $('#blkSummary');
  if (!el) return;
  const s = _blk.summary, m = _blk.meta;
  if (!m.checked_at && !Object.keys(s).length) {
    el.innerHTML = `<div class="card" style="margin-bottom:16px"><div class="card-body" style="padding:16px;color:var(--fg-3);font-size:13px">Проверка ещё не запускалась (результаты хранятся до перезапуска сервиса).</div></div>`;
    return;
  }
  const chip = (label, n, cls) => n ? `<span class="blk-chip ${cls || ''}">${label}: <b>${n}</b></span>` : '';
  el.innerHTML = `
    <div class="card" style="margin-bottom:16px"><div class="card-body" style="padding:14px 16px">
      <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center">
        ${chip('✅ Доступны', s.ok, 'blk-tag-green')}
        ${chip('🚫 Заблокировали', s.blocked, 'blk-tag-red')}
        ${chip('👻 Аккаунт удалён', s.deactivated, 'blk-tag-gray')}
        ${chip('❔ Чат не найден', s.no_chat, 'blk-tag-gray')}
        ${chip('⚠️ Не проверились', s.unknown, 'blk-tag-yellow')}
        <span style="margin-left:auto;font-size:11px;color:var(--fg-3)">
          проверено: ${m.total_checked || 0} · ${m.checked_at ? new Date(m.checked_at).toLocaleString('ru-RU') : '—'}
        </span>
      </div>
    </div></div>
  `;
}

function blkRenderTable() {
  const el = $('#blkResults');
  if (!el) return;
  const rows = _blk.rows;
  if (!rows.length) {
    el.innerHTML = _blk.meta.checked_at
      ? `<div class="card"><div class="card-body" style="padding:16px;color:var(--fg-2)">🎉 Недостижимых пользователей не найдено — чистить нечего.</div></div>`
      : '';
    return;
  }
  const fmtDate = (d) => d ? new Date(d).toLocaleDateString('ru-RU') : '—';
  el.innerHTML = `
    <div class="card">
      <div class="card-body" style="padding:0">
        <table class="tbl" style="width:100%">
          <thead><tr>
            <th style="width:32px"><input type="checkbox" id="blkSelAll"></th>
            <th>Пользователь</th>
            <th>Статус</th>
            <th>Оплачено</th>
            <th>Подписка</th>
            <th>Устройство</th>
            <th>Регистрация</th>
            <th>Ограничения</th>
          </tr></thead>
          <tbody>
            ${rows.map(r => {
              const st = _BLK_STATUS[r.status] || { label: r.status, cls: '' };
              const checked = _blk.selected.has(r.user_id) ? 'checked' : '';
              const blockers = (r.blockers || []).map(b => `<span class="blk-chip blk-tag-yellow">${esc(_BLK_BLOCKERS[b] || b)}</span>`).join(' ');
              return `<tr class="${r.deletable ? '' : 'blk-row-protected'}">
                <td>${r.deletable ? `<input type="checkbox" class="blk-sel" data-uid="${r.user_id}" ${checked}>` : ''}</td>
                <td>
                  <div style="font-weight:600;font-size:13px">${esc(r.name || '—')}</div>
                  <div class="mono" style="font-size:11px;color:var(--fg-3)">${r.user_id}${r.username ? ' · @' + esc(r.username) : ''}</div>
                </td>
                <td><span class="blk-chip ${st.cls}">${st.label}</span></td>
                <td>${r.paid_total ? `<b>${r.paid_total} ₽</b> 💰` : '<span style="color:var(--fg-3)">—</span>'}</td>
                <td>${r.sub_status === 'active' ? '🟢 активна' : (r.sub_status === 'expired' ? '⏳ истекла ' + fmtDate(r.sub_expires) : '—')}</td>
                <td>${r.last_device_seen ? fmtDate(r.last_device_seen) : '—'}</td>
                <td>${fmtDate(r.registered_at)}</td>
                <td>${blockers || '<span style="color:var(--green);font-size:11px">можно удалить</span>'}</td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>

    <div class="card" style="margin-top:14px;border-color:var(--red)">
      <div class="card-body" style="padding:16px">
        <div style="font-weight:700;margin-bottom:6px;color:var(--red)">Полная очистка</div>
        <div style="font-size:12px;color:var(--fg-2);margin-bottom:10px">
          Перед удалением каждый пользователь ещё раз проверяется вживую: если Telegram не подтвердит блокировку прямо в момент очистки — пользователь будет пропущен.
          Также автоматически пропускаются: активная подписка, активность устройств за 7 дней, админы, watchlist.
        </div>
        <label style="display:flex;align-items:center;gap:8px;font-size:12px;margin-bottom:12px;cursor:pointer">
          <input type="checkbox" id="blkDelPayments">
          Удалить и историю платежей (по умолчанию платежи сохраняются для финансовой отчётности)
        </label>
        <div style="display:flex;align-items:center;gap:12px">
          <button class="btn btn-danger" id="blkCleanupBtn">🗑 Полностью удалить выбранных (<span id="blkSelCount">0</span>)</button>
          <div id="blkCleanupProgress" style="display:none;flex:1">
            <div class="blk-progress"><div class="blk-progress-fill" id="blkCleanFill" style="width:0%"></div></div>
            <div class="blk-progress-txt" id="blkCleanTxt">0 / 0</div>
          </div>
        </div>
        <div id="blkCleanupReport" style="margin-top:12px"></div>
      </div>
    </div>
  `;
  const updCount = () => { const c = $('#blkSelCount'); if (c) c.textContent = _blk.selected.size; };
  updCount();
  $('#blkSelAll').addEventListener('change', (e) => {
    _blk.selected = e.target.checked ? new Set(rows.filter(r => r.deletable).map(r => r.user_id)) : new Set();
    $$('.blk-sel').forEach(cb => cb.checked = e.target.checked);
    updCount();
  });
  $$('.blk-sel').forEach(cb => cb.addEventListener('change', () => {
    const uid = parseInt(cb.dataset.uid, 10);
    if (cb.checked) _blk.selected.add(uid); else _blk.selected.delete(uid);
    updCount();
  }));
  $('#blkCleanupBtn').addEventListener('click', blkRunCleanup);
}

/* ── очистка ──────────────────────────────────────────────────────── */
async function blkRunCleanup() {
  const ids = [..._blk.selected];
  if (!ids.length) { toast('Никто не выбран', 'error'); return; }
  const delPay = $('#blkDelPayments').checked;
  const ok = await showConfirm({
    title: 'Полная очистка',
    message: `Полностью удалить ${ids.length} пользовател${ids.length === 1 ? 'я' : 'ей'} из всей системы?\n\n` +
      `Будут удалены: запись пользователя, подписки, устройства, тикеты, рефералы, клиенты на всех VPN-серверах` +
      (delPay ? ', ВКЛЮЧАЯ историю платежей' : ' (история платежей сохранится') + (delPay ? '.' : ').') +
      `\n\nКаждый будет перепроверен вживую перед удалением. Действие необратимо.`,
    okText: 'Удалить навсегда',
    danger: true,
  });
  if (!ok) return;
  const btn = $('#blkCleanupBtn');
  btn.disabled = true;
  try {
    const resp = await proxy('/admin-api/blocked/cleanup', {
      method: 'POST',
      body: JSON.stringify({ user_ids: ids, delete_payments: delPay }),
    });
    if (!resp.success) throw new Error(resp.error || 'unknown');
    $('#blkCleanupProgress').style.display = '';
    const poll = setInterval(async () => {
      try {
        const j = await proxy(`/admin-api/sync_status/${resp.job_id}`);
        const tot = j.total || ids.length;
        const fill = $('#blkCleanFill'), txt = $('#blkCleanTxt');
        if (fill) fill.style.width = Math.round((j.progress || 0) / tot * 100) + '%';
        if (txt) txt.textContent = `${j.progress || 0} / ${tot}`;
        if (j.status === 'done' || j.status === 'error') {
          clearInterval(poll);
          btn.disabled = false;
          $('#blkCleanupProgress').style.display = 'none';
          if (j.status === 'error') { toast('Ошибка: ' + (j.error || '?'), 'error'); return; }
          blkShowCleanupReport(j);
          toast(`Удалено: ${j.deleted_count || 0}, пропущено: ${j.skipped_count || 0}`, 'success');
          blkLoadResults(); // обновить таблицу — удалённые исчезнут
        }
      } catch (e) { /* продолжаем поллить */ }
    }, 1500);
  } catch (e) {
    btn.disabled = false;
    toast('Ошибка: ' + e.message, 'error');
  }
}

function blkShowCleanupReport(j) {
  const el = $('#blkCleanupReport');
  if (!el) return;
  const skipReason = (r) => (r.reasons || []).map(x => esc(_BLK_BLOCKERS[x] || x)).join(', ');
  el.innerHTML = `
    <div style="font-size:12px">
      <div style="margin-bottom:6px"><b>Отчёт:</b> удалено ${j.deleted_count || 0} · пропущено ${j.skipped_count || 0} · ошибок ${j.errors_count || 0}</div>
      ${(j.skipped || []).map(r => `<div class="blk-report-row">⏭ ${r.user_id} — ${skipReason(r)}</div>`).join('')}
      ${(j.errors || []).map(r => `<div class="blk-report-row" style="color:var(--red)">⚠ ${r.user_id} — ${esc((r.errors || []).join('; '))}</div>`).join('')}
      ${(j.deleted || []).map(r => `<div class="blk-report-row" style="color:var(--fg-3)">🗑 ${r.user_id} — удалён полностью</div>`).join('')}
    </div>
  `;
}

/* ── регистрация страницы ─────────────────────────────────────────── */
(function () {
  if (typeof PAGE_META !== 'undefined') {
    PAGE_META['blocked'] = { sec: 'Инструменты', title: 'Блокировки бота' };
  }
  const _orig = window.renderPage;
  window.renderPage = function (page) {
    if (page === 'blocked') { renderBlocked(); return; }
    if (_orig) return _orig(page);
  };
})();

/* ── CSS ──────────────────────────────────────────────────────────── */
(function () {
  const style = document.createElement('style');
  style.textContent = `
    .blk-chip{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;background:var(--bg-3);border:1px solid var(--border)}
    .blk-tag-red{background:rgba(220,80,80,.12);color:#e05c5c;border-color:rgba(220,80,80,.3)}
    .blk-tag-green{background:rgba(80,200,120,.12);color:#4fc07a;border-color:rgba(80,200,120,.3)}
    .blk-tag-gray{background:var(--bg-3);color:var(--fg-2)}
    .blk-tag-yellow{background:rgba(245,166,35,.14);color:#f5a623;border-color:rgba(245,166,35,.3)}
    .blk-row-protected{opacity:.55}
    .blk-progress{height:6px;background:var(--bg-3);border-radius:3px;overflow:hidden}
    .blk-progress-fill{height:100%;background:var(--accent);border-radius:3px;transition:width .4s}
    .blk-progress-txt{font-size:11px;color:var(--fg-3);margin-top:4px}
    .blk-report-row{padding:2px 0;border-bottom:1px solid var(--border);font-family:monospace;font-size:11px}
    .blk-report-row:last-child{border-bottom:none}
  `;
  document.head.appendChild(style);
})();
