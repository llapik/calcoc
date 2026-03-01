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
            // Show in diagnostics panel
            const diagResults = document.getElementById('diag-results');
            diagResults.innerHTML = `
                <div class="result-card">
                    <h3>Результат диагностики</h3>
                    <pre>${escapeHtml(result.summary)}</pre>
                </div>
            `;

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
            html += `
                <div class="problem-card ${p.severity}">
                    <div>
                        <span class="severity severity-${p.severity}">${p.severity}</span>
                        <span class="title">${escapeHtml(p.title)}</span>
                    </div>
                    <div class="desc">${escapeHtml(p.description)}</div>
                    ${p.auto_fixable ? `
                    <div class="actions">
                        <button class="btn btn-sm" onclick="fixProblem('${p.id}', '${p.fix_action}')">
                            Исправить
                        </button>
                    </div>` : ''}
                </div>
            `;
        }
        container.innerHTML = html;
    } catch {}
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

async function fixProblem(problemId, action) {
    // Safety check first
    try {
        const check = await API.post('/api/safety/check', { action });
        if (!check.allowed) {
            addMessage('Действие заблокировано: ' + check.reason, 'error');
            return;
        }
        if (check.requires_confirmation) {
            const ok = confirm(
                `Уровень риска: ${check.label} (${check.risk_level})\n\n` +
                `${check.reason}\n\n` +
                `Продолжить?`
            );
            if (!ok) return;
        }

        addMessage(`Выполняется исправление ${problemId} (${action})...`, 'system');
        // Actual fix would be called here via repair API
        addMessage('Функция автоматического исправления находится в разработке.', 'system');
    } catch (err) {
        addMessage('Ошибка: ' + err.message, 'error');
    }
}

/* ============================================================
   Settings
   ============================================================ */

function openSettings() {
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
