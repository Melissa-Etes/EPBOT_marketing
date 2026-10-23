"""Assistente de Oportunidades Comerciais EPTV — app Streamlit para o time comercial."""
import base64
import datetime as dt
import io
import json
import os
import shutil
import unicodedata
from pathlib import Path

import pandas as pd
import streamlit as st
from groq import Groq

BASE = Path(__file__).parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
SYSTEM_PROMPT = (BASE / "system_prompt.md").read_text(encoding="utf-8")
DETALHES = DATA / "propostas_extraidas.md"

TABELAS = {
    "oportunidades.csv": ["Oportunidade", "Campo/Segmento", "Meio associado", "Início", "Fim"],
    "executivos_meios.csv": ["Executivo", "Meios que trabalha"],
    "executivos_clientes.csv": ["Executivo", "Cliente", "Segmento do cliente"],
    "historico_propostas.csv": ["Cliente", "Campo da proposta", "Ano", "Resultado"],
}
TITULOS = {
    "oportunidades.csv": "Oportunidades",
    "executivos_meios.csv": "Executivos × Meios",
    "executivos_clientes.csv": "Executivos × Clientes",
    "historico_propostas.csv": "Histórico de propostas",
}
PREFERIDOS = ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "qwen/qwen3-32b", "openai/gpt-oss-20b"]
VISION_PREFERIDOS = ["qwen/qwen3.8-27b", "meta-models/muse-spark-open"]
VISION_KEYS = ("vision", "llama-4", "scout", "maverick", "-vl", "pixtral", "qwen3.8", "muse-spark")
CLAUDE_MODEL = "claude-sonnet-5-5"

st.set_page_config(page_title="Oportunidades EPTV", page_icon="📺", layout="wide")

st.markdown(
    """
<style>
#MainMenu, footer {visibility: hidden;}
.block-container {padding-top: 1.5rem; max-width: 1150px;}
.hero {background: linear-gradient(120deg, #0b3d91 0%, #1769e0 55%, #12b5a6 100%);
       color: #fff; padding: 1.6rem 1.8rem; border-radius: 18px; margin-bottom: 1.2rem;}
.hero h1 {margin: 0; font-size: 1.9rem; color: #fff;}
.hero p {margin: .35rem 0 0 0; opacity: .92; font-size: 1.02rem;}
.card {border: 1px solid rgba(128,128,128,.25); border-radius: 14px; padding: 1rem 1.1rem; height: 100%;}
.card h4 {margin: 0 0 .4rem 0;}
.stButton > button {border-radius: 10px; font-weight: 600;}
.stTabs [data-baseweb="tab"] {font-size: 1.05rem; padding: .6rem 1.1rem;}
</style>
<div class="hero"><h1>📺 Assistente de Oportunidades Comerciais</h1>
<p>Descubra quem acionar, com qual cliente e antes de a proposta vencer.</p></div>
""",
    unsafe_allow_html=True,
)


# ---------- utilidades ----------
def segredo(nome):
    try:
        v = st.secrets[nome]
    except Exception:
        v = os.getenv(nome)
    return v or st.session_state.get(f"_{nome}")


# ---------- senha de acesso (opcional, via APP_PASSWORD nos Secrets) ----------
if segredo("APP_PASSWORD") and not st.session_state.get("_liberado"):
    s = st.text_input("Senha de acesso", type="password")
    if s and s == segredo("APP_PASSWORD"):
        st.session_state["_liberado"] = True
        st.rerun()
    if s:
        st.error("Senha incorreta.")
    st.stop()


def chave(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("-", " ").split())


def ler(nome):
    p = DATA / nome
    cols = TABELAS[nome]
    if not p.exists():
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(p, dtype=str, keep_default_na=False, encoding="utf-8-sig", sep=None, engine="python")
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df[cols]


def gravar(nome, df):
    df.to_csv(DATA / nome, index=False, encoding="utf-8")


# ---------- barra lateral: chave e modelos ----------
with st.sidebar:
    st.header("⚙️ Configuração")
    if not segredo("GROQ_API_KEY"):
        k = st.text_input("Chave da Groq", type="password", help="Crie em console.groq.com/keys")
        if k:
            st.session_state["_GROQ_API_KEY"] = k
            st.rerun()
        st.info("Cole a chave da Groq para começar.")
        st.stop()
    st.success("Chave da Groq configurada ✅")
    with st.expander("Avançado"):
        ck = st.text_input("Chave da Anthropic (opcional, melhora a leitura de imagens)", type="password")
        if ck:
            st.session_state["_ANTHROPIC_API_KEY"] = ck

client = Groq(api_key=segredo("GROQ_API_KEY"))


@st.cache_data(ttl=3600, show_spinner=False)
def modelos(_k):
    return sorted(m.id for m in Groq(api_key=_k).models.list().data)


