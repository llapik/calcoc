/* AI PC Repair & Optimizer — Frontend Application (strings live in i18n.js) */

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

const RISK_ICONS = { green: '🟢', yellow: '🟡', red: '🔴', black: '⚫' };
const STATUS_ICONS = { good: '✔', warning: '⚠', serious: '▲', critical: '✖' };

function $(id) { return document.getElementById(id); }

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
}

function placeholder(key) { return `<p class="placeholder">${escapeHtml(T(key))}</p>`; }

function statusChip(status) {
    return `<span class="status-chip status-${status}">${STATUS_ICONS[status] || ''} ${escapeHtml(T('status.' + status))}</span>`;
}

/* ============================================================
   Panel navigation
   ============================================================ */

function showPanel(name) {
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    $('panel-' + name)?.classList.add('active');
    $('nav-' + name)?.classList.add('active');
    if (name === 'history') loadJournal();
}

/* ============================================================
   Chat
   ============================================================ */

function addMessage(text, type = 'ai') {
    const div = document.createElement('div');
    div.className = 'message message-' + type;
    div.textContent = text;
    $('chat-messages').appendChild(div);
    scrollChat();
    return div;
}

function scrollChat() {
    const container = $('chat-messages');
    container.scrollTop = container.scrollHeight;
}

function reportError(err) {
    addMessage(T('error.generic', { msg: err.message || err }), 'error');
}

function handleSubmit(e) {
    e.preventDefault();
    const input = $('chat-input');
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

function addProposalCard(event) {
    const card = document.createElement('div');
    card.className = 'message proposal-card';
    const isFix = event.type === 'fix_proposal';
    const risk = isFix
        ? `<span class="risk-badge risk-${event.risk_level}">${RISK_ICONS[event.risk_level] || ''} ${escapeHtml(event.risk_label)}</span>`
        : '';
    card.innerHTML = `
        <div class="proposal-head">${isFix ? '🛠️' : '↩'} ${escapeHtml(T(isFix ? 'card.fix' : 'card.rollback'))} ${risk}</div>
        <div class="title">${escapeHtml(event.title)}</div>
        ${isFix ? `<div class="desc">${escapeHtml(event.plan)}</div>` : ''}
        ${isFix && event.note ? `<div class="desc">${escapeHtml(event.note)}</div>` : ''}
        ${isFix && event.requires_backup ? `<div class="desc">${escapeHtml(T('card.backup'))}</div>` : ''}
        <div class="actions">
            <button class="btn btn-sm btn-primary" data-accept>${escapeHtml(T('action.run'))}</button>
            <button class="btn btn-sm" data-decline>${escapeHtml(T('action.not_now'))}</button>
        </div>`;
    const finish = (label) => { card.querySelector('.actions').innerHTML = `<span class="fix-note">${escapeHtml(label)}</span>`; };
    card.querySelector('[data-decline]').onclick = () => finish(T('card.declined'));
    card.querySelector('[data-accept]').onclick = async () => {
        finish(T('card.running'));
        const ok = isFix ? await executeRepair(event.problem_id) : await rollbackEntry(event.journal_id);
        finish(T(ok ? 'card.done' : 'card.failed'));
    };
    $('chat-messages').appendChild(card);
    scrollChat();
}

let chatBusy = false;

async function sendMessage(message) {
    if (chatBusy) return;
    showPanel('chat');
    addMessage(message, 'user');

    chatBusy = true;
    const steps = document.createElement('div');   // what the agent is doing
    steps.className = 'agent-steps';
    $('chat-messages').appendChild(steps);
    let msgDiv = null;                              // created on the first token
    let text = '';
    const thinking = addMessage(T('chat.thinking'), 'thinking');

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
            step.textContent = T('tool.' + event.name);
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
            addMessage(T('chat.error', { msg: event.message }), 'error');
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
        addMessage(T('chat.conn_error', { msg: err.message }), 'error');
    } finally {
        thinking.remove();
        if (!steps.children.length) steps.remove();
        chatBusy = false;
        scrollChat();
    }
}

