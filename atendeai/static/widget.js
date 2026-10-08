(() => {
  'use strict';
  const script = document.currentScript;
  if (!script || !script.dataset.empresa || !script.dataset.chave) return;
  const api = new URL(script.src).origin;
  const tenant = script.dataset.empresa, siteKey = script.dataset.chave;
  const storageKey = `atendeai:${api}:${tenant}`;
  const container = document.createElement('div'), shadow = container.attachShadow({mode: 'open'});
  shadow.innerHTML = `<style>
    :host{font-family:system-ui,-apple-system,sans-serif;color:#17324d;font-size:14px}*{box-sizing:border-box}button,textarea{font:inherit}button{cursor:pointer}
    .toggle{position:fixed;right:20px;bottom:20px;border:0;border-radius:28px;background:#075e54;color:white;padding:14px 22px;box-shadow:0 5px 20px #0002;font-weight:600;z-index:2147483000}
    .panel{position:fixed;right:20px;bottom:82px;width:min(370px,calc(100vw - 32px));height:min(540px,calc(100dvh - 115px));background:white;border:1px solid #dbe3e9;border-radius:18px;box-shadow:0 10px 45px #0003;z-index:2147483000;display:flex;flex-direction:column;overflow:hidden}
    .panel[hidden]{display:none}.header{background:#075e54;color:white;padding:18px;display:flex;align-items:center;gap:10px}.title{font-weight:700;font-size:17px;flex:1}.close{border:0;background:transparent;color:white;font-size:22px;padding:2px 6px}
    .messages{padding:16px;overflow:auto;flex:1;background:#f5f8fa;display:flex;flex-direction:column;gap:12px}.bubble{max-width:90%;padding:11px 13px;border-radius:13px;background:white;border:1px solid #e2e8ee;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.45}.mine{align-self:flex-end;background:#daf3ea;border-color:#c4e9dd}.who{font-size:11px;font-weight:600;color:#526777;display:block;margin-bottom:4px}
    .status{font-size:12px;padding:10px 16px;background:#fff;color:#526777;min-height:34px}.form{border-top:1px solid #e4e9ed;padding:12px;display:flex;align-items:flex-end;gap:8px}textarea{resize:none;flex:1;width:0;border:1px solid #cad5df;border-radius:10px;padding:10px;min-height:42px;max-height:110px;color:#17324d}textarea:focus{outline:2px solid #32a88d;outline-offset:1px}.send{border:0;background:#075e54;color:white;border-radius:10px;padding:12px}.send:disabled{opacity:.5;cursor:wait}.footer{padding:0 12px 10px;font-size:11px;color:#647684;display:flex;justify-content:space-between}.new{background:none;border:0;padding:0;color:#075e54;font-size:11px;text-decoration:underline}
    @media(max-width:430px){.panel{right:16px;bottom:78px}.toggle{right:16px;bottom:16px}}
  </style><button class="toggle" type="button" aria-expanded="false">Atendimento</button>
  <section class="panel" hidden aria-label="Chat de atendimento"><div class="header"><span class="title">Atendimento</span><button class="close" type="button" aria-label="Fechar chat">×</button></div>
  <div class="messages" role="log" aria-live="polite" aria-label="Mensagens"></div><div class="status" role="status"></div>
  <form class="form"><textarea aria-label="Sua mensagem" placeholder="Escreva sua dúvida…" maxlength="4000" rows="1" required></textarea><button class="send" type="submit">Enviar</button></form>
  <div class="footer"><span>Assistente virtual · AtendeAI</span><button class="new" type="button">Nova conversa</button></div></section>`;
  if (document.body) document.body.appendChild(container);
  else document.addEventListener('DOMContentLoaded', () => document.body.appendChild(container), {once: true});
  const $ = selector => shadow.querySelector(selector);
  const panel = $('.panel'), toggle = $('.toggle'), log = $('.messages'), status = $('.status');
  const input = $('textarea'), send = $('.send');
  let session = null, timer = null, busy = false, refreshing = false, pending = null;
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey));
    if (saved && saved.conversa && saved.conversa.id && saved.token_conversa) session = saved;
  } catch (_) {}
  const save = () => { try { session ? sessionStorage.setItem(storageKey, JSON.stringify(session)) : sessionStorage.removeItem(storageKey); } catch (_) {} };
  async function request(path, options = {}) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(api + path, {...options, signal: controller.signal, credentials: 'omit'});
      const data = await response.json();
      if (!response.ok) { const error = new Error(data.detail || 'Atendimento indisponível no momento.'); error.code = response.status; throw error; }
      return data;
    } finally { clearTimeout(timeout); }
  }
  const base = () => `/v1/atendimento/site/${encodeURIComponent(tenant)}/conversas/${encodeURIComponent(session.conversa.id)}/mensagens`;
  const auth = () => ({Authorization: `Bearer ${session.token_conversa}`});
  async function ensureSession() {
    if (!session) {
      session = await request(`/v1/atendimento/site/${encodeURIComponent(tenant)}/conversas`, {method: 'POST', headers: {'X-Site-Key': siteKey}});
      save();
    }
  }
  function render(data) {
    log.replaceChildren();
    for (const message of data.mensagens) {
      const bubble = document.createElement('div');
      bubble.className = 'bubble' + (message.direcao === 'entrada' ? ' mine' : '');
      const who = document.createElement('span');
      who.className = 'who';
      who.textContent = message.direcao === 'entrada' ? 'Você' : message.autor === 'humano' ? 'Atendente' : 'Assistente virtual';
      const text = document.createElement('span'); text.textContent = message.texto;
      bubble.append(who, text); log.appendChild(bubble);
    }
    log.scrollTop = log.scrollHeight;
    status.textContent = data.conversa.estado === 'humano' ? 'Aguardando atendimento de um responsável.' :
      data.mensagens.some(message => message.direcao === 'entrada' && ['recebida', 'em_analise'].includes(message.status)) ? 'Preparando resposta…' : '';
    input.disabled = data.conversa.estado === 'interrompida';
  }
  async function refresh() {
    if (!session || refreshing || panel.hidden) return;
    refreshing = true;
    try { render(await request(base(), {headers: auth()})); }
    catch (error) {
      if (error.code === 401 || error.code === 404) { session = null; save(); }
      status.textContent = 'Não foi possível atualizar. Tente abrir o chat novamente.';
    } finally { refreshing = false; }
  }
  async function open() {
    if (busy) return;
    panel.hidden = false; toggle.setAttribute('aria-expanded', 'true');
    status.textContent = 'Iniciando atendimento…'; busy = true; send.disabled = true;
    try { await ensureSession(); await refresh(); input.focus(); }
    catch (error) { status.textContent = error.code ? error.message : 'Atendimento indisponível no momento. Tente novamente.'; }
    finally { busy = false; send.disabled = false; }
    clearInterval(timer); timer = setInterval(refresh, 2000);
  }
  function close() { panel.hidden = true; toggle.setAttribute('aria-expanded', 'false'); clearInterval(timer); }
  toggle.addEventListener('click', () => panel.hidden ? open() : close());
  $('.close').addEventListener('click', close);
  $('.new').addEventListener('click', () => { if (busy) return; session = null; pending = null; save(); log.replaceChildren(); open(); });
  $('.form').addEventListener('submit', async event => {
    event.preventDefault();
    const text = input.value.trim(); if (!text || busy) return;
    busy = true; send.disabled = true;
    if (!pending || pending.texto !== text) pending = {texto: text, id_cliente: crypto.randomUUID ? crypto.randomUUID() : `m_${Date.now()}_${Math.random().toString(36).slice(2)}`};
    try {
      await ensureSession();
      await request(base(), {method: 'POST', headers: {...auth(), 'Content-Type': 'application/json'}, body: JSON.stringify(pending)});
      pending = null; input.value = ''; await refresh();
    } catch (error) { status.textContent = error.code ? error.message : 'Falha de conexão. Clique em Enviar para tentar novamente.'; }
    finally { busy = false; send.disabled = false; input.focus(); }
  });
  input.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('.form').requestSubmit(); } });
})();
