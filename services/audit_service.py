import json
import os
from typing import Any, Dict, List, Optional
from groq import Groq
from rag.vector_store import PowerBIRAG

GROQ_MODEL = "llama3-70b-8192"

class AuditService:
    def __init__(self, rag: PowerBIRAG, openai_api_key: Optional[str] = None):
        self.rag = rag
        # Acepta el parámetro legacy 'openai_api_key' por compatibilidad, pero prioriza GROQ_API_KEY
        self.api_key = os.getenv("GROQ_API_KEY") or openai_api_key
        self.ai_client = Groq(api_key=self.api_key) if self.api_key else None

    def execute_audit(self, model_data: Dict[str, Any], report_data: Dict[str, Any], static_findings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Enriquece los hallazgos estáticos con el contexto RAG de las guías
        y genera el dictamen técnico mediante gpt-4o-mini (o motor de scoring determinista).
        """
        # 1. Enriquecer cada hallazgo con evidencia RAG
        enriched_findings = []
        for finding in static_findings:
            query = f"{finding['rule']} {finding['category']} {finding.get('detail', '')}"
            rag_docs = self.rag.retrieve(query=query, top_k=1)
            if rag_docs:
                doc = rag_docs[0]
                finding["rag_reference"] = {
                    "source": doc["source"],
                    "section": doc["section"],
                    "title": doc["title"],
                    "excerpt": doc["content"].strip()
                }
            enriched_findings.append(finding)

        # 2. Si hay API Key de OpenAI disponible, ejecutamos la síntesis con gpt-4o-mini
        if self.ai_client:
            try:
                return self._generate_ai_report(model_data, report_data, enriched_findings)
            except Exception as e:
                # Si hay error en la llamada de red, devolver con motor determinista señalando el incidente
                fallback = self._generate_deterministic_report(model_data, report_data, enriched_findings)
                fallback["ai_status"] = f"Aviso de conexión OpenAI: {str(e)}. Se utilizó el motor de dictamen estructurado."
                return fallback
        else:
            return self._generate_deterministic_report(model_data, report_data, enriched_findings)

    def _generate_ai_report(self, model_data: Dict[str, Any], report_data: Dict[str, Any], enriched_findings: List[Dict[str, Any]]) -> Dict[str, Any]:
        tables = model_data.get("tables", [])
        relationships = model_data.get("relationships", [])

        prompt = f"""
Eres el Agente Auditor Experto en Optimización de Procesos y Rendimiento de Power BI.
Has analizado los archivos de definición de un modelo en formato PBIP.

ESTADÍSTICAS DEL MODELO:
- Total tablas: {len(tables)}
- Total relaciones: {len(relationships)}

HALLAZGOS DETECTADOS Y NORMAS RAG ASOCIADAS:
{json.dumps(enriched_findings, indent=2, ensure_ascii=False)}

INSTRUCCIONES DE RESPUESTA:
1. Redacta un Resumen Ejecutivo orientado a negocio y a la gestión del consumo de capacidad (Fabric / Power BI Service).
2. Detalla el impacto técnico en el Storage Engine (VertiPaq / compresión / memoria RAM) y en el Formula Engine.
3. Genera recomendaciones técnicas con ejemplos de corrección en DAX o definición TMDL para resolver cada punto.
4. Devuelve EXCLUSIVAMENTE un objeto JSON válido con este esquema:
{{
  "executive_summary": "texto",
  "capacity_and_memory_impact": "texto",
  "action_plan": [
      {{
          "step": int,
          "priority": "Inmediata" | "Media" | "Baja",
          "action": "descripción",
          "target": "objeto afectado"
      }}
  ],
  "evaluated_findings": [
      {{
          "category": "categoría",
          "severity": "severidad",
          "rule": "nombre de regla",
          "target": "objeto",
          "technical_rationale": "explicación basada en la guía",
          "remediation_code": "código DAX/TMDL de ejemplo",
          "rag_source": "cita exacta de la guía"
      }}
  ]
}}
"""
        response = self.ai_client.chat.completions.create(
            model=GROQ_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Eres un auditor técnico de Power BI de máxima reputación."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )
        ai_response = json.loads(response.choices[0].message.content)
        
        # Inyectar el score determinista calculado matemáticamente
        severity_counts = {"Crítica": 0, "Alta": 0, "Media": 0, "Baja": 0}
        for f in enriched_findings:
            sev = f.get("severity", "Media")
            if sev in severity_counts:
                severity_counts[sev] += 1
                
        penalty_crit = severity_counts["Crítica"] * 20
        penalty_alta = severity_counts["Alta"] * 10
        penalty_media = min(severity_counts["Media"] * 3, 20)
        penalty_baja = min(severity_counts["Baja"] * 1, 10)

        score = 100 - (penalty_crit + penalty_alta + penalty_media + penalty_baja)
        score = max(10, min(100, score))
        
        if score >= 80: level = "Excelente"
        elif score >= 60: level = "Aceptable"
        elif score >= 40: level = "En Riesgo"
        else: level = "Crítico"

        ai_response["score"] = score
        ai_response["level"] = level
        ai_response["ai_mode"] = f"Groq/{GROQ_MODEL}"
        ai_response["findings_summary"] = {
            "critical_count": severity_counts["Crítica"],
            "high_count": severity_counts["Alta"],
            "medium_count": severity_counts["Media"],
            "low_count": severity_counts["Baja"]
        }
        return ai_response

    def _generate_deterministic_report(self, model_data: Dict[str, Any], report_data: Dict[str, Any], enriched_findings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calcula el score y genera un reporte estructurado fundamentado en RAG."""
        severity_counts = {"Crítica": 0, "Alta": 0, "Media": 0, "Baja": 0, "Sugerencia": 0, "Informativo": 0}

        evaluated_findings = []
        action_plan = []
        step = 1

        for f in enriched_findings:
            sev = f.get("severity", "Media")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

            rag_ref = f.get("rag_reference", {})
            source_txt = f"{rag_ref.get('source', 'Guía')} ({rag_ref.get('section', '')})" if rag_ref else "Manual de Buenas Prácticas"

            evaluated_findings.append({
                "category": f.get("category"),
                "severity": sev,
                "rule": f.get("rule"),
                "target": f.get("target"),
                "detail": f.get("detail"),
                "impact": f.get("impact"),
                "recommendation": f.get("recommendation"),
                "rag_source": source_txt,
                "rag_excerpt": rag_ref.get("excerpt", "")
            })

            if sev in ["Crítica", "Alta", "Media"]:
                action_plan.append({
                    "step": step,
                    "priority": "Inmediata" if sev in ["Crítica", "Alta"] else "Media",
                    "action": f.get("recommendation"),
                    "target": f.get("target"),
                    "expected_benefit": "Optimización del motor de almacenamiento VertiPaq y eliminación de ambigüedades en filtros."
                })
                step += 1

        # Nuevo sistema de penalización equilibrado (Topes para fallos menores)
        penalty_crit = severity_counts["Crítica"] * 20
        penalty_alta = severity_counts["Alta"] * 10
        penalty_media = min(severity_counts["Media"] * 3, 20)  # Máximo 20 puntos perdidos por fallos medios
        penalty_baja = min(severity_counts["Baja"] * 1, 10)    # Máximo 10 puntos perdidos por fallos bajos

        score = 100 - (penalty_crit + penalty_alta + penalty_media + penalty_baja)
        score = max(10, min(100, score))
        
        # Ajuste de rangos
        if score >= 80:
            level = "Excelente"
        elif score >= 60:
            level = "Aceptable"
        elif score >= 40:
            level = "En Riesgo"
        else:
            level = "Crítico"

        return {
            "score": score,
            "level": level,
            "ai_mode": "Offline/Deterministic RAG" if not self.ai_client else f"Groq/{GROQ_MODEL}",
            "executive_summary": (
                f"El modelo semántico ha obtenido una calificación de {score}/100 ({level}). "
                f"Se han identificado {severity_counts['Crítica']} vulnerabilidades críticas, "
                f"{severity_counts['Alta']} de severidad alta y {severity_counts['Media']} de severidad media. "
                f"Las principales áreas de mejora se concentran en tipos de datos de memoria, relaciones y reglas de visibilidad."
            ),
            "capacity_and_memory_impact": (
                "El uso de números flotantes (Double) en campos de dinero incrementa el uso de RAM al forzar diccionarios hash. "
                "Asimismo, las tablas Auto Date/Time y las relaciones bidireccionales sobrecargan el Formula Engine en Fabric."
            ),
            "findings_summary": {
                "critical_count": severity_counts.get("Crítica", 0),
                "high_count": severity_counts.get("Alta", 0),
                "medium_count": severity_counts.get("Media", 0),
                "low_count": severity_counts.get("Baja", 0)
            },
            "action_plan": action_plan,
            "evaluated_findings": evaluated_findings
        }
