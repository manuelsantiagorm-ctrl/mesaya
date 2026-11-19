/* static/reservas/js/ordenes.js */
/* global document, window, bootstrap */
(function () {
  const $  = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  // ========= Config =========
  const CFG       = window.ORDENES_CONFIG || {};
  const URL_NUEVA = CFG.urlNuevaOrden; // ej: /orden/nueva/?mesa_id=1
  const ORIGIN    = window.location.origin;

  const absUrl = (u) => {
    try {
      return new URL(u, ORIGIN).toString();
    } catch {
      return u || "";
    }
  };

  const getCookie = (name) => {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    return parts.length === 2
      ? decodeURIComponent(parts.pop().split(";").shift())
      : "";
  };

  const CSRFTOKEN =
    CFG.csrfToken ||
    getCookie("csrftoken") ||
    ($("#csrfToken")?.value || "");

  // ========= UI helpers =========
  const setLoading = (el, msg) => {
    if (!el) return;
    el.innerHTML = `
      <div class="text-center py-5 text-muted">
        <div class="spinner-border"></div>
        <p class="mt-2">${(CFG.texto && CFG.texto.cargando) || msg || "Cargando..."}</p>
      </div>`;
  };

  const setError = (el, msg) => {
    if (!el) return;
    el.innerHTML = `
      <div class="alert alert-danger m-3">
        ${(CFG.texto && CFG.texto.error) || "Error al cargar"}<br>
        <small class="text-muted">${msg || ""}</small>
      </div>`;
  };

  function showToast(message, type = "success") {
    const toast = document.createElement("div");
    toast.className =
      "position-fixed top-0 start-50 translate-middle-x mt-3 alert alert-" +
      (type === "error" ? "danger" : "success") +
      " shadow-sm py-2 px-3 small";
    toast.textContent = message || "OK";
    document.body.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = "0";
    }, 2200);

    setTimeout(() => {
      toast.remove();
    }, 2600);
  }

  // ========= Elementos del modal host =========
  const modalEl = $("#modalOrden");
  const modal   = modalEl ? bootstrap.Modal.getOrCreateInstance(modalEl) : null;
  const cont    = $("#ordenContenido");
  if (!modalEl || !cont) return;

  // ===== Helper: reemplazar SOLO el body del modal
  function replaceOrdenBody(newHtml) {
    if (!newHtml) return;
    const current = document.getElementById("ordenModalBody");
    if (!current) {
      cont.innerHTML = newHtml;
    } else {
      current.outerHTML = newHtml;
    }
    wireInside(); // re-enganchar JS interno
  }

  // ========= Abrir modal desde cada mesa =========
  $$("#mapCanvas [data-orden-mesa]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const mesaId = Number(btn.dataset.mesaId || 0);
      if (!mesaId || !URL_NUEVA) return;

      modal.show();
      setLoading(cont);

      try {
        const url = absUrl(`${URL_NUEVA}?mesa_id=${encodeURIComponent(mesaId)}`);
        const res = await fetch(url, {
          credentials: "same-origin",
          headers: { "X-Requested-With": "fetch" },
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const text = await res.text();

        try {
          const j = JSON.parse(text);
          cont.innerHTML = j && j.html ? j.html : text;
        } catch {
          cont.innerHTML = text;
        }
        wireInside();
      } catch (err) {
        console.error(err);
        setError(cont, err.message);
      }
    });
  });

  // ========= Formulario "Agregar" =========
  function hookFormularioAgregar(root) {
    const form = root.querySelector("#formAgregarItem");
    if (!form || form.__wired) return;
    form.__wired = true;

    const btnSubmit = form.querySelector("[type=submit]");
    const alertErr  = form.querySelector("[data-error]");

    const endpoint =
      form.dataset.endpoint ||
      root.dataset.endpointAdd;

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!endpoint) return alert("No se encontró endpoint para agregar.");

      const prevTxt = btnSubmit ? btnSubmit.innerHTML : "";
      if (btnSubmit) {
        btnSubmit.disabled = true;
        form.classList.add("is-busy");
        btnSubmit.innerHTML =
          '<span class="spinner-border spinner-border-sm me-1"></span>Agregando…';
      }
      if (alertErr) {
        alertErr.classList.add("d-none");
        alertErr.textContent = "";
      }

      const fd = new FormData(form);
      const payload = {
        orden_id: Number(fd.get("orden_id")),
        codigo:   String(fd.get("codigo") || "").trim().toUpperCase(),
        nombre:   String(fd.get("nombre") || "").trim(),
        cantidad: Math.max(1, Number(fd.get("cantidad") || 1)),
        notas:    String(fd.get("notas") || "").trim(),
      };

      if (!payload.codigo && !payload.nombre) {
        if (alertErr) {
          alertErr.textContent =
            "Escribe código o usa el buscador de abajo.";
          alertErr.classList.remove("d-none");
        }
        if (btnSubmit) {
          btnSubmit.disabled = false;
          form.classList.remove("is-busy");
          btnSubmit.innerHTML = prevTxt;
        }
        return;
      }

      try {
        const res = await fetch(absUrl(endpoint), {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": CSRFTOKEN,
            "X-Requested-With": "fetch",
          },
          body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        const j = await res.json();
        if (!j.ok) throw new Error(j.error || "Error");

        replaceOrdenBody(j.html);
      } catch (err) {
        console.error(err);
        if (alertErr) {
          alertErr.textContent = "Error: " + err.message;
          alertErr.classList.remove("d-none");
        } else {
          alert("Error: " + err.message);
        }
      } finally {
        if (btnSubmit) {
          btnSubmit.disabled = false;
          form.classList.remove("is-busy");
          btnSubmit.innerHTML = prevTxt;
        }
      }
    });
  }

  // ========= Buscador / autocomplete =========
  function hookBusquedaRapida(root) {
    const input = root.querySelector("#buscarItem");
    const tbody = root.querySelector("#busquedaResultados");
    const form  = root.querySelector("#formAgregarItem");
    if (!input || !tbody || !form || input.__wired) return;
    input.__wired = true;

    const endpointSearch =
      input.dataset.endpoint || root.dataset.endpointBuscar;
    const endpointAdd =
      input.dataset.addEndpoint ||
      form.dataset.endpoint ||
      root.dataset.endpointAdd;

    const ordenId    = Number(
      input.dataset.ordenId || form.querySelector("[name='orden_id']").value || 0
    );
    const sucursalId = Number(input.dataset.sucursalId || 0);
    const fmt = new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: "MXN",
    });

    let debounce = null;

    input.addEventListener("input", () => {
      clearTimeout(debounce);
      const q = (input.value || "").trim();
      if (q.length < 2) {
        tbody.innerHTML = "";
        return;
      }
      debounce = setTimeout(() => buscar(q), 220);
    });

    async function buscar(q) {
      if (!endpointSearch) return;
      try {
        const url = absUrl(
          `${endpointSearch}?q=${encodeURIComponent(q)}&sucursal_id=${encodeURIComponent(
            sucursalId
          )}&limit=25`
        );
        const res = await fetch(url, {
          credentials: "same-origin",
          headers: { "X-Requested-With": "fetch" },
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();
        renderResultados(data.results || data.items || data || []);
      } catch (e) {
        tbody.innerHTML =
          `<tr><td colspan="5" class="text-danger">Error: ${e.message}</td></tr>`;
      }
    }

    function escapeHtml(s) {
      return (s || "").replace(/[&<>"']/g, (m) =>
        ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]
        )
      );
    }

    function renderResultados(items) {
      if (!Array.isArray(items) || items.length === 0) {
        tbody.innerHTML =
          '<tr><td colspan="5" class="text-muted text-center py-3">Sin resultados</td></tr>';
        return;
      }
      tbody.innerHTML = items
        .map((it, i) => {
          const precio = Number(it.precio || it.price || 0);
          const codigo = it.codigo || it.code || "";
          const nombre = it.nombre || it.name || "";
          return `
            <tr data-codigo="${codigo}" data-precio="${precio}">
              <td class="text-muted">${i + 1}</td>
              <td><span class="badge text-bg-secondary">${codigo || "-"}</span> ${escapeHtml(
                nombre
              )}</td>
              <td class="text-end">${fmt.format(precio)}</td>
              <td class="text-center" style="width:90px;">
                <input type="number" class="form-control form-control-sm" value="1" min="1">
              </td>
              <td class="text-end">
                <button class="btn btn-sm btn-primary" data-add>Agregar</button>
              </td>
            </tr>`;
        })
        .join("");

      tbody.querySelectorAll("[data-add]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          if (!endpointAdd)
            return alert("No se encontró endpoint para agregar.");
          const tr = btn.closest("tr");
          const cantidad = Math.max(
            1,
            Number(tr.querySelector("input[type='number']").value || 1)
          );
          const payload = {
            orden_id: ordenId,
            codigo: tr.dataset.codigo,
            cantidad,
          };
          try {
            const r = await fetch(absUrl(endpointAdd), {
              method: "POST",
              credentials: "same-origin",
              headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": CSRFTOKEN,
                "X-Requested-With": "fetch",
              },
              body: JSON.stringify(payload),
            });
            if (!r.ok) throw new Error("HTTP " + r.status);
            const j = await r.json();
            if (!j.ok) throw new Error(j.error || "Error");
            replaceOrdenBody(j.html);
          } catch (e) {
            alert("No se pudo agregar: " + e.message);
          }
        });
      });
    }
  }

  // ========= Acciones: enviar a cocina / cobrar =========
  function hookAcciones(root) {
    if (!root) return;

    // --- Botón Enviar a cocina ---
    const btnEnviar = root.querySelector("#btnEnviarCocina");
    if (btnEnviar && !btnEnviar.__wired) {
      btnEnviar.__wired = true;
      btnEnviar.disabled = false;

      btnEnviar.addEventListener("click", async () => {
        const url = root.dataset.submitUrl;
        if (!url) {
          alert("Falta URL de envío a cocina.");
          return;
        }
        btnEnviar.disabled = true;

        try {
          const res = await fetch(absUrl(url), {
            method: "POST",
            credentials: "same-origin",
            headers: {
              "X-CSRFToken": CSRFTOKEN,
              "X-Requested-With": "fetch",
            },
          });

          const j = await res.json();
          if (!res.ok || !j.ok) {
            throw new Error(j.error || "HTTP " + res.status);
          }

          if (j.html) {
            replaceOrdenBody(j.html);
          }

          showToast("Orden enviada a cocina ✅", "success");
        } catch (e) {
          console.error(e);
          alert("No se pudo enviar a cocina: " + e.message);
          btnEnviar.disabled = false;
        }
      });
    }

    // --- Botón Cobrar y cerrar ---
    const btnCobrar = root.querySelector("#btnCobrar");
    if (btnCobrar && !btnCobrar.__wired) {
      btnCobrar.__wired = true;

      btnCobrar.addEventListener("click", async () => {
        const url = root.dataset.chargeUrl;
        if (!url) {
          alert("Falta URL de cobro.");
          return;
        }

        if (!window.confirm("¿Cobrar y cerrar la cuenta?")) {
          return;
        }

        btnCobrar.disabled = true;

        try {
          const res = await fetch(absUrl(url), {
            method: "POST",
            credentials: "same-origin",
            headers: {
              "X-CSRFToken": CSRFTOKEN,
              "X-Requested-With": "fetch",
            },
          });

          const j = await res.json();
          if (!res.ok || !j.ok) {
            throw new Error(j.error || "HTTP " + res.status);
          }

          if (j.ticket_url) {
            window.open(j.ticket_url, "_blank");
          }

          window.location.reload();
        } catch (e) {
          console.error(e);
          alert("No se pudo cobrar: " + e.message);
          btnCobrar.disabled = false;
        }
      });
    }
  }

  // ========= EDITAR NOTAS DE UN ITEM (LÁPIZ) =========
  function hookEditarNotas(root) {
    const endpoint = root.dataset.endpointItemUpdate || "";
    if (!endpoint || root.__wiredNotas) return;
    root.__wiredNotas = true;

    root.addEventListener("click", async (ev) => {
      const btn = ev.target.closest("[data-item-edit]");
      if (!btn) return;

      const row = btn.closest("[data-item-row]");
      if (!row) return;

      const itemId = row.dataset.itemId;
      if (!itemId) return;

      const notasActuales = row.dataset.notas || "";
      const nuevasNotas = window.prompt("Notas del platillo:", notasActuales);
      if (nuevasNotas === null) return; // canceló

      // Actualiza UI local
      row.dataset.notas = nuevasNotas;

      const small = row.querySelector("td:nth-child(2) small.text-muted");
      if (small) {
        const partes = small.textContent.split("·");
        const base = partes[0].trim(); // "CATEGORIA ..." sin notas
        if (nuevasNotas.trim()) {
          small.innerHTML = `${base} · <span class="text-danger">${nuevasNotas}</span>`;
        } else {
          small.textContent = base;
        }
      }

      // Llamada al backend
      try {
        const res = await fetch(absUrl(endpoint), {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": CSRFTOKEN,
            "X-Requested-With": "fetch",
          },
          body: JSON.stringify({
            item_id: Number(itemId),
            notas: nuevasNotas,
          }),
        });
        if (!res.ok) {
          console.error("Error HTTP al actualizar notas:", res.status);
        }
      } catch (err) {
        console.error("Error al actualizar notas del item:", err);
        alert("No se pudo guardar la nota. Revisa la consola.");
      }
    });
  }

  // ========= Wiring principal (cada vez que cambia el body) =========
  function wireInside() {
    const root = $("#ordenModalBody", cont);
    if (!root) return;
    hookFormularioAgregar(root);
    hookBusquedaRapida(root);
    hookAcciones(root);
    hookEditarNotas(root);
  }

  // Re-enganchar si el modal ya tenía contenido
  modalEl.addEventListener("shown.bs.modal", wireInside);
})();

