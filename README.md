# AtendeAI — pesquisa de empresas, versão 0.1.0

Base da plataforma que terá três módulos:

| Módulo | Função | Estado desta versão |
| --- | --- | --- |
| Agente 1 | Encontrar, organizar e analisar possíveis clientes | Implementado |
| Agente 2 | Apresentar o serviço e acompanhar interessados | Fila preparada; envio e conversa serão implementados depois |
| Agente 3 | Atender clientes das empresas pelo site ou WhatsApp | Etapa posterior |

Os módulos podem usar o mesmo provedor de IA, com instruções e permissões distintas. Não é necessário contratar três modelos diferentes. Esta versão implementa a primeira etapa pedida; não é uma plataforma de atendimento completa.

## Pesquisa e cobertura

Fonte inicial: OpenStreetMap consultado pela API Overpass. Nenhuma chave paga é necessária para testar essa fonte. Há cache por cidade, segmentos, limite e provedor. Chamadas não atendidas pelo cache respeitam um intervalo global registrado no banco; não são disparadas em massa.

O catálogo inicial contém **20 municípios**, com códigos conferidos na API oficial do IBGE: São Paulo, Campinas, Sorocaba, Ribeirão Preto, São José do Rio Preto, Jundiaí, Bauru, Piracicaba, São José dos Campos, Taubaté, Araraquara, Franca, Presidente Prudente, Marília, Americana, Limeira, Indaiatuba, Itu, Botucatu e São Carlos. Litoral e outros estados não são aceitos. Mais municípios podem ser adicionados ao catálogo após verificar o código e a localização.

Sete segmentos: restaurantes, lojas, oficinas, beleza, serviços, academias e hospedagem. São categorias amplas para iniciar a busca, não todos os setores econômicos existentes.

A consulta usa a área do município e seu código IBGE, não o DDD do telefone. Campos publicados que contradizem a cidade ou o estado são rejeitados. O nome da cidade canônico corresponde à área pesquisada mesmo quando o cadastro original não traz `addr:city`.

A cobertura e a atualização dos contatos dependem dos dados disponíveis. A fonte pode devolver menos empresas do que o limite solicitado; telefones e sites podem estar ausentes ou desatualizados. A API não fabrica contatos e não testa se um telefone está ativo no WhatsApp. Revise a fonte antes de usar uma oportunidade.

As instâncias públicas do Overpass têm capacidade compartilhada e não devem sustentar uma plataforma comercial em escala. O endpoint público serve ao piloto com poucas consultas; para produção contínua, configure um provedor adequado ou uma instância própria em `OVERPASS_URL`. O código mantém o cache e o intervalo também com outro endpoint. Um limite configurável no software não elimina os limites do provedor.

## Testar no Windows

Extraia o ZIP e abra o PowerShell na pasta que contém `main.py`. Use Python 3.12 ou superior.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe main.py
```

Abra `http://localhost:8000/docs`. Clique em **Authorize**, informe a chave de teste `local-demo-key-change-me` e confirme.

O modo inicial é `demo`. Os resultados estão marcados como fictícios, não possuem contatos reais e não podem entrar na fila comercial. Abra `POST /v1/buscas`, clique em **Try it out** e use:

```json
{
  "cidade": "Campinas",
  "segmentos": ["restaurantes", "lojas", "oficinas"],
  "limite": 100,
  "usar_cache": true
}
```

Depois, consulte `GET /v1/empresas`. O modo de demonstração produz apenas alguns registros para testar o fluxo; o limite é um teto, não uma promessa de quantidade.

Para pesquisar empresas reais, pare o programa, altere `SEARCH_PROVIDER=overpass` no `.env` e inicie de novo. Os registros de teste continuam identificados; filtre `demonstracao=false` para listar apenas dados reais. Cada busca atual é acionada pela API. Ainda não há agendamento automático diário nesta versão.

