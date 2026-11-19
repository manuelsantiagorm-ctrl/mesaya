// Página comercial: chat animado, calculadora y respaldo de imágenes.
(function () {
  // Imágenes externas: si fallan, se ocultan y queda el fondo degradado
  document.querySelectorAll('img[data-fallback]').forEach(function (img) {
    img.addEventListener('error', function () { img.classList.add('img-broken'); });
  });

  // ---------- Chat del asistente (demostración) ----------
  var chat = document.getElementById('hero-chat');
  if (chat) {
    var EN = (document.documentElement.lang || '').indexOf('en') === 0;
    var guion = EN ? [
      ['in', 'Hi! Do you have a table for 4 tomorrow around 2? 🙌'],
      ['out', 'Hi Mariana! Tomorrow at 2:00 pm I have a table for 4 on the patio 🌿 or 2:30 pm indoors. Which one do you prefer?'],
      ['in', 'Patio please'],
      ['out', 'Done! Table for 4 tomorrow at 2:00 pm on the patio ✅ I sent your confirmation and a link in case you need to change it.'],
      ['in', 'Are dogs allowed? 🐶'],
      ['out', 'Of course! The patio is pet-friendly. See you there!']
    ] : [
      ['in', '¡Hola! ¿Tienen mesa para 4 mañana como a las 2? 🙌'],
      ['out', '¡Hola Mariana! Mañana a las 14:00 tengo mesa para 4 en terraza 🌿 o a las 14:30 en interior. ¿Cuál prefieres?'],
      ['in', 'Terraza porfa'],
      ['out', '¡Listo! Mesa para 4 mañana 14:00 en terraza ✅ Te envié tu confirmación y el enlace por si necesitas cambiarla.'],
      ['in', '¿Aceptan perritos? 🐶'],
      ['out', '¡Claro! La terraza es pet-friendly. ¡Los esperamos!']
    ];
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var i = 0;
    function agrega(tipo, texto) {
      var d = document.createElement('div');
      d.className = 'msg ' + tipo;
      d.textContent = texto;
      chat.appendChild(d);
      while (chat.children.length > 6) chat.removeChild(chat.firstChild);
      return d;
    }
    function paso() {
      if (i >= guion.length) {
        setTimeout(function () { chat.innerHTML = ''; i = 0; paso(); }, 4000);
        return;
      }
      var m = guion[i++];
      if (m[0] === 'out' && !reduce) {
        var t = document.createElement('div');
        t.className = 'msg typing';
        t.innerHTML = '<span></span><span></span><span></span>';
        chat.appendChild(t);
        setTimeout(function () { t.remove(); agrega(m[0], m[1]); setTimeout(paso, 1400); }, 1200);
      } else {
        agrega(m[0], m[1]);
        setTimeout(paso, reduce ? 300 : 1300);
      }
    }
    paso();
  }

  // ---------- Calculadora ----------
  var $ = function (id) { return document.getElementById(id); };
  if ($('c-res')) {
    var fmt = new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN', maximumFractionDigits: 0 });
    var PLAN = 1199;
    function calc() {
      var res = +$('c-res').value, per = +$('c-per').value, tic = +$('c-tic').value,
          ns = +$('c-ns').value / 100, red = +$('c-red').value / 100, ext = +$('c-ext').value;
      $('o-res').textContent = res; $('o-per').textContent = per; $('o-tic').textContent = fmt.format(tic);
      $('o-ns').textContent = Math.round(ns * 100) + '%'; $('o-red').textContent = Math.round(red * 100) + '%';
      $('o-ext').textContent = ext;
      var semanas = 4.33;
      var recuperado = res * ns * red * per * tic * semanas;
      var extra = ext * per * tic * semanas;
      var total = recuperado + extra;
      $('r-ns').textContent = fmt.format(recuperado);
      $('r-ext').textContent = fmt.format(extra);
      $('r-total').textContent = fmt.format(total);
      var veces = total / PLAN;
      var EN2 = (document.documentElement.lang || '').indexOf('en') === 0;
      $('r-roi').textContent = veces >= 1
        ? (EN2 ? 'That is ' + veces.toFixed(1).replace('.0', '') + 'x the cost of the Pro plan'
               : 'Equivale a ' + veces.toFixed(1).replace('.0', '') + ' veces lo que cuesta el plan Pro')
        : (EN2 ? 'Adjust the values to see your case' : 'Ajusta los valores para ver tu caso');
    }
    ['c-res', 'c-per', 'c-tic', 'c-ns', 'c-red', 'c-ext'].forEach(function (id) { $(id).addEventListener('input', calc); });
    calc();
  }
})();
