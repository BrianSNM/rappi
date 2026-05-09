"""
ops_bot.py — Operations Bot con LangGraph.

Flujo determinista:
    [generate_code] → [execute] → [verbalize]
                          ↓ error
                       [retry] → [execute]
"""
from __future__ import annotations

import io
import os
import traceback
from contextlib import redirect_stdout
from typing import Any, TypedDict

import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


DF_CONTEXT = """
EL DATAFRAME `df` YA ESTÁ CARGADO. Estructura conocida:

COLUMNAS:
- COUNTRY: string. Códigos: AR, BR, CL, CO, CR, EC, MX, PE, UY
- CITY: string
- ZONE: string
- ZONE_TYPE: "Wealthy" o "Non Wealthy"
- ZONE_PRIORITIZATION: "High Priority", "Prioritized" o "Not Prioritized"
- METRIC: una de las 14 métricas listadas abajo
- WEEK_AGO: int 0-8. WEEK_AGO=0 = semana actual (L0W). WEEK_AGO=8 = hace 8 semanas.
  "Esta semana" SIEMPRE = WEEK_AGO=0.
- VALUE: float

VALORES EXACTOS DE METRIC (respeta mayúsculas y espacios):

Rentabilidad y experiencia:
- "Gross Profit UE": Margen bruto / Total órdenes. Mayor = más rentable.
- "Perfect Orders": Órdenes sin defectos / Total. Mayor = mejor.
- "Orders": Número absoluto de órdenes.

Penetración:
- "Lead Penetration": Tiendas habilitadas / (Prospectos + Habilitadas + Salieron).
- "% Restaurants Sessions With Optimal Assortment".

Adopción Pro:
- "Pro Adoption", "% PRO Users Who Breakeven",
- "MLTV Top Verticals Adoption", "Turbo Adoption".

Conversión:
- "Non-Pro PTC > OP", "Restaurants SS > ATC CVR",
- "Restaurants SST > SS CVR", "Retail SST > SS CVR".

Comercial:
- "Restaurants Markdowns / GMV".

REGLAS DE IMPUTACIÓN:
- Si nulos en VALUE <= 25% del filtrado: imputa con la mediana.
- Si > 25%: usa dropna() y aclara "muestra pequeña por alta ausencia de datos".
"""


PROMPT_GENERATE = """Eres un Senior Operations Analyst en Rappi. Vas a recibir una pregunta
y debes responder generando un bloque de código pandas que la responda.

{context}

REGLAS DE GENERACIÓN DE CÓDIGO:

1. El df ya está cargado. NO uses df.head(), df.columns ni df.info().
2. Escribe UN solo bloque de código pandas que termine asignando el resultado
   final a una variable llamada `result`.
3. `result` puede ser un DataFrame, Serie, número o string.
4. NO uses inplace=True. Reasigna siempre.
5. Para filtros usa .copy().
6. NO incluyas print(). Solo asigna a `result`.
7. Devuelve SOLO el código Python, sin texto explicativo, sin markdown,
   sin ```python``` fences. Solo el código plano.

HISTORIAL RECIENTE (úsalo si la pregunta hace referencia a lo anterior):
{history}

PREGUNTA: {question}

CÓDIGO:"""


PROMPT_VERBALIZE = """Eres un Senior Operations Analyst en Rappi. Acabas de ejecutar un análisis
y vas a presentar el resultado al usuario.

PREGUNTA ORIGINAL: {question}

CÓDIGO EJECUTADO:
```python
{code}
```

RESULTADO DE LA EJECUCIÓN:
{result}

Redacta una respuesta clara, directa, en español, con números concretos.
- Si es ranking/top, lista los elementos con sus valores.
- Si es comparación, di explícitamente cuál es mayor/menor y por cuánto.
- Si es tendencia, di si mejora, empeora o se mantiene.
- Si la muestra es pequeña o hay nulos altos, menciónalo.
- Máximo 6 líneas. Sin introducciones largas. Sin saludos."""


PROMPT_RETRY = """El siguiente código falló al ejecutarse. Corrígelo.

{context}

CÓDIGO QUE FALLÓ:
```python
{code}
```

ERROR:
{error}

PREGUNTA ORIGINAL: {question}

Devuelve SOLO el código Python corregido, sin texto explicativo, sin markdown.
Asegúrate de que termine asignando el resultado final a una variable `result`."""


class BotState(TypedDict, total=False):
    question: str
    history: str
    code: str
    result_repr: str
    error: str
    retried: bool
    final_answer: str


SUGERENCIAS_RAPIDAS = [
    "¿Cuáles son las 5 zonas con mayor Lead Penetration esta semana?",
    "Compara Perfect Orders entre zonas Wealthy y Non Wealthy en MX",
    "¿Qué zonas tienen alto Lead Penetration pero bajo Perfect Orders?",
    "Promedio de Gross Profit UE por país",
    "¿Cuáles zonas se han deteriorado más en las últimas 4 semanas?",
]


