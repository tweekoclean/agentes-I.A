# Verificação das versões 0.4 e 0.5

Data: 8 de outubro de 2026 (UTC).

## Confirmação de encaminhamento e escopo na versão 0.5.4

Os sistemas 1 e 2 são ferramentas comerciais internas da AtendeAI; a integração entregue aos negócios é o sistema 3. O serviço de atendimento agora pergunta se o cliente quer chamar um responsável quando não consegue responder, sem abrir chamado antes da aceitação. “Sim”, “ss” e variações de caixa/pontuação são aceitas. Uma recusa mantém o bot e a confirmação sobrevive a reinícios. O resumo do chamado preserva a dúvida anterior à confirmação.

Ofensas dirigidas ao assistente e ameaças reconhecidas são ignoradas sem geração, resposta ou chamado, inclusive quando chegam em sequência antes do processamento. Essas entradas ficam fora do histórico usado pela IA. O modelo também pode classificar mensagens como fora do negócio e ignorá-las. Pedidos e dúvidas da empresa continuam pertinentes; a IA pode coletar dados, sem afirmar registro ou pagamento sem integração.

112 testes automatizados passaram localmente. Os novos casos incluem confirmações, recusa, reinício, silêncio e exclusão do contexto de mensagens abusivas, decisão de ignorar, pergunta sobre regras de encaminhamento e o fluxo de WhatsApp com envios simulados. Não houve envio de WhatsApp real. A versão mantém o mesmo modelo e a escolha automática de CPU da 0.5.3; não altera o esquema do banco.

## Uso da CPU disponível na versão 0.5.3

A versão 0.5.2 publicada respondeu à pergunta de demonstração em 21,4 segundos, contra 40,5 segundos antes dos ajustes. Uma continuação nessa conversa respondeu em 25,6 segundos. As duas respostas usaram o modo `ia`, sem encaminhamento. O diagnóstico detectou quota de quatro núcleos de CPU, mas o modelo continuava limitado a dois threads.

Na comparação local adicional, com o modelo pré-carregado antes de cada medição, dois threads levaram 47,42 segundos e quatro threads 20,11 segundos para a mesma pergunta e o mesmo texto de resposta, com 498 tokens de entrada e 64 de saída em ambos os casos. A carga da máquina varia; esse teste motivou medir também o uso dos quatro núcleos na hospedagem.

A versão 0.5.3 escolhe automaticamente até quatro threads apenas para o modelo gerenciado na mesma máquina, respeitando a quota e afinidade de CPU. Servidores remotos, modo manual e ambientes sem quota identificável mantêm `LOCAL_AI_THREADS`. O pré-carregamento usa a mesma quantidade escolhida pela geração. Não houve alteração de banco, limite comercial ou envio de WhatsApp.

104 testes automatizados passaram localmente, incluindo quotas fracionárias, redução por afinidade de CPU, limite de quatro threads e preservação da configuração manual/remota. O mesmo número de threads é verificado no pré-carregamento e na chamada de geração.

## Redução de latência na versão 0.5.2

O teste anterior à alteração, no chat público da Square Cloud, respondeu em modo `ia` após 40,5 segundos. A versão 0.5.2 pré-carrega o modelo no início, mantém os pesos em memória por 30 minutos após uso, compacta o contexto e reconverte referências curtas para os IDs reais dos documentos da própria empresa. O suporte limita a geração a 256 tokens. Não há cache de respostas prontas; o modelo continua elaborando cada resposta e a validação de contexto, referências e intervenção humana continua ativa.

Na comparação local, com o mesmo `qwen3:4b`, contexto 4096, dois threads e modelo já carregado antes de ambos os casos, a pergunta “Tenho clientes no site e no WhatsApp. Como vocês podem ajudar?” passou de 59,42 para 30,76 segundos. O contexto passou de 760 para 498 tokens e a saída de 106 para 64 tokens; o texto de resposta foi o mesmo. Carregamento prévio separado: 13,68 segundos. As durações variam com a carga da máquina; os tempos locais não substituem medição na hospedagem.

O modelo real também respondeu corretamente sobre uma loja fictícia fechada no sábado às 14h (fecha às 13h), permitiu visita no sábado às 10h e encaminhou a pergunta de preço ausente da base. Esses testes levaram 13,40, 15,96 e 6,05 segundos respectivamente. Não houve chamada à OpenAI ou envio de WhatsApp. O diagnóstico administrativo passa a mostrar contagens e tempos de geração, sem conteúdo de conversas ou credenciais.

