(function () {
    "use strict";

    // --- Config ---
    // Simple client-side password gate (not real security, just a deterrent).
    // Change this to set your own password.
    const PASSWORD = "teatri2026";

    const WEEKDAYS = ["Domenica", "Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato"];
    const MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];

    // --- State ---
    let allEvents = [];

    // --- DOM ---
    const gate = document.getElementById("gate");
    const gatePassword = document.getElementById("gate-password");
    const gateSubmit = document.getElementById("gate-submit");
    const gateError = document.getElementById("gate-error");
    const app = document.getElementById("app");
    const filterDate = document.getElementById("filter-date");
    const filterLocation = document.getElementById("filter-location");
    const filterVenue = document.getElementById("filter-venue");
    const filterPast = document.getElementById("filter-past");
    const eventsCount = document.getElementById("events-count");
    const eventsList = document.getElementById("events-list");
    const lastUpdated = document.getElementById("last-updated");

    // --- Password gate ---
    function checkAuth() {
        return localStorage.getItem("teatri_auth") === "ok";
    }

    function authenticate(pwd) {
        if (pwd === PASSWORD) {
            localStorage.setItem("teatri_auth", "ok");
            return true;
        }
        return false;
    }

    function showApp() {
        gate.style.display = "none";
        app.removeAttribute("hidden");
        app.style.display = "block";
        loadEvents();
    }

    gateSubmit.addEventListener("click", function () {
        if (authenticate(gatePassword.value)) {
            showApp();
        } else {
            gateError.hidden = false;
        }
    });

    gatePassword.addEventListener("keydown", function (e) {
        if (e.key === "Enter") gateSubmit.click();
    });

    if (checkAuth()) {
        showApp();
    }

    // --- Load events ---
    async function loadEvents() {
        try {
            const resp = await fetch("events.json");
            const data = await resp.json();
            allEvents = data.events || [];

            if (data.last_updated) {
                const d = new Date(data.last_updated);
                lastUpdated.textContent = "Ultimo aggiornamento: " +
                    d.toLocaleDateString("it-IT") + " " + d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
            }

            populateFilters();
            renderEvents();
        } catch (e) {
            eventsList.innerHTML = '<div class="no-events">Errore nel caricamento degli eventi.</div>';
        }
    }

    // --- Filters ---
    function populateFilters() {
        const locations = [...new Set(allEvents.map(e => e.location).filter(Boolean))].sort();
        const venues = [...new Set(allEvents.map(e => e.venue).filter(Boolean))].sort();

        locations.forEach(function (loc) {
            const opt = document.createElement("option");
            opt.value = loc;
            opt.textContent = loc;
            filterLocation.appendChild(opt);
        });

        venues.forEach(function (v) {
            const opt = document.createElement("option");
            opt.value = v;
            opt.textContent = v;
            filterVenue.appendChild(opt);
        });
    }

    filterDate.addEventListener("change", renderEvents);
    filterLocation.addEventListener("change", renderEvents);
    filterVenue.addEventListener("change", renderEvents);
    filterPast.addEventListener("change", renderEvents);

    // --- Render ---
    function formatDate(isoDate) {
        const d = new Date(isoDate + "T00:00:00");
        var wd = WEEKDAYS[d.getDay()];
        return wd + " " + d.getDate() + " " + MONTHS[d.getMonth()] + " " + d.getFullYear();
    }

    function isInRange(eventDate, range) {
        var today = new Date();
        today.setHours(0, 0, 0, 0);
        var d = new Date(eventDate + "T00:00:00");

        if (range === "today") {
            return d.getTime() === today.getTime();
        }
        if (range === "week") {
            var weekEnd = new Date(today);
            weekEnd.setDate(weekEnd.getDate() + 7);
            return d >= today && d <= weekEnd;
        }
        if (range === "month") {
            var monthEnd = new Date(today);
            monthEnd.setMonth(monthEnd.getMonth() + 1);
            return d >= today && d <= monthEnd;
        }
        return true; // "all"
    }

    function renderEvents() {
        var dateRange = filterDate.value;
        var locFilter = filterLocation.value;
        var venueFilter = filterVenue.value;
        var showPast = filterPast.checked;

        var today = new Date();
        today.setHours(0, 0, 0, 0);

        var filtered = allEvents.filter(function (ev) {
            var d = new Date(ev.date + "T00:00:00");
            var isPast = d < today;

            if (isPast && !showPast) return false;
            if (!isPast && !isInRange(ev.date, dateRange)) return false;
            if (locFilter && ev.location !== locFilter) return false;
            if (venueFilter && ev.venue !== venueFilter) return false;

            return true;
        });

        eventsCount.textContent = filtered.length + " event" + (filtered.length !== 1 ? "i" : "o") +
            (filtered.length > 0 ? "" : " trovati");

        if (filtered.length === 0) {
            eventsList.innerHTML = '<div class="no-events">Nessun evento trovato per i filtri selezionati.</div>';
            return;
        }

        eventsList.innerHTML = filtered.map(function (ev) {
            var isPast = new Date(ev.date + "T00:00:00") < today;
            var timeStr = ev.time ? " ore " + ev.time : "";
            var sources = (ev.source_urls || [ev.source_url]).map(function (url) {
                var domain = url.replace(/https?:\/\//, "").split("/")[0];
                return '<a href="' + url + '" target="_blank" rel="noopener">' + domain + '</a>';
            }).join(", ");

            return '<div class="event-card' + (isPast ? " past" : "") + '" onclick="this.querySelector(\'.event-details\').classList.toggle(\'open\')">' +
                '<div class="event-date">' + formatDate(ev.date) + timeStr + '</div>' +
                '<div class="event-title">' + escapeHtml(ev.title) + '</div>' +
                '<div class="event-meta">' + escapeHtml(ev.venue) + (ev.location ? " &middot; " + escapeHtml(ev.location) : "") + '</div>' +
                '<div class="event-details">' +
                (ev.description ? "<p>" + escapeHtml(ev.description) + "</p>" : "") +
                '<p class="event-source">Fonte: ' + sources + '</p>' +
                '</div>' +
                '</div>';
        }).join("");
    }

    function escapeHtml(text) {
        if (!text) return "";
        var div = document.createElement("div");
        div.appendChild(document.createTextNode(text));
        return div.innerHTML;
    }
})();
