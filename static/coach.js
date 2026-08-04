/**
 * Autocomplétion de recherche d'élève sur la page de détail d'une classe.
 * Interroge /api/students/search?q=... (élèves existants de l'entraîneur
 * en priorité, puis cache local de la base FIDE — jamais d'appel direct à
 * ratings.fide.com depuis le navigateur).
 */
(function () {
  const input = document.getElementById("student-search-input");
  const resultsList = document.getElementById("student-search-results");
  if (!input || !resultsList) return;

  const nameField = document.getElementById("add-name");
  const idField = document.getElementById("add-student-id");
  const fideIdField = document.getElementById("add-fide-id");
  const federationField = document.getElementById("add-federation");
  const titleField = document.getElementById("add-title");

  let debounceTimer = null;
  let currentAbortController = null;

  function clearResults() {
    resultsList.innerHTML = "";
    resultsList.hidden = true;
  }

  function renderResults(items) {
    resultsList.innerHTML = "";
    if (!items.length) {
      clearResults();
      return;
    }

    items.forEach((item) => {
      const li = document.createElement("li");
      const badge = item.source === "existing" ? "👤 déjà ajouté" : "🌐 FIDE";
      const details = [item.title, item.federation].filter(Boolean).join(" · ");
      li.innerHTML = `<strong>${item.name}</strong> <span class="hint">${details} — ${badge}</span>`;
      li.tabIndex = 0;
      li.addEventListener("click", () => selectResult(item));
      resultsList.appendChild(li);
    });
    resultsList.hidden = false;
  }

  function selectResult(item) {
    input.value = item.name;
    nameField.value = item.name;
    idField.value = item.source === "existing" ? item.student_id : "";
    fideIdField.value = item.fide_id || "";
    federationField.value = item.federation || "";
    titleField.value = item.title || "";
    clearResults();
  }

  input.addEventListener("input", () => {
    const query = input.value.trim();

    // Toute frappe manuelle invalide une sélection précédente : on repart
    // sur un ajout "libre" tant qu'une suggestion n'est pas re-choisie.
    idField.value = "";
    fideIdField.value = "";
    federationField.value = "";
    titleField.value = "";
    nameField.value = query;

    clearTimeout(debounceTimer);
    if (query.length < 2) {
      clearResults();
      return;
    }

    debounceTimer = setTimeout(async () => {
      if (currentAbortController) currentAbortController.abort();
      currentAbortController = new AbortController();
      try {
        const resp = await fetch(`/api/students/search?q=${encodeURIComponent(query)}`, {
          signal: currentAbortController.signal,
        });
        if (!resp.ok) {
          clearResults();
          return;
        }
        renderResults(await resp.json());
      } catch (err) {
        if (err.name !== "AbortError") clearResults();
      }
    }, 250);
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".popover-anchor")) clearResults();
  });
})();
