// Test de régression XSS du frontend.
// Règle : après esc(), il ne doit rester AUCUN caractère de balisage brut.
// Vérifier la présence de « onerror= » ne suffit pas — échappé, c'est du texte inerte.
globalThis.window = { location: { origin: 'https://jobs.example.com' } };
const here = new URL('.', import.meta.url).pathname;
const { esc, safeUrl } = await import(here + '../frontend/assets/js/fmt.js');

let fail = 0;
const check = (ok, msg) => { console.log(`  ${ok ? '✅' : '❌ ÉCHEC'}  ${msg}`); if (!ok) fail++; };

console.log('--- esc() : aucun métacaractère brut ne survit ---');
for (const p of ['<script>alert("XSS")</script>', '"><img src=x onerror=alert(1)>',
                 "'; alert(1); //", '</h3><svg onload=alert(1)>', '<a href="x">&']) {
  const out = esc(p);
  // Le seul & autorisé est celui qui ouvre une entité que nous avons produite.
  const raw = /[<>"']/.test(out) || /&(?!(amp|lt|gt|quot|#39);)/.test(out);
  check(!raw, `${JSON.stringify(p).slice(0, 40).padEnd(42)} -> ${JSON.stringify(out).slice(0, 52)}`);
}

console.log('--- safeUrl() : seuls http(s) passent ---');
for (const [u, mustBlock] of [['javascript:alert(1)', true], ['data:text/html,<script>', true],
                              ['vbscript:msgbox', true], ['https://candidat.francetravail.fr/offres/recherche/detail/1', false]]) {
  const out = safeUrl(u);
  check(mustBlock ? out === '#' : out.startsWith('https://'),
        `${u.slice(0, 34).padEnd(36)} -> ${out.slice(0, 40)}`);
}

console.log('--- attribut HTML : impossible de sortir des guillemets ---');
const attr = `data-offer="${esc('1" onclick="alert(1)')}"`;
check(!/"\s*onclick/.test(attr), attr.slice(0, 62));

console.log(fail ? `\n${fail} échec(s)` : '\nTous les tests XSS passent.');
process.exit(fail ? 1 : 0);
