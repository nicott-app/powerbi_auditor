import json
from pathlib import Path
from core.pbip_parser import PBIPParser
from core.static_rules import run_static_checks
from rag.vector_store import PowerBIRAG
from services.audit_service import AuditService

def main():
    print("--- 1. PARSEANDO PROYECTO PBIP DE PRUEBA ---")
    sample_path = "./sample_project"
    parser = PBIPParser(sample_path)
    data = parser.parse_all()
    model = data["model"]
    report = data["report"]
    print(f"Tablas detectadas: {[t['name'] for t in model['tables']]}")
    print(f"Relaciones detectadas: {len(model['relationships'])}")
    print(f"Páginas de reporte: {report.get('totalPages')}")

    print("\n--- 2. EJECUTANDO REGLAS ESTÁTICAS DE OPTIMIZACIÓN ---")
    findings = run_static_checks(model, report)
    print(f"Total hallazgos detectados: {len(findings)}")
    for idx, f in enumerate(findings, 1):
        print(f"[{idx}] [{f['severity']}] {f['rule']} -> {f['target']}")

    print("\n--- 3. VERIFICANDO MOTOR RAG ---")
    rag = PowerBIRAG()
    for test_q in ["Fixed Decimal Currency ahorro memoria", "crossfilter bidireccional", "CALCULATE FILTER tabla"]:
        docs = rag.retrieve(test_q, top_k=1)
        if docs:
            print(f"Consulta: '{test_q}' -> Match: {docs[0]['source']} ({docs[0]['title']})")

    print("\n--- 4. EJECUTANDO AUDIT SERVICE (MODO ESTRUCTURADO / DETERMINISTA) ---")
    audit_srv = AuditService(rag=rag)
    report_result = audit_srv.execute_audit(model, report, findings)
    print(f"Score obtenido: {report_result.get('score')} / 100 ({report_result.get('level')})")
    print(f"Resumen ejecutivo: {report_result.get('executive_summary')}")
    print(f"Total acciones planificadas: {len(report_result.get('action_plan', []))}")

    print("\n¡Prueba de integración completada con éxito!")

if __name__ == "__main__":
    main()
