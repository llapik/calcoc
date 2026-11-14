/* AI PC Repair & Optimizer — Frontend Application */

const API = {
    async post(url, data = {}) {
        const resp = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        return resp.json();
    },
    async get(url) {
        const resp = await fetch(url);
        return resp.json();
    },
};

/* ============================================================
   Panel navigation
   ============================================================ */

function showPanel(name) {
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));

    const panel = document.getElementById('panel-' + name);
    const btn = document.getElementById('nav-' + name);
    if (panel) panel.classList.add('active');
    if (btn) btn.classList.add('active');
    if (name === 'history') loadJournal();
}

/* ============================================================
   Chat
   ============================================================ */

function addMessage(text, type = 'ai') {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'message message-' + type;
    div.textContent = text;
    container.appendChild(div);
    scrollChat();
    return div;
}

function scrollChat() {
    const container = document.getElementById('chat-messages');
    container.scrollTop = container.scrollHeight;
}

function handleSubmit(e) {
    e.preventDefault();
    const input = document.getElementById('chat-input');
    const msg = input.value.trim();
    if (!msg) return;
    input.value = '';
    sendMessage(msg);
}

/* --- Minimal, safe Markdown: everything is escaped first, then a few constructs are re-enabled --- */

function renderInline(text) {
    return escapeHtml(text)
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s).,!?:;]|$)/g, '$1<em>$2</em>');
}

