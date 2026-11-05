// Formatage et échappement.
// esc() est OBLIGATOIRE sur tout HTML injecté : les libellés viennent de la banque.
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const EUR = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' });
const EUR0 = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 });

/** Montant en euros ; `sign` force le + des entrées. */
export function eur(n, { sign = false, round = false } = {}) {
    if (n === null || n === undefined || Number.isNaN(n)) return '—';
    const s = (round ? EUR0 : EUR).format(n);
    return sign && n > 0 ? `+${s}` : s;
}

export const pct = (x) => (x === null || x === undefined) ? '—'
    : `${(x * 100).toLocaleString('fr-FR', { maximumFractionDigits: 0 })} %`;

export function monthLabel(m) {
    const [y, mo] = m.split('-').map(Number);
    const s = new Date(y, mo - 1, 1).toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' });
    return s.charAt(0).toUpperCase() + s.slice(1);
}

export function shortMonth(m) {
    const [y, mo] = m.split('-').map(Number);
    return new Date(y, mo - 1, 1).toLocaleDateString('fr-FR', { month: 'short' }).replace('.', '');
}

export function shiftMonth(m, delta) {
    const [y, mo] = m.split('-').map(Number);
    const d = new Date(y, mo - 1 + delta, 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

export function currentMonth() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

export function dayLabel(iso) {
    const d = new Date(iso + 'T12:00:00');
    return isNaN(d) ? '' : d.toLocaleDateString('fr-FR', { weekday: 'short', day: 'numeric', month: 'short' });
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

export const KIND = { income: 'Entrée', expense: 'Dépense', savings: 'Épargne', transfer: 'Virement interne' };

/** Libellé lisible : la contrepartie si la banque la fournit, sinon le libellé
 *  sans son préfixe technique (« CARTE X1234 01/10 », « PRLV SEPA »…). */
export function opTitle(o) {
    if (o.counterparty) return o.counterparty;
    const t = String(o.label || '')
        .replace(/^(CARTE|CB)\s+X?\d{4}\s+(\d{2}\/\d{2}(\/\d{2,4})?\s+)?/i, '')
        .replace(/^(PRLV|PRELEVEMENT)\s+(SEPA\s+)?/i, '')
        .replace(/^(VIR(EMENT)?)\s+(SEPA\s+)?(RECU|EMIS|INST(ANTANE)?)?\s*/i, '');
    return t.trim() || o.label;
}
