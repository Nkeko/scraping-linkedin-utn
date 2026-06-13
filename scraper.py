import asyncio
import csv
import json
import os
import random
import re
import time
from pathlib import Path
from urllib.parse import urlencode

from dotenv import load_dotenv, set_key
from playwright.async_api import async_playwright

load_dotenv()

LI_AT_COOKIE      = os.getenv("LINKEDIN_COOKIE_LI_AT", "").strip()
JSESSIONID_COOKIE = os.getenv("LINKEDIN_COOKIE_JSESSIONID", "").strip()
LIDC_COOKIE       = os.getenv("LINKEDIN_COOKIE_LIDC", "").strip()
BCOOKIE           = os.getenv("LINKEDIN_COOKIE_BCOOKIE", "").strip()
LANG_COOKIE       = os.getenv("LINKEDIN_COOKIE_LANG", "v=2&lang=es-es").strip()
SCHOOL_ID         = os.getenv("LINKEDIN_SCHOOL_ID", "").strip()
OUTPUT            = os.getenv("OUTPUT_FILE", "output/utn_ba_graduados.csv")
PROGRESS_FILE = "progress.json"

# Titulo profesional del egresado (lo que figura en el perfil de LinkedIn)
# junto con el nombre de la carrera para mostrar en el CSV
CARRERAS = [
    ("Ingeniero Mecánico",                 "Ingeniería Mecánica"),
    ("Ingeniera Mecánica",                 "Ingeniería Mecánica"),
    ("Ingeniero Industrial",               "Ingeniería Industrial"),
    ("Ingeniera Industrial",               "Ingeniería Industrial"),
    ("Ingeniero Electrónico",              "Ingeniería Electrónica"),
    ("Ingeniera Electrónica",              "Ingeniería Electrónica"),
    ("Ingeniero en Sistemas de Información", "Ingeniería en Sistemas de Información"),
    ("Ingeniera en Sistemas de Información","Ingeniería en Sistemas de Información"),
    ("Ingeniero Civil",                    "Ingeniería Civil"),
    ("Ingeniera Civil",                    "Ingeniería Civil"),
    ("Ingeniero Electricista",             "Ingeniería Eléctrica"),
    ("Ingeniera Electricista",             "Ingeniería Eléctrica"),
    ("Ingeniero Químico",                  "Ingeniería Química"),
    ("Ingeniera Química",                  "Ingeniería Química"),
    ("Ingeniero Naval",                    "Ingeniería Naval"),
    ("Ingeniera Naval",                    "Ingeniería Naval"),
    ("Ingeniero Textil",                   "Ingeniería Textil"),
    ("Ingeniera Textil",                   "Ingeniería Textil"),
]

PAGE_SIZE       = 10
MAX_PAGES       = 100
MAX_RUN_MINUTES = 60
MIN_PER_CAREER  = 100   # minimo de perfiles con trabajo actual antes de pasar a la siguiente carrera


async def human_delay(min_s=2.0, max_s=5.0):
    await asyncio.sleep(random.uniform(min_s, max_s))