## Linux ou macOS

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python main.py
```

## PostgreSQL e Square Cloud

O projeto inclui `squarecloud.app` com `MAIN=main.py`, subdomínio `atendeai-co` e inicialização do Uvicorn na porta 80. O repositório de implantação é [tweekoclean/agentes-I.A](https://github.com/tweekoclean/agentes-I.A), branch `main`. Para um teste local de conexão, use `.env`; na hospedagem, use as variáveis do ambiente.

Configure:

```dotenv
APP_ENV=development
DATABASE_URL=postgresql://USUARIO:SENHA@HOST:PORTA/BANCO
ADMIN_API_KEY=UMA_CHAVE_PROPRIA_COM_PELO_MENOS_32_CARACTERES
SEARCH_PROVIDER=demo
PORT=80
DATABASE_SSL_MODE=verify-ca
```

Copie a URI de conexão fornecida pelo banco para `DATABASE_URL`. Não coloque `https://` antes dela nem use o endereço do painel. Se a senha tiver caracteres especiais, use a URI fornecida pelo provedor ou faça a codificação dos componentes corretamente. Os caminhos `sslkey`, `sslcert` e `sslrootcert` da URI de exemplo do provedor não são necessários quando você configura os certificados pelas variáveis abaixo: o aplicativo fornece os caminhos de execução ao driver.

### Certificados nas variáveis de ambiente

O conteúdo dos certificados e a chave privada ficam nas variáveis da Square Cloud. Base64 permite importar cada arquivo em uma linha; ele não criptografa os segredos. O código não contém certificados reais.

A Square Cloud fornece `certificate.pem` combinado, que pode ser usado nos três campos SSL. Para preparar uma única variável a partir desse arquivo, rode no seu computador, na pasta do projeto com as dependências instaladas:

```powershell
.\.venv\Scripts\python.exe certificados_env.py --pem certificate.pem
```

Se você tem os arquivos separados, use:

```powershell
.\.venv\Scripts\python.exe certificados_env.py --ca ca-certificate.crt --cert certificate.pem --key private-key.key
```

O comando valida o PEM e a correspondência da chave com o certificado, e cria `.env.certificados.txt`, pronto para importar nas variáveis da Square Cloud. Ele recusa sobrescrever arquivos existentes e não imprime as chaves. Importe esse arquivo junto com as variáveis de configuração do banco. Você também pode cadastrar os valores manualmente:

| Variável | Valor |
| --- | --- |
| `DATABASE_SSL_PEM_B64` | Conteúdo completo do PEM combinado, codificado em Base64 |
| `DATABASE_SSL_CA_B64` | Certificado da CA em Base64, para arquivos separados |
| `DATABASE_SSL_CERT_B64` | Certificado do cliente em Base64, para arquivos separados |
| `DATABASE_SSL_KEY_B64` | Chave privada em Base64, para arquivos separados |
| `DATABASE_SSL_MODE` | `verify-ca` (padrão com certificados) ou `verify-full` |

Escolha o PEM combinado ou preencha as três variáveis separadas. Não misture as alternativas. Se uma variável antiga estiver preenchida na Square Cloud, remova seu valor antes de mudar de alternativa. `verify-full` também verifica o nome do servidor, e depende de um certificado correspondente ao host. Uma URL que já exige `verify-full` mantém essa verificação, salvo configuração explícita de `DATABASE_SSL_MODE`.

O driver PostgreSQL precisa ler os arquivos: a aplicação os cria a partir das variáveis em um diretório temporário privado, com permissão 0700 no diretório e 0600 nos arquivos, e remove os arquivos ao encerrar ou falhar na inicialização. `.env.*`, `.pem`, `.crt`, `.key`, `.p12`, `.pfx` e `certs/` estão excluídos do Git e do pacote de implantação. A chave administrativa, a senha e os certificados também são omitidos da representação de `Settings`.

Gere uma chave própria em seu computador:

```powershell
.\.venv\Scripts\python.exe manage.py gerar-chave
```

Na Square Cloud, vincule a aplicação Python/web a este repositório, com branch `main`, arquivo principal `main.py` e o comando `START` do `squarecloud.app`. Mantenha as variáveis de ambiente na hospedagem; elas não são enviadas pelo GitHub. O projeto instala as dependências de `requirements.txt`.

