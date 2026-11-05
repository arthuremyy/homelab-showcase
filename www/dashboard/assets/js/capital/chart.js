// Courbe « valeur et versé » en SVG. Couleurs : jetons du thème (aucune couleur en dur).
// Valeur = trait plein --chart-1 ; Versé = pointillé --text-3 (référence, pas une série concurrente).
import { esc, eur, frDate } from './fmt.js';

const H = 260, PAD = { t: 12, r: 12, b: 26, l: 64 };

function ticks(min, max, n = 4) {
    const span = max - min || 1;
    const step0 = span / n;
    const mag = 10 ** Math.floor(Math.log10(step0));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0);
    const out = [];
    for (let v = Math.floor(min / step) * step; v <= max + step / 2; v += step) out.push(v);
    return out;
}

/** Dessine dans `host` ; `points` = [{date, total_value, total_invested}]. */
export function valueChart(host, points) {
    if (points.length < 2) {
        host.innerHTML = '<div class="empty">Pas encore assez d’historique.</div>';
        return;
    }
    const W = Math.max(host.clientWidth, 280);
    const vals = points.flatMap((p) => [p.total_value, p.total_invested]);
    const yt = ticks(Math.min(...vals), Math.max(...vals));
    const y0 = yt[0], y1 = yt[yt.length - 1];
    const x = (i) => PAD.l + (i / (points.length - 1)) * (W - PAD.l - PAD.r);
    const y = (v) => PAD.t + (1 - (v - y0) / (y1 - y0 || 1)) * (H - PAD.t - PAD.b);
    const line = (key) => points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`).join('');
    const months = [];
    points.forEach((p, i) => {
        if (i && p.date.slice(0, 7) !== points[i - 1].date.slice(0, 7)) months.push(i);
    });
    const stepM = Math.ceil(months.length / Math.max(1, Math.floor((W - PAD.l) / 70)));
    const monthLabel = (i) => new Date(points[i].date + 'T12:00:00')
        .toLocaleDateString('fr-FR', { month: 'short' }).replace('.', '');

    host.innerHTML = `
      <svg class="chart" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img"
           aria-label="Évolution de la valeur et du montant versé">
        ${yt.map((v) => `<line class="grid" x1="${PAD.l}" x2="${W - PAD.r}" y1="${y(v)}" y2="${y(v)}"/>
          <text class="axis" x="${PAD.l - 8}" y="${y(v) + 4}" text-anchor="end">${esc(eur(v, { round: true }))}</text>`).join('')}
        ${months.filter((_, k) => k % stepM === 0).map((i) =>
            `<text class="axis" x="${x(i)}" y="${H - 6}" text-anchor="middle">${esc(monthLabel(i))}</text>`).join('')}
        <path class="invested" d="${line('total_invested')}"/>
        <path class="value" d="${line('total_value')}"/>
        <g class="cursor" hidden><line y1="${PAD.t}" y2="${H - PAD.b}"/><circle r="4"/></g>
        <rect class="hit" x="${PAD.l}" y="0" width="${W - PAD.l - PAD.r}" height="${H}"/>
      </svg>
      <div class="chart-tip" hidden></div>`;

    const svg = host.querySelector('svg'), cursor = svg.querySelector('.cursor'), tip = host.querySelector('.chart-tip');
    const hit = svg.querySelector('.hit');
    const show = (clientX) => {
        const r = svg.getBoundingClientRect();
        const i = Math.round(((clientX - r.left) * (W / r.width) - PAD.l) / (W - PAD.l - PAD.r) * (points.length - 1));
        const p = points[Math.max(0, Math.min(points.length - 1, i))];
        const k = points.indexOf(p);
        cursor.hidden = false;
        cursor.querySelector('line').setAttribute('x1', x(k));
        cursor.querySelector('line').setAttribute('x2', x(k));
        cursor.querySelector('circle').setAttribute('cx', x(k));
        cursor.querySelector('circle').setAttribute('cy', y(p.total_value));
        const gain = p.total_value - p.total_invested;
        tip.innerHTML = `<b>${esc(frDate(p.date))}</b>
          <span><i class="sw value"></i>Valeur ${esc(eur(p.total_value))}</span>
          <span><i class="sw invested"></i>Versé ${esc(eur(p.total_invested))}</span>
          <span class="${gain >= 0 ? 'pos' : 'neg'}">Gain ${esc(eur(gain, { sign: true }))}</span>`;
        tip.hidden = false;
        const left = (x(k) / W) * r.width;
        tip.style.left = `${Math.min(Math.max(left - tip.offsetWidth / 2, 0), r.width - tip.offsetWidth)}px`;
    };
    hit.addEventListener('pointermove', (e) => show(e.clientX));
    hit.addEventListener('pointerdown', (e) => show(e.clientX));
    hit.addEventListener('pointerleave', () => { cursor.hidden = true; tip.hidden = true; });
}
