// « Réglages » : banque, alertes, catégories et règles.
import { api } from '../api.js';
import { esc, eur, since, KIND } from '../fmt.js';
import { toast, fail, modal, confirmBox } from '../ui.js';
import { changed } from '../state.js';

const el = () => document.getElementById('view-reglages');
let cats = { categories: [], rules: [] };

function bankCard(b) {
    let state, actions;
    if (!b.configured) {
        state = `<div class="notice">Enable Banking n’est pas encore configuré sur le serveur
                 (identifiant d’application et clé privée).</div>`;
        actions = '';
    } else if (!b.connected) {
        state = `<p><span class="dot dot-down"></span> ${b.valid_until ? 'Accès expiré' : 'Banque non reliée'}</p>`;
        actions = `<button class="btn btn-primary" data-bank="connect">Relier la banque</button>`;
    } else {
        state = `
          <dl class="dl">
            <dt>État</dt><dd><span class="dot dot-ok"></span> Reliée${b.days_left !== null ? `, accès valable ${b.days_left} jour(s)` : ''}</dd>
            <dt>Synchronisation</dt><dd>${esc(since(b.last_ok))}, 4 fois par jour</dd>
            ${b.last_error ? `<dt>Dernière erreur</dt><dd class="neg">${esc(b.last_error)}</dd>` : ''}
          </dl>
          <ul class="rows accounts">${b.accounts.map((a) => `
            <li class="row"><span class="grow">${esc(a.name)}${a.iban_tail ? ` <span class="dim">···${esc(a.iban_tail)}</span>` : ''}</span>
              <b>${eur(a.balance)}</b></li>`).join('')}</ul>`;
        actions = `
          <button class="btn" data-bank="sync">Synchroniser</button>
          <button class="btn" data-bank="connect">Renouveler l’accès</button>
          <button class="btn btn-ghost" data-bank="disconnect">Déconnecter</button>`;
    }
    return `
      <div class="card">
        <div class="card-header"><span class="card-title">Banque</span></div>
        <div class="card-body stack">${state}${actions ? `<div class="toolbar">${actions}</div>` : ''}</div>
      </div>`;
}

function alertsCard(s) {
    return `
      <form class="card" id="alerts-form">
        <div class="card-header"><span class="card-title">Alertes Discord</span></div>
        <div class="card-body">
          <div class="field"><label for="low">Prévenir si le solde passe sous</label>
            <input class="input" id="low" name="low_balance" type="number" min="0" step="10" value="${esc(s.low_balance)}">
            <span class="hint">0 pour désactiver. L’accès bancaire à renouveler et les synchronisations en échec sont toujours signalés.</span></div>
          <button class="btn" type="submit">Enregistrer</button>
        </div>
      </form>`;
}

function livretForm(s) {
    const l = s.livret || {};
    return `
      <form class="card" id="livret-form">
        <div class="card-header"><span class="card-title">Livret A</span></div>
        <div class="card-body">
          <div class="grid grid-2">
            <div class="field"><label for="lv-amount">Solde connu</label>
              <input class="input" id="lv-amount" name="amount" type="number" min="0" step="0.01" required value="${esc(l.amount ?? '')}"></div>
            <div class="field"><label for="lv-date">À la date du</label>
              <input class="input" id="lv-date" name="date" type="date" required value="${esc(l.date || new Date().toISOString().slice(0, 10))}"></div>
          </div>
          <p class="dim small">Le livret n’est pas lisible par la banque : son évolution est reconstituée à partir de ce
             solde et de tes virements. À recaler en janvier, après le versement des intérêts.</p>
          <button class="btn" type="submit">Enregistrer</button>
        </div>
      </form>`;
}

function categoriesCard() {
    const rows = cats.categories.map((c) => `
      <tr data-cat="${c.id}" tabindex="0">
        <td>${esc(c.name)}</td>
        <td class="dim">${esc(KIND[c.kind] || c.kind)}</td>
        <td class="num">${c.budget ? eur(c.budget, { round: true }) : '<span class="dim">—</span>'}</td>
      </tr>`).join('');
    return `
      <div class="card">
        <div class="card-header"><span class="card-title">Catégories</span>
          <div class="card-actions"><button class="btn btn-sm" id="cat-add">Ajouter</button></div></div>
        <div class="card-body flush"><div class="table-wrap"><table class="table clickable">
          <thead><tr><th>Nom</th><th>Nature</th><th class="num">Plafond / mois</th></tr></thead>
          <tbody>${rows}</tbody></table></div></div>
      </div>`;
}

