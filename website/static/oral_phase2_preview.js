(function () {
  function getCsrfToken() {
    const el = document.querySelector('meta[name="csrf-token"]');
    return el ? el.getAttribute('content') : '';
  }

  function getSelectedTests() {
    const checks = document.querySelectorAll('input[name="selected_tests"]');
    return Array.from(checks)
      .filter((cb) => cb.checked)
      .map((cb) => cb.value);
  }

  function setLoading() {
    const container = document.getElementById("test-results-container");
    if (!container) return;
    container.innerHTML = `
      <hr>
      <div class="text-muted small d-flex align-items-center">
        <span class="spinner-border spinner-border-sm mr-2" role="status" aria-hidden="true"></span>
        Loading results…
      </div>
    `;
  }

  async function preview() {
    const endpoint = window.ORAL_PREVIEW_TESTS_URL;
    if (!endpoint) return;

    const selected = getSelectedTests();
    setLoading();

    try {
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken(),
          "X-CSRF-Token": getCsrfToken(),
        },
        body: JSON.stringify({ selected_tests: selected }),
      });

      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || !data.ok) return;

      const container = document.getElementById("test-results-container");
      if (container) container.innerHTML = data.html || "";

      const wrapper = document.getElementById("radiograph-report-wrapper");
      if (wrapper) {
        const shouldShow = !!data.show_radiograph_report;
        const wasHidden = wrapper.classList.contains("d-none");

        wrapper.classList.toggle("d-none", !shouldShow);
        wrapper.classList.toggle("d-block", shouldShow);

        if (shouldShow && wasHidden) {
          wrapper.classList.add("soft-pulse");
          wrapper.scrollIntoView({ behavior: "smooth", block: "nearest" });
          setTimeout(() => wrapper.classList.remove("soft-pulse"), 2600);
        }
      }
    } catch (e) {}
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.addEventListener("change", (e) => {
      const t = e.target;
      if (t && t.matches('input[name="selected_tests"]')) {
        preview();
      }
    });

    preview();
  });
})();