def load_career_data(filepath) -> tuple[dict, set]:
    """Lee el CSV existente y devuelve:
    - counts: {nombre_carrera: cantidad_de_perfiles}
    - seen_urls: set de todos los url_perfil ya guardados
    """
    counts = {}
    seen_urls = set()
    if not Path(filepath).exists():
        return counts, seen_urls
    with open(filepath, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            c = row.get("carrera_buscada", "").strip()
            u = row.get("url_perfil", "").strip()
            if c:
                counts[c] = counts.get(c, 0) + 1
            if u:
                seen_urls.add(u)
    return counts, seen_urls


def load_progress() -> set:
    """Devuelve el set de titulos ya completados en sesiones anteriores."""
    if Path(PROGRESS_FILE).exists():
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        completed = set(data.get("completed", []))
        print(f"[+] Progreso cargado: {len(completed)} busquedas ya completadas.")
        return completed
    return set()


def save_progress(completed: set):
    """Guarda el set de titulos completados en progress.json."""
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump({"completed": list(completed)}, f, ensure_ascii=False, indent=2)


async def setup_context(playwright):
    browser = await playwright.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    # Usar sesion guardada si existe
    storage = "session_state.json" if Path("session_state.json").exists() else None
    context = await browser.new_context(
        viewport={"width": 1366, "height": 768},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        locale="es-AR",
        timezone_id="America/Argentina/Buenos_Aires",
        storage_state=storage,
    )
    if storage:
        print("[+] Usando sesion guardada.")
    return browser, context


async def verify_session(page):
    print("[~] Verificando sesion en LinkedIn...")
    try:
        await page.goto("https://www.linkedin.com/feed/", wait_until="commit", timeout=30000)
    except Exception:
        pass
    await human_delay(2.0, 4.0)

    # Si no esta logueado, esperar login manual
    if "feed" not in page.url and "mynetwork" not in page.url:
        print()
        print("=" * 55)
        print("  ACCION REQUERIDA: Inicia sesion en la ventana de Chrome")
        print("  que se abrio. El scraper esperara hasta que estes")
        print("  en tu feed de LinkedIn.")
        print("=" * 55)
        # Navegar al login para que el usuario pueda loguearse
        try:
            await page.goto("https://www.linkedin.com/login", wait_until="commit", timeout=15000)
        except Exception:
            pass
        # Esperar hasta 3 minutos a que el usuario se loguee
        for _ in range(180):
            await asyncio.sleep(1)
            if "feed" in page.url or "mynetwork" in page.url:
                break
        else:
            raise RuntimeError("Tiempo de espera agotado. No se detecto login.")

    print(f"[+] Sesion activa.")
    # Guardar sesion para proximas ejecuciones
    await page.context.storage_state(path="session_state.json")
    print("[+] Sesion guardada en session_state.json")


async def discover_school_id(page) -> str:
    if SCHOOL_ID:
        print(f"[+] School ID del .env: {SCHOOL_ID}")
        return SCHOOL_ID

    print("[~] Buscando school ID de UTN FRBA...")
    try:
        await page.goto(
            "https://www.linkedin.com/school/universidad-tecnologica-nacional/",
            wait_until="commit", timeout=30000
        )
        await human_delay(3.0, 5.0)
        html = await page.content()
        for pattern in [
            r'"entityUrn"\s*:\s*"urn:li:school:(\d+)"',
            r'urn:li:school:(\d+)',
            r'"schoolId"\s*:\s*"?(\d+)"?',
        ]:
            m = re.search(pattern, html)
            if m:
                sid = m.group(1)
                print(f"[+] School ID encontrado: {sid}")
                set_key(".env", "LINKEDIN_SCHOOL_ID", sid)
                return sid
    except Exception as e:
        print(f"[!] No se pudo obtener school ID: {e}")

    print("[!] Buscando sin school ID (solo keywords).")
    return ""


def build_search_url(school_id, titulo, start):
    if school_id:
        params = {
            "keywords": titulo,
            "schoolFilter": json.dumps([school_id]),
            "origin":   "FACETED_SEARCH",
            "start":    start,
        }
    else:
        # Sin school ID: buscar por titulo + UTN FRBA para acotar a esa regional
        params = {
            "keywords": f"{titulo} UTN FRBA",
            "origin":   "GLOBAL_SEARCH_HEADER",
            "start":    start,
        }
    return "https://www.linkedin.com/search/results/people/?" + urlencode(params)


async def parse_cards(page) -> list[dict]:
    # Esperar a que aparezca al menos un link de perfil
    try:
        await page.wait_for_selector("a[href*='/in/']", timeout=20000)
    except Exception:
        return []

    # Extraer datos via JavaScript directamente del DOM
    results = await page.evaluate("""
        () => {
            const results = [];
            const seen = new Set();

            // LinkedIn envuelve cada card en un <a href="/in/..."> (card completa)
            // y adentro hay otro <a href="/in/..."> que contiene SOLO el nombre (sin hijos).
            // Filtramos por links sin elementos hijo para obtener exactamente el nombre.
            const links = document.querySelectorAll('a[href*="/in/"]');
            for (const link of links) {
                const href = link.href.split('?')[0];
                if (!href.includes('/in/') || seen.has(href)) continue;
                if (href.endsWith('/in/') || href.includes('/in/settings')) continue;

                // Solo procesar links de nombre: sin elementos hijo (solo texto)
                if (link.children.length > 0) continue;

                const name = link.textContent.trim();
                if (!name || name === 'LinkedIn Member') continue;
                if (name.length < 2 || name.length > 80) continue;
                if (name.startsWith('•')) continue;

                seen.add(href);

                // Subir: link -> <p> (fila del nombre) -> contenedor del contenido
                let position = '', company = '';
                const nameRow = link.parentElement;
                const contentDiv = nameRow ? nameRow.parentElement : null;

                if (contentDiv) {
                    // Los <div> hijos directos del contenedor son: headline, ubicacion, etc.
                    const rows = contentDiv.querySelectorAll(':scope > div');
                    if (rows.length >= 1) position = rows[0].textContent.trim();
                }

                // Separar "Cargo en Empresa" o "Cargo at Company"
                if (position.includes(' en ')) {
                    const parts = position.split(' en ');
                    position = parts[0].trim();
                    company  = parts.slice(1).join(' en ').trim();
                } else if (position.includes(' at ')) {
                    const parts = position.split(' at ');
                    position = parts[0].trim();
                    company  = parts.slice(1).join(' at ').trim();
                }

                results.push({ nombre_completo: name, url_perfil: href, empresa_actual: company, cargo_actual: position });
            }
            return results;
        }
    """)

    return results


async def enrich_profile(page, profile: dict) -> dict:
    """Visita el perfil individualmente y extrae empresa y cargo de la seccion Experiencia."""
    url = profile["url_perfil"]
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=35000)
    except Exception as e:
        print(f"      [!] Error navegando a perfil: {e}")
        return profile

    current_url = page.url
    if "/authwall" in current_url or current_url.endswith("/login"):
        print("      [!] Sesion expirada al visitar perfil.")
        return profile

    # Esperar que el perfil cargue (nombre visible)
    try:
        await page.wait_for_selector("h1", timeout=10000)
    except Exception:
        pass
    await human_delay(2.0, 4.0)

    # Detectar el contenedor scrolleable una sola vez
    container_sel = await page.evaluate("""
        () => {
            for (const sel of ['main', '.scaffold-layout__main', '#main-content']) {
                const el = document.querySelector(sel);
                if (el && el.scrollHeight > el.clientHeight + 100) return sel;
            }
            return null;
        }
    """)

    async def scroll_down(px):
        if container_sel:
            await page.evaluate(f"document.querySelector('{container_sel}').scrollTop += {px}")
        else:
            await page.evaluate(f"window.scrollBy(0, {px})")

    # Scrollear con PageDown (teclado) — funciona sin importar que contenedor scrollea
    # El End key baja al fondo inmediatamente para disparar todo el lazy-loading
    try:
        await page.click("body", position={"x": 683, "y": 400})
    except Exception:
        pass
    await page.keyboard.press("End")
    await asyncio.sleep(3.0)

    # Si "actualidad" aun no esta en el DOM, seguir con PageDown
    for _ in range(30):
        found = await page.evaluate(
            "() => document.body.textContent.includes('actualidad')"
        )
        if found:
            await asyncio.sleep(0.5)
            break
        await page.keyboard.press("PageDown")
        await asyncio.sleep(0.4)

    data = await page.evaluate("""
        () => {
            let cargo = '', empresa = '', debug = '';

            // Usar innerText de la pagina completa para evitar problemas de DOM lazy-load
            const main = document.querySelector('main') || document.body;
            const fullText = (main.innerText || '');

            // Encontrar la posicion de la seccion Experiencia
            const expMatch = fullText.match(/\\bExperiencia\\b|\\bExperience\\b/);
            if (!expMatch) {
                debug = 'Experiencia no encontrada en innerText';
                return { cargo, empresa, debug };
            }

            // Tomar las lineas despues del heading
            const afterExp = fullText.slice(expMatch.index + expMatch[0].length);
            const allLines = afterExp
                .split('\\n')
                .map(l => l.trim())
                .filter(l => l && l !== '·' && l.length > 1);

            // Deduplicar consecutivos (LinkedIn duplica texto visible/oculto)
            const lines = allLines.filter((l, i) => i === 0 || l !== allLines[i - 1]);
            debug = 'lines: ' + JSON.stringify(lines.slice(0, 8));

            // Filtrar fechas, duraciones, bullets y metadata
            const isDate = t =>
                /^\\d{4}/.test(t) ||
                t.includes(' - ') ||
                t.includes('\\u2013') ||
                /^\\d+/.test(t) ||
                /(actualidad|actualmente)/i.test(t) ||
                /^(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\\./i.test(t) ||
                /^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/i.test(t) ||
                t.startsWith('•') ||
                /^Jornada/.test(t) ||
                /^\\d+ año/.test(t) ||
                /^\\d+ mes/.test(t);

            const filtered = lines.filter(t => !isDate(t));

            if (filtered.length >= 1) cargo   = filtered[0];
            if (filtered.length >= 2) empresa = filtered[1].split(' · ')[0].trim();

            // Fallback: separar "Cargo en Empresa"
            if (!empresa && cargo.includes(' en ')) {
                const parts = cargo.split(' en ');
                cargo   = parts[0].trim();
                empresa = parts.slice(1).join(' en ').trim();
            } else if (!empresa && cargo.includes(' at ')) {
                const parts = cargo.split(' at ');
                cargo   = parts[0].trim();
                empresa = parts.slice(1).join(' at ').trim();
            }

            return { cargo, empresa, debug };
        }
    """)

    print(f"      [debug] {data.get('debug', '')}")
    enriched = {**profile}
    if data.get("cargo"):
        enriched["cargo_actual"]   = data["cargo"]
    if data.get("empresa"):
        enriched["empresa_actual"] = data["empresa"]

    return enriched


