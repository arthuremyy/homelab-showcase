/**
 * HomeLab Auth Guard
 * Vérifie l'authentification sur chaque page protégée via le cookie HttpOnly.
 * À inclure sur TOUTES les pages sauf login.html
 */
(function() {
    function redirectToLogin() {
        const currentPage = window.location.pathname;
        window.location.href = '/login.html?redirect=' + encodeURIComponent(currentPage);
    }

    async function checkAuth() {
        try {
            const response = await fetch('/api/auth/check', {
                credentials: 'include'
            });

            if (!response.ok) {
                redirectToLogin();
                return;
            }

            const data = await response.json();
            // Rendre le body visible (il est caché par défaut via CSS)
            document.body.classList.add('authenticated');

            // Exposer le nom d'utilisateur globalement (pas le token)
            window.authUser = data.username;

            // Dispatch event pour que les autres scripts sachent que l'auth est OK
            window.dispatchEvent(new Event('auth-ready'));
        } catch (e) {
            redirectToLogin();
        }
    }

    // Fonction de logout globale
    window.logout = async function() {
        try {
            await fetch('/api/auth/logout', {
                method: 'POST',
                credentials: 'include'
            });
        } catch(e) {}
        window.location.href = '/login.html';
    };

    // Helper pour les requêtes authentifiées — utilise le cookie HttpOnly automatiquement
    window.authFetch = function(url, options = {}) {
        options.credentials = 'include';
        return fetch(url, options);
    };

    // Vérifier l'auth au chargement
    checkAuth();
})();