Mantenha `APP_ENV=development` e `SEARCH_PROVIDER=demo` enquanto testa a conexão e os dados fictícios. Depois da conexão confirmada, configure `APP_ENV=production` e `SEARCH_PROVIDER=overpass` para usar os dados reais. Produção exige PostgreSQL e uma chave administrativa própria com pelo menos 32 caracteres.

No primeiro início, a aplicação cria as tabelas que ainda não existem. Ela não remove registros existentes. Produção rejeita SQLite, modo demo e a chave padrão. Alterações futuras do esquema deverão usar migrações; `create_all` não modifica tabelas já criadas.

Após publicar, abra `/health` e depois `/docs`. Toda rota com dados ou ações exige `X-API-Key`. A documentação permite informar essa chave por **Authorize**. Esta chave é administrativa e deve ficar no servidor ou nas ferramentas do operador; não a coloque em um chat JavaScript público de clientes.

Comandos auxiliares:

```bash
python manage.py verificar-banco
python manage.py iniciar-banco
python manage.py gerar-sql
```

`schema-postgresql.sql` também permite conferir as tabelas. Execute esse SQL apenas uma vez em um banco vazio, se optar pela criação manual. A criação automática da aplicação dispensa executar o arquivo manualmente.

Vercel também suporta FastAPI. Este pacote está preparado diretamente para Square Cloud; a implantação na Vercel exigirá configurar o projeto e manter PostgreSQL externo. Rotinas futuras de pesquisa ou envio em segundo plano deverão usar execução durável, em vez de depender de uma tarefa que pode morrer depois da requisição.

## Análise opcional por IA

Configure `OPENAI_API_KEY` e, se desejar, `OPENAI_MODEL`. O modelo inicial é `gpt-4.1-mini`, configurável. Use `POST /v1/empresas/{id}/analise`.

Com a chave, a API chama a Responses API da OpenAI, exige uma saída JSON estruturada e valida a resposta localmente. Envia o nome, cidade, segmento, presença de canais públicos e horários publicados; não envia o número de telefone nem o endereço de email nessa análise. A análise aponta uma hipótese de benefício e perguntas para validar a necessidade. Ela não altera o contato, o consentimento ou a revisão.

Sem chave, o endpoint devolve uma análise simples baseada em regras e marca `modo=regras_sem_ia`. A pesquisa real não depende do modelo. Nenhuma chamada de IA paga é realizada apenas por iniciar a aplicação ou pesquisar uma cidade; cada análise é acionada separadamente.

## Rotas principais

| Rota | Função |
| --- | --- |
| `GET /health` | Verificar conexão com o banco |
| `GET /v1/cidades` | Ver o catálogo de municípios |
| `GET /v1/segmentos` | Ver os segmentos suportados |
| `POST /v1/buscas` | Encontrar e cadastrar empresas |
| `GET /v1/empresas` | Listar, filtrar e paginar resultados |
| `GET /v1/empresas/{id}` | Ver os dados de uma empresa |
| `POST /v1/empresas/{id}/analise` | Analisar os dados coletados |
| `POST /v1/empresas/{id}/revisao` | Aprovar, manter pendente ou descartar uma oportunidade |
| `POST /v1/empresas/{id}/consentimento` | Registrar autorização ou revogação de contato comercial |
| `GET /v1/comercial/fila` | Listar contatos aprovados e autorizados para a próxima etapa |

A deduplicação usa fonte + identificador do cadastro. Isso evita duplicar buscas repetidas e preserva filiais com o mesmo telefone. Objetos diferentes da fonte que representam o mesmo estabelecimento ainda podem exigir revisão manual.

## Preparação do agente comercial

Aprovar uma oportunidade não significa conceder autorização para contato. Uma empresa só aparece na fila quando é um registro real, está aprovada e possui autorização registrada para receber ofertas no número indicado.

O registro administrativo da autorização deve conter uma evidência verificável e a data real. O operador é responsável pela autenticidade da evidência: o software não transforma um texto digitado em consentimento válido. Uma página com telefone público não basta. A autorização pode ser obtida por formulário ou outro fluxo apropriado antes do contato comercial pelo WhatsApp.