/* ============================================================
   Diagnostics → panels
   ============================================================ */

async function runScan() {
    showLoading(T('loading.scan'));
    try {
        const result = await API.post('/api/scan');
        if (result.status !== 'ok') throw new Error(result.message);
        await API.post('/api/problems');
        await refreshPanels();
        hideLoading();
        addMessage(T('scan.done'), 'system');
        showPanel('health');
    } catch (err) {
        hideLoading();
        reportError(err);
    }
}

/* Redraw everything that depends on the last scan. Cheap: uses cached results on the server. */
async function refreshPanels() {
    try {
        if (!(await API.get('/api/status')).has_scan) return;
        const [health, problems, history] = await Promise.all([
            API.get('/api/health'), API.get('/api/problems'), API.get('/api/history'),
        ]);
        if (health.status === 'ok') renderHealth(health.health, history.status === 'ok' ? history.history : null);
        showProblems(problems);
    } catch (err) {
        console.warn('refresh failed', err);
    }
}

function clearPanels() {
    $('health-results').innerHTML = placeholder('health.empty');
    $('problems-results').innerHTML = placeholder('problems.empty');
    $('upgrade-results').innerHTML = placeholder('problems.empty');
    $('nav-health-dot').hidden = true;
    $('nav-problems-count').hidden = true;
}

/* ============================================================
   Health dashboard
   ============================================================ */

const COMPONENT_ICONS = {
    cpu: '🧠', memory: '🧮', disk: '💽', gpu: '🖥️', board: '🔌', os: '🪟', network: '🌐', security: '🛡️',
};

function renderMeter(m) {
    return `
        <div class="meter">
            <div class="meter-head"><span>${escapeHtml(m.label)}</span><span class="meter-value">${escapeHtml(m.text)}</span></div>
            <div class="meter-track status-${m.status}" role="meter" aria-valuemin="0" aria-valuemax="100"
                 aria-valuenow="${Math.round(m.percent)}" aria-label="${escapeHtml(m.label)}: ${escapeHtml(m.text)}">
                <div class="meter-fill" style="width:${Math.max(0, Math.min(100, m.percent))}%"></div>
            </div>
        </div>`;
}

function renderComponent(c) {
    const facts = c.facts.map(([k, v]) => `<div class="fact"><dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd></div>`).join('');
    // "info" findings are notes, not a state: neutral mark, never the green tick
    const problems = c.problems.map(p => p.severity === 'info'
        ? `<li class="status-neutral"><span class="pin">ℹ</span> ${escapeHtml(p.title)}</li>`
        : `<li class="status-${p.status}"><span class="pin">${STATUS_ICONS[p.status]}</span> ${escapeHtml(p.title)}</li>`).join('');
    let table = '';
    if (c.table) {
        const head = c.table.columns.map(h => `<th>${escapeHtml(h)}</th>`).join('');
        const rows = c.table.rows.map((r, i) => {
            const st = c.table.row_status[i];
            const cells = r.map(v => `<td>${escapeHtml(v)}</td>`).join('');
            return `<tr class="status-${st}"><td class="pin">${st === 'good' ? '' : STATUS_ICONS[st]}</td>${cells}</tr>`;
        }).join('');
        table = `<details class="smart"><summary>${escapeHtml(T('health.smart_table'))}</summary>
            <div class="table-scroll"><table><tr><th></th>${head}</tr>${rows}</table></div></details>`;
    }
    return `
        <section class="component-card status-${c.status}">
            <header>
                <span class="component-icon">${COMPONENT_ICONS[c.kind] || '•'}</span>
                <div class="component-title">
                    <span class="kind">${escapeHtml(c.title)}</span>
                    <span class="name" title="${escapeHtml(c.name)}">${escapeHtml(c.name)}</span>
                </div>
                ${statusChip(c.status)}
            </header>
            ${c.meters.map(renderMeter).join('')}
            ${facts ? `<dl class="facts">${facts}</dl>` : ''}
            ${problems ? `<ul class="component-problems">${problems}</ul>` : ''}
            ${table}
        </section>`;
}

