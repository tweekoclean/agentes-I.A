# Agente AtendeAI com IA local

A versão 0.5 usa um modelo de linguagem aberto em seu servidor. Não faz chamadas à OpenAI, não lê `OPENAI_API_KEY` e não muda automaticamente para um serviço pago se a IA local falhar. Os três agentes usam o mesmo modelo com instruções e permissões próprias.

O agente é da AtendeAI; o modelo base é o Qwen3, de terceiros, executado pelo Ollama. Isso não é treinamento de um modelo do zero. O modelo gera respostas com o histórico e os fatos de cada empresa, em vez de exigir uma frase pronta para cada pergunta. A base de informações continua necessária para conhecer horários, serviços, políticas e demais fatos do negócio.

## Ativar na Square Cloud

1. Aumente a memória da **aplicação AtendeAI** no painel da Square Cloud. Para o modelo padrão `qwen3:4b`, comece o teste com **4096 MB**; **6144 MB** oferece mais margem para o modelo e a API. O `squarecloud.app` está alinhado à escolha de 4096 MB deste projeto. Sua conta precisa ter capacidade livre suficiente para aplicar essa alocação; confirme a memória no painel da hospedagem antes de ativar a IA. Confira a configuração após novos deploys.
2. Importe as variáveis de [variaveis-ia-local.txt](variaveis-ia-local.txt). Acrescente-as às variáveis existentes: mantenha `DATABASE_URL`, `ADMIN_API_KEY` e `DATABASE_SSL_*` já configuradas. Os certificados continuam exclusivamente no ambiente.
3. Reinicie a aplicação. O primeiro início baixa o motor Ollama e o modelo. A API fica disponível durante o download. Pesos e arquivos do motor ficam em `.local-ai/`, fora do Git. A hospedagem precisa permitir acesso ao GitHub Releases e ao registro oficial do Ollama. O motor fixado é v0.40.1, com checksum SHA-256 conferido antes da instalação. Somente arquivos do runtime de CPU são extraídos.
4. Acompanhe os logs até aparecer `IA local pronta: qwen3:4b`. Se houver erro de download, confira a rede e reinicie. Downloads concluídos são reutilizados em reinícios enquanto o diretório de dados for preservado.
5. Abra o painel, clique **Atualizar** e selecione sua empresa. Em **Configuração**, confirme que o modelo aparece pronto, marque **Usar IA local para elaborar respostas** e salve.
6. Em **Base de respostas**, cadastre fatos reais da empresa. Teste perguntas escritas de formas diferentes e uma dúvida que os fatos não respondem. A dúvida desconhecida deve abrir um chamado para uma pessoa. Use o chat da sua empresa; a demonstração pública começa com IA desabilitada, mas o operador pode ativá-la em Configuração.

Diagnóstico autenticado: `GET /v1/ia/status`, com `X-API-Key`. Mostra configuração, download/inicialização e presença do modelo. A consulta não gera texto e não transmite credenciais. Presença do modelo não substitui um teste de conversa. O painel diferencia respostas cadastradas, IA desabilitada, modelo pendente e servidor indisponível.

Desde 0.5.2, o diagnóstico inclui limites de RAM/CPU identificados no contêiner e tempos da última geração: carregamento, leitura do contexto e produção da resposta. São apenas contagens e tempos; não inclui texto de clientes, respostas ou credenciais. Esses valores distinguem demora para carregar o modelo de demora para processar cada pergunta.

O runtime gerenciado pré-carrega o modelo antes de registrar `IA local pronta`. `LOCAL_AI_KEEP_ALIVE_MINUTES=30` mantém os pesos em memória por 30 minutos após o uso (aceita 1 a 1440); muda só a retenção em RAM, sem respostas armazenadas. O suporte envia instruções mais curtas e referências numéricas que o servidor reconverte para os IDs da base, com a mesma validação por empresa. A ordem dos documentos fica estável para aproveitar o cache de contexto do Ollama quando os documentos selecionados são os mesmos.

Desde 0.5.3, `LOCAL_AI_AUTO_THREADS=true` (padrão) ajusta o runtime gerenciado à CPU disponível, com até quatro threads, respeitando a quota e os núcleos acessíveis do contêiner. A Square Cloud publicada informou quatro núcleos e estava usando dois; o modo automático passa a usar os quatro sem exigir outra importação de variáveis. Com quota menor, usa menos threads. Se o limite não puder ser identificado, ou se o modelo estiver em servidor separado, preserva `LOCAL_AI_THREADS=2`. Para fixar a quantidade manualmente, use `LOCAL_AI_AUTO_THREADS=false` e ajuste `LOCAL_AI_THREADS`. Pré-carregamento e geração usam a mesma escolha para não trocar a configuração do modelo entre chamadas.

Se a resposta for encaminhada imediatamente, consulte o motivo do chamado no painel. `limite_ia_diario` indica que o teto de respostas da empresa foi atingido: aumente **Chamadas de IA por dia** em Configuração se houver capacidade. A demonstração nova usa 100 por dia desde a versão 0.5.1; cadastros existentes mantêm as configurações escolhidas pelo operador. Após ajustar, abra **Nova conversa** no chat ou conclua e retome o atendimento pausado. Uma empresa sem itens ativos na base precisa de informações reais cadastradas antes de responder dúvidas sobre o negócio.

