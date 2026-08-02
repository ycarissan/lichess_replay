/**
 * Répétition espacée — Système de Leitner (5 boîtes) via localStorage.
 *
 * Boîte 1 : à revoir le lendemain (échec récent)
 * Boîte 2 : dans 3 jours
 * Boîte 3 : dans 7 jours
 * Boîte 4 : dans 16 jours
 * Boîte 5 : dans 35 jours (quasi maîtrisé)
 *
 * Règle : bon coup trouvé sans aide -> +1 boîte (max 5).
 *         Solution révélée / coup faux -> retour boîte 1.
 *
 * Données 100% côté navigateur : propres à cet appareil, effacées si le
 * cache est vidé. Pas de synchronisation entre appareils.
 */

const LEITNER_STORAGE_KEY = 'lichess_puzzle_leitner_v1';

// Intervalle en jours associé à chaque boîte (index 1 à 5 ; 0 inutilisé).
const LEITNER_INTERVALS_DAYS = [null, 1, 3, 7, 16, 35];
const LEITNER_MAX_BOX = LEITNER_INTERVALS_DAYS.length - 1;

function leitnerLoad() {
  try {
    const raw = localStorage.getItem(LEITNER_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch (e) {
    console.error('Leitner: lecture localStorage impossible', e);
    return {};
  }
}

function leitnerSave(data) {
  try {
    localStorage.setItem(LEITNER_STORAGE_KEY, JSON.stringify(data));
  } catch (e) {
    console.error('Leitner: écriture localStorage impossible (quota plein ?)', e);
  }
}

function leitnerNextReviewDate(box) {
  const days = LEITNER_INTERVALS_DAYS[box];
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString();
}

/** Met à jour uniquement le FEN d'un puzzle déjà suivi (sans toucher au reste). */
function leitnerSetFen(puzzleId, fen) {
  const data = leitnerLoad();
  if (data[puzzleId] && fen) {
    data[puzzleId].fen = fen;
    leitnerSave(data);
  }
}

function leitnerHasPuzzle(puzzleId) {
  const data = leitnerLoad();
  return Object.prototype.hasOwnProperty.call(data, puzzleId);
}

/**
 * Enregistre un puzzle raté s'il n'existe pas encore dans le suivi.
 * Un puzzle nouvellement raté part en boîte 1, dû immédiatement.
 */
function leitnerTrackFailedPuzzle(puzzleId, meta) {
  const data = leitnerLoad();
  if (!data[puzzleId]) {
    data[puzzleId] = {
      box: 1,
      nextReview: new Date().toISOString(), // dû tout de suite
      rating: (meta && meta.rating) || null,
      themes: (meta && meta.themes) || [],
      fen: (meta && meta.fen) || null,
      history: []
    };
    leitnerSave(data);
  } else if (meta && meta.fen && !data[puzzleId].fen) {
    // Complète le FEN s'il manquait (ancien puzzle suivi avant cet ajout).
    data[puzzleId].fen = meta.fen;
    leitnerSave(data);
  }
  return data[puzzleId];
}

/**
 * Enregistre le résultat d'une tentative de révision.
 * success = true  -> le joueur a trouvé la solution sans aide -> boîte +1
 * success = false -> solution révélée ou coup faux             -> retour boîte 1
 */
function leitnerRecordResult(puzzleId, success, meta) {
  const data = leitnerLoad();
  const entry = data[puzzleId] || {
    box: 1, rating: (meta && meta.rating) || null,
    themes: (meta && meta.themes) || [], history: []
  };

  entry.box = success ? Math.min(entry.box + 1, LEITNER_MAX_BOX) : 1;
  entry.nextReview = leitnerNextReviewDate(entry.box);
  entry.history.push({ date: new Date().toISOString(), success });

  data[puzzleId] = entry;
  leitnerSave(data);
  return entry;
}

/** Puzzles dont la date de révision est aujourd'hui ou passée. */
function leitnerGetDuePuzzles() {
  const data = leitnerLoad();
  const now = new Date();
  return Object.entries(data)
    .filter(([, e]) => new Date(e.nextReview) <= now)
    .map(([id, e]) => ({ id, ...e }))
    .sort((a, b) => new Date(a.nextReview) - new Date(b.nextReview));
}

/** Tous les puzzles suivis (pour affichage/statistiques). */
function leitnerGetAllPuzzles() {
  const data = leitnerLoad();
  return Object.entries(data)
    .map(([id, e]) => ({ id, ...e }))
    .sort((a, b) => new Date(a.nextReview) - new Date(b.nextReview));
}

/** Compte les occurrences de chaque thème parmi tous les puzzles suivis. */
function leitnerGetThemeCounts() {
  const counts = {};
  leitnerGetAllPuzzles().forEach(p => {
    (p.themes || []).forEach(t => {
      counts[t] = (counts[t] || 0) + 1;
    });
  });
  return counts;
}

function leitnerFormatNextReview(iso) {
  const d = new Date(iso);
  const now = new Date();
  const diffDays = Math.ceil((d - now) / (1000 * 60 * 60 * 24));
  if (diffDays <= 0) return 'à réviser maintenant';
  if (diffDays === 1) return 'demain';
  return `dans ${diffDays} jours`;
}
