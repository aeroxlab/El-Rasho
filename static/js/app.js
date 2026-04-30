document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.flash-stack .flash').forEach((flash) => {
    setTimeout(() => {
      flash.style.opacity = '0';
      flash.style.transform = 'translateY(-8px)';
      flash.style.transition = 'opacity .28s ease, transform .28s ease';
      setTimeout(() => flash.remove(), 320);
    }, 3000);
  });

  const modalBackdrop = document.getElementById('modalBackdrop');
  const modalContent = document.getElementById('modalContent');
  const modalClose = document.getElementById('modalClose');

  document.querySelectorAll('[data-open-modal]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.getAttribute('data-open-modal');
      const template = document.getElementById(id);
      if (!template || !modalBackdrop || !modalContent) return;
      modalContent.innerHTML = template.innerHTML;
      modalBackdrop.classList.add('is-open');
    });
  });

  const closeModal = () => {
    if (modalBackdrop) modalBackdrop.classList.remove('is-open');
  };

  if (modalClose) modalClose.addEventListener('click', closeModal);
  if (modalBackdrop) {
    modalBackdrop.addEventListener('click', (e) => {
      if (e.target === modalBackdrop) closeModal();
    });
  }

  document.addEventListener('click', async (e) => {
    const copyBtn = e.target.closest('[data-copy]');
    if (!copyBtn) return;
    const text = copyBtn.getAttribute('data-copy') || '';
    if (!text.trim()) {
      showToast('No hay número configurado');
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      showToast('Número copiado');
    } catch (err) {
      const input = document.createElement('input');
      input.value = text;
      document.body.appendChild(input);
      input.select();
      document.execCommand('copy');
      input.remove();
      showToast('Número copiado');
    }
  });

  document.querySelectorAll('form').forEach((form) => {
    form.addEventListener('submit', () => {
      const button = form.querySelector('button[type="submit"]');
      if (!button) return;
      button.dataset.originalText = button.textContent;
      button.textContent = 'Procesando...';
      button.disabled = true;
      setTimeout(() => {
        button.disabled = false;
        button.textContent = button.dataset.originalText || 'Guardar';
      }, 6000);
    });
  });
});

function showToast(message) {
  const toast = document.createElement('div');
  toast.className = 'flash flash-success';
  toast.textContent = message;
  toast.style.position = 'fixed';
  toast.style.left = '50%';
  toast.style.bottom = '22px';
  toast.style.transform = 'translateX(-50%)';
  toast.style.zIndex = '200';
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 2200);
}
