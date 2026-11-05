// Formulaires : mouvement, pointage manuel, avis Natixis, nouvel actif.
// Chaque action réussie émet « changed » : la vue active se recharge.
import { api } from './api.js';
import { esc, eur, qty, pct, frDate, today, TX } from './fmt.js';
import { modal, toast, fail } from './ui.js';
import { state } from './state.js';

const changed = () => document.dispatchEvent(new CustomEvent('changed'));
const num = (v) => (v === null || v === '' ? 0 : Number(String(v).replace(',', '.')));

const ACCOUNTS = { PEA: 'PEA', CRYPTO: 'Bitcoin', PEE: 'PEE' };

function assetOptions(selected) {
    return state.assets.map((a) =>
        `<option value="${esc(a.isin)}" ${a.isin === selected ? 'selected' : ''}>${esc(a.name)}</option>`).join('');
}

// ── Mouvement (ajout / modification) ──

export async function movementForm(tx = null, defaults = {}) {
    const t = tx || { type: 'buy', account: defaults.account || 'PEA', date: today(), isin: defaults.isin || '' };
    const body = `
      <div class="grid grid-2">
        <label class="field"><span>Compte</span><select class="select" name="account">
          ${Object.entries(ACCOUNTS).map(([k, v]) => `<option value="${k}" ${k === t.account ? 'selected' : ''}>${esc(v)}</option>`).join('')}
        </select></label>
        <label class="field"><span>Type</span><select class="select" name="type">
          ${Object.entries(TX).map(([k, v]) => `<option value="${k}" ${k === t.type ? 'selected' : ''}>${esc(v)}</option>`).join('')}
        </select></label>
      </div>
      <label class="field"><span>Actif</span><select class="select" name="isin" required>
        <option value="">Choisir…</option>${assetOptions(t.isin)}</select></label>
      <div class="grid grid-2">
        <label class="field"><span>Date</span><input class="input" type="date" name="date" value="${esc(t.date)}" max="${today()}" required></label>
        <label class="field" data-trade><span>Quantité</span><input class="input" name="shares" inputmode="decimal" value="${esc(t.shares ?? '')}"></label>
        <label class="field" data-trade><span>Prix unitaire (€)</span><input class="input" name="price" inputmode="decimal" value="${esc(t.price ?? '')}"></label>
        <label class="field"><span data-amount-label>Montant (€)</span><input class="input" name="amount" inputmode="decimal" value="${esc(t.amount ?? '')}" placeholder="quantité × prix"></label>
        <label class="field" data-trade><span>Frais (€)</span><input class="input" name="fees" inputmode="decimal" value="${esc(t.fees || '')}"></label>
      </div>
      <div class="grid grid-2" data-pee>
        <label class="field"><span>Abondement brut (€)</span><input class="input" name="employer_amount" inputmode="decimal" value="${esc(t.employer_amount || '')}"></label>
        <label class="field"><span>Prélèvements sociaux (€)</span><input class="input" name="social_tax" inputmode="decimal" value="${esc(t.social_tax || '')}"></label>
        <label class="field"><span>Disponible le</span><input class="input" type="date" name="available_on" value="${esc(t.available_on || '')}"></label>
      </div>
      <label class="field"><span>Note</span><input class="input" name="note" maxlength="300" value="${esc(t.note || '')}"></label>`;

    const onMount = (form) => {
        const sync = () => {
            const trade = ['buy', 'sell'].includes(form.elements.type.value);
            form.querySelectorAll('[data-trade]').forEach((el) => { el.hidden = !trade; });
            form.querySelector('[data-pee]').hidden = !(form.elements.account.value === 'PEE' && form.elements.type.value === 'buy');
            form.querySelector('[data-amount-label]').textContent =
                form.elements.account.value === 'PEE' && form.elements.type.value === 'buy' ? 'Versé par moi (€)' : 'Montant (€)';
        };
        form.elements.account.addEventListener('change', sync);
        form.elements.type.addEventListener('change', sync);
        sync();
    };

    const fd = await modal({ title: tx ? 'Modifier le mouvement' : 'Nouveau mouvement', body,
                             danger: tx ? 'Supprimer' : null, onMount });
    if (!fd) return;
    try {
        if (fd === 'danger') {
            await api.del(`/transactions/${tx.id}`);
            toast('Mouvement supprimé.');
        } else {
            const payload = {
                account: fd.get('account'), type: fd.get('type'), isin: fd.get('isin'), date: fd.get('date'),
                shares: num(fd.get('shares')), price: num(fd.get('price')), amount: num(fd.get('amount')),
                fees: num(fd.get('fees')), note: fd.get('note') || '',
                employer_amount: num(fd.get('employer_amount')), social_tax: num(fd.get('social_tax')),
                available_on: fd.get('available_on') || null,
            };
            if (tx) await api.put(`/transactions/${tx.id}`, payload);
            else await api.post('/transactions', payload);
            toast(tx ? 'Mouvement modifié.' : 'Mouvement enregistré.');
        }
        changed();
    } catch (e) { fail(e); }
}

