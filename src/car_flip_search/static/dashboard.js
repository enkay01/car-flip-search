(() => {
    const toggles = document.querySelectorAll("[data-detail-toggle]");

    toggles.forEach((toggle) => {
        toggle.addEventListener("click", () => {
            const detail = document.getElementById(toggle.dataset.detailToggle);
            if (!detail) {
                return;
            }
            const expanded = toggle.getAttribute("aria-expanded") === "true";
            toggle.setAttribute("aria-expanded", String(!expanded));
            detail.hidden = expanded;
            const icon = toggle.querySelector(".toggle-icon");
            if (icon) {
                icon.textContent = expanded ? "+" : "−";
            }
        });
    });

    const deleteForm = document.querySelector("[data-capture-delete-form]");
    const captureCheckboxes = Array.from(document.querySelectorAll("[data-capture-checkbox]"));
    const selectAllCaptures = document.querySelector("[data-select-all-captures]");
    const selectionCount = document.querySelector("[data-selection-count]");
    const deleteButton = document.querySelector("[data-delete-button]");

    if (deleteForm && selectionCount && deleteButton) {
        const updateSelection = () => {
            const selectedCount = captureCheckboxes.filter((checkbox) => checkbox.checked).length;
            selectionCount.textContent = `${selectedCount} selected`;
            deleteButton.disabled = selectedCount === 0;
            if (selectAllCaptures) {
                selectAllCaptures.checked = captureCheckboxes.length > 0 && selectedCount === captureCheckboxes.length;
                selectAllCaptures.indeterminate = selectedCount > 0 && selectedCount < captureCheckboxes.length;
            }
        };

        captureCheckboxes.forEach((checkbox) => {
            checkbox.addEventListener("change", updateSelection);
        });

        if (selectAllCaptures) {
            selectAllCaptures.addEventListener("change", () => {
                captureCheckboxes.forEach((checkbox) => {
                    checkbox.checked = selectAllCaptures.checked;
                });
                updateSelection();
            });
        }

        deleteForm.addEventListener("submit", (event) => {
            const selectedCount = captureCheckboxes.filter((checkbox) => checkbox.checked).length;
            if (selectedCount === 0) {
                event.preventDefault();
                return;
            }
            const label = selectedCount === 1 ? "Capture" : "Captures";
            if (!window.confirm(`Delete ${selectedCount} ${label}? This cannot be undone.`)) {
                event.preventDefault();
            }
        });

        updateSelection();
    }

    const searchInput = document.getElementById("vehicle-search");
    const table = document.querySelector("[data-opportunity-table]");
    const liveCount = document.querySelector("[data-live-count]");
    if (!searchInput || !table || !liveCount) {
        return;
    }

    const rows = Array.from(table.querySelectorAll(".opportunity-row"));
    const detailRows = new Map(
        rows.map((row) => {
            const toggle = row.querySelector("[data-detail-toggle]");
            return [row, toggle ? document.getElementById(toggle.dataset.detailToggle) : null];
        }),
    );
    const initialCount = rows.length;

    searchInput.addEventListener("input", () => {
        const query = searchInput.value.trim().toLowerCase();
        let visible = 0;
        rows.forEach((row) => {
            const matches = !query || (row.dataset.searchText || "").includes(query);
            row.hidden = !matches;
            const detail = detailRows.get(row);
            if (detail && !matches) {
                detail.hidden = true;
            }
            if (matches) {
                visible += 1;
            }
        });
        liveCount.textContent = query
            ? `Showing ${visible} of ${initialCount} Candidate Vehicles`
            : `${initialCount} Candidate Vehicle(s)`;
    });
})();
