(function () {
  if (window.getOralConfig) return;

  window.getOralConfig = function getOralConfig() {
    if (window.ORAL_CONFIG && typeof window.ORAL_CONFIG === "object") {
      return window.ORAL_CONFIG;
    }

    const el = document.getElementById("oral-config");
    if (!el) {
      window.ORAL_CONFIG = {};
      return window.ORAL_CONFIG;
    }

    try {
      window.ORAL_CONFIG = JSON.parse(el.textContent || "{}") || {};
    } catch (e) {
      console.warn("Failed to parse oral-config JSON", e);
      window.ORAL_CONFIG = {};
    }
    return window.ORAL_CONFIG;
  };
})();