## Memória, qualidade e capacidade

O `qwen3:1.7b` quantizado ocupa cerca de 1,4 GB em pesos, segundo o catálogo oficial. O `qwen3:4b` ocupa cerca de 2,5 GB em pesos; precisa de memória adicional para execução, contexto e API. Tamanho do download não é o consumo total de RAM. O código bloqueia o início do modelo gerenciado quando o limite de memória detectado é inferior ao mínimo de teste previsto. A margem e o desempenho precisam ser verificados na hospedagem real.

Com 2560 MB, você pode testar `LOCAL_AI_MODEL=qwen3:1.7b`, mas o modelo menor mostrou erro de interpretação de horário em nossa avaliação e não é o padrão recomendado. Para um teste ainda mais leve, use `LOCAL_AI_MODEL=qwen3:0.6b` (pesos de aproximadamente 523 MB). Modelos pequenos têm menor capacidade de compreender perguntas e seguir instruções. O padrão `qwen3:4b` foi escolhido para melhorar a qualidade; ainda exige revisão dos casos reais do negócio. Não aumente apenas o contexto: ele também usa memória.

O servidor processa **uma inferência por vez**, com um modelo carregado e contexto de 4096 tokens. O suporte gera até 256 tokens por resposta; pesquisa/comercial mantêm o limite geral de 512 (ou o limite inferior configurado em `LOCAL_AI_MAX_TOKENS`). A quantidade de threads segue o modo automático ou a configuração manual descrita acima. `limite_ia_dia` continua por empresa, registrado no PostgreSQL: agora controla uso da máquina, não cobrança de uma API. Não existe capacidade ilimitada: CPU, memória e concorrência determinam quantas empresas o servidor suporta. Meça latência e consumo antes de expandir.

O Ollama escuta somente em `127.0.0.1:11434`; sua porta de gerenciamento não é publicada pela API AtendeAI. `OLLAMA_NO_CLOUD=1` desabilita os recursos de nuvem. Conversas são enviadas somente ao servidor configurado para IA local. Downloads iniciais usam a internet.

## Servidor próprio separado

Se o modelo ficar em uma VPS ou outra máquina, instale Ollama nela e baixe o modelo. Use `AI_PROVIDER=ollama`, `LOCAL_AI_AUTOSTART=false`, `LOCAL_AI_URL=https://SEU-ENDPOINT-PROTEGIDO` e `LOCAL_AI_TOKEN` com a chave de acesso do seu gateway. O gateway precisa aceitar `Authorization: Bearer ...` e encaminhar apenas `/api/chat` e `/api/tags` ao Ollama privado. Não é uma chave de IA paga: serve para proteger seu servidor. Não publique Ollama diretamente sem autenticação. Endpoints remotos HTTP, modelos `cloud` e o serviço ollama.com são rejeitados.

Ollama em seu PC não é o localhost da Square Cloud. Para uso local no PC, rode a API AtendeAI junto com Ollama e use `LOCAL_AI_AUTOSTART=false` e `http://127.0.0.1:11434`.

## Decisões e encaminhamento

A IA de suporte recebe somente fatos da empresa da conversa e histórico dessa conversa. Cada resposta precisa ser JSON válido e citar IDs da base fornecida; IDs de outra empresa são rejeitados. Alterações na base ou entrada de um atendente durante a geração invalidam a resposta pendente. Desde 0.5.4, uma resposta incompleta, falha, excesso de contexto ou dúvida sem fatos solicita confirmação antes de abrir o chamado:

> Não consegui responder sua solicitação com segurança. Quer que eu chame um responsável?

Após “sim”, “ss” ou equivalente, registra o chamado e pausa o bot com a mensagem:

> Estou encaminhando seu chamado para um responsável dar continuidade ao atendimento.

Uma recusa mantém o atendimento automático. Um pedido explícito de atendente já confirma o encaminhamento. Ofensas reconhecidas são ignoradas antes da inferência; a IA pode escolher `ignorar` para assuntos fora do negócio. Nenhuma resposta é publicada nessa decisão e mensagens ignoradas são excluídas do contexto recente. Consulte [PRODUTO.md](PRODUTO.md) para a separação dos três sistemas e o tratamento de pedidos.

Essa validação reduz falhas; não comprova que todo fato gerado é correto. Teste especialmente preços, políticas e exceções antes de oferecer o atendimento às empresas. O modelo não modifica consentimento, telefones, permissões ou configurações, nem confirma ações em sistemas que não foram integrados. A busca de empresas continua usando a fonte cadastrada; a IA não inventa empresas. O envio pelo WhatsApp continua exigindo a conta oficial configurada e as permissões já implementadas.

Referências oficiais: [Qwen3 4b](https://ollama.com/library/qwen3:4b), [Qwen3 1.7b](https://ollama.com/library/qwen3:1.7b), [Qwen3 0.6b](https://ollama.com/library/qwen3:0.6b), [API chat](https://docs.ollama.com/api/chat), [saídas estruturadas](https://docs.ollama.com/capabilities/structured-outputs), [Ollama local e limites de execução](https://docs.ollama.com/faq), [instalação Linux](https://docs.ollama.com/linux), [limites da Square Cloud](https://docs.squarecloud.app/en/platform/limitations-and-restrictions).
