var __EN = (document.documentElement.lang || '').indexOf('en') === 0;
// static/reservas/js/walkin_mesas.js
// Carga y llena el <select name="mesa"> según la sucursal actual.
// Expone window.WALKIN.loadMesasForCurrentSucursal() para que otros scripts lo llamen.

(function () {
  function readCfg() {
    try {
      return JSON.parse(document.getElementById("walkin-config")?.textContent || "{}");
    } catch {
      return {};
    }
  }

  function getSucursalId() {
    const sel = document.querySelector('select[name="sucursal"]');
    if (sel && sel.value) return sel.value;

    const hid = document.querySelector('input[type="hidden"][name="sucursal"]');
    return hid?.value || "";
  }

  async function fetchMesas(sucursalId) {
    const cfg = readCfg();
    let base = (cfg.urls && cfg.urls.api_mesas_base) || "/api/sucursal/0/mesas/";
    base = base.replace("/0/", `/${sucursalId}/`);
    const resp = await fetch(base, { headers: { "X-Requested-With": "fetch" } });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    return resp.json(); // { mesas: [...] }
  }

  function ensureSelectHasBootstrap(select) {
    if (!select) return;
    const c = select.getAttribute("class") || "";
    if (!/\bform-select\b/.test(c)) {
      select.setAttribute("class", (c + " form-select").trim());
    }
  }

  function fillSelect(mesas) {
    const select = document.querySelector('select[name="mesa"]');
    if (!select) return;
    ensureSelectHasBootstrap(select);

    const prev = select.value;
    select.innerHTML = "";

    const opt0 = new Option("— Selecciona mesa —", "");
    select.add(opt0);

    (mesas || []).forEach((m) => {
      const label = `${__EN ? "Table" : "Mesa"} ${m.numero}${m.capacidad ? ` (Cap. ${m.capacidad})` : ""}`;
      select.add(new Option(label, m.id));
    });

    // Restaurar selección previa si sigue disponible
    if (prev && [...select.options].some((o) => o.value === prev)) {
      select.value = prev;
    } else {
      select.value = "";
    }
  }

  async function loadMesasForCurrentSucursal() {
    const sucId = getSucursalId();
    if (!sucId) return;
    try {
      const data = await fetchMesas(sucId);
      fillSelect(data.mesas || []);
    } catch (e) {
      console.warn("[WALKIN] No se pudieron cargar mesas:", e);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    // Exponer para otros scripts (walkin.js)
    window.WALKIN = window.WALKIN || {};
    window.WALKIN.loadMesasForCurrentSucursal = loadMesasForCurrentSucursal;

    // 1) Al cargar
    loadMesasForCurrentSucursal();

    // 2) Si cambian la sucursal manualmente
    const sucSel = document.querySelector('select[name="sucursal"]');
    if (sucSel) sucSel.addEventListener("change", loadMesasForCurrentSucursal);
  });
})();
