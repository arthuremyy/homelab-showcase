// Vocabulaire et actions du suivi — UN seul endroit.
//
// Les codes en base (vivier, candidate…) restent internes : l'interface ne montre
// que des libellés d'action, compréhensibles sans mode d'emploi.
import { joursDepuis } from './fmt.js';

export const RELANCE_J = 10;     // mêmes seuils que backend/services/actions.py
export const SILENCE_J = 21;

export const LIBELLE = {
    nouveau: 'À trier',
    ecarte: 'Pas pour moi',
    vivier: 'À postuler',
    candidate: 'Postulé',
    entretien: 'Entretien',
    offre: 'Offre reçue',
    refuse: 'Refusée',
    sans_reponse: 'Sans réponse',
    decline: 'Abandonnée',
};

// Couleur du badge d'étape (classes du design system)
export const TON = {
    nouveau: '', ecarte: '', vivier: 'badge-accent', candidate: 'badge-accent',
    entretien: 'badge-warning', offre: 'badge-success',
    refuse: '', sans_reponse: '', decline: '',
};

export const ACTIVES = ['vivier', 'candidate', 'entretien', 'offre'];
export const CLOSES = ['refuse', 'sans_reponse', 'decline'];

// Étapes du tableau, dans l'ordre du parcours, avec ce qu'on y fait.
export const COLONNES = [
    { cle: 'vivier', titre: 'À postuler', aide: 'Gardées au tri. Prochaine étape : postuler.' },
    { cle: 'candidate', titre: 'Postulé', aide: `Relance proposée au bout de ${RELANCE_J} jours.` },
    { cle: 'entretien', titre: 'Entretiens', aide: 'Process en cours.' },
    { cle: 'offre', titre: 'Offres reçues', aide: 'Proposition à étudier.' },
];

// Prochaines actions selon l'étape. La première est l'action principale.
// '@followup' = relance faite (ne change pas d'étape).
const SUITE = {
    nouveau: [['vivier', 'À postuler'], ['ecarte', 'Pas pour moi']],
    vivier: [['candidate', 'J’ai postulé'], ['ecarte', 'Retirer']],
    candidate: [['entretien', 'Entretien obtenu'], ['@followup', 'J’ai relancé'],
        ['refuse', 'Refus reçu'], ['sans_reponse', 'Sans réponse']],
    entretien: [['offre', 'Offre reçue'], ['refuse', 'Refus reçu'], ['decline', 'J’abandonne']],
    offre: [['decline', 'Décliner']],
    refuse: [['vivier', 'Remettre à postuler']],
    sans_reponse: [['entretien', 'Finalement, entretien'], ['vivier', 'Remettre à postuler']],
    decline: [['vivier', 'Remettre à postuler']],
    ecarte: [['vivier', 'Remettre à postuler']],
};

/** Prochaines actions pour CETTE offre : l'action principale suit le contexte
 *  (relance due, silence prolongé, annonce retirée). Accepte aussi un code d'étape. */
export function suite(o) {
    const statut = typeof o === 'string' ? o : o.status;
    let liste = [...(SUITE[statut] || SUITE.nouveau)];
    if (typeof o === 'string') return liste;
    const enTete = (act) => {
        const i = liste.findIndex(([a]) => a === act);
        if (i > 0) liste = [liste[i], ...liste.slice(0, i), ...liste.slice(i + 1)];
    };
    const alerte = etatSuivi(o).alerte;
    if (alerte === 'Relance due') enTete('@followup');
    if (alerte === 'Sans réponse ?') enTete('sans_reponse');
    if (statut === 'vivier' && (o.is_active === 0 || o.is_active === false)) enTete('ecarte');
    return liste;
}

// Message de confirmation après une action
export const CONFIRMATION = {
    vivier: 'Ajoutée à « À postuler »',
    ecarte: 'Écartée',
    candidate: 'Candidature notée — relance proposée dans 10 jours',
    entretien: 'Passée en entretien',
    offre: 'Offre reçue, bravo',
    refuse: 'Classée « refusée »',
    sans_reponse: 'Classée « sans réponse »',
    decline: 'Classée « abandonnée »',
    nouveau: 'Remise à trier',
    '@followup': 'Relance notée — elle ressortira dans 10 jours',
};

/** Où en est cette candidature, en une phrase, et faut-il agir ? */
export function etatSuivi(o) {
    const j = (iso) => joursDepuis(iso);
    const jours = (n) => (n <= 0 ? 'aujourd’hui' : n === 1 ? 'hier' : `il y a ${n} j`);
    if (o.status === 'candidate' && o.applied_at) {
        const a = j(o.applied_at);
        const r = o.last_followup_at ? j(o.last_followup_at) : null;
        if (a >= SILENCE_J) return { texte: `Postulé ${jours(a)}`, alerte: 'Sans réponse ?', ton: 'badge-warning' };
        if (a >= RELANCE_J && (r === null || r >= RELANCE_J)) {
            return { texte: `Postulé ${jours(a)}`, alerte: 'Relance due', ton: 'badge-warning' };
        }
        return { texte: `Postulé ${jours(a)}${r !== null ? ` · relancé ${jours(r)}` : ''}` };
    }
    if (o.moved_at) {
        const n = j(o.moved_at);
        const verbe = { vivier: 'Gardée', entretien: 'En entretien depuis', offre: 'Reçue' }[o.status];
        if (verbe) return { texte: `${verbe} ${verbe.endsWith('depuis') ? (n <= 0 ? 'aujourd’hui' : `${n} j`) : jours(n)}` };
    }
    return { texte: '' };
}

/** L'annonce est-elle toujours en ligne ? */
export function enLigne(o) {
    if (o.is_active === 0 || o.is_active === false) {
        return { ok: false, texte: 'Annonce retirée', detail: o.last_seen_at ? `plus vue depuis ${dateCourte(o.last_seen_at)}` : '' };
    }
    return { ok: true, texte: 'En ligne' };
}

function dateCourte(iso) {
    const d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
}
