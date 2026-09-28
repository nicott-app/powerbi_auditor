import re
from typing import List, Dict, Any
from rag.knowledge_base import GUIDANCE_CORPUS

class PowerBIRAG:
    """
    Motor RAG para la base de conocimiento de buenas prácticas Power BI y DAX.
    Versión ultrarrápida: Matching léxico-semántico puramente determinista en RAM.
    """
    def __init__(self, openai_client=None):
        self.corpus = GUIDANCE_CORPUS

    def retrieve(self, query: str, top_k: int = 2) -> List[Dict[str, Any]]:
        """Recupera los fragmentos normativos más relevantes mediante coincidencia léxica rápida."""
        q_tokens = set(re.findall(r"\w+", query.lower()))
        scored = []
        for doc in self.corpus:
            doc_text = f"{doc['title']} {doc['section']} {doc['content']}".lower()
            d_tokens = set(re.findall(r"\w+", doc_text))
            overlap = len(q_tokens.intersection(d_tokens))
            
            # Bonificaciones por palabras clave específicas
            if any(k in query.lower() for k in ["moneda", "decimal", "currency", "fixed", "flotante", "float"]) and "currency" in doc["id"]:
                overlap += 15
            if any(k in query.lower() for k in ["bidireccional", "crossfilter", "ambigüedad", "relacion", "dirección"]) and "relation" in doc["id"]:
                overlap += 15
            if any(k in query.lower() for k in ["filter", "calculate", "expanded"]) and "expanded" in doc["id"]:
                overlap += 15
            if any(k in query.lower() for k in ["fecha", "date", "calendar", "tiempo", "auto"]) and "date" in doc["id"]:
                overlap += 15
            if any(k in query.lower() for k in ["jerarquía", "hierarchy", "mdx"]) and "hierarchy" in doc["id"]:
                overlap += 15
            if any(k in query.lower() for k in ["ocultar", "hidden", "clave", "key", "id"]) and "types" in doc["id"]:
                overlap += 10
                
            scored.append((overlap, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:top_k]]

    def retrieve_context_formatted(self, query: str, top_k: int = 2) -> str:
        docs = self.retrieve(query, top_k=top_k)
        formatted_chunks = []
        for d in docs:
            formatted_chunks.append(
                f"### Fuente: {d['source']} | Sección: {d['section']}\n"
                f"**{d['title']}**\n{d['content'].strip()}"
            )
        return "\n\n---\n\n".join(formatted_chunks)
