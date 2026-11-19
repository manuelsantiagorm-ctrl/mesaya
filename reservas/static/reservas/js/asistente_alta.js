var __EN = (document.documentElement.lang || '').indexOf('en') === 0;
// Asistente de alta: propone tiempos típicos y avisa de respuestas contradictorias.
(function () {
  var f = document.getElementById('wizard');
  if (!f) return;
  var $ = function (id) { return document.getElementById(id); };
  f.querySelectorAll('input[name=tipo]').forEach(function (r) {
    r.addEventListener('change', function () {
      [['ps', 'ps'], ['pf', 'pf'], ['g4', 'g4'], ['g6', 'g6']].forEach(function (p) {
        var el = $(p[0]);
        if (!el.dataset.tocado) el.value = r.dataset[p[1]];
      });
      revisa();
    });
  });
  ['ps', 'pf', 'g4', 'g6'].forEach(function (id) {
    $(id).addEventListener('input', function () { this.dataset.tocado = '1'; revisa(); });
  });
  function revisa() {
    var w = $('wz-warn'), msgs = [];
    var tipo = (f.querySelector('input[name=tipo]:checked') || {}).value;
    var ps = +$('ps').value, pf = +$('pf').value, g4 = +$('g4').value, g6 = +$('g6').value;
    if (tipo === 'rapida' && ps > 75) msgs.push(__EN ? ps + ' min per couple is a lot for fast food. Is that because of lingering after the meal?' : 'Para comida rápida, ' + ps + ' min por pareja es mucho. ¿Lo dices por la sobremesa?');
    if (tipo === 'manteles' && ps && ps < 60) msgs.push(__EN ? 'In fine dining a couple usually stays more than an hour. Are you sure?' : 'En alta cocina una pareja suele quedarse más de una hora. ¿Seguro?');
    if (g4 && ps && g4 < ps) msgs.push(__EN ? 'A group of 4 usually takes longer than a couple.' : 'Normalmente un grupo de 4 tarda más que una pareja.');
    if (g6 && g4 && g6 < g4) msgs.push(__EN ? 'A group of 6+ usually takes longer than a group of 4.' : 'Normalmente un grupo de 6+ tarda más que uno de 4.');
    w.classList.toggle('d-none', !msgs.length);
    w.textContent = msgs.join(' ');
  }
  revisa();
})();