STUDENT_KEYWORDS = {
    "estudiante", "student", "en formación", "en formacion",
    "cursando", "en curso", "alumno", "alumna",
}


def is_graduate_working(profile: dict) -> bool:
    """Devuelve True si el perfil parece un graduado trabajando (no estudiante)."""
    cargo   = (profile.get("cargo_actual")   or "").lower()
    empresa = (profile.get("empresa_actual") or "").lower()

    # Descartar estudiantes
    for kw in STUDENT_KEYWORDS:
        if kw in cargo:
            return False

    # Debe tener al menos cargo o empresa
    return bool(cargo or empresa)


async def scrape_carrera(page, school_id, titulo, session_start, max_seconds, already_seen=None) -> list[dict]:
    all_results = []
    seen_in_carrera = set(already_seen or [])  # pre-cargado con URLs ya procesadas

    # Dos pasadas de busqueda para maximizar resultados:
    # 1) Con schoolFilter (pocas personas que linkearon la entidad FRBA en LinkedIn)
    # 2) Sin schoolFilter, keywords con "UTN FRBA" (muchas mas personas que lo mencionan en su perfil)
    search_passes = []
    if school_id:
        search_passes.append((school_id, titulo))
    search_passes.append((None, f"{titulo} UTN FRBA"))

    for pass_sid, pass_kw in search_passes:
        label = f"school:{pass_sid}" if pass_sid else "keyword UTN FRBA"
        print(f"  [~] Pasada: '{pass_kw}' | {label}")
        consecutive_empty = consecutive_no_new = 0

        for page_num in range(MAX_PAGES):
            elapsed   = time.time() - session_start
            remaining = max_seconds - elapsed
            if remaining <= 0:
                print("[!] Tiempo limite alcanzado.")
                return all_results

            start = page_num * PAGE_SIZE
            print(f"    Pagina {page_num+1} (start={start}) | Tiempo restante: {int(remaining//60)}m {int(remaining%60)}s")

            url = build_search_url(pass_sid, pass_kw, start)
            try:
                await page.goto(url, wait_until="commit", timeout=30000)
            except Exception as e:
                print(f"    [!] Error navegando: {e}")
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    break
                continue

            current_url = page.url
            if "/authwall" in current_url or current_url.endswith("/login") or ("/login?" in current_url and "redirect" not in current_url):
                print("    [!] Sesion expirada.")
                return all_results

            # Scroll con teclado para cargar todos los cards de la pagina de resultados
            await human_delay(5.0, 10.0)
            try:
                await page.click("body", position={"x": 683, "y": 400})
            except Exception:
                pass
            await page.keyboard.press("End")
            await asyncio.sleep(2.0)
            for _ in range(5):
                await page.keyboard.press("PageDown")
                await asyncio.sleep(0.4)

            no_results = await page.query_selector(".search-no-results__container")
            if no_results:
                print("    [+] Sin mas resultados.")
                break

            page_results = await parse_cards(page)

            if not page_results:
                consecutive_empty += 1
                print(f"    [Sin resultados] ({consecutive_empty}/3)")
                if consecutive_empty >= 3:
                    break
                continue

            consecutive_empty = 0
            nuevos_en_pagina = [p for p in page_results if p["url_perfil"] not in seen_in_carrera]
            if not nuevos_en_pagina:
                consecutive_no_new += 1
                print(f"    [Solo duplicados] ({consecutive_no_new}/3)")
                if consecutive_no_new >= 3:
                    print("    [+] LinkedIn repite resultados. Siguiente pasada.")
                    break
            else:
                consecutive_no_new = 0

            for p in nuevos_en_pagina:
                seen_in_carrera.add(p["url_perfil"])

            print(f"    -> {len(nuevos_en_pagina)} nuevos (de {len(page_results)}), enriqueciendo...")
            for i, profile in enumerate(nuevos_en_pagina):
                if time.time() - session_start >= max_seconds:
                    print("    [!] Tiempo limite alcanzado durante enriquecimiento.")
                    return all_results
                print(f"      [{i+1}/{len(nuevos_en_pagina)}] {profile['nombre_completo']}")
                enriched = await enrich_profile(page, profile)
                if is_graduate_working(enriched):
                    all_results.append(enriched)
                else:
                    print(f"      [~] Filtrado: estudiante o sin datos")
                await human_delay(4.0, 8.0)
            print(f"    -> Total acumulado: {len(all_results)}")

            if (page_num + 1) % 10 == 0:
                extra = random.uniform(30, 60)
                print(f"[~] Pausa larga: {extra:.0f}s ...")
                await asyncio.sleep(extra)

    return all_results


