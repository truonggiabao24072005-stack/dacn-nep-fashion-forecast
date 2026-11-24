document.querySelectorAll('[data-research-run]').forEach(form => {
  form.addEventListener('submit', () => {
    const button = form.querySelector('[data-run-button]');
    const status = form.querySelector('[data-run-status]');
    if (button) { button.disabled = true; button.textContent = 'Đang chạy dự báo…'; }
    if (status) status.textContent = 'Đang tính từ lịch sử bán hàng. Vui lòng chờ kết quả.';
  });
});
