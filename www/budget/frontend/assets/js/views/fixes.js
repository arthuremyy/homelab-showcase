// « Fixes » : revenus, aides et charges qui reviennent chaque mois.
// La détection ne fait que proposer : rien n'est compté sans confirmation.
import { api } from '../api.js';
import { esc, eur, dayLabel } from '../fmt.js';
import { toast, fail, modal } from '../ui.js';
import { changed } from '../state.js';

const el = () => document.getElementById('view-fixes');
let data = { confirmed: [], suggestions: [], parties: [] };

const partyLabel = (key) => data.parties.find((p) => p.key === key)?.label;

const prevMonth = () => { const d = new Date(); d.setDate(0); return d.toLocaleDateString('fr-FR', { month: 'long' }); };

/** Sous-ligne d'un fixe : ce qu'il faut savoir, et seulement ça. */
function status(r) {
    const notes = [];
    if (r.missing) notes.push(['warn', `absent en ${prevMonth()}, dernier le ${dayLabel(r.last_seen)}`]);
    else if (r.never_seen) notes.push(['warn', 'jamais vu sur le compte : à rattacher']);
    if (r.key !== r.own_key) notes.push(['', `réglé par ${partyLabel(r.key) || r.key.slice(0, -2)}`]);
    return notes.map(([cls, t]) => `<span class="sub ${cls}">${esc(t)}</span>`).join('');
}

function section(title, list, empty) {
    const total = list.reduce((a, r) => a + r.amount, 0);
    return `
      <div class="card">
        <div class="card-header"><span class="card-title">${esc(title)}</span>
          <div class="card-actions"><b class="${total > 0 ? 'pos' : ''}">${eur(total, { sign: true })}</b><span class="dim">/ mois</span></div></div>
        <div class="card-body flush">${list.length ? `<ul class="rows list">${list.map((r) => `
          <li class="row" data-edit="${r.id}" tabindex="0">
            <span class="day">${r.day ? `le ${r.day}` : '—'}</span>
            <span class="grow">${esc(r.label)}${status(r)}</span>
            <b class="${r.amount > 0 ? 'pos' : ''}">${eur(r.amount, { sign: true })}</b>
          </li>`).join('')}</ul>` : `<p class="dim pad">${esc(empty)}</p>`}</div>
      </div>`;
}

function suggestions() {
    if (!data.suggestions.length) return '';
    return `
      <div class="card">
        <div class="card-header"><span class="card-title">Repérés dans tes opérations</span>
          <span class="badge badge-accent">${data.suggestions.length}</span>
          <div class="card-actions"><button class="btn btn-sm btn-primary" id="fix-all">Tout ajouter</button></div></div>
        <div class="card-body flush"><ul class="rows list">${data.suggestions.map((s, i) => `
          <li class="row">
            <span class="day">le ${s.day}</span>
            <span class="grow">${esc(s.label)}<span class="sub">vu ${s.months} mois de suite, dernier ${esc(dayLabel(s.last_date))}</span></span>
            <b class="${s.amount > 0 ? 'pos' : ''}">${eur(s.amount, { sign: true })}</b>
            <span class="acts">
              <button class="btn btn-sm btn-primary" data-ok="${i}">Ajouter</button>
              <button class="btn btn-sm btn-ghost" data-no="${i}">Ignorer</button>
            </span>
          </li>`).join('')}</ul></div>
      </div>`;
}

export async function render() {
    try { data = await api.get('/recurring'); }
    catch (e) { fail(e); return; }
    const inc = data.confirmed.filter((r) => r.amount > 0);
    const out = data.confirmed.filter((r) => r.amount < 0);
    const net = data.confirmed.reduce((a, r) => a + r.amount, 0);
    document.getElementById('sugg-pill').hidden = !data.suggestions.length;
    document.getElementById('sugg-pill').textContent = data.suggestions.length;
    el().innerHTML = `
      <div class="section-head"><h2>Chaque mois</h2>
        <span class="dim" title="Revenus fixes − charges fixes : ce qui reste chaque mois pour les dépenses courantes">reste à vivre
          <b class="${net >= 0 ? 'pos' : 'neg'}">${eur(net, { sign: true })}</b> / mois</span>
        <div class="toolbar"><button class="btn" id="fix-add">Ajouter un fixe</button></div></div>
      ${suggestions()}
      <div class="grid grid-2">
        ${section('Revenus et aides', inc, 'Salaire, prime d’activité, APL… ils apparaîtront ici une fois confirmés.')}
        ${section('Charges', out, 'Loyer, énergie, abonnements… ils apparaîtront ici une fois confirmés.')}
      </div>`;
}

