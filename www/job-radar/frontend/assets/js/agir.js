// Applique une action de suivi (bouton contextuel) puis prévient les vues.
import { api } from './api.js';
import { esc } from './fmt.js';
import { note } from './ui.js';
import { CONFIRMATION, suite } from './statuts.js';

export async function agir(offerId, action) {
    if (action === '@followup') await api.post('/followup', { offer_id: Number(offerId) });
    else await api.post('/status', { offer_id: Number(offerId), status: action });
    note(CONFIRMATION[action] || 'Enregistré');
    document.dispatchEvent(new CustomEvent('offer-updated'));
}

/** Boutons des prochaines actions. `max` limite le nombre affiché (les autres
 *  restent accessibles depuis la fiche). */
export function boutons(o, { max = 3, taille = 'btn-sm' } = {}) {
    return suite(o).slice(0, max).map(([act, lib], i) =>
        `<button class="btn ${taille} ${i === 0 ? 'btn-primary' : ''}" data-act="${esc(act)}" data-id="${esc(o.id)}">${esc(lib)}</button>`
    ).join('');
}

/** Délégation : un seul écouteur par conteneur pour tous les boutons [data-act]. */
export function brancher(zone) {
    zone.addEventListener('click', async (e) => {
        const b = e.target.closest('[data-act]');
        if (!b || !zone.contains(b)) return;
        e.stopPropagation();
        b.disabled = true;
        try { await agir(b.dataset.id, b.dataset.act); }
        catch (err) { note(err.message); b.disabled = false; }
    });
}
