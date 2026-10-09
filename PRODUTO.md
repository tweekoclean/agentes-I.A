# Nelvo Company: serviços digitais e operação comercial

| Sistema | Quem usa | Função |
| --- | --- | --- |
| 1 — Pesquisa | Operação interna da Nelvo | Encontrar empresas em São Paulo e interior, guardar contatos públicos e preparar oportunidades comerciais. |
| 2 — Comercial | Nelvo Company | Abordagem automatizada atual: apresentar e oferecer o sistema 3 pelo número comercial da Nelvo e conversar com os contatos aptos à abordagem. |
| 3 — Atendimento | Empresas contratantes | Atender os clientes da própria empresa pelo site/API e WhatsApp, com fatos e histórico separados por empresa. |

A Nelvo oferece atendimento com IA, criação de sites, sistemas sob medida e reformulação de sites. A home apresenta essas quatro soluções e direciona para `/aplicar`. O formulário aceita solicitações de todo o Brasil e registra os serviços, a UF, o site atual e o objetivo no funil comercial. O atendimento é o sistema 3; projetos de sites e sistemas possuem acompanhamento comercial próprio, sem criar automaticamente um cadastro de atendimento.

A Nelvo apresenta e vende os serviços. A pesquisa e a abordagem são ferramentas internas; a integração distribuída à empresa contratante é somente o sistema 3. A Nelvo não precisa ser cadastrada como uma empresa cliente para fazer prospecção. O cliente não recebe a chave administrativa que acessa pesquisa, prospecção ou outras empresas.

O sistema 2 envia pela fila após configuração do WhatsApp comercial, aprovação e autorização do contato. Encontrar um telefone público não libera automaticamente o envio. Os trabalhadores processam os envios e as respostas; as permissões existentes continuam sendo verificadas. A operação exige conectar a conta oficial. Um cadastro de oportunidade comercial e um cadastro de cliente de atendimento são entidades separadas.

## Conversa do sistema 3

O assistente usa os fatos cadastrados da empresa e o histórico recente para elaborar suas respostas. Pode orientar a escolha e perguntar detalhes de um pedido ou agendamento. Não afirma que registrou um pedido, cobrou ou confirmou uma reserva sem integração que execute essa operação.

Se não conseguir responder com segurança, pergunta: “Não consegui responder sua solicitação com segurança. Quer que eu chame um responsável?”. A conversa continua no estado `bot`, com `aguardando_confirmacao=true`. “Sim”, “sim”, “ss”, “Ss”, “SS!” e formas equivalentes confirmam o chamado, preservam a dúvida original no resumo e pausam o assistente. A confirmação fica no banco e sobrevive a reinícios. Uma recusa mantém o bot ativo; uma nova pergunta pode continuar o atendimento.

Se o cliente pedir explicitamente para falar com um atendente, essa solicitação já autoriza o encaminhamento. Falhas de conta WhatsApp e janela expirada são pausadas para correção operacional; não é enviada uma confirmação fora da janela permitida.

Uma pergunta reconhecível sobre os serviços da empresa que o modelo classifica indevidamente como assunto externo passa a oferecer um responsável. A categoria de abuso é separada para preservar o silêncio em mensagens maliciosas, mesmo quando mencionam o negócio.

Ofensas sexuais dirigidas ao assistente, ameaças e insultos reconhecidos pelo filtro são ignorados sem chamada à IA, resposta ou chamado. Um filtro de assunto também reconhece perguntas gerais de geografia, política, esporte, entretenimento e cálculos isolados. Ele considera a base da empresa e solicitações comerciais antes de bloquear: uma entrega na capital ou uma dúvida de matemática para uma escola continuam pertinentes. Os demais assuntos são classificados pelo modelo; mensagens identificadas como claramente fora do negócio não recebem resposta nem abrem chamado. Entradas ignoradas não entram no contexto das respostas seguintes. O filtro distingue ameaças de expressões de negócio, como “quero matar minha fome”. A classificação por IA pode errar; a base e os testes por empresa continuam necessários.