try:
    DISPONIVEIS = modelos(segredo("GROQ_API_KEY"))
except Exception as e:
    st.error(f"Não consegui falar com a Groq: {e}")
    st.stop()

MODEL = next((m for m in PREFERIDOS if m in DISPONIVEIS), None) or next(
    m for m in DISPONIVEIS if not any(k in m for k in ("whisper", "guard", "tts", "orpheus", "safeguard"))
)
VISION_MODEL = next((m for m in VISION_PREFERIDOS if m in DISPONIVEIS), None) or next(
    (m for m in DISPONIVEIS if any(k in m.lower() for k in VISION_KEYS)), None
)
CLAUDE_KEY = segredo("ANTHROPIC_API_KEY")
TEM_OCR = shutil.which("tesseract") is not None
BACKEND = "groq" if VISION_MODEL else ("claude" if CLAUDE_KEY else ("ocr" if TEM_OCR else None))


# ---------- contexto para a IA ----------
def contexto(ref):
    op = ler("oportunidades.csv")
    fim = pd.to_datetime(op["Fim"], format="%d/%m/%Y", errors="coerce")
    op["Dias até o fim"] = ((fim - pd.Timestamp(ref)).dt.days).map(lambda x: "" if pd.isna(x) else str(int(x)))
    partes = [f"## {TITULOS['oportunidades.csv']}\n" + op.to_csv(index=False)]
    for n in ("executivos_meios.csv", "executivos_clientes.csv", "historico_propostas.csv"):
        partes.append(f"## {TITULOS[n]}\n" + ler(n).to_csv(index=False))
    if DETALHES.exists():
        partes.append("## Detalhes das propostas (preços, mercados, bloqueios, regras)\n" + DETALHES.read_text(encoding="utf-8"))
    return "\n\n".join(partes)


def responder(historico, ref):
    system = (f"{SYSTEM_PROMPT}\n\nData de referência atual: {ref:%d/%m/%Y}.\n\n# DOCUMENTOS (base de dados)\n{contexto(ref)}")
    stream = client.chat.completions.create(
        model=MODEL, temperature=0.2, stream=True,
        messages=[{"role": "system", "content": system}] + historico,
    )
    for ch in stream:
        yield ch.choices[0].delta.content or ""


# ---------- leitura de propostas (imagem/PDF) ----------
EXTRACT_PROMPT = """Você extrai dados de um card de oportunidade comercial de mídia (EPTV / Grupo EP).
Leia a imagem e responda SOMENTE com um JSON com estas chaves:
- oportunidade, tipo, meios (lista), mercados (lista), inicio, fim, prazo_comercializacao
- precos: lista de {item, praca, valor} exatamente como no card
- bloqueios_ou_restricoes: lista, ou []
- campo_segmento_explicito: só se estiver escrito no card, senão null
- campo_segmento_sugerido: sua melhor dedução do segmento de anunciante-alvo (ex. Varejo, Automotivo, Esporte)
- observacoes: regras relevantes (descontos, requisitos, público) e suposições que você fez
- linha_csv: {oportunidade, campo_segmento (explícito, senão sugerido), meio_associado (meios separados por vírgula),
  inicio, fim} com datas DD/MM/AAAA. Se o card não informa o ano, use ANO_REF. Se há uma única data
  (evento pontual), use a mesma em inicio e fim. Sem data alguma: deixe vazio.
Use null quando não estiver na imagem. NÃO invente valores nem datas.""".replace("ANO_REF", str(dt.date.today().year))


def _json(txt):
    return json.loads(txt[txt.index("{"): txt.rindex("}") + 1])


def paginas(nome, conteudo):
    if nome.lower().endswith(".pdf"):
        import fitz
        for i, pg in enumerate(fitz.open(stream=conteudo, filetype="pdf")):
            yield f"{Path(nome).stem}_p{i+1}", "image/png", pg.get_pixmap(dpi=110).tobytes("png")
    else:
        mime = "image/png" if nome.lower().endswith(".png") else "image/jpeg"
        yield Path(nome).stem, mime, conteudo


def extrair(mime, dados):
    """Tenta cada leitor disponível em ordem; se um falhar (ex.: limite da Groq), passa para o próximo."""
    ordem = [b for b, ok in (("groq", VISION_MODEL), ("claude", CLAUDE_KEY), ("ocr", TEM_OCR)) if ok]
    erro = None
    for b in ordem:
        try:
            return _extrair(b, mime, dados)
        except Exception as e:
            erro = e
    raise erro


