// « Opérations » : le mois opération par opération, catégorie modifiable en un geste.
import { api } from '../api.js';
import { esc, eur, dayLabel, opTitle, KIND } from '../fmt.js';
import { toast, fail, modal } from '../ui.js';
import { state, changed } from '../state.js';
import { monthNav, wireMonthNav } from './mois.js';

const el = () => document.getElementById('view-operations');
let data = { operations: [], categories: [] };
let q = '';
let quick = '';             // filtre rapide : '' toutes, 'out', 'in', 'todo' (à classer)

// « Divers » est le repli de la catégorisation : ce qui y tombe reste à classer.
const QUICK = [['', 'Toutes'], ['out', 'Dépenses'], ['in', 'Entrées'], ['todo', 'À classer']];
const unsorted = (o) => !o.category_id || data.categories.find((c) => c.id === o.category_id)?.name === 'Divers';

function catOptions(selected, { blank = false } = {}) {
    const groups = {};
    for (const c of data.categories) (groups[c.kind] ||= []).push(c);
    return (blank ? '<option value="">Toutes les catégories</option>' : '') +
        Object.entries(groups).map(([k, cs]) => `<optgroup label="${esc(KIND[k] || k)}">${
            cs.map((c) => `<option value="${c.id}" ${String(c.id) === String(selected) ? 'selected' : ''}>${esc(c.name)}</option>`).join('')
        }</optgroup>`).join('');
}

function filtered() {
    const needle = q.trim().toLowerCase();
    return data.operations.filter((o) =>
        (!state.category || String(o.category_id) === String(state.category)) &&
        (quick !== 'out' || o.amount < 0) && (quick !== 'in' || o.amount > 0) && (quick !== 'todo' || unsorted(o)) &&
        (!needle || `${o.counterparty || ''} ${o.label}`.toLowerCase().includes(needle)));
}

function table() {
    const ops = filtered();
    if (!ops.length) return `<div class="empty"><strong>Aucune opération</strong>${
        data.operations.length ? 'Aucun résultat pour ce filtre.' : 'Rien pour ce mois-ci.'}</div>`;
    let lastDay = null;
    const rows = ops.map((o) => {
        const head = o.date !== lastDay
            ? `<tr class="day-row"><td colspan="3">${esc(dayLabel(o.date))}</td></tr>` : '';
        lastDay = o.date;
        return head + `
          <tr>
            <td class="label">
              <div class="title">${esc(opTitle(o))}
                ${o.status === 'PDNG' ? '<span class="badge">en attente</span>' : ''}
                ${o.source === 'manual' ? '<span class="badge">saisie</span>' : ''}</div>
              ${o.counterparty ? `<div class="sub">${esc(o.label)}</div>` : ''}
            </td>
            <td class="cat-cell">
              <select class="select select-sm" data-op="${o.id}" aria-label="Catégorie">${catOptions(o.category_id)}</select>
            </td>
            <td class="num ${o.amount > 0 ? 'pos' : ''}">${eur(o.amount, { sign: true })}
              ${o.source === 'manual' ? `<button class="btn btn-sm btn-ghost btn-icon" data-del="${o.id}" title="Supprimer la saisie" aria-label="Supprimer la saisie">✕</button>` : ''}
            </td>
          </tr>`;
    }).join('');
    const inc = ops.filter((o) => o.amount > 0).reduce((a, o) => a + o.amount, 0);
    const out = ops.filter((o) => o.amount < 0).reduce((a, o) => a + o.amount, 0);
    return `<div class="table-wrap"><table class="table ops">
      <tbody>${rows}</tbody>
      <tfoot><tr><td colspan="2">${ops.length} opération${ops.length > 1 ? 's' : ''}</td>
        <td class="num"><span class="pos">${eur(inc, { sign: true })}</span> · ${eur(out)}</td></tr></tfoot></table></div>`;
}

function paint() {
    document.getElementById('ops-table').innerHTML = table();
}

