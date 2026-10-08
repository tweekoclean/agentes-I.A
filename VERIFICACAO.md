# Verificação da versão 0.1.0

Data: 8 de outubro de 2026 (UTC).

- 30 testes automatizados passaram em ambiente local, incluindo os 18 testes da API e 12 testes da configuração SSL.
- PEM separado e combinado foram validados com certificados fictícios gerados durante os testes. Chaves incompatíveis e valores Base64 inválidos foram recusados antes da conexão.
- A conversão para variáveis de ambiente, as permissões privadas, a limpeza após falha e a passagem dos parâmetros SSL ao driver foram verificadas.
- Uma busca real de oficinas, restaurantes, beleza e lojas na área de Campinas retornou 100 cadastros do OpenStreetMap.
- Nessa amostra, 22 cadastros têm telefone público normalizado e 14 têm site informado.
- A amostra completa, com URLs das fontes, está em `samples/empresas-campinas.json`.
- As rotas e os modelos da documentação da API foram gerados sem erro.
- O esquema PostgreSQL compilou, incluindo chaves, índices e referências entre tabelas.

Os 100 registros são cadastros da fonte pública, não empresas que manifestaram interesse ou autorizaram receber ofertas. A existência e a atualização de cada contato precisam ser revisadas na fonte. A amostra é de Campinas, não uma pesquisa de todo o estado.

Ainda não foi verificada uma conexão com uma instância real de PostgreSQL do usuário; seus certificados e URI ainda não foram fornecidos ou configurados nesta sessão. As chamadas de análise por IA foram simuladas nos testes; nenhum consumo pago de IA foi realizado. A versão anterior da API foi iniciada pelo usuário na Square Cloud, com `/health` retornando `status: ok`. Nenhuma mensagem de WhatsApp foi enviada.
