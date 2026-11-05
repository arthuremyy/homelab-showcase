/**
 * HomeLab Monitoring Dashboard v5.0
 * Optimised: DOM diff, setTimeout polling, cached refs, rAF batching
 * Fixed: real host network via /proc/1/net/dev
 */

const STATE_FR = { running: 'en marche', exited: 'arrêté', paused: 'en pause', restarting: 'redémarre', created: 'créé', dead: 'mort' };

class Dashboard {
    constructor() {
        this.charts = {};
        this.live = { labels: [], cpu: [], mem: [], netD: [], netU: [], dioR: [], dioW: [] };
        this.maxPts = 120;
        this.period = 'live';
        this.timer = null;
        this.errCount = 0;
        this.polling = false;

        // DOM reference cache
        this._refs = {};
        this._escEl = document.createElement('div');

        // Diff keys to avoid unnecessary DOM rebuilds
        this._prev = { containers: '', cores: '', disks: '', procCpu: '', procMem: '', ifaces: '' };
    }

    init() {
        this.cacheRefs();
        this.initCharts();
        this.bindPeriod();
        this.bindSpeedtest();
        this.startClock();
        this.startPolling();
    }

    /* ── DOM helpers ── */

    cacheRefs() {
        const ids = [
            'v-host', 'v-os', 'v-uptime', 'v-load',
            'c-cpu', 'c-mem', 'c-swap', 'c-disk', 'c-net', 'c-temp',
            'b-cpu', 'b-mem', 'b-swap', 'b-disk', 'b-temp',
            's-cpu', 's-mem', 's-swap', 's-disk', 's-temp',
            's-net-down', 's-net-up', 's-net-total',
            'cores-grid', 'ct-grid', 'ct-count',
            'disks-list', 'proc-cpu', 'proc-mem', 'ifaces',
            'status-badge', 'status-text', 'update-info', 'clock',
            'st-btn-host', 'st-btn-vpn',
            'st-dl-host', 'st-ul-host', 'st-ping-host', 'st-details-host',
            'st-dl-vpn', 'st-ul-vpn', 'st-ping-vpn', 'st-details-vpn'
        ];
        for (const id of ids) this._refs[id] = document.getElementById(id);
    }

    ref(id) { return this._refs[id] || document.getElementById(id); }

    txt(id, val) {
        const e = this.ref(id);
        const v = val ?? '—';
        if (e && e.textContent !== v) e.textContent = v;
    }

    bar(id, pct, warnAt = 75, dangerAt = 90) {
        const e = this.ref(id);
        if (e) {
            const w = Math.min(Math.max(pct || 0, 0), 100) + '%';
            if (e.style.width !== w) e.style.width = w;
            const m = e.parentElement;
            m.classList.toggle('is-warning', pct >= warnAt && pct < dangerAt);
            m.classList.toggle('is-danger', pct >= dangerAt);
        }
    }

    esc(s) { this._escEl.textContent = s || ''; return this._escEl.innerHTML; }

    /* ── Charts ── */

    /** Couleurs lues dans les jetons du design system (clair ou sombre). */
    palette() {
        const v = (n, f) => (window.SF ? SF.cssVar(n) : '') || f;
        return {
            text: v('--text', '#17191c'), text2: v('--text-2', '#4b5058'), text3: v('--text-3', '#737a84'),
            grid: v('--chart-grid', '#eceef1'), border: v('--border', '#e3e5e8'), surface: v('--surface', '#fff'),
            font: v('--font', 'system-ui, sans-serif'),
            c1: v('--chart-1', '#2f5bd0'), c2: v('--chart-2', '#1a9486'), c3: v('--chart-3', '#c88114'),
            c4: v('--chart-4', '#c2466b'), c5: v('--chart-5', '#6b5bc4'),
        };
    }

    /** Changement de thème : on reconstruit les graphiques avec les nouvelles couleurs. */
    retheme() {
        const data = {};
        for (const k in this.charts) {
            const c = this.charts[k];
            data[k] = { labels: c.data.labels, sets: c.data.datasets.map(d => d.data) };
            c.destroy();
        }
        this.charts = {};
        this.initCharts();
        for (const k in data) this.setChartData(this.charts[k], data[k].labels, data[k].sets);
    }

