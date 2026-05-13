"""
AUDITCONT ECUADOR AI - BACKEND FUNCIONAL
"""

import io
import uuid
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch


# -----------------------------
# CONFIGURACIÓN APP
# -----------------------------
app = FastAPI(title="AuditCont API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# base temporal en memoria
analyses_db = {}


# -----------------------------
# MODELOS
# -----------------------------
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


# -----------------------------
# HEALTH CHECK
# -----------------------------
@app.get("/health")
def health_check():
    return {
        "status": "connected",
        "service": "AuditCont Backend API"
    }


# -----------------------------
# FUNCIÓN DETECTAR TIPO
# -----------------------------
def detectar_tipo_por_codigo(codigo):
    codigo = str(codigo).strip()

    if codigo.startswith("1"):
        return "activo"
    elif codigo.startswith("2"):
        return "pasivo"
    elif codigo.startswith("3"):
        return "patrimonio"
    elif codigo.startswith("4"):
        return "ingreso"
    elif codigo.startswith("5"):
        return "gasto"
    else:
        return "otro"


# -----------------------------
# ANALIZAR ARCHIVO
# -----------------------------
@app.post("/api/v1/analyze", response_model=AuditResult)
async def analyze_file(file: UploadFile = File(...)):

    content = await file.read()
    file_size_kb = len(content) / 1024

    try:
        df = None

        # detectar formato
        if file.filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(
                io.BytesIO(content),
                engine="openpyxl"
            )

        elif file.filename.endswith(".csv"):
            df = pd.read_csv(
                io.BytesIO(content)
            )

        else:
            raise HTTPException(
                status_code=400,
                detail="Solo se permiten archivos Excel o CSV"
            )

        # -----------------------------
        # NORMALIZAR COLUMNAS
        # -----------------------------
        df.columns = [
            str(c).lower().strip().replace(" ", "_")
            for c in df.columns
        ]

        print("COLUMNAS DETECTADAS:")
        print(df.columns.tolist())

        # detectar saldo
        saldo_col = next(
            (
                c for c in df.columns
                if "saldo" in c
                or "balance" in c
            ),
            None
        )

        # detectar tipo cuenta
        tipo_col = next(
            (
                c for c in df.columns
                if "tipo_cuenta" in c
                or "tipo" in c
                or "clase" in c
            ),
            None
        )

        # detectar código
        codigo_col = next(
            (
                c for c in df.columns
                if "codigo" in c
                or "código" in c
                or "cod" in c
            ),
            None
        )

        # fallback saldo
        if not saldo_col:
            numeric_cols = df.select_dtypes(
                include="number"
            ).columns

            if len(numeric_cols) > 0:
                saldo_col = numeric_cols[-1]

        if not saldo_col:
            raise HTTPException(
                status_code=400,
                detail="No se encontró columna saldo"
            )

        # limpiar saldo
        df[saldo_col] = pd.to_numeric(
            df[saldo_col],
            errors="coerce"
        ).fillna(0)

        # -----------------------------
        # DETECTAR TIPO DE CUENTA
        # -----------------------------
        if tipo_col:
            df["tipo_detectado"] = (
                df[tipo_col]
                .astype(str)
                .str.lower()
            )

        elif codigo_col:
            df["tipo_detectado"] = df[
                codigo_col
            ].apply(detectar_tipo_por_codigo)

        else:
            raise HTTPException(
                status_code=400,
                detail="No se encontró tipo_cuenta ni código contable"
            )

        # -----------------------------
        # CALCULAR TOTALES
        # -----------------------------
        assets = df[
            df["tipo_detectado"].str.contains(
                "activo",
                na=False
            )
        ][saldo_col].sum()

        liabilities = df[
            df["tipo_detectado"].str.contains(
                "pasivo",
                na=False
            )
        ][saldo_col].sum()

        equity = df[
            df["tipo_detectado"].str.contains(
                "patrimonio",
                na=False
            )
        ][saldo_col].sum()

        income = df[
            df["tipo_detectado"].str.contains(
                "ingreso",
                na=False
            )
        ][saldo_col].sum()

        expenses = df[
            df["tipo_detectado"].str.contains(
                "gasto",
                na=False
            )
        ][saldo_col].sum()

        # ecuación contable
        difference = assets - (
            liabilities + equity
        )

        balanced = abs(difference) < 1

        findings = []

        # -----------------------------
        # BALANCE DESCUADRADO
        # -----------------------------
        if not balanced:
            findings.append(
                Finding(
                    id=1,
                    type="equation",
                    severity="critical",
                    title="Balance descuadrado",
                    desc=f"""
Activos: ${assets:,.2f}
Pasivos: ${liabilities:,.2f}
Patrimonio: ${equity:,.2f}
Diferencia: ${difference:,.2f}
""",
                    account="General",
                    recommendation="Revisar registros contables."
                )
            )

        # -----------------------------
        # SALDOS NEGATIVOS
        # -----------------------------
        negatives = df[
            df[saldo_col] < 0
        ]

        if not negatives.empty:
            findings.append(
                Finding(
                    id=2,
                    type="negative",
                    severity="high",
                    title="Saldos negativos detectados",
                    desc=f"Se detectaron {len(negatives)} cuentas con saldo negativo.",
                    account="General",
                    recommendation="Revisar registros contables."
                )
            )

        # si todo está correcto
        if len(findings) == 0:
            findings.append(
                Finding(
                    id=3,
                    type="success",
                    severity="low",
                    title="Balance correcto",
                    desc="No se detectaron errores críticos.",
                    account="General",
                    recommendation="Archivo listo para revisión."
                )
            )

        recommendations = [
            "Verificar clasificación contable",
            "Revisar saldos negativos",
            "Validar ecuación contable",
            "Analizar ingresos y gastos"
        ]

        audit_id = str(uuid.uuid4())[:8]

        result = AuditResult(
            audit_id=audit_id,
            filename=file.filename,
            filesize=f"{file_size_kb:.1f} KB",
            analyzed_at=datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            summary={
                "total_assets": assets,
                "total_liabilities": liabilities,
                "total_equity": equity,
                "total_income": income,
                "total_expenses": expenses,
                "equation_balanced": balanced,
                "difference": difference
            },
            findings=findings,
            recommendations=recommendations
        )

        analyses_db[audit_id] = result

        return result

    except HTTPException:
        raise

    except Exception as e:
        print("ERROR:", str(e))

        raise HTTPException(
            status_code=500,
            detail=f"Error procesando archivo: {str(e)}"
        )


# -----------------------------
# GENERAR PDF
# -----------------------------
@app.get("/api/v1/reports/{audit_id}/pdf")
def download_report(audit_id: str):

    if audit_id not in analyses_db:
        raise HTTPException(
            status_code=404,
            detail="Auditoría no encontrada"
        )

    res = analyses_db[audit_id]

    buffer = io.BytesIO()
    c = canvas.Canvas(
        buffer,
        pagesize=letter
    )

    width, height = letter

    c.setFont("Helvetica-Bold", 20)
    c.drawString(
        inch,
        height - inch,
        "AuditCont Ecuador AI"
    )

    c.setFont("Helvetica", 12)
    c.drawString(
        inch,
        height - 1.5 * inch,
        f"Archivo: {res.filename}"
    )

    c.drawString(
        inch,
        height - 2 * inch,
        f"Fecha: {res.analyzed_at}"
    )

    y = height - 3 * inch

    c.setFont("Helvetica-Bold", 14)
    c.drawString(
        inch,
        y,
        "Hallazgos:"
    )

    y -= 0.5 * inch

    c.setFont("Helvetica", 11)

    for finding in res.findings:
        c.drawString(
            inch,
            y,
            f"- {finding.title}"
        )

        y -= 0.4 * inch

        if y < inch:
            c.showPage()
            y = height - inch

    c.save()

    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition":
            f"attachment; filename=reporte_{audit_id}.pdf"
        }
    )


# -----------------------------
# EJECUCIÓN LOCAL
# -----------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000
    )
