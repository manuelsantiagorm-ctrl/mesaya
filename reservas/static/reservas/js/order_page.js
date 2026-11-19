// static/reservas/js/order_page.js — pantalla de orden del mesero
(function () {
  const app = document.getElementById("ordenApp");
  if (!app) return;
  function getCookie(name) {
    const v = `; ${document.cookie}`; const p = v.split(`; ${name}=`);
    return p.length === 2 ? decodeURIComponent(p.pop().split(";").shift()) : null;
  }
  const CSRF = getCookie("csrftoken");
  const ERR = app.dataset.msgError || "Error";

  async function post(url, fd) {
    const res = await fetch(url, { method: "POST", headers: { "X-CSRFToken": CSRF || "", "X-Requested-With": "fetch" }, body: fd || new FormData() });
    let data = {};
    try { data = await res.json(); } catch (e) { data = { ok: res.ok }; }
    if (!res.ok || data.ok === false) throw new Error(data.error || ERR);
    return data;
  }
  function fallo(e) { alert(e && e.message ? e.message : ERR); }

  // Pestañas de categorías
  document.querySelectorAll(".menu-tab").forEach(function (b) {
    b.addEventListener("click", function () {
      document.querySelectorAll(".menu-tab").forEach(x => x.classList.toggle("on", x === b));
      document.querySelectorAll(".menu-panel").forEach(p => p.classList.toggle("d-none", p.id !== b.dataset.tab));
    });
  });

  // Tocar un platillo = agregar 1
  document.querySelectorAll(".platillo").forEach(function (b) {
    b.addEventListener("click", async function () {
      b.disabled = true; b.classList.add("agregando");
      const fd = new FormData(); fd.append("item_id", b.dataset.item); fd.append("cantidad", "1");
      try { await post(app.dataset.addUrl, fd); location.reload(); } catch (e) { fallo(e); b.disabled = false; b.classList.remove("agregando"); }
    });
  });

  // Platillo que no está en el menú
  const addForm = document.getElementById("addItemForm");
  if (addForm) addForm.addEventListener("submit", async function (e) {
    e.preventDefault();
    try { await post(app.dataset.addUrl, new FormData(addForm)); location.reload(); } catch (err) { fallo(err); }
  });

  // Quitar (solo lo que no se ha mandado)
  document.querySelectorAll("[data-quitar]").forEach(function (b) {
    b.addEventListener("click", async function () {
      const fd = new FormData(); fd.append("item_id", b.dataset.quitar);
      try { await post(app.dataset.quitarUrl, fd); location.reload(); } catch (e) { fallo(e); }
    });
  });

  const btnEnviar = document.getElementById("btnEnviar");
  if (btnEnviar) btnEnviar.addEventListener("click", async function () {
    btnEnviar.disabled = true;
    try { await post(btnEnviar.dataset.url); location.reload(); } catch (e) { fallo(e); btnEnviar.disabled = false; }
  });

  const btnCobrar = document.getElementById("btnCobrar");
  if (btnCobrar) btnCobrar.addEventListener("click", async function () {
    const propina = prompt(app.dataset.msgPropina || "Propina", "0");
    if (propina === null) return;
    const fd = new FormData(); fd.append("propina", propina || "0"); fd.append("metodo", "CASH");
    try { const d = await post(btnCobrar.dataset.url, fd); location = d.redirect || app.querySelector("a[href]").href; } catch (e) { fallo(e); }
  });
})();
