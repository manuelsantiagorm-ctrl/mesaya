var __EN = (document.documentElement.lang || '').indexOf('en') === 0;
// Flujo público de reserva: carga horarios reales y permite elegir uno.
(function () {
  const form = document.getElementById('form-reserva');
  if (!form) return;
  const url = form.dataset.slotsUrl;
  const fecha = form.querySelector('[name="fecha"]');
  const party = form.querySelector('[name="party"]');
  const hora = document.getElementById('id_hora');
  const box = document.getElementById('slots');

  function marcar(valor) {
    hora.value = valor || '';
    box.querySelectorAll('button[data-slot]').forEach(b => b.classList.toggle('active', b.dataset.slot === valor));
  }

  function pintar(slots) {
    box.innerHTML = '';
    if (!slots.length) {
      box.innerHTML = '<div class="text-muted small" style="grid-column:1/-1"><i class="bi bi-calendar-x me-1"></i>' + (__EN ? 'No times available that day. Try another date.' : 'No hay horarios disponibles ese día. Prueba otra fecha.') + '</div>';
      marcar('');
      return;
    }
    slots.forEach(s => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'btn btn-outline-primary';
      b.dataset.slot = s.value;
      b.textContent = s.label;
      b.addEventListener('click', () => marcar(s.value));
      box.appendChild(b);
    });
    const actual = hora.value;
    if (actual && slots.some(s => s.value === actual)) marcar(actual);
    else if (actual) marcar('');
  }

  async function cargar() {
    if (!fecha.value) return;
    box.innerHTML = '<span class="text-muted small">' + (__EN ? 'Loading times…' : 'Cargando horarios…') + '</span>';
    try {
      const qs = new URLSearchParams({ fecha: fecha.value, party: party.value || '2' });
      const r = await fetch(url + '?' + qs.toString(), { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
      const data = await r.json();
      pintar(data.slots || []);
    } catch (e) {
      box.innerHTML = '<span class="text-danger small">' + (__EN ? 'We couldn\'t load the times. Please try again.' : 'No pudimos cargar los horarios. Intenta de nuevo.') + '</span>';
    }
  }

  document.querySelectorAll('[data-pick-time]').forEach(b => b.addEventListener('click', () => {
    hora.value = b.dataset.pickTime;
    cargar();
    box.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }));

  form.addEventListener('submit', (e) => {
    if (!hora.value) {
      e.preventDefault();
      e.stopImmediatePropagation();
      box.scrollIntoView({ behavior: 'smooth', block: 'center' });
      box.classList.add('border', 'border-danger', 'rounded', 'p-2');
    }
  }, true);

  fecha.addEventListener('change', cargar);
  party.addEventListener('change', cargar);
  cargar();
})();
