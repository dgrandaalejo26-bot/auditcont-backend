import io
import uuid
import pandas as pd
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any

app = FastAPI(title="AuditCont API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

analyses_db = {}

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
    filesize: str
    analyzed_at: str
    summary: Dict[str, Any]
    findings: List[Finding]
    recommendations: List[str]


# ---------------- FUNCIÓN DETECTAR TIPO ----------------

def detect_account_type(code):
    code = str(code)

    if code.startswith("1"):
        return "activo"
    elif code.startswith("2"):
        return "pasivo"
    elif code.startswith("3"):
        return "patrimonio"
    elif code.startswith("4"):
        return "ingreso"
    elif code.startswith("5"):
        return "gasto"
    elif code.startswith("6"):
        return "costo"
    else:
        return "otro"


# ---------------- HEALTH ----------------

@app.get("/health")
def health():
    return {
        "status": "ok"
    }


# ---------------- ANALYZE ----------------

@app.post("/api/v1/analyze", response_model=AuditResult)
async def analyze_file(file: UploadFile = File(...)):

    try:
        content = await file.read()

        if file.filename.endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(content))
        elif file.filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        else:
            raise HTTPException(
                status_code=400,
                detail="Solo se permiten archivos Excel o CSV"
            )

        # normalizar columnas
        df.columns = [
            c.lower().strip()
            .replace(" ", "_")
            .replace("ó", "o")
            for c in df.columns
        ]

        print(df.columns)

        # detectar columnas
        code_col = next(
            (c for c in df.columns if "codigo" in c),
            None
        )

        saldo_col = next(
            (c for c in df.columns if "saldo" in c),
            None
        )

        cuenta_col = next(
            (c for c in df.columns if "cuenta" in c),
            None
        )

        if not code_col:
            raise HTTPException(
                status_code=400,
                detail="No se encontró columna código"
            )

        if not saldo_col:
            raise HTTPException(
                status_code=400,
                detail="No se encontró columna saldo"
            )

        # eliminar filas vacías
        df = df.dropna(subset=[code_col])

        # detectar tipo automáticamente
        df["tipo_detectado"] = df[code_col].apply(detect_account_type)

        # convertir saldo
        df[saldo_col] = pd.to_numeric(
            df[saldo_col],
            errors="coerce"
        ).fillna(0)

        # sumatorias
        activos = df[df["tipo_detectado"] == "activo"][saldo_col].sum()
        pasivos = df[df["tipo_detectado"] == "pasivo"][saldo_col].sum()
        patrimonio = df[df["tipo_detectado"] == "patrimonio"][saldo_col].sum()

        diferencia = activos - (pasivos + patrimonio)
        balanceado = abs(diferencia) < 1

        findings = []

        if not balanceado:
            findings.append(
                Finding(
                    id=1,
                    type="balance",
                    severity="critical",
                    title="Balance descuadrado",
                    desc=f"Diferencia detectada: {diferencia}",
                    account="General",
                    recommendation="Revisar cuentas contables"
                )
            )

        negativos = df[df[saldo_col] < 0]

        if len(negativos) > 0:
            findings.append(
                Finding(
                    id=2,
                    type="negative",
                    severity="high",
                    title="Saldos negativos detectados",
                    desc=f"Se encontraron {len(negativos)} cuentas negativas",
                    account="General",
                    recommendation="Revisar registros negativos"
                )
            )

        audit_id = str(uuid.uuid4())[:8]

        result = AuditResult(
            audit_id=audit_id,
            filename=file.filename,
            filesize=f"{round(len(content)/1024,2)} KB",
            analyzed_at=str(datetime.now()),
            summary={
                "activos": activos,
                "pasivos": pasivos,
                "patrimonio": patrimonio,
                "balanceado": balanceado,
                "diferencia": diferencia
            },
            findings=findings,
            recommendations=[
                "Revisar cuentas negativas",
                "Verificar balance general",
                "Validar consistencia NIIF Ecuador"
            ]
        )

        analyses_db[audit_id] = result

        return result

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
