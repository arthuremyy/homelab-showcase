// Test de régression XSS du frontend Budget.
// Règle : après esc(), il ne doit rester AUCUN caractère de balisage brut.
// Les libellés bancaires sont des données externes : un commerçant choisit son libellé.
const here = new URL('.', import.meta.url).pathname;
const { esc, opTitle } = await import(here + '../frontend/assets/js/fmt.js');

let fail = 0;
const check = (ok, msg) => { console.log(`  ${ok ? '✅' : '❌ ÉCHEC'}  ${msg}`); if (!ok) fail++; };

console.log('--- esc() : aucun métacaractère brut ne survit ---');
for (const p of ['<script>alert("XSS")</script>', '"><img src=x onerror=alert(1)>',
                 "'; alert(1); //", 'CARTE X1234 <svg onload=alert(1)>', '<a href="x">&']) {
  const out = esc(p);
  const raw = /[<>"']/.test(out) || /&(?!(amp|lt|gt|quot|#39);)/.test(out);
  check(!raw, `${JSON.stringify(p).slice(0, 40).padEnd(42)} -> ${JSON.stringify(out).slice(0, 52)}`);
}

console.log('--- attribut HTML : impossible de sortir des guillemets ---');
const attr = `data-cat="${esc('1" onclick="alert(1)')}"`;
check(!/"\s*onclick/.test(attr), attr.slice(0, 62));

console.log('--- opTitle() : nettoie sans perdre le libellé ---');
check(opTitle({ label: 'CARTE X1234 01/10 CARREFOUR CITY' }) === 'CARREFOUR CITY', 'préfixe carte retiré');
check(opTitle({ label: 'PRLV SEPA FREE MOBILE' }) === 'FREE MOBILE', 'préfixe prélèvement retiré');
check(opTitle({ label: 'X', counterparty: 'ACME' }) === 'ACME', 'contrepartie prioritaire');

console.log(fail ? `\n${fail} échec(s)` : '\nTous les tests XSS passent.');
process.exit(fail ? 1 : 0);
