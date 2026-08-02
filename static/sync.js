/**
 * Bascule le stockage du suivi Leitner entre localStorage (gratuit) et
 * Supabase via l'API Flask (premium, synchronisé multi-appareils).
 *
 * Principe :
 *  - Utilisateur gratuit  -> toutes les fonctions leitner*() de leitner.js
 *    s'exécutent normalement sur localStorage, rien ne change.
 *  - Utilisateur premium  -> au chargement, on récupère les données
 *    Supabase et on les FUSIONNE avec le cache localStorage (en cas de
 *    conflit sur un même puzzle, Supabase gagne car plus susceptible de
 *    refléter un autre appareil). Les entrées présentes UNIQUEMENT en
 *    local (jamais encore synchronisées, ex. juste après le passage en
 *    premium) sont conservées ET renvoyées vers Supabase, pour ne jamais
 *    perdre d'historique existant. Chaque écriture (track/record/set-fen)
 *    est ensuite répercutée à la fois en local et sur le serveur.
 *
 * Ce module doit être chargé APRÈS leitner.js.
 */

let SYNC_IS_PREMIUM = false;
let SYNC_READY = null; // Promise résolue une fois le statut connu (et les données fusionnées si premium)

function syncInit() {
  if (SYNC_READY) return SYNC_READY;

  SYNC_READY = fetch('/api/leitner/status')
    .then(r => r.ok ? r.json() : { premium: false })
    .then(status => {
      SYNC_IS_PREMIUM = !!status.premium;
      if (!SYNC_IS_PREMIUM) return;

      // Premium : on fusionne Supabase et le cache local, sans jamais
      // écraser silencieusement des données locales non encore envoyées.
      return fetch('/api/leitner/data')
        .then(r => r.ok ? r.json() : null)
        .then(payload => {
          const serverData = (payload && payload.data) || {};
          const localData = leitnerLoad();

          // Union : le serveur gagne sur les clés en conflit, mais toute
          // entrée locale absente du serveur est conservée.
          const merged = Object.assign({}, localData, serverData);
          leitnerSave(merged);

          // Renvoie vers Supabase les entrées qui n'y étaient pas encore
          // (ex. juste après le passage en premium) pour ne rien perdre.
          const missingOnServer = {};
          Object.keys(localData).forEach(id => {
            if (!(id in serverData)) missingOnServer[id] = localData[id];
          });
          if (Object.keys(missingOnServer).length > 0) {
            fetch('/api/leitner/push', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ entries: missingOnServer }),
            }).catch(() => {});
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