Pedidos de interrupção removem o contato da fila. Um evento antigo não reativa uma autorização revogada mais recentemente. A próxima etapa precisará verificar o estado imediatamente antes de cada envio, registrar o resultado de cada mensagem e receber revogações também pelas respostas do WhatsApp.

Não há envio de mensagem nesta versão e nenhum número foi conectado. Para a etapa 2, serão necessários a configuração do WhatsApp Business Platform, um remetente adequado e modelos aprovados quando exigidos. Os limites, custos e regras do WhatsApp continuarão valendo.

## Depois: atendimento por site e WhatsApp

O agente 3 terá configuração e dados separados por empresa contratante. Um chat no site enviará mensagens para sua API; o WhatsApp entregará mensagens por webhook autenticado. O sistema receberá a conversa, verificará a empresa e o cliente, consultará a base de conhecimento e as APIs autorizadas, e responderá no mesmo canal.

Se precisar de uma pessoa, o sistema deverá primeiro registrar e encaminhar o chamado com histórico e resumo. Depois, pode responder: “Estou encaminhando seu chamado para um responsável dar continuidade ao atendimento.” A IA ficará pausada naquela conversa enquanto a equipe assumir. A integração do cliente e o painel dessa etapa ainda não estão implementados.

## Verificação

```bash
python -m unittest discover -s tests -v
```

Os testes usam SQLite em memória, respostas simuladas do provedor e chamadas de IA simuladas. Cobrem autenticação, escopo geográfico, deduplicação, preservação de filiais, cache, consentimento, revogação, eventos antigos, isolamento da decisão de IA, indisponibilidade da fonte e compilação do esquema PostgreSQL. Também verificam Base64, PEM combinado e separado, chave incompatível, permissões dos arquivos, passagem dos parâmetros ao driver e limpeza após falha de inicialização. Os testes que geram certificados efêmeros exigem `openssl` no computador; os demais testes não dependem dele. Eles não enviam mensagens nem cobram uso de IA.

Uma conexão real com seu PostgreSQL deverá ser verificada depois de configurar a URI. O teste do esquema não equivale a testar sua instância de PostgreSQL.

## Fontes e licenças

Dados OpenStreetMap: © OpenStreetMap contributors, sob [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/). A API apresenta a atribuição, a licença e a URL de cada registro. Dados públicos da fonte ficam nas tabelas de pesquisa; evidências de autorização e decisões comerciais são registros operacionais separados. Ao redistribuir uma base derivada dos dados OSM, respeite atribuição e as condições da licença. Os registros de demonstração e os fixtures de teste são fictícios.

Referências consultadas em 8 de outubro de 2026:

- [Catálogo de municípios do IBGE — São Paulo](https://servicodados.ibge.gov.br/api/v1/localidades/estados/35/municipios)
- [Filtro por área no Overpass](https://dev.overpass-api.de/overpass-doc/en/full_data/area.html)
- [Capacidade e uso das instâncias públicas Overpass](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html)
- [Copyright e licença OpenStreetMap](https://www.openstreetmap.org/copyright)
- [FastAPI e bancos relacionais](https://fastapi.tiangolo.com/tutorial/sql-databases/)
- [FastAPI na Square Cloud](https://docs.squarecloud.app/en/tutorials/api/fastapi)
- [PostgreSQL e certificados na Square Cloud](https://help.squarecloud.app/pt-br/article/como-criar-um-banco-postgresql-e-conectar-ma6gn5/)
- [Verificação SSL no PostgreSQL](https://www.postgresql.org/docs/current/libpq-ssl.html)
- [FastAPI na Vercel](https://vercel.com/docs/frameworks/backend/fastapi)
- [OpenAI Docs: saída estruturada](https://developers.openai.com/api/docs/guides/structured-outputs)
- [OpenAI Docs: GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini)
- [Política de mensagens do WhatsApp Business](https://business.whatsapp.com/policy)
