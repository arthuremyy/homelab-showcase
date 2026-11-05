// « Aujourd'hui » : la page d'arrivée. Elle répond, dans cet ordre, à :
//   1. mes données sont-elles à jour ?
//   2. qu'est-ce que je dois faire aujourd'hui ?
//   3. qu'est-ce qui est arrivé de nouveau et mérite un coup d'œil ?
import { api } from '../api.js';
import { esc, titre, ville, salaireCourt, experienceCourte, CONTRAT, SOURCE } from '../fmt.js';
import { note } from '../ui.js';
import { charger, courant, depuisQuand, heure, fraicheur } from '../apercu.js';
import { boutons, brancher } from '../agir.js';
import { etatSuivi, enLigne } from '../statuts.js';

const box = () => document.getElementById('today');
let suivi = null;            // minuterie pendant une collecte manuelle

function blocFraicheur(a) {
    const f = fraicheur(a);
    const lignes = a.sources.map((s) => {
        const etat = !s.enabled ? '<span class="badge">Non configurée</span>'
            : s.running ? '<span class="badge badge-warning">En cours</span>'
            : s.late ? '<span class="badge badge-danger">En retard</span>'
            : '<span class="badge badge-success">OK</span>';
        const rythme = s.cadence_hours >= 24 ? '1 fois par jour' : `toutes les ${s.cadence_hours} h`;
        return `<tr>
            <td>${esc(SOURCE[s.source] || s.source)}</td>
            <td>${etat}</td>
            <td class="num">${s.last_ok_at ? esc(depuisQuand(s.last_ok_at)) : '—'}</td>
            <td class="num hide-sm">${esc(s.active)} en ligne</td>
            <td class="num hide-sm">${s.created ? `+${esc(s.created)} nouvelles` : '—'}</td>
            <td class="text-3 hide-sm">${esc(rythme)}</td>
        </tr>`;
    }).join('');
    return `<section class="card fresh-card">
        <div class="card-header">
            <span class="card-title"><span class="dot ${esc(f.ton)}"></span> ${esc(f.texte)}</span>
            <div class="card-actions">
                ${a.next_collect_at && !a.collecting ? `<span class="text-3 fresh-next">Prochaine vers ${esc(heure(a.next_collect_at))}</span>` : ''}
                <button class="btn btn-sm" id="collect" ${a.collecting ? 'disabled' : ''}>
                    ${a.collecting ? 'Collecte en cours…' : 'Actualiser maintenant'}</button>
            </div>
        </div>
        <details class="fresh-detail">
            <summary>Détail par source</summary>
            <div class="table-wrap"><table class="table">
                <thead><tr><th>Source</th><th>État</th><th class="num">Dernière collecte</th>
                    <th class="num hide-sm">Annonces</th><th class="num hide-sm">Dernière passe</th><th class="hide-sm">Rythme</th></tr></thead>
                <tbody>${lignes}</tbody>
            </table></div>
            <p class="hint">France Travail : chaque annonce est revérifiée à chaque collecte et à
                l’ouverture de sa fiche. Adzuna et Jooble : « retirée » après 3 collectes
                sans la revoir. Toute annonce non confirmée depuis 72 h est retirée.</p>
        </details>
    </section>`;
}

function entonnoir(c) {
    const etapes = [
        ['deck', 'À trier', c.a_trier, `${c.nouvelles_24h} nouvelles en 24 h`],
        ['suivi', 'À postuler', c.vivier, 'gardées au tri'],
        ['suivi', 'Postulé', c.candidate, 'en attente de réponse'],
        ['suivi', 'Entretiens', c.entretien, 'process en cours'],
        ['suivi', 'Offres', c.offre, 'propositions reçues'],
    ];
    return `<section class="funnel">${etapes.map(([tab, lib, n, sous]) => `
        <button class="kpi funnel-step" data-goto="${tab}">
            <span class="kpi-label">${esc(lib)}</span>
            <span class="kpi-value">${esc(n)}</span>
            <span class="kpi-sub">${esc(sous)}</span>
        </button>`).join('')}</section>`;
}

