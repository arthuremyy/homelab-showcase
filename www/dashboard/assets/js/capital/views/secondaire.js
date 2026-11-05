// Secondaire, replié par défaut : briefing IA de la semaine et alertes de prix.
import { api } from '../api.js';
import { esc, eur, since } from '../fmt.js';
import { modal, toast, fail } from '../ui.js';
import { state } from '../state.js';

const SENTIMENT = { bullish: ['Haussier', 'badge-success'], bearish: ['Baissier', 'badge-danger'],
                    neutral: ['Neutre', ''] };
const KIND = { price_above: 'Cours au-dessus de', price_below: 'Cours en dessous de', pct_day: 'Variation du jour ≥ ±' };

async function briefingHtml() {
    const b = await api.get('/briefing');
    if (b.status !== 'ok') return `<p class="dim">${esc(b.message)}</p>`;
    const c = b.content;
    const [label, badge] = SENTIMENT[c.market_sentiment] || [c.market_sentiment, ''];
    return `<p class="dim">${esc(b.date)} · <span class="badge ${badge}">${esc(label)}</span></p>
      <p>${esc(c.summary)}</p>
      ${c.focus_du_jour ? `<p><b>À surveiller.</b> ${esc(c.focus_du_jour)}</p>` : ''}
      ${c.conseil_du_jour ? `<p><b>Conseil.</b> ${esc(c.conseil_du_jour)}</p>` : ''}`;
}

async function alertsHtml() {
    const [rules, events] = await Promise.all([api.get('/alerts/rules'), api.get('/alerts/events?all=true&limit=5')]);
    const ruleRows = rules.rules.map((r) => `<li class="row">
        <span class="grow">${esc(r.asset_name || r.isin)}<span class="sub">${esc(KIND[r.kind])} ${esc(r.kind === 'pct_day' ? `${r.threshold} %` : eur(r.threshold))}</span></span>
        <button class="btn btn-sm btn-ghost" data-del-rule="${r.id}" aria-label="Supprimer l’alerte">Supprimer</button></li>`).join('');
    const eventRows = events.events.map((e) => `<li class="row"><span class="grow">${esc(e.message)}</span>
        <span class="dim">${esc(since(e.fired_at.replace(' ', 'T') + 'Z'))}</span></li>`).join('');
    return `<ul class="rows">${ruleRows || '<li class="row dim">Aucune alerte.</li>'}</ul>
      <button class="btn btn-sm" data-add-rule>Ajouter une alerte</button>
      ${eventRows ? `<h4>Derniers déclenchements</h4><ul class="rows">${eventRows}</ul>` : ''}
      <p class="dim small">Les alertes partent sur Discord.</p>`;
}

export async function render(host) {
    host.innerHTML = `
      <details class="card fold"><summary class="card-header"><h3 class="card-title">Briefing de la semaine</h3></summary>
        <div class="card-body stack" data-briefing><p class="dim">Chargement…</p></div>
        <div class="card-body"><button class="btn btn-sm" data-generate>Générer maintenant</button></div></details>
      <details class="card fold"><summary class="card-header"><h3 class="card-title">Alertes de prix</h3></summary>
        <div class="card-body stack" data-alerts><p class="dim">Chargement…</p></div></details>`;
    briefingHtml().then((h) => { host.querySelector('[data-briefing]').innerHTML = h; })
        .catch((e) => { host.querySelector('[data-briefing]').innerHTML = `<p class="neg">${esc(e.message)}</p>`; });
    refreshAlerts(host);
}

function refreshAlerts(host) {
    alertsHtml().then((h) => { host.querySelector('[data-alerts]').innerHTML = h; })
        .catch((e) => { host.querySelector('[data-alerts]').innerHTML = `<p class="neg">${esc(e.message)}</p>`; });
}

async function addRule(host) {
    const held = state.summary.positions.filter((p) => !p.closed);
    const fd = await modal({ title: 'Nouvelle alerte', ok: 'Créer', body: `
      <label class="field"><span>Actif</span><select class="select" name="isin">
        ${held.map((p) => `<option value="${esc(p.isin)}">${esc(p.name)} — ${esc(eur(p.price_eur))}</option>`).join('')}</select></label>
      <label class="field"><span>Condition</span><select class="select" name="kind">
        ${Object.entries(KIND).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('')}</select></label>
      <label class="field"><span>Seuil (€ ou %)</span><input class="input" name="threshold" inputmode="decimal" required></label>` });
    if (!fd) return;
    try {
        await api.post('/alerts/rules', { isin: fd.get('isin'), kind: fd.get('kind'),
                                          threshold: Number(String(fd.get('threshold')).replace(',', '.')) });
        toast('Alerte créée.');
        refreshAlerts(host);
    } catch (e) { fail(e); }
}

export function wire(root) {
    root.addEventListener('click', async (e) => {
        const host = document.getElementById('secondary');
        if (!host) return;
        if (e.target.closest('[data-add-rule]')) addRule(host);
        const del = e.target.closest('[data-del-rule]');
        if (del) {
            try { await api.del(`/alerts/rules/${del.dataset.delRule}`); refreshAlerts(host); } catch (err) { fail(err); }
        }
        const gen = e.target.closest('[data-generate]');
        if (gen) {
            gen.disabled = true;
            gen.textContent = 'Génération… (jusqu’à 2 min)';
            try {
                const r = await api.post('/briefing/generate');
                if (r.status !== 'ok') throw new Error(r.error || 'Échec de la génération');
                host.querySelector('[data-briefing]').innerHTML = await briefingHtml();
            } catch (err) { fail(err); }
            finally { gen.disabled = false; gen.textContent = 'Générer maintenant'; }
        }
    });
}
