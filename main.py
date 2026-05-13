import io
import uuid
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="AuditCont API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- MODELOS ----------------

class Finding(BaseModel):
    id: int
    type: str
    severity: str
    title: str
    desc: str
    account: str
    recommendation: str


class AuditResult(BaseModel):
    audit_id: str
    filename: str
    analyzed_at: str
    summary: Dict[str, Any]
    findings: List[Finding]
    recommendations: List[str]


# ---------------- FUNCIONES ----------------

def limpiar_columnas(df):
    df.columns = [
        str(col).strip().lower()
        .replace(" ", "_")
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        for col in df.columns
    ]
    return df


def detectar_columna(df, posibles):
    for col in df.columns:
        for palabra in posibles:
            if palabra in col:
                return col
    return None


# ---------------- HEALTH ----------------

@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------- ANALYZE ----------------

@app.post("/api/v1/analyze")
async def analyze(file: UploadFile = File(...)):

    try:
        content = await file.read()

        # Leer Excel
        if file.filename.endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(content))
        elif file.filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        else:
            raise HTTPException(
                status_code=400,
                detail="Solo se aceptan archivos Excel o CSV"
            )

        # limpiar columnas
        df = limpiar_columnas(df)

        print("COLUMNAS DETECTADAS:")
        print(df.columns.tolist())

        # detectar columnas automáticamente
        cuenta_col = detectar_columna(df, ["cuenta", "codigo"])
        nombre_col = detectar_columna(df, ["nombre"])
        tipo_col = detectar_columna(df, ["tipo"])
        valor_col = detectar_columna(df, ["valor", "saldo"])

        if not valor_col:
            raise HTTPException(
                status_code=400,
                detail=f"No encontré columna de valores. Columnas detectadas: {df.columns.tolist()}"
            )

        if not tipo_col:
            raise HTTPException(
                status_code=400,
                detail=f"No encontré columna TIPO. Columnas detectadas: {df.columns.tolist()}"
            )

        # limpiar datos
        df[valor_col] = pd.to_numeric(df[valor_col], errors="coerce").fillna(0)

        df[tipo_col] = df[tipo_col].astype(str).str.upper()

        activos = df[df[tipo_col].str.contains("ACTIVO")][valor_col].sum()
        pasivos = df[df[tipo_col].str.contains("PASIVO")][valor_col].sum()
        patrimonio = df[df[tipo_col].str.contains("PATRIMONIO")][valor_col].sum()

        diferencia = activos - (pasivos + patrimonio)

        findings = []

        if abs(diferencia) > 1:
            findings.append({
                "id": 1,
                "type": "balance",
                "severity": "high",
                "title": "Balance descuadrado",
                "desc": f"Diferencia detectada: {diferencia}",
                "account": "General",
                "recommendation": "Revisar registros contables"
            })

        negativos = df[df[valor_col] < 0]

        if len(negativos) > 0:
            findings.append({
                "id": 2,
                "type": "negative",
                "severity": "medium",
                "title": "Saldos negativos",
                "desc": f"Se encontraron {len(negativos)} cuentas negativas",
                "account": "General",
                "recommendation": "Revisar saldos"
            })

        return {
            "audit_id": str(uuid.uuid4())[:8],
            "filename": file.filename,
            "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "summary": {
                "activos": activos,
                "pasivos": pasivos,
                "patrimonio": patrimonio,
                "diferencia": diferencia
            },
            "findings": findings,
            "recommendations": [
                "Revisar cuentas descuadradas",
                "Validar saldos negativos"
            ]
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error procesando archivo: {str(e)}"
        )
