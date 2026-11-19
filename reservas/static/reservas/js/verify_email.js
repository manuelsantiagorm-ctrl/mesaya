// Lógica de UX para la verificación de correo (OTP).
// Archivo: static/reservas/js/verify_email.js
(function () {
  const code = document.getElementById('id_code') || document.querySelector('[autocomplete="one-time-code"]');
  if (code) {
    code.focus();
    code.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        this.closest('form')?.submit();
      }
    });
  }

  // Cooldown visual para "Reenviar código"
  const btn = document.getElementById('resendBtn');
  if (!btn) return;
  let remaining = parseInt(btn.dataset.remaining || '0', 10);
  const original = btn.textContent;

  function tick(){
    if (remaining > 0){
      btn.disabled = true;
      btn.textContent = original + ' (' + remaining + 's)';
      remaining -= 1;
      setTimeout(tick, 1000);
    } else {
      btn.disabled = false;
      btn.textContent = original;
    }
  }
  if (remaining > 0) tick();
})();
