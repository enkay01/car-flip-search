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
