// Toutes les offres : explorer, rechercher, retrouver une annonce.
// Chaque ligne dit quand l'offre a été publiée et où j'en suis avec elle.
import { api } from '../api.js';
import { esc, ilYA, experienceCourte, salaireCourt, titre, ville, CONTRAT, SOURCE } from '../fmt.js';
import { debounce } from '../ui.js';
import { LIBELLE, TON } from '../statuts.js';

const filtres = {
    q: '', sort: 'match', tracks: [], statuses: [], min_match: 0, max_age_days: null,
    hide_lock_in: true, include_inactive: false, limit: 100, offset: 0,
};

function entree(o) {
    const sous = [o.company, ville(o.location), CONTRAT[o.contract_type], SOURCE[o.source]].filter(Boolean);
    const sal = salaireCourt(o);
    const xp = experienceCourte(o);
    const statut = o.status && o.status !== 'nouveau'
        ? `<span class="badge ${esc(TON[o.status] || '')}">${esc(LIBELLE[o.status])}</span>` : '';
    const retiree = o.is_active === 0 ? '<span class="badge badge-danger">Retirée</span>' : '';
    return `<li class="entry" data-offer="${esc(o.id)}" tabindex="0">
        <div>
            <div class="entry-title">${esc(titre(o.title))} ${statut} ${retiree}</div>
            <div class="entry-sub">${sous.map((m, i) =>
                (i === 0 ? esc(m) : `<span class="dim">${esc(m)}</span>`)).join(' · ')}</div>
        </div>
        <div class="entry-cell dim">${esc(ilYA(o.posted_at) || '—')}</div>
        <div class="entry-cell${sal ? '' : ' dim'}">${esc(sal || '—')}</div>
        <div class="entry-cell${xp ? '' : ' dim'}">${esc(xp || '—')}</div>
        <div class="entry-score">${o.match_score == null ? '—' : esc(o.match_score)}</div>
    </li>`;
}

const ENTETE = `<li class="entries-head label" aria-hidden="true">
    <span>Intitulé</span><span>Publiée</span><span>Salaire</span><span>Expérience</span><span>Pertinence</span></li>`;

let affichees = [];

export async function render({ suite = false } = {}) {
    const ul = document.getElementById('entries');
    const total = document.getElementById('l-total');
    if (!suite) { filtres.offset = 0; affichees = []; }
    if (!ul.innerHTML) ul.innerHTML = '<li class="blank">Chargement…</li>';
    let d;
    try { d = await api.post('/list', filtres); }
    catch (e) { ul.innerHTML = `<li class="blank">${esc(e.message)}</li>`; return; }
    affichees = affichees.concat(d.items || []);
    total.textContent = `${d.total} offre${d.total > 1 ? 's' : ''}`;
    const reste = d.total - affichees.length;
    ul.innerHTML = affichees.length
        ? ENTETE + affichees.map(entree).join('')
          + (reste > 0 ? `<li class="entries-more"><button class="btn btn-sm" id="l-more">
              Afficher ${Math.min(reste, filtres.limit)} de plus (${reste} restantes)</button></li>` : '')
        : `<li class="blank"><strong>Aucune offre</strong>
             <p>Rien ne correspond. Élargis la période, le statut, ou décoche « Masquer l’OT ».</p></li>`;
}

export function wire() {
    const relance = debounce(render);
    const on = (id, ev, fn) => document.getElementById(id).addEventListener(ev, fn);
    on('q', 'input', (e) => { filtres.q = e.target.value.trim(); relance(); });
    on('tri', 'change', (e) => { filtres.sort = e.target.value; render(); });
    on('famille', 'change', (e) => { filtres.tracks = e.target.value ? [e.target.value] : []; render(); });
    on('l-statut', 'change', (e) => {
        const v = e.target.value;
        filtres.statuses = v === 'closes' ? ['refuse', 'sans_reponse', 'decline'] : v ? [v] : [];
        render();
    });
    on('l-age', 'change', (e) => { filtres.max_age_days = Number(e.target.value) || null; render(); });
    on('l-ot', 'change', (e) => { filtres.hide_lock_in = e.target.checked; render(); });
    on('l-retirees', 'change', (e) => { filtres.include_inactive = e.target.checked; render(); });
    on('entries', 'click', (e) => {
        if (!e.target.closest('#l-more')) return;
        filtres.offset = affichees.length;
        render({ suite: true });
    });
}
