import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DB_DIR / "audit_history.db"

def init_db():
    """Inicializa la base de datos SQLite y crea las tablas si no existen."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                project_name TEXT NOT NULL,
                score INTEGER NOT NULL,
                level TEXT NOT NULL,
                critical_count INTEGER NOT NULL DEFAULT 0,
                high_count INTEGER NOT NULL DEFAULT 0,
                medium_count INTEGER NOT NULL DEFAULT 0,
                low_count INTEGER NOT NULL DEFAULT 0,
                report_json TEXT NOT NULL
            )
        """)
        conn.commit()

def save_audit(project_name: str, report: Dict[str, Any]) -> int:
    """Guarda un reporte de auditoría en la base de datos."""
    init_db()
    summary = report.get("findings_summary", {})
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO audit_history (
                created_at, project_name, score, level,
                critical_count, high_count, medium_count, low_count, report_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now_str,
            project_name,
            int(report.get("score", 0)),
            report.get("level", "Desconocido"),
            summary.get("critical_count", 0),
            summary.get("high_count", 0),
            summary.get("medium_count", 0),
            summary.get("low_count", 0),
            json.dumps(report, ensure_ascii=False)
        ))
        conn.commit()
        return cursor.lastrowid

def get_history(limit: int = 50) -> List[Dict[str, Any]]:
    """Obtiene el listado resumen de auditorías pasadas (sin el JSON pesado)."""
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, created_at, project_name, score, level,
                   critical_count, high_count, medium_count, low_count
            FROM audit_history
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def get_audit(audit_id: int) -> Optional[Dict[str, Any]]:
    """Recupera el reporte completo de una auditoría por su ID."""
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, created_at, project_name, score, level,
                   critical_count, high_count, medium_count, low_count, report_json
            FROM audit_history
            WHERE id = ?
        """, (audit_id,))
        row = cursor.fetchone()
        if not row:
            return None
        res = dict(row)
        res["report"] = json.loads(res["report_json"])
        del res["report_json"]
        return res

def delete_audit(audit_id: int) -> bool:
    """Elimina una auditoría por su ID."""
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM audit_history WHERE id = ?", (audit_id,))
        conn.commit()
        return cursor.rowcount > 0