function renderHealth(h, history) {
    const counts = [];
    if (h.counts.critical) counts.push(`<span class="status-chip status-critical">${STATUS_ICONS.critical} ${h.counts.critical} ${escapeHtml(T('health.count.critical'))}</span>`);
    if (h.counts.warning) counts.push(`<span class="status-chip status-warning">${STATUS_ICONS.warning} ${h.counts.warning} ${escapeHtml(T('health.count.warning'))}</span>`);
    if (h.counts.fixable) counts.push(`<span class="status-chip status-neutral">🛠️ ${h.counts.fixable} ${escapeHtml(T('health.count.fixable'))}</span>`);

    let html = `
        <section class="health-hero status-${h.status}">
            <div class="score" aria-label="${h.score} ${escapeHtml(T('health.score'))}">
                <span class="score-value">${h.score}</span><span class="score-max">${escapeHtml(T('health.score'))}</span>
            </div>
            <div class="hero-body">
                <div class="verdict">${STATUS_ICONS[h.status]} ${escapeHtml(h.verdict)}</div>
                <div class="hero-counts">${counts.join('')}</div>
                <div class="hero-actions">
                    <button class="btn btn-primary btn-sm" data-ask="chat.ask_health">💬 ${escapeHtml(T('action.ask_ai'))}</button>
                    ${h.counts.critical + h.counts.warning ? `<button class="btn btn-sm" onclick="showPanel('problems')">${escapeHtml(T('action.show_problems'))}</button>` : ''}
                </div>
            </div>
        </section>
        <h3 class="section-title">${escapeHtml(T('health.components'))}</h3>
        <div class="component-grid">${h.components.map(renderComponent).join('')}</div>`;

    html += `<h3 class="section-title">${escapeHtml(T('health.trends'))}
        ${history ? `<span class="section-note">${escapeHtml(T('health.points', { n: history.data_points }))}</span>` : ''}</h3>`;
    if (!history || !history.series.length) {
        html += placeholder('health.trends.few');
    } else {
        if (history.predictions.length) {
            html += `<div class="forecast"><div class="forecast-title">${escapeHtml(T('health.forecast'))}: ${escapeHtml(history.summary)}</div><ul>`
                + history.predictions.map(p => {
                    const st = { critical: 'critical', high: 'serious', medium: 'warning', low: 'good' }[p.risk] || 'good';
                    return `<li><span class="status-chip status-${st}">${STATUS_ICONS[st]} ${escapeHtml(T('risk.' + p.risk))}</span>
                        <span>${escapeHtml(p.description)}</span></li>`;
                }).join('') + '</ul></div>';
        }
        html += '<div class="chart-grid" id="chart-grid"></div>';
    }

    $('health-results').innerHTML = html;
    if (history && history.series.length) history.series.forEach(s => $('chart-grid').appendChild(buildChart(s)));

    const dot = $('nav-health-dot');
    dot.hidden = h.status === 'good';
    dot.className = 'nav-dot status-' + h.status;
}

/* --- Line chart: one series per chart (small multiples), crosshair + tooltip, table view --- */

const SVG_NS = 'http://www.w3.org/2000/svg';

function svgEl(tag, attrs = {}) {
    const el = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
}

function formatDate(ms, withYear = true) {
    return new Date(ms).toLocaleDateString(LANG, withYear
        ? { day: 'numeric', month: 'short', year: 'numeric' } : { day: 'numeric', month: 'short' });
}

