/* Fluxo real de navegador contra SQLite descartável, sem Meta ou IA paga. */
const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const fs = require("node:fs/promises");
const path = require("node:path");
const { chromium } = require("playwright");
const KEY = "browser-test-administrative-key-not-a-real-secret";
const port = process.env.PANEL_TEST_PORT || "8136";
const base = "http://127.0.0.1:" + port;
const output = process.env.PANEL_TEST_OUTPUT || "/tmp/atendeai-panel-check";
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let serverOutput = "";
const server = spawn(process.env.PYTHON_BIN || "python3", ["-m", "uvicorn", "browser_server:app", "--app-dir", "tests", "--host", "127.0.0.1", "--port", port, "--log-level", "warning"], {
  cwd: path.resolve(__dirname, ".."), env: { ...process.env, PANEL_TEST_PORT: port }, stdio: ["ignore", "pipe", "pipe"],
});
server.stdout.on("data", (chunk) => { serverOutput += chunk; });
server.stderr.on("data", (chunk) => { serverOutput += chunk; });
let browser;
async function waitFor(work, description) {
  for (let i = 0; i < 80; i++) {
    if (await work()) return;
    await delay(250);
  }
  throw new Error("Não concluído: " + description);
}
async function get(route, administrative = false) {
  const response = await fetch(base + route, { headers: administrative ? { "X-API-Key": KEY } : {} });
  assert.equal(response.status, 200, "GET " + route);
  return response.json();
}
async function visible(page, selector) { await page.locator(selector).first().waitFor({ state: "visible", timeout: 20000 }); }
async function noOverflow(page, label) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  assert.equal(overflow, false, label + " cabe na tela");
}
async function scrollService(page, index, label) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.evaluate((index) => {
    const marker = document.getElementById("service-marker-" + index);
    const panel = document.getElementById("service-panel-" + index);
    const top = parseFloat(getComputedStyle(panel).top) || 110;
    window.scrollTo({ top: window.scrollY + marker.getBoundingClientRect().top - top + 10, behavior: "instant" });
  }, index);
  await waitFor(async () => await page.locator("#service-tab-" + index).getAttribute("aria-current") === "step", label);
  assert.equal(await page.locator(".solution-card").count(), 4, "Os quatro cartões mantêm o conteúdo acessível");
  await delay(550);
  await noOverflow(page, label);
  const card = await page.locator("#service-panel-" + index).boundingBox();
  assert(card.y >= 0 && card.y < page.viewportSize().height, label + " visível durante o scroll");
  await page.screenshot({ path: path.join(output, label + ".png") });
}