// === ELIMINAR ÍTEM DEL CARRITO ===
(function () {
  const $ = (s, r = document) => r.querySelector(s);

  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return decodeURIComponent(parts.pop().split(";").shift());
    return "";
  }
  const CSRFTOKEN =
    ($("#csrfToken") && $("#csrfToken").value) ||
    getCookie("csrftoken") ||
    "";

  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-item-remove]");
    if (!btn) return;

    const root = $("#ordenModalBody");
    if (!root) return;

    const itemId = btn.getAttribute("data-item-id")
                  || btn.closest("[data-item-row]")?.dataset.itemId;
    const ordenId = root.dataset.orderId;
    const urlRemove = root.dataset.endpointItemRemove;

    if (!itemId || !urlRemove) {
      console.warn("Falta itemId o urlRemove");
      return;
    }

    if (!confirm("¿Eliminar este platillo de la orden?")) {
      return;
    }

    try {
      const res = await fetch(urlRemove, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": CSRFTOKEN,
          "X-Requested-With": "fetch",
        },
        body: JSON.stringify({
          orden_id: Number(ordenId),
          item_id: Number(itemId),
        }),
      });

      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`HTTP ${res.status}: ${txt.slice(0,200)}`);
      }

      let data = null;
      try {
        data = await res.json();
      } catch (_) {
        window.location.reload();
        return;
      }

      if (!data.ok) {
        throw new Error(data.error || "No se pudo eliminar el platillo.");
      }

      const row = btn.closest("[data-item-row]");
      if (row) row.remove();

      const tbody = root.querySelector("tbody");
      if (tbody && !tbody.querySelector("[data-item-row]")) {
        tbody.innerHTML = `
          <tr>
            <td colspan="6" class="text-center text-muted py-4">
              Sin productos.
            </td>
          </tr>`;
      }

      if (data.subtotal !== undefined) {
        const elSub = root.querySelector("tfoot tr:nth-child(1) th:last-child");
        if (elSub) elSub.textContent = `$${data.subtotal}`;
      }
      if (data.impuestos !== undefined) {
        const elImp = root.querySelector("tfoot tr:nth-child(2) th:last-child");
        if (elImp) elImp.textContent = `$${data.impuestos}`;
      }
      if (data.total !== undefined) {
        const elTot = root.querySelector("tfoot tr:nth-child(3) th:last-child");
        if (elTot) elTot.textContent = `$${data.total}`;
      }

    } catch (err) {
      console.error(err);
      alert("Error al eliminar el platillo. Revisa la consola / pestaña Network.");
    }
  });
})();
