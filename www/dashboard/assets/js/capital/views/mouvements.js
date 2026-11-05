// Tous les mouvements, filtrés par compte. Un clic ouvre la modification ; les rattrapages
// de pointage sont signalés (date et prix à préciser).
import { api } from '../api.js';
import { esc, eur, qty, frDate, TX, SOURCE } from '../fmt.js';
import { fail } from '../ui.js';
import { movementForm, assetForm } from '../forms.js';

const el = () => document.getElementById('view-mouvements');
const NAMES = { PEA: 'PEA', CRYPTO: 'Bitcoin', PEE: 'PEE' };
let filter = '';
let txs = [];

function table() {
    const list = txs.filter((t) => !filter || t.account === filter);
    if (!list.length) return '<div class="empty">Aucun mouvement.</div>';
    return `<div class="table-wrap"><table class="table clickable">
      <thead><tr><th>Date</th><th>Compte</th><th>Mouvement</th><th class="num">Quantité</th><th class="num">Prix</th><th class="num">Montant</th></tr></thead>
      <tbody>${list.map((t) => `<tr data-id="${t.id}" tabindex="0">
        <td>${esc(frDate(t.date))}</td><td>${esc(NAMES[t.account] || t.account)}</td>
        <td>${esc(TX[t.type] || t.type)} · ${esc(t.name)}
          <span class="sub ${t.source === 'pointage' ? 'warn' : ''}">${esc(SOURCE[t.source] || t.source)}${t.note ? ` — ${esc(t.note)}` : ''}</span></td>
        <td class="num">${t.shares ? esc(qty(t.shares)) : ''}</td>
        <td class="num">${t.price ? esc(eur(t.price)) : ''}</td>
        <td class="num">${esc(eur(t.amount))}${t.employer_amount ? `<span class="sub">+ ${esc(eur(t.employer_amount))} abondement</span>` : ''}</td>
      </tr>`).join('')}</tbody></table></div>`;
}

function draw() {
    el().querySelector('[data-table]').innerHTML = table();
}

export async function render() {
    el().innerHTML = `
      <div class="toolbar">
        <div class="segmented" role="group" aria-label="Compte">${[['', 'Tous'], ...Object.entries(NAMES)].map(([k, v]) =>
            `<button data-filter="${k}" aria-pressed="${k === filter}">${esc(v)}</button>`).join('')}</div>
        <span class="grow"></span>
        <button class="btn btn-sm" data-asset>Nouvel actif</button>
        <a class="btn btn-sm btn-ghost" href="/api/capital/api/export" download>Exporter (CSV)</a>
      </div>
      <div class="card" data-table><div class="empty">Chargement…</div></div>`;
    try {
        txs = (await api.get('/transactions')).transactions;
        draw();
    } catch (e) { fail(e); }
}

export function wire() {
    const root = el();
    root.addEventListener('click', (e) => {
        const f = e.target.closest('[data-filter]');
        if (f) {
            filter = f.dataset.filter;
            root.querySelectorAll('[data-filter]').forEach((b) => b.setAttribute('aria-pressed', String(b === f)));
            draw();
        }
        if (e.target.closest('[data-asset]')) assetForm();
        const row = e.target.closest('tr[data-id]');
        if (row) movementForm(txs.find((t) => t.id === Number(row.dataset.id)));
    });
    root.addEventListener('keydown', (e) => {
        const row = e.target.closest('tr[data-id]');
        if (row && e.key === 'Enter') movementForm(txs.find((t) => t.id === Number(row.dataset.id)));
    });
}
