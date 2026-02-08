# EPUB Translator Studio

Idioma: [English](README.md) | [Polski](README.pl.md) | [Deutsch](README.de.md) | **Espanol** | [Francais](README.fr.md) | [Portugues](README.pt.md)

Kit de escritorio para traducir y editar archivos EPUB con IA.

KEYWORDS: `traductor EPUB`, `herramienta de traduccion EPUB`, `traduccion con IA`, `traductor de ebooks`, `Ollama`, `Google Gemini`, `Translation Memory`, `QA gate`, `Tkinter`, `Electron`, `FastAPI`, `Python`.

## Que hace
- Traduccion EPUB (`translate`) y post-edicion (`edit`)
- Validacion EPUB
- Translation Memory (TM) y cache de segmentos
- Flujo de QA findings y QA gate
- Operaciones EPUB: front card, quitar portada/imagenes, editor de segmentos
- Cola de proyectos (`pending`, `run all`)

## Variantes
- `project-tkinter/` (variante principal, Python + Tkinter)
- `project-web-desktop/` (Electron + FastAPI)
- `legacy/` (scripts raiz archivados, no recomendado)

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
- IA local con Ollama: instala Ollama y descarga al menos un modelo (ejemplo: `ollama pull llama3.1:8b`).
- IA online (por ejemplo Google Gemini): configura una API key valida (`GOOGLE_API_KEY` o campo en la GUI).
- Para proveedores online se requiere acceso a internet.

## Documentacion
- Manual de usuario (PL): `project-tkinter/MANUAL_PL.md`
- Flujo Git (PL): `project-tkinter/GIT_WORKFLOW_PL.md`
- Soporte (PL): `SUPPORT_PL.md`

## Licencia
- Licencia: `EPUB Translator Studio Personal Use License v1.0` (`LICENSE`)
- Este proyecto es source-available y no es open source OSI/FSF.
- El uso privado de copias sin modificar es gratuito.
- Cualquier modificacion, redistribucion o uso comercial requiere acuerdo escrito previo (`COMMERCIAL_LICENSE.md`).
- Ejemplos practicos (ES): `LICENSE_GUIDE_ES.md`
