(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const root = "/v1/atendimento/empresas";
  const pageSize = 50;
  const state = {
    key: "", epoch: 0, pending: new Set(), companies: [], tenant: null, ai: null, view: "dashboard",
    queuePage: 1, queueItems: [], queueFingerprint: "", knowledgePage: 1, knowledge: [],
    conversation: null, conversationId: "", historyPage: 1, historyFingerprint: "",
    editingKnowledge: "", siteKeys: new Map(), drafts: new Map(), polling: false, busy: false,
    catalog: null, leadsPage: 1, funnelPage: 1, commercialPage: 1, salesPage: 1,
    application: null, conversion: null, lead: null, sales: null, salesHistoryPage: 1,
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
    state.ai = null;
    state.conversation = null;
    state.conversationId = "";
    state.siteKeys.clear();
    state.drafts.clear();
    state.application = state.conversion = state.lead = state.sales = null;
    state.leadsPage = state.funnelPage = state.commercialPage = state.salesPage = 1;
    $("funnel-filter").reset();
    $("admin-key").value = "";
    $("reply-text").value = "";
    for (const id of ["company-select", "queue-list", "message-list", "knowledge-list", "lead-list", "funnel-board", "commercial-messages", "commercial-conversations", "dashboard-metrics", "dashboard-stages", "dashboard-checklist", "application-details", "lead-details", "sales-history", "commercial-status"]) $(id).replaceChildren();
    $("integration-code").textContent = "";
    $("integration-code").hidden = true;
    $("test-company").removeAttribute("href");
    $("settings-form").reset();
    for (const dialog of document.querySelectorAll("dialog")) {
      if (dialog.open) dialog.close();
      for (const form of dialog.querySelectorAll("form")) form.reset();
    }
    for (const id of ["application-name", "application-origin", "lead-name", "sales-title", "sales-help", "conversation-title", "conversation-meta", "company-caption"]) $(id).textContent = "";
    $("app-screen").hidden = true;
    $("login-screen").hidden = false;
    $("notice").hidden = true;
    inlineError("login-error", message);
  }
  async function api(path, { method = "GET", body, timeoutMs = 15000 } = {}) {
    const controller = new AbortController();
    const epoch = state.epoch;
    const key = state.key;
    if (!key) throw new Error("Entre novamente no painel.");
    state.pending.add(controller);
    const timeout = setTimeout(() => controller.abort("timeout"), timeoutMs);
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
    state.ai = await api("/v1/ia/status");
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
    const internal = ["dashboard", "research", "funnel", "commercial"].includes(state.view);
    $("nelvo-workspace").hidden = !internal;
    $("no-company").hidden = internal || !!tenant;
    $("company-workspace").hidden = internal || !tenant;
    $("company-select").disabled = !state.companies.length;
    $("company-caption").textContent = internal ? "NELVO COMPANY · OPERAÇÃO COMERCIAL" : (tenant ? "CLIENTE · " + tenant.nome : "ATENDIMENTO DAS EMPRESAS CLIENTES");
    if (!tenant) return;
    $("automation-status").textContent = !tenant.ativa ? "Empresa desativada" :
      (tenant.ia_habilitada ? (state.ai?.pronta ? "IA local ativa" : "IA local aguardando configuração") : "Respostas cadastradas");
    $("whatsapp-status").textContent = tenant.whatsapp_ativo ? "Configurado" : "Aguardando configuração";
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
    await showView(["dashboard", "research", "funnel", "commercial"].includes(state.view) ? "inbox" : state.view, false);
  }
  async function showView(view, cancel = true) {
    if (cancel) invalidate();
    state.view = view;
    $("view-title").textContent = { dashboard: "Visão geral", research: "Buscar empresas", funnel: "Funil de aplicação", commercial: "Comercial WhatsApp", inbox: "Atendimentos dos clientes", knowledge: "Base de respostas", settings: "Configuração do cliente" }[view];
    for (const element of document.querySelectorAll(".nav-button")) {
      const active = element.dataset.view === view;
      element.classList.toggle("active", active);
      if (active) element.setAttribute("aria-current", "page"); else element.removeAttribute("aria-current");
    }
    for (const name of ["dashboard", "research", "funnel", "commercial", "inbox", "knowledge", "settings"]) $("view-" + name).hidden = name !== view;
    renderOverview();
    inlineError("load-error");
    try {
      if (view === "dashboard") { await loadDashboard(); return; }
      if (view === "research") { await loadCatalog(); await loadLeads(); return; }
      if (view === "funnel") { await loadFunnel(); return; }
      if (view === "commercial") { await loadCommercial(); return; }
      if (!state.tenant) return;
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
    const states = { desabilitada: "IA local desabilitada", indisponivel: "Servidor de IA indisponível", modelo_pendente: "Modelo ainda não baixado" };
    const startup = { aguardando_inicio: "Preparando IA local", baixando_runtime: "Baixando o motor da IA", instalando_runtime: "Instalando o motor da IA", iniciando_runtime: "Iniciando o motor da IA", baixando_modelo: "Baixando o modelo", memoria_insuficiente: "Aumente a memória da aplicação", falha_inicializacao: "Confira os logs da hospedagem", runtime_encerrado: "Reinicie a aplicação e confira os recursos" };
    $("ai-help").textContent = state.ai?.pronta ? "Modelo local pronto: " + state.ai.modelo + ". Ele elabora respostas com as informações da empresa e o histórico, sem cobrança por tokens. O limite diário controla o uso do servidor." :
      (startup[state.ai?.inicializacao] || states[state.ai?.estado] || "Verifique a configuração da IA local") + ". Atualize o painel para conferir. Ative o uso de IA nesta empresa depois que o modelo estiver pronto.";
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
  function openCompany(application = null) {
    state.conversion = application;
    $("company-form").reset();
    if (application) $("new-name").value = application.nome_empresa;
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
      state.tenant = state.companies.find((company) => company.id === "00000000-0000-4000-a000-000000000003") || state.companies[0] || null;
      $("company-select").value = state.tenant?.id || "";
      await showView("dashboard", false);
    });
  });
  $("logout").addEventListener("click", () => { endSession(); $("admin-key").focus(); });
  $("mobile-menu-toggle").addEventListener("click", () => {
    const closed = document.querySelector(".sidebar").classList.toggle("menu-closed");
    $("mobile-menu-toggle").setAttribute("aria-expanded", String(!closed));
    $("mobile-menu-toggle").setAttribute("aria-label", closed ? "Expandir menu" : "Recolher menu");
  });
  $("company-select").addEventListener("change", guarded((event) => selectCompany(event.target.value)));
  for (const button of document.querySelectorAll(".nav-button")) button.addEventListener("click", guarded(() => showView(button.dataset.view)));
  $("refresh").addEventListener("click", guarded(async () => {
    await loadCompanies(); renderOverview(); await showView(state.view);
  }));
  $("create-company").addEventListener("click", () => openCompany());
  $("create-first-company").addEventListener("click", () => openCompany());
  for (const button of document.querySelectorAll(".close-dialog")) button.addEventListener("click", () => button.closest("dialog").close());
  $("company-form").addEventListener("submit", (event) => {
    event.preventDefault();
    formAction(event.currentTarget, "company-form-error", async () => {
      const origins = parseOrigins($("new-origins").value);
      if ($("new-allow-test").checked && !origins.includes(window.location.origin)) origins.push(window.location.origin);
      const result = await api(state.conversion ? "/v1/funil/" + state.conversion.id + "/cliente" : root, { method: "POST", body: { nome: $("new-name").value.trim(), origens_permitidas: origins, boas_vindas: $("new-welcome").value.trim() } });
      const company = result.empresa || result;
      if (company.chave_site) state.siteKeys.set(company.id, company.chave_site);
      state.conversion = null;
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
  const stages = { nova: "Novas", qualificacao: "Qualificação", demonstracao: "Demonstração", proposta: "Proposta", ganha: "Contratadas", perdida: "Arquivadas" };
  const volumes = { ate_30: "Até 30 conversas/dia", "31_100": "31 a 100 conversas/dia", "101_300": "101 a 300 conversas/dia", mais_300: "Mais de 300 conversas/dia", nao_sei: "Ainda não sabe", nao_informado: "Não informado" };
  const messageStatus = { rascunho: "Rascunho", aprovada: "Aprovada", descartada: "Descartada", na_fila: "Na fila", processando: "Processando", aceita: "Aceita pela Meta", envio_incerto: "Envio sem confirmação", falhou: "Falha", bloqueada: "Bloqueada", cancelada: "Cancelada", recebida: "Recebida", processada: "Processada" };
  function action(text, work, className = "secondary") {
    const button = node("button", "button " + className, text);
    button.type = "button";
    button.addEventListener("click", guarded(async () => {
      button.disabled = true;
      try { await work(); } finally { button.disabled = false; }
    }));
    return button;
  }
  function details(container, entries) {
    container.replaceChildren(...entries.map(([label, value]) => {
      const item = node("div", "detail-item");
      item.append(node("span", "", label), node("p", "", value || "Não informado"));
      return item;
    }));
  }
  function pager(prefix, page, count, total = null) {
    $(prefix + "-prev").disabled = page === 1;
    $(prefix + "-next").disabled = total === null ? count < pageSize : page * pageSize >= total;
    $(prefix + "-page").textContent = "Página " + page + (total === null ? "" : " · " + total + " registros");
  }
  async function loadDashboard() {
    const [summary, commercial] = await Promise.all([api("/v1/funil/resumo"), api("/v1/comercial/status")]);
    const open = summary.etapas.filter((stage) => !["ganha", "perdida"].includes(stage.id)).reduce((sum, item) => sum + item.quantidade, 0);
    $("dashboard-metrics").replaceChildren(...[
      ["EMPRESAS ENCONTRADAS", summary.empresas_encontradas, "Empresas reais salvas pela pesquisa"],
      ["OPORTUNIDADES ATIVAS", open, "Aplicações em acompanhamento"],
      ["EMPRESAS CLIENTES", summary.clientes, "Espaços de atendimento cadastrados"],
      ["ABORDAGENS NA FILA", commercial.mensagens_na_fila, "Mensagens aguardando processamento"],
    ].map(([label, value, caption]) => {
      const card = node("article", "card metric");
      card.append(node("small", "", label), node("strong", "", value.toLocaleString("pt-BR")), node("p", "", caption));
      return card;
    }));
    const max = Math.max(1, ...summary.etapas.map((stage) => stage.quantidade));
    $("dashboard-stages").replaceChildren(...summary.etapas.map((stage) => {
      const row = node("div", "stage-row");
      const progress = node("progress");
      progress.max = max; progress.value = stage.quantidade;
      progress.setAttribute("aria-label", stage.nome + ": " + stage.quantidade);
      row.append(node("span", "", stage.nome), progress, node("strong", "", stage.quantidade));
      return row;
    }));
    $("dashboard-checklist").replaceChildren(...[
      [true, "Pesquisa e aplicações", "Busque empresas ou compartilhe o formulário público."],
      [commercial.envio_ativo, "WhatsApp comercial da Nelvo", commercial.envio_ativo ? "Envio habilitado. A entrega depende da Meta e da autorização da empresa." : "Aguardando número e configuração da conta comercial da Nelvo."],
      [Boolean(state.ai?.pronta), "IA de atendimento dos clientes", state.ai?.pronta ? "Modelo local pronto. Ative por empresa após cadastrar suas informações." : "Confira a inicialização do modelo nas configurações dos clientes."],
    ].map(([ready, title, text]) => {
      const row = node("div", "check-item"); const copy = node("div");
      copy.append(node("strong", "", title), node("p", "", text));
      row.append(node("span", "badge " + (ready ? "green" : "amber"), ready ? "✓" : "○"), copy); return row;
    }));
  }
  async function loadCatalog() {
    if (state.catalog) return;
    const [cities, segments] = await Promise.all([api("/v1/cidades"), api("/v1/segmentos")]);
    state.catalog = { cidades: cities.cidades.map((city) => city.nome), segmentos: segments.segmentos.map((segment) => ({ id: segment.id, nome: segment.descricao })) };
    $("search-city").replaceChildren(...state.catalog.cidades.map((city) => { const option = node("option", "", city); option.value = city; return option; }));
    $("search-city").value = "Campinas";
    $("search-segment").replaceChildren(...state.catalog.segmentos.map((segment) => { const option = node("option", "", segment.nome); option.value = segment.id; return option; }));
  }
  async function loadLeads() {
    const params = new URLSearchParams({ cidade: $("search-city").value, segmento: $("search-segment").value, limite: pageSize, pagina: state.leadsPage });
    const data = await api("/v1/empresas?" + params);
    pager("leads", state.leadsPage, data.empresas.length, data.total);
    if (!data.empresas.length) { empty($("lead-list"), "Nenhuma empresa encontrada ainda.", "Pesquise uma cidade e segmento para preencher sua lista."); return; }
    $("lead-list").replaceChildren(...data.empresas.map((lead) => {
      const row = node("article", "card lead-row"); const info = node("div", "lead-info");
      info.append(node("h3", "", lead.nome), node("p", "", lead.cidade + " · " + (state.catalog?.segmentos.find((s) => s.id === lead.segmento)?.nome || lead.segmento)), node("p", "", lead.telefone_publicado || "Telefone não publicado"));
      const buttons = node("div", "lead-actions");
      buttons.append(node("span", "badge " + (lead.demonstracao ? "amber" : "blue"), lead.demonstracao ? "Demonstração" : (lead.elegivel_para_etapa_comercial ? "Pronta para abordagem" : "Revisar contato")), action("Abrir empresa →", () => openLead(lead.id)));
      row.append(info, buttons); return row;
    }));
    $("search-source").textContent = data.empresas.some((lead) => lead.demonstracao) ? "Fonte de demonstração: empresas fictícias, sem envio real. Para pesquisar empresas reais, configure SEARCH_PROVIDER=overpass." : "Dados de fontes públicas. OpenStreetMap © colaboradores · ODbL. Verifique os contatos antes da abordagem.";
  }
  async function openLead(id, { refresh = false, preserveContact = false } = {}) {
    const lead = await api("/v1/empresas/" + encodeURIComponent(id));
    if (refresh && (!$("lead-dialog").open || state.lead?.id !== id)) return;
    const contactDraft = preserveContact ? { phone: $("lead-phone").value, evidence: $("lead-evidence").value, status: $("lead-consent-status").value } : null;
    state.lead = lead;
    $("lead-name").textContent = lead.nome;
    details($("lead-details"), [["Cidade / segmento", lead.cidade + " · " + lead.segmento], ["Endereço", lead.endereco_publicado], ["Contato publicado", lead.telefone_publicado], ["Site", lead.site], ["Origem", lead.demonstracao ? "Demonstração fictícia" : lead.fonte], ["Autorização WhatsApp", lead.consentimento_whatsapp]]);
    if (lead.url_fonte && /^https:\/\//.test(lead.url_fonte)) {
      const link = node("a", "", "Consultar fonte ↗"); link.href = lead.url_fonte; link.target = "_blank"; link.rel = "noopener noreferrer"; $("lead-details").append(link);
    }
    $("lead-review").value = lead.revisao; $("lead-note").value = lead.nota_revisao || "";
    $("lead-phone").value = contactDraft?.phone || lead.destinatario_whatsapp_autorizado || lead.telefone_normalizado || "";
    $("lead-evidence").value = contactDraft?.evidence || "";
    if (contactDraft) $("lead-consent-status").value = contactDraft.status;
    $("lead-add-funnel").disabled = lead.demonstracao; $("lead-draft").disabled = lead.demonstracao;
    $("lead-consent-form").hidden = lead.demonstracao;
    inlineError("lead-action-error");
    if (!$("lead-dialog").open) $("lead-dialog").showModal();
  }
  async function loadFunnel() {
    const params = new URLSearchParams({ limite: pageSize, pagina: state.funnelPage, busca: $("funnel-search").value.trim() });
    if ($("funnel-stage").value) params.set("etapa", $("funnel-stage").value);
    const data = await api("/v1/funil?" + params);
    $("funnel-total").textContent = data.total + " oportunidades nesta seleção · clique em uma empresa para atualizar a etapa e o próximo passo.";
    pager("funnel", state.funnelPage, data.aplicacoes.length, data.total);
    $("funnel-board").replaceChildren(...Object.entries(stages).filter(([id]) => !$("funnel-stage").value || $("funnel-stage").value === id).map(([id, title]) => {
      const column = node("section", "funnel-column"); column.dataset.stage = id;
      const entries = data.aplicacoes.filter((item) => item.etapa === id);
      const header = node("header"); header.append(node("h2", "", title), node("span", "count", entries.length)); column.append(header);
      for (const item of entries) {
        const card = node("button", "application-card"); card.type = "button";
        card.append(node("span", "badge " + (item.origem === "aplicacao" ? "blue" : "gray"), item.origem === "aplicacao" ? "Aplicação recebida" : "Pesquisa"), node("h3", "", item.nome_empresa), node("p", "", item.cidade + " / " + (item.uf || "SP") + " · " + item.segmento), node("p", "", item.servicos.map(serviceName).join(" · ")), node("p", "", item.nome_contato || "Contato a confirmar"), node("small", "", "Atualizada " + date(item.atualizada_em)));
        card.addEventListener("click", () => openApplication(item)); column.append(card);
      }
      if (!entries.length) column.append(node("p", "column-empty", "Nenhuma oportunidade nesta página"));
      return column;
    }));
  }
  function serviceName(id) { return ({ atendimento_ia: "Atendimento com IA", criacao_site: "Criação de site", sistema: "Sistema sob medida", reformulacao_site: "Reformulação de site" })[id] || id; }
  function openApplication(item) {
    state.application = item;
    $("application-name").textContent = item.nome_empresa; $("application-origin").textContent = item.origem === "aplicacao" ? "APLICAÇÃO PÚBLICA" : "EMPRESA DA PESQUISA";
    const includesSupport = item.servicos.includes("atendimento_ia");
    details($("application-details"), [["Cidade / segmento", item.cidade + " / " + (item.uf || "SP") + " · " + item.segmento], ["Serviços solicitados", item.servicos.map(serviceName).join(" · ")], ["Responsável", item.nome_contato], ["WhatsApp", item.whatsapp], ["Site atual", item.site_atual || "Não informado"], ...(includesSupport ? [["Canais de atendimento", item.canais.map(channelName).join(" e ")], ["Volume", volumes[item.volume]]] : []), ["Necessidade", item.objetivo], ["Autorização declarada no formulário", item.autoriza_contato ? "Autorizou contato sobre os serviços selecionados. Confira o responsável antes de registrar uma autorização de envio comercial." : "Não registrada"]]);
    if (item.abordagem_disponivel || item.empresa_id) {
    const contact = action("Revisar contato e preparar abordagem de atendimento", async () => {
      const result = await api("/v1/funil/" + item.id + "/empresa", { method: "POST" });
      $("funnel-dialog").close(); await openLead(result.empresa_id);
    });
    $("application-details").append(contact);
    } else $("application-details").append(node("p", "field-help", "Use o contato informado e registre a conversa, proposta e entrega nas notas deste projeto."));
    $("application-stage").value = item.etapa; $("application-notes").value = item.notas;
    $("application-stage").disabled = Boolean(item.cliente_id);
    $("application-convert").hidden = !includesSupport;
    $("application-convert").textContent = item.cliente_id ? "Abrir cliente" : "Implantar atendimento";
    $("application-convert").disabled = !item.cliente_id && item.etapa !== "ganha";
    $("application-convert-help").textContent = !includesSupport ? "Projeto de site ou sistema: acompanhe a contratação e a entrega nas etapas e notas do funil." : (item.cliente_id ? "O espaço de atendimento deste cliente já foi criado." : "Salve a etapa Contratada para habilitar o espaço de atendimento. A conexão com WhatsApp é configurada depois.");
    inlineError("application-error"); if (!$("funnel-dialog").open) $("funnel-dialog").showModal();
  }
  async function loadCommercial() {
    const [status, data, conversations] = await Promise.all([
      api("/v1/comercial/status"), api("/v1/comercial/mensagens?" + new URLSearchParams({ limite: pageSize, pagina: state.commercialPage, ...($("commercial-filter").value ? { status: $("commercial-filter").value } : {}) })),
      api("/v1/comercial/conversas?limite=" + pageSize + "&pagina=" + state.salesPage),
    ]);
    const heading = node("div", "status-heading"); heading.append(node("span", "badge " + (status.envio_ativo ? "green" : "amber"), status.envio_ativo ? "Habilitado" : "Configuração pendente"), node("h2", "", "WhatsApp comercial da Nelvo"));
    $("commercial-status").replaceChildren(heading, node("p", "", status.envio_ativo ? "Envio habilitado · " + status.abordagens_tentadas_hoje + " tentativas hoje de " + status.limite_diario_abordagens + ". Mensagens iniciais exigem autorização, revisão e template aprovado na Meta." : "Você já pode preparar e revisar abordagens. O envio será liberado após cadastrar o número e configurar a conta da Nelvo na Meta."));
    if (status.variaveis_pendentes.length) $("commercial-status").append(node("p", "field-help", "Configuração na hospedagem: " + status.variaveis_pendentes.join(", ")));
    pager("commercial", state.commercialPage, data.mensagens.length);
    if (!data.mensagens.length) empty($("commercial-messages"), "Nenhuma abordagem nesta seleção.", "Abra uma empresa na pesquisa ou no funil para criar o rascunho comercial.");
    else $("commercial-messages").replaceChildren(...data.mensagens.map((message) => {
      const card = node("article", "card commercial-card"); const header = node("div", "card-heading");
      header.append(node("h3", "", message.destinatario || "Destinatário a confirmar"), node("span", "badge " + (message.status === "rascunho" ? "amber" : "blue"), messageStatus[message.status] || message.status));
      card.append(header, node("p", "", message.texto), node("small", "muted", date(message.criada_em)));
      if (message.entrega) card.append(node("p", "message-status", "Entrega: " + ({ delivered: "entregue", read: "lida", failed: "falhou", sent: "enviada" }[message.entrega] || message.entrega)));
      if (message.erro) card.append(node("p", "message-status", message.erro));
      const buttons = node("div", "actions");
      const mutate = async (endpoint, body) => { await api("/v1/comercial/mensagens/" + message.id + endpoint, { method: "POST", ...(body ? { body } : {}) }); await loadCommercial(); };
      if (["rascunho", "aprovada"].includes(message.status)) {
        if (message.status === "rascunho") buttons.append(action("Aprovar rascunho", () => mutate("/revisao", { aprovar: true }), "primary"));
        buttons.append(action("Descartar", () => mutate("/revisao", { aprovar: false })));
      }
      if (message.status === "aprovada") { const send = action("Enfileirar envio", () => mutate("/enfileirar"), "primary"); send.disabled = !status.envio_ativo; buttons.append(send); }
      if (message.status === "na_fila") buttons.append(action("Cancelar envio", () => mutate("/cancelar")));
      if (message.empresa_id) buttons.append(action("Ver empresa", () => openLead(message.empresa_id), "quiet"));
      card.append(buttons); return card;
    }));
    pager("sales", state.salesPage, conversations.conversas.length);
    if (!conversations.conversas.length) empty($("commercial-conversations"), "As conversas comerciais aparecerão aqui.", "Acompanhe as respostas das empresas ao WhatsApp da Nelvo.");
    else $("commercial-conversations").replaceChildren(...conversations.conversas.map((item) => {
      const row = node("article", "card lead-row"); const copy = node("div", "lead-info");
      copy.append(node("h3", "", item.destinatario), node("p", "", item.contato_interrompido ? "Empresa pediu para interromper o contato" : (item.ia_pausada ? "Aguardando responsável" : "Respostas automáticas habilitadas")));
      row.append(copy, action("Abrir conversa →", async () => { state.sales = item; state.salesHistoryPage = 1; await loadSalesHistory(); $("sales-dialog").showModal(); })); return row;
    }));
  }
  async function loadSalesHistory() {
    const data = await api("/v1/comercial/conversas/" + state.sales.id + "?limite=50&pagina=" + state.salesHistoryPage);
    state.sales = data.conversa;
    $("sales-title").textContent = data.conversa.destinatario;
    $("sales-history").replaceChildren(...data.mensagens.map((message) => {
      const item = node("article", message.direcao === "saida" ? "outbound" : ""); item.append(node("small", "", (message.direcao === "saida" ? "Nelvo" : "Empresa") + " · " + date(message.criada_em)), node("span", "", message.texto)); return item;
    }));
    $("sales-history-prev").disabled = data.mensagens.length < 50; $("sales-history-next").disabled = state.salesHistoryPage === 1;
    $("sales-history-page").textContent = "Página " + state.salesHistoryPage;
    $("sales-help").textContent = data.conversa.contato_interrompido ? "Contato interrompido pela empresa." : (data.conversa.ia_pausada ? "Respostas automáticas pausadas. " + (data.conversa.motivo_pausa || "") : "O agente comercial conversa sobre a oferta da Nelvo.");
    $("sales-pause").disabled = data.conversa.contato_interrompido;
    $("sales-pause").textContent = data.conversa.ia_pausada ? "Retomar respostas automáticas" : "Pausar respostas automáticas";
  }
  for (const button of document.querySelectorAll("[data-open]")) button.addEventListener("click", guarded(() => showView(button.dataset.open)));
  $("copy-application").addEventListener("click", guarded(async () => { const url = location.origin + "/aplicar"; if (navigator.clipboard) { await navigator.clipboard.writeText(url); notice("Link do formulário copiado."); } else notice("Link da aplicação: " + url); }));
  $("search-form").addEventListener("submit", (event) => {
    event.preventDefault(); formAction(event.currentTarget, "search-error", async () => {
      $("search-submit").textContent = "Pesquisando…";
      try { await api("/v1/buscas", { method: "POST", timeoutMs: 65000, body: { cidade: $("search-city").value, segmentos: [$("search-segment").value], limite: Number($("search-limit").value), usar_cache: true } }); state.leadsPage = 1; await loadLeads(); notice("Pesquisa concluída. Abra uma empresa para revisar o contato."); }
      finally { $("search-submit").textContent = "Buscar empresas →"; }
    });
  });
  $("load-leads").addEventListener("click", guarded(async () => { state.leadsPage = 1; await loadLeads(); }));
  $("funnel-filter").addEventListener("submit", (event) => { event.preventDefault(); guarded(async () => { state.funnelPage = 1; await loadFunnel(); })(); });
  $("commercial-filter").addEventListener("change", guarded(async () => { state.commercialPage = 1; await loadCommercial(); }));
  for (const [prefix, field, work] of [["leads", "leadsPage", loadLeads], ["funnel", "funnelPage", loadFunnel], ["commercial", "commercialPage", loadCommercial], ["sales", "salesPage", loadCommercial]]) {
    for (const [suffix, delta] of [["prev", -1], ["next", 1]]) $(prefix + "-" + suffix).addEventListener("click", guarded(async () => { state[field] = Math.max(1, state[field] + delta); await work(); }));
  }
  $("funnel-detail-form").addEventListener("submit", (event) => { event.preventDefault(); formAction(event.currentTarget, "application-error", async () => {
    const item = await api("/v1/funil/" + state.application.id, { method: "PATCH", body: { etapa: $("application-stage").value, notas: $("application-notes").value } });
    state.application = item;
    await loadFunnel();
    if ($("funnel-dialog").open) openApplication(item);
    notice("Aplicação atualizada.");
  }); });
  $("application-convert").addEventListener("click", guarded(async () => {
    const item = state.application; $("funnel-dialog").close();
    if (item.cliente_id) { await loadCompanies(); state.view = "settings"; await selectCompany(item.cliente_id); }
    else openCompany(item);
  }));
  $("lead-review-form").addEventListener("submit", (event) => { event.preventDefault(); formAction(event.currentTarget, "lead-action-error", async () => {
    const id = state.lead.id; await api("/v1/empresas/" + id + "/revisao", { method: "POST", body: { status: $("lead-review").value, observacao: $("lead-note").value } }); await openLead(id, { refresh: true, preserveContact: true }); notice("Revisão salva.");
  }); });
  $("lead-consent-form").addEventListener("submit", (event) => { event.preventDefault(); formAction(event.currentTarget, "lead-action-error", async () => {
    const id = state.lead.id; await api("/v1/empresas/" + id + "/consentimento", { method: "POST", body: { status: $("lead-consent-status").value, destinatario_whatsapp: $("lead-phone").value, evidencia: $("lead-evidence").value } }); await openLead(id, { refresh: true }); notice("Autorização registrada.");
  }); });
  $("lead-add-funnel").addEventListener("click", guarded(async () => { await api("/v1/funil/empresas", { method: "POST", body: { empresa_id: state.lead.id } }); $("lead-dialog").close(); await showView("funnel"); notice("Empresa adicionada ao funil."); }));
  $("lead-draft").addEventListener("click", guarded(async () => { await api("/v1/comercial/rascunhos", { method: "POST", body: { empresa_id: state.lead.id } }); $("lead-dialog").close(); await showView("commercial"); notice("Abordagem criada. Revise antes de enviar."); }));
  $("sales-pause").addEventListener("click", guarded(async () => { await api("/v1/comercial/conversas/" + state.sales.id + "/pausa", { method: "POST", body: { pausado: !state.sales.ia_pausada } }); await loadSalesHistory(); }));
  for (const [id, delta] of [["sales-history-prev", 1], ["sales-history-next", -1]]) $(id).addEventListener("click", guarded(async () => { state.salesHistoryPage = Math.max(1, state.salesHistoryPage + delta); await loadSalesHistory(); }));
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
