# Assistente de Oportunidades Comerciais EPTV

App Streamlit (Groq) que cruza executivos, meios, clientes e oportunidades.
**Este repositório não contém dados nem chaves de API.**

## Arquivos
- `abrir_app_no_colab.ipynb` — notebook que instala tudo e abre o app com um link público.
- `eptv_app.zip` — código do app (sem nenhum CSV).

## Como usar
1. No Colab, abra `abrir_app_no_colab.ipynb`.
2. Em 🔑 **Secrets**, crie `GROQ_API_KEY` (e, opcional, `ANTHROPIC_API_KEY`) e ative *Acesso ao notebook*.
3. Rode as células; na 2ª, envie `eptv_app.zip`. A 3ª mostra o link do app.
4. No app, aba **🗂️ Dados**, envie seus CSVs em *Substituir enviando um CSV*:
   `oportunidades.csv`, `executivos_meios.csv`, `executivos_clientes.csv`, `historico_propostas.csv`.
   Colunas esperadas:
   - oportunidades: `Oportunidade, Campo/Segmento, Meio associado, Início, Fim`
   - executivos_meios: `Executivo, Meios que trabalha`
   - executivos_clientes: `Executivo, Cliente, Segmento do cliente`
   - historico_propostas: `Cliente, Campo da proposta, Ano, Resultado`
5. Os dados ficam só na sessão do Colab: baixe os CSVs (aba Dados) antes de fechar.

## Publicar no Streamlit Community Cloud
1. Acesse [share.streamlit.io](https://share.streamlit.io) e entre com o GitHub.
2. **Create app** → *Deploy a public app from GitHub*:
   - Repository: `giovanna0622/EPTV_CHATBOT` · Branch: `main`
   - Main file path: `eptv_app/app.py`
3. Em **Advanced settings** → *Secrets*, cole:
   ```toml
   GROQ_API_KEY = "sua-chave-groq"
   APP_PASSWORD = "uma-senha-para-o-time"
   # ANTHROPIC_API_KEY = "opcional"
   ```
4. **Deploy**. Depois, envie os CSVs pela aba **🗂️ Dados**.

Atenção: no Streamlit Cloud os CSVs enviados ficam no servidor e são vistos por todos que acessam o app
(por isso a `APP_PASSWORD`), e somem quando o app reinicia — baixe-os pela aba Dados para guardar.
