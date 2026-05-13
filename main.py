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
# CONFIG APP
# -----------------------------
app = FastAPI(
    title="AuditCont API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Base temporal en memoria
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
        "message": "AuditCont funcionando correctamente"
    }


# -----------------------------
# ANALIZAR ARCHIVO
# -----------------------------
@app.post("/api/v1/analyze", response_model=AuditResult)
async def analyze_file(file: UploadFile = File(...)):
    
    if not file:
        raise HTTPException(status_code=400, detail="Debe subir un archivo")

    content = await file.read()
    file_size_kb = len(content) / 1024

    try:
        # Leer archivo
        if file.filename.endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(content))
        elif file.filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        else:
            raise HTTPException(
                status_code=400,
                detail="Solo se aceptan archivos Excel o CSV"
            )

        # Normalizar nombres columnas
        df.columns = [
            str(col).lower().strip().replace(" ", "_")
            for col in df.columns
        ]

        print("Columnas detectadas:", df.columns.tolist())

        # Buscar columnas requeridas
        tipo_col = next(
            (c for c in df.columns if "tipo" in c),
            None
        )

        valor_col = next(
            (c for c in df.columns if "valor" in c or "saldo" in c),
            None
        )

        cuenta_col = next(
            (c for c in df.columns if "cuenta" in c),
            None
        )

        if not tipo_col:
            raise HTTPException(
                status_code=400,
                detail="No existe columna tipo"
            )

        if not valor_col:
            raise HTTPException(
                status_code=400,
                detail="No existe columna valor o saldo"
            )

        # Limpiar datos
        df[tipo_col] = df[tipo_col].astype(str).str.upper()

        df[valor_col] = pd.to_numeric(
            df[valor_col],
            errors="coerce"
        ).fillna(0)

        # Totales
        total_activos = df[
            df[tipo_col].str.contains("ACTIVO", na=False)
        ][valor_col].sum()

        total_pasivos = df[
            df[tipo_col].str.contains("PASIVO", na=False)
        ][valor_col].sum()

        total_patrimonio = df[
            df[tipo_col].str.contains("PATRIMONIO", na=False)
        ][valor_col].sum()

        diferencia = total_activos - (
            total_pasivos + total_patrimonio
        )

        balanceado = abs(diferencia) < 1

        findings = []

        if not balanceado:
            findings.append(
                Finding(
                    id=1,
                    type="equation",
                    severity="critical",
                    title="Balance descuadrado",
                    desc=f"""
Activos: {total_activos}
Pasivos: {total_pasivos}
Patrimonio: {total_patrimonio}
Diferencia: {diferencia}
""",
                    account="General",
                    recommendation="Revisar balance contable"
                )
            )

        negativos = df[df[valor_col] < 0]

        if not negativos.empty:
            findings.append(
                Finding(
                    id=2,
                    type="negative",
                    severity="high",
                    title="Valores negativos detectados",
                    desc=f"Se encontraron {len(negativos)} cuentas negativas",
                    account="General",
                    recommendation="Revisar saldos negativos"
                )
            )

        if len(findings) == 0:
            findings.append(
                Finding(
                    id=3,
                    type="success",
                    severity="low",
                    title="Balance correcto",
                    desc="No se encontraron errores",
                    account="General",
                    recommendation="Todo correcto"
                )
            )

        recommendations = [
            "Revisar balances antes de enviar a Supercias",
            "Corregir saldos negativos",
            "Mantener consistencia en tipos de cuenta"
        ]

        audit_id = str(uuid.uuid4())[:8]

        result = AuditResult(
            audit_id=audit_id,
            filename=file.filename,
            filesize=f"{file_size_kb:.2f} KB",
            analyzed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            summary={
                "total_assets": total_activos,
                "total_liabilities": total_pasivos,
                "total_equity": total_patrimonio,
                "difference": diferencia,
                "equation_balanced": balanceado
            },
            findings=findings,
            recommendations=recommendations
        )

        analyses_db[audit_id] = result

        return result

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error procesando archivo: {str(e)}"
        )


# -----------------------------
# PDF
# -----------------------------
@app.get("/api/v1/reports/{audit_id}/pdf")
def generate_pdf(audit_id: str):

    if audit_id not in analyses_db:
        raise HTTPException(
            status_code=404,
            detail="Auditoría no encontrada"
        )

    result = analyses_db[audit_id]

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)

    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(100, 750, "AuditCont Ecuador AI")

    pdf.setFont("Helvetica", 12)
    pdf.drawString(
        100,
        720,
        f"Archivo: {result.filename}"
    )

    pdf.drawString(
        100,
        700,
        f"Fecha: {result.analyzed_at}"
    )

    pdf.drawString(
        100,
        680,
        f"Activos: {result.summary['total_assets']}"
    )

    pdf.drawString(
        100,
        660,
        f"Pasivos: {result.summary['total_liabilities']}"
    )

    pdf.drawString(
        100,
        640,
        f"Patrimonio: {result.summary['total_equity']}"
    )

    pdf.save()
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
# RUN LOCAL
# -----------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000
    )