def _extrair(backend, mime, dados):
    b64 = base64.b64encode(dados).decode()
    if backend == "groq":
        # limite gratuito da Groq para este modelo é 1000 tokens de saída por minuto
        r = client.chat.completions.create(
            model=VISION_MODEL, temperature=0, max_tokens=900,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": EXTRACT_PROMPT + " Responda de forma compacta, sem texto fora do JSON."},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]}])
        return _json(r.choices[0].message.content)
    if backend == "claude":
        import anthropic
        r = anthropic.Anthropic(api_key=CLAUDE_KEY).messages.create(
            model=CLAUDE_MODEL, max_tokens=3000,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
                {"type": "text", "text": EXTRACT_PROMPT}]}])
        return _json(r.content[0].text)
    import pytesseract
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(dados)).convert("L")
    im = ImageOps.autocontrast(im.resize((im.width * 2, im.height * 2)))
    texto = pytesseract.image_to_string(im, lang="por", config="--psm 6")
    r = client.chat.completions.create(
        model=MODEL, temperature=0,
        messages=[{"role": "system", "content": EXTRACT_PROMPT + " O texto abaixo veio de OCR e pode ter erros; corrija só o óbvio e use null no resto."},
                  {"role": "user", "content": "TEXTO DO CARD (OCR):\n" + texto}])
    return _json(r.choices[0].message.content)


# ---------- abas ----------
aba_chat, aba_nova, aba_dados = st.tabs(["💬 Perguntar", "➕ Nova proposta", "🗂️ Dados"])

