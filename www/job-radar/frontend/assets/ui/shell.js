/* HomeLab UI — barre latérale commune.
 *
 * À charger dans <head>, APRÈS services.js, en script classique (pas de defer) :
 * il applique le thème et l'état replié avant le premier rendu, puis insère
 * la barre au chargement du DOM.
 *
 * Les préférences (thème, barre repliée) sont des cookies posés sur
 * .example.com : ils suivent l'utilisateur d'une application à l'autre,
 * ce que localStorage (propre à chaque sous-domaine) ne permet pas.
 *
 * API exposée : window.SF.icon(nom), SF.cssVar(nom), SF.services,
 * événement window « sf-themechange » à chaque changement de thème effectif.
 */
(function () {
    'use strict';

    var ROOT = 'example.com';
    var DASH_HOSTS = [ROOT, 'invest.' + ROOT];
    var VPN_PROBE = 'https://dashboard.' + ROOT + '/assets/ui/probe.svg';
    var html = document.documentElement;
    var services = window.SF_SERVICES || [];

    // ── Icônes : trait 1,5 px, 24×24, currentColor ──────────────────────────
    var P = {
        home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M10 21v-6h4v6"/>',
        activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
        wallet: '<path d="M4 7a2 2 0 0 1 2-2h12v4"/><path d="M4 7v11a2 2 0 0 0 2 2h14V9H6a2 2 0 0 1-2-2z"/><path d="M16 14.5h.01"/>',
        chart: '<path d="M3 3v18h18"/><path d="m7 15 4-4 3 3 6-6"/>',
        briefcase: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M3 13h18"/>',
        drive: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 14h18"/><path d="M7 17h.01M11 17h.01"/>',
        gamepad: '<rect x="2" y="6" width="20" height="12" rx="4"/><path d="M6 12h4M8 10v4"/><path d="M15 13h.01M18 11h.01"/>',
        exchange: '<path d="M7 4 3 8l4 4"/><path d="M3 8h14"/><path d="m17 12 4 4-4 4"/><path d="M21 16H7"/>',
        bike: '<circle cx="5.5" cy="17" r="3.5"/><circle cx="18.5" cy="17" r="3.5"/><path d="M5.5 17 9 9h7l2.5 8"/><path d="M9 9 12 17l4-8"/><path d="M14 5h3"/>',
        film: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18M17 3v18M3 8h4M3 16h4M17 8h4M17 16h4M3 12h18"/>',
        inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z"/>',
        folder: '<path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
        file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h6"/>',
        clapper: '<path d="M4 11v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8z"/><path d="M4 11 19.5 7l-.8-3.2a1 1 0 0 0-1.2-.7L4.7 6.3a1 1 0 0 0-.7 1.2z"/>',
        tv: '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="m17 2-5 5-5-5"/>',
        search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
        captions: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 15h4M15 15h2M7 11h2M13 11h4"/>',
        download: '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
        shield: '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/>',
        code: '<path d="m16 18 6-6-6-6"/><path d="m8 6-6 6 6 6"/>',
        external: '<path d="M7 17 17 7"/><path d="M8 7h9v9"/>',
        chevron: '<path d="m6 9 6 6 6-6"/>',
        collapse: '<path d="m11 17-5-5 5-5"/><path d="m18 17-5-5 5-5"/>',
        menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
        logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
        sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
        moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
        monitor: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
        refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/>',
        plus: '<path d="M12 5v14M5 12h14"/>',
        x: '<path d="M18 6 6 18M6 6l12 12"/>',
        lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
        server: '<rect x="3" y="4" width="18" height="7" rx="1.5"/><rect x="3" y="13" width="18" height="7" rx="1.5"/><path d="M7 7.5h.01M7 16.5h.01"/>',
        cpu: '<rect x="6" y="6" width="12" height="12" rx="1.5"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
        down: '<path d="M12 5v14"/><path d="m6 13 6 6 6-6"/>',
        up: '<path d="M12 19V5"/><path d="m6 11 6-6 6 6"/>',
        play: '<path d="M7 5v14l11-7z"/>',
        box: '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="m3 8 9 5 9-5M12 13v8"/>'
    };

    function icon(name, cls) {
        return '<svg class="' + (cls || '') + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
            'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
            (P[name] || P.box) + '</svg>';
    }

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    // ── Préférences partagées entre sous-domaines ───────────────────────────
    function onRootDomain() {
        var h = location.hostname;
        return h === ROOT || h.slice(-(ROOT.length + 1)) === '.' + ROOT;
    }
    function getPref(name) {
        try {
            var m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
            return m ? decodeURIComponent(m[1]) : null;
        } catch (e) { return null; }
    }
    function setPref(name, value) {
        try {
            document.cookie = name + '=' + encodeURIComponent(value) + '; path=/; max-age=31536000; SameSite=Lax' +
                (onRootDomain() ? '; domain=.' + ROOT : '') + (location.protocol === 'https:' ? '; Secure' : '');
        } catch (e) { /* cookies bloqués : préférence non mémorisée */ }
    }

    // ── Thème ───────────────────────────────────────────────────────────────
    var mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
    function themeMode() {
        var t = getPref('sf_theme');
        return t === 'light' || t === 'dark' ? t : 'auto';
    }
    function effectiveTheme() {
        var m = themeMode();
        if (m !== 'auto') return m;
        return mq && mq.matches ? 'dark' : 'light';
    }
    function applyTheme() {
        var m = themeMode();
        if (m === 'auto') html.removeAttribute('data-theme');
        else html.setAttribute('data-theme', m);
    }
    function announceTheme() {
        try { window.dispatchEvent(new CustomEvent('sf-themechange', { detail: { theme: effectiveTheme() } })); }
        catch (e) { /* navigateur ancien */ }
    }

    // Appliqués tout de suite : aucun clignotement au chargement.
    applyTheme();
    if (getPref('sf_nav') === 'collapsed') html.setAttribute('data-sf-nav', 'collapsed');
    html.classList.add('sf-has-shell');
    if (mq && mq.addEventListener) mq.addEventListener('change', function () {
        if (themeMode() === 'auto') announceTheme();
    });

    // ── Liens et élément actif ──────────────────────────────────────────────
    var onDash = DASH_HOSTS.indexOf(location.host) >= 0 || !onRootDomain();  // IP/localhost = tests du tableau de bord

    function cleanPath(p) {
        p = p.replace(/\.html$/, '').replace(/\/index$/, '/');
        return p || '/';
    }
    function hrefOf(s) {
        var u = new URL(s.url);
        if (onDash && DASH_HOSTS.indexOf(u.host) >= 0) return u.pathname;   // garde invest. et les tests locaux
        return s.url;
    }
    function isActive(s) {
        var u = new URL(s.url);
        if (DASH_HOSTS.indexOf(u.host) >= 0) {
            if (!onDash) return false;
            if (s.hosts && s.hosts.indexOf(location.host) >= 0) return true;
            if (location.host.indexOf('invest.') === 0) return false;
            return cleanPath(location.pathname) === cleanPath(u.pathname);
        }
        return u.host === location.host;
    }
    function current() {
        for (var i = 0; i < services.length; i++) if (isActive(services[i])) return services[i];
        return null;
    }

    function item(s) {
        var ext = s.kind === 'external' || s.newTab;
        var active = isActive(s);
        return '<a class="sf-item' + (active ? ' active' : '') + '" href="' + esc(hrefOf(s)) + '"' +
            ' data-sf-id="' + esc(s.id) + '" data-scope="' + esc(s.scope) + '"' +
            (ext ? ' target="_blank" rel="noopener"' : '') +
            (active ? ' aria-current="page"' : '') +
            ' title="' + esc(s.label + (s.desc ? ' — ' + s.desc : '')) + '">' +
            icon(s.icon) + '<span class="sf-label">' + esc(s.label) + '</span>' +
            (ext ? icon('external', 'sf-ext') : '') + '</a>';
    }

    function themeButton() {
        var m = themeMode();
        var ic = m === 'light' ? 'sun' : m === 'dark' ? 'moon' : 'monitor';
        var lbl = m === 'light' ? 'Clair' : m === 'dark' ? 'Sombre' : 'Système';
        return icon(ic) + '<span class="sf-foot-label">' + lbl + '</span>';
    }

    function render() {
        var byKind = function (k) { return services.filter(function (s) { return s.kind === k; }); };
        var home = byKind('home')[0];
        var extOpen = getPref('sf_ext') !== 'closed';

        var aside = document.createElement('aside');
        aside.className = 'sf-sidebar';
        aside.id = 'sf-sidebar';
        aside.setAttribute('aria-label', 'Navigation');
        aside.innerHTML =
            '<a class="sf-brand" href="' + esc(home ? hrefOf(home) : '/') + '">' +
                '<span class="sf-mark">S</span><span class="sf-brand-name">HomeLab</span></a>' +
            '<nav class="sf-nav">' +
                (home ? item(home) : '') +
                '<div class="sf-group"><div class="sf-group-title"><span>Applications</span></div>' +
                    byKind('internal').map(item).join('') + '</div>' +
                '<details class="sf-group sf-ext-group"' + (extOpen ? ' open' : '') + '>' +
                    '<summary class="sf-group-title"><span>Services tiers</span>' +
                    '<span class="sf-group-note" hidden></span>' + icon('chevron', 'sf-chevron') + '</summary>' +
                    byKind('external').map(item).join('') + '</details>' +
            '</nav>' +
            '<div class="sf-foot">' +
                '<button type="button" class="sf-foot-btn sf-theme" title="Thème : clair, sombre ou système">' + themeButton() + '</button>' +
                '<button type="button" class="sf-foot-btn sf-collapse" title="Replier la barre">' + icon('collapse') + '</button>' +
                '<button type="button" class="sf-foot-btn sf-logout" title="Se déconnecter">' + icon('logout') + '<span class="sf-foot-label">Quitter</span></button>' +
            '</div>';

        var cur = current();
        var top = document.createElement('header');
        top.className = 'sf-topbar';
        top.innerHTML = '<button type="button" class="sf-burger" aria-label="Ouvrir la navigation" aria-controls="sf-sidebar">' +
            icon('menu') + '</button><span class="sf-mark">S</span><span>' + esc(cur ? cur.label : 'HomeLab') + '</span>';

        var scrim = document.createElement('div');
        scrim.className = 'sf-scrim';

        var body = document.body;
        body.insertBefore(scrim, body.firstChild);
        body.insertBefore(aside, body.firstChild);
        body.insertBefore(top, body.firstChild);

        wire(aside, top, scrim);
        if (html.getAttribute('data-sf-nav') === 'collapsed') forceOpen(aside, true);
        probeVpn(aside);
    }

    function forceOpen(aside, on) {
        var d = aside.querySelector('.sf-ext-group');
        if (!d) return;
        if (on) d.open = true;
        else d.open = getPref('sf_ext') !== 'closed';
    }

    function logout() {
        if (onDash) {
            fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
                .catch(function () {})
                .then(function () { location.href = '/login.html'; });
        } else {
            location.href = 'https://' + ROOT + '/login.html?logout=1';
        }
    }

    function wire(aside, top, scrim) {
        aside.querySelector('.sf-theme').addEventListener('click', function () {
            var next = { auto: 'light', light: 'dark', dark: 'auto' }[themeMode()];
            setPref('sf_theme', next);
            applyTheme();
            this.innerHTML = themeButton();
            announceTheme();
        });
        aside.querySelector('.sf-collapse').addEventListener('click', function () {
            var collapsed = html.getAttribute('data-sf-nav') === 'collapsed';
            if (collapsed) html.removeAttribute('data-sf-nav');
            else html.setAttribute('data-sf-nav', 'collapsed');
            setPref('sf_nav', collapsed ? 'expanded' : 'collapsed');
            forceOpen(aside, !collapsed);
            try { window.dispatchEvent(new Event('resize')); } catch (e) { /* graphiques */ }
        });
        aside.querySelector('.sf-logout').addEventListener('click', logout);

        var ext = aside.querySelector('.sf-ext-group');
        ext.addEventListener('toggle', function () {
            if (html.getAttribute('data-sf-nav') === 'collapsed') return;
            setPref('sf_ext', ext.open ? 'open' : 'closed');
        });

        aside.addEventListener('click', function (e) {
            var a = e.target.closest('.sf-item');
            if (a && a.classList.contains('is-unreachable')) { e.preventDefault(); return; }
            if (a) html.classList.remove('sf-drawer-open');
        });

        var burger = top.querySelector('.sf-burger');
        burger.addEventListener('click', function () {
            html.classList.add('sf-drawer-open');
            burger.setAttribute('aria-expanded', 'true');
        });
        scrim.addEventListener('click', function () {
            html.classList.remove('sf-drawer-open');
            burger.setAttribute('aria-expanded', 'false');
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') html.classList.remove('sf-drawer-open');
        });
    }

    // ── Joignabilité du VPN ─────────────────────────────────────────────────
    // Une image servie uniquement derrière Tailscale : si elle charge, les
    // services VPN sont joignables. Utile seulement hors example.com (tests locaux).
    var vpnState = null;
    var vpnWaiters = [];
    function vpnReachable(cb) {
        if (vpnState !== null) { cb(vpnState); return; }
        vpnWaiters.push(cb);
        if (vpnWaiters.length > 1) return;
        var here = services.some(function (s) { return s.scope === 'vpn' && new URL(s.url).host === location.host; });
        if (here) { done(true); return; }
        // Page publique : Chrome bloque (ou fait demander une autorisation pour) toute
        // requête vers une adresse Tailscale depuis un site public (Local Network Access).
        // On ne sonde donc pas : les liens VPN restent actifs, sans grisage.
        if (onRootDomain()) { done(true); return; }
        var img = new Image();
        var timer = setTimeout(function () { done(false); }, 2500);
        img.onload = function () { clearTimeout(timer); done(true); };
        img.onerror = function () { clearTimeout(timer); done(false); };
        img.src = VPN_PROBE + '?t=' + Date.now();
        function done(ok) {
            if (vpnState !== null) return;
            vpnState = ok;
            vpnWaiters.splice(0).forEach(function (f) { f(ok); });
        }
    }

    function probeVpn(aside) {
        vpnReachable(function (ok) {
            if (ok) return;
            aside.querySelectorAll('.sf-item[data-scope="vpn"]').forEach(function (a) {
                a.classList.add('is-unreachable');
                a.setAttribute('aria-disabled', 'true');
                a.title = a.title + ' — accessible via Tailscale uniquement';
            });
            var note = aside.querySelector('.sf-group-note');
            if (note) { note.textContent = 'VPN requis'; note.hidden = false; }
        });
    }

    window.SF = {
        services: services,
        icon: icon,
        esc: esc,
        theme: effectiveTheme,
        vpnReachable: vpnReachable,
        href: hrefOf,
        cssVar: function (name) {
            return getComputedStyle(html).getPropertyValue(name).trim();
        }
    };

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', render);
    else render();
})();
