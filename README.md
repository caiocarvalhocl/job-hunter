# Job Hunter

Pipeline automatizado de busca de vagas. Ele varre vários job boards de tempos
em tempos, pontua cada vaga contra o seu perfil usando uma LLM, e manda as que
passam do corte para o seu Telegram. Para as vagas boas, você gera CV adaptado
e cover letter em DOCX com um comando no próprio chat.

Cada pessoa roda a própria instância: seu bot, seu perfil, seu banco de dados,
na sua máquina. Não existe servidor central nem conta compartilhada.

```
scrapers/*  ──►  filtro de palavra-chave  ──►  filtro de senioridade
    │                                                   │
    ▼                                                   ▼
 RawJob                                    filtros de local / trilha / PCD
                                                        │
                                                        ▼
                                              score de fit (LLM)
                                                        │
                            ┌───────────────────────────┤
                            ▼                           ▼
                  score < MIN_FIT_SCORE       score ≥ MIN_FIT_SCORE
                   salvo como "ignored"        Telegram + SQLite
                                                        │
                                              /cv /cover /docs (sob demanda)
```

---

## 1. Requisitos

**Python 3.12.** Não use 3.13 nem 3.14: os pacotes nativos usados aqui (lxml,
pydantic) ainda não compilam nessas versões. Confira com `python --version`.

Você também vai precisar de duas contas gratuitas:

| O quê | Onde | Para quê |
|---|---|---|
| Chave da API Groq | [console.groq.com](https://console.groq.com) | pontuar as vagas e gerar os documentos |
| Bot do Telegram | [@BotFather](https://t.me/BotFather) | receber as vagas e rodar os comandos |

Opcionalmente, uma chave da Anthropic serve de fallback quando a Groq atinge
rate limit. Sem ela o pipeline funciona, só espera a próxima janela.

---

## 2. Instalação

```bash
git clone <url-do-seu-repositorio>
cd job-hunter

rm -rf venv
python3.12 -m venv venv

source venv/bin/activate          # Linux / macOS
# source venv/Scripts/activate    # Windows com Git Bash
# venv\Scripts\activate           # Windows com PowerShell ou CMD

pip install -r requirements.txt
```

---

## 3. Criar seu bot no Telegram

Fale com o [@BotFather](https://t.me/BotFather), mande `/newbot` e siga as
instruções. No final ele devolve um token no formato `123456789:AAF...`, que é
o seu `TELEGRAM_BOT_TOKEN`.

Para descobrir seu `TELEGRAM_CHAT_ID`, mande qualquer mensagem para o bot que
você acabou de criar e depois abra no navegador:

```
https://api.telegram.org/bot<SEU_TOKEN>/getUpdates
```

O número em `"chat":{"id": ...}` é o seu chat id. Só mensagens vindas desse id
são processadas; qualquer outra pessoa que encontrar seu bot é ignorada.

---

## 4. Configurar o `.env`

```bash
cp .env.example .env
```

Abra o `.env` e preencha. As três primeiras são obrigatórias, o resto tem
padrão razoável:

| Variável | O que faz |
|---|---|
| `GROQ_API_KEY` | sua chave da Groq |
| `TELEGRAM_BOT_TOKEN` | token do passo 3 |
| `TELEGRAM_CHAT_ID` | seu chat id do passo 3 |
| `ANTHROPIC_API_KEY` | opcional, fallback quando a Groq limita |
| `SEARCH_KEYWORDS` | palavras-chave da sua busca, separadas por vírgula |
| `SEARCH_LOCATION` | região de referência da busca |
| `SEARCH_REMOTE_ONLY` | `true` para só remoto |
| `MIN_FIT_SCORE` | score mínimo para notificar (padrão 60) |
| `MIN_CV_SCORE` | score a partir do qual vale a pena gerar CV (padrão 80) |
| `ACCEPT_PLENO` | `true` se você também aceita vaga de pleno |
| `ALLOW_ONSITE_IN_REGION` | aceita presencial/híbrido nas cidades abaixo |
| `LOCAL_REGION_CITIES` | suas cidades aceitáveis para presencial |
| `TRACK_RULES` | política geográfica por tipo de vaga (ver abaixo) |
| `EXCLUDE_PCD_RESERVED` | `true` exclui vagas afirmativas para PCD |
| `SCRAPE_INTERVAL_HOURS` | de quantas em quantas horas varrer (padrão 6) |
| `DATABASE_URL` | padrão `sqlite:///./job_hunter.db`, não precisa mexer |

### `TRACK_RULES`, a política por tipo de vaga

Cada vaga é classificada em uma trilha (`dev`, `qa` ou `support`) e cada trilha
tem uma regra de onde você aceita. As regras são `anywhere` (qualquer lugar),
`abroad_only` (só fora do Brasil) e `domestic_only` (só no Brasil). Trilha que
você não listar cai em `anywhere`.

```bash
# Padrão: dev em qualquer lugar, QA e suporte só no exterior
TRACK_RULES=dev:anywhere,qa:abroad_only,support:abroad_only

# Aceita tudo, em qualquer lugar
TRACK_RULES=dev:anywhere,qa:anywhere,support:anywhere

# Só quer dev, e só no Brasil
TRACK_RULES=dev:domestic_only,qa:abroad_only,support:abroad_only
```

Vaga cuja trilha não foi identificada sempre passa, para não descartar por
engano um dev classificado errado. A IA decide depois.

---

## 5. Montar seu perfil

```bash
cp data/master_profile.example.yaml data/master_profile.yaml
```

Preencha com seus dados reais. Esse arquivo é a **única** fonte de fatos sobre
você: a LLM só seleciona e reordena o que estiver lá, nunca inventa experiência
ou tecnologia que não esteja escrita. Se uma skill não aparece no CV gerado,
provavelmente ela não está no YAML.

Cada campo de texto é bilíngue (`pt` e `en`), porque o gerador escolhe o idioma
conforme a vaga. Preencha os dois mesmo quando parecer repetitivo.

O `data/master_profile.yaml` está no `.gitignore`, já que tem telefone, e-mail e
endereço. Se o seu repositório for privado e você quiser versionar o perfil como
backup, apague aquela linha do `.gitignore`.

---

## 6. Rodar

O jeito recomendado, tudo num terminal só:

```bash
python run_all.py
```

Isso sobe o scheduler e o bot no mesmo processo. Ele faz uma primeira varredura
imediatamente (em segundo plano, então o bot já responde comandos enquanto isso)
e depois repete a cada `SCRAPE_INTERVAL_HOURS`. `Ctrl+C` encerra os dois.

Os modos separados continuam existindo, para quando você quiser só uma parte:

```bash
python main.py          # uma varredura só, e sai
python scheduler.py     # só o scraping agendado, sem bot
python bot.py           # só o bot, sem scraping automático
```

**Não rode `run_all.py` e `bot.py` ao mesmo tempo.** Dois long pollings com o
mesmo token fazem a API do Telegram devolver 409 Conflict e os dois processos
passam a perder mensagens.

Para deixar rodando depois de fechar o terminal, no Linux, a forma mais simples
é um serviço de usuário do systemd:

```ini
# ~/.config/systemd/user/job-hunter.service
[Unit]
Description=Job Hunter
After=network-online.target

[Service]
WorkingDirectory=%h/job-hunter
ExecStart=%h/job-hunter/venv/bin/python run_all.py
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now job-hunter
systemctl --user status job-hunter
journalctl --user -u job-hunter -f      # acompanhar os logs
```

---

## 7. Usando o bot

Depois que o processo está de pé, tudo acontece no chat do Telegram. Mande
`/ajuda` a qualquer momento para ver a lista.

### Receber vagas

Não precisa fazer nada. A cada varredura, as vagas que passam do
`MIN_FIT_SCORE` chegam sozinhas, com título, empresa, se é remoto, o score de
fit, um resumo do porquê, o link e os comandos prontos para gerar documentos.

### Adicionar uma vaga na mão

Útil para LinkedIn, que não tem API pública de busca, ou para qualquer vaga que
alguém te mandou:

```
/vaga https://www.linkedin.com/jobs/view/123456789
```

Sem mais nada, o bot busca aquela URL uma única vez, extrai a descrição,
pontua e salva. Se a página estiver atrás de login e a extração falhar, mande
de novo colando o texto da vaga numa linha abaixo da URL:

```
/vaga https://www.linkedin.com/jobs/view/123456789
Estamos buscando uma pessoa desenvolvedora backend para...
(cole aqui o texto completo da vaga)
```

Assim o bot usa o texto colado, sem nenhum acesso automatizado à página.

Vaga adicionada manualmente pula os filtros de nível e de trilha, porque você
já decidiu que quer aquela vaga. O bot avisa se ela estaria fora da sua
política, mas salva mesmo assim.

### Listar as vagas salvas

```
/lista
```

Mostra as candidatas com o id curto de cada uma, o score, e ícones indicando se
já tem cover letter (📄) ou CV adaptado (🎯) gerado.

### Gerar os documentos

Os documentos não são gerados automaticamente, para economizar cota da LLM.
Peça quando quiser, usando o id que veio na notificação ou no `/lista`:

```
/cv a1b2c3d4        # CV adaptado para aquela vaga
/cover a1b2c3d4     # cover letter
/docs a1b2c3d4      # os dois
```

O idioma é detectado pela vaga. Para forçar, acrescente `pt` ou `en`:

```
/cv a1b2c3d4 en
```

Os arquivos chegam como DOCX no próprio chat. `/carta` e `/resume` são atalhos
para `/cover`.

### Todos os comandos

| Comando | O que faz |
|---|---|
| `/ajuda` | lista os comandos |
| `/vaga <url>` | adiciona uma vaga manualmente |
| `/lista` | mostra as vagas salvas com seus ids |
| `/cv <id> [pt\|en]` | gera e envia o CV adaptado |
| `/cover <id> [pt\|en]` | gera e envia a cover letter |
| `/docs <id> [pt\|en]` | gera e envia os dois |

Pelo terminal, `python generate.py <id> [--cv] [--cover] [--lang pt|en]` faz o
mesmo, para quem preferir.

---

## 8. Testes

```bash
pip install -r requirements-dev.txt
pytest
```

A suíte roda inteiramente offline: nenhuma chamada de rede, nenhuma chamada
real de LLM, nenhuma chave necessária. Ela cobre o casamento de palavras-chave
por limite de palavra, os filtros de senioridade e de trilha, a invariante de
"nada inventado" do gerador de CV, a renderização do DOCX e os helpers de
formatação do Telegram.

---

## 9. Segurança e git

O `.env` nunca pode ser commitado. Ele já está no `.gitignore`, mas vale
conferir antes do primeiro commit:

```bash
git check-ignore -v .env      # deve responder que está ignorado
git ls-files | grep -i env    # deve mostrar só .env.example
```

Se uma chave já foi commitada em algum momento, **rotacione a chave primeiro**
(revogue na Groq, `/revoke` no BotFather). Apagar do histórico depois não
protege nada se a chave antiga continua válida. Para limpar o histórico existe
`scripts/scrub_secrets.sh`, que usa `git-filter-repo` e exige force-push.

Para conferir se o histórico de um repositório tem `.env`:

```bash
git log --all --oneline -- .env
```

Se responder alguma coisa, tem chave exposta ali.

Quando for compartilhar seu fork com outra pessoa, prefira o botão **"Use this
template"** do GitHub (Settings → Template repository) em vez de mandar um
clone com histórico. O template cria um repositório novo com um único commit,
sem carregar commits antigos por engano.

### Começando um repositório limpo

Se você recebeu este projeto como pasta solta (sem `.git`), o primeiro commit
é seu e nasce sem histórico herdado, que é exatamente o que você quer:

```bash
git init
git add .
git status                    # CONFIRA: .env e master_profile.yaml não podem aparecer
git commit -m "chore: setup inicial do job-hunter"
git remote add origin <url-do-seu-repositorio>
git push -u origin main
```

O `git status` antes do commit é o passo que importa. Se `.env` ou
`data/master_profile.yaml` aparecerem na lista, pare e confira o `.gitignore`
antes de commitar.

---

## 10. Notas de design

**A LLM nunca escreve o CV.** Para um CV adaptado, o modelo devolve só um
*plano* (quais skills, bullets e projetos manter e em que ordem);
`generators/tailored_cv.py` valida esse plano contra o `master_profile.yaml` e
descarta qualquer coisa que não esteja lá. O modelo não consegue inventar
experiência nem que tente.

**Saída amigável a ATS.** Os CVs saem em DOCX de coluna única, com títulos
padrão e sem tabelas, caixas de texto ou colunas, que costumam quebrar os
parsers de ATS.

**Casamento por limite de palavra.** As palavras-chave usam regex ancorada em
`\b`, então `Java` nunca casa com `JavaScript` e `Spring Boot` casa como uma
unidade só.

**Falha transitória não vira vaga perdida.** Se o scoring falhar por rate limit
ou rede, a vaga não é persistida como ignorada; a URL continua "não vista" e a
próxima rodada tenta de novo.

---

## 11. Fontes de vagas

Ativas por API JSON pública, mais confiáveis: Remotive, Jobicy, Arbeitnow, We
Work Remotely (RSS). Raspadas de HTML, mais frágeis porque os seletores podem
mudar: Gupy, Programathor, Himalayas.

Ficam de fora por decisão de projeto: RemoteOK e Wellfound cobram do candidato;
Indeed está atrás de Cloudflare e proíbe scraping automatizado nos termos;
Remote.co passou a exigir JavaScript. Os arquivos de scraper de alguns deles
continuam no repositório, desligados, caso a situação mude.

### Adicionar um board novo

Boards modernos carregam as vagas via JavaScript a partir de um endpoint JSON
interno. Em vez de escrever um scraper por board, configure um `SourceConfig`
em `scrapers/generic_sources.py` e o `GenericJSONScraper` cuida do resto.

Para achar o endpoint: abra o board, faça uma busca, F12 → aba Network → filtro
"Fetch/XHR", ache a requisição cujo JSON tem as vagas que aparecem na tela,
copie a URL e veja quais chaves têm título, empresa, local, url e descrição.
Preencha o `SourceConfig` e mova para `ENABLED_SOURCES`.

---

## 12. Stack

Python · asyncio · aiohttp · BeautifulSoup · SQLAlchemy · Pydantic · Groq ·
python-telegram-bot · python-docx · APScheduler