function renderMarkdown(src) {
    const lines = src.replace(/\r/g, '').split('\n');
    const out = [];
    let list = null;      // 'ul' | 'ol'
    let table = null;     // array of rows
    let code = null;      // array of lines
    const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
    const closeTable = () => {
        if (!table) return;
        const [head, ...body] = table;
        const row = (cells, tag) => '<tr>' + cells.map(c => `<${tag}>${renderInline(c)}</${tag}>`).join('') + '</tr>';
        out.push('<table>' + row(head, 'th') + body.map(r => row(r, 'td')).join('') + '</table>');
        table = null;
    };

    for (const line of lines) {
        if (line.trim().startsWith('```')) {
            if (code) { out.push('<pre>' + escapeHtml(code.join('\n')) + '</pre>'); code = null; }
            else { closeList(); closeTable(); code = []; }
            continue;
        }
        if (code) { code.push(line); continue; }

        if (/^\s*\|.*\|\s*$/.test(line)) {
            closeList();
            const cells = line.trim().slice(1, -1).split('|').map(c => c.trim());
            if (cells.every(c => /^:?-{2,}:?$/.test(c))) continue;  // separator row
            (table = table || []).push(cells);
            continue;
        }
        closeTable();

        let m;
        if ((m = line.match(/^\s*(#{1,4})\s+(.*)$/))) {
            closeList();
            out.push(`<h4>${renderInline(m[2])}</h4>`);
        } else if ((m = line.match(/^\s*(?:[-*•]|(\d+)[.)])\s+(.*)$/))) {
            const kind = m[1] ? 'ol' : 'ul';
            if (list !== kind) { closeList(); out.push(`<${kind}>`); list = kind; }
            out.push(`<li>${renderInline(m[2])}</li>`);
        } else if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
            closeList();
            out.push('<hr>');
        } else if (line.trim() === '') {
            closeList();
        } else {
            closeList();
            out.push(`<p>${renderInline(line)}</p>`);
        }
    }
    if (code) out.push('<pre>' + escapeHtml(code.join('\n')) + '</pre>');
    closeList();
    closeTable();
    return out.join('');
}

const TOOL_LABELS = {
    scan_system: 'Диагностика системы',
    list_problems: 'Просмотр найденных проблем',
    get_component_details: 'Чтение данных компонента',
    propose_fix: 'Подготовка исправления',
    get_upgrade_advice: 'Подбор апгрейда',
    get_journal: 'Чтение журнала операций',
    propose_rollback: 'Подготовка отката',
    search_knowledge: 'Поиск в базе знаний',
};

function addProposalCard(event) {
    const card = document.createElement('div');
    card.className = 'message proposal-card';
    const isFix = event.type === 'fix_proposal';
    const risk = isFix
        ? `<span class="risk-badge risk-${event.risk_level}">${RISK_ICONS[event.risk_level] || ''} ${escapeHtml(event.risk_label)}</span>`
        : '';
    card.innerHTML = `
        <div class="proposal-head">${isFix ? '🛠️ Предлагаю исправить' : '↩ Предлагаю откатить'} ${risk}</div>
        <div class="title">${escapeHtml(event.title)}</div>
        ${isFix ? `<div class="desc">${escapeHtml(event.plan)}</div>` : ''}
        ${isFix && event.note ? `<div class="desc">${escapeHtml(event.note)}</div>` : ''}
        ${isFix && event.requires_backup ? '<div class="desc">Перед изменением будет создана резервная копия.</div>' : ''}
        <div class="actions">
            <button class="btn btn-sm btn-primary" data-accept>Выполнить</button>
            <button class="btn btn-sm" data-decline>Не сейчас</button>
        </div>`;
    const finish = (label) => { card.querySelector('.actions').innerHTML = `<span class="fix-note">${label}</span>`; };
    card.querySelector('[data-decline]').onclick = () => finish('Отклонено');
    card.querySelector('[data-accept]').onclick = async () => {
        finish('Выполняется…');
        const ok = isFix ? await executeRepair(event.problem_id) : await rollbackEntry(event.journal_id);
        finish(ok ? '✔ Выполнено' : '✖ Не выполнено — подробности ниже');
    };
    document.getElementById('chat-messages').appendChild(card);
    scrollChat();
}

let chatBusy = false;

async function sendMessage(message) {
    if (chatBusy) return;
    addMessage(message, 'user');

    // Handle special commands
    if (message === '/scan') {
        await runScan();
        return;
    }
    if (message === '/upgrade') {
        await runUpgrade();
        return;
    }

    chatBusy = true;
    const container = document.getElementById('chat-messages');
    const steps = document.createElement('div');   // what the agent is doing
    steps.className = 'agent-steps';
    container.appendChild(steps);
    let msgDiv = null;                              // created on the first token
    let text = '';
    const thinking = addMessage('Думаю…', 'thinking');

    const handle = (event) => {
        switch (event.type) {
        case 'token':
            if (!msgDiv) msgDiv = addMessage('', 'ai');
            text += event.text;
            msgDiv.innerHTML = renderMarkdown(text);
            break;
        case 'tool_start': {
            const step = document.createElement('div');
            step.className = 'agent-step running';
            step.dataset.id = event.id;
            step.textContent = TOOL_LABELS[event.name] || event.name;
            steps.appendChild(step);
            break;
        }
        case 'tool_end': {
            const step = [...steps.children].find(s => s.dataset.id === event.id);
            if (step) step.className = 'agent-step ' + (event.ok ? 'ok' : 'failed');
            // text after a tool call belongs to a new bubble, below the steps
            if (msgDiv && text.trim()) { msgDiv = null; text = ''; }
            break;
        }
        case 'fix_proposal':
        case 'rollback_proposal':
            addProposalCard(event);
            break;
        case 'state_changed':
            refreshPanels();
            break;
        case 'error':
            addMessage('Ошибка AI: ' + event.message, 'error');
            break;
        }
        scrollChat();
    };

    try {
        const resp = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message }),
        });
        if (!resp.ok) throw new Error((await resp.json()).message || resp.statusText);

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                let event;
                try { event = JSON.parse(line.slice(6)); } catch { continue; }
                handle(event);
            }
        }
    } catch (err) {
        addMessage('Ошибка подключения: ' + err.message, 'error');
    } finally {
        thinking.remove();
        if (!steps.children.length) steps.remove();
        chatBusy = false;
        scrollChat();
    }
}

