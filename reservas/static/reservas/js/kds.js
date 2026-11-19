/* static/reservas/js/kds.js */
/* global document, window */

(function () {
  const grid = document.getElementById("kds-grid");
  if (!grid) return;

  const filterMesaEl = document.getElementById("kdsMesaFilter");
  const filterTimeEl = document.getElementById("kdsTimeFilter");
  const soundEl = document.getElementById("kdsNewOrderSound");  // opcional

  const DATA_URL   = grid.dataset.dataUrl || "";
  const UPDATE_TPL = grid.dataset.updateUrlPattern || "";
  const REFRESH_MS = Number(grid.dataset.refreshMs || 3000);

  let lastMaxId = 0;

  // -------- CSRF ----------
  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) {
      return decodeURIComponent(parts.pop().split(";").shift());
    }
    return "";
  }

  // -------- Utils ----------
  function escapeHtml(str) {
    return (str || "").replace(/[&<>"']/g, (m) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m] || m)
    );
  }

  function statusBadge(st) {
    const map = {
      SUBMITTED: { cls: "secondary", label: "EN COLA" },
      IN_PREP:   { cls: "warning",   label: "EN PREP." },
      READY:     { cls: "success",   label: "LISTO" },
      SERVED:    { cls: "info",      label: "SERVIDO" },
    };
    const data = map[st] || { cls: "secondary", label: st || "N/A" };
    return `<span class="badge text-bg-${data.cls} text-uppercase small">${data.label}</span>`;
  }
  function itemRow(it) {
  const notas = it.notas
    ? `
      <div class="mt-1">
        <span class="badge bg-danger-subtle text-danger small">
          📝 ${escapeHtml(it.notas)}
        </span>
      </div>
    `
    : "";

  return `
    <li class="list-group-item d-flex justify-content-between align-items-start">
      <div>
        <strong>${it.cantidad}×</strong> ${escapeHtml(it.nombre)}
        ${notas}
      </div>
      <span>$${escapeHtml(String(it.importe))}</span>
    </li>`;
}


  function actionBtn(id, label, target, icon) {
    return `
      <button class="btn btn-sm btn-outline-dark me-2"
              data-kds-action
              data-id="${id}"
              data-status="${target}">
        ${icon} ${label}
      </button>`;
  }

  function actionsForStatus(order) {
    const id = order.id;
    switch (order.status) {
      case "SUBMITTED":
        return (
          actionBtn(id, "En preparación", "IN_PREP", "👨‍🍳") +
          actionBtn(id, "Listo", "READY", "✅")
        );
      case "IN_PREP":
        return actionBtn(id, "Listo", "READY", "✅");
      case "READY":
        return actionBtn(id, "Entregada", "SERVED", "🚶‍♂️");
      case "SERVED":
        return `<span class="text-muted">Entregada a mesa</span>`;
      default:
        return "";
    }
  }

  // -------- Render ----------
  function renderOrders(orders) {
    if (!Array.isArray(orders)) orders = [];

    if (!orders.length) {
      grid.innerHTML = `
        <div class="col-12">
          <div class="alert alert-light border text-center py-4 mb-0">
            Sin órdenes activas.
          </div>
        </div>`;
      return;
    }

    const html = orders
      .map((o) => {
        const itemsHtml = (o.items || []).map(itemRow).join("");
        const mesa = o.mesa ? `Mesa ${escapeHtml(String(o.mesa))}` : "Sin mesa";
        const hora = o.submitted_at
          ? new Date(o.submitted_at).toLocaleTimeString()
          : "";

        return `
          <div class="col-12 col-md-6 col-lg-4">
            <div class="card shadow-sm h-100 kds-card" data-order-id="${o.id}">
              <div class="card-body d-flex flex-column">
                <div class="d-flex justify-content-between align-items-center mb-2">
                  <h5 class="mb-0">${mesa}</h5>
                  ${statusBadge(o.status)}
                </div>

                <ul class="list-group list-group-flush mb-3">
                  ${itemsHtml}
                </ul>

                <div class="mt-auto">
                  ${actionsForStatus(o)}
                </div>
              </div>
              <div class="card-footer d-flex justify-content-between small text-muted">
                <span>${escapeHtml(o.sucursal || "")}</span>
                <span>${hora}</span>
              </div>
            </div>
          </div>`;
      })
      .join("");

    grid.innerHTML = html;
  }

  // -------- Fetch + sonido ----------
  async function fetchKdsData() {
    try {
      const params = new URLSearchParams();
      const mesa = filterMesaEl ? filterMesaEl.value : "";
      const rango = filterTimeEl ? filterTimeEl.value : "";

      if (mesa) params.append("mesa", mesa);
      if (rango) params.append("rango", rango);

      const url = params.toString() ? `${DATA_URL}?${params.toString()}` : DATA_URL;
      if (!url) return;

      const res = await fetch(url, {
        cache: "no-store",
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" },
      });
      if (!res.ok) throw new Error("HTTP " + res.status);

      const data = await res.json();
      const orders = data.orders || [];

      // detectar nuevas órdenes -> sonido
      const maxId = orders.reduce((m, o) => {
        const n = Number(o.id) || 0;
        return n > m ? n : m;
      }, 0);

      if (maxId > lastMaxId && lastMaxId !== 0 && soundEl) {
        try {
          soundEl.currentTime = 0;
          soundEl.play();
        } catch (e) {
          console.warn("No se pudo reproducir el sonido de nueva orden", e);
        }
      }
      if (!lastMaxId) {
        lastMaxId = maxId; // primer load no suena
      } else {
        lastMaxId = Math.max(lastMaxId, maxId);
      }

      renderOrders(orders);
    } catch (err) {
      console.error("Error al obtener datos del KDS:", err);
    }
  }

  // -------- Update estado ----------
  async function updateStatus(orderId, target) {
    if (!UPDATE_TPL) return;

    const url = UPDATE_TPL.replace("/0/", `/${orderId}/`);
    const form = new FormData();
    form.append("status", target);

    try {
      const res = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "X-CSRFToken": getCookie("csrftoken"),
        },
        body: form,
      });
      if (!res.ok) throw new Error("HTTP " + res.status);

      await fetchKdsData();
    } catch (err) {
      console.error("Error al actualizar estado KDS:", err);
    }
  }

  // Delegación de eventos para los botones de estado
  grid.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-kds-action]");
    if (!btn) return;
    const id = Number(btn.dataset.id || 0);
    const st = btn.dataset.status || "";
    if (!id || !st) return;
    updateStatus(id, st);
  });

  // Cambio de filtros
  if (filterMesaEl) {
    filterMesaEl.addEventListener("change", () => {
      lastMaxId = 0;
      fetchKdsData();
    });
  }
  if (filterTimeEl) {
    filterTimeEl.addEventListener("change", () => {
      lastMaxId = 0;
      fetchKdsData();
    });
  }

  // Primer load + intervalo
  window.addEventListener("load", fetchKdsData);
  setInterval(fetchKdsData, REFRESH_MS || 3000);
})();
