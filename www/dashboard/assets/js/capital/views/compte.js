// Un compte (PEA, Bitcoin, PEE) : état du pointage → chiffres → lignes → spécificités → pointages passés.
import { api } from '../api.js';
import { esc, eur, pct, qty, cls, frDate, since } from '../fmt.js';
import { fail } from '../ui.js';
import { checkForm, avisForm, movementForm } from '../forms.js';
import { STATE_LABEL, STATE_BADGE, checkLine } from './ensemble.js';

const el = () => document.getElementById('view-compte');
let current = 'PEA';

function header(a) {
    const pee = a.id === 'PEE';
    return `<div class="card"><div class="card-body hero">
      <div class="hero-main"><span class="kpi-label">${esc(a.name)} · ${esc(a.provider)}</span>
        <span class="hero-value">${esc(eur(a.value))}</span>
        <span class="check-line"><span class="badge ${STATE_BADGE[a.check.state]}">${esc(STATE_LABEL[a.check.state])}</span>
          <span class="dim">${esc(checkLine(a))}</span></span></div>
      <dl class="hero-side">
        <div><dt>Versé</dt><dd>${esc(eur(a.invested, { round: true }))}</dd></div>
        ${pee ? `<div><dt>Abondement net</dt><dd>${esc(eur(a.employer, { round: true }))}</dd></div>` : ''}
        <div><dt>Gain</dt><dd class="${cls(a.pnl_eur)}">${esc(eur(a.pnl_eur, { sign: true, round: true }))} <small>${esc(pct(a.pnl_pct))}</small></dd></div>
      </dl>
      <div class="hero-actions">
        ${pee ? '<button class="btn btn-primary" data-avis>Importer un avis Natixis</button>' : ''}
        <button class="btn ${pee ? '' : 'btn-primary'}" data-check>Pointer</button>
      </div>
    </div></div>`;
}

function positionsTable(a, positions) {
    const open = positions.filter((p) => !p.closed);
    if (!open.length) return '<div class="card"><div class="empty">Aucune ligne.</div></div>';
    const pee = a.id === 'PEE';
    const head = pee
        ? '<th>Fonds</th><th class="num">Parts</th><th class="num">Valeur de part</th><th class="num">Valeur</th><th class="num">Versé</th><th class="num">Abondement</th><th class="num">Gain</th>'
        : '<th>Actif</th><th class="num">Quantité</th><th class="num">PRU</th><th class="num">Cours</th><th class="num">Valeur</th><th class="num">Gain</th>';
    const rows = open.map((p) => {
        const quote = `${esc(eur(p.price_eur))}<span class="sub ${p.change_24h ? cls(p.change_24h) : ''}">${esc(pct(p.change_24h))} · ${esc(since(p.price_updated_at))}</span>`;
        const gain = `<span class="${cls(p.pnl_eur)}">${esc(eur(p.pnl_eur, { sign: true }))}</span><span class="sub">${esc(pct(p.pnl_pct))}</span>`;
        return pee
            ? `<tr data-isin="${esc(p.isin)}"><td>${esc(p.name)}</td><td class="num">${esc(qty(p.shares))}</td><td class="num">${quote}</td>
                <td class="num"><b>${esc(eur(p.value))}</b></td><td class="num">${esc(eur(p.invested))}</td>
                <td class="num">${esc(eur(p.employer))}</td><td class="num">${gain}</td></tr>`
            : `<tr data-isin="${esc(p.isin)}"><td>${esc(p.name)}</td><td class="num">${esc(qty(p.shares))}</td><td class="num">${esc(eur(p.pru))}</td>
                <td class="num">${quote}</td><td class="num"><b>${esc(eur(p.value))}</b></td><td class="num">${gain}</td></tr>`;
    }).join('');
    return `<div class="card"><div class="table-wrap"><table class="table clickable positions">
      <thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div></div>`;
}

function peaCard(pea) {
    return `<div class="card"><div class="card-header"><h3 class="card-title">Plafond des versements</h3>
        <span class="dim">${esc(eur(pea.versements, { round: true }))} / ${esc(eur(pea.plafond, { round: true }))}</span></div>
      <div class="card-body"><div class="meter"><span style="width:${Math.max(pea.utilisation_pct, 0.5)}%"></span></div>
        <p class="dim small">Reste ${esc(eur(pea.restant, { round: true }))} de versements possibles.</p></div></div>`;
}

function availabilityCard(items) {
    const t = new Date().toLocaleDateString('sv-SE');
    return `<div class="card"><div class="card-header"><h3 class="card-title">Déblocages</h3></div>
      <div class="card-body"><ul class="rows">${items.map((x) => `<li class="row">
        <span class="grow">${x.available_on === 'inconnue' ? 'Date inconnue'
            : x.available_on <= t ? 'Disponible' : `Disponible le ${esc(frDate(x.available_on))}`}</span>
        <b>${esc(eur(x.value))}</b></li>`).join('')}</ul>
      <p class="dim small">Chaque versement est bloqué 5 ans (sauf cas de déblocage anticipé).</p></div></div>`;
}

function checksCard(checks) {
    if (!checks.length) return '';
    return `<div class="card"><div class="card-header"><h3 class="card-title">Pointages</h3></div>
      <div class="table-wrap"><table class="table">
        <thead><tr><th>Date</th><th>Source</th><th class="num">Réel</th><th class="num">Calculé</th><th>État</th></tr></thead>
        <tbody>${checks.slice(0, 8).map((c) => `<tr><td>${esc(frDate(c.date))}</td>
          <td>${c.source === 'pdf' ? 'Avis Natixis' : 'Saisie'}${c.adjustments ? `<span class="sub">${c.adjustments} rattrapage(s)</span>` : ''}</td>
          <td class="num">${esc(eur(c.declared_total))}</td><td class="num">${esc(eur(c.computed_total))}</td>
          <td><span class="badge ${c.status === 'ok' ? 'badge-success' : 'badge-danger'}">${c.status === 'ok' ? 'Concordant' : 'Écart'}</span></td></tr>`).join('')}
        </tbody></table></div></div>`;
}

export async function render(account = current) {
    current = account;
    try {
        const [d, c] = await Promise.all([api.get(`/accounts/${account}`), api.get(`/accounts/${account}/checks`)]);
        el().innerHTML = header(d.account) + positionsTable(d.account, d.positions)
            + (d.pea ? peaCard(d.pea) : '') + (d.availability?.length ? availabilityCard(d.availability) : '')
            + checksCard(c.checks);
    } catch (e) { fail(e); }
}

export function wire() {
    el().addEventListener('click', (e) => {
        if (e.target.closest('[data-check]')) checkForm(current);
        if (e.target.closest('[data-avis]')) avisForm();
        const row = e.target.closest('tr[data-isin]');
        if (row) movementForm(null, { account: current, isin: row.dataset.isin });
    });
}