def _content_to_text(resp: Any) -> str:
    """
    Convierte la respuesta del LLM a string plano.
    Gemini a veces devuelve content como lista de partes [{type:'text', text:'...'}].
    """
    content = getattr(resp, "content", resp)

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                # formato típico: {"type": "text", "text": "..."}
                parts.append(item.get("text") or item.get("content") or "")
            else:
                parts.append(str(item))
        return "".join(parts)

    if isinstance(content, dict):
        return content.get("text") or content.get("content") or str(content)

    return str(content)


def _strip_code_fences(text: str) -> str:
    """Quita ```python ... ``` que el LLM a veces incluye."""
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def _format_result(result: Any) -> str:
    if isinstance(result, pd.DataFrame):
        if len(result) > 30:
            return result.head(30).to_string() + f"\n\n... ({len(result)} filas en total)"
        return result.to_string()
    elif isinstance(result, pd.Series):
        if len(result) > 30:
            return result.head(30).to_string() + f"\n\n... ({len(result)} elementos)"
        return result.to_string()
    elif isinstance(result, (int, float)):
        return f"{result}"
    else:
        return str(result)[:2000]


class OperationsBot:
    """Bot con flujo LangGraph."""

    def __init__(self, df: pd.DataFrame, modelo: str = "gemini-flash-latest"):
        from langchain_google_genai import ChatGoogleGenerativeAI

        self.df = df
        self.llm = ChatGoogleGenerativeAI(model=modelo, temperature=0.0)
        self.graph = self._build_graph()

    def _node_generate_code(self, state: BotState) -> BotState:
        prompt = PROMPT_GENERATE.format(
            context=DF_CONTEXT,
            history=state.get("history") or "(sin historial)",
            question=state["question"],
        )
        resp = self.llm.invoke(prompt)
        code = _strip_code_fences(_content_to_text(resp))
        return {"code": code}

    def _node_execute(self, state: BotState) -> BotState:
        code = state.get("code", "")
        local_ns = {"df": self.df, "pd": pd}
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                exec(code, local_ns)
            if "result" not in local_ns:
                return {"error": "El código no asignó la variable `result`."}
            result_repr = _format_result(local_ns["result"])
            return {"result_repr": result_repr, "error": ""}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    def _node_retry(self, state: BotState) -> BotState:
        prompt = PROMPT_RETRY.format(
            context=DF_CONTEXT,
            code=state.get("code", ""),
            error=state.get("error", ""),
            question=state["question"],
        )
        resp = self.llm.invoke(prompt)
        new_code = _strip_code_fences(_content_to_text(resp))
        return {"code": new_code, "retried": True, "error": ""}

    def _node_verbalize(self, state: BotState) -> BotState:
        prompt = PROMPT_VERBALIZE.format(
            question=state["question"],
            code=state.get("code", ""),
            result=state.get("result_repr", "(sin resultado)"),
        )
        resp = self.llm.invoke(prompt)
        answer = _content_to_text(resp).strip()
        return {"final_answer": answer}

    def _route_after_execute(self, state: BotState) -> str:
        if state.get("error") and not state.get("retried"):
            return "retry"
        return "verbalize"

    def _build_graph(self):
        from langgraph.graph import StateGraph, END

        g = StateGraph(BotState)
        g.add_node("generate", self._node_generate_code)
        g.add_node("execute", self._node_execute)
        g.add_node("retry", self._node_retry)
        g.add_node("verbalize", self._node_verbalize)

        g.set_entry_point("generate")
        g.add_edge("generate", "execute")
        g.add_conditional_edges(
            "execute",
            self._route_after_execute,
            {"retry": "retry", "verbalize": "verbalize"},
        )
        g.add_edge("retry", "execute")
        g.add_edge("verbalize", END)

        return g.compile()

    @staticmethod
    def _format_history(history: list[dict] | None) -> str:
        if not history:
            return "(sin historial)"
        recientes = history[-4:]
        out = []
        for msg in recientes:
            role = "Usuario" if msg["role"] == "user" else "Analista"
            content = msg.get("content", "")
            if isinstance(content, list):
                content = _content_to_text(content)
            content = str(content)[:250]
            if content:
                out.append(f"{role}: {content}")
        return "\n".join(out) if out else "(sin historial)"

    def query(
        self, question: str, history: list[dict] | None = None
    ) -> dict[str, Any]:
        try:
            state_in: BotState = {
                "question": question,
                "history": self._format_history(history),
                "retried": False,
            }
            state_out = self.graph.invoke(state_in)

            answer = state_out.get("final_answer") or "Sin respuesta."
            code = state_out.get("code", "")

            if state_out.get("error"):
                answer = (
                    f"El análisis falló tras un reintento: `{state_out['error']}`\n\n"
                    "Intenta reformular la pregunta."
                )

            return {
                "respuesta": answer,
                "codigo": code or "# (sin código)",
                "error": state_out.get("error") or None,
            }

        except Exception as e:
            return {
                "respuesta": (
                    f"Error en el flujo del bot: **{type(e).__name__}**\n\n"
                    f"Detalle: `{e}`"
                ),
                "codigo": "",
                "error": f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            }