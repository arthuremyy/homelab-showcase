// Rendu d'une offre. Partagé par le deck et le tiroir : une offre s'affiche
// exactement pareil partout.
//
// Règle de composition : la FACE AVANT ne porte que le socle — intitulé,
// entreprise, ville, salaire, expérience, contrat. Six informations, de quoi
// trancher en trois secondes. Tout le reste (indices, raisons, alertes,
// description) vit dans le dépliant.
import {
    esc, safeUrl, dateFr, ilYA, joursDepuis, experienceCourte, titre, ville,
    TRACK, CONTRAT, TELETRAVAIL, SOURCE,
} from '../fmt.js';

function fait(cle, valeur) {
    const vide = !valeur;
    return `<div>
        <dt class="label">${esc(cle)}</dt>
        <dd${vide ? ' class="absent"' : ''}>${esc(vide ? 'non communiqué' : valeur)}</dd>
    </div>`;
}

function jauge(nom, valeur, accent = false) {
    const v = Math.max(0, Math.min(100, valeur ?? 0));
    return `<div class="gauge">
        <span class="label">${esc(nom)}</span>
        <span class="track${accent ? ' is-accent' : ''}"><i style="width:${v}%"></i></span>
        <span class="score num">${valeur == null ? '—' : esc(valeur)}<small> /100</small></span>
    </div>`;
}

/** Les n motifs les plus lourds d'un côté donné. */
function motifs(liste, signe, n) {
    return (Array.isArray(liste) ? liste : [])
        .filter((b) => b.label !== 'Base' && (signe > 0 ? b.delta > 0 : b.delta < 0))
        .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
        .slice(0, n);
}

function listeMotifs(items, classe) {
    if (!items.length) return '';
    return `<ul class="reasons">${items.map((b) => `<li class="${classe}">
        <span class="d">${b.delta > 0 ? '+' : ''}${esc(b.delta)}</span>
        <span>${esc(b.label)}</span></li>`).join('')}</ul>`;
}

function detailComplet(titre, items) {
    const l = (Array.isArray(items) ? items : []).map((b) => {
        const d = Number(b.delta) || 0;
        return `<li class="${d > 0 ? 'pos' : d < 0 ? 'neg' : ''}">
            <span class="d">${d > 0 ? '+' : ''}${esc(d)}</span>
            <span>${esc(b.label)}</span></li>`;
    }).join('');
    return `<p class="section-title">${esc(titre)}</p><ul class="reasons">${l || '<li><span></span><span>—</span></li>'}</ul>`;
}

/** Publiée quand, et toujours en ligne ? — la question « est-ce à jour » au niveau de l'offre. */
function fraicheurOffre(o) {
    const morceaux = [];
    if (o.posted_at) morceaux.push(`publiée ${ilYA(o.posted_at)}`);
    if (o.is_active === 0) {
        morceaux.push(`<span class="badge badge-danger">Annonce retirée</span>`);
    } else if (o.last_seen_at) {
        const h = Math.round((Date.now() - new Date(o.last_seen_at).getTime()) / 3600000);
        morceaux.push(h < 1 ? 'vérifiée en ligne il y a moins d’une heure'
            : h < 48 ? `vérifiée en ligne il y a ${h} h` : `vérifiée en ligne ${ilYA(o.last_seen_at)}`);
    }
    return morceaux.length ? `<p class="sheet-fresh">${morceaux.join(' · ')}</p>` : '';
}

