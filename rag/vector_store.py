import os
import re
import numpy as np
from typing import List, Dict, Any, Optional
from rag.knowledge_base import GUIDANCE_CORPUS

class PowerBIRAG:
    """
    Motor RAG para la base de conocimiento de buenas prácticas Power BI y DAX.
    Soporta modo semántico vectorial (OpenAI text-embedding-3-small)
    con fallback automático a matching léxico-semántico en caso de operar offline.
    """
    def __init__(self, openai_client=None):
        self.client = openai_client
        self.corpus = GUIDANCE_CORPUS
        self.doc_embeddings: Dict[str, np.ndarray] = {}
        self._initialize_embeddings()

    def _initialize_embeddings(self):
        """Pre-calcula o almacena vectores si hay cliente OpenAI configurado."""
        if not self.client:
            return
        try:
            texts = [f"{d['title']}\n{d['section']}\n{d['content']}" for d in self.corpus]
            response = self.client.embeddings.create(
                model="text-embedding-3-small",
                input=texts
            )
            for idx, item in enumerate(response.data):
                doc_id = self.corpus[idx]["id"]
                self.doc_embeddings[doc_id] = np.array(item.embedding, dtype=np.float32)
        except Exception as e:
            # Fallback a modo léxico si falla la API
            self.doc_embeddings = {}

    def retrieve(self, query: str, top_k: int = 2) -> List[Dict[str, Any]]:
        """Recupera los fragmentos normativos más relevantes para la consulta dada."""
        # Si tenemos embeddings calculados, usamos similitud de coseno
        if self.client and self.doc_embeddings:
            try:
                q_resp = self.client.embeddings.create(
                    model="text-embedding-3-small",
                    input=query
                )
                q_vec = np.array(q_resp.data[0].embedding, dtype=np.float32)
                
                scores = []
                for doc in self.corpus:
                    doc_id = doc["id"]
                    d_vec = self.doc_embeddings.get(doc_id)
                    if d_vec is not None:
                        sim = float(np.dot(q_vec, d_vec) / (np.linalg.norm(q_vec) * np.linalg.norm(d_vec)))
                        scores.append((sim, doc))
                scores.sort(key=lambda x: x[0], reverse=True)
                return [doc for _, doc in scores[:top_k]]
            except Exception:
                pass

        # Fallback determinista ponderado por tokens y conceptos clave
        q_tokens = set(re.findall(r"\w+", query.lower()))
        scored = []
        for doc in self.corpus:
            doc_text = f"{doc['title']} {doc['section']} {doc['content']}".lower()
            d_tokens = set(re.findall(r"\w+", doc_text))
            overlap = len(q_tokens.intersection(d_tokens))
            # Bonificaciones por palabras clave específicas
            if any(k in query.lower() for k in ["moneda", "decimal", "currency", "fixed"]) and "currency" in doc["id"]:
                overlap += 15
            if any(k in query.lower() for k in ["bidireccional", "crossfilter", "ambigüedad", "relacion"]) and "relation" in doc["id"]:
                overlap += 15
            if any(k in query.lower() for k in ["filter", "calculate", "expanded"]) and "expanded" in doc["id"]:
                overlap += 15
            if any(k in query.lower() for k in ["fecha", "date", "calendar"]) and "date" in doc["id"]:
                overlap += 15
            if any(k in query.lower() for k in ["jerarquía", "hierarchy", "mdx"]) and "hierarchy" in doc["id"]:
                overlap += 15
            if any(k in query.lower() for k in ["ocultar", "hidden", "clave", "key"]) and "types" in doc["id"]:
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
