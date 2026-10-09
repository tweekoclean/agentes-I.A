(() => {
  "use strict";
  const instances = new WeakMap();
  function mount(root, options = {}) {
  if (instances.has(root)) return instances.get(root);
  const $ = (id) => root.querySelector("#" + id);
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const running = new Set();
  reduced.addEventListener("change", () => { if (reduced.matches) for (const animation of running) animation.cancel(); });
  function animate(element, frames, options = {}) {
    if (!reduced.matches && element?.animate) {
      const animation = element.animate(frames, { duration: 350, easing: "cubic-bezier(.2,.8,.2,1)", ...options });
      running.add(animation);
      animation.finished.catch(() => {}).finally(() => running.delete(animation));
      return animation;
    }
  }
  root.addEventListener("invalid", event => {
    animate(event.target, [{ translate: "0" }, { translate: "-4px" }, { translate: "4px" }, { translate: "-2px" }, { translate: "0" }], { duration: 280 });
  }, true);
  const services = { atendimento_ia: "Atendimento com IA", criacao_site: "Criação de site", sistema: "Sistema sob medida", reformulacao_site: "Reformulação de site" };
  const selectedServices = () => Object.keys(services).filter((id) => $("apply-service-" + id).checked);
  const channels = () => $("apply-support-fields").disabled ? [] : [$("apply-whatsapp").checked ? "whatsapp" : "", $("apply-site").checked ? "site" : ""].filter(Boolean);
  function updateServices() {
    const selected = selectedServices();
    $("apply-support-fields").hidden = $("apply-support-fields").disabled = !selected.includes("atendimento_ia");
    $("apply-website").required = selected.includes("reformulacao_site");
    $("apply-website-label").textContent = $("apply-website").required ? "Endereço do site que deseja reformular" : "Site atual (opcional)";
  }
  for (const id of Object.keys(services)) $("apply-service-" + id).addEventListener("change", updateServices);
  let requested = options.service || new URLSearchParams(location.search).get("servico");
  if (Object.hasOwn(services, requested)) $("apply-service-" + requested).checked = true;
  updateServices();
  let step = 1, submitting = false, completed = false;
  let submissionId = crypto.randomUUID();
  function error(message = "") {
    $("public-error").textContent = message; $("public-error").hidden = !message;
    if (message) animate($("public-error"), [{ opacity: 0, translate: "0 8px" }, { opacity: 1, translate: "0" }]);
  }
  function validate(number) {
    const section = $("application-step-" + number);
    for (const input of section.querySelectorAll("input,select,textarea")) if (!input.reportValidity()) return false;
    if (number === 1 && !/^(?:55)?\d{10,11}$/.test($("apply-phone").value.replace(/\D/g, ""))) { error("Informe um telefone brasileiro com DDD."); $("apply-phone").focus(); return false; }
    if (number === 2 && !selectedServices().length) { error("Selecione pelo menos uma solução para seu projeto."); $("apply-service-atendimento_ia").focus(); return false; }
    if (number === 2 && selectedServices().includes("atendimento_ia") && !channels().length) { error("Selecione pelo menos um canal de atendimento."); $("apply-whatsapp").focus(); return false; }
    return true;
  }
  function showStep(number) {
    const direction = number >= step ? 1 : -1;
    step = number; error();
    for (let i = 1; i <= 3; i++) {
      $("application-step-" + i).hidden = i !== step;
      const item = $("application-steps").children[i - 1];
      item.classList.toggle("current", i === step); item.classList.toggle("done", i < step);
      if (i === step) item.setAttribute("aria-current", "step"); else item.removeAttribute("aria-current");
    }
    $("application-back").hidden = step === 1;
    $("application-next").hidden = step === 3; $("application-submit").hidden = step !== 3;
    $("application-step-label").textContent = "Passo " + step + " de 3";
    $("application-steps").style.setProperty("--step-progress", ((step - 1) / 2) * 100 + "%");
    if (step === 3) {
      const values = [["Empresa", $("apply-company").value.trim()], ["Cidade / segmento", $("apply-city").value.trim() + " / " + $("apply-state").value + " · " + $("apply-segment").selectedOptions[0].textContent], ["Contato", $("apply-contact").value.trim() + " · " + $("apply-phone").value], ["Soluções", selectedServices().map((id) => services[id]).join(" · ")], ["Necessidade", $("apply-goal").value.trim()]];
      if ($("apply-website").value.trim()) values.push(["Site atual", $("apply-website").value.trim()]);
      if (selectedServices().includes("atendimento_ia")) values.push(["Canais de atendimento", channels().map((id) => id === "whatsapp" ? "WhatsApp" : "Chat do site").join(" e ")], ["Conversas por dia", $("apply-volume").selectedOptions[0].textContent]);
      $("public-summary").replaceChildren(...values.map(([label, text]) => { const item = document.createElement("div"); item.className = "detail-item"; const title = document.createElement("span"); title.textContent = label; const content = document.createElement("p"); content.textContent = text; item.append(title, content); return item; }));
    }
    const section = $("application-step-" + number);
    animate(section, [{ opacity: 0, translate: direction * 26 + "px 0" }, { opacity: 1, translate: "0" }], { duration: 400 });
    if (number === 3) { section.querySelector("h3").tabIndex = -1; section.querySelector("h3").focus(); }
    else section.querySelector("input,select,textarea")?.focus();
    root.closest?.("dialog")?.querySelector(".modal-body")?.scrollTo({ top: 0, behavior: "auto" });
  }
  $("application-next").addEventListener("click", () => { error(); if (validate(step)) showStep(step + 1); });
  $("application-back").addEventListener("click", () => { if (!submitting) showStep(step - 1); });
  // Campos de etapas ocultas são validados explicitamente antes do envio.
  $("public-application-form").noValidate = true;
  $("public-application-form").addEventListener("submit", async (event) => {
    event.preventDefault(); if (submitting) return;
    if (step !== 3) { if (validate(step)) showStep(step + 1); return; }
    for (let number = 1; number <= 3; number++) { if (!validate(number)) { showStep(number); validate(number); return; } }
    submitting = true; $("application-submit").disabled = $("application-back").disabled = true;
    $("public-application-form").classList.add("is-submitting");
    $("application-submit").textContent = "Enviando…"; error();
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch("/publico/aplicacoes", { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "omit", cache: "no-store", signal: controller.signal,
        body: JSON.stringify({ id_envio: submissionId, nome_empresa: $("apply-company").value.trim(), cidade: $("apply-city").value.trim(), uf: $("apply-state").value, servicos: selectedServices(), site_atual: $("apply-website").value.trim(), segmento: $("apply-segment").value, nome_contato: $("apply-contact").value.trim(), whatsapp: $("apply-phone").value, canais: channels(), volume: $("apply-volume").value, objetivo: $("apply-goal").value.trim(), autoriza_contato: $("apply-consent").checked, site_extra: $("apply-extra").value }) });
      const data = await response.json(); if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Confira os campos e tente novamente.");
      $("public-protocol").textContent = "Protocolo: " + data.protocolo;
      $("public-application-form").hidden = $("application-steps").hidden = $("application-intro").hidden = true;
      $("public-success").hidden = false; completed = true;
      animate($("public-success"), [{ opacity: 0, scale: .94, translate: "0 20px" }, { opacity: 1, scale: 1, translate: "0" }], { duration: 500 });
      $("application-new-request").focus();
    } catch (failure) { error(failure.name === "AbortError" || failure instanceof TypeError ? "Não conseguimos confirmar o recebimento. Tente enviar novamente nesta página; sua solicitação não será duplicada." : failure.message); }
    finally { clearTimeout(timer); submitting = false; $("public-application-form").classList.remove("is-submitting"); $("application-submit").disabled = $("application-back").disabled = false; $("application-submit").textContent = "Enviar solicitação →"; }
  });
  async function loadCatalog() {
    try {
      const response = await fetch("/publico/aplicacoes/catalogo", { cache: "no-store", credentials: "omit" });
      if (!response.ok) throw new Error(); const data = await response.json();
      for (const state of data.estados) { const option = document.createElement("option"); option.value = option.textContent = state; $("apply-state").append(option); }
      for (const segment of data.segmentos) { const option = document.createElement("option"); option.value = segment.id; option.textContent = segment.nome; $("apply-segment").append(option); }
      $("application-next").disabled = false;
    } catch { error("Não foi possível carregar o formulário. Atualize a página para tentar novamente."); }
  }
  $("application-new-request").addEventListener("click", () => {
    if (submitting) return;
    $("public-application-form").reset();
    completed = false; submissionId = crypto.randomUUID();
    if (Object.hasOwn(services, requested)) $("apply-service-" + requested).checked = true;
    updateServices();
    $("public-application-form").hidden = $("application-steps").hidden = $("application-intro").hidden = false;
    $("public-success").hidden = true;
    showStep(1);
  });
  const instance = {
    selectService(service) {
      if (submitting || !Object.hasOwn(services, service)) return;
      requested = service;
      if (completed) return;
      $("apply-service-" + service).checked = true; updateServices();
      if (step === 3) showStep(2);
    },
    focus() { (completed ? $("application-new-request") : $("application-step-" + step).querySelector("input,select,textarea"))?.focus(); },
  };
  instances.set(root, instance);
  loadCatalog();
  return instance;
  }
  window.NelvoApplication = { mount };
  if (document.getElementById("public-application-form")) mount(document);
})();
