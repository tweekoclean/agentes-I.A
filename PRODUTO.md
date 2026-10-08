# Os três sistemas da AtendeAI

| Sistema | Quem usa | Função |
| --- | --- | --- |
| 1 — Pesquisa | AtendeAI | Encontrar empresas em São Paulo e interior, guardar contatos públicos e preparar oportunidades comerciais. |
| 2 — Comercial | AtendeAI | Apresentar e oferecer o sistema 3 pelo número comercial da AtendeAI e conversar com os contatos aptos à abordagem. |
| 3 — Atendimento | Empresas contratantes | Atender os clientes da própria empresa pelo site/API e WhatsApp, com fatos e histórico separados por empresa. |

A pesquisa não instala o atendimento no negócio encontrado. Os sistemas 1 e 2 são ferramentas internas da AtendeAI. A integração distribuída ao cliente é o sistema 3; o cliente não recebe a chave administrativa que acessa pesquisa, prospecção ou outras empresas.

O sistema 2 envia pela fila após configuração do WhatsApp comercial, aprovação e autorização do contato. Encontrar um telefone público não libera automaticamente o envio. Os trabalhadores processam os envios e as respostas; as permissões existentes continuam sendo verificadas. A operação exige conectar a conta oficial. Um cadastro de oportunidade comercial e um cadastro de cliente de atendimento são entidades separadas.

## Conversa do sistema 3

O assistente usa os fatos cadastrados da empresa e o histórico recente para elaborar suas respostas. Pode orientar a escolha e perguntar detalhes de um pedido ou agendamento. Não afirma que registrou um pedido, cobrou ou confirmou uma reserva sem integração que execute essa operação.

Se não conseguir responder com segurança, pergunta: “Não consegui responder sua solicitação com segurança. Quer que eu chame um responsável?”. A conversa continua no estado `bot`, com `aguardando_confirmacao=true`. “Sim”, “sim”, “ss”, “Ss”, “SS!” e formas equivalentes confirmam o chamado, preservam a dúvida original no resumo e pausam o assistente. A confirmação fica no banco e sobrevive a reinícios. Uma recusa mantém o bot ativo; uma nova pergunta pode continuar o atendimento.

Se o cliente pedir explicitamente para falar com um atendente, essa solicitação já autoriza o encaminhamento. Falhas de conta WhatsApp e janela expirada são pausadas para correção operacional; não é enviada uma confirmação fora da janela permitida.

Ofensas sexuais dirigidas ao assistente, ameaças e insultos reconhecidos pelo filtro são ignorados sem chamada à IA, resposta ou chamado. Mensagens identificadas pela IA como claramente fora do assunto da empresa também não recebem resposta nem abrem chamado. Entradas ignoradas não entram no contexto das respostas seguintes. O filtro distingue ameaças de expressões de negócio, como “quero matar minha fome”. A classificação por IA pode errar; a base e os testes por empresa continuam necessários.
