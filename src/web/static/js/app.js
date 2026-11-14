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
    container.scrollTop = container.scrollHeight;
    return div;
}

function handleSubmit(e) {
    e.preventDefault();
    const input = document.getElementById('chat-input');
    const msg = input.value.trim();
    if (!msg) return;
    input.value = '';
    sendMessage(msg);
}

async function sendMessage(message) {
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

    // Stream AI response
    const msgDiv = addMessage('', 'ai');

    try {
        const resp = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message }),
        });

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
                try {
                    const data = JSON.parse(line.slice(6));
                    if (data.token) {
                        msgDiv.textContent += data.token;
                    }
                    if (data.error) {
                        msgDiv.textContent = 'Ошибка: ' + data.error;
                        msgDiv.className = 'message message-error';
                    }
                } catch {}
            }
        }

        if (!msgDiv.textContent) {
            msgDiv.textContent = 'Не удалось получить ответ от AI.';
            msgDiv.className = 'message message-error';
        }
    } catch (err) {
        msgDiv.textContent = 'Ошибка подключения: ' + err.message;
        msgDiv.className = 'message message-error';
    }

    document.getElementById('chat-messages').scrollTop =
        document.getElementById('chat-messages').scrollHeight;
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

async function renderScan() {
    const result = await API.post('/api/scan');
    if (result.status === 'ok') showScan(result);
}

async function runProblems() {
    try {
        const result = await API.post('/api/problems');
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
                    <button class="btn btn-sm btn-primary" data-fix="${escapeHtml(p.id)}" ${blocked ? 'disabled' : ''}>
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
    } catch (err) {
        hideLoading();
        addMessage('Ошибка: ' + err.message, 'error');
    }
}

function closeRepair() {
    document.getElementById('repair-modal').classList.remove('active');
}

async function refreshAfterChange() {
    const status = await API.get('/api/status');
    if (status.has_scan) {
        if (status.demo) await renderScan();
        await runProblems();
    }
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
    } catch (err) {
        hideLoading();
        addMessage('Ошибка: ' + err.message, 'error');
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
    try {
        const status = await API.get('/api/status');
        const badge = document.getElementById('ai-badge');
        if (badge && status.ai_available) {
            badge.textContent = `AI: ${status.ai_model}`;
            badge.style.borderColor = 'var(--green)';
        } else if (badge) {
            badge.textContent = 'AI: отключён';
        }
    } catch {}
});
