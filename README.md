# BetManager Professional — Auto Paste

Fluxo principal: **Ctrl+V do print → OCR automático → ficha editável → Salvar aposta**.

## Recursos
- Cola print via Ctrl+V e inicia OCR automaticamente, sem botão "Analisar"
- Upload de imagem como alternativa, também com leitura automática
- Preview do print ao lado da ficha
- Campos editáveis antes de salvar
- Stake padrão 1u; valor em R$ é apenas informativo
- Resultado: PENDENTE, WIN, HALF WIN, VOID, HALF LOSS e LOSS
- Cálculo correto do lucro em unidades
- Dashboard, filtros, edição, exclusão, relatórios e exportação
- Todos os usuários em perfil ADMIN
- SQLite local para teste e PostgreSQL para uso compartilhado

## Teste local
1. Extraia o ZIP.
2. Execute `INICIAR.bat` no Windows.
3. Abra **Importar aposta**.
4. Copie um print para a área de transferência e pressione **Ctrl+V** na área de colagem.
5. Aguarde a ficha aparecer automaticamente.
6. Confira/corrija os dados e clique em **Salvar aposta**.

O OCR depende da qualidade e do layout do print, por isso a ficha sempre fica editável antes do salvamento.


## API-Football
No Streamlit Cloud > App settings > Secrets, adicione:

API_FOOTBALL_KEY = "SUA_CHAVE"

O sistema usa o OCR primeiro. Se conseguir identificar os dois times, consulta a API-Football para confirmar o jogo, normalizar os nomes e preencher o campeonato automaticamente.

## Disparador Telegram
Nos Secrets do Streamlit, configure:
```toml
TELEGRAM_BOT_TOKEN = "token_do_bot"
TELEGRAM_CHAT_ID = "-100xxxxxxxxxx"
```
Ao cadastrar a aposta, informe o horário do jogo e mantenha **Avisar 10 min antes** marcado. No menu **📣 Disparador Telegram**, escolha a aposta e clique em **Disparar aposta no Telegram**.

> Importante: o lembrete é executado pelo processo do app. Em hospedagens que colocam o app para dormir, como pode ocorrer no Streamlit Community Cloud, não há garantia de execução enquanto o processo estiver suspenso. Para operação 24/7, hospede o app/worker em um serviço que permaneça ativo.