# ===== Perguntar =====
with aba_chat:
    ops = ler("oportunidades.csv")
    c0, c1, c2 = st.columns([1, 1.4, 1.4])
    with c0:
        st.markdown('<div class="card"><h4>📅 Hoje é</h4>', unsafe_allow_html=True)
        ref = st.date_input("Data de referência", dt.date.today(), format="DD/MM/YYYY", label_visibility="collapsed")
        st.markdown("</div>", unsafe_allow_html=True)
    with c1:
        st.markdown('<div class="card"><h4>🎯 Quem devo acionar?</h4>', unsafe_allow_html=True)
        escolha = st.selectbox("Oportunidade", ops["Oportunidade"].tolist() or ["(sem oportunidades)"], label_visibility="collapsed")
        b1 = st.button("Sugerir executivos e clientes", width="stretch")
        st.markdown("</div>", unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="card"><h4>⏰ Perto de vencer</h4>', unsafe_allow_html=True)
        dias = st.slider("Dias", 3, 30, 7, label_visibility="collapsed", help="Quantos dias à frente olhar")
        b2 = st.button(f"Propostas que vencem em {dias} dias", width="stretch")
        st.markdown("</div>", unsafe_allow_html=True)

    st.session_state.setdefault("msgs", [])
    pergunta = None
    if b1:
        pergunta = (f"Quais executivos devo acionar para a oportunidade '{escolha}' e com qual cliente da carteira de cada um? "
                    "Monte a tabela pronta para disparo.")
    if b2:
        pergunta = (f"Hoje é {ref:%d/%m/%Y}. Quais propostas vencem nos próximos {dias} dias (ou já venceram há pouco)? "
                    "Para cada uma, diga quem acionar e com qual cliente.")

    st.write("")
    for m in st.session_state.msgs:
        with st.chat_message(m["role"], avatar="🧑‍💼" if m["role"] == "user" else "📺"):
            st.markdown(m["content"])

    digitada = st.chat_input("Ou escreva sua pergunta aqui… ex.: quais clientes a Mariana atende?")
    pergunta = pergunta or digitada
    if pergunta:
        st.session_state.msgs.append({"role": "user", "content": pergunta})
        with st.chat_message("user", avatar="🧑‍💼"):
            st.markdown(pergunta)
        with st.chat_message("assistant", avatar="📺"):
            try:
                resp = st.write_stream(responder(st.session_state.msgs, ref))
            except Exception as e:
                resp = ("⚠️ Não consegui responder agora. Se for erro de limite da Groq, aguarde um minuto e tente de novo.\n\n"
                        f"`{e}`")
                st.warning(resp)
        st.session_state.msgs.append({"role": "assistant", "content": resp})
    if st.session_state.msgs and st.button("🧹 Nova conversa"):
        st.session_state.msgs = []
        st.rerun()

# ===== Nova proposta =====
with aba_nova:
    st.subheader("Adicionar propostas a partir da imagem do card")
    st.caption("Envie a imagem (JPG/PNG) ou PDF da proposta. A IA lê, você confere e salva. Oportunidades que já existem não são repetidas.")
    if BACKEND is None:
        st.error("Não há leitor de imagem disponível. Na Groq não existe modelo de visão nesta conta; instale o Tesseract "
                 "(OCR) ou informe uma chave da Anthropic em ⚙️ Configuração → Avançado.")
    else:
        nomes = {"groq": f"Groq ({VISION_MODEL})", "claude": "Claude", "ocr": "OCR + Groq"}
        st.caption(f"Leitor em uso: **{nomes[BACKEND]}**")
        ups = st.file_uploader("Cards das propostas", type=["jpg", "jpeg", "png", "pdf"], accept_multiple_files=True)
        if ups and st.button("🔍 Ler propostas", type="primary"):
            res = []
            barra = st.progress(0.0)
            itens = [(u.name, u.getvalue()) for u in ups]
            total = len(itens)
            for i, (n, b) in enumerate(itens):
                try:
                    for nome, mime, dados in paginas(n, b):
                        res.append({"arquivo": nome, "dados": extrair(mime, dados)})
                except Exception as e:
                    st.warning(f"Não consegui ler {n}: {e}")
                barra.progress((i + 1) / total)
            st.session_state["extraidas"] = res

        ext = st.session_state.get("extraidas")
        if ext:
            st.markdown("#### Confira e corrija antes de salvar")
            linhas = []
            for e in ext:
                l = e["dados"].get("linha_csv") or {}
                linhas.append({
                    "Oportunidade": l.get("oportunidade") or e["dados"].get("oportunidade") or "",
                    "Campo/Segmento": l.get("campo_segmento") or "",
                    "Meio associado": l.get("meio_associado") or "",
                    "Início": l.get("inicio") or "", "Fim": l.get("fim") or "",
                })
            editado = st.data_editor(pd.DataFrame(linhas), num_rows="dynamic", width="stretch", key="ed_novas")
            st.caption("💡 O campo/segmento quase nunca aparece no card: o que vem aqui é sugestão da IA. Ajuste se precisar.")
            with st.expander("Ver tudo que a IA leu (preços, mercados, bloqueios, regras)"):
                for e in ext:
                    st.markdown(f"**{e['arquivo']}**")
                    st.json(e["dados"], expanded=False)
            if st.button("💾 Salvar no CSV de oportunidades", type="primary"):
                atual = ler("oportunidades.csv")
                existentes = {chave(x) for x in atual["Oportunidade"]}
                novas, repetidas = [], []
                for _, r in editado.iterrows():
                    nome = str(r["Oportunidade"]).strip()
                    if not nome:
                        continue
                    if chave(nome) in existentes:
                        repetidas.append(nome)
                        continue
                    existentes.add(chave(nome))
                    novas.append(r)
                if novas:
                    gravar("oportunidades.csv", pd.concat([atual, pd.DataFrame(novas)], ignore_index=True))
                    txt = DETALHES.read_text(encoding="utf-8") if DETALHES.exists() else "# Propostas extraídas de imagens (revisar)\n"
                    ja = chave(txt)
                    for e in ext:
                        nome = (e["dados"].get("oportunidade") or e["arquivo"])
                        if chave(nome) not in ja:
                            txt += f"\n\n## {nome}\n```json\n{json.dumps(e['dados'], ensure_ascii=False, indent=1)}\n```"
                    DETALHES.write_text(txt, encoding="utf-8")
                if novas:
                    st.success(f"✅ {len(novas)} oportunidade(s) adicionada(s): " + ", ".join(str(r["Oportunidade"]) for r in novas))
                if repetidas:
                    st.info("Já existiam (não repetidas): " + ", ".join(repetidas))
                if not novas and not repetidas:
                    st.warning("Nada para salvar.")
                st.session_state.pop("extraidas", None)

# ===== Dados =====
with aba_dados:
    st.subheader("Bases de dados")
    st.caption("Edite direto na tabela (adicione linhas pelo + no fim) e clique em Salvar. As mudanças valem para a próxima pergunta.")
    subs = st.tabs([TITULOS[n] for n in TABELAS])
    for sub, nome in zip(subs, TABELAS):
        with sub:
            df = ler(nome)
            ed = st.data_editor(df, num_rows="dynamic", width="stretch", key=f"ed_{nome}")
            c_a, c_b, c_c = st.columns([1, 1, 2])
            if c_a.button("💾 Salvar", key=f"sv_{nome}"):
                gravar(nome, ed)
                st.success("Salvo!")
            c_b.download_button("⬇️ Baixar CSV", ed.to_csv(index=False).encode("utf-8"), file_name=nome, key=f"dl_{nome}")
            up = c_c.file_uploader("Substituir enviando um CSV", type=["csv"], key=f"up_{nome}")
            if up is not None and st.button("Substituir tabela", key=f"rp_{nome}"):
                novo = pd.read_csv(up, dtype=str, keep_default_na=False, encoding="utf-8-sig", sep=None, engine="python")
                faltam = [c for c in TABELAS[nome] if c not in novo.columns]
                if faltam:
                    st.error(f"Faltam as colunas: {', '.join(faltam)}")
                else:
                    gravar(nome, novo[TABELAS[nome]])
                    st.success("Tabela substituída!")
                    st.rerun()