async function refreshPanels() {
    try {
        if (!(await API.get('/api/status')).has_scan) return;
        const scan = await API.get('/api/scan');
        if (scan.status === 'ok') showScan(scan);
        await showProblems(await API.get('/api/problems'));
    } catch {}
}

/* ============================================================
   Diagnostics
   ============================================================ */

async function runScan() {
    showLoading('Выполняется диагностика системы...');
    try {
        const result = await API.post('/api/scan');
        hideLoading();

        if (result.status === 'ok') {
            showScan(result);

            // Also report in chat
            addMessage('Диагностика завершена. Переключитесь на вкладку "Диагностика" для просмотра результатов.', 'system');

            // Auto-run problems analysis
            await runProblems();
        } else {
            addMessage('Ошибка диагностики: ' + (result.message || 'Неизвестная ошибка'), 'error');
        }
    } catch (err) {
        hideLoading();
        addMessage('Ошибка: ' + err.message, 'error');
    }
}

const RISK_ICONS = { green: '🟢', yellow: '🟡', red: '🔴', black: '⚫' };

function showScan(result) {
    document.getElementById('diag-results').innerHTML = `
        <div class="result-card">
            <h3>Результат диагностики</h3>
            <pre>${escapeHtml(result.summary)}</pre>
        </div>
    `;
}

async function runProblems() {
    await showProblems(await API.post('/api/problems'));
}

async function showProblems(result) {
    try {
        if (result.status !== 'ok') return;

        const container = document.getElementById('problems-results');
        if (!result.problems || result.problems.length === 0) {
            container.innerHTML = '<p class="placeholder">Проблем не обнаружено!</p>';
            return;
        }

        let html = `<p style="margin-bottom:1rem">${escapeHtml(result.summary)}</p>`;
        for (const p of result.problems) {
            const fixed = p.status === 'fixed';
            let actions = '';
            if (fixed) {
                actions = `<div class="actions">
                    <button class="btn btn-sm" data-rollback="${p.journal_id}">↩ Откатить</button>
                </div>`;
            } else if (p.fix) {
                const f = p.fix;
                const blocked = f.availability === 'blocked' || f.availability === 'unavailable';
                actions = `<div class="actions">
                    <button class="btn btn-sm btn-primary" data-fix="${escapeHtml(p.key)}" ${blocked ? 'disabled' : ''}>
                        Исправить
                    </button>
                    <span class="risk-badge risk-${f.risk_level}">${RISK_ICONS[f.risk_level] || ''} ${escapeHtml(f.risk_label)}</span>
                    ${blocked ? `<span class="fix-note">${escapeHtml(f.note)}</span>` : ''}
                </div>`;
            }
            html += `
                <div class="problem-card ${fixed ? 'fixed' : p.severity}">
                    <div>
                        <span class="severity severity-${fixed ? 'fixed' : p.severity}">${fixed ? '✔ исправлено' : p.severity}</span>
                        <span class="title">${escapeHtml(p.title)}</span>
                    </div>
                    <div class="desc">${escapeHtml(p.description)}</div>
                    ${actions}
                </div>
            `;
        }
        container.innerHTML = html;
    } catch (err) {
        addMessage('Ошибка: ' + err.message, 'error');
    }
}

async function runUpgrade() {
    showLoading('Анализ конфигурации...');
    try {
        const result = await API.post('/api/upgrade');
        hideLoading();

        if (result.status === 'ok') {
            const container = document.getElementById('upgrade-results');
            container.innerHTML = `
                <div class="result-card">
                    <pre>${escapeHtml(result.text)}</pre>
                </div>
            `;
            showPanel('upgrade');
            addMessage('Рекомендации по апгрейду готовы. Переключитесь на вкладку "Апгрейд".', 'system');
        }
    } catch (err) {
        hideLoading();
        addMessage('Ошибка: ' + err.message, 'error');
    }
}

/* ============================================================
   Repair: plan → confirm → execute → journal
   ============================================================ */

