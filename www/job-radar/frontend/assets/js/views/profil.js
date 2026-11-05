// Réglages : qui je suis (oriente la pertinence), ce que je veux voir, comment
// être prévenu, et d'où viennent les offres.
import { api } from '../api.js';
import { esc, SOURCE } from '../fmt.js';
import { note } from '../ui.js';
import { courant, depuisQuand } from '../apercu.js';

const SECTIONS = [
    {
        titre: 'Mon profil',
        aide: 'Sert à calculer la pertinence de chaque offre. Modifier puis enregistrer recalcule tous les scores.',
        champs: [
            ['goal', 'Objectif de carrière', 'zone', ''],
            ['experience', 'Expérience', 'zone', ''],
            ['diploma', 'Diplôme visé', 'ligne', ''],
            ['prior_diploma', 'Diplôme précédent', 'ligne', ''],
            ['graduation', 'Fin d’études (AAAA-MM-JJ)', 'ligne', ''],
            ['xp_years', 'Années d’expérience', 'ligne', ''],
            ['geo', 'Zone géographique', 'ligne', ''],
            ['salary_floor', 'Salaire plancher (brut annuel, €)', 'ligne',
                'Une offre dont le haut de fourchette est en dessous perd des points. Une offre sans salaire affiché n’est jamais pénalisée.'],
        ],
    },
    {
        titre: 'Tri',
        champs: [
            ['hide_ot', 'Masquer les postes OT et automatisme', 'bool',
                'Ils te ramènent vers l’industrie. Ils restent visibles dans « Toutes les offres ».'],
        ],
    },
    {
        titre: 'Notifications Discord',
        champs: [
            ['alert_min', 'Alerte immédiate à partir de la pertinence', 'ligne',
                'Une offre nouvelle au-dessus de ce score est envoyée aussitôt (jamais pour les postes OT).'],
            ['digest_hour', 'Heure du point quotidien (HH:MM)', 'ligne',
                'Envoyé seulement s’il y a quelque chose à dire.'],
            ['discord_webhook', 'Webhook Discord', 'ligne', 'Vide : salon #news-job du serveur.'],
        ],
    },
];

function champ([cle, libelle, type, aide], p) {
    const id = `p-${esc(cle)}`;
    const input = type === 'zone'
        ? `<textarea id="${id}" class="textarea" rows="3" data-key="${esc(cle)}">${esc(p[cle] || '')}</textarea>`
        : type === 'bool'
        ? `<input type="checkbox" id="${id}" data-key="${esc(cle)}" data-bool ${p[cle] !== '0' ? 'checked' : ''}>`
        : `<input id="${id}" class="input" data-key="${esc(cle)}" value="${esc(p[cle] || '')}">`;
    if (type === 'bool') {
        return `<div class="field"><label class="field-inline" for="${id}">${input} ${esc(libelle)}</label>
            ${aide ? `<span class="hint">${esc(aide)}</span>` : ''}</div>`;
    }
    return `<div class="field"><label for="${id}">${esc(libelle)}</label>${input}
        ${aide ? `<span class="hint">${esc(aide)}</span>` : ''}</div>`;
}

function sources(queries) {
    const a = courant();
    const etat = (src) => a?.sources.find((s) => s.source === src);
    const parSource = {};
    queries.forEach((q) => { (parSource[q.source] ||= []).push(q); });
    return Object.entries(parSource).map(([src, qs]) => {
        const s = etat(src);
        const resume = !s ? '' : !s.enabled ? 'non configurée (clés absentes)'
            : `dernière collecte ${depuisQuand(s.last_ok_at)} · ${s.active} annonces en ligne`;
        return `<div class="src-block">
            <div class="src-head"><strong>${esc(SOURCE[src] || src)}</strong>
                <span class="text-3">${esc(resume)}</span></div>
            <ul class="src-list">${qs.map((q) => `<li><label class="field-inline">
                <input type="checkbox" data-query="${esc(q.id)}" ${q.enabled ? 'checked' : ''}> ${esc(q.label)}</label></li>`).join('')}</ul>
        </div>`;
    }).join('');
}

export async function render() {
    const el = document.getElementById('profil');
    if (!el.innerHTML) el.innerHTML = '<p class="blank">Chargement…</p>';
    let d;
    try { d = await api.get('/profile'); }
    catch (e) { el.innerHTML = `<p class="blank">${esc(e.message)}</p>`; return; }
    const p = d.profile || {};

    el.innerHTML = `<div class="settings">
        <div class="settings-main">
            ${SECTIONS.map((s) => `<section class="card">
                <div class="card-header"><span class="card-title">${esc(s.titre)}</span></div>
                <div class="card-body">
                    ${s.aide ? `<p class="hint settings-aide">${esc(s.aide)}</p>` : ''}
                    ${s.champs.map((c) => champ(c, p)).join('')}
                </div>
            </section>`).join('')}
            <div class="settings-save"><button class="btn btn-primary" id="save">Enregistrer et recalculer les scores</button></div>
        </div>
        <section class="card queries">
            <div class="card-header"><span class="card-title">Sources et recherches</span></div>
            <div class="card-body">
                <p class="hint settings-aide">Chaque recherche cochée est lancée à chaque collecte. Garder des
                    mots-clés courts et précis.</p>
                ${sources(d.queries || [])}
            </div>
        </section>
    </div>`;

    document.getElementById('save').addEventListener('click', async (ev) => {
        const values = {};
        el.querySelectorAll('[data-key]').forEach((n) => {
            values[n.dataset.key] = n.hasAttribute('data-bool') ? (n.checked ? '1' : '0') : n.value;
        });
        ev.target.disabled = true;
        try {
            await api.post('/profile', { values });
            await api.post('/rescore', {});
            note('Enregistré — recalcul des scores en cours');
        } catch (e) { note(e.message); }
        finally { ev.target.disabled = false; }
    });

    el.querySelectorAll('[data-query]').forEach((cb) => {
        cb.addEventListener('change', async () => {
            try {
                await api.post('/query/toggle', { query_id: Number(cb.dataset.query), enabled: cb.checked });
                note(cb.checked ? 'Recherche activée' : 'Recherche désactivée');
            } catch (e) { note(e.message); cb.checked = !cb.checked; }
        });
    });
}
