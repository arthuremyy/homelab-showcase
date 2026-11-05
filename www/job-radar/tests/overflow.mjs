// Contrôle de débordement horizontal, de 320 à 1920 px.
//
// Existe parce que relire du CSS ne suffit pas : le titre qui n'était pas en
// serif, le dépliant affiché en tofu et la carte qui débordait sur mobile
// n'étaient visibles qu'en image.
//
//   cd /tmp && npm install playwright && npx playwright install chromium
//   PLAYWRIGHT_PATH=/tmp/node_modules/playwright/index.mjs \
//   SFAUTH="$TOKEN" node www/job-radar/tests/overflow.mjs
//
// playwright reste hors dépôt : il ne sert qu'à la vérification.

const { chromium } = await import(process.env.PLAYWRIGHT_PATH || 'playwright');
const b = await chromium.launch({ args: ['--ignore-certificate-errors'] });
let bad = 0;
for (const w of [320, 375, 480, 768, 1024, 1440, 1920]) {
  const ctx = await b.newContext({ viewport: { width: w, height: 900 }, ignoreHTTPSErrors: true });
  await ctx.addCookies([{ name: 'sfauth', value: process.env.SFAUTH, domain: 'jobs.example.com', path: '/' }]);
  const p = await ctx.newPage();
  for (const [nom, h] of [['aujourdhui','#/today'],['trier','#/deck'],['offres','#/liste'],['candidatures','#/suivi'],['reglages','#/profil']]) {
    await p.goto('about:blank');
    await p.goto('https://jobs.example.com/' + h, { waitUntil: 'networkidle' });
    await p.waitForTimeout(700);
    const r = await p.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
      coupables: [...document.querySelectorAll('*')]
        .filter((e) => e.getBoundingClientRect().right > document.documentElement.clientWidth + 1)
        .slice(0, 3).map((e) => e.className || e.tagName),
    }));
    const ok = r.scroll <= r.client + 1;
    if (!ok) { bad++; console.log(`  ❌ ${w}px ${nom} : ${r.scroll} > ${r.client} — ${r.coupables.join(', ')}`); }
  }
  await ctx.close();
  console.log(`  ${w}px : ${bad ? 'voir ci-dessus' : 'aucun débordement'}`);
}
await b.close();
console.log(bad ? `\n❌ ${bad} débordement(s)` : '\n✅ aucun débordement horizontal, de 320 à 1920 px');
process.exit(bad ? 1 : 0);
