// Formatage et échappement.
// esc() est OBLIGATOIRE sur tout HTML injecté : intitulés et noms d'entreprise
// viennent de sources externes non fiables.
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** N'autorise que http(s). Bloque javascript:, data:, etc. */
export function safeUrl(u) {
    try {
        const url = new URL(String(u), window.location.origin);
        return (url.protocol === 'http:' || url.protocol === 'https:') ? url.href : '#';
    } catch { return '#'; }
}

export const TRACK = {
    cyber_indus: 'cyber + industrie',
    cyber_pur: 'cyber généraliste',
    ot_pur: 'OT / automatisme',
    hors_cible: 'hors cible',
};
export const CONTRAT = {
    cdi: 'CDI', cdd: 'CDD', vie: 'VIE', alternance: 'Alternance',
    stage: 'Stage', interim: 'Intérim', unknown: null,
};
export const TELETRAVAIL = {
    full: 'Télétravail complet', partial: 'Télétravail partiel', none: 'Sur site', unknown: null,
};
export const SOURCE = { france_travail: 'France Travail', adzuna: 'Adzuna', jooble: 'Jooble' };
// Libellés des étapes du suivi : voir statuts.js (source unique).

/** Nombre de jours écoulés, formulé pour un suivi de candidature. */
export function depuis(iso) {
    const j = joursDepuis(iso);
    if (j === null) return null;
    if (j <= 0) return "aujourd’hui";
    if (j === 1) return 'hier';
    return `il y a ${j} jours`;
}

export function joursDepuis(iso) {
    if (!iso) return null;
    const d = new Date(iso);
    if (isNaN(d)) return null;
    return Math.floor((Date.now() - d.getTime()) / 86400000);
}

export function ilYA(iso) {
    const j = joursDepuis(iso);
    if (j === null) return '';
    if (j <= 0) return "aujourd’hui";
    if (j === 1) return 'hier';
    if (j < 31) return `il y a ${j} jours`;
    const m = Math.floor(j / 30);
    return `il y a ${m} mois`;
}

export function dateFr(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' });
}

/** Expérience demandée, en clair. Le libellé de la source prime. */
export function experience(o) {
    if (o.xp_label) return o.xp_label;
    if (o.xp_required === 0) return 'Débutant accepté';
    if (o.xp_required != null) return `${o.xp_required} an${o.xp_required > 1 ? 's' : ''}`;
    return null;
}

/** Salaire compact pour une colonne déjà titrée « Salaire » :
 *  « 39 000 – 44 000 € brut annuel » → « 39 – 44 k€ ». Répéter « brut annuel »
 *  sur chaque ligne faisait passer la valeur à la ligne. */
export function salaireCourt(o) {
    const lo = o.salary_min, hi = o.salary_max;
    if (!lo) return null;
    const k = (v) => Math.round(v / 1000);
    return (hi && k(hi) !== k(lo)) ? `${k(lo)} – ${k(hi)} k€` : `${k(lo)} k€`;
}

/** Expérience compacte : les libellés des sources sont parfois des phrases
 *  entières (« 3 An(s) - en environnements cloud modernes »). */
export function experienceCourte(o) {
    if (o.xp_required === 0) return 'Débutant';
    if (o.xp_required != null) return `${o.xp_required} an${o.xp_required > 1 ? 's' : ''}`;
    const l = o.xp_label;
    if (!l) return null;
    if (/débutant/i.test(l)) return 'Débutant';
    const m = l.match(/(\d+)\s*an/i);
    if (m) return `${m[1]} an${Number(m[1]) > 1 ? 's' : ''}`;
    return l.length > 18 ? l.slice(0, 17) + '…' : l;
}

/** Intitulé débarrassé des mentions de genre, souvent répétées par les sources :
 *  « Ingénieur Réseaux et Sécurité H/F (H/F) » → « Ingénieur Réseaux et Sécurité ». */
export function titre(t) {
    if (!t) return '';
    let s = String(t);
    // Retire toutes les mentions H/F, F/H, M/F, H/F/X… entre parenthèses ou nues.
    s = s.replace(/[\s(\[/–-]*\b([hfmx])\s*[/.]\s*([hfmx])(\s*[/.]\s*[hfmx])?\b[\s)\]]*/gi, ' ');
    s = s.replace(/\s{2,}/g, ' ').replace(/[\s·,;:–-]+$/, '').trim();
    return s || String(t).trim();
}

/** Ville sans le code département, qui fait doublon avec le reste de la fiche. */
export function ville(loc) {
    if (!loc) return null;
    return String(loc).replace(/^\d{2}\s*-\s*/, '').replace(/\s*-\s*\d{2}$/, '').trim() || null;
}