export async function render() {
    const root = el();
    try { data = await api.post('/operations/list', { month: state.month }); }
    catch (e) { fail(e); return; }
    root.innerHTML = `
      ${monthNav(state.month, data.months)}
      <div class="toolbar ops-bar">
        <div class="segmented" role="group" aria-label="Filtre rapide">${QUICK.map(([k, l]) =>
            `<button type="button" data-quick="${k}" aria-pressed="${k === quick}">${l}</button>`).join('')}</div>
        <input class="input grow" type="search" id="ops-q" placeholder="Rechercher un libellé" value="${esc(q)}">
        <select class="select" id="ops-cat" aria-label="Filtrer par catégorie">${catOptions(state.category, { blank: true })}</select>
        <button class="btn" id="ops-add">Ajouter une opération</button>
      </div>
      <div class="card"><div class="card-body flush" id="ops-table"></div></div>`;
    paint();
}

async function categorize(sel) {
    const id = Number(sel.dataset.op);
    const category_id = Number(sel.value);
    const o = data.operations.find((x) => x.id === id);
    const name = sel.selectedOptions[0]?.textContent || '';
    try {
        await api.post('/operations/categorize', { id, category_id });
        if (o) { o.category_id = category_id; o.category_locked = 1; }
        toast(`Classée dans ${name}.`, {
            action: 'Toujours pour ce libellé',
            ms: 8000,
            onAction: async () => {
                try {
                    const r = await api.post('/operations/categorize', { id, category_id, remember: true });
                    toast(`Règle « ${r.rule} » créée${r.changed ? `, ${r.changed} autre(s) opération(s) reclassée(s)` : ''}.`);
                    render();
                    changed();
                } catch (e) { fail(e); }
            },
        });
        changed();
    } catch (e) { fail(e); }
}

async function addManual() {
    const today = new Date().toISOString().slice(0, 10);
    const f = await modal({
        title: 'Ajouter une opération',
        body: `
          <div class="field"><label for="m-label">Libellé</label>
            <input class="input" id="m-label" name="label" required maxlength="200" placeholder="Ex. marché, espèces"></div>
          <div class="grid grid-2">
            <div class="field"><label for="m-amount">Montant</label>
              <input class="input" id="m-amount" name="amount" type="number" step="0.01" required placeholder="-25,00">
              <span class="hint">Négatif pour une dépense</span></div>
            <div class="field"><label for="m-date">Date</label>
              <input class="input" id="m-date" name="date" type="date" required value="${today}"></div>
          </div>
          <div class="field"><label for="m-cat">Catégorie</label>
            <select class="select" id="m-cat" name="category_id"><option value="">Automatique</option>${catOptions('')}</select></div>`,
        ok: 'Ajouter',
    });
    if (!f) return;
    try {
        await api.post('/operations/add', {
            label: f.get('label'), amount: Number(f.get('amount')), date: f.get('date'),
            category_id: f.get('category_id') ? Number(f.get('category_id')) : null,
        });
        state.month = f.get('date').slice(0, 7);
        toast('Opération ajoutée.');
        render();
        changed();
    } catch (e) { fail(e); }
}

export function wire() {
    const root = el();
    wireMonthNav(root, render);
    root.addEventListener('input', (e) => {
        if (e.target.id === 'ops-q') { q = e.target.value; paint(); }
    });
    root.addEventListener('change', (e) => {
        if (e.target.id === 'ops-cat') { state.category = e.target.value; paint(); }
        else if (e.target.matches('select[data-op]')) categorize(e.target);
    });
    root.addEventListener('click', async (e) => {
        if (e.target.closest('#ops-add')) { addManual(); return; }
        const qb = e.target.closest('[data-quick]');
        if (qb) {
            quick = qb.dataset.quick;
            root.querySelectorAll('[data-quick]').forEach((b) => b.setAttribute('aria-pressed', String(b === qb)));
            paint();
            return;
        }
        const del = e.target.closest('[data-del]');
        if (del) {
            try { await api.post('/operations/delete', { id: Number(del.dataset.del) }); render(); changed(); }
            catch (err) { fail(err); }
        }
    });
}
