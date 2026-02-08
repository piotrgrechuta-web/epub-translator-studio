# EPUB Translator Studio

Idioma: [English](README.md) | [Polski](README.pl.md) | [Deutsch](README.de.md) | [Espanol](README.es.md) | [Francais](README.fr.md) | **Portugues**

Kit desktop para traducao e edicao de arquivos EPUB com IA.

KEYWORDS: `tradutor EPUB`, `ferramenta de traducao EPUB`, `traducao com IA`, `tradutor de ebooks`, `Ollama`, `Google Gemini`, `Translation Memory`, `QA gate`, `Tkinter`, `Electron`, `FastAPI`, `Python`.

## O que faz
- Traducao EPUB (`translate`) e pos-edicao (`edit`)
- Validacao EPUB
- Translation Memory (TM) e cache de segmentos
- Fluxo de QA findings e QA gate
- Operacoes EPUB: front card, remocao de capa/imagens, editor de segmentos
- Fila de projetos (`pending`, `run all`)

## Variantes
- `project-tkinter/` (variante principal, Python + Tkinter)
- `project-web-desktop/` (Electron + FastAPI)
- `legacy/` (scripts raiz arquivados, nao recomendado)

## Inicio rapido

### Tkinter
```powershell
cd project-tkinter
python app_main.py --variant classic
```

### Web Desktop
```powershell
cd project-web-desktop
.\run-backend.ps1
.\run-desktop.ps1
```

## Requisitos
- IA local com Ollama: instalar Ollama e baixar pelo menos um modelo (exemplo: `ollama pull llama3.1:8b`).
- IA online (por exemplo Google Gemini): configurar uma API key valida (`GOOGLE_API_KEY` ou campo na GUI).
- Para provedores online, acesso a internet e obrigatorio.

## Documentacao
- Manual do usuario (PL): `project-tkinter/MANUAL_PL.md`
- Workflow Git (PL): `project-tkinter/GIT_WORKFLOW_PL.md`
- Informacoes de suporte (PL): `SUPPORT_PL.md`

## Licenca
- Licenca: `EPUB Translator Studio Personal Use License v1.0` (`LICENSE`)
- Este projeto e source-available e nao e open source OSI/FSF.
- O uso privado de copias sem modificacao e gratuito.
- Qualquer modificacao, redistribuicao ou uso comercial exige acordo escrito previo (`COMMERCIAL_LICENSE.md`).
- Exemplos praticos (PT): `LICENSE_GUIDE_PT.md`