async function fixProblem(problemId) {
    try {
        const { outcome, message } = await API.post('/api/repair', { problem_id: problemId, dry_run: true });
        if (!outcome) {
            addMessage('Ошибка: ' + (message || 'проблема не найдена'), 'error');
            return;
        }
        if (outcome.status !== 'done') {
            addMessage(outcome.message, 'error');
            showPanel('chat');
            return;
        }
        if (!outcome.requires_confirmation) {
            await executeRepair(problemId);
            return;
        }
        const risk = document.getElementById('repair-risk');
        risk.className = 'risk-badge risk-' + outcome.risk_level;
        risk.textContent = `${RISK_ICONS[outcome.risk_level] || ''} ${outcome.risk_label}`;
        document.getElementById('repair-plan').textContent = outcome.plan;
        document.getElementById('repair-note').textContent = outcome.message;
        document.getElementById('repair-step-backup').hidden = !outcome.requires_backup;
        document.getElementById('repair-confirm').onclick = async () => {
            closeRepair();
            await executeRepair(problemId);
        };
        document.getElementById('repair-modal').classList.add('active');
    } catch (err) {
        addMessage('Ошибка: ' + err.message, 'error');
    }
}

async function executeRepair(problemId) {
    showLoading('Выполняется исправление...');
    try {
        const { outcome } = await API.post('/api/repair', { problem_id: problemId, confirm: true });
        hideLoading();
        const ok = outcome.status === 'done';
        const suffix = ok && outcome.journal_id ? ` (запись журнала #${outcome.journal_id})` : '';
        addMessage(outcome.message + suffix, ok ? 'system' : 'error');
        await refreshAfterChange();
        return ok;
    } catch (err) {
        hideLoading();
        addMessage('Ошибка: ' + err.message, 'error');
        return false;
    }
}

function closeRepair() {
    document.getElementById('repair-modal').classList.remove('active');
}

async function refreshAfterChange() {
    await refreshPanels();
    await loadJournal();
}

/* ============================================================
   Journal
   ============================================================ */

const STATUS_LABELS = {
    completed: 'выполнено', rolled_back: 'отменено', failed: 'ошибка', purged: 'копия удалена', pending: 'ожидает',
};

async function loadJournal() {
    try {
        const result = await API.get('/api/journal');
        const container = document.getElementById('history-results');
        if (!result.entries || result.entries.length === 0) {
            container.innerHTML = '<p class="placeholder">Журнал операций пуст.</p>';
            return;
        }
        let html = '';
        for (const e of result.entries) {
            const when = new Date(e.timestamp * 1000).toLocaleString();
            html += `
                <div class="journal-entry status-${e.status}">
                    <div class="journal-main">
                        <span class="journal-id">#${e.id}</span>
                        <span class="title">${escapeHtml(e.description || e.action)}</span>
                        <span class="risk-badge risk-${e.risk_level}">${RISK_ICONS[e.risk_level] || ''}</span>
                        <span class="journal-status">${STATUS_LABELS[e.status] || e.status}</span>
                    </div>
                    <div class="desc">${escapeHtml(when)}${e.target ? ' · ' + escapeHtml(e.target) : ''}</div>
                    ${e.can_rollback ? `<div class="actions">
                        <button class="btn btn-sm" data-rollback="${e.id}">↩ Откатить</button>
                    </div>` : ''}
                </div>
            `;
        }
        container.innerHTML = html;
    } catch {}
}

async function rollbackEntry(entryId) {
    showLoading('Откат операции...');
    try {
        const result = await API.post(`/api/journal/${entryId}/rollback`);
        hideLoading();
        addMessage(result.message, result.status === 'ok' ? 'system' : 'error');
        await refreshAfterChange();
        return result.status === 'ok';
    } catch (err) {
        hideLoading();
        addMessage('Ошибка: ' + err.message, 'error');
        return false;
    }
}

async function purgeBackups() {
    if (!confirm('Удалить все резервные копии? Откат выполненных операций станет невозможен.')) return;
    const result = await API.post('/api/backups/purge');
    addMessage(result.message, 'system');
    await refreshAfterChange();
}