function form(r = {}) {
    return `
      <div class="field"><label for="f-label">Libellé</label>
        <input class="input" id="f-label" name="label" required maxlength="80" value="${esc(r.label || '')}"></div>
      <div class="grid grid-2">
        <div class="field"><label for="f-amount">Montant mensuel</label>
          <input class="input" id="f-amount" name="amount" type="number" step="0.01" required value="${r.amount ?? ''}">
          <span class="hint">Négatif pour une charge</span></div>
        <div class="field"><label for="f-day">Jour du mois</label>
          <input class="input" id="f-day" name="day" type="number" min="1" max="31" value="${r.day ?? ''}"></div>
      </div>
      <div class="field"><label for="f-match">Correspond à</label>
        <select class="select" id="f-match" name="match_key">
          <option value="">${r.id ? 'son propre libellé' : 'Automatique (libellé)'}</option>
          ${data.parties.map((p) => `<option value="${esc(p.key)}" ${p.key === r.key && r.key !== r.own_key || (p.key === r.key && r.id) ? 'selected' : ''}>${
              esc(p.label)} · ${esc(eur(p.last_amount, { sign: true }))}</option>`).join('')}
        </select>
        <span class="hint">L’opération qui règle ce fixe. Plusieurs fixes peuvent partager la même (ex. APL et prime d’activité versées en un virement CAF).</span></div>`;
}

const values = (f) => ({ label: f.get('label'), amount: Number(f.get('amount')),
                         day: f.get('day') ? Number(f.get('day')) : null,
                         match_key: f.get('match_key') || null });

async function act(fn, msg) {
    try { await fn(); if (msg) toast(msg); render(); changed(); }
    catch (e) { fail(e); }
}

export function wire() {
    el().addEventListener('click', async (e) => {
        const ok = e.target.closest('[data-ok]');
        const no = e.target.closest('[data-no]');
        const edit = e.target.closest('[data-edit]');
        if (ok) {
            const s = data.suggestions[Number(ok.dataset.ok)];
            act(() => api.post('/recurring/confirm', { key: s.key, match_key: s.match_key, label: s.label, amount: s.amount, day: s.day }),
                `${s.label} ajouté aux fixes.`);
        } else if (no) {
            const s = data.suggestions[Number(no.dataset.no)];
            act(() => api.post('/recurring/ignore', { key: s.key }));
        } else if (e.target.closest('#fix-all')) {
            act(async () => {
                for (const x of data.suggestions) {
                    await api.post('/recurring/confirm', { key: x.key, match_key: x.match_key, label: x.label, amount: x.amount, day: x.day });
                }
            }, `${data.suggestions.length} fixes ajoutés. Retire ceux qui n’en sont pas d’un clic.`);
        } else if (e.target.closest('#fix-add')) {
            const f = await modal({ title: 'Ajouter un fixe', body: form(), ok: 'Ajouter' });
            if (f) act(() => api.post('/recurring/add', values(f)), 'Fixe ajouté.');
        } else if (edit) {
            const r = data.confirmed.find((x) => x.id === Number(edit.dataset.edit));
            if (!r) return;
            const f = await modal({ title: 'Modifier le fixe', body: form(r), danger: 'Retirer' });
            if (f === 'danger') act(() => api.post('/recurring/delete', { id: r.id }), 'Fixe retiré.');
            else if (f) act(() => api.post('/recurring/update', { id: r.id, ...values(f) }));
        }
    });
    el().addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && e.target.matches('[data-edit]')) e.target.click();
    });
}
