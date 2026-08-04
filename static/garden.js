/**
 * Jardin de puzzles : chaque puzzle suivi est une plante dont le stade de
 * croissance reflète sa boîte Leitner (1 = graine, 5 = plusieurs roses).
 * Les sprites sont des SVG statiques (static/garden/stage-N-*.svg) inlinés
 * dans le DOM (pas de <img>) pour pouvoir animer le vent en CSS sur les
 * éléments internes.
 */

const GARDEN_STAGE_FILES = {
  1: '/static/garden/stage-1-graine.svg',
  2: '/static/garden/stage-2-plantule.svg',
  3: '/static/garden/stage-3-bourgeon.svg',
  4: '/static/garden/stage-4-rose.svg',
  5: '/static/garden/stage-5-roses.svg',
};

const GARDEN_STAGE_LABELS = {
  1: 'Graine',
  2: 'Plantule',
  3: 'Bourgeon',
  4: 'Rose',
  5: 'Plusieurs roses',
};

const gardenStageCache = {};

function gardenLoadStageTemplate(stage) {
  if (gardenStageCache[stage]) return Promise.resolve(gardenStageCache[stage]);
  return fetch(GARDEN_STAGE_FILES[stage])
    .then(r => r.text())
    .then(svgText => {
      gardenStageCache[stage] = svgText;
      return svgText;
    });
}

function gardenStageForBox(box) {
  return Math.min(5, Math.max(1, box || 1));
}

/** Précharge les 5 gabarits une bonne fois pour toutes. */
function gardenPreloadAllStages() {
  return Promise.all([1, 2, 3, 4, 5].map(gardenLoadStageTemplate));
}

/**
 * Construit la scène du jardin dans `containerEl` à partir d'une liste de
 * puzzles suivis (même format que leitnerGetAllPuzzles()).
 */
function renderGarden(containerEl, puzzles) {
  containerEl.innerHTML = '';
  if (!puzzles || puzzles.length === 0) return Promise.resolve();

  return gardenPreloadAllStages().then(() => {
    puzzles.forEach((p) => {
      const stage = gardenStageForBox(p.box);
      const wrapper = document.createElement('a');
      wrapper.className = `garden-plant garden-stage-${stage}`;
      wrapper.href = `/replay/${p.id}`;
      wrapper.title = `Puzzle ${p.id} — ${GARDEN_STAGE_LABELS[stage]} (boîte ${p.box}/5)`;
      wrapper.innerHTML = gardenStageCache[stage];

      // Vent léger : décalage aléatoire de durée/phase par plante, pour
      // qu'elles n'oscillent pas toutes exactement en même temps.
      const swayGroup = wrapper.querySelector('.plant-sway');
      if (swayGroup) {
        const duration = (3.2 + Math.random() * 2.2).toFixed(2);
        const delay = (Math.random() * 3).toFixed(2);
        swayGroup.style.animationDuration = `${duration}s`;
        swayGroup.style.animationDelay = `-${delay}s`;
      }

      containerEl.appendChild(wrapper);
    });
  });
}
