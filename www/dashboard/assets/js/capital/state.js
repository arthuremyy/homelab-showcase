// État partagé : résumé du portefeuille (positions, comptes) et registre des actifs.
import { api } from './api.js';

export const state = { summary: null, assets: [] };

export async function load() {
    const [summary, assets] = await Promise.all([api.get('/portfolio'), api.get('/assets')]);
    state.summary = summary;
    state.assets = assets.assets;
    document.dispatchEvent(new CustomEvent('loaded'));
    return summary;
}
