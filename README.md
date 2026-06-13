# LinkedIn Scraper — UTN FRBA Graduados

Scraper de perfiles de LinkedIn para egresados de la Universidad Tecnológica Nacional Facultad Regional Buenos Aires (UTN FRBA).

## Qué hace

- Busca ingenieros graduados de UTN FRBA en LinkedIn por carrera
- Extrae: nombre completo, URL de perfil, empresa actual y cargo actual
- Visita cada perfil individualmente para obtener datos precisos de la sección Experiencia
- Filtra estudiantes y perfiles sin trabajo actual
- Acumula resultados en CSV entre sesiones (modo append)
- Guarda progreso para retomar si se interrumpe
- Requiere mínimo 100 perfiles con trabajo actual por carrera antes de pasar a la siguiente

## Carreras incluidas

Ingeniería Mecánica, Industrial, Electrónica, Sistemas de Información, Civil, Eléctrica, Química, Naval y Textil (búsqueda en masculino y femenino).

## Setup

### 1. Instalar dependencias

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configurar credenciales

```bash
cp .env.example .env
```

Editar `.env` con tus datos:

```
LINKEDIN_COOKIE_LI_AT=<tu cookie li_at>
LINKEDIN_COOKIE_JSESSIONID=<tu cookie jsessionid>
LINKEDIN_SCHOOL_ID=65519489
OUTPUT_FILE=output/utn_ba_graduados.csv
```

### Cómo obtener las cookies de LinkedIn

1. Iniciar sesión en LinkedIn en Chrome
2. Abrir DevTools → Application → Cookies → `https://www.linkedin.com`
3. Copiar los valores de `li_at` y `JSESSIONID`

> Usar una cuenta secundaria, no la personal. LinkedIn prohíbe scraping en sus ToS.

### 3. Ejecutar

```bash
python scraper.py
```

El scraper abre Chrome visible (no headless) para reducir detección. Al terminar la sesión de 60 minutos, volver a correr — retoma desde donde quedó.

## Output

`output/utn_ba_graduados.csv` con columnas:

| nombre_completo | url_perfil | empresa_actual | cargo_actual | carrera_buscada |

## Archivos

| Archivo | Descripción |
|---|---|
| `scraper.py` | Lógica principal |
| `requirements.txt` | Dependencias Python |
| `.env.example` | Template de configuración |
| `progress.json` | Estado entre sesiones (auto-generado) |

## Configuración (scraper.py)

| Constante | Default | Descripción |
|---|---|---|
| `MAX_RUN_MINUTES` | 60 | Duración máxima por sesión |
| `MIN_PER_CAREER` | 100 | Mínimo de perfiles por carrera |
| `LINKEDIN_SCHOOL_ID` | 65519489 | ID de UTN FRBA en LinkedIn |
