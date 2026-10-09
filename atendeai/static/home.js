(() => {
  "use strict";
  const toggle = document.getElementById("home-menu-toggle");
  const nav = document.getElementById("home-nav");
  const close = () => { nav.classList.remove("is-open"); toggle.setAttribute("aria-expanded", "false"); };
  toggle.addEventListener("click", () => {
    const open = toggle.getAttribute("aria-expanded") !== "true";
    toggle.setAttribute("aria-expanded", String(open)); nav.classList.toggle("is-open", open);
  });
  nav.addEventListener("click", (event) => { if (event.target.closest("a")) close(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") close(); });
  window.matchMedia("(min-width: 901px)").addEventListener("change", close);
})();
