import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.pbip_parser import PBIPParser
from core.static_rules import run_static_checks
from rag.vector_store import PowerBIRAG
from services.audit_service import AuditService

# Cargar variables de entorno si existe archivo .env
load_dotenv()

app = FastAPI(
    title="PowerBI Model Auditor & Process Optimizer Agent",
    description="Servicio continuo de auditoría de modelos PBIP contra guías de buenas prácticas y VertiPaq usando RAG y gpt-4o-mini.",
    version="1.0.0"
)

# Permitir CORS para integración web
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicializar motor RAG
rag_engine = PowerBIRAG()

# Montar archivos estáticos para la interfaz de usuario
static_dir = Path(__file__).parent / "web" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/")
def get_ui():
    """Sirve la interfaz web interactiva del agente auditor."""
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "PowerBI Auditor Agent API is running. Access /docs for Swagger UI."}

@app.get("/health")
def health():
    has_key = bool(os.getenv("GROQ_API_KEY"))
    return {
        "status": "online",
        "service": "powerbi-auditor-agent",
        "ai_engine": "Groq/llama-3.3-70b-versatile",
        "groq_configured": has_key,
        "rag_docs_count": len(rag_engine.corpus)
    }

class FolderAuditRequest(BaseModel):
    folder_path: str
    api_key: Optional[str] = None

@app.post("/api/v1/audit/folder")
def audit_folder(req: FolderAuditRequest):
    """
    Audita una carpeta de proyecto PBIP existente en el servidor o disco local.
    """
    target_path = Path(req.folder_path)
    if not target_path.exists():
        raise HTTPException(status_code=400, detail=f"La ruta '{req.folder_path}' no existe en el sistema.")

    try:
        parser = PBIPParser(str(target_path))
        data = parser.parse_all()
        model_data = data["model"]
        report_data = data["report"]

        static_findings = run_static_checks(model_data, report_data)

        # Usar key del request si se proveyó, o la del entorno
        active_key = req.api_key or os.getenv("GROQ_API_KEY")
        audit_srv = AuditService(rag=rag_engine, openai_api_key=active_key)
        report = audit_srv.execute_audit(model_data, report_data, static_findings)

        return {
            "project_name": target_path.stem,
            "audit_report": report
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error durante la auditoría: {str(e)}")

@app.post("/api/v1/audit/upload-zip")
async def audit_upload_zip(file: UploadFile = File(...), api_key: Optional[str] = Form(None)):
    """
    Recibe un archivo comprimido .zip con la estructura de un proyecto .pbip y ejecuta la auditoría.
    """
    if not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="El archivo enviado debe tener extensión .zip.")

    temp_dir = tempfile.mkdtemp(prefix="pbi_audit_")
    try:
        zip_path = Path(temp_dir) / file.filename
        with open(zip_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)

        parser = PBIPParser(temp_dir)
        data = parser.parse_all()
        model_data = data["model"]
        report_data = data["report"]

        static_findings = run_static_checks(model_data, report_data)

        active_key = api_key or os.getenv("GROQ_API_KEY")
        audit_srv = AuditService(rag=rag_engine, openai_api_key=active_key)
        report = audit_srv.execute_audit(model_data, report_data, static_findings)

        return {
            "project_name": file.filename,
            "audit_report": report
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al procesar el archivo zip: {str(e)}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

from fastapi.responses import StreamingResponse
from services.docs_service import generate_technical_docs

@app.post("/api/v1/docs/upload-zip")
async def docs_upload_zip(file: UploadFile = File(...), api_key: Optional[str] = Form(None)):
    """
    Recibe un archivo comprimido .zip con la estructura .pbip y genera la Documentación en Word (.docx).
    """
    if not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="El archivo enviado debe tener extensión .zip.")

    temp_dir = tempfile.mkdtemp(prefix="pbi_docs_")
    try:
        zip_path = Path(temp_dir) / file.filename
        with open(zip_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)

        parser = PBIPParser(temp_dir)
        data = parser.parse_all()
        model_data = data["model"]
        report_data = data["report"]
        
        active_key = api_key or os.getenv("GROQ_API_KEY")
        
        docx_stream = generate_technical_docs(model_data, report_data, active_key)
        
        headers = {
            'Content-Disposition': f'attachment; filename="Doc_Tecnica_{Path(file.filename).stem}.docx"'
        }
        
        return StreamingResponse(docx_stream, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers=headers)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al generar documentación: {str(e)}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


from services.dax_optimizer_service import analyze_and_optimize_dax

@app.post("/api/v1/dax/optimize")
async def optimize_dax_endpoint(file: UploadFile = File(...), api_key: str = Form(None)):
    """
    Analiza las métricas DAX del modelo en busca de antipatrones y solicita una refactorización a Groq.
    Devuelve un JSON con el código original y el optimizado.
    """
    if not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="El archivo debe ser un .zip del PBIP")

    temp_dir = Path("temp_dax_pbip")
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        zip_path = temp_dir / file.filename
        with open(zip_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)

        parser = PBIPParser(temp_dir)
        data = parser.parse_all()
        model_data = data["model"]
        
        result = analyze_and_optimize_dax(model_data, api_key)
        return JSONResponse(content=result)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en la optimización DAX: {str(e)}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

from services.excel_service import generate_audit_excel

@app.post("/api/v1/audit/export-excel")
async def export_audit_excel(report: dict):
    """
    Recibe el JSON del reporte de auditoría generado previamente y devuelve un archivo Excel descargable.
    """
    try:
        excel_stream = generate_audit_excel(report)
        headers = {
            'Content-Disposition': 'attachment; filename="Auditoria_Modelo_PowerBI.xlsx"'
        }
        return StreamingResponse(
            excel_stream, 
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
            headers=headers
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al generar Excel: {str(e)}")

@app.get("/api/v1/rules")
def get_verified_rules():
    """Retorna la lista de reglas y buenas prácticas configuradas en el agente."""
    return {
        "categories": [
            "Optimización de Memoria (VertiPaq - Fixed Decimal vs Float)",
            "Modelado de Relaciones (1:N, Sin Many-to-Many, Sin Bidireccionales)",
            "Tipado Homogéneo en Relaciones",
            "Visibilidad y Seguridad de Campos (Ocultar Claves Técnicas y Hechos Base)",
            "Nomenclatura y Visibilidad - Estándar Corporativo: Campos SK/COD deben estar ocultos",
            "Nomenclatura y Visibilidad - Estándar Corporativo: Campos DES no deben existir en el modelo (renombrar en Power Query)",
            "Nomenclatura Limpia y Orientada a Negocio",
            "Jerarquías y Desactivación de Attribute Hierarchies",
            "Gobierno de Fechas (Desactivar Auto Date/Time, Calendario Único)",
            "Buenas Prácticas DAX (DIVIDE vs IFERROR, Evitar filtros de tabla en CALCULATE, Variables VAR)",
            "Experiencia de Usuario en Reportes (Límite de visuales por página)"
        ]
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("main:app", host=host, port=port, reload=True)
