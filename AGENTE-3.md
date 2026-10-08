# Agente 3 — atendimento por empresa

O atendimento usa a API da AtendeAI no seu servidor, com um chat incorporável para sites e o WhatsApp oficial de cada empresa. A base e o histórico de uma empresa ficam separados dos demais. As rotas administrativas exigem a chave administrativa; visitantes recebem um token para sua própria conversa.

## Cadastrar uma empresa e suas respostas

Em [/docs](https://atendeai-co.squareweb.app/docs), faça **Authorize** com sua ADMIN_API_KEY e execute `POST /v1/atendimento/empresas`:

```json
{
  "nome": "Nome da empresa",
  "origens_permitidas": ["https://www.site-da-empresa.com", "https://atendeai-co.squareweb.app"],
  "boas_vindas": "Olá! Sou o assistente virtual da empresa. Como posso ajudar?",
  "ia_habilitada": false,
  "limite_conversas_dia": 100,
  "limite_ia_dia": 100
}
```

Cadastre origens completas, sem caminho. Domínio com/sem www são distintos. HTTP é aceito somente em localhost/127.0.0.1. Guarde o id da empresa e a chave_site. A chave do site é pública no código incorporado e identifica a configuração; ela não concede acesso administrativo ou ao histórico de outros visitantes. A listagem não devolve a chave original; use a rota /chave-site para substituí-la.

Empresas contratantes e oportunidades da pesquisa são cadastros separados. Uma aprovação comercial não cria automaticamente um cliente de atendimento.

Adicione respostas reais pela rota `POST /v1/atendimento/empresas/{empresa_id}/base`:

```json
{"titulo":"Horário de atendimento","conteudo":"Atendemos de segunda a sexta, das 9h às 18h, no horário de São Paulo.","ativa":true}
```

Use itens curtos, com fatos reais da empresa, até 2.000 caracteres. GET lista e PUT atualiza/desativa os itens. Sem IA, perguntas com correspondência na base recebem o texto cadastrado; as demais abrem um chamado. A busca considera até 100 itens ativos. Com IA local, prioriza os itens da pergunta e completa o contexto com até cinco itens da própria empresa. Inclui documentos inteiros que cabem no contexto, sem cortar exceções. Ainda não há busca vetorial de grandes documentos, upload de PDFs nem consulta a sistemas de pedidos.

Para ativar a IA, configure o modelo local conforme [IA-LOCAL.md](IA-LOCAL.md) e use PATCH da empresa com `{"ia_habilitada":true}` ou marque o uso de IA no painel. As chamadas enviam a mensagem, até quatro mensagens recentes de contexto e somente fatos da própria empresa ao seu servidor local. Mensagens antigas podem ser removidas para caber no contexto. Tokens da conversa e credenciais do WhatsApp não entram na chamada. A base é fornecida como contexto, sem treinamento do modelo.

O limite diário de IA é reservado no banco antes da chamada, no fuso de São Paulo. Falhas podem consumir a reserva. Ao atingir o teto, o sistema abre um chamado. PATCH também permite alterar limites, origens, boas-vindas ou desativar a empresa.

## Incorporar o chat

Inclua antes de fechar o body, substituindo os dois valores:

```html
<script src="https://atendeai-co.squareweb.app/widget/atendeai.js"
        data-empresa="ID_DA_EMPRESA" data-chave="CHAVE_SITE" defer></script>
```

O botão Atendimento abre a conversa. O widget usa a chave pública para criar a sessão e um token privado por conversa para consultar/enviar mensagens. O token fica no sessionStorage da aba quando disponível. ADMIN_API_KEY nunca deve entrar no widget.

Para a página de teste, cadastre a origem https://atendeai-co.squareweb.app e abra:

```text
https://atendeai-co.squareweb.app/teste-atendimento?empresa=ID_DA_EMPRESA&chave=CHAVE_SITE
```

Teste “qual o horário de atendimento?” e “quero falar com um atendente”. O servidor precisa estar na versão 0.3.

Se o site usa CSP, permita o domínio da API em script-src e connect-src conforme sua configuração. O widget usa Shadow DOM e insere textos com textContent.

## Usar a API diretamente

1. POST /v1/atendimento/site/{empresa_id}/conversas com X-Site-Key e a origem cadastrada. Recebe ID e token_conversa.
2. POST /v1/atendimento/site/{empresa_id}/conversas/{conversa_id}/mensagens com Authorization: Bearer TOKEN_CONVERSA e `{"texto":"Minha dúvida","id_cliente":"identificador-unico"}`.
3. GET da mesma rota para consultar histórico e estado bot/humano/interrompida.

O navegador envia Origin em POST e consultas entre origens. No GET de histórico de mesma origem, a API usa a origem do Referer quando Origin não é enviado; o token privado continua obrigatório. A página de teste envia apenas a origem como referência. Em testes por cliente HTTP/backend, informe a origem cadastrada. Reutilize id_cliente ao repetir uma tentativa com o mesmo texto: a API grava uma entrada. Reutilizar o ID com outro texto é recusado.

O POST grava na fila e o worker responde depois. O widget consulta a cada dois segundos enquanto aberto; o tempo depende da fila e do provedor. Há até 50 entradas por conversa de site, além do teto diário de novas conversas. Chave pública e origem identificam a configuração; os limites também são aplicados no banco.

## Atendimento humano

Abra [o painel do operador](https://atendeai-co.squareweb.app/painel) e informe sua `ADMIN_API_KEY`. Selecione a empresa, abra **Atendimento** e clique no chamado. O histórico aparece ao lado da fila. **Assumir atendimento** pausa o bot; enviar uma resposta também mantém o bot pausado. A resposta é registrada na mesma conversa do cliente. Depois de concluir o pedido, use **Concluir e retomar automático**.

A chave administrativa fica apenas em memória e precisa ser informada novamente após recarregar ou sair. O painel não deve ser distribuído com essa chave aos clientes: ela concede acesso a todas as empresas. A versão atual tem um operador administrativo; não há contas individuais ou permissões por funcionário. Base e configuração podem ser gerenciadas pelo painel sem executar rotas manualmente.

GET /v1/atendimento/empresas/{id}/chamados lista a fila. O histórico completo está em /conversas/{conversa_id}. O sistema grava o chamado e pausa o bot antes de registrar a frase de encaminhamento.

O operador responde por `POST /v1/atendimento/empresas/{id}/conversas/{conversa_id}/responder`:

```json
{"texto":"Olá, aqui é o responsável. Vou verificar sua solicitação."}
```

A resposta aparece na mesma sessão de site ou entra na fila do WhatsApp correspondente. A IA continua pausada. Após concluir, envie /pausa com `{"pausado":false}` para resolver os chamados abertos e retomar o bot. Com true, o operador assume e cancela respostas automáticas pendentes.

O painel acompanha a fila automaticamente enquanto a aba está aberta e visível. Não há notificação externa por email nesta versão. Pedido de pessoa, mídia, ausência de resposta, falha da IA, base alterada durante a resposta e limite de automação geram chamados. A API não altera pedidos, cobra pagamentos ou executa ações em sistemas externos.

## WhatsApp de cada empresa

Cada empresa precisa de uma conta/número oficial autorizada para a integração. As credenciais ficam no ambiente da Square Cloud, em SUPPORT_WHATSAPP_ACCOUNTS_JSON, uma linha JSON. Exemplo de estrutura, com valores substituíveis:

```json
{"ID_REAL_DA_EMPRESA":{"enabled":true,"token":"TOKEN_META","phone_number_id":"ID_NUMERICO_META","app_secret":"SEGREDO_APP","verify_token":"VALOR_PARA_WEBHOOK","api_version":"v24.0"}}
```

Use o ID real retornado pelo cadastro e o ID numérico real do remetente. O exemplo não está pronto para importar. Uma conta incompleta deve ficar enabled=false. Não reutilize o mesmo número em duas empresas ou no comercial. WHATSAPP_* continua reservado ao agente 2. Tokens não são salvos no código ou na tabela de empresas.

Cadastre na Meta:

```text
https://atendeai-co.squareweb.app/webhooks/atendimento/whatsapp/ID_DA_EMPRESA
```

Repita verify_token, habilite eventos messages e vincule a conta ao aplicativo conforme o fluxo da Meta. O servidor verifica HMAC do corpo e phone_number_id. Reinicie após alterar o ambiente. Para várias contas no mesmo aplicativo Meta, valide os callbacks/subscrições no provedor; esta versão oferece uma URL por empresa, sem Embedded Signup ou roteador único para várias contas.

O cliente inicia o pedido de suporte. Este canal não faz abordagem comercial. Respostas livres, inclusive humanas, exigem a janela de 24 horas. Fora da janela, o chamado fica salvo e não há envio livre. Aceitação e entrega são registradas separadamente; falhas incertas não são reenviadas automaticamente.

SAIR interrompe a conversa e cancela textos pendentes. Um “oi” posterior não reativa o bot. O próprio cliente pode pedir “retomar”, “reiniciar atendimento” ou “quero atendimento novamente” depois da interrupção. Isso retoma o suporte e não concede consentimento comercial no agente 2.

## Banco e implantação

O deploy cria seis novas tabelas sem modificar as existentes. PostgreSQL, certificados e chave administrativa continuam no ambiente. Não execute o SQL completo no banco atual: create_all cria o que falta. O SQL completo é para um banco vazio.

Referências: [política WhatsApp Business](https://business.whatsapp.com/policy), [webhooks da Meta](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/create-webhook-endpoint/) e [saída estruturada local](https://docs.ollama.com/capabilities/structured-outputs).

## Demonstração pronta

Abra [a demonstração](https://atendeai-co.squareweb.app/demonstracao). Ela usa um cadastro separado chamado AtendeAI — Demonstração, com respostas por regras/base, sem ativação de IA paga ou conta WhatsApp. Pergunte “quais serviços vocês oferecem?” e depois “quero falar com um atendente”. O segundo pedido cria um chamado real na fila dessa empresa de teste e pausa o bot. Use as rotas administrativas da empresa 00000000-0000-4000-a000-000000000003 para consultar/responder.

SUPPORT_DEMO_ENABLED=false desativa a página e a criação inicial da demonstração. A inicialização preserva alterações anteriores e não duplica a empresa/base. Desative também a empresa pela API se desejar bloquear sessões já abertas. O teto padrão é de 100 novas conversas por dia para a demonstração.

## IA local sem OpenAI

A versão 0.5 usa Qwen3 por Ollama, hospedado por você. A ativação e os recursos necessários estão em [IA-LOCAL.md](IA-LOCAL.md). Sem modelo habilitado, a base usa o modo `base_sem_ia`. Com IA local habilitada para a empresa, o modelo elabora respostas a partir dos fatos e histórico; a transferência para o responsável continua salva no banco.
