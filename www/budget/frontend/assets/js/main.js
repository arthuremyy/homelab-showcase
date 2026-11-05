// Amorçage et routeur par onglets. Modules ES natifs, aucun framework, aucun CDN.
import { api } from './api.js';
import { since } from './fmt.js';
import { toast, fail } from './ui.js';
import * as mois from './views/mois.js';
import * as operations from './views/operations.js';
import * as fixes from './views/fixes.js';
import * as reglages from './views/reglages.js';

// L'ordre est celui des onglets (raccourcis 1 à 4).
const VUES = { mois, operations, fixes, reglages };
const actif = () => document.querySelector('nav.sections button[aria-selected="true"]')?.dataset.tab;

function aller(onglet) {
    if (!VUES[onglet]) onglet = 'mois';
    document.querySelectorAll('nav.sections button').forEach((b) =>
        b.setAttribute('aria-selected', String(b.dataset.tab === onglet)));
    document.querySelectorAll('.view').forEach((v) =>
        v.classList.toggle('active', v.id === `view-${onglet}`));
    if (window.location.hash !== `#/${onglet}`) history.replaceState(null, '', `${window.location.pathname}#/${onglet}`);
    VUES[onglet].render();
}

function fraicheur(bank) {
    const f = document.getElementById('fresh');
    f.textContent = bank.configured ? `Banque ${since(bank.last_ok)}` : '';
    f.title = bank.last_error ? `Dernière erreur : ${bank.last_error}` : '';
}

async function synchroniser(btn) {
    btn.disabled = true;
    btn.classList.add('spin');
    try {
        const r = await api.post('/bank/sync');
        toast(r.new ? `${r.new} nouvelle(s) opération(s).` : 'Déjà à jour.');
        VUES[actif()].render();
    } catch (e) { fail(e); }
    finally { btn.disabled = false; btn.classList.remove('spin'); }
}

function global() {
    document.querySelectorAll('nav.sections button').forEach((b) =>
        b.addEventListener('click', () => aller(b.dataset.tab)));
    document.addEventListener('click', (e) => {
        const g = e.target.closest('[data-goto]');
        if (g) aller(g.dataset.goto);
    });
    document.addEventListener('goto', (e) => aller(e.detail));
    document.addEventListener('overview', (e) => {
        fraicheur(e.detail.bank);
        const pill = document.getElementById('sugg-pill');
        pill.hidden = !e.detail.suggestions;
        pill.textContent = e.detail.suggestions || '';
    });
    document.getElementById('sync-btn').addEventListener('click', (e) => synchroniser(e.currentTarget));
    document.addEventListener('keydown', (e) => {
        if (e.target.matches?.('input, select, textarea') || e.metaKey || e.ctrlKey || e.altKey) return;
        if (document.getElementById('modal-host').childElementCount) return;
        const i = ['1', '2', '3', '4'].indexOf(e.key);
        if (i >= 0) aller(Object.keys(VUES)[i]);
    });
    window.addEventListener('hashchange', () => aller(window.location.hash.replace('#/', '')));
}

// Retour de la banque (?bank=ok|error) : message, puis URL nettoyée.
const retour = new URLSearchParams(window.location.search).get('bank');
if (retour) {
    toast(retour === 'ok' ? 'Banque reliée, opérations importées.' : 'La connexion à la banque n’a pas abouti.',
          { error: retour !== 'ok', ms: 8000 });
}

Object.values(VUES).forEach((v) => v.wire());
global();
aller(window.location.hash.replace('#/', '') || 'mois');
if (actif() !== 'mois') api.post('/overview', {}).then((d) => fraicheur(d.bank)).catch(() => {});
