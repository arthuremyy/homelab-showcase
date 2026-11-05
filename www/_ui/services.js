/* HomeLab UI — manifeste unique de navigation.
 *
 * Ajouter un service = ajouter une entrée ici, puis scripts/sync-ui.sh.
 * La barre latérale et l'accueil sont générés depuis cette liste.
 *
 *   kind      internal  application maison, ouverte dans le même onglet (barre latérale commune)
 *             external  service tiers, ouvert dans un nouvel onglet
 *   scope     public    joignable partout (Cloudflare)
 *             vpn       joignable seulement via Tailscale
 *   newTab    force l'ouverture dans un nouvel onglet (application maison sans barre commune)
 *   container nom du conteneur Docker pour la pastille d'état (null : pas de pastille)
 */
window.SF_SERVICES = [
    { id: 'home',       label: 'Accueil',      icon: 'home',      kind: 'home',     scope: 'vpn',    url: 'https://dashboard.example.com/' },

    { id: 'budget',     label: 'Budget',       icon: 'wallet',    kind: 'internal', scope: 'vpn',    url: 'https://budget.example.com/',
      desc: 'Comptes, dépenses et reste à vivre', container: 'budget' },
    { id: 'monitoring', label: 'Monitoring',   icon: 'activity',  kind: 'internal', scope: 'vpn',    url: 'https://monitoring.example.com/',
      desc: 'Métriques système en temps réel', container: 'dashboard-api' },
    { id: 'capital',    label: 'Capital',      icon: 'chart',     kind: 'internal', scope: 'vpn',    url: 'https://capital.example.com/',
      desc: 'Portefeuille, performance et briefing', container: 'capital-control' },
    { id: 'jobs',       label: 'Job Radar',    icon: 'briefcase', kind: 'internal', scope: 'vpn',    url: 'https://jobs.example.com/',
      desc: 'Veille d’offres cyber', container: 'job-radar' },

];
