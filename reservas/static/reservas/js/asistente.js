var __EN = (document.documentElement.lang || '').indexOf('en') === 0;
// Chat del asistente de reservaciones
(function () {
  const log = document.getElementById('chat-log');
  const form = document.getElementById('chat-form');
  const input = document.getElementById('chat-input');
  if (!log || !form) return;
  const url = log.dataset.url;
  const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;

  function enlazar(texto) {
    // Escapa HTML y convierte URLs en enlaces
    const esc = texto.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return esc.replace(/(https?:\/\/[^\s)]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>')
              .replace(/\n/g, '<br>');
  }
  function agregar(texto, quien) {
    const d = document.createElement('div');
    d.className = 'chat-msg ' + quien;
    d.innerHTML = enlazar(texto);
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
    return d;
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const texto = input.value.trim();
    if (!texto) return;
    agregar(texto, 'user');
    input.value = '';
    input.disabled = true;
    const espera = agregar(__EN ? 'Typing…' : 'Escribiendo…', 'bot typing');
    try {
      const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify({ mensaje: texto }),
      });
      const data = await r.json();
      espera.remove();
      agregar(data.respuesta || data.error || (__EN ? 'I couldn\'t answer, please try again.' : 'No pude responder, intenta de nuevo.'), 'bot');
    } catch (err) {
      espera.remove();
      agregar(__EN ? 'Connection lost. Please try again.' : 'Se perdió la conexión. Intenta de nuevo.', 'bot');
    } finally {
      input.disabled = false;
      input.focus();
    }
  });
})();
