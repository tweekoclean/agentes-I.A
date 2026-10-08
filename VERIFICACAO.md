# Verificação da versão 0.3.0

Data: 8 de outubro de 2026 (UTC).

- 57 testes automatizados passaram em ambiente local: 18 da pesquisa/API, 12 da configuração SSL e 27 do agente comercial.
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

O agente 3 acrescenta 21 testes de isolamento de empresas/visitantes, base de respostas, limite de uso de IA, webhooks de suporte, interrupção, retomada pelo cliente e encaminhamento humano. Eles passaram localmente antes da recuperação do código para o GitHub. A suíte completa de 78 verificações deve passar no workflow Testes AtendeAI antes da publicação desta etapa. O widget também passa por verificação de sintaxe JavaScript. Nenhum número real da Meta está configurado nesta sessão.