function formatValue(v, unit) {
    const n = Number.isInteger(v) ? v.toLocaleString(LANG) : v.toLocaleString(LANG, { maximumFractionDigits: 1 });
    return unit ? `${n} ${unit}` : n;
}

/* Axis ticks on round numbers: 2-3 intervals with a step of 1, 2, 2.5 or 5 × 10^n. */
function niceTicks(min, max) {
    if (min === max) { min -= 1; max += 1; }
    const raw = (max - min) / 2;
    const pow = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].find(m => m * pow >= raw) * pow;
    const start = Math.floor(min / step) * step;
    const ticks = [start];
    while (ticks[ticks.length - 1] < max) ticks.push(start + ticks.length * step);
    return ticks;
}

function buildChart(series) {
    const W = 340, H = 150, L = 44, R = 14, TOP = 12, B = 22;
    const pts = series.points;
    const last = pts[pts.length - 1];
    const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
    const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
    const ticks = niceTicks(Math.min(...ys), Math.max(...ys));
    const y0 = ticks[0], y1 = ticks[ticks.length - 1];
    const px = t => L + (x1 === x0 ? 0.5 : (t - x0) / (x1 - x0)) * (W - L - R);
    const py = v => TOP + (1 - (v - y0) / (y1 - y0)) * (H - TOP - B);

    const card = document.createElement('figure');
    card.className = 'chart-card';
    const cap = document.createElement('figcaption');
    const title = document.createElement('span');
    title.className = 'chart-title';
    title.textContent = series.label;
    const now = document.createElement('span');
    now.className = 'chart-now';
    now.textContent = formatValue(last[1], series.unit);
    cap.append(title, now);
    card.appendChild(cap);

    const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', tabindex: '0' });
    svg.setAttribute('aria-label', `${series.label}: ${formatValue(pts[0][1], series.unit)} → ${formatValue(last[1], series.unit)}`);
    for (const v of ticks) {
        svg.appendChild(svgEl('line', { x1: L, x2: W - R, y1: py(v), y2: py(v), class: v === y0 ? 'axis' : 'grid' }));
        const label = svgEl('text', { x: L - 6, y: py(v) + 4, 'text-anchor': 'end', class: 'tick' });
        label.textContent = formatValue(Math.round(v * 100) / 100, '');
        svg.appendChild(label);
    }
    for (const [t, anchor] of [[x0, 'start'], [x1, 'end']]) {
        const label = svgEl('text', { x: px(t), y: H - 5, 'text-anchor': anchor, class: 'tick' });
        label.textContent = formatDate(t, false);
        svg.appendChild(label);
    }
    svg.appendChild(svgEl('path', {
        class: 'series-area',
        d: `M${px(xs[0])},${py(y0)} ` + pts.map(p => `L${px(p[0])},${py(p[1])}`).join(' ') + ` L${px(x1)},${py(y0)} Z`,
    }));
    svg.appendChild(svgEl('path', { class: 'series-line', d: pts.map((p, i) => `${i ? 'L' : 'M'}${px(p[0])},${py(p[1])}`).join(' ') }));
    svg.appendChild(svgEl('circle', { class: 'series-dot', cx: px(last[0]), cy: py(last[1]), r: 4 }));

    const cross = svgEl('line', { class: 'crosshair', y1: TOP, y2: H - B, visibility: 'hidden' });
    const focus = svgEl('circle', { class: 'series-dot', r: 4, visibility: 'hidden' });
    svg.append(cross, focus);

    const tip = $('chart-tip');
    const show = (i, clientX, clientY) => {
        const p = pts[i];
        cross.setAttribute('x1', px(p[0])); cross.setAttribute('x2', px(p[0]));
        focus.setAttribute('cx', px(p[0])); focus.setAttribute('cy', py(p[1]));
        cross.setAttribute('visibility', 'visible'); focus.setAttribute('visibility', 'visible');
        tip.replaceChildren();
        const value = document.createElement('strong');
        value.textContent = formatValue(p[1], series.unit);
        const date = document.createElement('span');
        date.textContent = formatDate(p[0]);
        tip.append(value, date);
        tip.hidden = false;
        const box = tip.getBoundingClientRect();
        // beside the pointer, flipping to its left near the edge so it never covers the point
        const left = clientX + 14 + box.width > window.innerWidth - 8 ? clientX - box.width - 14 : clientX + 14;
        tip.style.left = Math.max(8, left) + 'px';
        tip.style.top = Math.max(8, clientY - box.height - 12) + 'px';
    };
    const hide = () => {
        cross.setAttribute('visibility', 'hidden'); focus.setAttribute('visibility', 'hidden');
        tip.hidden = true;
    };
    const nearest = (clientX) => {
        const rect = svg.getBoundingClientRect();
        const x = (clientX - rect.left) / rect.width * W;
        let best = 0;
        pts.forEach((p, i) => { if (Math.abs(px(p[0]) - x) < Math.abs(px(pts[best][0]) - x)) best = i; });
        return best;
    };
    let kb = pts.length - 1;
    svg.addEventListener('pointermove', e => { kb = nearest(e.clientX); show(kb, e.clientX, e.clientY); });
    svg.addEventListener('pointerleave', hide);
    svg.addEventListener('blur', hide);
    svg.addEventListener('keydown', e => {
        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
        e.preventDefault();
        kb = Math.max(0, Math.min(pts.length - 1, kb + (e.key === 'ArrowLeft' ? -1 : 1)));
        const rect = svg.getBoundingClientRect();
        show(kb, rect.left + px(pts[kb][0]) / W * rect.width, rect.top + py(pts[kb][1]) / H * rect.height);
    });
    card.appendChild(svg);

    const note = document.createElement('div');
    note.className = 'chart-note';
    note.textContent = T('chart.from', { date: formatDate(x0) }) + ' · ' + formatValue(pts[0][1], series.unit) + ' → ' + formatValue(last[1], series.unit);
    card.appendChild(note);

    const details = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = T('chart.table');
    const table = document.createElement('table');
    const headRow = table.insertRow();
    for (const h of [T('chart.date'), series.label]) {
        const th = document.createElement('th');
        th.textContent = h;
        headRow.appendChild(th);
    }
    for (const p of pts) {
        const row = table.insertRow();
        row.insertCell().textContent = formatDate(p[0]);
        row.insertCell().textContent = formatValue(p[1], series.unit);
    }
    details.append(summary, table);
    card.appendChild(details);
    return card;
}

