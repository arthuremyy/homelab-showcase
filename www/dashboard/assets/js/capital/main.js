// Amorçage et routeur. Onglets : vue d'ensemble, un onglet par compte, mouvements.
// Modules ES natifs, aucun framework, aucune bibliothèque.
import { api } from './api.js';
import { since } from './fmt.js';
import { toast, fail } from './ui.js';
import { state, load } from './state.js';
import { movementForm } from './forms.js';
import * as ensemble from './views/ensemble.js';
import * as compte from './views/compte.js';
import * as mouvements from './views/mouvements.js';

const ACCOUNTS = ['PEA', 'CRYPTO', 'PEE'];
const TABS = ['ensemble', ...ACCOUNTS, 'mouvements'];
const actif = () => document.querySelector('nav.sections button[aria-selected="true"]')?.dataset.tab;
const fromHash = () => window.location.hash.replace('#/', '');
let booted = false;

function show(tab) {
    if (!TABS.includes(tab)) tab = 'ensemble';
    document.querySelectorAll('nav.sections button').forEach((b) =>
        b.setAttribute('aria-selected', String(b.dataset.tab === tab)));
    const view = ACCOUNTS.includes(tab) ? 'compte' : tab;
    document.querySelectorAll('.view').forEach((v) => v.classList.toggle('active', v.id === `view-${view}`));
    if (window.location.hash !== `#/${tab}`) history.replaceState(null, '', `${window.location.pathname}#/${tab}`);
    if (tab === 'ensemble') ensemble.render();
    else if (tab === 'mouvements') mouvements.render();
    else compte.render(tab);
}

function freshness() {
    const s = state.summary;
    document.getElementById('fresh').textContent = s?.oldest_quote_at ? `Cours ${since(s.oldest_quote_at)}` : '';
}

async function reload() {
    try { await load(); } catch (e) { fail(e); return; }
    freshness();
    show(booted ? actif() : fromHash());      // premier chargement : l'onglet de l'URL
    booted = true;
}

function wire() {
    document.querySelectorAll('nav.sections button').forEach((b) => b.addEventListener('click', () => show(b.dataset.tab)));
    document.addEventListener('click', (e) => {
        const g = e.target.closest('[data-goto]');
        if (g) show(g.dataset.goto);
    });
    window.addEventListener('hashchange', () => show(fromHash()));
    document.addEventListener('changed', reload);
    document.getElementById('add-btn').addEventListener('click', () =>
        movementForm(null, { account: ACCOUNTS.includes(actif()) ? actif() : 'PEA' }));
    document.getElementById('refresh-btn').addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        btn.disabled = true;
        try {
            const r = await api.post('/portfolio/refresh');
            toast(`${r.updated} cours mis à jour.`);
            await reload();
        } catch (err) { fail(err); } finally { btn.disabled = false; }
    });
    document.addEventListener('keydown', (e) => {
        if (e.target.matches?.('input, select, textarea') || e.metaKey || e.ctrlKey || e.altKey) return;
        if (document.getElementById('modal-host').childElementCount) return;
        const i = ['1', '2', '3', '4', '5'].indexOf(e.key);
        if (i >= 0) show(TABS[i]);
    });
    // Cours rafraîchis toutes les minutes tant que l'onglet est visible (hors formulaire ouvert).
    setInterval(async () => {
        if (document.hidden || document.getElementById('modal-host').childElementCount) return;
        try {
            await load();
            freshness();
            // Pas de rendu si le briefing ou les alertes sont dépliés : on ne referme rien sous les yeux.
            if (actif() === 'ensemble' && !document.querySelector('#view-ensemble details[open]')) ensemble.render();
        } catch { /* 401 géré par api */ }
    }, 60000);
}

[ensemble, compte, mouvements].forEach((v) => v.wire());
wire();
reload();
