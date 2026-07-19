(function () {
  "use strict";

  var TIER_LABELS = { "1000": "Tier 1", "2000": "Tier 2", "3000": "Tier 3" };
  var TIER_BADGE_CLASS = { "1000": "badge-tier1", "2000": "badge-tier2", "3000": "badge-tier3" };

  var rawData = [];
  try {
    var dataEl = document.getElementById("subscribers-data");
    rawData = JSON.parse(dataEl ? dataEl.textContent : "[]") || [];
  } catch (err) {
    rawData = [];
  }

  var records = rawData.map(function (sub, index) {
    return {
      row_number: index + 1,
      user_name: sub.user_name || sub.user_login || "",
      user_login: sub.user_login || "",
      user_id: sub.user_id || "",
      tier: sub.tier || "",
      plan_name: sub.plan_name || "",
      is_gift: !!sub.is_gift,
      gifter_name: sub.is_gift ? (sub.gifter_name || sub.gifter_login || "") : "",
      gifter_login: sub.is_gift ? (sub.gifter_login || "") : "",
      broadcaster_name: sub.broadcaster_name || "",
      broadcaster_login: sub.broadcaster_login || "",
    };
  });

  var state = {
    search: "",
    tier: "",
    type: "",
    sortKey: "row_number",
    sortDir: "asc",
    page: 1,
    pageSize: 25,
  };

  var els = {
    body: document.getElementById("subscribersBody"),
    emptyState: document.getElementById("emptyState"),
    search: document.getElementById("searchInput"),
    tierFilter: document.getElementById("tierFilter"),
    typeFilter: document.getElementById("typeFilter"),
    pageSizeSelect: document.getElementById("pageSizeSelect"),
    prevBtn: document.getElementById("prevPageBtn"),
    nextBtn: document.getElementById("nextPageBtn"),
    pageIndicator: document.getElementById("pageIndicator"),
    summary: document.getElementById("paginationSummary"),
    headers: document.querySelectorAll("#subscribersTable th[data-key]"),
    exportCsvBtn: document.getElementById("exportCsvBtn"),
    exportXlsxBtn: document.getElementById("exportXlsxBtn"),
    overlay: document.getElementById("loadingOverlay"),
  };

  function getFiltered() {
    var term = state.search.trim().toLowerCase();

    return records.filter(function (row) {
      if (state.tier && row.tier !== state.tier) return false;
      if (state.type === "gift" && !row.is_gift) return false;
      if (state.type === "regular" && row.is_gift) return false;

      if (!term) return true;

      return (
        row.user_name.toLowerCase().indexOf(term) !== -1 ||
        row.user_login.toLowerCase().indexOf(term) !== -1 ||
        row.gifter_name.toLowerCase().indexOf(term) !== -1 ||
        row.user_id.toLowerCase().indexOf(term) !== -1
      );
    });
  }

  function getSorted(rows) {
    var key = state.sortKey;
    var dir = state.sortDir === "asc" ? 1 : -1;

    return rows.slice().sort(function (a, b) {
      var va = a[key];
      var vb = b[key];

      if (typeof va === "boolean" || typeof vb === "boolean") {
        va = va ? 1 : 0;
        vb = vb ? 1 : 0;
      } else if (typeof va === "number" || typeof vb === "number") {
        va = Number(va) || 0;
        vb = Number(vb) || 0;
      } else {
        va = String(va || "").toLowerCase();
        vb = String(vb || "").toLowerCase();
      }

      if (va < vb) return -1 * dir;
      if (va > vb) return 1 * dir;
      return 0;
    });
  }

  function tierBadge(tier) {
    if (!tier) return "&mdash;";
    var label = TIER_LABELS[tier] || tier;
    var cls = TIER_BADGE_CLASS[tier] || "badge-tier1";
    return '<span class="badge ' + cls + '">' + label + "</span>";
  }

  function typeBadge(isGift) {
    return isGift
      ? '<span class="badge badge-gift">Gift</span>'
      : '<span class="badge badge-regular">Regular</span>';
  }

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
  }

  function renderRows(pageRows) {
    if (!pageRows.length) {
      els.body.innerHTML = "";
      els.emptyState.classList.remove("hidden");
      return;
    }

    els.emptyState.classList.add("hidden");

    els.body.innerHTML = pageRows
      .map(function (row) {
        return (
          "<tr>" +
          "<td>" + row.row_number + "</td>" +
          "<td><div class=\"cell-user-name\">" + escapeHtml(row.user_name) + "</div><div class=\"cell-user-login\">" + escapeHtml(row.user_login) + "</div></td>" +
          "<td>" + tierBadge(row.tier) + "</td>" +
          "<td>" + escapeHtml(row.plan_name || "—") + "</td>" +
          "<td>" + typeBadge(row.is_gift) + "</td>" +
          "<td>" + escapeHtml(row.gifter_name || "—") + "</td>" +
          "<td>" + escapeHtml(row.broadcaster_name || "—") + "</td>" +
          "<td>" + escapeHtml(row.user_id) + "</td>" +
          "</tr>"
        );
      })
      .join("");
  }

  function updateSortIndicators() {
    els.headers.forEach(function (th) {
      th.classList.remove("sorted-asc", "sorted-desc");
      if (th.getAttribute("data-key") === state.sortKey) {
        th.classList.add(state.sortDir === "asc" ? "sorted-asc" : "sorted-desc");
      }
    });
  }

  function render() {
    var filtered = getSorted(getFiltered());
    var total = filtered.length;
    var pageSize = state.pageSize || total || 1;
    var totalPages = state.pageSize ? Math.max(1, Math.ceil(total / pageSize)) : 1;

    if (state.page > totalPages) state.page = totalPages;
    if (state.page < 1) state.page = 1;

    var startIndex = state.pageSize ? (state.page - 1) * pageSize : 0;
    var endIndex = state.pageSize ? Math.min(startIndex + pageSize, total) : total;
    var pageRows = filtered.slice(startIndex, endIndex);

    renderRows(pageRows);
    updateSortIndicators();

    els.summary.textContent = total
      ? "Mostrando " + (startIndex + 1) + "–" + endIndex + " de " + total + " subscribers"
      : "Nenhum resultado";
    els.pageIndicator.textContent = "Pagina " + state.page + " de " + totalPages;
    els.prevBtn.disabled = state.page <= 1;
    els.nextBtn.disabled = state.page >= totalPages;

    render.lastFiltered = filtered;
  }

  function csvEscape(value) {
    var text = value == null ? "" : String(value);
    if (/[",\n;]/.test(text)) {
      return '"' + text.replace(/"/g, '""') + '"';
    }
    return text;
  }

  function exportCsv() {
    var rows = render.lastFiltered || getSorted(getFiltered());
    var header = ["#", "user_name", "user_login", "tier", "plan_name", "is_gift", "gifter_name", "broadcaster_name", "user_id"];
    var lines = [header.join(",")];

    rows.forEach(function (row) {
      lines.push([
        row.row_number,
        csvEscape(row.user_name),
        csvEscape(row.user_login),
        csvEscape(TIER_LABELS[row.tier] || row.tier),
        csvEscape(row.plan_name),
        row.is_gift ? "true" : "false",
        csvEscape(row.gifter_name),
        csvEscape(row.broadcaster_name),
        csvEscape(row.user_id),
      ].join(","));
    });

    var blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "subscribers.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  function exportXlsx() {
    if (typeof XLSX === "undefined") {
      console.log("[SUBSCRIBERS] Biblioteca XLSX nao carregou");
      return;
    }

    var rows = render.lastFiltered || getSorted(getFiltered());
    var sheetData = rows.map(function (row) {
      return {
        "#": row.row_number,
        Usuario: row.user_name,
        Login: row.user_login,
        Tier: TIER_LABELS[row.tier] || row.tier,
        Plano: row.plan_name,
        Gift: row.is_gift ? "Sim" : "Nao",
        "Gifted By": row.gifter_name,
        Broadcaster: row.broadcaster_name,
        "User ID": row.user_id,
      };
    });

    var worksheet = XLSX.utils.json_to_sheet(sheetData);
    var workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, "Subscribers");
    XLSX.writeFile(workbook, "subscribers.xlsx");
  }

  els.search.addEventListener("input", function () {
    state.search = els.search.value;
    state.page = 1;
    render();
  });

  els.tierFilter.addEventListener("change", function () {
    state.tier = els.tierFilter.value;
    state.page = 1;
    render();
  });

  els.typeFilter.addEventListener("change", function () {
    state.type = els.typeFilter.value;
    state.page = 1;
    render();
  });

  els.pageSizeSelect.addEventListener("change", function () {
    state.pageSize = Number(els.pageSizeSelect.value) || 0;
    state.page = 1;
    render();
  });

  els.prevBtn.addEventListener("click", function () {
    state.page -= 1;
    render();
  });

  els.nextBtn.addEventListener("click", function () {
    state.page += 1;
    render();
  });

  els.headers.forEach(function (th) {
    th.addEventListener("click", function () {
      var key = th.getAttribute("data-key");
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = key;
        state.sortDir = "asc";
      }
      render();
    });
  });

  els.exportCsvBtn.addEventListener("click", exportCsv);
  els.exportXlsxBtn.addEventListener("click", exportXlsx);

  render();

  if (els.overlay) {
    els.overlay.classList.add("is-hidden");
    setTimeout(function () {
      els.overlay.style.display = "none";
    }, 300);
  }
})();