    initCharts() {
        const P = this.palette();
        const grid = { color: P.grid };
        const ticks = { color: P.text3, font: { size: 11, family: P.font } };

        // Ligne verticale au survol
        const crosshairPlugin = {
            id: 'crosshair',
            afterDraw(chart) {
                if (chart.tooltip?._active?.length) {
                    const x = chart.tooltip._active[0].element.x;
                    const yAxis = chart.scales.y;
                    const ctx = chart.ctx;
                    ctx.save();
                    ctx.beginPath();
                    ctx.moveTo(x, yAxis.top);
                    ctx.lineTo(x, yAxis.bottom);
                    ctx.lineWidth = 1;
                    ctx.strokeStyle = P.border;
                    ctx.stroke();
                    ctx.restore();
                }
            }
        };

        const tooltipConf = {
            enabled: true,
            mode: 'index',
            intersect: false,
            backgroundColor: P.surface,
            titleColor: P.text,
            bodyColor: P.text2,
            borderColor: P.border,
            borderWidth: 1,
            cornerRadius: 6,
            padding: 10,
            titleFont: { size: 12, weight: '600', family: P.font },
            bodyFont: { size: 12, family: P.font },
            bodySpacing: 4,
            usePointStyle: true,
            boxWidth: 8,
            boxHeight: 8,
            boxPadding: 4,
            caretSize: 0,
            displayColors: true,
        };

        const base = {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: { mode: 'index', intersect: false },
            hover: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: tooltipConf,
            },
            scales: {
                x: { display: true, grid: { display: false }, ticks: { ...ticks, maxTicksLimit: 6, maxRotation: 0 } },
                y: { min: 0, grid, ticks }
            }
        };

        const mkLine = (color) => ({
            data: [], borderColor: color, backgroundColor: color,
            fill: false, tension: 0, pointRadius: 0,
            pointHoverRadius: 3, pointHoverBackgroundColor: color,
            pointHoverBorderWidth: 0,
            borderWidth: 1.5
        });

        // Single-dataset tooltip formatter (CPU / RAM)
        const singleTooltip = (unit) => ({
            ...tooltipConf,
            callbacks: {
                label: (ctx) => ' ' + ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(1) + unit,
            }
        });

        // Multi-dataset tooltip formatter (Net / Disk IO)
        const multiTooltip = (unit) => ({
            ...tooltipConf,
            callbacks: {
                label: (ctx) => ' ' + ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(2) + unit,
            }
        });

        const legendConf = { display: true, align: 'end', labels: { color: P.text2, boxWidth: 8, boxHeight: 8, usePointStyle: true, pointStyle: 'circle', font: { size: 11, family: P.font } } };

        this.charts.cpu = new Chart(document.getElementById('chart-cpu'), {
            type: 'line',
            data: { labels: [], datasets: [{ label: 'CPU', ...mkLine(P.c1) }] },
            options: { ...base, scales: { ...base.scales, y: { ...base.scales.y, max: 100 } },
                plugins: { ...base.plugins, tooltip: singleTooltip('%') } },
            plugins: [crosshairPlugin]
        });

        this.charts.mem = new Chart(document.getElementById('chart-mem'), {
            type: 'line',
            data: { labels: [], datasets: [{ label: 'Mémoire', ...mkLine(P.c5) }] },
            options: { ...base, scales: { ...base.scales, y: { ...base.scales.y, max: 100 } },
                plugins: { ...base.plugins, tooltip: singleTooltip('%') } },
            plugins: [crosshairPlugin]
        });

        this.charts.net = new Chart(document.getElementById('chart-net'), {
            type: 'line',
            data: { labels: [], datasets: [
                { label: 'Descendant', ...mkLine(P.c2) },
                { label: 'Montant', ...mkLine(P.c3) }
            ]},
            options: { ...base, plugins: { ...base.plugins, legend: legendConf, tooltip: multiTooltip(' MB/s') } },
            plugins: [crosshairPlugin]
        });

