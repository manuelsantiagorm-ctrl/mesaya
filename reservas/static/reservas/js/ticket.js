// Ticket térmico: imprimir al cargar y botones sin JS en línea (CSP)
(function () {
  if (document.body.hasAttribute('data-autoprint')) window.addEventListener('load', () => window.print());
  document.addEventListener('click', (e) => {
    const p = e.target.closest('[data-print]');
    if (p) { window.print(); return; }
    const h = e.target.closest('[data-href]');
    if (h) window.location.href = h.dataset.href;
  });
})();