102 testes automatizados passaram localmente. Os novos casos verificam pré-carregamento sem mensagem de cliente, referências curtas convertidas apenas para documentos da requisição, ordem estável do contexto, retenção limitada em memória e diagnóstico sem conteúdo privado. Os testes existentes de alteração da base, tomada de atendimento por humano, isolamento entre empresas e ausência de fallback pago continuam passando.

## Correção da demonstração na versão 0.5.1

A demonstração publicada estava com o teto antigo de uma resposta de IA por dia. Depois que a IA local foi ativada, novas perguntas abriram chamados com motivo `limite_ia_diario` antes de chamar o modelo. O cadastro dessa demonstração foi ajustado para 100 respostas por dia, e a conversa mais recente pausada por esse limite foi retomada. O padrão de novas demonstrações agora também é 100; limites individuais escolhidos pelo operador continuam preservados nos reinícios.

Um teste na Square Cloud enviou “Tenho clientes no site e no WhatsApp. Como vocês podem ajudar?” e recebeu resposta no modo `ia`, com a conversa em estado `bot`, sem encaminhamento. A resposta levou aproximadamente 111 segundos nesta hospedagem. O teste comprova geração pelo modelo nesse caso; não comprova atendimento imediato ou capacidade para muitas empresas simultâneas.

97 testes passaram localmente, incluindo uma conversa de demonstração com duas respostas de IA após ativação, sem esgotar o limite na segunda mensagem. A verificação de deploy aceita resposta da base ou da IA local, aguarda a geração e falha caso a pergunta sobre os serviços seja encaminhada. Não houve envio de WhatsApp ou chamada à OpenAI.

## IA local da versão 0.5

96 testes passaram localmente: os 83 testes existentes adaptados ao protocolo local e 13 testes adicionais de limites, isolamento, status privado, contexto, modelos cloud recusados, ausência de fallback pago e instalação do runtime. Sintaxe do painel/widget e geração do esquema PostgreSQL foram verificadas. Não há mudança de esquema nesta versão.

O teste de navegador passou em desktop e celular com banco descartável: login, empresas, base, chamado, resposta humana, retomada, isolamento e chave administrativa apenas na memória.

O Ollama v0.40.1 e os pesos do Qwen3 foram baixados e conferidos por SHA-256. O teste real do modelo 1.7B encontrou uma conclusão incorreta sobre horário; por isso, o padrão escolhido é 4B. Com `qwen3:4b`, contexto de 4096 e dois threads, o agente respondeu que a loja não abre no sábado após as 14h quando a base define fechamento às 13h, permitiu a visita no sábado às 10h e escolheu encaminhar uma pergunta de preço ausente da base. Essas três perguntas não eram mensagens prontas cadastradas.

Neste ambiente, a primeira resposta do 4B levou aproximadamente 44,5 s, incluindo carregamento; as seguintes levaram 13,7 s e 17,5 s. `/api/ps` informou aproximadamente 3036 MiB para o modelo carregado. Esse número não inclui toda a aplicação e não é uma medição de desempenho na Square Cloud. 3082 MB oferece pouca margem; o instalador exige pelo menos 4096 MB para esse modelo. Recomendamos testar consumo e latência na hospedagem antes de expandir.

O modelo ainda pode errar. Saída estruturada e IDs de referência não garantem que toda afirmação esteja correta. Os testes cobrem casos específicos, não uma certificação geral de qualidade. A aplicação mantém encaminhamento humano, limites por empresa e uma inferência por vez. Não houve chamada à OpenAI nem envio real de WhatsApp. A IA publicada só inicia após configurar memória e variáveis na hospedagem; a configuração padrão mantém a IA desabilitada.

## Histórico da versão 0.4

