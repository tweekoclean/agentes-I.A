(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const root = "/v1/atendimento/empresas";
  const pageSize = 50;
  const state = {
    key: "", epoch: 0, pending: new Set(), companies: [], tenant: null, view: "inbox",
    queuePage: 1, queueItems: [], queueFingerprint: "", knowledgePage: 1, knowledge: [],
    conversation: null, conversationId: "", historyPage: 1, historyFingerprint: "",
    editingKnowledge: "", siteKeys: new Map(), drafts: new Map(), polling: false, busy: false,
  };
  let noticeTimer;
  const reasons = {
    precisa_responsavel: "Cliente pediu uma pessoa", sem_resposta_na_base: "Dúvida sem resposta cadastrada",
    avaliacao_responsavel: "Precisa de avaliação", falha_ia: "Não foi possível responder automaticamente",
    mensagem_de_midia: "Cliente enviou mídia", limite_ia_diario: "Limite diário de IA atingido",
    limite_conversa_automatica: "Precisa de acompanhamento", janela_resposta_encerrada: "Janela do WhatsApp encerrada",
    whatsapp_nao_configurado: "WhatsApp aguardando configuração", base_alterada_durante_resposta: "Base atualizada durante o atendimento",
    pausa_operador: "Atendimento assumido", resposta_operador: "Operador na conversa",
  };
  const channelName = (channel) => channel === "whatsapp" ? "WhatsApp" : "Site";
  const stateName = (value) => ({ bot: "Automático", humano: "Com responsável", interrompida: "Interrompida" }[value] || value);
  const date = (value, short = false) => {
    if (!value || Number.isNaN(Date.parse(value))) return "";
    return new Intl.DateTimeFormat("pt-BR", {
      timeZone: "America/Sao_Paulo", ...(short ? {} : { day: "2-digit", month: "2-digit" }),
      hour: "2-digit", minute: "2-digit",
    }).format(new Date(value));
  };
  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }
  function notice(message, error = false) {
    clearTimeout(noticeTimer);
    $("notice").textContent = message;
    $("notice").classList.toggle("error", error);
    $("notice").hidden = false;
    noticeTimer = setTimeout(() => { $("notice").hidden = true; }, error ? 10000 : 6000);
  }
  function inlineError(id, message = "") {
    $(id).textContent = message;
    $(id).hidden = !message;
  }
  function invalidate() {
    state.epoch += 1;
    for (const controller of state.pending) controller.abort();
    state.pending.clear();
  }
  function endSession(message = "") {
    invalidate();
    state.key = "";
    state.companies = [];
    state.tenant = null;
    state.conversation = null;
    state.conversationId = "";
    state.siteKeys.clear();
    state.drafts.clear();
    $("admin-key").value = "";
    $("reply-text").value = "";
    for (const id of ["company-select", "queue-list", "message-list", "knowledge-list"]) $(id).replaceChildren();
    $("integration-code").textContent = "";
    $("integration-code").hidden = true;
    $("test-company").removeAttribute("href");
    $("settings-form").reset();
    for (const dialog of document.querySelectorAll("dialog")) {
      if (dialog.open) dialog.close();
      dialog.querySelector("form")?.reset();
    }
    $("app-screen").hidden = true;
    $("login-screen").hidden = false;
    $("notice").hidden = true;
    inlineError("login-error", message);
  }
  async function api(path, { method = "GET", body } = {}) {
    const controller = new AbortController();
    const epoch = state.epoch;
    const key = state.key;
    if (!key) throw new Error("Entre novamente no painel.");
    state.pending.add(controller);
    const timeout = setTimeout(() => controller.abort("timeout"), 15000);
    try {
      const response = await fetch(path, {
        method, signal: controller.signal, cache: "no-store", credentials: "omit",
        headers: { "X-API-Key": key, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      if (epoch !== state.epoch || key !== state.key) throw new DOMException("Sessão alterada", "AbortError");
      let data;
      try { data = await response.json(); } catch { data = {}; }
      if (response.status === 401) {
        endSession("Chave inválida ou alterada. Confira a ADMIN_API_KEY e entre novamente.");
        throw new DOMException("Sessão encerrada", "AbortError");
      }
      if (!response.ok) {
        const detail = Array.isArray(data.detail) ? data.detail.map((item) => item.msg).join("; ") : data.detail;
        throw new Error(response.status >= 500 ? "O servidor não conseguiu concluir. Tente novamente em instantes." : (detail || "Não foi possível concluir esta ação."));
      }
      if (epoch !== state.epoch) throw new DOMException("Sessão alterada", "AbortError");
      return data;
    } catch (error) {
      if (epoch !== state.epoch) throw new DOMException("Sessão alterada", "AbortError");
      if (controller.signal.reason === "timeout" || error instanceof TypeError) {
        throw new Error(method === "GET" ? "Não foi possível conectar ao servidor. Atualize em instantes." :
          "Não foi possível confirmar a ação. Atualize os dados antes de tentar novamente.");
      }
      throw error;
    } finally {
      clearTimeout(timeout);
      state.pending.delete(controller);
    }
  }
  const guarded = (work) => async (event) => {
    try { await work(event); } catch (error) { if (error.name !== "AbortError") notice(error.message, true); }
  };
  async function formAction(form, errorId, work) {
    const button = form.querySelector('[type="submit"]');
    button.disabled = true;
    state.busy = true;
    if (errorId) inlineError(errorId);
    try { await work(); } catch (error) {
      if (error.name !== "AbortError") {
        if (errorId) inlineError(errorId, error.message); else notice(error.message, true);
      }
    } finally {
      button.disabled = false;
      state.busy = false;
      if (form.id === "reply-form") updateConversationControls();
    }
  }
  function companyPath() { return root + "/" + encodeURIComponent(state.tenant.id); }
  function empty(container, title, text) {
    const element = node("div", "empty");
    element.append(node("span", "empty-symbol", "◌"), node("h2", "", title), node("p", "", text));
    container.replaceChildren(element);
  }
  async function loadCompanies() {
    const companies = [];
    let page = 1;
    while (true) {
      const data = await api(root + "?limite=1000&pagina=" + page);
      companies.push(...data.empresas);
      if (data.empresas.length < 1000) break;
      page += 1;
    }
    state.companies = companies;
    $("company-select").replaceChildren(...companies.map((company) => {
      const option = node("option", "", company.nome + (company.ativa ? "" : " · desativada"));
      option.value = company.id;
      return option;
    }));
    if (state.tenant) {
      state.tenant = companies.find((company) => company.id === state.tenant.id) || null;
      $("company-select").value = state.tenant?.id || "";
    }
  }
  function renderOverview() {
    const tenant = state.tenant;
    $("no-company").hidden = !!tenant;
    $("company-workspace").hidden = !tenant;
    $("company-select").disabled = !state.companies.length;
    $("company-caption").textContent = tenant ? tenant.nome : "SEU ESPAÇO DE ATENDIMENTO";
    if (!tenant) return;
    $("automation-status").textContent = !tenant.ativa ? "Empresa desativada" :
      (tenant.ia_habilitada ? (tenant.ia_configurada ? "IA + base de respostas" : "IA aguardando configuração") : "Base de respostas");
    $("whatsapp-status").textContent = tenant.whatsapp_ativo ? "Conectado" : "Aguardando configuração";
    $("conversation-limit").textContent = tenant.limite_conversas_dia.toLocaleString("pt-BR");
  }
  async function selectCompany(id) {
    invalidate();
    for (const dialog of document.querySelectorAll("dialog[open]")) dialog.close();
    state.tenant = state.companies.find((item) => item.id === id) || null;
    state.queuePage = state.knowledgePage = state.historyPage = 1;
    state.queueItems = [];
    state.knowledge = [];
    state.conversationId = "";
    state.conversation = null;
    state.queueFingerprint = state.historyFingerprint = "";
    $("company-select").value = state.tenant?.id || "";
    $("reply-text").value = "";
    $("conversation-empty").hidden = false;
    $("conversation-content").hidden = true;
    $("queue-list").replaceChildren();
    $("message-list").replaceChildren();
    $("knowledge-list").replaceChildren();
    inlineError("load-error");
    renderOverview();
    await showView(state.view, false);
  }
  async function showView(view, cancel = true) {
    if (cancel) invalidate();
    state.view = view;
    $("view-title").textContent = { inbox: "Atendimento", knowledge: "Base de respostas", settings: "Configuração" }[view];
    for (const element of document.querySelectorAll(".nav-button")) {
      const active = element.dataset.view === view;
      element.classList.toggle("active", active);
      if (active) element.setAttribute("aria-current", "page"); else element.removeAttribute("aria-current");
    }
    for (const name of ["inbox", "knowledge", "settings"]) $("view-" + name).hidden = name !== view;
    inlineError("load-error");
    if (!state.tenant) return;
    try {
      if (view === "inbox") await Promise.all([loadQueue(), state.conversationId ? loadConversation() : Promise.resolve()]);
      else if (view === "knowledge") await loadKnowledge();
      else renderSettings();
    } catch (error) { if (error.name !== "AbortError") inlineError("load-error", error.message); }
  }
  async function loadQueue() {
    const filter = $("queue-filter").value;
    const endpoint = filter === "conversas" ? "/conversas" : "/chamados?status=" + filter;
    const data = await api(companyPath() + endpoint + (filter === "conversas" ? "?" : "&") + "limite=" + pageSize + "&pagina=" + state.queuePage);
    state.queueItems = data[filter === "conversas" ? "conversas" : "chamados"];
    $("queue-count").textContent = state.queueItems.length;
    $("queue-page").textContent = "Página " + state.queuePage;
    $("queue-prev").disabled = state.queuePage === 1;
    $("queue-next").disabled = state.queueItems.length < pageSize;
    $("last-updated").textContent = "Atualizado às " + date(new Date().toISOString(), true);
    const fingerprint = filter + state.queuePage + JSON.stringify(state.queueItems);
    if (fingerprint === state.queueFingerprint) return;
    state.queueFingerprint = fingerprint;
    renderQueue();
  }
  function renderQueue() {
    const container = $("queue-list");
    const all = $("queue-filter").value === "conversas";
    if (!state.queueItems.length) {
      empty(container, all ? "Nenhuma conversa nesta página." : "Nenhum chamado nesta página.",
        "As novas conversas e os pedidos de atendimento aparecerão aqui.");
      return;
    }
    container.replaceChildren(...state.queueItems.map((item) => {
      const id = all ? item.id : item.conversa_id;
      const button = node("button", "queue-item" + (state.conversationId === id ? " selected" : ""));
      button.type = "button";
      button.dataset.conversation = id;
      const badge = node("span", "badge " + (all && item.estado === "bot" ? "green" : "amber"),
        all ? channelName(item.canal) + " · " + stateName(item.estado) : ({ aberto: "Aguardando responsável", resolvido: "Resolvido", interrompido: "Interrompido" }[item.status] || item.status));
      button.append(badge, node("strong", "", all ? (item.contato || "Conversa " + id.slice(0, 8)) : (reasons[item.motivo] || "Pedido de atendimento")));
      if (!all) button.append(node("p", "", item.resumo.replace(/^Motivo: [^.]+\.\s*Última mensagem:\s*/, "")));
      button.append(node("span", "queue-date", date(all ? item.criada_em : item.criado_em)));
      button.addEventListener("click", guarded(() => selectConversation(id)));
      return button;
    }));
  }
  async function selectConversation(id) {
    invalidate();
    state.conversationId = id;
    state.conversation = null;
    state.historyPage = 1;
    state.historyFingerprint = "";
    $("reply-text").value = state.drafts.get(state.tenant.id + "/" + id) || "";
    $("conversation-title").textContent = "Carregando conversa…";
    $("conversation-meta").textContent = "";
    $("conversation-state").textContent = "";
    $("message-list").replaceChildren();
    $("conversation-empty").hidden = true;
    $("conversation-content").hidden = false;
    updateConversationControls();
    for (const button of $("queue-list").querySelectorAll("button")) button.classList.toggle("selected", button.dataset.conversation === id);
    await loadConversation();
  }
  async function loadConversation() {
    const id = state.conversationId;
    if (!id) return;
    const data = await api(companyPath() + "/conversas/" + encodeURIComponent(id) + "?limite=100&pagina=" + state.historyPage);
    if (state.conversationId !== id) return;
    state.conversation = data.conversa;
    $("conversation-title").textContent = data.conversa.contato || "Conversa " + id.slice(0, 8);
    $("conversation-meta").textContent = channelName(data.conversa.canal) + " · " + date(data.conversa.criada_em);
    $("conversation-state").textContent = stateName(data.conversa.estado);
    $("conversation-state").className = "badge " + ({ bot: "green", humano: "amber", interrompida: "gray" }[data.conversa.estado] || "gray");
    $("history-page").textContent = state.historyPage === 1 ? "Até 100 mensagens recentes" : "Histórico · página " + state.historyPage;
    $("history-older").disabled = data.mensagens.length < 100;
    $("history-newer").disabled = state.historyPage === 1;
    updateConversationControls();
    const fingerprint = id + state.historyPage + JSON.stringify(data.mensagens);
    if (fingerprint === state.historyFingerprint) return;
    const container = $("message-list");
    const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 70;
    const firstLoad = !state.historyFingerprint;
    state.historyFingerprint = fingerprint;
    container.replaceChildren(...data.mensagens.map((message) => {
      const outgoing = message.direcao === "saida";
      const wrapper = node("article", "message" + (outgoing ? " outbound" : ""));
      const author = { visitante: "Cliente", cliente: "Cliente", humano: "Responsável", assistente: "Assistente", sistema: "AtendeAI" }[message.autor] || "Cliente";
      const label = node("div", "message-label");
      label.append(node("strong", "", author), node("time", "", date(message.criada_em, true)));
      wrapper.append(label, node("p", "message-text", message.texto));
      if (outgoing && data.conversa.canal === "whatsapp") {
        const statuses = { na_fila: "Na fila", enviando: "Confirmando envio", aceita: "Aceita pelo WhatsApp", disponivel: "Disponível", cancelada: "Cancelada", falhou: "Falha no envio", incerta: "Envio sem confirmação", bloqueada: "Envio bloqueado" };
        const deliveries = { delivered: "Entregue", read: "Lida", failed: "Falha de entrega", sent: "Enviada" };
        wrapper.append(node("p", "message-status", deliveries[message.entrega] || statuses[message.status] || message.status));
      }
      return wrapper;
    }));
    if (firstLoad || atBottom) container.scrollTop = container.scrollHeight;
  }
  function updateConversationControls() {
    const conversation = state.conversation;
    const blocked = !conversation || !state.tenant?.ativa || conversation.estado === "interrompida";
    $("reply-text").disabled = blocked;
    $("reply-submit").disabled = blocked || state.busy;
    $("take-over").disabled = blocked || conversation?.estado === "humano" || state.busy;
    $("resume-bot").disabled = blocked || conversation?.estado !== "humano" || state.busy;
    $("reply-help").textContent = blocked ? "Esta conversa não está disponível para resposta." :
      (conversation.canal === "whatsapp" ? "A resposta entra na fila do WhatsApp dentro da janela de atendimento." : "Ao responder, o atendimento automático fica pausado.");
  }
  async function changePause(paused) {
    const id = state.conversationId;
    if (!id || state.busy) return;
    state.busy = true;
    updateConversationControls();
    try {
      await api(companyPath() + "/conversas/" + encodeURIComponent(id) + "/pausa", { method: "POST", body: { pausado: paused } });
      await Promise.all([loadConversation(), loadQueue()]);
      notice(paused ? "Atendimento assumido. As respostas automáticas estão pausadas." : "Chamado concluído e atendimento automático retomado.");
    } finally { state.busy = false; updateConversationControls(); }
  }
  async function loadKnowledge() {
    const data = await api(companyPath() + "/base?limite=" + pageSize + "&pagina=" + state.knowledgePage);
    state.knowledge = data.base;
    $("knowledge-page").textContent = "Página " + state.knowledgePage;
    $("knowledge-prev").disabled = state.knowledgePage === 1;
    $("knowledge-next").disabled = data.base.length < pageSize;
    const container = $("knowledge-list");
    if (!data.base.length) { empty(container, "O que seus clientes precisam saber?", "Cadastre horários, serviços e outras respostas da empresa."); return; }
    container.replaceChildren(...data.base.map((item) => {
      const card = node("article", "card knowledge-card");
      const heading = node("div", "card-heading");
      heading.append(node("h2", "", item.titulo), node("span", "badge " + (item.ativa ? "green" : "gray"), item.ativa ? "Ativa" : "Desativada"));
      const actions = node("div", "knowledge-actions");
      const edit = node("button", "button secondary", "Editar resposta");
      edit.type = "button";
      edit.addEventListener("click", () => openKnowledge(item));
      const toggle = node("button", "button quiet", item.ativa ? "Desativar" : "Ativar");
      toggle.type = "button";
      toggle.addEventListener("click", guarded(async () => {
        toggle.disabled = true;
        try {
          await api(companyPath() + "/base/" + encodeURIComponent(item.id), { method: "PUT", body: { titulo: item.titulo, conteudo: item.conteudo, ativa: !item.ativa } });
          await loadKnowledge();
        } finally { toggle.disabled = false; }
      }));
      actions.append(edit, toggle);
      card.append(heading, node("p", "knowledge-text", item.conteudo), actions);
      return card;
    }));
  }
  function openKnowledge(item) {
    state.editingKnowledge = item?.id || "";
    $("knowledge-form-title").textContent = item ? "Editar resposta" : "Nova resposta";
    $("knowledge-title").value = item?.titulo || "";
    $("knowledge-text").value = item?.conteudo || "";
    $("knowledge-active").checked = item ? item.ativa : true;
    inlineError("knowledge-form-error");
    $("knowledge-dialog").showModal();
  }
  function renderSettings() {
    const tenant = state.tenant;
    $("settings-welcome").value = tenant.boas_vindas;
    $("settings-origins").value = tenant.origens_permitidas.join("\n");
    $("settings-conversations").value = tenant.limite_conversas_dia;
    $("settings-ai-limit").value = tenant.limite_ia_dia;
    $("settings-active").checked = tenant.ativa;
    $("settings-ai").checked = tenant.ia_habilitada;
    $("ai-help").textContent = tenant.ia_configurada ? "Ao ativar, as chamadas de IA podem gerar cobrança no provedor. O limite diário é aplicado por empresa." :
      "Configure OPENAI_API_KEY nas variáveis de ambiente para usar IA. Enquanto isso, o atendimento usa respostas cadastradas e encaminha dúvidas para uma pessoa.";
    $("whatsapp-help").textContent = tenant.whatsapp_ativo ? "A conta desta empresa está configurada e habilitada para suporte." : "A conta desta empresa ainda precisa ser configurada e habilitada na API oficial da Meta.";
    $("tenant-reference").value = tenant.id;
    renderIntegration();
  }
  function renderIntegration() {
    const tenant = state.tenant;
    const key = state.siteKeys.get(tenant.id);
    $("integration-code").hidden = !key;
    $("copy-integration").hidden = !key;
    $("test-company").hidden = !key || !tenant.origens_permitidas.includes(window.location.origin);
    $("integration-help").textContent = key ? "Guarde o código: a chave do site só aparece ao cadastrar ou substituir. Ela identifica este chat e não dá acesso ao painel." :
      "A chave original não pode ser recuperada. Use o código que você guardou ou substitua a chave para gerar um novo código.";
    $("integration-code").textContent = key ? '<script src="' + window.location.origin + '/widget/atendeai.js"\n  data-empresa="' + tenant.id + '"\n  data-chave="' + key + '" defer></script>' : "";
    if (key) $("test-company").href = "/teste-atendimento?" + new URLSearchParams({ empresa: tenant.id, chave: key });
    else $("test-company").removeAttribute("href");
  }
  const parseOrigins = (text) => [...new Set(text.split(/[\n,]+/).map((value) => value.trim()).filter(Boolean))];
  function openCompany() {
    $("company-form").reset();
    inlineError("company-form-error");
    $("company-dialog").showModal();
  }

  $("login-form").addEventListener("submit", (event) => {
    event.preventDefault();
    formAction(event.currentTarget, "login-error", async () => {
      invalidate();
      state.key = $("admin-key").value.trim();
      $("admin-key").value = "";
      await loadCompanies();
      $("login-screen").hidden = true;
      $("app-screen").hidden = false;
      state.view = "inbox";
      await selectCompany(state.companies.find((company) => company.id === "00000000-0000-4000-a000-000000000003")?.id || state.companies[0]?.id);
    });
  });
  $("logout").addEventListener("click", () => { endSession(); $("admin-key").focus(); });
  $("company-select").addEventListener("change", guarded((event) => selectCompany(event.target.value)));
  for (const button of document.querySelectorAll(".nav-button")) button.addEventListener("click", guarded(() => showView(button.dataset.view)));
  $("refresh").addEventListener("click", guarded(async () => {
    await loadCompanies(); renderOverview(); await showView(state.view);
  }));
  $("create-company").addEventListener("click", openCompany);
  $("create-first-company").addEventListener("click", openCompany);
  for (const button of document.querySelectorAll(".close-dialog")) button.addEventListener("click", () => button.closest("dialog").close());
  $("company-form").addEventListener("submit", (event) => {
    event.preventDefault();
    formAction(event.currentTarget, "company-form-error", async () => {
      const origins = parseOrigins($("new-origins").value);
      if ($("new-allow-test").checked && !origins.includes(window.location.origin)) origins.push(window.location.origin);
      const company = await api(root, { method: "POST", body: { nome: $("new-name").value.trim(), origens_permitidas: origins, boas_vindas: $("new-welcome").value.trim() } });
      state.siteKeys.set(company.id, company.chave_site);
      $("company-dialog").close();
      await loadCompanies();
      state.view = "settings";
      await selectCompany(company.id);
      notice("Empresa cadastrada. Guarde o código de integração do chat.");
    });
  });
  $("queue-filter").addEventListener("change", guarded(async () => { invalidate(); state.queuePage = 1; state.queueFingerprint = ""; await loadQueue(); }));
  for (const [id, change] of [["queue-prev", -1], ["queue-next", 1]]) $(id).addEventListener("click", guarded(async () => { invalidate(); state.queuePage = Math.max(1, state.queuePage + change); await loadQueue(); }));
  for (const [id, change] of [["history-older", 1], ["history-newer", -1]]) $(id).addEventListener("click", guarded(async () => { invalidate(); state.historyPage = Math.max(1, state.historyPage + change); state.historyFingerprint = ""; await loadConversation(); }));
  $("take-over").addEventListener("click", guarded(() => changePause(true)));
  $("resume-bot").addEventListener("click", guarded(() => changePause(false)));
  $("reply-text").addEventListener("input", () => {
    if (state.tenant && state.conversationId) state.drafts.set(state.tenant.id + "/" + state.conversationId, $("reply-text").value);
  });
  $("reply-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state.conversation || state.busy) return;
    formAction(event.currentTarget, null, async () => {
      const tenantId = state.tenant.id;
      const id = state.conversationId;
      const message = await api(companyPath() + "/conversas/" + encodeURIComponent(id) + "/responder", { method: "POST", body: { texto: $("reply-text").value.trim() } });
      state.drafts.delete(tenantId + "/" + id);
      $("reply-text").value = "";
      state.historyPage = 1;
      await Promise.all([loadConversation(), loadQueue()]);
      notice(message.status === "na_fila" ? "Resposta colocada na fila do WhatsApp." : "Resposta registrada na conversa do cliente.");
    });
  });
  $("add-knowledge").addEventListener("click", () => openKnowledge());
  for (const [id, change] of [["knowledge-prev", -1], ["knowledge-next", 1]]) $(id).addEventListener("click", guarded(async () => { invalidate(); state.knowledgePage = Math.max(1, state.knowledgePage + change); await loadKnowledge(); }));
  $("knowledge-form").addEventListener("submit", (event) => {
    event.preventDefault();
    formAction(event.currentTarget, "knowledge-form-error", async () => {
      const item = state.editingKnowledge;
      await api(companyPath() + "/base" + (item ? "/" + encodeURIComponent(item) : ""), { method: item ? "PUT" : "POST", body: {
        titulo: $("knowledge-title").value.trim(), conteudo: $("knowledge-text").value.trim(), ativa: $("knowledge-active").checked,
      } });
      $("knowledge-dialog").close();
      if (!item) state.knowledgePage = 1;
      await loadKnowledge();
      notice("Resposta salva na base da empresa.");
    });
  });
  $("settings-form").addEventListener("submit", (event) => {
    event.preventDefault();
    formAction(event.currentTarget, null, async () => {
      const tenant = await api(companyPath(), { method: "PATCH", body: {
        boas_vindas: $("settings-welcome").value.trim(), origens_permitidas: parseOrigins($("settings-origins").value),
        limite_conversas_dia: Number($("settings-conversations").value), limite_ia_dia: Number($("settings-ai-limit").value),
        ativa: $("settings-active").checked, ia_habilitada: $("settings-ai").checked,
      } });
      state.tenant = tenant;
      state.companies = state.companies.map((item) => item.id === tenant.id ? tenant : item);
      $("company-select").selectedOptions[0].textContent = tenant.nome + (tenant.ativa ? "" : " · desativada");
      renderOverview(); renderSettings();
      notice("Preferências salvas.");
    });
  });
  $("copy-integration").addEventListener("click", guarded(async () => {
    if (!navigator.clipboard) { notice("Selecione e copie o código mostrado acima."); return; }
    await navigator.clipboard.writeText($("integration-code").textContent);
    notice("Código copiado.");
  }));
  $("rotate-site-key").addEventListener("click", () => $("rotate-dialog").showModal());
  $("confirm-rotate").addEventListener("click", guarded(async () => {
    const button = $("confirm-rotate");
    button.disabled = true;
    try {
      const data = await api(companyPath() + "/chave-site", { method: "POST" });
      state.siteKeys.set(data.empresa_id, data.chave_site);
      $("rotate-dialog").close();
      renderIntegration();
      notice("Nova chave gerada. Atualize o código incorporado nos sites da empresa.");
    } finally { button.disabled = false; }
  }));
  let pollCount = 0;
  setInterval(async () => {
    if (!state.key || !state.tenant || state.view !== "inbox" || state.polling || state.busy || document.hidden) return;
    state.polling = true;
    try {
      const work = [];
      if (state.conversationId && state.historyPage === 1) work.push(loadConversation());
      if (++pollCount % 3 === 0) work.push(loadQueue());
      await Promise.all(work);
      inlineError("load-error");
    } catch (error) { if (error.name !== "AbortError") inlineError("load-error", error.message); }
    finally { state.polling = false; }
  }, 5000);
  window.addEventListener("pagehide", () => endSession());
})();
