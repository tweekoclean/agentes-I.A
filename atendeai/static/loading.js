/* Transições de página e progresso de operações, sem aguardar vídeos ou imagens fora da tela. */
(() => {
  "use strict";
  const root = document.documentElement;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  let navigationTimer, safetyTimer, operations = 0, entering = true;
  root.classList.add("nelvo-loading");
  function finish() {
    clearTimeout(safetyTimer);
    clearTimeout(navigationTimer);
    root.classList.remove("nelvo-loading", "nelvo-leaving");
    root.classList.add("nelvo-ready");
    entering = false;
  }
  // A interface continua disponível mesmo se um recurso falhar ou a navegação for cancelada.
  safetyTimer = setTimeout(finish, 4000);
  window.NelvoLoading = {
    begin() {
      operations++;
      root.classList.add("nelvo-working");
      let ended = false;
      return () => {
        if (ended) return;
        ended = true;
        operations = Math.max(0, operations - 1);
        root.classList.toggle("nelvo-working", operations > 0);
      };
    },
  };
  document.addEventListener("DOMContentLoaded", async () => {
    const logo = document.querySelector("#nelvo-loader img");
    await Promise.race([
      logo?.decode?.().catch(() => {}),
      new Promise(resolve => setTimeout(resolve, 1000)),
    ]);
    requestAnimationFrame(finish);
    document.addEventListener("click", event => {
      const link = event.target.closest("a[href]");
      if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || link.target || link.hasAttribute("download")) return;
      const destination = new URL(link.href, location.href);
      if (destination.origin !== location.origin || !["/", "/aplicar", "/painel"].includes(destination.pathname)) return;
      if (destination.pathname === location.pathname && destination.search === location.search) return;
      if (reduced.matches) return;
      event.preventDefault();
      if (root.classList.contains("nelvo-leaving")) return;
      root.classList.remove("nelvo-ready");
      root.classList.add("nelvo-leaving");
      navigationTimer = setTimeout(() => location.assign(destination.href), 180);
      safetyTimer = setTimeout(finish, 4000);
    });
  }, { once: true });
  addEventListener("pageshow", event => {
    if (event.persisted || !entering) finish();
    if (event.persisted) { operations = 0; root.classList.remove("nelvo-working"); }
  });
  reduced.addEventListener("change", () => {
    if (reduced.matches && entering) finish();
  });
})();