- 83 testes automatizados passaram localmente: 18 da pesquisa/API, 12 da configuração SSL, 27 do agente comercial, 23 do atendimento e 3 do painel/acesso administrativo. A versão anterior, 0.3, teve 79 testes aprovados também no GitHub Actions.
- PEM separado e combinado foram validados com certificados fictícios gerados durante os testes. Chaves incompatíveis e valores Base64 inválidos foram recusados antes da conexão.
- A conversão para variáveis de ambiente, as permissões privadas, a limpeza após falha e a passagem dos parâmetros SSL ao driver foram verificadas.
- Uma busca real de oficinas, restaurantes, beleza e lojas na área de Campinas retornou 100 cadastros do OpenStreetMap.
- Nessa amostra, 22 cadastros têm telefone público normalizado e 14 têm site informado.
- A amostra completa, com URLs das fontes, está em `samples/empresas-campinas.json`.
- As rotas e os modelos da documentação da API foram gerados sem erro.
- O esquema PostgreSQL compilou, incluindo chaves, índices e referências entre tabelas.
- O agente 2 foi verificado com HTTP simulado: rascunho sem envio, revisão obrigatória, configuração desligada, consentimento, geografia, números compartilhados e revalidação antes do envio.
- Recusas, timeouts, respostas sem identificador, processamento interrompido, limite diário no fuso de São Paulo e ausência de repetição automática foram verificados.
- Os testes cobrem assinatura e desafio do webhook, eventos malformados, duplicatas, status fora de ordem e confirmação de entrega recebida antes da resposta HTTP do envio.
- Pedidos de interrupção revogam o consentimento e cancelam pendências; autorização posterior e troca de destinatário foram verificadas.
- Respostas dentro da janela de 24 horas, histórico, encaminhamento com chamado, pausa da IA, atendimento manual e limites de respostas passaram nos testes.
- Chamadas de IA simuladas validaram saída estruturada, isolamento das permissões, encaminhamento após saída inválida e descarte de resposta quando chega uma nova mensagem durante a análise.
- A dependência `tzdata==2026.5` foi instalada no ambiente de teste para disponibilizar o fuso também em sistemas sem base de fusos do sistema operacional.

Os 100 registros são cadastros da fonte pública, não empresas que manifestaram interesse ou autorizaram receber ofertas. A existência e a atualização de cada contato precisam ser revisadas na fonte. A amostra é de Campinas, não uma pesquisa de todo o estado.

A API publicada em `https://atendeai-co.squareweb.app` iniciou com os certificados configurados nas variáveis de ambiente e conectou ao PostgreSQL do projeto. `/health` retornou `status: ok`, e uma busca real de restaurantes de Campinas persistiu 20 cadastros, depois consultados em `GET /v1/empresas`. Esses registros permanecem sem revisão aprovada e sem consentimento comercial.

O fluxo comercial foi testado localmente com SQLite e HTTP simulado. O esquema PostgreSQL compilou; os testes de concorrência em uma instância real de PostgreSQL e a validação do envio/recebimento com número e credenciais reais da Meta ainda dependem dessa configuração. As chamadas de IA foram simuladas; nenhum consumo pago de IA foi realizado. Nenhuma mensagem real de WhatsApp foi enviada.

O agente 3 tem 22 testes de isolamento de empresas/visitantes, base de respostas, limite de uso de IA, webhooks de suporte, interrupção, retomada pelo cliente, encaminhamento humano e demonstração sem IA paga. A suíte completa de 79 testes passou no GitHub Actions em 8 de outubro de 2026, junto da verificação de sintaxe do widget e geração do esquema PostgreSQL. Nenhum número real da Meta foi configurado nesta sessão.

## Painel da versão 0.4

O teste em navegador Chromium passou com empresas fictícias e banco SQLite descartável. O cliente abriu o widget, recebeu uma resposta da base, pediu um humano e recebeu na mesma conversa a resposta enviada pelo painel. O bot continuou pausado até o operador concluir; depois voltou a responder pela base.

Foram verificados login inválido/válido, cadastro de empresa, código de integração, alteração de limites, confirmação/cancelamento de substituição de chave, cadastro/edição/desativação de respostas, separação entre empresas e ausência da chave administrativa em armazenamento persistente ou no código do widget. Textos com marcação HTML foram mostrados como texto sem executar JavaScript.

As telas de login, atendimento e configuração foram conferidas em desktop (1440 px) e celular (390 px), sem rolagem horizontal. Capturas dos testes ficam nos artefatos do workflow Testes AtendeAI. A sintaxe dos dois scripts e a geração do esquema PostgreSQL foram verificadas. O painel não altera o esquema do banco.

A consulta de histórico aceita a origem do Referer quando o GET de mesma origem omite Origin. Token privado, vínculo com a empresa e origem cadastrada continuam obrigatórios; origem inválida, token incorreto e referência malformada foram recusados. O telefone do WhatsApp só é exibido nas rotas do operador.

Nenhuma mensagem real de WhatsApp foi enviada e nenhuma chamada paga de IA foi executada. O teste de navegador usa exclusivamente o servidor descartável de tests/browser_server.py; esse módulo não é importado pelo aplicativo publicado. Integração real com a Meta e contas individuais de operadores/clientes continuam pendentes.