function rulesCard() {
    return `
      <div class="card">
        <div class="card-header"><span class="card-title">Règles</span></div>
        <div class="card-body flush">${cats.rules.length ? `<ul class="rows list">${cats.rules.map((r) => `
          <li class="row"><span class="grow"><code>${esc(r.pattern)}</code> → ${esc(r.category)}</span>
            <button class="btn btn-sm btn-ghost" data-rule="${r.id}">Supprimer</button></li>`).join('')}</ul>`
            : `<p class="dim pad">Change la catégorie d’une opération puis choisis « Toujours pour ce libellé » : la règle apparaît ici.</p>`}</div>
      </div>`;
}

export async function render() {
    let b, s;
    try {
        [b, s, cats] = await Promise.all([api.get('/bank/status'), api.get('/settings'), api.get('/categories')]);
    } catch (e) { fail(e); return; }
    el().innerHTML = `
      <div class="grid grid-2">
        <div class="stack">${bankCard(b)}${livretForm(s)}${alertsCard(s)}${rulesCard()}</div>
        <div class="stack">${categoriesCard()}</div>
      </div>`;
}

function catForm(c = {}) {
    return `
      <div class="field"><label for="c-name">Nom</label>
        <input class="input" id="c-name" name="name" required maxlength="60" value="${esc(c.name || '')}"></div>
      <div class="grid grid-2">
        <div class="field"><label for="c-kind">Nature</label>
          <select class="select" id="c-kind" name="kind">${Object.entries(KIND).map(([k, l]) =>
              `<option value="${k}" ${k === (c.kind || 'expense') ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>
          <span class="hint">Les virements internes ne comptent ni en entrée ni en dépense.</span></div>
        <div class="field"><label for="c-budget">Plafond mensuel</label>
          <input class="input" id="c-budget" name="budget" type="number" min="0" step="10" value="${c.budget ?? ''}">
          <span class="hint">Facultatif</span></div>
      </div>`;
}

async function editCategory(c) {
    const f = await modal({ title: c ? 'Modifier la catégorie' : 'Nouvelle catégorie', body: catForm(c || {}),
                            danger: c ? 'Supprimer' : null });
    if (!f) return;
    try {
        if (f === 'danger') {
            if (!await confirmBox('Supprimer la catégorie', `Les opérations de « ${c.name} » seront reclassées automatiquement.`, 'Supprimer')) return;
            await api.post('/categories/delete', { id: c.id });
        } else {
            await api.post('/categories/save', { id: c?.id ?? null, name: f.get('name'), kind: f.get('kind'),
                                                 budget: f.get('budget') ? Number(f.get('budget')) : null });
        }
        render(); changed();
    } catch (e) { fail(e); }
}

async function bank(action, btn) {
    btn.disabled = true;
    try {
        if (action === 'connect') {
            const r = await api.post('/bank/connect');
            window.location.href = r.url;          // page d'authentification de la banque
            return;
        }
        if (action === 'disconnect') {
            if (!await confirmBox('Déconnecter la banque', 'Les opérations déjà importées sont conservées.', 'Déconnecter')) return;
            await api.post('/bank/disconnect');
        }
        if (action === 'sync') {
            const r = await api.post('/bank/sync');
            toast(r.new ? `${r.new} nouvelle(s) opération(s).` : 'Déjà à jour.');
        }
        render(); changed();
    } catch (e) { fail(e); }
    finally { btn.disabled = false; }
}

export function wire() {
    el().addEventListener('click', (e) => {
        const b = e.target.closest('[data-bank]');
        if (b) { bank(b.dataset.bank, b); return; }
        if (e.target.closest('#cat-add')) { editCategory(null); return; }
        const r = e.target.closest('[data-rule]');
        if (r) {
            api.post('/rules/delete', { id: Number(r.dataset.rule) }).then(render).catch(fail);
            return;
        }
        const c = e.target.closest('tr[data-cat]');
        if (c) editCategory(cats.categories.find((x) => x.id === Number(c.dataset.cat)));
    });
    el().addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && e.target.matches('tr[data-cat]')) e.target.click();
    });
    el().addEventListener('submit', async (e) => {
        if (e.target.id === 'livret-form') {
            e.preventDefault();
            const f = new FormData(e.target);
            try {
                await api.post('/settings', { livret: { amount: Number(f.get('amount')), date: f.get('date') } });
                toast('Livret A enregistré.');
                changed();
            } catch (err) { fail(err); }
            return;
        }
        if (e.target.id !== 'alerts-form') return;
        e.preventDefault();
        try {
            await api.post('/settings', { low_balance: Number(new FormData(e.target).get('low_balance') || 0) });
            toast('Enregistré.');
        } catch (err) { fail(err); }
    });
}