/* ============================================================
   Problems
   ============================================================ */

function showProblems(result) {
    if (result.status !== 'ok') return;
    const container = $('problems-results');
    const open = result.problems.filter(p => p.status === 'open');
    const badge = $('nav-problems-count');
    badge.hidden = open.length === 0;
    badge.textContent = open.length;

    if (!result.problems.length) {
        container.innerHTML = placeholder('problems.none');
        return;
    }
    let html = `<p class="panel-summary">${escapeHtml(result.summary)}</p>`;
    for (const p of result.problems) {
        const fixed = p.status === 'fixed';
        let actions = '';
        if (fixed) {
            actions = `<div class="actions"><button class="btn btn-sm" data-rollback="${p.journal_id}">↩ ${escapeHtml(T('action.rollback'))}</button></div>`;
        } else if (p.fix) {
            const f = p.fix;
            const blocked = f.availability === 'blocked' || f.availability === 'unavailable';
            actions = `<div class="actions">
                <button class="btn btn-sm btn-primary" data-fix="${escapeHtml(p.key)}" ${blocked ? 'disabled' : ''}>${escapeHtml(T('action.fix'))}</button>
                <span class="risk-badge risk-${f.risk_level}">${RISK_ICONS[f.risk_level] || ''} ${escapeHtml(f.risk_label)}</span>
                ${blocked ? `<span class="fix-note">${escapeHtml(f.note)}</span>` : ''}
            </div>`;
        }
        const sev = fixed ? 'fixed' : p.severity;
        html += `
            <div class="problem-card ${sev}">
                <div>
                    <span class="severity severity-${sev}">${escapeHtml(T('severity.' + sev))}</span>
                    <span class="title">${escapeHtml(p.title)}</span>
                </div>
                <div class="desc">${escapeHtml(p.description)}</div>
                ${actions}
            </div>`;
    }
    container.innerHTML = html;
}

