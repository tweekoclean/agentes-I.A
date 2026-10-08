# Comece por aqui

Esta é a primeira etapa do projeto: encontrar e organizar possíveis clientes para vender atendimento por IA.

O código está pronto para instalar e testar. A API já foi iniciada na Square Cloud; as próximas versões usam o repositório GitHub `tweekoclean/agentes-I.A`, branch `main`. A integração com seu PostgreSQL depende de configurar a conexão e os certificados nas variáveis da hospedagem. O sistema de envio de WhatsApp e o atendimento dos clientes serão construídos nas etapas seguintes.

## O que já funciona

- Busca em 20 municípios de São Paulo capital e interior, com sete segmentos.
- Consulta real ao OpenStreetMap e modo de demonstração com empresas fictícias.
- Cadastro com nome, segmento, cidade, contato público e fonte dos dados.
- Repetição de buscas sem duplicar o mesmo registro da fonte.
- PostgreSQL em produção e SQLite para testar no computador.
- Análise opcional por IA, configurando uma chave da OpenAI.
- Revisão dos resultados e registro de autorização ou revogação para contato comercial.

Um telefone publicado não confirma que a empresa usa WhatsApp e não registra autorização para enviar ofertas.

## Próximo passo recomendado

1. Crie um banco **PostgreSQL**, por exemplo com o nome `atendeai`.
2. Vincule a aplicação Python/web da Square Cloud ao GitHub, usando a branch `main`. O arquivo principal é `main.py`.
3. Nas variáveis da hospedagem, configure `DATABASE_URL`, `ADMIN_API_KEY`, `APP_ENV=development` e `SEARCH_PROVIDER=demo` para o primeiro teste.
4. Prepare os certificados com `certificados_env.py` e importe `.env.certificados.txt` nas variáveis da Square Cloud. Os arquivos privados ficam fora do GitHub. Veja os dois comandos possíveis no `README.md`.
5. Reinicie e abra `/health`, que deve retornar `status: ok`. Depois abra `/docs`, clique em **Authorize** e informe sua `ADMIN_API_KEY`.
6. Use `POST /v1/buscas` para testar uma cidade e os segmentos desejados. Para ativar a busca real, mude `APP_ENV=production` e `SEARCH_PROVIDER=overpass` após configurar o PostgreSQL.

Você ainda não precisa comprar um número para esta etapa. O número e a configuração da Meta entrarão na integração do agente comercial.

Os detalhes de instalação, teste local e hospedagem estão em `README.md`. Cadastre as credenciais nas variáveis da hospedagem ou em um `.env` local. Não é necessário enviar a senha do banco pelo chat.