// ── Nouvel actif (recherche Yahoo / CoinGecko), puis son premier mouvement ──

export async function assetForm() {
    let results = [];
    const fd = await modal({
        title: 'Ajouter un actif', ok: 'Ajouter',
        body: `<label class="field"><span>Nom, ticker ou ISIN</span>
                 <input class="input" name="q" autocomplete="off" required></label>
               <div class="rows" data-results></div>`,
        onMount: (form) => {
            let timer;
            form.q.addEventListener('input', () => {
                clearTimeout(timer);
                timer = setTimeout(async () => {
                    const box = form.querySelector('[data-results]');
                    if (form.q.value.trim().length < 2) { box.innerHTML = ''; return; }
                    try {
                        results = (await api.get(`/assets/search?q=${encodeURIComponent(form.q.value.trim())}`)).results;
                        box.innerHTML = results.slice(0, 8).map((r, i) => `
                          <label class="row"><input type="radio" name="pick" value="${i}" ${i ? '' : 'checked'}>
                            <span class="grow">${esc(r.name)}<span class="sub">${esc([r.ticker, r.isin, r.exchange].filter(Boolean).join(' · '))}</span></span>
                            ${r.pea_eligible ? '<span class="badge">PEA</span>' : ''}</label>`).join('')
                            || '<p class="dim">Aucun résultat.</p>';
                    } catch (e) { box.innerHTML = `<p class="neg">${esc(e.message)}</p>`; }
                }, 350);
            });
        },
    });
    if (!fd || fd.get('pick') === null) return;
    const r = results[Number(fd.get('pick'))];
    try {
        const isin = r.isin || r.ticker || r.coingecko_id;
        await api.post('/assets', { ...r, isin, pea_eligible: !!r.pea_eligible });
        state.assets = (await api.get('/assets')).assets;
        await movementForm(null, { isin, account: r.asset_type === 'crypto' ? 'CRYPTO' : 'PEA' });
    } catch (e) { fail(e); }
}

// ── Pointage manuel ──

function resultTable(res) {
    const gapCell = (l) => l.share_ok ? '<span class="pos">ok</span>'
        : `<span class="neg">${l.share_gap > 0 ? '+' : ''}${esc(qty(l.share_gap))}</span>`;
    const priceCell = (l) => l.price_gap_pct === null ? '<span class="dim">—</span>'
        : `<span class="${l.price_ok ? 'dim' : 'warn'}">${esc(pct(l.price_gap_pct))}</span>`;
    return `
      <div class="table-wrap"><table class="table">
        <thead><tr><th>Actif</th><th class="num">Réel</th><th class="num">Calculé</th><th class="num">Quantité</th><th class="num">Écart de cours</th></tr></thead>
        <tbody>${res.lines.map((l) => `<tr>
          <td>${esc(l.name)}${(l.lots || []).filter((x) => !x.ok).map((x) =>
              `<span class="sub warn">Disponible ${esc(frDate(x.available_on))} : ${esc(qty(x.declared_shares))} réel, ${esc(qty(x.computed_shares))} calculé</span>`).join('')}</td>
          <td class="num">${esc(qty(l.declared_shares))}</td><td class="num">${esc(qty(l.computed_shares))}</td>
          <td class="num">${gapCell(l)}</td><td class="num">${priceCell(l)}</td></tr>`).join('')}</tbody>
        <tfoot><tr><td>Total</td><td class="num">${esc(eur(res.declared_total))}</td><td class="num">${esc(eur(res.computed_total))}</td><td></td><td></td></tr></tfoot>
      </table></div>`;
}

function verdict(res) {
    if (res.status === 'ok') return '<div class="notice">Tout concorde avec l’établissement.</div>';
    const parts = [];
    if (res.share_gaps) parts.push(`${res.share_gaps} quantité(s) diffèrent : un mouvement manque ou est en trop.`);
    if (res.price_gaps) parts.push(`${res.price_gaps} cours s’écarte(nt) de la tolérance : la source de prix diverge (rien à corriger dans les mouvements).`);
    return `<div class="notice notice-warning">${parts.map(esc).join('<br>')}</div>`;
}

const adjustBox = (res) => res.share_gaps ? `
    <label class="check"><input type="checkbox" name="adjust" checked>
      Créer les mouvements de rattrapage (au cours du jour, à préciser ensuite dans Mouvements)</label>` : '';

