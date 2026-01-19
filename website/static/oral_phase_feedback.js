(function () {
  if (window.__ORAL_PHASE_FEEDBACK_INITED) return;
  window.__ORAL_PHASE_FEEDBACK_INITED = true;

  function getCsrfToken() {
    const tokenEl = document.querySelector('meta[name="csrf-token"]');
    return tokenEl ? tokenEl.getAttribute("content") : "";
  }

  async function saveOnlyNearestForm(btn) {
    const form = btn && btn.closest ? btn.closest("form") : document.querySelector("form");
    if (!form) return true;

    const formData = new FormData(form);
    formData.append("save_only", "1");

    try {
      const resp = await fetch(window.location.href, {
        method: "POST",
        headers: {
          "X-CSRFToken": getCsrfToken(),
          "X-CSRF-Token": getCsrfToken(),
          "X-Requested-With": "XMLHttpRequest"
        },
        body: formData
      });
      return resp.ok;
    } catch (e) {
      return false;
    }
  }

  function openDetailsAndScroll(details, container) {
    if (details) details.open = true;
    try {
      (container || details)?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    } catch (e) {}
  }

  function getJsonHeaders() {
    return {
      "Content-Type": "application/json",
      "X-CSRFToken": getCsrfToken(),
      "X-CSRF-Token": getCsrfToken()
    };
  }

  function bindFeedbackButton(btn) {
    if (btn.dataset.bound === "1") return;
    btn.dataset.bound = "1";

    const url = btn.getAttribute("data-url") || window.ORAL_PHASE_FEEDBACK_URL || "";
    const statusId = btn.getAttribute("data-status") || "phase-feedback-status";
    const containerId = btn.getAttribute("data-container") || "phase-feedback-container";
    const detailsId = btn.getAttribute("data-details") || "phase-feedback-details";
    const scope = btn.getAttribute("data-scope") || null;
    const requiredSelector = btn.getAttribute("data-required") || null;
    const minChars = parseInt(btn.getAttribute("data-minchars") || "20", 10);

    const status = document.getElementById(statusId);
    const container = document.getElementById(containerId);
    const details = document.getElementById(detailsId);

    if (!container) return;
    if (!url) {
      container.innerHTML = "<div class='alert alert-warning mb-0'>Feedback URL is not configured.</div>";
      btn.disabled = true;
      return;
    }

    function hasRequiredText() {
      if (!requiredSelector) return true;
      const fields = document.querySelectorAll(requiredSelector);
      return Array.from(fields).some((el) => ((el.value || "").trim().length >= minChars));
    }

    function updateButtonState() {
      if (!requiredSelector) return;
      btn.disabled = !hasRequiredText();
    }

    updateButtonState();
    if (requiredSelector) {
      document.querySelectorAll(requiredSelector).forEach((el) => {
        el.addEventListener("input", updateButtonState);
      });
    }

    btn.addEventListener("click", async () => {
      if (requiredSelector && !hasRequiredText()) {
        container.innerHTML =
          `<div class="alert alert-info mb-0">Add a little more detail before requesting feedback (at least ${minChars} characters).</div>`;
        openDetailsAndScroll(details, container);
        return;
      }

      const originalLabel = btn.dataset.label || btn.innerText;
      btn.dataset._originalLabel = originalLabel;
      btn.innerText = "Checking...";
      btn.disabled = true;

      try {
        const saved = await saveOnlyNearestForm(btn);
        if (!saved) {
          container.innerHTML =
            "<div class='alert alert-danger mb-0'>Could not save your notes before generating feedback. Please try again.</div>";
          openDetailsAndScroll(details, container);
          return;
        }

        const resp = await fetch(url, {
          method: "POST",
          headers: getJsonHeaders(),
          body: JSON.stringify({ scope })
        });

        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.ok) {
          container.innerHTML =
            `<div class="alert alert-danger mb-0">${data.error || "Failed to generate feedback."}</div>`;
          openDetailsAndScroll(details, container);
          return;
        }

        container.innerHTML =
          data.feedback_html || `<div class="alert alert-success mb-0">Feedback generated.</div>`;
        openDetailsAndScroll(details, container);
      } catch (e) {
        container.innerHTML =
          "<div class='alert alert-danger mb-0'>Network error while generating feedback.</div>";
        openDetailsAndScroll(details, container);
      } finally {
        btn.innerText = btn.dataset._originalLabel || originalLabel;
        btn.disabled = requiredSelector ? !hasRequiredText() : false;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    const primaryBtn = document.getElementById("phase-feedback-btn");
    if (primaryBtn) bindFeedbackButton(primaryBtn);

    document.querySelectorAll("[data-phase-feedback]").forEach((btn) => bindFeedbackButton(btn));
  });
})();