function ligneOffre(o, { avecEtat = true } = {}) {
    const meta = [o.company, ville(o.location)].filter(Boolean).map(esc).join(' · ');
    const e = avecEtat ? etatSuivi(o) : { texte: '' };
    const l = enLigne(o);
    return `<li class="row-item">
        <div class="row-main" data-offer="${esc(o.id)}" tabindex="0">
            <div class="row-title">${esc(titre(o.title))}</div>
            <div class="row-sub">${meta}${e.texte ? ` · <span class="text-3">${esc(e.texte)}</span>` : ''}
                ${e.alerte ? `<span class="badge ${esc(e.ton)}">${esc(e.alerte)}</span>` : ''}
                ${!l.ok ? `<span class="badge badge-danger">${esc(l.texte)}</span>` : ''}</div>
        </div>
        <div class="row-actions">${boutons(o, { max: 2 })}</div>
    </li>`;
}

function aFaire(groupes) {
    if (!groupes.length) {
        return `<section class="card"><div class="empty"><strong>Rien d’urgent</strong>
            Aucune relance due, aucun entretien en cours, aucune annonce gardée qui attend.
            <br><button class="btn btn-sm" data-goto="deck">Trier des offres</button></div></section>`;
    }
    // 3 lignes par groupe : la page d'accueil donne la direction, le détail est
    // dans Candidatures.
    const MAX = 3;
    return groupes.map((g) => `<section class="card todo-card">
        <div class="card-header"><span class="card-title">${esc(g.label)}</span>
            <span class="badge">${esc(g.items.length)}</span></div>
        <ul class="row-list">${g.items.slice(0, MAX).map((o) => ligneOffre(o)).join('')}</ul>
        ${g.items.length > MAX ? `<div class="card-foot"><button class="btn btn-sm btn-ghost" data-goto="suivi">
            Voir les ${esc(g.items.length)} dans Candidatures</button></div>` : ''}
    </section>`).join('');
}

function nouveautes(items) {
    if (!items.length) {
        return `<div class="empty">Aucune nouvelle offre très pertinente ces 3 derniers jours.</div>`;
    }
    return `<ul class="row-list">${items.map((o) => {
        const meta = [o.company, ville(o.location), CONTRAT[o.contract_type], salaireCourt(o),
            experienceCourte(o)].filter(Boolean).map(esc).join(' · ');
        return `<li class="row-item">
            <span class="score-pill" title="Pertinence">${esc(o.match_score)}</span>
            <div class="row-main" data-offer="${esc(o.id)}" tabindex="0">
                <div class="row-title">${esc(titre(o.title))}</div>
                <div class="row-sub">${meta} · <span class="text-3">arrivée ${esc(depuisQuand(o.first_seen_at))}</span></div>
            </div>
            <div class="row-actions">${boutons({ ...o, status: 'nouveau' }, { max: 2 })}</div>
        </li>`;
    }).join('')}</ul>`;
}

function peindre(a) {
    box().innerHTML = `
        ${blocFraicheur(a)}
        ${entonnoir(a.counts)}
        <div class="today-grid">
            <div class="today-col">
                <h2 class="today-h">À faire</h2>
                ${aFaire(a.todo)}
            </div>
            <div class="today-col">
                <h2 class="today-h">Nouveautés pertinentes <span class="text-3">· 3 derniers jours</span></h2>
                <section class="card">${nouveautes(a.nouveautes)}
                    <div class="card-foot"><button class="btn btn-sm btn-ghost" data-goto="deck">
                        Tout trier (${esc(a.counts.a_trier)})</button></div>
                </section>
            </div>
        </div>`;
}

async function lancerCollecte(b) {
    b.disabled = true;
    b.textContent = 'Collecte en cours…';
    const avant = courant()?.counts?.nouvelles_24h ?? 0;
    try { await api.post('/collect', {}); }
    catch (e) { note(e.message); b.disabled = false; return; }
    clearInterval(suivi);
    let tours = 0;
    suivi = setInterval(async () => {
        tours += 1;
        const a = await charger();
        if (a && (!a.collecting || tours > 45)) {
            clearInterval(suivi);
            const n = Math.max(0, (a.counts.nouvelles_24h || 0) - avant);
            note(n ? `Collecte terminée : ${n} nouvelle(s) offre(s)` : 'Collecte terminée : rien de nouveau');
            if (document.getElementById('view-today').classList.contains('active')) peindre(a);
        }
    }, 4000);
}

export async function render() {
    if (!box().innerHTML) box().innerHTML = '<p class="blank">Chargement…</p>';
    const a = await charger();
    if (!a) { box().innerHTML = '<p class="blank">Impossible de charger l’aperçu.</p>'; return; }
    peindre(a);
}

export function wire() {
    brancher(box());
    box().addEventListener('click', (e) => {
        const b = e.target.closest('#collect');
        if (b) lancerCollecte(b);
    });
}
