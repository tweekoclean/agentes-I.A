(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const compactHeight = window.matchMedia("(max-height: 640px)");
  const nav = $("home-nav");
  const closeMenu = () => { nav.classList.remove("is-open"); $("home-menu-toggle").setAttribute("aria-expanded", "false"); };
  $("home-menu-toggle").addEventListener("click", () => {
    const open = $("home-menu-toggle").getAttribute("aria-expanded") !== "true";
    $("home-menu-toggle").setAttribute("aria-expanded", String(open)); nav.classList.toggle("is-open", open);
  });
  nav.addEventListener("click", (event) => { if (event.target.closest("a")) closeMenu(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeMenu(); });
  window.matchMedia("(min-width: 901px)").addEventListener("change", closeMenu);

  // Um único formulário compartilhado com /aplicar, sem iframe ou cópias dos campos.
  const modal = $("application-modal");
  let opener, form, loading, requestedService;
  async function loadForm() {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch("/aplicar/conteudo", { credentials: "omit", cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error("Não foi possível carregar.");
      const fragment = new DOMParser().parseFromString(await response.text(), "text/html").querySelector(".application-card-shell");
      if (!fragment?.querySelector("#public-application-form")) throw new Error("Formulário indisponível.");
      $("application-modal-body").replaceChildren(document.importNode(fragment, true));
      form = window.NelvoApplication.mount($("application-modal-body"), { service: requestedService });
    } finally { clearTimeout(timer); }
  }
  async function openForm(link) {
    opener = link; requestedService = new URL(link.href, location.href).searchParams.get("servico");
    $("application-modal-error").hidden = true;
    if (!modal.open) modal.showModal();
    document.body.classList.add("modal-open");
    closeMenu();
    try {
      if (!form) { loading ||= loadForm(); await loading; }
      form.selectService(requestedService);
      if (modal.open) form.focus();
    } catch {
      loading = null;
      const message = document.createElement("p"); message.textContent = "Não foi possível carregar o formulário.";
      const retry = document.createElement("button"); retry.type = "button"; retry.className = "button primary"; retry.textContent = "Tentar novamente";
      retry.addEventListener("click", () => openForm(opener));
      const fallback = document.createElement("a"); fallback.href = "/aplicar"; fallback.className = "button secondary"; fallback.textContent = "Abrir formulário em outra página"; fallback.dataset.standalone = "true";
      $("application-modal-body").replaceChildren(message, retry, fallback);
    }
  }
  document.addEventListener("click", (event) => {
    const link = event.target.closest('a[href^="/aplicar"]');
    if (!link || link.dataset.standalone || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
    const path = new URL(link.href, location.href);
    if (path.pathname !== "/aplicar" || path.origin !== location.origin) return;
    event.preventDefault(); openForm(link);
  });
  $("application-modal-close").addEventListener("click", () => modal.close());
  modal.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const focusable = [...modal.querySelectorAll('a[href], button, input, select, textarea, [tabindex]')]
      .filter((el) => !el.disabled && el.tabIndex >= 0 && el.getClientRects().length);
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  });
  modal.addEventListener("click", (event) => {
    const rect = modal.getBoundingClientRect();
    if (event.target === modal && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) modal.close();
  });
  modal.addEventListener("close", () => { document.body.classList.remove("modal-open"); opener?.focus({ preventScroll: true }); });

  const story = $("services-story");
  const tabs = [...document.querySelectorAll(".service-tabs button")];
  const panels = [...document.querySelectorAll(".solution-card")];
  const markers = tabs.map((_, i) => $("service-marker-" + i));
  let active = -1, queued = false, navigation = null;
  function setService(index) {
    if (index === active) return;
    active = index;
    tabs.forEach((tab, i) => { if (i === index) tab.setAttribute("aria-current", "step"); else tab.removeAttribute("aria-current"); });
    panels.forEach((panel, i) => { panel.classList.toggle("is-active", i === index); panel.classList.toggle("is-past", i < index); });
  }
  function stickyTop() { return parseFloat(getComputedStyle(panels[0]).top) || 110; }
  function updateScroll() {
    queued = false;
    if (navigation && Math.abs(window.scrollY - navigation.top) > 4 && performance.now() < navigation.until) return;
    navigation = null;
    let index = 0;
    markers.forEach((marker, i) => { if (marker.getBoundingClientRect().top <= stickyTop() + 35) index = i; });
    setService(index);
  }
  function schedule() { if (!queued) { queued = true; requestAnimationFrame(updateScroll); } }
  function navigate(index, focus = false) {
    setService(index);
    if (focus) tabs[index].focus({ preventScroll: true });
    const destination = window.scrollY + markers[index].getBoundingClientRect().top - stickyTop();
    navigation = { top: destination, until: performance.now() + 2000 };
    window.scrollTo({ top: destination, behavior: reduced.matches ? "instant" : "smooth" });
  }
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => navigate(i));
    tab.addEventListener("keydown", (event) => {
      const next = ({ ArrowRight: (i + 1) % 4, ArrowDown: (i + 1) % 4, ArrowLeft: (i + 3) % 4, ArrowUp: (i + 3) % 4, Home: 0, End: 3 })[event.key];
      if (next !== undefined) { event.preventDefault(); navigate(next, true); }
    });
  });
  const film = $("nelvo-film");
  let userPaused = false, automaticPause = false;
  film.addEventListener("pause", () => { if (!automaticPause && !film.ended) userPaused = true; });
  film.addEventListener("play", () => { userPaused = false; automaticPause = false; });
  function pauseFilm() { automaticPause = true; film.pause(); }
  function resumeFilm() { if (!userPaused && !reduced.matches && !document.hidden) { automaticPause = false; film.play().catch(() => {}); } }
  document.body.classList.add("motion-ready");
  function updatePreference() {
    document.body.classList.toggle("motion-reduced", reduced.matches);
    document.body.classList.toggle("short-viewport", compactHeight.matches);
    document.body.classList.remove("services-compact");
    const oversized = panels.some((panel) => panel.offsetHeight + stickyTop() > window.innerHeight);
    document.body.classList.toggle("services-compact", oversized);
    film.autoplay = !reduced.matches;
    if (reduced.matches) pauseFilm();
    navigation = null; schedule();
  }
  reduced.addEventListener("change", updatePreference); compactHeight.addEventListener("change", updatePreference);
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", updatePreference, { passive: true });
  document.addEventListener("visibilitychange", () => document.hidden ? pauseFilm() : resumeFilm());
  new IntersectionObserver((entries) => { for (const entry of entries) entry.isIntersecting ? resumeFilm() : pauseFilm(); }, { threshold: .1 }).observe(film);
  for (const event of ["wheel", "touchstart"]) window.addEventListener(event, () => { navigation = null; }, { passive: true });
  const reveals = document.querySelectorAll(".hero-copy > *, .section-heading, .about-grid, .process-grid li, .faq-list details, .closing, .site-footer, .about-art, .studio-showcase");
  const revealObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) if (entry.isIntersecting) { entry.target.classList.add("is-visible"); revealObserver.unobserve(entry.target); }
  }, { threshold: 0.12 });
  reveals.forEach((element) => { element.classList.add("scroll-reveal"); revealObserver.observe(element); });
  const motionObserver = new IntersectionObserver((entries) => { entries.forEach((entry) => entry.target.classList.toggle("in-view", entry.isIntersecting)); });
  motionObserver.observe(story); motionObserver.observe(document.querySelector(".hero"));
  setService(0); updatePreference();
})();
