// Amorçage et routeur par onglets. Modules ES natifs, aucun framework, aucun CDN.
import { closeDrawer, isTyping } from './ui.js';
import { charger } from './apercu.js';
import * as today from './views/today.js';
import * as deck from './views/deck.js';
import * as suivi from './views/suivi.js';
import * as liste from './views/liste.js';
import * as profil from './views/profil.js';
import * as fiche from './views/fiche.js';

// L'ordre est celui des onglets (raccourcis 1 à 5).
const VUES = { today, deck, suivi, liste, profil };
const actif = () => document.querySelector('nav.sections button[aria-selected="true"]')?.dataset.tab;

function aller(onglet) {
    if (!VUES[onglet]) onglet = 'today';
    document.querySelectorAll('nav.sections button').forEach((b) =>
        b.setAttribute('aria-selected', String(b.dataset.tab === onglet)));
    document.querySelectorAll('.view').forEach((v) =>
        v.classList.toggle('active', v.id === `view-${onglet}`));
    if (window.location.hash !== `#/${onglet}`) history.replaceState(null, '', `#/${onglet}`);
    VUES[onglet].render();
}

function global() {
    document.querySelectorAll('nav.sections button').forEach((b) =>
        b.addEventListener('click', () => aller(b.dataset.tab)));

    // Délégation : ouvrir la fiche depuis n'importe quelle vue.
    document.addEventListener('click', (e) => {
        const vers = e.target.closest('[data-goto]');
        if (vers) { aller(vers.dataset.goto); return; }
        if (e.target.closest('[data-act], [data-fact], a, input, select')) return;
        const cible = e.target.closest('[data-offer]');
        if (cible) { fiche.open(cible.dataset.offer); return; }
        if (e.target.closest('[data-close]') || e.target.id === 'scrim') closeDrawer();
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeDrawer();
        if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
        const cible = e.target.closest?.('[data-offer]');
        if (e.key === 'Enter' && cible) { fiche.open(cible.dataset.offer); return; }
        const i = ['1', '2', '3', '4', '5'].indexOf(e.key);
        if (i >= 0) aller(Object.keys(VUES)[i]);
    });

    window.addEventListener('hashchange', () => {
        aller(window.location.hash.replace('#/', '') || 'today');
    });

    // Après chaque action : compteurs et vue courante à jour.
    document.addEventListener('offer-updated', () => {
        charger();
        const v = actif();
        if (VUES[v] && v !== 'deck') VUES[v].render();
    });

    // Fraîcheur et compteurs, sans recharger la page
    setInterval(() => { if (!document.hidden) charger(); }, 120000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) charger(); });
}

// Compatibilité des anciens liens (#/suivi gardé, #/vivier etc. → candidatures)
const ANCIENS = { vivier: 'suivi', todo: 'today' };
today.wire();
deck.wire();
suivi.wire();
liste.wire();
global();
charger();
const h = window.location.hash.replace('#/', '');
aller(ANCIENS[h] || h || 'today');
