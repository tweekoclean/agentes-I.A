# Agente 2 — WhatsApp comercial

Esta etapa apresenta a proposta da AtendeAI aos contatos autorizados, registra respostas e encaminha interessados ao responsável. O número conectado aqui é o número comercial da AtendeAI. Para conectar números e sites de empresas contratantes, use [AGENTE-3.md](AGENTE-3.md).

## Conferir a implantação

Abra [a documentação da API](https://atendeai-co.squareweb.app/docs), clique em **Authorize** e informe sua `ADMIN_API_KEY`. Execute `GET /v1/comercial/status`. A versão sem credenciais inicia normalmente, mantém a pesquisa disponível e informa as variáveis pendentes. `envio_ativo=false` é esperado antes da configuração.

O deploy cria as cinco novas tabelas comerciais automaticamente, preservando as empresas e os registros de consentimento existentes. Não execute `schema-postgresql.sql` novamente sobre o banco atual; o arquivo completo serve para um banco vazio.

## Configurar o remetente na Meta

Configure um aplicativo com WhatsApp Business Platform/Cloud API e um número remetente. Para o primeiro teste, pode usar o número de teste fornecido pela Meta e um destinatário seu autorizado no painel. Para operação real, conclua a configuração do número comercial e as permissões exigidas para sua conta.

Cadastre estas variáveis na Square Cloud. Mantenha as variáveis atuais de PostgreSQL, certificados e chave administrativa.

| Variável | O que preencher |
| --- | --- |
| `WHATSAPP_TOKEN` | Token da Meta com acesso ao número e permissão de envio; use uma credencial adequada à operação contínua |
| `WHATSAPP_PHONE_NUMBER_ID` | ID numérico do remetente mostrado na configuração da Meta; não é o telefone com DDD |
| `WHATSAPP_APP_SECRET` | Segredo do aplicativo Meta, usado para validar os eventos recebidos |
| `WHATSAPP_VERIFY_TOKEN` | Valor secreto escolhido por você; repita o mesmo valor no cadastro do webhook |
| `WHATSAPP_API_VERSION` | Versão Graph compatível com seu aplicativo; padrão configurável `v24.0` |
| `WHATSAPP_TEMPLATE_NAME` | Nome do template aprovado; padrão `atendeai_apresentacao` |
| `WHATSAPP_TEMPLATE_LANGUAGE` | Idioma do template, inicialmente `pt_BR` |
| `WHATSAPP_ENABLED` | `true` para ativar depois de conferir as credenciais e o template; padrão `false` |
| `COMMERCIAL_AUTO_REPLY` | `true` para respostas automáticas; `false` para registrar as entradas e abrir chamados sem responder |
| `COMMERCIAL_DAILY_LIMIT` | Teto local de tentativas/reservas de abordagem inicial por dia; padrão `100` |
| `COMMERCIAL_MAX_AUTO_REPLIES` | Respostas automáticas por conversa antes de encaminhar; padrão `6` |
| `OPENAI_API_KEY` | Opcional para respostas por IA; sem chave, o sistema usa regras limitadas e encaminha outras dúvidas |
| `OPENAI_MODEL` | Modelo de IA, padrão `gpt-4.1-mini` |

Os segredos ficam no ambiente. Eles não aparecem no status, nas mensagens de erro do cliente Meta nem na representação de `Settings`. Um token temporário pode expirar; uma recusa da Meta fica registrada e não inicia repetição automática.

Configure na Meta a URL de callback:

```text
https://atendeai-co.squareweb.app/webhooks/whatsapp
```

Use o mesmo `WHATSAPP_VERIFY_TOKEN`, assine o campo de eventos `messages` e vincule a conta WhatsApp Business ao aplicativo conforme o fluxo da Meta. O GET devolve o desafio de verificação; o POST exige `X-Hub-Signature-256`, calculado sobre o corpo bruto com o segredo do aplicativo. Eventos de outro `phone_number_id` são ignorados. Reinicie a aplicação após mudar as variáveis.

## Cadastrar o template de apresentação

Crie um template de marketing, idioma português do Brasil, com nome `atendeai_apresentacao` ou o nome que você configurou. Esta versão espera **somente o corpo com um parâmetro de texto**, sem cabeçalho ou botões obrigatórios:

```text
Olá, {{1}}! Aqui é da AtendeAI. Você autorizou nosso contato sobre atendimento por IA para WhatsApp e sites. Posso te apresentar uma demonstração? Se preferir não receber mensagens, responda SAIR.
```

O parâmetro `{{1}}` recebe o nome da empresa. Use um nome fictício como exemplo na configuração da Meta. Aguarde a aprovação do template. Mantenha o texto cadastrado igual ao texto de apresentação deste projeto, para que a prévia e a mensagem enviada correspondam. A API envia o nome do template e o parâmetro; quem guarda o texto do template é a Meta.

## Testar a mensagem sem enviar

Em `POST /v1/comercial/rascunhos`, use o ID de uma empresa obtido por `GET /v1/empresas`:

```json
{"empresa_id": "ID_DA_EMPRESA"}
```

A resposta traz `id`, `texto`, `payload_whatsapp` e `status=rascunho`. Essa ação apenas grava uma prévia, mesmo sem credenciais do WhatsApp. A presença de um telefone público não concede autorização e não confirma que aquele número usa WhatsApp.

Para testar um envio completo, use um destinatário seu ou uma empresa que realmente autorizou receber essa oferta. Registre a revisão da empresa e o consentimento existente pelas rotas administrativas, com o número, evidência verificável e data real. Não registre consentimento para os contatos coletados apenas porque o telefone está público. Os dados fictícios do modo `demo` não podem entrar no envio.

O fluxo de uma abordagem é:

1. `POST /v1/empresas/{empresa_id}/revisao` com `{"status":"aprovada"}`.
2. `POST /v1/empresas/{empresa_id}/consentimento` para registrar uma autorização real já obtida.
3. `POST /v1/comercial/rascunhos` para preparar a mensagem.
4. `POST /v1/comercial/mensagens/{mensagem_id}/revisao` com `{"aprovar":true}`.
5. `POST /v1/comercial/mensagens/{mensagem_id}/enfileirar` para colocar o envio na fila.
6. `GET /v1/comercial/mensagens` para acompanhar o resultado.

**Enfileirar inicia o envio quando o WhatsApp estiver ativo.** O servidor acompanha a fila automaticamente a cada ciclo. `POST /v1/comercial/processar` também processa uma entrada e um envio, útil para diagnóstico. O envio revalida os dados atuais; mudanças de número exigem um novo rascunho e nova revisão.

Uma mesma mensagem não é reenviada por chamadas repetidas da rota. Há uma abordagem inicial por destinatário, inclusive quando duas filiais têm o mesmo número. Esta versão não faz campanhas recorrentes ou follow-ups automáticos. É possível cancelar um envio ainda pendente com `POST /v1/comercial/mensagens/{id}/cancelar`.

## Acompanhar respostas e chamados

Respostas de contatos autorizados são gravadas pelo webhook. O processamento posterior pode responder às dúvidas sobre a proposta. Preço, contrato, demonstração, pedido de pessoa, mídia, limite de respostas ou falha na análise geram um chamado em `GET /v1/comercial/encaminhamentos` e pausam a IA. Quando permitido, o sistema responde:

```text
Estou encaminhando seu contato para um responsável dar continuidade ao atendimento.
```

O chamado fica disponível ao operador pela API, com motivo, última mensagem e acesso ao histórico em `GET /v1/comercial/conversas/{conversa_id}`. Esta versão não notifica um funcionário em outro canal, não agenda demonstrações e não tem painel de atendimento humano. O operador consulta os chamados e atende a pessoa pelo canal apropriado. Só retome a IA depois disso, com `POST /v1/comercial/conversas/{id}/pausa` e `{"pausado":false}`; a retomada resolve os chamados abertos daquela conversa.

Pedidos como `SAIR` revogam a autorização do número, pausam a conversa e cancelam a fila imediatamente após o recebimento. Não é enviado outro texto de confirmação comercial. Para retomar, é preciso registrar uma nova autorização real posterior ao pedido e então reativar a conversa. Um pedido recebido do número antigo não revoga o consentimento de um número diferente.

Contatos sem empresa autorizada são registrados e encaminhados ao operador sem resposta comercial automática. Receber um “oi” não cria autorização para ofertas. Respostas de texto livre exigem uma mensagem recebida nas últimas 24 horas; a condição é verificada também no momento do envio.

## Interpretar o resultado do envio

| Status | Significado e ação |
| --- | --- |
| `rascunho` / `aprovada` | Prévia ainda sem envio |
| `na_fila` | Aguardando processamento ou o próximo dia, se o teto diário foi atingido |
| `aceita` | A Meta devolveu um identificador; ainda não garante entrega |
| `entrega=sent/delivered/read` | Status confirmado por webhook, separado da aceitação inicial |
| `bloqueada` | Revisão, consentimento, número, pausa ou janela não permitiram o envio |
| `falhou` | Recusa do pedido ou falha de entrega comunicada pela Meta; consulte `erro` e `id_whatsapp` |
| `envio_incerto` | Timeout, resposta inconclusiva ou processo interrompido; pode ter havido envio, sem confirmação salva |
| `cancelada` / `descartada` | Mensagem cancelada ou não aprovada |

Não há repetição automática de falhas. Em uma recusa definitiva sem `id_whatsapp`, corrija o motivo, cancele a mensagem e prepare/revise outra manualmente. Uma mensagem aceita pela Meta ou com resultado incerto não libera outra abordagem inicial; confira o resultado com a Meta antes de qualquer ação. Falhas de entrega após a aceitação também não liberam novo envio.

O teto diário é do aplicativo, contado no fuso de São Paulo e persistido no banco antes da chamada externa. Uma reserva pode consumir o teto mesmo se o processo parar antes de chamar a Meta. Os limites e custos da conta Meta continuam independentes. A fila e o histórico sobrevivem ao reinício; um envio interrompido fica incerto, sem reenvio automático.

Referências oficiais:

- [Política do WhatsApp Business](https://business.whatsapp.com/policy)
- [Webhook da WhatsApp Business Platform](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/create-webhook-endpoint/)
- [Exemplo de envio de template — coleção da Meta](https://www.postman.com/meta/whatsapp-business-platform/request/o65u5m5/send-message-template-text)
- [Templates da WhatsApp Business Platform](https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/overview)