export function renderSheet(o, { open = false } = {}) {
    const lieu = ville(o.location);
    const byline = [o.company, lieu].filter(Boolean)
        .map((x) => esc(x)).join('<span class="sep">·</span>');

    const jours = joursDepuis(o.posted_at);
    const alertes = [];
    if (o.lock_in_flag) alertes.push(`<div class="notice">
        <b>Ce poste te ramène vers l’automatisme et l’OT industriel.</b>
        Il peut coller à ton expérience tout en refermant tes options à trois ou cinq ans.</div>`);
    if (o.below_floor) alertes.push(`<div class="notice">
        <b>Le haut de fourchette passe sous ton plancher.</b>
        À ce niveau tu es payé comme un technicien, pas comme un ingénieur.</div>`);
    if (o.few_candidates) alertes.push(`<div class="notice">
        <b>La source signale peu de candidatures.</b> C’est un signal rare, et il joue pour toi.</div>`);

    const positifs = motifs(o.match_breakdown, 1, 3);
    const negatifs = [...motifs(o.match_breakdown, -1, 2), ...motifs(o.success_breakdown, -1, 2)]
        .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta)).slice(0, 3);

    // Aucune source n'expose de date limite ni de date de début de mission :
    // on n'affiche que ce qui existe réellement.
    const publiee = o.posted_at ? `${dateFr(o.posted_at)} — ${ilYA(o.posted_at)}` : null;
    const secondaires = [
        ['Publiée', publiee],
        ['Télétravail', TELETRAVAIL[o.remote]],
        ['Temps de travail', o.work_time],
        ['Effectif', o.company_size],
        ['Secteur', o.sector],
        ['Statut', o.qualification],
        ['Déplacements', o.travel],
        ['Postes', o.n_positions > 1 ? `${o.n_positions} à pourvoir` : null],
        ['Source', SOURCE[o.source] || o.source],
        ['Famille', TRACK[o.track]],
    ].filter(([, v]) => v);

    return `<article class="sheet" data-sheet="${esc(o.id)}">
        <h2>${esc(titre(o.title))}</h2>
        ${byline ? `<p class="byline">${byline}</p>` : ''}
        ${fraicheurOffre(o)}

        <dl class="facts">
            ${fait('Salaire', o.salary_raw)}
            ${fait('Expérience', experienceCourte(o))}
            ${fait('Contrat', o.contract_detail || CONTRAT[o.contract_type])}
        </dl>

        <details class="fold"${open ? ' open' : ''}>
            <summary>Détail</summary>
            <div class="fold-body">
                ${alertes.join('')}

                <div class="gauges">
                    ${jauge('Pertinence', o.match_score, true)}
                    ${jauge('Ouverture', o.portability_score)}
                    ${jauge('Chances', o.success_score)}
                </div>
                <p class="hint sheet-hint">
                    <b>Pertinence</b> : adéquation à ton profil et à ton objectif.
                    <b>Ouverture</b> : ce poste élargit-il tes options à 3–5 ans.
                    <b>Chances</b> : estimation explicable, pas une prédiction.
                </p>

                ${positifs.length ? `<p class="section-title">Ce qui joue pour toi</p>
                    ${listeMotifs(positifs, 'pos')}` : ''}
                ${negatifs.length ? `<p class="section-title">Points de vigilance</p>
                    ${listeMotifs(negatifs, 'neg')}` : ''}

                ${secondaires.length ? `<p class="section-title">Informations</p>
                    <dl class="facts">${secondaires.map(([k, v]) => fait(k, v)).join('')}</dl>` : ''}

                ${Array.isArray(o.skills) && o.skills.length ? `<p class="section-title">Compétences attendues</p>
                    <div class="chips">${o.skills.map((s) => `<span class="chip">${esc(s)}</span>`).join('')}</div>` : ''}

                ${o.company_desc ? `<p class="section-title">L’entreprise</p>
                    <p class="prose">${esc(o.company_desc)}</p>` : ''}

                ${o.description ? `<p class="section-title">L’annonce</p>
                    <p class="prose">${esc(o.description)}</p>` : ''}

                ${detailComplet('Détail de la pertinence', o.match_breakdown)}
                ${detailComplet('Détail de l’ouverture', o.portability_breakdown)}
                ${detailComplet('Détail des chances', o.success_breakdown)}
            </div>
        </details>
    </article>`;
}

export const lienOffre = (o) => safeUrl(o.url);
