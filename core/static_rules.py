import re
from typing import Any, Dict, List

def run_static_checks(model_data: Dict[str, Any], report_data: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """
    Ejecuta un conjunto integral de comprobaciones estáticas sobre el modelo PBIP
    y la definición del reporte.
    """
    findings = []
    tables = model_data.get("tables", [])
    relationships = model_data.get("relationships", [])

    # -------------------------------------------------------------
    # 0. DETECCIÓN DE LIVE CONNECTION (THIN REPORT)
    # -------------------------------------------------------------
    if model_data.get("is_live_connection"):
        findings.append({
            "category": "General",
            "severity": "Informativo",
            "rule": "Reporte de Conexión Directa (Live Connection)",
            "target": "Modelo Completo",
            "detail": "El archivo subido es un reporte desacoplado ('Thin Report'). No contiene tablas, relaciones ni medidas físicas en su código.",
            "impact": "Las métricas de rendimiento del modelo (VertiPaq, Esquema Estrella) no pueden ser evaluadas porque el motor está en Power BI Service o SSAS.",
            "recommendation": "Para auditar el modelo semántico, suba el archivo .pbip o .zip correspondiente al Dataset original."
        })
        
    # Mapa rápido de columnas por tabla para comprobación de tipos en relaciones
    column_type_map = {}
    for t in tables:
        tname = t["name"]
        column_type_map[tname] = {}
        for c in t.get("columns", []):
            column_type_map[tname][c["name"]] = c.get("dataType", "unknown").lower()

    # -------------------------------------------------------------
    # 1. AUTO DATE/TIME Y TABLA DE FECHAS DEDICADA
    # -------------------------------------------------------------
    auto_date_tables = [t["name"] for t in tables if t.get("isAutoDateTime")]
    if auto_date_tables:
        findings.append({
            "category": "Modelo y Fechas",
            "severity": "Alta",
            "rule": "Desactivar Auto Date/Time en el Modelo",
            "target": f"{len(auto_date_tables)} tablas LocalDateTable detectadas",
            "detail": f"Se han detectado {len(auto_date_tables)} tablas de fechas automáticas internas ({', '.join(auto_date_tables[:3])}...).",
            "impact": "Cada columna de fecha genera una tabla oculta en VertiPaq con jerarquías automáticas, aumentando drásticamente el tamaño del modelo y degradando los refrescos.",
            "recommendation": "Desmarcar la opción 'Auto Date/Time' en Opciones > Carga de datos y crear una única dimensión 'Calendario' / 'Date' dedicada y marcada como Date Table."
        })

    has_date_table = any(t["name"].lower() in ["calendario", "calendar", "date", "dimdate", "fecha", "dimfecha"] for t in tables if not t.get("isAutoDateTime"))
    if not has_date_table and not auto_date_tables:
        findings.append({
            "category": "Modelo y Fechas",
            "severity": "Media",
            "rule": "Falta de Tabla de Calendario Centralizada",
            "target": "Modelo Global",
            "detail": "No se identificó una tabla de calendario estándar con nombres comunes (Calendario, Fecha, Date).",
            "impact": "Las funciones de Time Intelligence en DAX requieren una tabla de fechas continua sin saltos.",
            "recommendation": "Crear una tabla de fechas dedicada usando CALENDAR() o CALENDARAUTO()."
        })

    # -------------------------------------------------------------
    # 2. NOMENCLATURA DE TABLAS Y COLUMNAS
    # -------------------------------------------------------------
    technical_prefixes = ["tbl_", "tbl", "dim_", "fact_", "stg_", "dwh_", "vw_"]
    for t in tables:
        if t.get("isAutoDateTime"):
            continue
        tname = t["name"]
        tname_lower = tname.lower()
        if any(tname_lower.startswith(p) for p in technical_prefixes):
            findings.append({
                "category": "Nomenclatura y Experiencia",
                "severity": "Baja",
                "rule": "Nomenclatura de tabla orientada a negocio",
                "target": f"Tabla: {tname}",
                "detail": f"La tabla '{tname}' contiene un prefijo técnico de base de datos.",
                "impact": "Dificulta la autosuficiencia de los usuarios de negocio y rompe la consistencia en reportes corporativos.",
                "recommendation": f"Renombrar '{tname}' eliminando el prefijo técnico para reflejar el término de negocio en lenguaje natural."
            })

    # -------------------------------------------------------------
    # 3. CONVERSIÓN DE DECIMAL (DOUBLE) A MONEDA (FIXED DECIMAL / CURRENCY)
    # -------------------------------------------------------------
    monetary_keywords = ["precio", "price", "importe", "amount", "coste", "cost", "total", "venta", "sales", "revenue", "margen", "margin", "tax", "iva", "descuento", "discount"]
    for t in tables:
        if t.get("isAutoDateTime"):
            continue
        for c in t.get("columns", []):
            cname = c["name"]
            cname_lower = cname.lower()
            dtype = c.get("dataType", "").lower()
            
            is_money_named = any(kw in cname_lower for kw in monetary_keywords)
            if is_money_named and dtype in ["double", "decimal"]:
                findings.append({
                    "category": "Optimización de Memoria (VertiPaq)",
                    "severity": "Media",
                    "rule": "Modificar campos decimales por tipo Moneda (Fixed Decimal / Currency)",
                    "target": f"{t['name']}[{cname}]",
                    "detail": f"La columna monetaria '{cname}' está configurada como '{dtype}'.",
                    "impact": "Los números flotantes (Double) generan una cardinalidad altísima y fuerzan Hash Encoding. Currency se almacena como entero de 64 bits escalado x10.000 con Value Encoding, mejorando la compresión.",
                    "recommendation": f"Cambiar el tipo de datos de {t['name']}[{cname}] a 'Fixed Decimal Number' (Currency)."
                })

    # -------------------------------------------------------------
    # 4. CAMPOS QUE DEBEN OCULTARSE VS MOSTRARSE
    # -------------------------------------------------------------
    for t in tables:
        if t.get("isAutoDateTime"):
            continue
        for c in t.get("columns", []):
            cname = c["name"]
            cname_lower = cname.lower()
            is_key = cname_lower.endswith("key") or cname_lower.endswith("id") or cname_lower.startswith("id_") or cname_lower == "id"
            if is_key and not c.get("isHidden"):
                findings.append({
                    "category": "Visibilidad de Campos",
                    "severity": "Baja",
                    "rule": "Ocultar claves foráneas y columnas de relación técnicas",
                    "target": f"{t['name']}[{cname}]",
                    "detail": f"La columna de clave '{cname}' está visible en el panel de campos.",
                    "impact": "Las claves no deben ser utilizadas directamente por los usuarios en tablas o filtros.",
                    "recommendation": f"Establecer 'isHidden: true' en {t['name']}[{cname}]."
                })

            # --- REGLA PERSONALIZADA: SK y COD deben estar ocultos ---
            if (cname.startswith("SK") or cname.startswith("COD")) and not c.get("isHidden"):
                findings.append({
                    "category": "Nomenclatura y Visibilidad (Estándar Corporativo)",
                    "severity": "Alta",
                    "rule": "Ocultar campos con prefijo SK o COD antes de publicar",
                    "target": f"{t['name']}[{cname}]",
                    "detail": f"El campo '{cname}' usa un prefijo técnico corporativo (SK/COD) y está visible en el panel de campos.",
                    "impact": "Los campos SK (Surrogate Key) y COD (Código técnico) son internos al modelo y no deben ser accesibles para los usuarios finales del informe.",
                    "recommendation": f"Establecer 'isHidden: true' en {t['name']}[{cname}] antes de publicar en el servicio Power BI."
                })

            # --- REGLA PERSONALIZADA: campos DES no deben existir ---
            if cname.startswith("DES"):
                findings.append({
                    "category": "Nomenclatura y Visibilidad (Estándar Corporativo)",
                    "severity": "Crítica",
                    "rule": "Eliminar campos con prefijo DES del modelo publicado",
                    "target": f"{t['name']}[{cname}]",
                    "detail": f"El campo '{cname}' conserva el prefijo técnico 'DES', lo que indica que no fue renombrado en Power Query durante la carga.",
                    "impact": "Según el estándar corporativo, los campos 'DES' deben ser transformados y renombrados en la query de carga (Power Query) antes de llegar al modelo semántico. Su presencia implica un incumplimiento del proceso de preparación de datos.",
                    "recommendation": f"Acceder a Power Query, localizar la columna '{cname}' en la tabla '{t['name']}' y renombrarla con el nombre de negocio correspondiente antes de cargar el modelo."
                })

            dtype = c.get("dataType", "").lower()
            if not c.get("isCalculated") and not c.get("isHidden") and dtype in ["int64", "double", "decimal", "currency"]:
                if c.get("summarizeBy") and c.get("summarizeBy").lower() not in ["none", ""]:
                    if any(kw in t["name"].lower() for kw in ["fact", "ventas", "sales", "movimientos", "transacciones"]):
                        findings.append({
                            "category": "Visibilidad de Campos y Medidas Explícitas",
                            "severity": "Baja",
                            "rule": "Ocultar columnas base de hechos numéricos para evitar medidas implícitas",
                            "target": f"{t['name']}[{cname}]",
                            "detail": f"La columna numérica '{cname}' permite agregaciones implícitas en visuales.",
                            "impact": "Genera inconsistencias analíticas y no aprovecha la reutilización de código DAX.",
                            "recommendation": f"Crear una medida explícita (ej. Total {cname} = SUM({t['name']}[{cname}])) y ocultar la columna base."
                        })

    # -------------------------------------------------------------
    # 5. JERARQUÍAS Y OPTIMIZACIÓN isAvailableInMdx
    # -------------------------------------------------------------
    for t in tables:
        if t.get("isAutoDateTime"):
            continue
        col_names_lower = [c["name"].lower() for c in t.get("columns", [])]
        has_geo = any("pais" in cn or "country" in cn for cn in col_names_lower) and any("ciudad" in cn or "city" in cn for cn in col_names_lower)
        if has_geo and not t.get("hierarchies"):
            findings.append({
                "category": "Jerarquías y Navegación",
                "severity": "Sugerencia",
                "rule": "Definir jerarquía explícita de Geografía",
                "target": f"Tabla: {t['name']}",
                "detail": "La tabla cuenta con atributos geográficos pero no tiene jerarquía explícita.",
                "impact": "Los usuarios deben arrastrar manualmente campo por campo y se dificulta el drill-down.",
                "recommendation": "Crear una jerarquía explícita (ej. 'Geografía': País > Región > Ciudad)."
            })

        for c in t.get("columns", []):
            cname = c["name"]
            cname_lower = cname.lower()
            if (cname_lower.endswith("id") or cname_lower.endswith("key")) and c.get("isAvailableInMdx"):
                findings.append({
                    "category": "Optimización de Memoria (VertiPaq)",
                    "severity": "Baja",
                    "rule": "Desactivar jerarquías de atributo en claves técnicas (isAvailableInMdx = false)",
                    "target": f"{t['name']}[{cname}]",
                    "detail": f"La columna '{cname}' tiene la propiedad isAvailableInMdx activa.",
                    "impact": "VertiPaq crea estructuras MDX innecesarias, aumentando memoria y tiempo de procesado.",
                    "recommendation": f"Establecer 'isAvailableInMdx: false' para {t['name']}[{cname}]."
                })

    # -------------------------------------------------------------
    # 6. ESQUEMA ESTRELLA Y RELACIONES
    # -------------------------------------------------------------
    table_relations = {}
    for r in relationships:
        ft = r.get("fromTable", "")
        tt = r.get("toTable", "")
        
        if ft not in table_relations: table_relations[ft] = []
        if tt not in table_relations: table_relations[tt] = []
        table_relations[ft].append(tt)
        table_relations[tt].append(ft)

        from_col = r.get("fromColumn", "")
        to_col = r.get("toColumn", "")
        cross = r.get("crossFilter", "").lower()
        card = r.get("cardinality", "").lower()

        # Evitar Filtro Bidireccional
        if cross in ["bothdirections", "both"]:
            findings.append({
                "category": "Modelado de Relaciones",
                "severity": "Alta",
                "rule": "Evitar relaciones bidireccionales",
                "target": f"{from_col} <-> {to_col}",
                "detail": "La relación tiene dirección de filtro 'Both'.",
                "impact": "Microsoft y DAX Guide recomiendan evitar bidireccionales ya que degradan rendimiento y crean rutas ambiguas.",
                "recommendation": "Usar 'Single' y activar bidireccionalidad vía DAX (CROSSFILTER) solo si es necesario."
            })

        # Evitar Muchos a Muchos
        if card in ["manytomany", "both"]:
            findings.append({
                "category": "Modelado de Relaciones",
                "severity": "Alta",
                "rule": "Evitar relaciones Muchos a Muchos (MMR)",
                "target": f"{from_col} <-> {to_col}",
                "detail": "Relación definida como Muchos a Muchos.",
                "impact": "Las relaciones M:M no soportan 'Expanded Tables' en DAX y pueden generar ambigüedad.",
                "recommendation": "Crear una tabla puente (Bridge Table) para mantener relaciones 1:N."
            })

        # Coincidencia de tipos de datos (DirectQuery Model Guidance)
        def parse_col_ref(ref: str):
            match = re.match(r"^([^\[]+)\[(.*)\]$", ref.strip())
            if match:
                return match.group(1).strip(), match.group(2).strip()
            if "." in ref:
                parts = ref.split(".", 1)
                return parts[0].strip(), parts[1].strip()
            return None, None

        t1, c1 = parse_col_ref(from_col)
        t2, c2 = parse_col_ref(to_col)
        if t1 and t2 and t1 in column_type_map and t2 in column_type_map:
            type1 = column_type_map[t1].get(c1, "unknown")
            type2 = column_type_map[t2].get(c2, "unknown")
            if type1 != "unknown" and type2 != "unknown" and type1 != type2:
                findings.append({
                    "category": "Modelado de Relaciones",
                    "severity": "Crítica",
                    "rule": "Relaciones con campos del mismo tipo de datos",
                    "target": f"{from_col} ({type1}) <-> {to_col} ({type2})",
                    "detail": f"Tipos de datos discordantes: '{type1}' vs '{type2}'.",
                    "impact": "Impide el uso óptimo de índices en VertiPaq o en el motor relacional (DirectQuery), causando graves penalizaciones de rendimiento.",
                    "recommendation": "Homogeneizar el tipo de datos en Power Query o en la base de datos de origen."
                })
            
            # Detectar relaciones sobre GUID (Microsoft DirectQuery Guidance)
            if "guid" in type1 or "uniqueidentifier" in type1 or "guid" in type2 or "uniqueidentifier" in type2:
                findings.append({
                    "category": "Modelado de Relaciones",
                    "severity": "Alta",
                    "rule": "Evitar relaciones sobre GUID / UniqueIdentifier",
                    "target": f"{from_col} <-> {to_col}",
                    "detail": "Relación basada en GUID.",
                    "impact": "En modelos DirectQuery (y VertiPaq), el uso de GUID como clave de relación degrada el rendimiento de los JOINs de manera significativa.",
                    "recommendation": "Sustituir por claves enteras (Surrogate Keys) en el origen de datos."
                })

    # Detección de copo de nieve (Snowflake Schema - Microsoft Star Schema Guidance)
    # Buscamos tablas que estén relacionadas con otras tablas que NO son hechos
    # Para hacerlo de manera simplificada, si una tabla no tiene medidas (es dimensión) y se relaciona con otra dimensión
    dimension_tables = [t["name"] for t in tables if not t.get("measures", []) and not t.get("isAutoDateTime")]
    for dim in dimension_tables:
        related = table_relations.get(dim, [])
        for rel_dim in related:
            if rel_dim in dimension_tables and rel_dim != dim:
                findings.append({
                    "category": "Esquema Estrella",
                    "severity": "Media",
                    "rule": "Desnormalizar dimensiones Copo de Nieve (Snowflake)",
                    "target": f"{dim} -> {rel_dim}",
                    "detail": f"Se detectó un diseño tipo copo de nieve entre dimensiones ({dim} y {rel_dim}).",
                    "impact": "Microsoft recomienda aplanar dimensiones en Esquema Estrella para reducir saltos de relaciones y mejorar el rendimiento DAX/VertiPaq.",
                    "recommendation": f"Consolidar {rel_dim} dentro de {dim} mediante Power Query o vistas en origen."
                })
                break # Solo reportar una vez por dimensión para no saturar

    # -------------------------------------------------------------
    # 7. AUDITORÍA DE MEDIDAS DAX
    # -------------------------------------------------------------
    for t in tables:
        for m in t.get("measures", []):
            mname = m.get("name", "")
            expr = m.get("expression", "")
            expr_lower = expr.lower()

            if "iferror(" in expr_lower:
                findings.append({
                    "category": "Buenas Prácticas DAX",
                    "severity": "Media",
                    "rule": "Sustituir IFERROR por DIVIDE o comprobaciones explícitas",
                    "target": f"{t['name']}[{mname}]",
                    "detail": "La medida utiliza IFERROR().",
                    "impact": "Inhabilita rutas de optimización del Storage Engine provocando un costoso 'CallbackDataID' al Formula Engine.",
                    "recommendation": "Usar DIVIDE(num, den) o proteger el denominador explícitamente."
                })

            full_table_filter = re.search(r"calculate\s*\([^,]+,\s*filter\s*\(\s*([a-zA-Z0-9_'\s]+)\s*,", expr, re.IGNORECASE)
            if full_table_filter:
                table_filtered = full_table_filter.group(1).strip().replace("'", "")
                findings.append({
                    "category": "Buenas Prácticas DAX",
                    "severity": "Alta",
                    "rule": "Evitar FILTER de tabla completa dentro de CALCULATE",
                    "target": f"{t['name']}[{mname}]",
                    "detail": f"Se aplica FILTER() sobre toda la tabla '{table_filtered}'.",
                    "impact": "Activa la materialización de 'Expanded Tables' arrastrando todas las columnas relacionadas a la caché de memoria.",
                    "recommendation": "Filtrar solo columnas individuales o usar KEEPFILTERS()."
                })

            lines_count = len(expr.splitlines())
            if lines_count > 6 and "var " not in expr_lower:
                findings.append({
                    "category": "Buenas Prácticas DAX",
                    "severity": "Baja",
                    "rule": "Uso de Variables (VAR) en medidas complejas",
                    "target": f"{t['name']}[{mname}]",
                    "detail": f"Medida de {lines_count} líneas sin VAR.",
                    "impact": "Dificulta legibilidad y aumenta el riesgo de computar múltiples veces la misma expresión.",
                    "recommendation": "Refactorizar usando variables."
                })

            if not m.get("displayFolder"):
                findings.append({
                    "category": "Gobernanza",
                    "severity": "Informativo",
                    "rule": "Organizar medidas en Display Folders",
                    "target": f"{t['name']}[{mname}]",
                    "detail": "La medida no pertenece a ninguna carpeta.",
                    "impact": "Entorpece la navegabilidad del modelo para usuarios finales.",
                    "recommendation": "Asignar 'displayFolder'."
                })

    # -------------------------------------------------------------
    # 8. AUDITORÍA DEL REPORTE (PERFORMANCE ANALYZER & UX)
    # -------------------------------------------------------------
    if report_data and report_data.get("available"):
        for page in report_data.get("pages", []):
            vcount = page.get("visualsCount", 0)
            if vcount > 10:
                findings.append({
                    "category": "Diseño de Reportes (UX y Rendimiento)",
                    "severity": "Media",
                    "rule": "Limitar visuales por página (Microsoft Performance Analyzer Guidance)",
                    "target": f"Página: '{page.get('name')}' ({vcount} visuales)",
                    "detail": f"La página contiene {vcount} visuales, superando la recomendación de 8-10.",
                    "impact": "Incrementa el tiempo 'Other' (espera en cola). Cada visual lanza consultas concurrentes a VertiPaq.",
                    "recommendation": "Consolidar métricas con tarjetas multi-fila, tooltips o drill-through."
                })

    # -------------------------------------------------------------
    # 9. ELEMENTOS HUÉRFANOS (Sin uso en Reporte ni en DAX - Opción A)
    # -------------------------------------------------------------
    if report_data and report_data.get("available") and "raw_text" in report_data:
        raw_text = report_data["raw_text"]
        
        # Construir el gran texto (Haystack) donde buscar referencias
        all_dax_expressions = []
        for t in tables:
            for c in t.get("columns", []):
                if c.get("expression"):
                    all_dax_expressions.append(c["expression"])
            for m in t.get("measures", []):
                if m.get("expression"):
                    all_dax_expressions.append(m["expression"])
                    
        haystack_pieces = [raw_text] + all_dax_expressions
        
        # Añadir referencias de relaciones
        for rel in relationships:
            haystack_pieces.append(rel.get("fromColumn", ""))
            haystack_pieces.append(rel.get("toColumn", ""))
            
        combined_haystack = "\n".join(haystack_pieces)

        # Buscar Medidas Huérfanas
        for t in tables:
            if t.get("isAutoDateTime"):
                continue
            for m in t.get("measures", []):
                mname = m["name"]
                escaped = re.escape(mname)
                # Buscamos [Medida] o "Medida" (JSON) o 'Medida'
                pattern = r"\[" + escaped + r"\]|\"" + escaped + r"\"|'" + escaped + r"'"
                
                if not re.search(pattern, combined_haystack, re.IGNORECASE):
                    findings.append({
                        "category": "Limpieza de Modelo (Elementos Huérfanos)",
                        "severity": "Baja",
                        "rule": "Eliminar medidas no utilizadas (Huérfanas)",
                        "target": f"{t['name']}[{mname}]",
                        "detail": f"La medida '{mname}' no se utiliza en el reporte PBIP ni dentro de otra fórmula DAX.",
                        "impact": "Las medidas no usadas ensucian el modelo y dificultan el mantenimiento (aunque no consumen RAM).",
                        "recommendation": "Revisar y eliminar. (Aviso: Valide que no se use en Excels externos vía Live Connection o en roles RLS)."
                    })

        # Buscar Columnas Huérfanas
        for t in tables:
            if t.get("isAutoDateTime"):
                continue
            for c in t.get("columns", []):
                cname = c["name"]
                escaped = re.escape(cname)
                pattern = r"\[" + escaped + r"\]|\"" + escaped + r"\"|'" + escaped + r"'"
                
                if not re.search(pattern, combined_haystack, re.IGNORECASE):
                    findings.append({
                        "category": "Limpieza de Modelo (Elementos Huérfanos)",
                        "severity": "Alta",
                        "rule": "Eliminar columnas físicas no utilizadas",
                        "target": f"{t['name']}[{cname}]",
                        "detail": f"La columna '{cname}' de '{t['name']}' no aparece en ningún visual del reporte, ni en DAX, ni en relaciones.",
                        "impact": "Consumo altísimo de memoria RAM y degradación de tiempos de actualización (motor VertiPaq).",
                        "recommendation": "Eliminar desde Power Query o la base de datos origen. (Aviso: Valide uso externo o RLS)."
                    })

    return findings