        this.charts.dio = new Chart(document.getElementById('chart-dio'), {
            type: 'line',
            data: { labels: [], datasets: [
                { label: 'Lecture', ...mkLine(P.c1) },
                { label: 'Écriture', ...mkLine(P.c4) }
            ]},
            options: { ...base, plugins: { ...base.plugins, legend: legendConf, tooltip: multiTooltip(' MB/s') } },
            plugins: [crosshairPlugin]
        });
    }

    /* ── Period selector ── */

    bindPeriod() {
        document.querySelectorAll('.period-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.period = btn.dataset.p;

                if (this.period === 'live') {
                    this.clearLive();
                    // Polling is always running, just update info
                    this.setInfo('Temps réel — 1 s');
                } else {
                    this.loadHistory(this.period);
                    this.setInfo('Historique');
                }
            });
        });
    }

    /* ── Polling (robust, with timeout + visibility + overlap protection) ── */

    startPolling() {
        if (this.polling) return; // prevent duplicate chains
        this.polling = true;
        this._pollInFlight = false;

        // Visibility API: pause when tab hidden, immediate refresh on return
        if (!this._visHandler) {
            this._visHandler = () => {
                if (document.hidden) {
                    // Tab hidden → clear timer (browser throttles anyway)
                    if (this.timer) { clearTimeout(this.timer); this.timer = null; }
                } else if (this.polling) {
                    // Tab visible again → poll immediately for fresh data
                    if (this.timer) clearTimeout(this.timer);
                    this.poll();
                }
            };
            document.addEventListener('visibilitychange', this._visHandler);
        }

        this.poll();
    }

    stopPolling() {
        this.polling = false;
        if (this.timer) { clearTimeout(this.timer); this.timer = null; }
    }

    schedulePoll() {
        if (!this.polling || document.hidden) return;
        const delay = this.errCount > 0 ? 5000 : 1000;
        this.timer = setTimeout(() => this.poll(), delay);
    }

    async poll() {
        if (this._pollInFlight) return; // skip if previous poll still running
        this._pollInFlight = true;

        try {
            // Fetch with 8s timeout to avoid hanging forever
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 8000);

            const r = await authFetch('/api/system', { signal: controller.signal });
            clearTimeout(timeout);

            if (!r.ok) throw new Error('HTTP ' + r.status);
            const d = await r.json();

            if (d.status === 'loading') {
                this.setStatus(true);
                return;
            }

            this.errCount = 0;
            this.setStatus(true);

            requestAnimationFrame(() => {
                this.updateAll(d);
                if (this.period === 'live') {
                    this.pushLive(d);
                    this.refreshCharts();
                }
            });
        } catch (e) {
            this.errCount++;
            if (this.errCount > 3) this.setStatus(false);
            // Log only real errors, not aborts
            if (e.name !== 'AbortError') console.warn('Poll error:', e.message);
        } finally {
            this._pollInFlight = false;
            this.schedulePoll();
        }
    }

    /* ── History ── */

    async loadHistory(period) {
        try {
            const r = await authFetch('/api/history?period=' + period);
            const result = await r.json();
            if (!result.data || result.data.length === 0) return;

            const long = period === '7d' || period === '30d';
            const labels = result.data.map(d => {
                const dt = new Date(d.t * 1000);
                return long
                    ? dt.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' }) + ' ' + dt.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
                    : dt.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
            });

            this.setChartData(this.charts.cpu, labels, [result.data.map(d => d.cpu)]);
            this.setChartData(this.charts.mem, labels, [result.data.map(d => d.memory)]);
            this.setChartData(this.charts.net, labels, [result.data.map(d => d.net_down), result.data.map(d => d.net_up)]);
            this.setChartData(this.charts.dio, labels, [result.data.map(d => d.disk_read), result.data.map(d => d.disk_write)]);
        } catch (e) {
            console.error('History error:', e);
        }
    }

    setChartData(chart, labels, datasets) {
        chart.data.labels = labels;
        for (let i = 0; i < datasets.length; i++) chart.data.datasets[i].data = datasets[i];
        chart.update('none');
    }

    /* ── Live chart data ── */

    pushLive(d) {
        const t = new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const L = this.live;
        L.labels.push(t);
        L.cpu.push(d.cpu?.percent ?? 0);
        L.mem.push(d.memory?.percent ?? 0);
        L.netD.push(d.network?.download_mb ?? 0);
        L.netU.push(d.network?.upload_mb ?? 0);
        L.dioR.push(d.disk_io?.read_mb ?? 0);
        L.dioW.push(d.disk_io?.write_mb ?? 0);

        if (L.labels.length > this.maxPts) {
            const cut = L.labels.length - this.maxPts;
            for (const k in L) L[k] = L[k].slice(cut);
        }
    }

    clearLive() { for (const k in this.live) this.live[k] = []; }

    refreshCharts() {
        const L = this.live;
        this.setChartData(this.charts.cpu, L.labels, [L.cpu]);
        this.setChartData(this.charts.mem, L.labels, [L.mem]);
        this.setChartData(this.charts.net, L.labels, [L.netD, L.netU]);
        this.setChartData(this.charts.dio, L.labels, [L.dioR, L.dioW]);
    }

    /* ── UI updates (diff-based) ── */

    updateAll(d) {
        // System bar
        this.txt('v-host', d.system?.hostname);
        this.txt('v-os', d.system?.os);
        this.txt('v-uptime', d.system?.uptime);
        this.txt('v-load', d.system?.load?.map(l => l.toFixed(2)).join('  '));

        // CPU card
        if (d.cpu) {
            this.txt('c-cpu', d.cpu.percent + '%');
            this.bar('b-cpu', d.cpu.percent);
            this.txt('s-cpu', d.cpu.cores + ' cœurs · ' + d.cpu.threads + ' threads · ' + d.cpu.freq_mhz + ' MHz');
        }

        // Memory card
        if (d.memory) {
            this.txt('c-mem', d.memory.percent + '%');
            this.bar('b-mem', d.memory.percent);
            this.txt('s-mem', d.memory.used_gb + ' / ' + d.memory.total_gb + ' Go');
            this.txt('c-swap', d.memory.swap_percent + '%');
            this.bar('b-swap', d.memory.swap_percent);
            this.txt('s-swap', d.memory.swap_used_gb + ' / ' + d.memory.swap_total_gb + ' Go');
        }

        // Disk card
        if (d.disk) {
            this.txt('c-disk', d.disk.percent + '%');
            this.bar('b-disk', d.disk.percent, 85, 95);
            let diskSub = d.disk.used_gb + ' / ' + d.disk.total_gb + ' Go · ' + d.disk.mount;
            if (d.disk_io) {
                diskSub += '\nLecture ' + d.disk_io.read_mb.toFixed(2) + ' · écriture ' + d.disk_io.write_mb.toFixed(2) + ' Mo/s';
            }
            this.txt('s-disk', diskSub);
        }

        // Network card (real host data)
        if (d.network) {
            const total = (d.network.download_mb + d.network.upload_mb).toFixed(2);
            this.txt('c-net', total + ' Mo/s');
            this.txt('s-net-down', d.network.download_mb.toFixed(2) + ' Mo/s');
            this.txt('s-net-up', d.network.upload_mb.toFixed(2) + ' Mo/s');
            // Total bandwidth
            const iface = d.network.interface || 'enp4s0';
            this.txt('s-net-total', iface + ' · reçu ' + d.network.total_recv_gb + ' Go · émis ' + d.network.total_sent_gb + ' Go');
        }

        // Temperature card — CPU prioritaire, disque en subtitle
        const temps = d.temperatures || {};
        const cpuTemp  = temps.cpu;
        const diskTemp = temps.disk || temps.other;
        if (cpuTemp) {
            this.txt('c-temp', cpuTemp.value + ' °C');
            this.bar('b-temp', Math.min(cpuTemp.value, 100), 70, 85);
            let sub = 'CPU (' + cpuTemp.sensor + ')';
            if (diskTemp) sub += '\nDisque : ' + diskTemp.value + ' °C';
            this.txt('s-temp', sub);
        } else if (diskTemp) {
            this.txt('c-temp', diskTemp.value + '°C');
            this.bar('b-temp', Math.min(diskTemp.value, 100));
            this.txt('s-temp', 'Disque (' + diskTemp.sensor + ')\nCPU : N/D');
        } else if (d.temperature) {
            this.txt('c-temp', d.temperature.value + '°C');
            this.bar('b-temp', Math.min(d.temperature.value, 100));
            this.txt('s-temp', d.temperature.sensor || 'Inconnu');
        } else {
            this.txt('c-temp', 'N/A');
            this.txt('s-temp', 'Non disponible');
        }

        // Sub-sections
        this.updateCores(d.cpu?.per_core);
        this.updateContainers(d.containers);
        this.updateDisks(d.disks);
        this.updateProcesses(d.processes);
        this.updateInterfaces(d.interfaces);
    }

    /* ── Diff-based section updates ── */

    updateCores(cores) {
        if (!cores) return;
        const key = cores.join(',');
        if (key === this._prev.cores) return;
        this._prev.cores = key;
        const el = this.ref('cores-grid');
        if (!el) return;
        el.innerHTML = cores.map((val, i) => {
            const cls = val > 80 ? ' is-danger' : val > 50 ? ' is-warning' : '';
            return '<div class="core-item"><span class="core-label">Cœur ' + i + '</span>' +
                '<span class="core-val">' + val + ' %</span>' +
                '<div class="meter' + cls + '"><span style="width:' + Math.min(val, 100) + '%"></span></div></div>';
        }).join('');
    }

    updateContainers(containers) {
        if (!containers) return;
        this.txt('ct-count', containers.length);
        const key = containers.map(c => c.name + c.state + (c.cpu_percent | 0) + (c.memory_mb | 0)).join('|');
        if (key === this._prev.containers) return;
        this._prev.containers = key;
        const el = this.ref('ct-grid');
        if (!el) return;
        el.innerHTML = containers.map(c => {
            const dot = c.state === 'running' ? 'dot-ok' : c.state === 'exited' ? 'dot-down' : 'dot-warn';
            const ram = c.memory_mb != null
                ? c.memory_mb + ' Mo' + (c.memory_percent ? ' · ' + c.memory_percent.toFixed(1) + ' %' : '')
                : '—';
            return '<tr><td>' + this.esc(c.name) + '</td>' +
                '<td><span class="ct-state"><span class="dot ' + dot + '"></span>' + this.esc(STATE_FR[c.state] || c.state) + '</span></td>' +
                '<td class="num">' + (c.cpu_percent ?? '—') + ' %</td>' +
                '<td class="num">' + ram + '</td>' +
                '<td class="hide-md"><div class="ct-image" title="' + this.esc(c.image) + '">' + this.esc(c.image) + '</div></td></tr>';
        }).join('');
    }

    updateDisks(disks) {
        if (!disks) return;
        const key = disks.map(d => d.mount + d.percent).join('|');
        if (key === this._prev.disks) return;
        this._prev.disks = key;
        const el = this.ref('disks-list');
        if (!el) return;
        el.innerHTML = disks.map(d => {
            const cls = d.percent > 90 ? ' is-danger' : d.percent > 75 ? ' is-warning' : '';
            return '<div class="list-row"><span class="list-name">' + this.esc(d.mount) + '</span>' +
                '<span class="list-val">' + d.used_gb + ' / ' + d.total_gb + ' Go · ' + d.percent + ' %</span></div>' +
                '<div class="meter' + cls + '"><span style="width:' + d.percent + '%"></span></div>';
        }).join('');
    }

    updateProcesses(procs) {
        if (!procs) return;
        if (procs.by_cpu) {
            const key = procs.by_cpu.map(p => p.name + p.cpu).join('|');
            if (key !== this._prev.procCpu) {
                this._prev.procCpu = key;
                const el = this.ref('proc-cpu');
                if (el) el.innerHTML = procs.by_cpu.map(p =>
                    '<div class="list-row"><span class="list-name">' + this.esc(p.name) + '</span><span class="list-val">' + p.cpu + ' %</span></div>'
                ).join('');
            }
        }
        if (procs.by_memory) {
            const key = procs.by_memory.map(p => p.name + p.mem_mb).join('|');
            if (key !== this._prev.procMem) {
                this._prev.procMem = key;
                const el = this.ref('proc-mem');
                if (el) el.innerHTML = procs.by_memory.map(p =>
                    '<div class="list-row"><span class="list-name">' + this.esc(p.name) + '</span><span class="list-val">' +
                    p.mem_mb + ' Mo' + (p.percent ? ' · ' + p.percent.toFixed(1) + ' %' : '') + '</span></div>'
                ).join('');
            }
        }
    }

    updateInterfaces(ifaces) {
        if (!ifaces) return;
        const key = ifaces.map(i => i.name + i.ip + i.up + (i.rx_gb || 0) + (i.tx_gb || 0)).join('|');
        if (key === this._prev.ifaces) return;
        this._prev.ifaces = key;
        const el = this.ref('ifaces');
        if (!el) return;
        el.innerHTML = ifaces.map(i =>
            '<div class="iface-row">' +
            '<span class="dot ' + (i.up ? 'dot-ok' : 'dot-down') + '"></span>' +
            '<span class="list-name">' + this.esc(i.name) + '</span>' +
            '<span class="iface-ip">' + this.esc(i.ip || '—') + '</span>' +
            '<span class="iface-traffic">' +
                '<span>reçu ' + (i.rx_gb ?? '—') + ' Go</span>' +
                '<span>émis ' + (i.tx_gb ?? '—') + ' Go</span>' +
                (i.speed ? '<span>' + i.speed + ' Mbit/s</span>' : '') +
            '</span>' +
            '</div>'
        ).join('');
    }

    /* ── Helpers ── */

    setStatus(ok) {
        const b = this.ref('status-badge');
        const t = this.ref('status-text');
        const cls = 'status-badge ' + (ok ? 'connected' : 'error');
        if (b && b.className !== cls) b.className = cls;
        const txt = ok ? 'Connecté' : 'Déconnecté';
        if (t && t.textContent !== txt) t.textContent = txt;
    }

    setInfo(msg) { this.txt('update-info', msg); }

    startClock() {
        const el = this.ref('clock');
        if (!el) return;
        const fmt = { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' };
        const update = () => { el.textContent = new Date().toLocaleString('fr-FR', fmt); };
        update();
        setInterval(update, 1000);
    }

    /* ── SpeedTest ── */

    bindSpeedtest() {
        document.querySelectorAll('.st-btn').forEach(btn => {
            btn.addEventListener('click', () => this.runSpeedtest(btn.dataset.target));
        });
    }

    async runSpeedtest(target) {
        const btn = this.ref('st-btn-' + target);
        if (!btn || btn.disabled) return;

        btn.disabled = true;
        btn.classList.add('running');
        btn.textContent = 'En cours…';

        ['dl', 'ul', 'ping'].forEach(m => this.txt('st-' + m + '-' + target, '—'));
        const det = this.ref('st-details-' + target);
        if (det) det.innerHTML = '<span>Test en cours, environ 30 s…</span>';

        try {
            const r = await authFetch('/api/speedtest/run?target=' + target, { method: 'POST' });
            const res = await r.json();
            if (!res.ok) throw new Error(res.error || 'Erreur');
            this._pollSpeedtest(target);
        } catch (e) {
            btn.disabled = false;
            btn.classList.remove('running');
            btn.textContent = 'Lancer';
            if (det) det.innerHTML = '<span class="st-error">' + this.esc(e.message) + '</span>';
        }
    }

    async _pollSpeedtest(target) {
        try {
            const r = await authFetch('/api/speedtest/status');
            const data = await r.json();
            const st = data[target];

            if (st.status === 'running') {
                setTimeout(() => this._pollSpeedtest(target), 2000);
                return;
            }

            const btn = this.ref('st-btn-' + target);
            if (btn) {
                btn.disabled = false;
                btn.classList.remove('running');
                btn.textContent = 'Relancer';
            }

            const det = this.ref('st-details-' + target);

            if (st.status === 'done' && st.data) {
                this.txt('st-dl-' + target, st.data.download);
                this.txt('st-ul-' + target, st.data.upload);
                this.txt('st-ping-' + target, st.data.ping);
                if (det) {
                    det.innerHTML =
                        '<span><b>Serveur</b> ' + this.esc(st.data.server) + ' (' + this.esc(st.data.location) + ')</span>' +
                        '<span><b>IP</b> ' + this.esc(st.data.ip) + '</span>' +
                        (st.data.isp ? '<span><b>FAI</b> ' + this.esc(st.data.isp) + '</span>' : '');
                }
            } else if (st.status === 'error') {
                if (det) det.innerHTML = '<span class="st-error">' + this.esc(st.error || 'Erreur inconnue') + '</span>';
            }
        } catch (e) {
            setTimeout(() => this._pollSpeedtest(target), 3000);
        }
    }
}

/* ── Start ── */
function startMonitoring() {
    if (window.__monitoring) return;
    window.__monitoring = new Dashboard();
    window.__monitoring.init();
    window.addEventListener('sf-themechange', () => window.__monitoring.retheme());
}
// Le script est différé : l'authentification a pu aboutir avant son exécution.
if (document.body.classList.contains('authenticated')) startMonitoring();
else window.addEventListener('auth-ready', startMonitoring);