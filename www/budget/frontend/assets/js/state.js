// État partagé entre les vues : mois affiché, filtre de catégorie transmis à « Opérations ».
import { currentMonth } from './fmt.js';

export const state = {
    month: currentMonth(),
    category: '',          // filtre pré-rempli depuis « Ce mois »
};

/** Navigation entre onglets sans dépendance circulaire avec main.js. */
export const goto = (tab) => document.dispatchEvent(new CustomEvent('goto', { detail: tab }));
export const changed = () => document.dispatchEvent(new CustomEvent('data-changed'));
