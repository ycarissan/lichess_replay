/**
 * Bascule le stockage du suivi Leitner entre localStorage (gratuit) et
 * Supabase via l'API Flask (premium, synchronisé multi-appareils).
 *
 * Principe :
 *  - Utilisateur gratuit  -> toutes les fonctions leitner*() de leitner.js
 *    s'exécutent normalement sur localStorage, rien ne change.
 *  - Utilisateur premium  -> au chargement, on récupère les données
 *    Supabase et on écrase le cache localStorage local avec (source de
 *    vérité = Supabase). Chaque écriture (track/record/set-fen) est ensuite
 *    répercutée à la fois en local (cache rapide, lecture instantanée) et
 *    sur le serveur (pour la synchro sur les autres appareils).
 *
 * Ce module doit être chargé APRÈS leitner.js.
 */

let SYNC_IS_PREMIUM = false;
let SYNC_READY = null; // Promise résolue une fois le statut connu (et les données tirées si premium)

function syncInit() {
  if (SYNC_READY) return SYNC_READY;

  SYNC_READY = fetch('/api/leitner/status')
    .then(r => r.ok ? r.json() : { premium: false })
    .then(status => {
      SYNC_IS_PREMIUM = !!status.premium;
      if (!SYNC_IS_PREMIUM) return;

      // Premium : Supabase fait autorité, on rafraîchit le cache local.
      return fetch('/api/leitner/data')
        .then(r => r.ok ? r.json() : null)
        .then(payload => {
          if (payload && payload.data) {
            leitnerSave(payload.data);
          }
        });
    })
    .catch(() => {
      SYNC_IS_PREMIUM = false;
    });

  return SYNC_READY;
}

/** Enveloppe leitnerTrackFailedPuzzle : miroir Supabase si premium. */
function syncTrackFailedPuzzle(puzzleId, meta) {
  const entry = leitnerTrackFailedPuzzle(puzzleId, meta);
  syncInit().then(() => {
    if (!SYNC_IS_PREMIUM) return;
    fetch('/api/leitner/track', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ puzzle_id: puzzleId, ...meta }),
    }).catch(() => {});
  });
  return entry;
}

/** Enveloppe leitnerRecordResult : miroir Supabase si premium. */
function syncRecordResult(puzzleId, success, meta) {
  const entry = leitnerRecordResult(puzzleId, success, meta);
  syncInit().then(() => {
    if (!SYNC_IS_PREMIUM) return;
    fetch('/api/leitner/record', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ puzzle_id: puzzleId, success, ...meta }),
    }).catch(() => {});
  });
  return entry;
}

/** Enveloppe leitnerSetFen : miroir Supabase si premium. */
function syncSetFen(puzzleId, fen) {
  leitnerSetFen(puzzleId, fen);
  syncInit().then(() => {
    if (!SYNC_IS_PREMIUM) return;
    fetch('/api/leitner/set-fen', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ puzzle_id: puzzleId, fen }),
    }).catch(() => {});
  });
}
