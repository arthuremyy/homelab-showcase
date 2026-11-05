// Fiche complète dans un tiroir latéral, ouverte depuis n'importe quelle vue.
// En tête : où j'en suis avec cette offre, et les prochaines actions possibles.
import { api } from '../api.js';
import { esc } from '../fmt.js';
import { openDrawer, closeDrawer, note } from '../ui.js';
import { renderSheet, lienOffre } from './sheet.js';
import { agir } from '../agir.js';
import { LIBELLE, TON, suite, etatSuivi } from '../statuts.js';

export async function open(id) {
    openDrawer('<p class="blank">Chargement…</p>');
    let o;
    try { ({ offer: o } = await api.get(`/offer/${encodeURIComponent(id)}`)); }
    catch (e) { openDrawer(`<p class="blank">${esc(e.message)}</p>`); return; }

    const e = etatSuivi(o);
    const actions = suite(o).map(([act, lib], i) =>
        `<button class="btn btn-sm ${i === 0 ? 'btn-primary' : ''}" data-fact="${esc(act)}">${esc(lib)}</button>`).join('');
    const toutes = Object.entries(LIBELLE).filter(([k]) => k !== o.status)
        .map(([k, l]) => `<option value="${esc(k)}">${esc(l)}</option>`).join('');

    openDrawer(`
        <div class="drawer-top">
            <a class="btn btn-sm" href="${lienOffre(o)}" target="_blank" rel="noopener noreferrer">Voir l’annonce ↗</a>
            <button class="btn btn-sm btn-ghost" data-close>Fermer</button>
        </div>
        <div class="fiche-status">
            <div class="fiche-status-line">
                <span class="badge ${esc(TON[o.status] || '')}">${esc(LIBELLE[o.status] || o.status)}</span>
                ${e.texte ? `<span class="text-3">${esc(e.texte)}</span>` : ''}
                ${e.alerte ? `<span class="badge ${esc(e.ton)}">${esc(e.alerte)}</span>` : ''}
            </div>
            <div class="fiche-actions" id="fiche-actions">${actions}
                <select class="select input-sm fiche-move" aria-label="Déplacer vers une autre étape">
                    <option value="">Autre étape…</option>${toutes}</select>
            </div>
        </div>
        ${renderSheet(o, { open: true })}`);

    const zone = document.getElementById('fiche-actions');
    const faire = async (act) => {
        try { await agir(o.id, act); closeDrawer(); }
        catch (err) { note(err.message); }
    };
    zone.addEventListener('click', (ev) => {
        const b = ev.target.closest('[data-fact]');
        if (b) faire(b.dataset.fact);
    });
    zone.querySelector('.fiche-move').addEventListener('change', (ev) => {
        if (ev.target.value) faire(ev.target.value);
    });
}