export async function checkForm(account) {
    const positions = state.summary.positions.filter((p) => p.account === account && !p.closed);
    const acc = state.summary.accounts.find((a) => a.id === account);
    const fd = await modal({
        title: `Pointer — ${acc.name}`, ok: 'Comparer', wide: true,
        body: `<p class="dim">Recopie ce qu’affiche ${esc(acc.provider)} aujourd’hui. La valeur est facultative : elle sert à contrôler les cours.</p>
          <div class="table-wrap"><table class="table check-input">
            <thead><tr><th>Actif</th><th>Quantité</th><th>Valeur (€)</th></tr></thead>
            <tbody>${positions.map((p) => `<tr>
              <td>${esc(p.name)}<span class="sub">calculé : ${esc(qty(p.shares))} · ${esc(eur(p.value))}</span></td>
              <td><input class="input input-sm" name="s:${esc(p.isin)}" inputmode="decimal" value="${esc(String(p.shares).replace('.', ','))}" required></td>
              <td><input class="input input-sm" name="v:${esc(p.isin)}" inputmode="decimal" placeholder="${esc(p.value.toFixed(2).replace('.', ','))}"></td>
            </tr>`).join('')}</tbody></table></div>`,
    });
    if (!fd) return;
    const lines = positions.map((p) => ({
        isin: p.isin, shares: num(fd.get(`s:${p.isin}`)),
        value: fd.get(`v:${p.isin}`) ? num(fd.get(`v:${p.isin}`)) : null,
    }));
    try {
        const res = await api.post(`/accounts/${account}/check/preview`, { lines });
        const fd2 = await modal({ title: `Pointer — ${acc.name}`, ok: 'Enregistrer le pointage', wide: true,
                                  body: verdict(res) + resultTable(res) + adjustBox(res) });
        if (!fd2) return;
        const saved = await api.post(`/accounts/${account}/check`, { lines, adjust: fd2.get('adjust') === 'on' });
        toast(saved.adjustments ? `Pointage enregistré, ${saved.adjustments} mouvement(s) de rattrapage créé(s).`
                                : 'Pointage enregistré.');
        changed();
    } catch (e) { fail(e); }
}

// ── Avis d'opération Natixis (PEE) ──

export async function avisForm() {
    const fd = await modal({
        title: 'Importer un avis Natixis', ok: 'Lire le PDF',
        body: `<p class="dim">Avis d’opération téléchargé depuis l’espace épargnant Natixis Interépargne.
                 Les versements sont ajoutés, et la situation des avoirs sert de pointage.</p>
               <input class="input" type="file" name="file" accept="application/pdf" required>`,
    });
    if (!fd) return;
    const file = fd.get('file');
    try {
        const form = new FormData();
        form.append('file', file);
        const p = await api.upload('/pee/import/preview', form);
        const ops = p.operations.length ? `
          <h4>Versements${p.category ? ` — ${esc(p.category)}` : ''}</h4>
          <div class="table-wrap"><table class="table">
            <thead><tr><th>Fonds</th><th class="num">Versé</th><th class="num">Abondement</th><th class="num">Parts</th><th>Disponible</th><th></th></tr></thead>
            <tbody>${p.operations.map((o) => `<tr>
              <td>${esc(o.name || o.fund)}<span class="sub">${esc(frDate(o.date))} à ${esc(eur(o.price))}</span></td>
              <td class="num">${esc(eur(o.amount))}</td>
              <td class="num">${esc(eur(o.employer_amount))}<span class="sub">− ${esc(eur(o.social_tax))} prél. sociaux</span></td>
              <td class="num">${esc(qty(o.shares))}</td><td>${esc(frDate(o.available_on))}</td>
              <td>${o.exists ? '<span class="badge">déjà enregistré</span>' : '<span class="badge badge-accent">nouveau</span>'}</td></tr>`).join('')}</tbody>
          </table></div>` : '<p class="dim">Aucun versement dans cet avis.</p>';
        const unknown = p.unknown_funds.length
            ? `<div class="notice notice-danger">Fonds inconnus : ${esc(p.unknown_funds.join(', '))}. Import impossible.</div>` : '';
        const check = p.check ? `<h4>Situation au ${esc(frDate(p.situation_date))}</h4>${verdict(p.check)}${resultTable(p.check)}${adjustBox(p.check)}` : '';
        const fd2 = await modal({ title: 'Importer un avis Natixis', wide: true,
                                  ok: p.unknown_funds.length ? null : 'Importer', body: unknown + ops + check });
        if (!fd2) return;
        const form2 = new FormData();
        form2.append('file', file);
        form2.append('adjust', fd2.get('adjust') === 'on' ? 'true' : 'false');
        const r = await api.upload('/pee/import', form2);
        toast(`${r.added} versement(s) ajouté(s)` + (r.check ? `, pointage ${r.check.status === 'ok' ? 'concordant' : 'avec écart'}.` : '.'));
        changed();
    } catch (e) { fail(e); }
}