def save_csv(results, filepath):
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    fields = ["nombre_completo", "url_perfil", "empresa_actual", "cargo_actual", "carrera_buscada"]
    file_exists = Path(filepath).exists()
    mode = "a" if file_exists else "w"
    with open(filepath, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not file_exists:
            writer.writeheader()
        writer.writerows(results)
    action = "Agregado" if file_exists else "Guardado"
    print(f"[+] {action}: {len(results)} registros en {filepath}")


async def main():
    if not LI_AT_COOKIE:
        raise ValueError("LINKEDIN_COOKIE_LI_AT no configurado en .env")

    async with async_playwright() as pw:
        browser, context = await setup_context(pw)
        page = await context.new_page()

        try:
            await verify_session(page)
            school_id = await discover_school_id(page)

            completed                = load_progress()
            career_counts, seen_urls = load_career_data(OUTPUT)
            all_results              = []
            session_start            = time.time()
            max_seconds              = MAX_RUN_MINUTES * 60

            for titulo, nombre_carrera in CARRERAS:
                if time.time() - session_start >= max_seconds:
                    print(f"\n[!] Limite de {MAX_RUN_MINUTES} min. Guardando.")
                    break

                if titulo in completed:
                    print(f"[~] Ya completado: '{titulo}', saltando.")
                    continue

                current_count = career_counts.get(nombre_carrera, 0)
                if current_count >= MIN_PER_CAREER:
                    print(f"[~] '{nombre_carrera}' ya tiene {current_count} resultados >= {MIN_PER_CAREER}. Saltando.")
                    completed.add(titulo)
                    save_progress(completed)
                    continue

                print(f"\n{'='*55}\n[>] {nombre_carrera} — '{titulo}' ({current_count}/{MIN_PER_CAREER})\n{'='*55}")
                carrera_results = await scrape_carrera(
                    page, school_id, titulo, session_start, max_seconds,
                    already_seen=seen_urls,
                )

                nuevos = 0
                for r in carrera_results:
                    r["carrera_buscada"] = nombre_carrera
                    if r["url_perfil"] not in seen_urls:
                        seen_urls.add(r["url_perfil"])
                        all_results.append(r)
                        nuevos += 1

                omitidos = len(carrera_results) - nuevos
                print(f"[+] {nuevos} nuevos" + (f" ({omitidos} duplicados)" if omitidos else ""))

                career_counts[nombre_carrera] = current_count + nuevos
                total_carrera = career_counts[nombre_carrera]

                if total_carrera >= MIN_PER_CAREER:
                    completed.add(titulo)
                    save_progress(completed)
                    print(f"[+] Minimo alcanzado: {total_carrera}/{MIN_PER_CAREER} para '{nombre_carrera}'.")
                else:
                    print(f"[~] {total_carrera}/{MIN_PER_CAREER} para '{nombre_carrera}'. Proxima sesion continua.")

                if (titulo, nombre_carrera) != CARRERAS[-1] and time.time() - session_start < max_seconds:
                    pausa = random.uniform(20, 45)
                    print(f"[~] Pausa entre carreras: {pausa:.0f}s ...")
                    await asyncio.sleep(pausa)

            print(f"\n[+] Total esta sesion: {len(all_results)} perfiles unicos")
            if all_results:
                save_csv(all_results, OUTPUT)

            # Resetear progreso solo si TODAS las carreras alcanzaron el minimo
            all_titles = {titulo for titulo, _ in CARRERAS}
            if all_titles.issubset(completed):
                Path(PROGRESS_FILE).unlink(missing_ok=True)
                print("[+] Todas las carreras completadas. Progreso reseteado.")

        finally:
            await context.close()
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
