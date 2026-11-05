// Captures des cinq pages, en clair et en sombre, sur deux largeurs.
//
// Existe parce que relire du CSS ne suffit pas : le titre qui n'était pas en
// serif, le dépliant affiché en tofu et la carte qui débordait sur mobile
// n'étaient visibles qu'en image.
//
//   cd /tmp && npm install playwright && npx playwright install chromium
//   PLAYWRIGHT_PATH=/tmp/node_modules/playwright/index.mjs \
//   SFAUTH="$TOKEN" node www/job-radar/tests/shoot.mjs
//
// playwright reste hors dépôt : il ne sert qu'à la vérification.

// Captures réelles de chaque page, en clair et en sombre, sur trois largeurs.
const { chromium } = await import(process.env.PLAYWRIGHT_PATH || 'playwright');

const TOKEN = process.env.SFAUTH;
const OUT = process.env.OUT || '/tmp/job-radar-shots';
const TAG = process.env.TAG || '';

const browser = await chromium.launch({ args: ['--ignore-certificate-errors'] });

async function shoot(theme, width, height, pages) {
    const ctx = await browser.newContext({
        viewport: { width, height },
        ignoreHTTPSErrors: true,
        deviceScaleFactor: 2,
        colorScheme: theme === 'dark' ? 'dark' : 'light',
    });
    await ctx.addCookies([{ name: 'sfauth', value: TOKEN, domain: 'jobs.example.com', path: '/' }]);
    // Résolution DNS forcée vers l'IP Tailscale.
    await ctx.route('**/*', (route) => route.continue());
    const page = await ctx.newPage();
    const errs = [];
    page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
    page.on('pageerror', (e) => errs.push('pageerror: ' + e.message));

    for (const [nom, hash, prep] of pages) {
        // Rechargement forcé : goto sur une URL qui ne diffère que par le
        // fragment ne recharge pas le document.
        await page.goto('about:blank');
        await page.goto('https://jobs.example.com/' + hash, { waitUntil: 'networkidle' });
        await page.waitForTimeout(900);
        if (prep) await prep(page);
        await page.waitForTimeout(500);
        const f = `${OUT}/${TAG}${nom}-${theme}-${width}.png`;
        await page.screenshot({ path: f, fullPage: false });
        console.log('  ' + f.split('/').pop());
    }
    await ctx.close();
    return errs;
}

const PAGES = [
    ['00-aujourdhui', '#/today',  null],
    ['01-trier',      '#/deck',   null],
    ['02-detail',     '#/deck',   async (p) => { await p.keyboard.press('d'); }],
    ['03-offres',     '#/liste',  null],
    ['04-candidatures', '#/suivi', null],
    ['05-reglages',   '#/profil', null],
];

const all = [];
for (const theme of ['light', 'dark']) {
    for (const w of [1280, 480]) {
        all.push(...await shoot(theme, w, w === 480 ? 900 : 900, PAGES));
    }
}
await browser.close();
if (all.length) { console.log('\nErreurs console :'); [...new Set(all)].slice(0,8).forEach(e => console.log('  ' + e)); }
else console.log('\n✅ aucune erreur console');
