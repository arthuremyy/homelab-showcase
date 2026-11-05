// Candidatures : un tableau par étape (À postuler → Postulé → Entretiens → Offres).
//
// Chaque carte dit où en est la candidature (« postulé il y a 12 j — relance due »)
// et porte l'action suivante en un clic. Plus de liste déroulante d'étapes ni de
// sous-onglets : on voit tout le parcours d'un coup d'œil.
import { api } from '../api.js';
import { esc, titre, ville, salaireCourt } from '../fmt.js';
import { boutons, brancher } from '../agir.js';
import { COLONNES, CLOSES, LIBELLE, etatSuivi, enLigne } from '../statuts.js';

const box = () => document.getElementById('board');
let voirClos = false;

function carte(o) {
    const e = etatSuivi(o);
    const l = enLigne(o);
    const meta = [o.company, ville(o.location), salaireCourt(o)].filter(Boolean).map(esc).join(' · ');
    return `<li class="bcard${e.alerte ? ' is-due' : ''}">
        <div class="bcard-main" data-offer="${esc(o.id)}" tabindex="0">
            <div class="row-title">${esc(titre(o.title))}</div>
            <div class="row-sub">${meta}</div>
            <div class="bcard-state">
                ${e.texte ? `<span class="text-3">${esc(e.texte)}</span>` : ''}
                ${e.alerte ? `<span class="badge ${esc(e.ton)}">${esc(e.alerte)}</span>` : ''}
                ${!l.ok ? `<span class="badge badge-danger" title="${esc(l.detail)}">${esc(l.texte)}</span>` : ''}
            </div>
        </div>
        <div class="bcard-actions">${boutons(o, { max: 2 })}</div>
    </li>`;
}

const VISIBLES = 8;           // au-delà, la colonne se replie
const deplies = new Set();

function colonne(c, items) {
    // Ce qui demande une action remonte en tête, puis la plus pertinente
    items.sort((a, b) => Number(!!etatSuivi(b).alerte) - Number(!!etatSuivi(a).alerte)
        || (b.match_score ?? 0) - (a.match_score ?? 0));
    const tout = deplies.has(c.cle) || items.length <= VISIBLES + 2;
    const montres = tout ? items : items.slice(0, VISIBLES);
    return `<section class="bcol">
        <header class="bcol-head">
            <span class="bcol-title">${esc(c.titre)}</span><span class="badge">${esc(items.length)}</span>
            <p class="bcol-help">${esc(c.aide)}</p>
        </header>
        ${items.length ? `<ul class="bcol-list">${montres.map(carte).join('')}</ul>`
            : '<p class="bcol-empty">Rien ici pour l’instant.</p>'}
        ${tout ? '' : `<button class="btn btn-sm btn-ghost btn-block bcol-more" data-more="${esc(c.cle)}">
            Voir les ${esc(items.length - VISIBLES)} autres</button>`}
    </section>`;
}

function clos(items) {
    if (!items.length) return '';
    return `<section class="card closed">
        <button class="closed-toggle" id="toggle-clos" aria-expanded="${voirClos}">
            Candidatures terminées <span class="badge">${esc(items.length)}</span>
            <span class="text-3">refus, sans réponse, abandons</span></button>
        ${voirClos ? `<ul class="row-list">${items.map((o) => `<li class="row-item">
            <div class="row-main" data-offer="${esc(o.id)}" tabindex="0">
                <div class="row-title">${esc(titre(o.title))}</div>
                <div class="row-sub">${esc([o.company, ville(o.location)].filter(Boolean).join(' · '))}</div>
            </div>
            <span class="badge">${esc(LIBELLE[o.status])}</span>
            <div class="row-actions">${boutons(o, { max: 1 })}</div>
        </li>`).join('')}</ul>` : ''}
    </section>`;
}

export async function render() {
    if (!box().innerHTML) box().innerHTML = '<p class="blank">Chargement…</p>';
    let items;
    try {
        ({ items } = await api.post('/list', {
            statuses: [...COLONNES.map((c) => c.cle), ...CLOSES],
            include_inactive: true, hide_lock_in: false, min_match: 0, limit: 500, sort: 'date',
        }));
    } catch (e) { box().innerHTML = `<p class="blank">${esc(e.message)}</p>`; return; }

    const par = (k) => items.filter((o) => o.status === k);
    const enCours = COLONNES.reduce((n, c) => n + par(c.cle).length, 0);
    box().innerHTML = `
        ${enCours ? '' : `<div class="notice">Aucune candidature en cours. Garde des offres
            depuis <a href="#/deck">À trier</a> : elles arrivent ici dans « À postuler ».</div>`}
        <div class="board">${COLONNES.map((c) => colonne(c, par(c.cle))).join('')}</div>
        ${clos(items.filter((o) => CLOSES.includes(o.status)))}`;
}

export function wire() {
    brancher(box());
    box().addEventListener('click', (e) => {
        if (e.target.closest('#toggle-clos')) { voirClos = !voirClos; render(); }
        const m = e.target.closest('[data-more]');
        if (m) { deplies.add(m.dataset.more); render(); }
    });
}
