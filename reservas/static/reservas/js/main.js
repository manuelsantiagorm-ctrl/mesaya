// Auto-dismiss de alerts (5s)
window.addEventListener('DOMContentLoaded', () => {
  setTimeout(() => {
    document.querySelectorAll('.alert').forEach(el => {
      const inst = bootstrap.Alert.getOrCreateInstance(el);
      inst.close();
    });
  }, 5000);
});

// reservas/static/reservas/js/main.js

// Auto-cerrar mensajes de Django
(function () {
  const AUTO_CLOSE_MS = 4000;
  setTimeout(() => {
    document.querySelectorAll('.alert').forEach(el => {
      // Si usas Bootstrap, quitar 'show' aplica el fade
      el.classList.remove('show');
      setTimeout(() => el.remove(), 300);
    });
  }, AUTO_CLOSE_MS);
})();

// Si quieres evitar multi-submit en forms:
document.addEventListener('submit', (e) => {
  const btn = e.target.querySelector('[type="submit"]');
  if (btn && !e.target.hasAttribute('data-no-lock')) {
    btn.disabled = true;
    btn.dataset.originalText = btn.innerHTML;
    btn.innerHTML = btn.dataset.loadingText || 'Procesando...';
  }
});


// Selects que se envían solos (sin JS en línea, compatible con CSP)
document.addEventListener('change', (e) => {
  const el = e.target;
  if (el.matches && el.matches('select[data-autosubmit]') && el.form) el.form.submit();
});

// Confirmación antes de enviar formularios marcados con data-confirm
document.addEventListener('submit', (e) => {
  const msg = e.target.dataset && e.target.dataset.confirm;
  if (msg && !window.confirm(msg)) { e.preventDefault(); e.stopImmediatePropagation(); }
}, true);

// Campos de solo lectura que se seleccionan al hacer clic (enlaces / código para copiar)
document.addEventListener('click', (e) => {
  if (e.target.matches && e.target.matches('[data-copy]')) e.target.select();
});

// Confirmación en botones/enlaces con data-confirm-click
document.addEventListener('click', (e) => {
  const el = e.target.closest && e.target.closest('[data-confirm-click]');
  if (el && !window.confirm(el.dataset.confirmClick)) { e.preventDefault(); e.stopImmediatePropagation(); }
}, true);

// Navegación con sombra al hacer scroll + revelado de secciones
(function () {
  const nav = document.querySelector('.brand-nav');
  const onScroll = () => nav && nav.classList.toggle('is-scrolled', window.scrollY > 8);
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
  const els = document.querySelectorAll('.reveal');
  if (!('IntersectionObserver' in window)) return;
  document.documentElement.classList.add('js-reveal');
  const io = new IntersectionObserver((entries) => {
    entries.forEach(en => { if (en.isIntersecting) { en.target.classList.add('is-in'); io.unobserve(en.target); } });
  }, { threshold: 0.12 });
  els.forEach(e => io.observe(e));
})();

// Contadores animados: <span data-count="123">0</span>
(function () {
  const els = document.querySelectorAll('[data-count]');
  els.forEach(el => {
    const fin = parseFloat(el.dataset.count) || 0;
    const dec = (el.dataset.count.split('.')[1] || '').length;
    const t0 = performance.now(), dur = 900;
    const step = (t) => {
      const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      el.textContent = (fin * e).toFixed(dec);
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
})();

// Pantallas que se actualizan solas (meseros, cocina): recarga si nadie está escribiendo
(function () {
  const el = document.querySelector('[data-autorefresh]');
  if (!el) return;
  const seg = parseInt(el.getAttribute('data-autorefresh'), 10) || 30;
  setInterval(function () {
    const a = document.activeElement;
    const ocupado = a && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA' || a.tagName === 'SELECT');
    if (!ocupado && !document.querySelector('.modal.show')) location.reload();
  }, seg * 1000);
})();

// Equipo: el paso "¿En qué sucursal?" solo aparece para puestos de una sucursal
document.querySelectorAll('[data-puesto-form]').forEach(function (f) {
  const porSuc = (f.getAttribute('data-por-sucursal') || '').split(',');
  const paso = f.querySelector('.suc-step');
  function sync() {
    const r = f.querySelector('input[type=radio]:checked');
    if (paso) paso.classList.toggle('d-none', !!r && porSuc.indexOf(r.value) === -1);
  }
  f.addEventListener('change', sync); sync();
});
