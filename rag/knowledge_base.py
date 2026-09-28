import os
from pathlib import Path

"""
Base de conocimiento curada para el motor RAG del Agente Power BI.
Incluye extractos y principios de las guías base y carga dinámicamente
cualquier documento (.md o .txt) situado en la carpeta rag/documents/.
"""

# Corpus Base estático
GUIDANCE_CORPUS = [
    {
        "id": "ms_guidance_star_schema_principles",
        "source": "Microsoft Learn: Esquema en Estrella",
        "section": "Diseño de esquemas en estrella",
        "title": "Principios del Esquema en Estrella",
        "content": "Microsoft recomienda el diseño en estrella como estándar de oro para modelos semánticos en Power BI Desktop. Tablas de dimensiones representan entidades del negocio y tablas de hechos almacenan métricas. Evitar copo de nieve."
    },
    {
        "id": "ms_guidance_directquery_optimizations",
        "source": "Microsoft Learn: DirectQuery Model Guidance",
        "section": "Optimización del diseño DirectQuery",
        "title": "Buenas Prácticas en DirectQuery",
        "content": "Evitar columnas calculadas y relaciones sobre columnas calculadas o GUID. Ocultar la columna unilateral de relaciones y limitar el número de visuales por página."
    },
    {
        "id": "dax_guide_currency",
        "source": "The Definitive Guide to DAX",
        "section": "Data Types & Optimizing VertiPaq",
        "title": "Decimal a Currency (Fixed Decimal)",
        "content": "Convertir columnas monetarias de Double a Currency (Fixed Decimal) reduce drásticamente el uso de memoria RAM, permite Value Encoding y acelera VertiPaq."
    },
    {
        "id": "dax_guide_expanded_tables",
        "source": "The Definitive Guide to DAX",
        "section": "Expanded Tables & Filter Conditions",
        "title": "Evitar Filtros de Tabla en CALCULATE",
        "content": "NUNCA filtrar una tabla entera dentro de CALCULATE (ej. CALCULATE([M], FILTER(Tabla, ...))). Debe filtrarse la columna específica con KEEPFILTERS o predicados booleanos directos."
    },
    {
        "id": "dax_guide_callbackdataid",
        "source": "The Definitive Guide to DAX",
        "section": "CallbackDataID",
        "title": "Impacto de IFERROR y ROUND en Iteradores",
        "content": "Funciones no soportadas en Storage Engine (xmSQL) como IFERROR obligan a ejecutar CallbackDataID llamando al Formula Engine por cada fila, ralentizando la ejecución."
    }
]

# Carga dinámica de documentos adicionales de la empresa
DOCS_DIR = Path(__file__).parent / "documents"

def load_local_documents():
    """Lee archivos .md o .txt de la carpeta documents y los añade al corpus."""
    if not DOCS_DIR.exists():
        return

    for file_path in DOCS_DIR.glob("*"):
        if file_path.suffix.lower() in [".md", ".txt"]:
            try:
                content = file_path.read_text(encoding="utf-8")
                
                # Crear un chunk por archivo
                # En un entorno de producción avanzado, aquí se podría aplicar un TextSplitter de LangChain
                chunk = {
                    "id": f"custom_doc_{file_path.stem}",
                    "source": "Documentación Interna / Corporativa",
                    "section": file_path.name,
                    "title": file_path.stem.replace("_", " ").title(),
                    "content": content
                }
                GUIDANCE_CORPUS.append(chunk)
            except Exception as e:
                print(f"Error cargando el documento {file_path.name}: {e}")

# Ejecutamos la carga dinámica al importar el módulo
load_local_documents()
