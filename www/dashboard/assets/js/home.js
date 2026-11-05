/**
 * Accueil — indicateurs du serveur, applications et services tiers.
 * Les listes viennent du manifeste commun (window.SF_SERVICES) ; l'état
 * des conteneurs et les métriques de GET /api/system (cookie d'auth).
 */
(function () {
    const SF = window.SF;
    const esc = SF.esc;
    let running = null;          // Set des conteneurs en marche, null tant qu'inconnu

    const $ = (id) => document.getElementById(id);
    const txt = (id, v) => { const e = $(id); if (e && e.textContent !== v) e.textContent = v; };
    const fr = (n, d = 1) => Number(n).toLocaleString('fr-FR', { maximumFractionDigits: d, minimumFractionDigits: d });

    function meter(id, pct, warnAt = 75, dangerAt = 90) {
        const e = $(id);
        if (!e) return;
        e.style.width = Math.min(Math.max(pct || 0, 0), 100) + '%';
        const m = e.parentElement;
        m.classList.toggle('is-warning', pct >= warnAt && pct < dangerAt);
        m.classList.toggle('is-danger', pct >= dangerAt);
    }

    function stateOf(s) {
        if (!s.container || !running) return { cls: '', label: s.container ? '…' : '—' };
        return running.has(s.container)
            ? { cls: 'dot-ok', label: 'En ligne' }
            : { cls: 'dot-down', label: 'Arrêté' };
    }

    function renderApps() {
        const apps = SF.services.filter((s) => s.kind === 'internal');
        $('apps').innerHTML = apps.map((s) => {
            const st = stateOf(s);
            const ext = s.newTab ? ' target="_blank" rel="noopener"' : '';
            return `<a class="app-tile" href="${esc(SF.href(s))}"${ext} data-scope="${esc(s.scope)}">
                <span class="app-icon">${SF.icon(s.icon)}</span>
                <span class="app-name">${esc(s.label)}${s.scope === 'vpn' ? '<span class="badge">VPN</span>' : ''}</span>
                <span class="dot ${st.cls}" title="${esc(st.label)}"></span>
                <span class="app-desc">${esc(s.desc || '')}</span>
            </a>`;
        }).join('');
    }

    function renderExternals() {
        const ext = SF.services.filter((s) => s.kind === 'external');
        $('externals').innerHTML = ext.map((s) => {
            const st = stateOf(s);
            const host = new URL(s.url).host;
            return `<tr data-scope="${esc(s.scope)}">
                <td><a href="${esc(s.url)}" target="_blank" rel="noopener">${SF.icon(s.icon)}${esc(s.label)}</a></td>
                <td class="hide-sm text-2">${esc(s.desc || '')}</td>
                <td class="hide-sm"><span class="ext-host">${esc(host)}</span></td>
                <td>${s.scope === 'vpn' ? '<span class="badge">VPN</span>' : '<span class="badge badge-accent">Public</span>'}</td>
                <td><span class="ext-state"><span class="dot ${st.cls}"></span>${esc(st.label)}</span></td>
            </tr>`;
        }).join('');
    }

    function markVpn() {
        SF.vpnReachable((ok) => {
            if (ok) return;
            document.querySelectorAll('[data-scope="vpn"]').forEach((el) => {
                el.classList.add('is-unreachable');
                el.title = 'Accessible via Tailscale uniquement';
            });
        });
    }

    function render() {
        renderApps();
        renderExternals();
        markVpn();
    }

    function update(d) {
        if (d.cpu) {
            txt('k-cpu', fr(d.cpu.percent) + ' %');
            meter('m-cpu', d.cpu.percent);
            txt('s-cpu', `${d.cpu.cores} cœurs · charge ${(d.system?.load || []).map((l) => fr(l, 2)).join(' ')}`);
        }
        if (d.memory) {
            txt('k-mem', fr(d.memory.percent) + ' %');
            meter('m-mem', d.memory.percent);
            txt('s-mem', `${fr(d.memory.used_gb)} / ${fr(d.memory.total_gb)} Go`);
        }
        if (d.disk) {
            txt('k-disk', fr(d.disk.percent) + ' %');
            meter('m-disk', d.disk.percent, 85, 95);
            txt('s-disk', `${fr(d.disk.total_gb - d.disk.used_gb, 0)} Go libres sur ${fr(d.disk.total_gb, 0)}`);
        }
        const cts = d.containers || [];
        const up = cts.filter((c) => c.state === 'running');
        txt('k-ct', `${up.length} / ${cts.length}`);
        const down = cts.filter((c) => c.state !== 'running').map((c) => c.name);
        txt('s-ct', down.length ? `Arrêté : ${down.join(', ')}` : 'Tous en marche');
        $('s-ct').className = 'kpi-sub ' + (down.length ? 'negative' : '');
        if (d.system) txt('host-meta', `${d.system.hostname} · en ligne depuis ${d.system.uptime}`);

        const next = new Set(up.map((c) => c.name));
        const changed = !running || next.size !== running.size || [...next].some((n) => !running.has(n));
        running = next;
        if (changed) render();
    }

    // Hors VPN, les liens VPN restent affichés mais ne mènent nulle part.
    document.addEventListener('click', (e) => {
        if (e.target.closest('.is-unreachable')) e.preventDefault();
    });

    let timer = null;
    async function poll() {
        clearTimeout(timer);
        try {
            const r = await window.authFetch('/api/system');
            if (r.ok) {
                const d = await r.json();
                if (d.status !== 'loading') update(d);
            }
        } catch (e) { /* silencieux : l'accueil reste utilisable */ }
        if (!document.hidden) timer = setTimeout(poll, 15000);
    }

    document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
    render();
    window.addEventListener('auth-ready', poll);
})();
