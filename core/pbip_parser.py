import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

class PBIPParser:
    """
    Parser para proyectos de Power BI en formato PBIP.
    Soporta definiciones semánticas en TMDL y TMSL (model.bim),
    así como definiciones de reportes (report.json o TMDL/pages).
    """
    def __init__(self, pbip_root: str):
        self.root = Path(pbip_root)
        self.semantic_dir = self._locate_semantic_model_dir()
        self.report_dir = self._locate_report_dir()

    def _locate_semantic_model_dir(self) -> Optional[Path]:
        # Busca carpeta .SemanticModel o .Dataset
        if self.root.name.endswith(".SemanticModel") or self.root.name.endswith(".Dataset"):
            return self.root

        for p in self.root.glob("*"):
            if p.is_dir() and (p.name.endswith(".SemanticModel") or p.name.endswith(".Dataset")):
                return p
        for p in self.root.rglob("*"):
            if p.is_dir() and (p.name.endswith(".SemanticModel") or p.name.endswith(".Dataset")):
                return p
        # Si contiene definition/ o model.bim directamente
        if (self.root / "definition").exists() or (self.root / "model.bim").exists():
            return self.root
        return None

    def _locate_report_dir(self) -> Optional[Path]:
        for p in self.root.glob("*"):
            if p.is_dir() and p.name.endswith(".Report"):
                return p
        for p in self.root.rglob("*"):
            if p.is_dir() and p.name.endswith(".Report"):
                return p
        return None

    def parse_all(self) -> Dict[str, Any]:
        """Extrae el modelo semántico completo y estadísticas de reporte si existen."""
        if self.semantic_dir:
            model_data = self.parse_model()
            model_data["is_live_connection"] = False
        else:
            model_data = {"tables": [], "relationships": [], "is_live_connection": True}
            
        report_data = self.parse_report()
        return {
            "model": model_data,
            "report": report_data
        }

    def parse_model(self) -> Dict[str, Any]:
        definition_dir = self.semantic_dir / "definition"
        bim_file = self.semantic_dir / "model.bim"

        if (definition_dir / "tables").exists():
            return self._parse_tmdl(definition_dir)
        elif bim_file.exists():
            with open(bim_file, "r", encoding="utf-8") as f:
                return self._parse_bim(json.load(f))
        else:
            raise ValueError("No se encontraron definiciones TMDL (definition/tables) ni model.bim.")

    def _parse_tmdl(self, definition_dir: Path) -> Dict[str, Any]:
        tables = []
        tables_path = definition_dir / "tables"
        for tmdl_file in sorted(tables_path.glob("*.tmdl")):
            table_info = self._parse_single_tmdl_table(tmdl_file)
            tables.append(table_info)

        relationships = []
        rel_file = definition_dir / "relationships.tmdl"
        if rel_file.exists():
            relationships = self._parse_tmdl_relationships(rel_file)

        return {"tables": tables, "relationships": relationships}

    def _parse_single_tmdl_table(self, file_path: Path) -> Dict[str, Any]:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()

        table_name_match = re.search(r"^table\s+['\"]?([^'\"\n\r]+)['\"]?", content, re.MULTILINE)
        table_name = table_name_match.group(1).strip() if table_name_match else file_path.stem

        is_auto_date = bool(re.search(r"LocalDateTable_|DateTableTemplate_", table_name, re.IGNORECASE))

        columns = []
        measures = []
        hierarchies = []

        # Parsear columnas
        # Ejemplo TMDL:
        # column 'Unit Price'
        #   dataType: decimal
        #   isHidden
        #   formatString: \$#,0.00
        # o column Subtotal = [Quantity] * [Price]
        col_blocks = re.split(r"\n(?=\s*column\s+)", content)
        for block in col_blocks:
            m = re.match(r"\s*column\s+['\"]?([^'\"=\n\r]+)['\"]?(?:\s*=\s*(.*?))?(?:\n|$)", block)
            if m:
                cname = m.group(1).strip()
                expr = m.group(2).strip() if m.group(2) else ""
                dtype_match = re.search(r"dataType:\s*(\w+)", block, re.IGNORECASE)
                dtype = dtype_match.group(1).lower() if dtype_match else ("calculated" if expr else "unknown")
                is_hidden = bool(re.search(r"\bisHidden\b", block))
                is_avail_mdx = not bool(re.search(r"isAvailableInMdx:\s*false", block, re.IGNORECASE))
                summarize_by = None
                sum_match = re.search(r"summarizeBy:\s*(\w+)", block, re.IGNORECASE)
                if sum_match:
                    summarize_by = sum_match.group(1)

                columns.append({
                    "name": cname,
                    "dataType": dtype,
                    "isCalculated": bool(expr),
                    "expression": expr,
                    "isHidden": is_hidden,
                    "isAvailableInMdx": is_avail_mdx,
                    "summarizeBy": summarize_by
                })

        # Parsear medidas
        # measure TotalSales = SUM(Sales[Amount])
        measure_blocks = re.split(r"\n(?=\s*measure\s+)", content)
        for block in measure_blocks:
            # Aislar solo la métrica: cortar si empieza otra definición TMDL
            block_only_measure = re.split(r"\n\s*(?:column|partition|hierarchy|annotation|table)\s+", block)[0]
            
            m = re.match(r"\s*measure\s+['\"]?([^'\"=\n\r]+)['\"]?\s*=\s*(.*)", block_only_measure, re.DOTALL)
            if m:
                mname = m.group(1).strip()
                mexpr_raw = m.group(2).strip()
                mexpr = re.sub(r"\n\s*(formatString|displayFolder|isHidden|lineageTag|description|detailRowsDefinition)\s*:.*", "", mexpr_raw)
                
                folder_match = re.search(r"displayFolder:\s*['\"]?([^'\"\n\r]+)['\"]?", block_only_measure)
                display_folder = folder_match.group(1).strip() if folder_match else None
                is_hidden = bool(re.search(r"\bisHidden\b", block_only_measure))
                format_match = re.search(r"formatString:\s*([^\n\r]+)", block_only_measure)
                format_str = format_match.group(1).strip() if format_match else None

                measures.append({
                    "name": mname,
                    "expression": mexpr.strip(),
                    "displayFolder": display_folder,
                    "isHidden": is_hidden,
                    "formatString": format_str
                })

        # Parsear jerarquías
        # hierarchy 'Fecha Jerarquía'
        hierarchy_blocks = re.split(r"\n(?=\s*hierarchy\s+)", content)
        for block in hierarchy_blocks[1:]:
            h_match = re.match(r"\s*hierarchy\s+['\"]?([^'\"\n\r]+)['\"]?", block)
            if h_match:
                hierarchies.append({"name": h_match.group(1).strip()})

        return {
            "name": table_name,
            "isAutoDateTime": is_auto_date,
            "columns": columns,
            "measures": measures,
            "hierarchies": hierarchies
        }

    def _parse_tmdl_relationships(self, rel_path: Path) -> List[Dict[str, Any]]:
        content = rel_path.read_text(encoding="utf-8", errors="ignore")
        rels = []
        # Bloques de relationship
        blocks = re.split(r"\n(?=relationship\s+)", content)
        for b in blocks:
            from_m = re.search(r"fromColumn:\s*([^\n\r]+)", b)
            to_m = re.search(r"toColumn:\s*([^\n\r]+)", b)
            if from_m and to_m:
                cross_m = re.search(r"crossFilteringBehavior:\s*(\w+)", b)
                card_m = re.search(r"cardinality:\s*(\w+)", b)
                is_active = "isActive: false" not in b

                from_col = from_m.group(1).strip().replace("'", "")
                to_col = to_m.group(1).strip().replace("'", "")
                from_table = from_col.split(".")[0] if "." in from_col else from_col.split("[")[0]
                to_table = to_col.split(".")[0] if "." in to_col else to_col.split("[")[0]

                rels.append({
                    "fromColumn": from_col,
                    "toColumn": to_col,
                    "fromTable": from_table,
                    "toTable": to_table,
                    "crossFilter": cross_m.group(1) if cross_m else "oneDirection",
                    "cardinality": card_m.group(1) if card_m else "oneToMany",
                    "isActive": is_active
                })
        return rels

    def _parse_bim(self, data: Dict[str, Any]) -> Dict[str, Any]:
        model = data.get("model", {})
        parsed_tables = []
        for t in model.get("tables", []):
            name = t.get("name", "")
            is_auto_date = bool(re.search(r"LocalDateTable_|DateTableTemplate_", name, re.IGNORECASE))
            cols = []
            for c in t.get("columns", []):
                cols.append({
                    "name": c.get("name"),
                    "dataType": str(c.get("dataType", "unknown")).lower(),
                    "isCalculated": "expression" in c,
                    "expression": c.get("expression", ""),
                    "isHidden": c.get("isHidden", False),
                    "isAvailableInMdx": c.get("isAvailableInMdx", True),
                    "summarizeBy": c.get("summarizeBy", None)
                })
            measures = []
            for m in t.get("measures", []):
                measures.append({
                    "name": m.get("name"),
                    "expression": m.get("expression", ""),
                    "displayFolder": m.get("displayFolder", None),
                    "isHidden": m.get("isHidden", False),
                    "formatString": m.get("formatString", None)
                })
            hierarchies = [{"name": h.get("name")} for h in t.get("hierarchies", [])]
            parsed_tables.append({
                "name": name,
                "isAutoDateTime": is_auto_date,
                "columns": cols,
                "measures": measures,
                "hierarchies": hierarchies
            })

        parsed_rels = []
        for r in model.get("relationships", []):
            from_t = r.get("fromTable", "")
            from_c = r.get("fromColumn", "")
            to_t = r.get("toTable", "")
            to_c = r.get("toColumn", "")
            parsed_rels.append({
                "fromColumn": f"{from_t}[{from_c}]",
                "toColumn": f"{to_t}[{to_c}]",
                "fromTable": from_t,
                "toTable": to_t,
                "crossFilter": r.get("crossFilteringBehavior", "oneDirection"),
                "cardinality": r.get("cardinality", "oneToMany"),
                "isActive": r.get("isActive", True)
            })
        return {"tables": parsed_tables, "relationships": parsed_rels}

    def parse_report(self) -> Dict[str, Any]:
        """Analiza la estructura del reporte si existe carpeta .Report."""
        if not self.report_dir or not self.report_dir.exists():
            return {"available": False, "pages": []}

        pages_info = []
        # PBIP moderno con TMDL/pages
        pages_dir = self.report_dir / "definition" / "pages"
        if pages_dir.exists():
            for p_dir in pages_dir.iterdir():
                if p_dir.is_dir():
                    page_tmdl = p_dir / "page.tmdl"
                    page_json = p_dir / "page.json"
                    visuals_count = len(list(p_dir.glob("visuals/*"))) if (p_dir / "visuals").exists() else 0
                    p_name = p_dir.name
                    
                    if page_tmdl.exists():
                        content = page_tmdl.read_text(encoding="utf-8", errors="ignore")
                        match = re.search(r"displayName:\s*(.+)", content)
                        if match:
                            p_name = match.group(1).strip()
                    elif page_json.exists():
                        try:
                            with open(page_json, "r", encoding="utf-8") as f:
                                j = json.load(f)
                                p_name = j.get("displayName", p_name)
                        except Exception:
                            pass
                            
                    pages_info.append({"name": p_name, "visualsCount": visuals_count})
        else:
            # PBIP con report.json
            report_json = self.report_dir / "report.json"
            if report_json.exists():
                try:
                    with open(report_json, "r", encoding="utf-8") as f:
                        rdata = json.load(f)
                    sections = rdata.get("sections", [])
                    for s in sections:
                        visuals = s.get("visualContainers", [])
                        pages_info.append({
                            "name": s.get("displayName", s.get("name", "Página")),
                            "visualsCount": len(visuals)
                        })
                except Exception:
                    pass

        # Recopilar todo el texto crudo del reporte para escaneo heurístico (Opción A)
        raw_text_blocks = []
        for file_path in self.report_dir.rglob("*"):
            if file_path.is_file() and file_path.suffix in [".json", ".tmdl"]:
                try:
                    raw_text_blocks.append(file_path.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    pass
        report_raw_text = "\n".join(raw_text_blocks)

        return {
            "available": True,
            "totalPages": len(pages_info),
            "pages": pages_info,
            "raw_text": report_raw_text
        }
