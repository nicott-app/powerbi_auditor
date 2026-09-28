import json
from io import BytesIO
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from typing import Dict, Any

def generate_audit_excel(audit_report: Dict[str, Any]) -> BytesIO:
    """
    Genera un archivo Excel (.xlsx) con los resultados de la auditoría.
    Consta de dos hojas: 
    1. Resumen Ejecutivo (Score, Impactos y Estadísticas)
    2. Detalle de Hallazgos (La lista completa de hallazgos verificados)
    """
    wb = openpyxl.Workbook()
    
    # -------------------------------------------------------------
    # HOJA 1: RESUMEN EJECUTIVO
    # -------------------------------------------------------------
    ws_resumen = wb.active
    ws_resumen.title = "Resumen Ejecutivo"
    
    # Estilos básicos
    title_font = Font(name="Arial", size=16, bold=True, color="FFFFFF")
    header_font = Font(name="Arial", size=12, bold=True, color="FFFFFF")
    bold_font = Font(name="Arial", size=11, bold=True)
    normal_font = Font(name="Arial", size=11)
    
    fill_dark = PatternFill(start_color="111827", end_color="111827", fill_type="solid")
    fill_header = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    
    align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    align_left = Alignment(horizontal="left", vertical="top", wrap_text=True)
    
    border_thin = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))

    # Título principal
    ws_resumen.merge_cells('A1:D2')
    cell_title = ws_resumen['A1']
    cell_title.value = "Auditoría de Modelo Power BI - Resumen Ejecutivo"
    cell_title.font = title_font
    cell_title.fill = fill_dark
    cell_title.alignment = align_center

    # Score y Nivel
    score = audit_report.get("score", 0)
    level = audit_report.get("level", "Desconocido")
    
    ws_resumen['A4'] = "Score de Salud:"
    ws_resumen['A4'].font = bold_font
    ws_resumen['B4'] = f"{score} / 100"
    ws_resumen['B4'].font = Font(name="Arial", size=12, bold=True)
    
    ws_resumen['A5'] = "Nivel de Calidad:"
    ws_resumen['A5'].font = bold_font
    ws_resumen['B5'] = level
    ws_resumen['B5'].font = normal_font

    # Obtener el color basado en el nivel
    score_color = "059669" # Verde
    if score < 50: score_color = "DC2626" # Rojo
    elif score < 70: score_color = "EA580C" # Naranja
    elif score < 85: score_color = "D97706" # Amarillo
    
    ws_resumen['B4'].font = Font(name="Arial", size=12, bold=True, color=score_color)
    ws_resumen['B5'].font = Font(name="Arial", size=11, bold=True, color=score_color)

    # Conteo de hallazgos
    fs = audit_report.get("findings_summary", {})
    ws_resumen['D4'] = "Resumen de Hallazgos:"
    ws_resumen['D4'].font = bold_font
    
    ws_resumen['D5'] = f"Críticos: {fs.get('critical_count', 0)}"
    ws_resumen['D6'] = f"Altos: {fs.get('high_count', 0)}"
    ws_resumen['D7'] = f"Medios: {fs.get('medium_count', 0)}"
    ws_resumen['D8'] = f"Bajos: {fs.get('low_count', 0)}"

    # Textos largos (Resumen Ejecutivo)
    ws_resumen.merge_cells('A10:D10')
    ws_resumen['A10'] = "Resumen Ejecutivo y Gestión de Capacidad"
    ws_resumen['A10'].font = header_font
    ws_resumen['A10'].fill = fill_header

    ws_resumen.merge_cells('A11:D14')
    cell_exec = ws_resumen['A11']
    cell_exec.value = audit_report.get("executive_summary", "")
    cell_exec.font = normal_font
    cell_exec.alignment = align_left
    
    ws_resumen.merge_cells('A16:D16')
    ws_resumen['A16'] = "Impacto en VertiPaq y Memoria"
    ws_resumen['A16'].font = header_font
    ws_resumen['A16'].fill = fill_header

    ws_resumen.merge_cells('A17:D19')
    cell_impact = ws_resumen['A17']
    cell_impact.value = audit_report.get("capacity_and_memory_impact", "")
    cell_impact.font = normal_font
    cell_impact.alignment = align_left

    # Ajuste de ancho de columnas
    ws_resumen.column_dimensions['A'].width = 25
    ws_resumen.column_dimensions['B'].width = 25
    ws_resumen.column_dimensions['C'].width = 5
    ws_resumen.column_dimensions['D'].width = 30

    # -------------------------------------------------------------
    # HOJA 2: HALLAZGOS DETALLADOS
    # -------------------------------------------------------------
    ws_detalles = wb.create_sheet(title="Hallazgos Detallados")
    
    headers_detalles = ["Categoría", "Severidad", "Regla Violada", "Objeto (Target)", "Detalle Técnico", "Impacto", "Recomendación / Código"]
    ws_detalles.append(headers_detalles)
    
    # Estilo de la cabecera
    for col_num, header in enumerate(headers_detalles, 1):
        cell = ws_detalles.cell(row=1, column=col_num)
        cell.font = header_font
        cell.fill = fill_header
        cell.alignment = align_center
        cell.border = border_thin

    findings = audit_report.get("evaluated_findings", [])
    
    for row_idx, f in enumerate(findings, 2):
        sev = f.get("severity", "")
        
        # Color mapping para severidad
        bg_color = "FFFFFF"
        if sev == "Crítica": bg_color = "FFC7CE"  # Rojo claro
        elif sev == "Alta": bg_color = "FFEB9C"   # Naranja claro
        elif sev == "Media": bg_color = "FFF2CC"  # Amarillo claro
        elif sev == "Baja": bg_color = "C6EFCE"   # Verde claro
        
        row_data = [
            f.get("category", ""),
            sev,
            f.get("rule", ""),
            f.get("target", ""),
            f.get("detail", f.get("technical_rationale", "")),
            f.get("impact", ""),
            f.get("recommendation", f.get("remediation_code", ""))
        ]
        
        for col_idx, val in enumerate(row_data, 1):
            cell = ws_detalles.cell(row=row_idx, column=col_idx)
            cell.value = str(val) if val else ""
            cell.font = normal_font
            cell.alignment = align_left
            cell.border = border_thin
            
            # Aplicar color a la celda de severidad
            if col_idx == 2:
                cell.fill = PatternFill(start_color=bg_color, end_color=bg_color, fill_type="solid")
                cell.font = Font(name="Arial", size=11, bold=True)

    # Autoajustar ancho de columnas en detalles
    ws_detalles.column_dimensions['A'].width = 25
    ws_detalles.column_dimensions['B'].width = 15
    ws_detalles.column_dimensions['C'].width = 40
    ws_detalles.column_dimensions['D'].width = 25
    ws_detalles.column_dimensions['E'].width = 50
    ws_detalles.column_dimensions['F'].width = 40
    ws_detalles.column_dimensions['G'].width = 50

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output