async function runUpgrade() {
    showLoading(T('loading.upgrade'));
    try {
        const result = await API.post('/api/upgrade');
        hideLoading();
        if (result.status !== 'ok') throw new Error(result.message);
        $('upgrade-results').innerHTML = `<div class="result-card"><pre>${escapeHtml(result.text)}</pre></div>`;
    } catch (err) {
        hideLoading();
        reportError(err);
    }
}

/* ============================================================
   Repair: plan → confirm → execute → journal
   ============================================================ */

async function fixProblem(problemKey) {
    try {
        const { outcome, message } = await API.post('/api/repair', { problem_id: problemKey, dry_run: true });
        if (!outcome) throw new Error(message);
        if (outcome.status !== 'done') {
            addMessage(outcome.message, 'error');
            showPanel('chat');
            return;
        }
        if (!outcome.requires_confirmation) {
            await executeRepair(problemKey);
            return;
        }
        const risk = $('repair-risk');
        risk.className = 'risk-badge risk-' + outcome.risk_level;
        risk.textContent = `${RISK_ICONS[outcome.risk_level] || ''} ${outcome.risk_label}`;
        $('repair-plan').textContent = outcome.plan;
        $('repair-note').textContent = outcome.message;
        $('repair-step-backup').hidden = !outcome.requires_backup;
        $('repair-confirm').onclick = async () => {
            closeRepair();
            await executeRepair(problemKey);
        };
        $('repair-modal').classList.add('active');
    } catch (err) {
        reportError(err);
    }
}

async function executeRepair(problemKey) {
    showLoading(T('loading.repair'));
    try {
        const { outcome, message } = await API.post('/api/repair', { problem_id: problemKey, confirm: true });
        hideLoading();
        if (!outcome) throw new Error(message);
        const ok = outcome.status === 'done';
        const suffix = ok && outcome.journal_id ? ` (${T('journal.entry', { id: outcome.journal_id })})` : '';
        addMessage(outcome.message + suffix, ok ? 'system' : 'error');
        await refreshAfterChange();
        return ok;
    } catch (err) {
        hideLoading();
        reportError(err);
        return false;
    }
}

function closeRepair() {
    $('repair-modal').classList.remove('active');
}

async function refreshAfterChange() {
    await refreshPanels();
    await loadJournal();
}

/* ============================================================
   Journal
   ============================================================ */

async function loadJournal() {
    try {
        const result = await API.get('/api/journal');
        const container = $('history-results');
        if (!result.entries || result.entries.length === 0) {
            container.innerHTML = placeholder('journal.empty');
            return;
        }
        container.innerHTML = result.entries.map(e => `
            <div class="journal-entry status-${e.status}">
                <div class="journal-main">
                    <span class="journal-id">#${e.id}</span>
                    <span class="title">${escapeHtml(e.description || e.action)}</span>
                    <span class="risk-badge risk-${e.risk_level}">${RISK_ICONS[e.risk_level] || ''}</span>
                    <span class="journal-status">${escapeHtml(T('journal.' + e.status))}</span>
                </div>
                <div class="desc">${escapeHtml(new Date(e.timestamp * 1000).toLocaleString(LANG))}${e.target ? ' · ' + escapeHtml(e.target) : ''}</div>
                ${e.can_rollback ? `<div class="actions"><button class="btn btn-sm" data-rollback="${e.id}">↩ ${escapeHtml(T('action.rollback'))}</button></div>` : ''}
            </div>`).join('');
    } catch (err) {
        console.warn('journal failed', err);
    }
}

