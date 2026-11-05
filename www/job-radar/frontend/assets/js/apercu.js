// État global léger : l'aperçu du serveur (fraîcheur, compteurs, à faire).
// Chargé au démarrage, rafraîchi toutes les 2 minutes et après chaque action ;
// il alimente les pastilles des onglets et l'indicateur de fraîcheur.
import { api } from './api.js';
import { esc } from './fmt.js';

let dernier = null;
const abonnes = new Set();

export const courant = () => dernier;
export function abonner(fn) { abonnes.add(fn); if (dernier) fn(dernier); }

export async function charger() {
    try {
        dernier = await api.get('/overview');
        abonnes.forEach((fn) => { try { fn(dernier); } catch { /* une vue ne casse pas les autres */ } });
    } catch { /* l'indicateur reste sur sa dernière valeur */ }
    return dernier;
}

/** « il y a 12 min », « il y a 3 h », « hier à 06:19 » */
export function depuisQuand(iso) {
    if (!iso) return 'jamais';
    const d = new Date(iso);
    if (isNaN(d)) return '';
    const min = Math.round((Date.now() - d.getTime()) / 60000);
    if (min < 1) return 'à l’instant';
    if (min < 60) return `il y a ${min} min`;
    const h = Math.floor(min / 60);
    if (h < 24) return `il y a ${h} h`;
    const heure = d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
    if (h < 48) return `hier à ${heure}`;
    return d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' }) + ` à ${heure}`;
}

export function heure(iso) {
    const d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
}

/** Synthèse de fraîcheur : ok | retard | panne, avec une phrase. */
export function fraicheur(a) {
    if (!a) return { ton: '', texte: '…' };
    if (a.collecting) return { ton: 'dot-warn', texte: 'Collecte en cours…' };
    const actives = a.sources.filter((s) => s.enabled);
    const enRetard = actives.filter((s) => s.late);
    if (!a.last_collect_at) return { ton: 'dot-down', texte: 'Aucune collecte' };
    const quand = depuisQuand(a.last_collect_at);
    if (enRetard.length === actives.length) return { ton: 'dot-down', texte: `Données anciennes · ${quand}` };
    if (enRetard.length) return { ton: 'dot-warn', texte: `À jour · ${quand} · ${enRetard.length} source en retard` };
    return { ton: 'dot-ok', texte: `À jour · ${quand}` };
}

// Pastilles des onglets et indicateur de la barre de page
abonner((a) => {
    const pill = (tab, n) => {
        const el = document.querySelector(`[data-tab="${tab}"] .pill`);
        if (el) { el.textContent = n || ''; el.hidden = !n; }
    };
    pill('deck', a.counts.a_trier);
    pill('suivi', a.counts.vivier + a.counts.candidate + a.counts.entretien + a.counts.offre);
    pill('today', a.todo.reduce((n, g) => n + g.items.length, 0));
    const f = fraicheur(a);
    const el = document.getElementById('fresh');
    if (el) {
        el.innerHTML = `<span class="dot ${esc(f.ton)}"></span>${esc(f.texte)}`;
        el.title = 'Dernière collecte des offres — détail dans « Aujourd’hui »';
    }
});
