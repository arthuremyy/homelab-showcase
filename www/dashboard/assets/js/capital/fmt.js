// Formatage et échappement. esc() est OBLIGATOIRE sur tout HTML injecté.
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const EUR = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' });
const EUR0 = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 });

/** Montant en euros ; `sign` force le + des gains. */
export function eur(n, { sign = false, round = false } = {}) {
    if (n === null || n === undefined || Number.isNaN(n)) return '—';
    const s = (round ? EUR0 : EUR).format(n);
    return sign && n > 0 ? `+${s}` : s;
}

/** Pourcentage déjà multiplié par 100 (ex. 6.34 → « +6,34 % »). */
export function pct(n, { sign = true } = {}) {
    if (n === null || n === undefined || Number.isNaN(n)) return '—';
    const s = Number(n).toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return `${sign && n > 0 ? '+' : ''}${s} %`;
}

/** Quantité : jusqu'à 6 décimales, sans zéros inutiles. */
export const qty = (n) => Number(n ?? 0).toLocaleString('fr-FR', { maximumFractionDigits: 6 });

export const cls = (n) => (n > 0 ? 'pos' : n < 0 ? 'neg' : '');

export function frDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso.slice(0, 10) + 'T12:00:00');
    return isNaN(d) ? iso : d.toLocaleDateString('fr-FR');
}

export function since(iso) {
    if (!iso) return 'jamais';
    const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (min < 1) return 'à l’instant';
    if (min < 60) return `il y a ${min} min`;
    const h = Math.round(min / 60);
    if (h < 24) return `il y a ${h} h`;
    return `il y a ${Math.round(h / 24)} j`;
}

export const today = () => new Date().toLocaleDateString('sv-SE');      // AAAA-MM-JJ local

export const TX = { buy: 'Achat', sell: 'Vente', dividend: 'Dividende', fee: 'Frais' };
export const SOURCE = { manuel: 'Saisie', pdf: 'Avis Natixis', pointage: 'Rattrapage', reprise: 'Reprise' };
export const CLASS = { monetary: 'Monétaire', equity: 'Actions', etf: 'ETF', crypto: 'Crypto',
                       mixed: 'Diversifié', bond: 'Obligations', autre: 'Autre' };
