/* A preferência de aparência é pública; nenhuma credencial é armazenada. */
(() => {
  "use strict";
  const system = matchMedia("(prefers-color-scheme: dark)");
  let saved;
  try { saved = localStorage.getItem("nelvo-theme"); } catch {}
  if (!["light", "dark"].includes(saved)) saved = null;
  function apply(theme) {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    document.querySelectorAll("[data-theme-toggle]").forEach(button => {
      const dark = theme === "dark";
      button.setAttribute("aria-pressed", String(dark));
      button.setAttribute("aria-label", dark ? "Ativar tema claro" : "Ativar tema escuro");
      button.title = dark ? "Ativar tema claro" : "Ativar tema escuro";
      button.querySelector("[data-theme-icon]").textContent = dark ? "☀" : "☾";
    });
  }
  apply(saved || (system.matches ? "dark" : "light"));
  document.addEventListener("DOMContentLoaded", () => {
    apply(document.documentElement.dataset.theme);
    document.querySelectorAll("[data-theme-toggle]").forEach(button => button.addEventListener("click", () => {
      saved = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      try { localStorage.setItem("nelvo-theme", saved); } catch {}
      apply(saved);
    }));
  });
  system.addEventListener("change", () => { if (!saved) apply(system.matches ? "dark" : "light"); });
  window.addEventListener("storage", event => {
    if (event.key !== "nelvo-theme") return;
    saved = ["light", "dark"].includes(event.newValue) ? event.newValue : null;
    apply(saved || (system.matches ? "dark" : "light"));
  });
})();
