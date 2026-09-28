import json
import re
import os
import sys
from groq import Groq
from core.prompts import DAX_OPTIMIZER_PROMPT

GROQ_MODEL = "openai/gpt-oss-120b"

def _sanitize_text(text):
    if not isinstance(text, str):
        return str(text) if text is not None else ""
    replacements = {
        '\u2011': '-', '\u2013': '-', '\u2014': '-',
        '\u2018': "'", '\u2019': "'", '\u201c': '"',
        '\u201d': '"', '\u2026': '...', '\u00a0': ' ',
        '\u2022': '-', '\u2192': '->',
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text

def _sanitize_dict(obj):
    if isinstance(obj, str):
        return _sanitize_text(obj)
    elif isinstance(obj, dict):
        return {k: _sanitize_dict(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_dict(item) for item in obj]
    return obj

def _get_dax_smells(measures: list) -> list:
    """Evalúa estáticamente expresiones DAX y devuelve las que tienen antipatrones."""
    suspects = []
    for m in measures:
        expr_raw = m.get("expression", "")
        if not expr_raw:
            continue
            
        expr = expr_raw.upper()
        name = m.get("name", "Unknown")
        reasons = []
        
        # 1. División manual sin DIVIDE
        if "/" in expr and "DIVIDE" not in expr:
            reasons.append("Uso de división manual '/' sin protección de DIVIDE(). Riesgo de error de división por cero.")
            
        # 2. Uso de FILTER(ALL(...))
        if re.search(r"FILTER\s*\(\s*ALL", expr):
            reasons.append("Uso de FILTER(ALL(...)) que elimina el context transition y procesa toda la tabla. Suele ser mejor usar KEEPFILTERS u optimizar filtros.")
            
        # 3. IFERROR
        if "IFERROR" in expr:
            reasons.append("Uso de IFERROR(), que puede ocultar errores graves y evitar atajos de evaluación del motor tabular.")
            
        # 4. Expresiones inusualmente complejas/largas que merecen revisión
        if len(expr_raw) > 250:
            reasons.append("Métrica excepcionalmente larga y compleja. Potencial candidato a simplificación mediante variables (VAR).")
            
        if reasons:
            suspects.append({
                "measure_name": name,
                "expression": expr_raw,
                "smells_detected": reasons
            })
            
    return suspects

def analyze_and_optimize_dax(model_data: dict, api_key: str = None) -> dict:
    if not api_key:
        api_key = os.getenv("GROQ_API_KEY")
        
    all_measures = []
    for t in model_data.get("tables", []):
        all_measures.extend(t.get("measures", []))
        
    suspects = _get_dax_smells(all_measures)
    
    if not suspects:
        return {
            "status": "success",
            "message": "¡Excelente! No se encontraron antipatrones DAX evidentes en el modelo.",
            "optimizations": []
        }
        
    if not api_key:
        return {
            "status": "error",
            "message": "Se encontraron métricas a mejorar, pero no hay API Key de Groq configurada.",
            "optimizations": []
        }
        
    # Limitar a top 8 para no saturar los tokens de Groq Free (8000 TPM)
    suspects = suspects[:8]
    
    prompt = DAX_OPTIMIZER_PROMPT + "\n\n### MÉTRICAS A EVALUAR:\n" + json.dumps(suspects, indent=2, ensure_ascii=False)
    
    client = Groq(api_key=api_key)
    print(f"[dax_optimizer] Enviando {len(suspects)} métricas sospechosas a Groq para refactorización...")
    
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful AI that returns JSON only."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2
        )
        result = json.loads(response.choices[0].message.content)
        result = _sanitize_dict(result)
        return {
            "status": "success",
            "message": f"Se optimizaron {len(result.get('optimizations', []))} métricas.",
            "optimizations": result.get("optimizations", [])
        }
    except Exception as e:
        err_msg = str(e).encode('ascii', 'replace').decode('ascii')
        print(f"[dax_optimizer] ERROR al llamar a Groq: {type(e).__name__}: {err_msg}")
        
        # Intentar recuperar el JSON si es un error 400 de Groq
        err_str = str(e)
        if "failed_generation" in err_str:
            try:
                fg_start = err_str.find("'failed_generation': '")
                if fg_start != -1:
                    fg_start += len("'failed_generation': '")
                    fg_end = err_str.rfind("'}")
                    if fg_end > fg_start:
                        raw_json = err_str[fg_start:fg_end]
                        raw_json = raw_json.replace('\\\\"', '"').replace("\\'", "'")
                        result = json.loads(raw_json)
                        result = _sanitize_dict(result)
                        return {
                            "status": "success",
                            "message": f"Recuperado tras fallo de Groq. Se optimizaron {len(result.get('optimizations', []))} métricas.",
                            "optimizations": result.get("optimizations", [])
                        }
            except Exception as parse_err:
                print(f"[dax_optimizer] No se pudo recuperar failed_generation: {type(parse_err).__name__}")
                
        return {
            "status": "error",
            "message": f"Fallo al contactar con la IA para la refactorización: {err_msg}",
            "optimizations": []
        }
