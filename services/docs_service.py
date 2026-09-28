import json
import os
import sys
from io import BytesIO
from datetime import datetime
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from groq import Groq

from core.prompts import DOCS_PROMPT

GROQ_MODEL = "llama3-70b-8192"

# Forzar stdout a utf-8 para evitar crashes con charmap en Windows
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

def _sanitize_text(text):
    """Reemplaza caracteres Unicode problemáticos para la consola de Windows."""
    if not isinstance(text, str):
        return str(text) if text is not None else ""
    replacements = {
        '\u2011': '-',   # non-breaking hyphen
        '\u2013': '-',   # en dash
        '\u2014': '-',   # em dash
        '\u2018': "'",   # left single quote
        '\u2019': "'",   # right single quote
        '\u201c': '"',   # left double quote
        '\u201d': '"',   # right double quote
        '\u2026': '...', # ellipsis
        '\u00a0': ' ',   # non-breaking space
        '\u2022': '-',   # bullet
        '\u2192': '->',  # right arrow
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text

def _sanitize_dict(obj):
    """Aplica _sanitize_text recursivamente a todos los valores string de un dict/list."""
    if isinstance(obj, str):
        return _sanitize_text(obj)
    elif isinstance(obj, dict):
        return {k: _sanitize_dict(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_dict(item) for item in obj]
    return obj

def generate_technical_docs(model_data: dict, report_data: dict, api_key: str = None) -> BytesIO:
    """
    Coordina la obtención del JSON de GPT-4o-mini y la renderización del documento Word.
    Lanza una excepción si hay API Key configurada pero la llamada a OpenAI falla.
    """
    # 1. Resolver la API Key (GROQ_API_KEY del entorno tiene prioridad, luego el parámetro)
    if not api_key:
        api_key = os.getenv("GROQ_API_KEY")

    print(f"[docs_service] API Key detectada: {'Sí (' + api_key[:8] + '...)' if api_key else 'No'}")

    if api_key:
        client = Groq(api_key=api_key)
        try:
            # Construir resumen compacto del modelo para no superar el límite de tokens de Groq
            compact_tables = []
            for t in model_data.get("tables", []):
                if t.get("isAutoDateTime"):
                    continue
                col_names = [c.get("name", "") for c in t.get("columns", [])]
                measure_names = [m.get("name", "") for m in t.get("measures", [])]
                compact_tables.append({
                    "name": t.get("name", ""),
                    "columns": col_names,
                    "measures": measure_names
                })
            
            compact_rels = []
            for r in model_data.get("relationships", []):
                compact_rels.append({
                    "from": r.get("fromColumn", r.get("from", "")),
                    "to": r.get("toColumn", r.get("to", ""))
                })
            
            compact_model = json.dumps({
                "tables": compact_tables,
                "relationships": compact_rels
            }, default=str, ensure_ascii=False)
            
            # Truncar a 4000 chars como máximo para dejar margen al prompt + respuesta
            if len(compact_model) > 4000:
                compact_model = compact_model[:4000] + "..."
            
            full_prompt = DOCS_PROMPT + "\n\n" + compact_model
            print(f"[docs_service] Prompt compacto: {len(full_prompt)} chars")
            print(f"[docs_service] Llamando a Groq ({GROQ_MODEL}) para generar documentación...")
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": "You are a helpful AI that returns JSON only, no markdown."},
                    {"role": "user", "content": full_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.3
            )
            doc_content = json.loads(response.choices[0].message.content)
            # Sanitizar todos los textos del LLM para evitar charmap en Windows
            doc_content = _sanitize_dict(doc_content)
            print("[docs_service] Respuesta de Groq recibida correctamente.")
        except Exception as e:
            err_msg = str(e).encode('ascii', 'replace').decode('ascii')
            print(f"[docs_service] ERROR al llamar a Groq: {type(e).__name__}: {err_msg}")
            
            # Intentar recuperar el JSON del campo failed_generation de Groq
            doc_content = None
            err_str = str(e)
            if "failed_generation" in err_str:
                try:
                    # Extraer el JSON del failed_generation
                    fg_start = err_str.find("'failed_generation': '")
                    if fg_start != -1:
                        fg_start += len("'failed_generation': '")
                        fg_end = err_str.rfind("'}")
                        if fg_end > fg_start:
                            raw_json = err_str[fg_start:fg_end]
                            # Limpiar escapes dobles
                            raw_json = raw_json.replace('\\\\"', '"').replace("\\'", "'")
                            doc_content = json.loads(raw_json)
                            doc_content = _sanitize_dict(doc_content)
                            print("[docs_service] JSON recuperado del failed_generation de Groq.")
                except Exception as parse_err:
                    print(f"[docs_service] No se pudo recuperar failed_generation: {type(parse_err).__name__}")
            
            if doc_content is None:
                print("[docs_service] Usando fallback estatico tras error de Groq.")
                doc_content = _fallback_doc_content(model_data)
    else:
        print("[docs_service] Sin API Key -> usando analisis estatico (fallback).")
        doc_content = _fallback_doc_content(model_data)

    # --- GARANTIZAR 100% DE LAS MÉTRICAS (Merge determinista) ---
    real_measures = {}
    for table in model_data.get("tables", []):
        for m in table.get("measures", []):
            mname = m.get("name")
            if mname:
                real_measures[mname] = {
                    "name": mname,
                    "expression": m.get("expression", ""),
                    "folder": m.get("displayFolder") or "Raiz"
                }
    
    print(f"[docs_service] Medidas reales detectadas en el modelo: {len(real_measures)}")

    ai_descriptions = {}
    for folder in doc_content.get("dax_dictionary", []):
        for m in folder.get("measures", []):
            ai_descriptions[m.get("name")] = m.get("description", "")

    folders_map = {}
    for mname, mdata in real_measures.items():
        folder = mdata["folder"]
        desc = ai_descriptions.get(mname, "Medida del modelo de datos.")
        if folder not in folders_map:
            folders_map[folder] = []
        folders_map[folder].append({
            "name": mname,
            "description": desc,
            "expression": mdata["expression"]
        })
    doc_content["dax_dictionary"] = [{"folder": k, "measures": v} for k, v in folders_map.items()]
    print(f"[docs_service] Carpetas DAX generadas: {len(doc_content.get('dax_dictionary', []))}")
    print(f"[docs_service] Total medidas en doc: {sum(len(f['measures']) for f in doc_content['dax_dictionary'])}")
    
    # Inyectar metadata del reporte para renderizar
    doc_content["report_data"] = report_data
    # -------------------------------------------------------------

    # 2. Renderizar el Documento Word
    return _render_docx(doc_content)

def _set_table_borders(table, color_hex="DF0027"):
    """Hack en XML para aplicar bordes rojos personalizados a una tabla entera"""
    tbl = table._tbl
    tblPr = tbl.tblPr
    
    # Crear un bloque de bordes
    tblBorders = OxmlElement('w:tblBorders')
    for border_name in ['top', 'left', 'bottom', 'right', 'insideH', 'insideV']:
        border = OxmlElement(f'w:{border_name}')
        border.set(qn('w:val'), 'single')
        border.set(qn('w:sz'), '4') # Grosor
        border.set(qn('w:space'), '0')
        border.set(qn('w:color'), color_hex)
        tblBorders.append(border)
    tblPr.append(tblBorders)

def _add_arial_paragraph(doc, text, size=11, bold=False):
    """Crea un párrafo con texto en Arial. Usa siempre run-level font para evitar contaminar estilos."""
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = 'Arial'
    run._element.rPr.rFonts.set(qn('w:ascii'), 'Arial')
    run._element.rPr.rFonts.set(qn('w:hAnsi'), 'Arial')
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = False
    return p

def _add_cell_text(cell, text, bold=False, size=11):
    """Escribe texto en una celda de tabla con fuente Arial a nivel de run."""
    cell.text = ""
    p = cell.paragraphs[0]
    run = p.add_run(text)
    run.font.name = 'Arial'
    run._element.rPr.rFonts.set(qn('w:ascii'), 'Arial')
    run._element.rPr.rFonts.set(qn('w:hAnsi'), 'Arial')
    run.font.size = Pt(size)
    run.font.bold = bold

def _add_toc(doc):
    """Inserta el código XML (sdt) para un índice de contenidos que Word interpretará."""
    p = doc.add_paragraph()
    run = p.add_run()
    fldChar = OxmlElement('w:fldChar')
    fldChar.set(qn('w:fldCharType'), 'begin')
    instrText = OxmlElement('w:instrText')
    instrText.set(qn('xml:space'), 'preserve')
    instrText.text = 'TOC \\o "1-3" \\h \\z \\u'
    fldChar2 = OxmlElement('w:fldChar')
    fldChar2.set(qn('w:fldCharType'), 'separate')
    fldChar3 = OxmlElement('w:fldChar')
    fldChar3.set(qn('w:fldCharType'), 'end')
    
    r = run._r
    r.append(fldChar)
    r.append(instrText)
    r.append(fldChar2)
    r.append(fldChar3)

def _add_image_placeholder(doc, text):
    """Inserta una caja sombreada como marcador para que el usuario pegue capturas de pantalla."""
    tbl = doc.add_table(rows=1, cols=1)
    tbl.autofit = True
    cell = tbl.cell(0,0)
    shading_elm = OxmlElement('w:shd')
    shading_elm.set(qn('w:fill'), 'EFEFEF')
    cell._tc.get_or_add_tcPr().append(shading_elm)
    
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(f"\n[ ESPACIO PARA CAPTURA: {text} ]\nPegue la imagen aquí\n")
    run.font.name = 'Arial'
    run.font.color.rgb = RGBColor(120, 120, 120)
    run.font.size = Pt(10)
    
    # Establecer altura de celda
    tr = tbl.rows[0]._tr
    trPr = tr.get_or_add_trPr()
    trHeight = OxmlElement('w:trHeight')
    trHeight.set(qn('w:val'), '1440') # Aprox 1 pulgada
    trPr.append(trHeight)
    doc.add_paragraph()

def _render_docx(data: dict) -> BytesIO:
    doc = Document()
    COLOR_ROJO = RGBColor(223, 0, 39)  # #DF0027

    # Estilo Normal base: Arial 11
    normal_style = doc.styles['Normal']
    normal_style.font.name = 'Arial'
    normal_style.font.size = Pt(11)

    def add_heading(text, level=1):
        p = doc.add_heading(level=level)
        run = p.add_run(text)
        run.font.name = 'Arial Black'
        run._element.rPr.rFonts.set(qn('w:ascii'), 'Arial Black')
        run._element.rPr.rFonts.set(qn('w:hAnsi'), 'Arial Black')
        run.font.color.rgb = COLOR_ROJO
        if level == 1:
            run.font.size = Pt(14)
            run.font.italic = False
        else:
            run.font.size = Pt(12)
            run.font.italic = True
        p.paragraph_format.keep_with_next = True
        p.paragraph_format.space_before = Pt(18)
        p.paragraph_format.space_after = Pt(6)
        return p

    # --- PORTADA ---
    title_p = doc.add_heading(level=0)
    title_run = title_p.add_run(
        f"Documentacion Tecnica y Funcional\nModelo: {data.get('project_name', 'PBIP Model')}"
    )
    title_run.font.name = 'Arial Black'
    title_run._element.rPr.rFonts.set(qn('w:ascii'), 'Arial Black')
    title_run._element.rPr.rFonts.set(qn('w:hAnsi'), 'Arial Black')
    title_run.font.color.rgb = COLOR_ROJO
    title_run.font.size = Pt(18)
    title_run.font.italic = False
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()

    # Tabla de versión
    tbl_ver = doc.add_table(rows=2, cols=4)
    tbl_ver.autofit = True
    _set_table_borders(tbl_ver, "DF0027")
    headers = ["Version", "Fecha de Creacion", "Desarrollado por", "Estado"]
    values  = ["1.0", datetime.now().strftime("%d/%m/%Y"), "[TU_USUARIO]", "Definitivo / Aprobado"]
    for i in range(4):
        _add_cell_text(tbl_ver.rows[0].cells[i], headers[i], bold=True)
        _add_cell_text(tbl_ver.rows[1].cells[i], values[i])

    doc.add_page_break()

    # --- ÍNDICE ---
    add_heading("Índice de Contenidos", level=1)
    
    # Instrucciones para el usuario
    p_toc_inst = doc.add_paragraph()
    run_toc = p_toc_inst.add_run("[INSTRUCCIÓN PARA EL USUARIO: Para generar el índice de páginas, diríjase a la pestaña de Word 'Referencias' > 'Tabla de contenido' y seleccione un diseño automático].")
    run_toc.italic = True
    run_toc.font.color.rgb = RGBColor(128, 128, 128)
    
    _add_toc(doc)
    doc.add_page_break()

    # --- 1. RESUMEN EJECUTIVO ---
    add_heading("1. Resumen Ejecutivo y Alcance", level=1)
    _add_arial_paragraph(doc, data.get("executive_summary", ""))
    doc.add_paragraph()

    # --- 2. ARQUITECTURA ---
    add_heading("2. Arquitectura, Origen de Datos y Plegado de Consultas", level=1)
    add_heading("2.1 Origen de Datos", level=2)
    _add_arial_paragraph(doc, data.get("architecture", {}).get("origin_details", ""))

    add_heading("2.2 Plegado de Consultas (Query Folding)", level=2)
    _add_arial_paragraph(doc, data.get("architecture", {}).get("query_folding_text", ""))

    add_heading("2.3 Estructura de Tablas Cargadas", level=2)
    tables_data = data.get("architecture", {}).get("tables", [])
    if tables_data:
        tbl_t = doc.add_table(rows=1, cols=3)
        _set_table_borders(tbl_t, "DF0027")
        for idx, hdr in enumerate(["Tabla", "Rol", "Campos"]):
            _add_cell_text(tbl_t.rows[0].cells[idx], hdr, bold=True)
        for t in tables_data:
            row = tbl_t.add_row().cells
            _add_cell_text(row[0], t.get("name", ""))
            _add_cell_text(row[1], t.get("role", ""))
            cols = t.get("columns", [])
            col_text = ("• " + "\n• ".join(cols)) if isinstance(cols, list) and cols else str(cols)
            _add_cell_text(row[2], col_text)
    doc.add_paragraph()

    # --- 3. MODELO SEMANTICO ---
    add_heading("3. Estructura del Modelo Semantico y Relaciones", level=1)
    _add_arial_paragraph(doc, data.get("semantic_model", {}).get("topology_description", ""))
    
    add_heading("3.1 Vista del Modelo", level=2)
    _add_image_placeholder(doc, "Vista de Modelo (Esquema Estrella/Copo de Nieve)")
    
    add_heading("3.2 Detalle de Relaciones", level=2)
    rels = data.get("semantic_model", {}).get("relationships", [])
    if rels:
        tbl_r = doc.add_table(rows=1, cols=4)
        _set_table_borders(tbl_r, "DF0027")
        for idx, hdr in enumerate(["Dimension (1)", "Clave Dimension", "Tabla Hechos (*)", "Clave Hechos"]):
            _add_cell_text(tbl_r.rows[0].cells[idx], hdr, bold=True)
        for r in rels:
            row = tbl_r.add_row().cells
            _add_cell_text(row[0], r.get("dimension_table", ""))
            _add_cell_text(row[1], r.get("dimension_key", ""))
            _add_cell_text(row[2], r.get("fact_table", ""))
            _add_cell_text(row[3], r.get("fact_key", ""))

    doc.add_page_break()

    # --- 4. ESTRUCTURA DEL INFORME (PAGINAS UI) ---
    add_heading("4. Estructura del Informe (Front-End)", level=1)
    
    report_metadata = data.get("report_data", {})
    is_available = report_metadata.get("available", False)
    pages = report_metadata.get("pages", [])
    total_pages = report_metadata.get("totalPages", 0)
    
    if is_available and total_pages > 0:
        _add_arial_paragraph(doc, f"El informe está compuesto por un total de {total_pages} pestañas visuales. A continuación se detalla cada una de ellas junto con su captura correspondiente.")
        
        for idx, page in enumerate(pages, 1):
            page_name = page.get("name", f"Página {idx}")
            add_heading(f"4.{idx} {page_name}", level=2)
            _add_image_placeholder(doc, f"Pestaña: {page_name}")
            doc.add_paragraph()
    else:
        _add_arial_paragraph(doc, "No se adjuntaron definiciones de reporte (UI) en el proyecto cargado, o el reporte no tiene pestañas publicadas.")

    doc.add_page_break()

    # --- 5. DICCIONARIO DAX ---
    add_heading("5. Diccionario de Medidas Calculadas (DAX)", level=1)
    for folder in data.get("dax_dictionary", []):
        add_heading(f"Carpeta: {folder.get('folder', 'Raiz')}", level=2)
        for measure in folder.get("measures", []):
            _add_arial_paragraph(doc, f"Medida: {measure.get('name', '')}", bold=True)
            desc = measure.get('description', '').strip()
            if desc:
                _add_arial_paragraph(doc, desc, size=10)
            p_dax = doc.add_paragraph()
            run_dax = p_dax.add_run(measure.get('expression', ''))
            run_dax.font.name = 'Arial'
            run_dax._element.rPr.rFonts.set(qn('w:ascii'), 'Arial')
            run_dax._element.rPr.rFonts.set(qn('w:hAnsi'), 'Arial')
            run_dax.font.size = Pt(9)
            run_dax.font.italic = False
            shading_elm = OxmlElement('w:shd')
            shading_elm.set(qn('w:fill'), 'F2F2F2')
            p_dax._p.get_or_add_pPr().append(shading_elm)
            doc.add_paragraph()

    doc.add_page_break()

    # --- 6. RLS ---
    add_heading("6. Seguridad a Nivel de Fila (RLS)", level=1)
    _add_arial_paragraph(doc, data.get("rls_status", "No aplica."))

    # --- 7. PARAMETROS DE CAMPO ---
    add_heading("7. Parametros de Campo", level=1)
    _add_arial_paragraph(doc, data.get("field_parameters_status", "No aplica."))

    # --- 8. PERIODICIDAD ---
    add_heading("8. Periodicidad de Actualizacion", level=1)
    _add_arial_paragraph(doc, data.get("refresh_schedule", "No se ha detectado informacion explicita sobre periodicidad."))

    f = BytesIO()
    doc.save(f)
    f.seek(0)
    return f


def _fallback_doc_content(model_data: dict) -> dict:
    """Datos simulados si no hay API Key o hay error"""
    tables = [t.get("name", "Unknown") for t in model_data.get("tables", [])]
    return {
        "project_name": "Modelo Generado Offline",
        "executive_summary": "Este documento ha sido generado mediante análisis estático porque no hay API Key activa.",
        "architecture": {
            "origin_details": "Múltiples orígenes no determinados.",
            "query_folding_text": "El plegado de consultas traslada el cómputo al motor de origen.",
            "tables": [{"name": t, "role": "Desconocido", "columns": ["Campo A", "Campo B"]} for t in tables]
        },
        "semantic_model": {
            "topology_description": f"Se han detectado {len(model_data.get('relationships', []))} relaciones.",
            "relationships": []
        },
        "dax_dictionary": [],
        "rls_status": f"Roles detectados: {len(model_data.get('roles', []))}",
        "field_parameters_status": "Desconocido en modo offline",
        "refresh_schedule": "Desconocido en modo offline"
    }