(async () => {
  await fs.mkdir(output, { recursive: true });
  await waitFor(async () => { try { return (await fetch(base + "/health")).ok; } catch { return false; } }, "inicialização do servidor");
  const fixtures = await get("/__test__/fixtures");
  const errors = [];
  browser = await chromium.launch({ headless: true,
    ...(process.env.PANEL_CHROME_PATH ? { executablePath: process.env.PANEL_CHROME_PATH } : {}),
    ...(process.env.PANEL_CHROME_ARGS ? { args: JSON.parse(process.env.PANEL_CHROME_ARGS) } : {}),
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const panel = await context.newPage();
  panel.on("pageerror", (error) => errors.push(error.message));
  await panel.goto(base + "/painel");
  await visible(panel, "#login-screen");
  await noOverflow(panel, "Login desktop");
  await panel.screenshot({ path: path.join(output, "login-desktop.png"), fullPage: true });
  await panel.locator("#admin-key").fill("incorrect-administrative-key");
  await panel.locator("#login-submit").click();
  await visible(panel, "#login-error");
  assert.equal(await panel.locator("#app-screen").isVisible(), false);
  await panel.locator("#admin-key").fill(KEY);
  await panel.locator("#login-submit").click();
  await visible(panel, "#app-screen");
  await waitFor(async () => (await panel.locator("#company-select").inputValue()) === fixtures.first.id, "empresa inicial");
  assert.equal(await panel.locator("#admin-key").inputValue(), "");
  assert.equal(await panel.evaluate((key) => JSON.stringify({ ...localStorage, ...sessionStorage }).includes(key), KEY), false);

  await visible(panel, "#view-dashboard");
  await visible(panel, ".metric");
  await noOverflow(panel, "Central Nelvo desktop");
  await panel.screenshot({ path: path.join(output, "nelvo-dashboard-desktop.png"), fullPage: true });

  // Formulário público real: três etapas, revisão segura, recibo e aplicação no funil privado.
  const applicant = await context.newPage();
  applicant.on("pageerror", (error) => errors.push(error.message));
  await applicant.goto(base + "/");
  await visible(applicant, ".home-page");
  await noOverflow(applicant, "Home desktop");
  assert.equal(Math.round((await applicant.locator(".site-header").boundingBox()).width), 1440, "Navbar acompanha toda a largura da página");
  await applicant.locator("[data-theme-toggle]").click();
  await waitFor(async () => await applicant.locator("html").getAttribute("data-theme") === "dark", "transição para tema escuro");
  assert.equal(await applicant.locator("html").getAttribute("data-theme"), "dark");
  await applicant.reload();
  assert.equal(await applicant.locator("html").getAttribute("data-theme"), "dark", "Tema permanece após recarregar");
  assert.equal(await applicant.locator("[data-theme-toggle]").getAttribute("aria-label"), "Ativar tema claro");
  await applicant.screenshot({ path: path.join(output, "home-dark-desktop.png"), fullPage: true });
  await applicant.locator("[data-theme-toggle]").click();
  await waitFor(async () => await applicant.locator("html").getAttribute("data-theme") === "light", "transição para tema claro");
  assert.equal(await applicant.locator("html").getAttribute("data-theme"), "light");
  assert.equal(await applicant.locator("#public-application-form").count(), 0, "Formulário carregado ao abrir o popup");
  assert.equal(await applicant.locator(".solution-card").count(), 4);
  assert.equal(await applicant.locator(".nelvo-logo img").first().evaluate((img) => img.complete && img.naturalWidth > 0), true, "Logo original carregada");
  await applicant.screenshot({ path: path.join(output, "home-desktop.png"), fullPage: true });
  await applicant.screenshot({ path: path.join(output, "home-hero-desktop.png") });
  assert.equal(await applicant.locator("#nelvo-film").count(), 1);
  assert.equal(await applicant.locator("#nelvo-film").evaluate(el => el.controls && el.muted && el.playsInline), true);
  assert.equal(await applicant.locator(".about-art img,.studio-showcase img").count(), 2);
  assert.equal(await applicant.locator(".services-footer").count(), 0, "Faixa removida");
  for (let index = 0; index < 4; index++) await scrollService(applicant, index, "servico-desktop-" + (index + 1));
  await applicant.evaluate(() => window.scrollTo({top: 0, behavior: "instant"}));
  await applicant.locator(".hero-actions .cta").click();
  assert.equal(new URL(applicant.url()).pathname, "/");
  assert.equal(await applicant.locator("#application-modal").evaluate((el) => el.open), true);
  await visible(applicant, "#apply-company");
  await delay(450);
  await noOverflow(applicant, "Aplicação desktop");
  await applicant.screenshot({ path: path.join(output, "aplicacao-desktop.png") });
  await applicant.locator("#apply-company").fill('Pizzaria do Bairro <img src=x onerror="window.__xss=true">');
  await applicant.keyboard.press("Escape");
  await applicant.locator("#application-modal").waitFor({ state: "hidden" });
  assert.equal(await applicant.locator("#application-modal").isVisible(), false);
  assert.equal(await applicant.locator(".hero-actions .cta").evaluate((el) => el === document.activeElement), true, "Foco volta ao botão");
  await applicant.locator(".hero-actions .cta").click();
  assert((await applicant.locator("#apply-company").inputValue()).startsWith("Pizzaria do Bairro"), "Fechar preserva o preenchimento");
  await applicant.locator("#application-modal-close").focus();
  await applicant.keyboard.press("Shift+Tab");
  assert.equal(await applicant.evaluate(() => document.activeElement.closest("dialog")?.id), "application-modal", "Teclado permanece no popup");
  await applicant.locator("#apply-city").fill("Campinas");
  await applicant.locator("#apply-state").selectOption("SP");
  await applicant.locator("#apply-segment").selectOption("restaurantes");
  await applicant.locator("#apply-contact").fill("Responsável Fictício");
  await applicant.locator("#apply-phone").fill("(19) 91234-5678");
  await applicant.locator("#application-next").click();
  await applicant.locator("#apply-service-atendimento_ia").check();
  await visible(applicant, "#apply-volume");
  await applicant.locator("#apply-volume").selectOption("31_100");
  await applicant.locator("#apply-goal").fill("Responder dúvidas sobre cardápio, horários e entrega.");
  await applicant.locator("#application-next").click();
  await visible(applicant, "#public-summary");
  assert.equal(await applicant.evaluate(() => Boolean(window.__xss)), false);
  await applicant.locator("#application-back").click();
  assert.equal(await applicant.locator("#apply-volume").inputValue(), "31_100");
  await applicant.locator("#application-next").click();
  await applicant.locator("#apply-consent").check();
  await applicant.locator("#application-submit").click();
  await visible(applicant, "#public-success");
  await panel.locator('[data-view="funnel"]').click();
  await visible(panel, ".application-card");
  const applicationCard = panel.locator(".application-card").filter({ hasText: "Pizzaria do Bairro" });
  await applicationCard.click();
  await visible(panel, "#funnel-dialog");
  assert.equal(await panel.locator("#application-convert").isEnabled(), false);
  await panel.locator("#application-stage").selectOption("proposta");
  await panel.locator("#application-notes").fill("Demonstração concluída; proposta apresentada.");
  await panel.locator('#funnel-detail-form button[type="submit"]').click();
  await waitFor(async () => (await get("/v1/funil", true)).aplicacoes.some((item) => item.nome_empresa.startsWith("Pizzaria do Bairro") && item.etapa === "proposta"), "etapa persistida");
  await waitFor(async () => await panel.locator('#funnel-detail-form button[type="submit"]').isEnabled(), "atualização do formulário concluída");
  await panel.locator("#funnel-dialog .close-dialog").click();
  await panel.screenshot({ path: path.join(output, "funil-desktop.png"), fullPage: true });
  await applicationCard.click();
  await panel.locator("#application-stage").selectOption("ganha");
  await panel.locator('#funnel-detail-form button[type="submit"]').click();
  await waitFor(async () => await panel.locator("#application-convert").isEnabled(), "cadastro liberado após contratação");
  await panel.locator("#application-convert").click();
  await visible(panel, "#company-dialog");
  await panel.locator('#company-form button[type="submit"]').click();
  await visible(panel, "#integration-code");
  assert.equal(await panel.evaluate(() => Boolean(window.__xss)), false);
  const apps = (await get("/v1/funil", true)).aplicacoes;
  assert(apps.find((item) => item.nome_empresa.startsWith("Pizzaria do Bairro")).cliente_id, "Aplicação vinculada ao serviço do cliente");
  await applicant.locator("#application-new-request").click();
  assert.equal(await applicant.locator("#apply-company").inputValue(), "", "Nova solicitação começa vazia");
  assert.equal(await applicant.locator("#application-step-1").isVisible(), true);

  // Projeto web de outro estado: seleção pela home, URL obrigatória e nenhuma implantação de atendimento.
  await applicant.goto(base + "/");
  await scrollService(applicant, 3, "servico-reformulacao-cta");
  await applicant.locator('a[href="/aplicar?servico=reformulacao_site"]').click();
  await applicant.locator("#apply-company").fill("Studio Web Nacional · teste");
  await applicant.locator("#apply-city").fill("Belo Horizonte");
  await applicant.locator("#apply-state").selectOption("MG");
  await applicant.locator("#apply-segment").selectOption("outro");
  await applicant.locator("#apply-contact").fill("Responsável do Projeto");
  await applicant.locator("#apply-phone").fill("(31) 91234-5678");
  await applicant.locator("#application-next").click();
  assert.equal(await applicant.locator("#apply-service-reformulacao_site").isChecked(), true);
  assert.equal(await applicant.locator("#apply-support-fields").isVisible(), false);
  await applicant.locator("#apply-goal").fill("Reformular o site e organizar o controle financeiro em um sistema próprio.");
  await applicant.locator("#application-next").click();
  assert.equal(await applicant.locator("#application-step-2").isVisible(), true, "Site atual obrigatório para reformulação");
  await applicant.locator("#apply-website").fill("https://studio.example.invalid");
  await applicant.locator("#apply-service-sistema").check();
  await applicant.locator("#apply-service-criacao_site").check();
  await applicant.locator("#application-next").click();
  await visible(applicant, "#public-summary");
  assert((await applicant.locator("#public-summary").textContent()).includes("Belo Horizonte / MG"));
  await applicant.locator("#apply-consent").check();
  await applicant.locator("#application-submit").click();
  await visible(applicant, "#public-success");
  await panel.locator('[data-view="funnel"]').click();
  await panel.locator(".application-card").filter({ hasText: "Studio Web Nacional" }).click();
  assert.equal(await panel.locator("#application-convert").isVisible(), false);
  assert((await panel.locator("#application-details").textContent()).includes("Sistema sob medida"));
  assert((await panel.locator("#application-details").textContent()).includes("https://studio.example.invalid"));
  await panel.locator("#funnel-dialog .close-dialog").click();

  // Pesquisa e abordagem da Nelvo: revisão, autorização, rascunho e aprovação, sem enviar WhatsApp.
  await panel.locator('[data-view="research"]').click();
  await visible(panel, ".lead-row");
  await panel.locator(".lead-row").filter({ hasText: "Restaurante Jardim" }).getByRole("button", { name: "Abrir empresa →" }).click();
  await visible(panel, "#lead-dialog");
  await panel.locator("#lead-review").selectOption("aprovada");
  await panel.locator('#lead-review-form button[type="submit"]').click();
  await waitFor(async () => (await get("/v1/empresas/" + fixtures.lead_id, true)).revisao === "aprovada", "revisão da empresa");
  await panel.locator("#lead-evidence").fill("Autorização fictícia do responsável registrada exclusivamente para este teste automatizado.");
  await panel.locator('#lead-consent-form button[type="submit"]').click();
  await waitFor(async () => (await get("/v1/empresas/" + fixtures.lead_id, true)).consentimento_whatsapp === "concedido", "autorização comercial");
  await panel.locator("#lead-add-funnel").click();
  await visible(panel, "#view-funnel");
  await panel.locator('[data-view="research"]').click();
  await panel.locator(".lead-row").filter({ hasText: "Restaurante Jardim" }).getByRole("button", { name: "Abrir empresa →" }).click();
  await panel.locator("#lead-draft").click();
  await visible(panel, ".commercial-card");
  await panel.getByText(/Aqui é da Nelvo Company/).waitFor();
  await panel.getByRole("button", { name: "Aprovar rascunho" }).click();
  await panel.getByRole("button", { name: "Enfileirar envio" }).waitFor();
  assert.equal(await panel.getByRole("button", { name: "Enfileirar envio" }).isEnabled(), false, "Envio bloqueado sem Meta configurada");
  await noOverflow(panel, "Comercial desktop");
  await panel.screenshot({ path: path.join(output, "comercial-desktop.png"), fullPage: true });

  await panel.setViewportSize({ width: 390, height: 844 });
  await panel.locator('[data-view="dashboard"]').click();
  await visible(panel, ".metric");
  await noOverflow(panel, "Central Nelvo móvel");
  await panel.locator("#mobile-menu-toggle").click();
  assert.equal(await panel.locator("#mobile-menu-toggle").getAttribute("aria-expanded"), "false");
  await panel.screenshot({ path: path.join(output, "nelvo-dashboard-mobile.png"), fullPage: true });
  await panel.locator("#mobile-menu-toggle").click();
  await panel.locator('[data-view="funnel"]').click();
  await visible(panel, ".application-card");
  await noOverflow(panel, "Funil móvel");
  await panel.locator("#mobile-menu-toggle").click();
  await panel.screenshot({ path: path.join(output, "funil-mobile.png"), fullPage: true });
  await panel.locator("#mobile-menu-toggle").click();
  await applicant.setViewportSize({ width: 390, height: 844 });
  await applicant.goto(base + "/");
  await noOverflow(applicant, "Home móvel");
  await applicant.screenshot({ path: path.join(output, "home-mobile.png"), fullPage: true });
  await applicant.screenshot({ path: path.join(output, "home-hero-mobile.png") });
  for (let index = 0; index < 4; index++) await scrollService(applicant, index, "servico-mobile-" + (index + 1));
  await applicant.locator('a[href="/aplicar?servico=reformulacao_site"]').click();
  await visible(applicant, "#apply-company");
  await noOverflow(applicant, "Popup móvel");
  await delay(450);
  await applicant.screenshot({ path: path.join(output, "popup-mobile.png") });
  await applicant.locator("#apply-company").fill("Empresa teste móvel");
  await applicant.locator("#apply-city").fill("Recife");
  await applicant.locator("#apply-state").selectOption("PE");
  await applicant.locator("#apply-segment").selectOption("outro");
  await applicant.locator("#apply-contact").fill("Responsável Teste");
  await applicant.locator("#apply-phone").fill("(81) 91234-5678");
  await applicant.locator("#application-next").click();
  await visible(applicant, "#apply-service-reformulacao_site");
  await noOverflow(applicant, "Projeto no popup móvel");
  await delay(450);
  await applicant.screenshot({ path: path.join(output, "popup-projeto-mobile.png") });
  await applicant.locator("#application-modal-close").click();
  await applicant.emulateMedia({ reducedMotion: "reduce" });
  assert.equal(await applicant.locator("#nelvo-film").evaluate(el => el.paused), true);
  await applicant.locator("#service-tab-0").click();
  await applicant.keyboard.press("ArrowRight");
  assert.equal(await applicant.locator("#service-tab-1").getAttribute("aria-current"), "step");
  assert.equal(await applicant.locator("#service-panel-1").evaluate((el) => getComputedStyle(el).position), "relative");
  await applicant.emulateMedia({ reducedMotion: "no-preference" });
  await applicant.evaluate(() => window.scrollTo({top: 0, behavior: "instant"}));
  await applicant.locator("#home-menu-toggle").click();
  assert.equal(await applicant.locator("#home-menu-toggle").getAttribute("aria-expanded"), "true");
  await applicant.locator('#home-nav a[href="#duvidas"]').click();
  assert.equal(await applicant.locator("#home-menu-toggle").getAttribute("aria-expanded"), "false");
  await applicant.locator(".faq-list summary").first().click();
  assert.equal(await applicant.locator(".faq-list details").first().getAttribute("open"), "");
  await applicant.goto(base + "/aplicar");
  await visible(applicant, "#apply-company");
  await noOverflow(applicant, "Aplicação móvel");
  await applicant.screenshot({ path: path.join(output, "aplicacao-mobile.png"), fullPage: true });
  // Falha temporária: reabrir o fragmento mantém apenas uma instância do formulário.
  let unavailable = true;
  await applicant.route("**/aplicar/conteudo", (route) => unavailable ? route.fulfill({ status: 503, body: "Indisponível" }) : route.continue());
  await applicant.goto(base + "/");
  await applicant.locator(".hero-actions .cta").click();
  await visible(applicant, '#application-modal button:has-text("Tentar novamente")');
  assert.equal(await applicant.locator('#application-modal a[data-standalone]').getAttribute("href"), "/aplicar");
  unavailable = false;
  await applicant.getByRole("button", { name: "Tentar novamente" }).click();
  await visible(applicant, "#apply-company");
  assert.equal(await applicant.locator("#public-application-form").count(), 1);
  await applicant.locator("#application-modal-close").click();
  // Conteúdo permanece acessível mesmo em uma tela estreita ou baixa.
  await applicant.setViewportSize({ width: 320, height: 780 });
  await applicant.locator("#service-tab-3").click();
  assert.equal(await applicant.locator("#service-tab-3").getAttribute("aria-current"), "step");
  await noOverflow(applicant, "Home estreita");
  await applicant.setViewportSize({ width: 768, height: 1024 });
  await scrollService(applicant, 2, "servico-tablet");
  await applicant.close();
  await panel.setViewportSize({ width: 1440, height: 1000 });
  await panel.locator("#company-select").selectOption(fixtures.first.id);
  await panel.locator('[data-view="inbox"]').click();

  // Cliente no widget: pergunta da base, pedido de humano e resposta do operador.
  const visitorContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const visitor = await visitorContext.newPage();
  visitor.on("pageerror", (error) => errors.push(error.message));
  await visitor.goto(base + "/teste-atendimento?" + new URLSearchParams({ empresa: fixtures.first.id, chave: fixtures.first.chave_site }));
  await visitor.getByRole("button", { name: "Atendimento", exact: true }).click();
  await visitor.getByRole("textbox", { name: "Sua mensagem" }).fill("Qual o horário de atendimento?");
  await visitor.getByRole("button", { name: "Enviar", exact: true }).click();
  await visitor.getByText("Atendemos de segunda a sexta, das 9h às 18h.", { exact: true }).waitFor({ timeout: 20000 });
  await visitor.getByRole("textbox", { name: "Sua mensagem" }).fill("Quero falar com um atendente.");
  await visitor.getByRole("button", { name: "Enviar", exact: true }).click();
  await visitor.getByText("Estou encaminhando seu chamado para um responsável dar continuidade ao atendimento.", { exact: true }).waitFor({ timeout: 20000 });
  await panel.locator("#refresh").click();
  await visible(panel, ".queue-item");
  await panel.locator(".queue-item").first().click();
  await waitFor(async () => (await panel.locator("#conversation-state").textContent()) === "Com responsável", "histórico do chamado");
  const malicious = '<img src=x onerror="window.__xss=true">';
  const manual = "Olá! Aqui é o responsável. Vou verificar sua solicitação. " + malicious;
  await panel.locator("#reply-text").fill(manual);
  await panel.locator("#reply-submit").click();
  await visitor.getByText(manual, { exact: true }).waitFor({ timeout: 20000 });
  assert.equal(await panel.evaluate(() => Boolean(window.__xss)), false);
  assert.equal(await visitor.evaluate(() => Boolean(window.__xss)), false);
  assert.equal(await panel.locator("#conversation-state").textContent(), "Com responsável");
  await noOverflow(panel, "Atendimento desktop");
  await panel.screenshot({ path: path.join(output, "atendimento-desktop.png"), fullPage: true });
  await panel.locator("#resume-bot").click();
  await waitFor(async () => (await panel.locator("#conversation-state").textContent()) === "Automático", "retomada do bot");
  const tickets = await get("/v1/atendimento/empresas/" + fixtures.first.id + "/chamados", true);
  assert.equal(tickets.chamados.length, 0, "Chamado concluído");
  await visitor.getByRole("textbox", { name: "Sua mensagem" }).fill("Qual o horário de atendimento?");
  await visitor.getByRole("button", { name: "Enviar", exact: true }).click();
  await waitFor(async () => (await visitor.getByText("Atendemos de segunda a sexta, das 9h às 18h.", { exact: true }).count()) === 2, "bot responde depois da retomada");

  // Base: cadastrar, editar e desativar; dados de outra empresa ficam separados.
  await panel.locator('[data-view="knowledge"]').click();
  await visible(panel, ".knowledge-card");
  await panel.locator("#add-knowledge").click();
  await panel.locator("#knowledge-title").fill("Serviços " + malicious);
  await panel.locator("#knowledge-text").fill("Fazemos revisão e troca de óleo. " + malicious);
  await panel.locator('#knowledge-form button[type="submit"]').click();
  await waitFor(async () => (await panel.locator(".knowledge-card").count()) === 2, "cadastro de resposta");
  assert.equal(await panel.evaluate(() => Boolean(window.__xss)), false);
  const card = panel.locator(".knowledge-card").filter({ has: panel.getByRole("heading", { name: "Serviços " + malicious, exact: true }) });
  await card.getByRole("button", { name: "Editar resposta" }).click();
  await panel.locator("#knowledge-text").fill("Revisão de veículos com agendamento.");
  await panel.locator('#knowledge-form button[type="submit"]').click();
  await card.getByText("Revisão de veículos com agendamento.", { exact: true }).waitFor();
  await card.getByRole("button", { name: "Desativar", exact: true }).click();
  await card.getByText("Desativada", { exact: true }).waitFor();
  await panel.locator("#company-select").selectOption(fixtures.second.id);
  await visible(panel, ".knowledge-card");
  await panel.getByRole("heading", { name: "Resposta exclusiva da Aurora", exact: true }).waitFor();
  assert.equal(await panel.getByRole("heading", { name: "Serviços " + malicious, exact: true }).count(), 0);

  // Cadastro e configuração: código do widget, link de teste e substituição deliberada.
  await panel.locator("#create-company").click();
  await panel.locator("#new-name").fill("Empresa de teste " + malicious);
  await panel.locator("#new-origins").fill("https://empresa.example.invalid");
  await panel.locator('#company-form button[type="submit"]').click();
  await visible(panel, "#integration-code");
  const newId = await panel.locator("#tenant-reference").inputValue();
  const integration = await panel.locator("#integration-code").textContent();
  assert(integration.includes(newId));
  assert.equal(integration.includes(KEY), false);
  assert.equal(await panel.evaluate(() => Boolean(window.__xss)), false);
  assert.equal(await panel.locator("#settings-ai").isChecked(), false);
  await panel.locator("#settings-conversations").fill("25");
  await panel.locator('#settings-form button[type="submit"]').click();
  await waitFor(async () => (await panel.locator("#conversation-limit").textContent()) === "25", "salvar limites");
  await noOverflow(panel, "Configuração desktop");
  await panel.screenshot({ path: path.join(output, "configuracao-desktop.png"), fullPage: true });
  await panel.locator("#rotate-site-key").click();
  assert.equal(await panel.locator("#integration-code").textContent(), integration);
  await panel.locator("#rotate-dialog .close-dialog.button").click();
  assert.equal(await panel.locator("#integration-code").textContent(), integration);
  await panel.locator("#rotate-site-key").click();
  await panel.locator("#confirm-rotate").click();
  await waitFor(async () => (await panel.locator("#integration-code").textContent()) !== integration, "substituição de chave");
  const testLink = await panel.locator("#test-company").getAttribute("href");
  assert(testLink.includes(newId));
  assert.equal(testLink.includes(KEY), false);

  // Layout móvel, saída e recarga: nenhuma chave administrativa persistida.
  await panel.setViewportSize({ width: 390, height: 844 });
  await noOverflow(panel, "Configuração móvel");
  await panel.screenshot({ path: path.join(output, "configuracao-mobile.png"), fullPage: true });
  await panel.locator("#company-select").selectOption(fixtures.first.id);
  await panel.locator('[data-view="inbox"]').click();
  await panel.locator("#queue-filter").selectOption("conversas");
  await visible(panel, ".queue-item");
  await panel.locator(".queue-item").first().click();
  await visible(panel, "#conversation-content");
  await noOverflow(panel, "Atendimento móvel");
  await panel.screenshot({ path: path.join(output, "atendimento-mobile.png"), fullPage: true });
  await panel.locator("#logout").click();
  await visible(panel, "#login-screen");
  assert.equal(await panel.locator("#message-list").textContent(), "");
  assert.equal(await panel.locator("#application-details").textContent(), "");
  assert.equal(await panel.locator("#lead-phone").inputValue(), "");
  assert.equal(await panel.evaluate((key) => JSON.stringify({ ...localStorage, ...sessionStorage }).includes(key), KEY), false);
  await panel.reload();
  await visible(panel, "#login-screen");
  await noOverflow(panel, "Login móvel");
  await panel.screenshot({ path: path.join(output, "login-mobile.png"), fullPage: true });
  assert.deepEqual(errors, [], "Sem erros de JavaScript no painel ou widget");
  console.log("Painel verificado em desktop e celular: login, empresa, base, isolamento, chamado, resposta humana, retomada e chave apenas em memória.");
  console.log("Nelvo verificada: aplicação pública, etapas do funil, cadastro do cliente, revisão, autorização, abordagem comercial e menu móvel.");
  console.log("Testes com empresas fictícias; nenhum envio real de WhatsApp ou consumo de IA.");
})().catch(async (error) => {
  if (browser) {
    const pages = browser.contexts().flatMap((context) => context.pages());
    for (let index = 0; index < pages.length; index++) {
      await pages[index].screenshot({ path: path.join(output, "falha-" + index + ".png"), fullPage: true }).catch(() => {});
    }
  }
  console.error(error);
  if (serverOutput) console.error(serverOutput);
  process.exitCode = 1;
}).finally(async () => {
  if (browser) await browser.close();
  server.kill("SIGTERM");
});