/* ============================================================
   Demo scenarios
   ============================================================ */

async function setDemo(scenarioId) {
    const result = await API.post('/api/demo', { scenario: scenarioId || null });
    if (result.status !== 'ok') {
        addMessage('Ошибка: ' + result.message, 'error');
        return;
    }
    document.getElementById('demo-badge').hidden = !result.active;
    for (const id of ['diag-results', 'problems-results', 'upgrade-results']) {
        document.getElementById(id).innerHTML = '<p class="placeholder">Сначала выполните диагностику.</p>';
    }
    if (result.active) {
        const title = document.getElementById('demo-select').selectedOptions[0].textContent;
        addMessage(`${title}. Все исправления выполняются в песочнице — реальная система не изменяется.`, 'system');
        await runScan();
        showPanel('problems');
    } else {
        addMessage('Демо-режим выключен: работаем с этим компьютером.', 'system');
    }
}

/* ============================================================
   Settings
   ============================================================ */

async function openSettings() {
    try {
        const current = await API.get('/api/settings');
        document.getElementById('setting-backend').value = current.ai_backend;
        document.getElementById('setting-expert').checked = current.expert_mode;
        document.getElementById('setting-model').value = current.openrouter_model;
        document.getElementById('setting-key').value = '';
        document.getElementById('setting-key').placeholder = current.openrouter_key_set
            ? 'Ключ сохранён — введите новый, чтобы заменить' : 'sk-or-v1-…';
    } catch {}
    document.getElementById('settings-modal').classList.add('active');
}

function closeSettings() {
    document.getElementById('settings-modal').classList.remove('active');
}

async function setLanguage(lang) {
    await API.post('/api/settings', { language: lang });
    location.reload();
}

async function updateSetting(key, value) {
    await API.post('/api/settings', { [key]: value });
    if (key === 'expert_mode') await refreshAfterChange();  // availability of risky fixes changed
    if (key === 'ai_backend') await updateAiBadge();
}

async function saveOpenRouter() {
    const payload = { ai_backend: 'openrouter' };
    const key = document.getElementById('setting-key').value.trim();
    const model = document.getElementById('setting-model').value.trim();
    if (key) payload.openrouter_api_key = key;
    if (model) payload.openrouter_model = model;
    const result = await API.post('/api/settings', payload);
    document.getElementById('setting-backend').value = 'openrouter';
    document.getElementById('setting-key').value = '';
    document.getElementById('setting-key-status').textContent = result.ai_backend_active === 'openrouter'
        ? '✔ Сохранено, AI-агент включён' : 'Ключ не задан — AI недоступен';
    await updateAiBadge();
}

async function updateAiBadge() {
    try {
        const status = await API.get('/api/status');
        const badge = document.getElementById('ai-badge');
        if (!badge) return;
        if (status.ai_available) {
            badge.textContent = `AI: ${status.ai_model}${status.ai_agent ? ' · агент' : ''}`;
            badge.style.borderColor = 'var(--green)';
        } else {
            badge.textContent = 'AI: отключён';
            badge.style.borderColor = '';
        }
    } catch {}
}

/* ============================================================
   Utilities
   ============================================================ */

function showLoading(text = 'Загрузка...') {
    document.getElementById('loading-text').textContent = text;
    document.getElementById('loading').style.display = 'flex';
}

function hideLoading() {
    document.getElementById('loading').style.display = 'none';
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/* ============================================================
   Init
   ============================================================ */

document.addEventListener('click', (e) => {
    const fix = e.target.closest('[data-fix]');
    if (fix) fixProblem(fix.dataset.fix);
    const rollback = e.target.closest('[data-rollback]');
    if (rollback) rollbackEntry(rollback.dataset.rollback);
});

document.addEventListener('DOMContentLoaded', async () => {
    await updateAiBadge();
    await refreshPanels();   // a scan may already exist (page reload, --demo)
});
