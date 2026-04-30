document.addEventListener('DOMContentLoaded', () => {
  setupModals();
  setupCopyButtons();
  setupConfirmForms();
  setupLoadingButtons();
  setupPublicLoader();
  setupQrCroppers();
  setupPublicLinkFeedback();
});

function setupModals() {
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
      setupQrCroppers(modalContent);
      setupConfirmForms(modalContent);
      setupLoadingButtons(modalContent);
    });
  });
  const closeModal = () => modalBackdrop && modalBackdrop.classList.remove('is-open');
  if (modalClose) modalClose.addEventListener('click', closeModal);
  if (modalBackdrop) modalBackdrop.addEventListener('click', (e) => { if (e.target === modalBackdrop) closeModal(); });
}

function setupCopyButtons(root = document) {
  root.addEventListener('click', async (e) => {
    const copyBtn = e.target.closest('[data-copy]');
    if (!copyBtn) return;
    const text = copyBtn.getAttribute('data-copy') || '';
    if (!text.trim()) return showToast('No hay dato configurado');
    try { await navigator.clipboard.writeText(text); }
    catch (_) {
      const input = document.createElement('input');
      input.value = text; document.body.appendChild(input); input.select(); document.execCommand('copy'); input.remove();
    }
    showToast('Copiado correctamente');
  }, { once: root !== document });
}

function setupConfirmForms(root = document) {
  root.querySelectorAll('.confirm-form').forEach((form) => {
    if (form.dataset.readyConfirm) return;
    form.dataset.readyConfirm = '1';
    form.addEventListener('submit', (e) => {
      const msg = form.dataset.confirm || '¿Confirmas esta acción?';
      if (!confirm(msg)) e.preventDefault();
    });
  });
}

function setupLoadingButtons(root = document) {
  root.querySelectorAll('form').forEach((form) => {
    if (form.dataset.readySubmit) return;
    form.dataset.readySubmit = '1';
    form.addEventListener('submit', () => {
      const button = form.querySelector('button[type="submit"]');
      if (!button) return;
      button.dataset.originalText = button.textContent;
      button.textContent = 'Procesando...';
      button.disabled = true;
      setTimeout(() => { button.disabled = false; button.textContent = button.dataset.originalText || 'Guardar'; }, 6500);
    });
  });
}

function setupPublicLoader() {
  const loader = document.getElementById('publicLoader');
  const detail = document.getElementById('publicDetail');
  if (!loader || !detail) return;
  setTimeout(() => {
    loader.classList.add('is-done');
    detail.classList.remove('is-hidden');
    detail.classList.add('is-ready');
  }, 1700);
}

function setupPublicLinkFeedback(root = document) {
  root.querySelectorAll('.public-link').forEach((link) => {
    if (link.dataset.readyLink) return;
    link.dataset.readyLink = '1';
    link.addEventListener('click', () => showToast('Link público listo. Abriendo detalle...'));
  });
}

function setupQrCroppers(root = document) {
  root.querySelectorAll('.qr-payment-form').forEach((form) => {
    const input = form.querySelector('.qr-file-input');
    const cropper = form.querySelector('[data-cropper]');
    if (!input || !cropper || input.dataset.readyCrop) return;
    input.dataset.readyCrop = '1';
    const img = cropper.querySelector('img');
    const zoom = cropper.querySelector('.crop-zoom');
    const btn = cropper.querySelector('.apply-crop');
    const status = cropper.querySelector('.crop-status');
    let state = { url: null, dragging: false, sx: 0, sy: 0, x: 0, y: 0, scale: 1 };

    const applyTransform = () => {
      img.style.transform = `translate(${state.x}px, ${state.y}px) scale(${state.scale})`;
    };

    input.addEventListener('change', () => {
      const file = input.files && input.files[0];
      if (!file) return;
      if (state.url) URL.revokeObjectURL(state.url);
      state.url = URL.createObjectURL(file);
      img.src = state.url;
      state.x = 0; state.y = 0; state.scale = 1; zoom.value = 1;
      cropper.hidden = false;
      status.textContent = 'Recorte pendiente';
      applyTransform();
    });

    zoom.addEventListener('input', () => { state.scale = parseFloat(zoom.value || '1'); applyTransform(); });
    img.addEventListener('pointerdown', (e) => { state.dragging = true; state.sx = e.clientX - state.x; state.sy = e.clientY - state.y; img.setPointerCapture(e.pointerId); });
    img.addEventListener('pointermove', (e) => { if (!state.dragging) return; state.x = e.clientX - state.sx; state.y = e.clientY - state.sy; applyTransform(); });
    img.addEventListener('pointerup', () => { state.dragging = false; });

    btn.addEventListener('click', async () => {
      if (!input.files || !input.files[0] || !img.complete) return;
      const frame = cropper.querySelector('.crop-frame');
      const rect = frame.getBoundingClientRect();
      const canvas = document.createElement('canvas');
      canvas.width = 900; canvas.height = 900;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);
      const imgNaturalRatio = img.naturalWidth / img.naturalHeight;
      let drawW = rect.width, drawH = rect.height;
      if (imgNaturalRatio > 1) drawH = drawW / imgNaturalRatio; else drawW = drawH * imgNaturalRatio;
      drawW *= state.scale; drawH *= state.scale;
      const dx = (rect.width - drawW) / 2 + state.x;
      const dy = (rect.height - drawH) / 2 + state.y;
      const scaleToCanvas = canvas.width / rect.width;
      ctx.drawImage(img, dx * scaleToCanvas, dy * scaleToCanvas, drawW * scaleToCanvas, drawH * scaleToCanvas);
      canvas.toBlob((blob) => {
        const cropped = new File([blob], 'qr_recortado.png', { type: 'image/png' });
        const dt = new DataTransfer();
        dt.items.add(cropped);
        input.files = dt.files;
        status.textContent = 'Recorte aplicado';
        showToast('QR recortado listo para guardar');
      }, 'image/png', 0.95);
    });
  });
}

function showToast(message) {
  const toast = document.createElement('div');
  toast.className = 'flash flash-success';
  toast.textContent = message;
  toast.style.position = 'fixed';
  toast.style.left = '50%';
  toast.style.bottom = '22px';
  toast.style.transform = 'translateX(-50%)';
  toast.style.zIndex = '300';
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 2400);
}
