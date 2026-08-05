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

/**
 * Cartes cliquables (classes, élèves) : on entre dans la classe ou la
 * fiche élève en cliquant n'importe où sur la carte, sauf sur la case à
 * cocher ou le formulaire de suppression (.no-card-nav).
 */
(function () {
  document.querySelectorAll(".selectable-card[data-href]").forEach((card) => {
    card.addEventListener("click", (e) => {
      if (e.target.closest(".no-card-nav")) return;
      window.location.href = card.dataset.href;
    });
  });
})();

/**
 * Confirmation avant suppression / retrait (icône poubelle sur chaque
 * carte). Le message exact vient de data-confirm sur le formulaire.
 */
(function () {
  document.querySelectorAll(".trash-form").forEach((form) => {
    form.addEventListener("submit", (e) => {
      const message = form.dataset.confirm || "Confirmer la suppression ?";
      if (!confirm(message)) e.preventDefault();
    });
  });
})();

/**
 * Sélection multiple + barre d'actions groupées : fonctionne aussi bien
 * pour les classes (coach.html : suppression groupée) que pour les
 * élèves d'une classe (coach_class.html : retrait groupé + déplacement
 * groupé vers une autre classe). Les éléments concernés (bulk-bar,
 * bulk-count, cases à cocher) sont optionnels : ce bloc ne fait rien si
 * la page ne les propose pas.
 */
(function () {
  const bulkBar = document.getElementById("bulk-bar");
  const bulkCount = document.getElementById("bulk-count");
  const checkboxes = document.querySelectorAll(".card-checkbox");
  if (!bulkBar || !checkboxes.length) return;

  function selectedIds() {
    return Array.from(checkboxes)
      .filter((cb) => cb.checked)
      .map((cb) => cb.dataset.id);
  }

  function updateBulkBar() {
    const ids = selectedIds();
    bulkBar.hidden = ids.length === 0;
    if (bulkCount) {
      bulkCount.textContent = `${ids.length} sélectionné${ids.length > 1 ? "s" : ""}`;
    }
  }

  checkboxes.forEach((cb) => cb.addEventListener("change", updateBulkBar));

  function submitWithIds(form, fieldName, extra) {
    const ids = selectedIds();
    if (!ids.length) return;
    form.querySelectorAll('input[type="hidden"][data-generated]').forEach((el) => el.remove());
    ids.forEach((id) => {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = fieldName;
      input.value = id;
      input.dataset.generated = "1";
      form.appendChild(input);
    });
    if (extra) {
      Object.entries(extra).forEach(([name, value]) => {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = name;
        input.value = value;
        input.dataset.generated = "1";
        form.appendChild(input);
      });
    }
    form.submit();
  }

  // --- Suppression groupée de classes (coach.html) ---
  const bulkDeleteBtn = document.getElementById("bulk-delete-btn");
  const bulkDeleteForm = document.getElementById("bulk-delete-form");
  if (bulkDeleteBtn && bulkDeleteForm) {
    bulkDeleteBtn.addEventListener("click", () => {
      const ids = selectedIds();
      if (!ids.length) return;
      if (!confirm(`Supprimer ${ids.length} classe(s) sélectionnée(s) ? Les élèves ne sont pas supprimés.`)) return;
      submitWithIds(bulkDeleteForm, "class_ids");
    });
  }

  // --- Retrait groupé d'élèves (coach_class.html) ---
  const bulkRemoveBtn = document.getElementById("bulk-remove-btn");
  const bulkRemoveForm = document.getElementById("bulk-remove-form");
  if (bulkRemoveBtn && bulkRemoveForm) {
    bulkRemoveBtn.addEventListener("click", () => {
      const ids = selectedIds();
      if (!ids.length) return;
      if (!confirm(`Retirer ${ids.length} élève(s) sélectionné(s) de cette classe ?`)) return;
      submitWithIds(bulkRemoveForm, "student_ids");
    });
  }

  // --- Déplacement groupé d'élèves vers une autre classe (coach_class.html) ---
  const bulkMoveBtn = document.getElementById("bulk-move-btn");
  const bulkMoveForm = document.getElementById("bulk-move-form");
  const bulkMoveTarget = document.getElementById("bulk-move-target");
  if (bulkMoveBtn && bulkMoveForm && bulkMoveTarget) {
    bulkMoveBtn.addEventListener("click", () => {
      const ids = selectedIds();
      const targetId = bulkMoveTarget.value;
      if (!ids.length) return;
      if (!targetId) {
        alert("Choisissez une classe de destination.");
        return;
      }
      const targetName = bulkMoveTarget.options[bulkMoveTarget.selectedIndex].textContent;
      if (!confirm(`Déplacer ${ids.length} élève(s) vers "${targetName}" ?`)) return;
      submitWithIds(bulkMoveForm, "student_ids", { target_class_id: targetId });
    });
  }

  updateBulkBar();
})();