async function rollbackEntry(entryId) {
    showLoading(T('loading.rollback'));
    try {
        const result = await API.post(`/api/journal/${entryId}/rollback`);
        hideLoading();
        addMessage(result.message, result.status === 'ok' ? 'system' : 'error');
        await refreshAfterChange();
        return result.status === 'ok';
    } catch (err) {
        hideLoading();
        reportError(err);
        return false;
    }
}

async function purgeBackups() {
    if (!confirm(T('journal.purge.confirm'))) return;
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
        addMessage(T('error.generic', { msg: result.message }), 'error');
        return;
    }
    $('demo-badge').hidden = !result.active;
    clearPanels();
    if (result.active) {
        addMessage(T('demo.on', { title: $('demo-select').selectedOptions[0].dataset.title }), 'system');
        await runScan();
    } else {
        addMessage(T('demo.off'), 'system');
    }
}

/* ============================================================
   Settings
   ============================================================ */

async function openSettings() {
    try {
        const current = await API.get('/api/settings');
        $('setting-backend').value = current.ai_backend;
        $('setting-expert').checked = current.expert_mode;
        $('setting-model').value = current.openrouter_model;
        $('setting-key').value = '';
        $('setting-key').placeholder = current.openrouter_key_set ? T('settings.key.saved') : 'sk-or-v1-…';
        $('setting-key-status').textContent = '';
    } catch {}
    $('settings-modal').classList.add('active');
}

function closeSettings() {
    $('settings-modal').classList.remove('active');
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
    const key = $('setting-key').value.trim();
    const model = $('setting-model').value.trim();
    if (key) payload.openrouter_api_key = key;
    if (model) payload.openrouter_model = model;
    const result = await API.post('/api/settings', payload);
    $('setting-backend').value = 'openrouter';
    $('setting-key').value = '';
    $('setting-key-status').textContent = T(result.ai_backend_active === 'openrouter' ? 'settings.key.ok' : 'settings.key.missing');
    await updateAiBadge();
}

async function updateAiBadge() {
    try {
        const status = await API.get('/api/status');
        const badge = $('ai-badge');
        if (status.ai_available) {
            badge.textContent = `AI: ${status.ai_model}${status.ai_agent ? ' · ' + T('badge.agent') : ''}`;
            badge.style.borderColor = 'var(--good)';
        } else {
            badge.textContent = T('badge.ai_off');
            badge.style.borderColor = '';
        }
    } catch {}
}

/* ============================================================
   Utilities and init
   ============================================================ */

function showLoading(text) {
    $('loading-text').textContent = text || T('loading.default');
    $('loading').style.display = 'flex';
}

function hideLoading() {
    $('loading').style.display = 'none';
}

document.addEventListener('click', (e) => {
    const fix = e.target.closest('[data-fix]');
    if (fix) fixProblem(fix.dataset.fix);
    const rollback = e.target.closest('[data-rollback]');
    if (rollback) rollbackEntry(rollback.dataset.rollback);
    const suggest = e.target.closest('[data-suggest]');
    if (suggest) sendMessage(T(suggest.dataset.suggest));
    const ask = e.target.closest('[data-ask]');
    if (ask) sendMessage(T(ask.dataset.ask));
});

document.addEventListener('DOMContentLoaded', async () => {
    applyI18n();
    document.querySelectorAll('#demo-select option[data-title]').forEach(o => {
        o.textContent = `${T('source.demo')}: ${o.dataset.title}`;
    });
    $('nav-upgrade').addEventListener('click', () => {
        if (!$('upgrade-results').querySelector('.result-card')) runUpgrade();
    });
    await updateAiBadge();
    await refreshPanels();   // a scan may already exist (page reload, --demo)
});
