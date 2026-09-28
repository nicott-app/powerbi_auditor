# Agente de IA para Auditoría y Optimización de Modelos Power BI (PBIP)

Servicio autónomo y continuo (REST API + Web UI) que ingiere proyectos de Power BI en formato **`.pbip`** (archivos TMDL o `model.bim`) y realiza una auditoría exhaustiva de calidad, rendimiento y gobernanza contra una base de conocimiento normativo mediante **RAG (Retrieval-Augmented Generation)** y **`gpt-4o-mini`**.

---

## 🎯 Criterios y Reglas Auditadas

El agente audita automáticamente las directrices del **Manual de Buenas Prácticas en Power BI (SMU / Avos Tech)**, **The Definitive Guide to DAX (Marco Russo & Alberto Ferrari)** y las guías de arquitectura de **Microsoft**:

1. **Optimización de Memoria VertiPaq (Moneda vs Decimal)**:
   - Detecta columnas de importe/precio/coste/venta configuradas como punto flotante (`Double` / `Decimal`).
   - Recomienda conversión a `Fixed Decimal Number` (`Currency`), permitiendo compresión por **Value Encoding** y eliminando diccionarios de memoria.
2. **Campos que deben ocultarse vs mostrarse**:
   - Detección de claves foráneas (`*Key`, `*ID`) visibles al usuario final.
   - Columnas base numéricas en tablas de hechos que deben ocultarse para forzar el uso de medidas explícitas.
3. **Modelado y Relaciones**:
   - Detección y penalización de filtros cruzados bidireccionales (`BothDirections`).
   - Detección de relaciones Muchos a Muchos (`ManyToMany` débiles).
   - Verificación de tipos de datos idénticos en ambos lados de la relación.
4. **Nomenclatura Orientada a Negocio**:
   - Detección de prefijos técnicos de base de datos (`tbl_`, `dim_`, `fact_`, etc.).
5. **Jerarquías y Atributos MDX**:
   - Sugerencia de jerarquías de usuario para campos temporales y geográficos.
   - Recomendación de `isAvailableInMdx = false` en claves técnicas para ahorrar RAM de índices jerárquicos.
6. **Fechas y Calendario**:
   - Detección de tablas de fechas automáticas (`LocalDateTable_*`).
   - Validación de tabla de fechas dedicada y marcada como Date Table.
7. **Buenas Prácticas en DAX**:
   - Detección de `IFERROR()` sustituyéndolo por `DIVIDE()` o comprobaciones preventivas.
   - Detección de `FILTER(Tabla, ...)` de tabla completa en `CALCULATE()` (anti-patrón de expanded tables).
   - Uso de variables `VAR ... RETURN` para evitar reevaluaciones y documentar el código.
8. **Diseño de Reportes y UX**:
   - Conteo de visuales por página (alerta si supera el umbral recomendado de 8-10 visuales).

---

## 🚀 Puesta en Marcha Rápida

### 1. Requisitos Previos
- Windows 10/11
- Python 3.13 (instalado en el sistema)

### 2. Configurar Clave de OpenAI (Opcional)
Para habilitar el agente generativo con `gpt-4o-mini`, copia el archivo `.env.example` a `.env` y añade tu clave:
```env
OPENAI_API_KEY=sk-...
PORT=8000
HOST=0.0.0.0
```
> **Nota**: Si no configuras la clave de OpenAI, el servicio funciona automáticamente en **Modo RAG Determinista Offline**, ejecutando todas las comprobaciones y citando las fuentes normativas sin coste.

### 3. Iniciar el Servicio
Haz doble clic en **`start_server.bat`** o ejecuta en PowerShell:
```powershell
.\venv\Scripts\python.exe main.py
```

El servicio estará disponible en:
- **Interfaz Web Interactiva**: [http://localhost:8000](http://localhost:8000)
- **Documentación Swagger / OpenAPI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Comprobación de Salud**: [http://localhost:8000/health](http://localhost:8000/health)

---

## 📡 Endpoints de la API REST

### 1. `POST /api/v1/audit/folder`
Audita un proyecto `.pbip` especificando su ruta local o de red:
```json
{
  "folder_path": "C:/MisProyectos/Ventas_Retail.pbip",
  "api_key": "sk-..." // Opcional si ya está en .env
}
```

### 2. `POST /api/v1/audit/upload-zip` (Multipart Form)
Permite subir un archivo `.zip` que contiene la carpeta del proyecto PBIP.

### 3. `GET /api/v1/rules`
Devuelve el catálogo de normas y categorías que el agente evalúa.

---

## 📁 Proyecto de Prueba Incluido

El repositorio incluye la carpeta **`sample_project/`** con un proyecto PBIP sintético que contiene intencionadamente vulnerabilidades típicas (Auto Date/Time, campos Double en moneda, relaciones bidireccionales, IFERROR, etc.). Puedes auditarlo directamente introduciendo `./sample_project` en la interfaz web.
