import io
import hashlib
import hmac
from pathlib import Path
import uuid

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from PIL import Image, ImageOps
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak
)
from reportlab.graphics.shapes import (
    Drawing,
    Line,
    String,
    PolyLine
)

from supabase import create_client

st.set_page_config(
    page_title="PDP Control Center Chinalco - MAININ",
    page_icon="📊",
    layout="wide"
)

# =====================================================
# CONEXIÓN SUPABASE
# =====================================================

@st.cache_resource
def conectar_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]

    return create_client(url, key)


@st.cache_resource
def conectar_supabase_admin():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_ADMIN_KEY"]

    return create_client(url, key)


supabase = conectar_supabase()
supabase_admin = conectar_supabase_admin()


# =====================================================
# CONFIGURACIÓN GENERAL
# =====================================================

AREAS = [
    "MOLINOS",
    "CHANCADO",
    "FLOTACION",
    "RELAVES"
]

# =====================================================
# FUNCIONES DE IMPORTACIÓN
# =====================================================

def limpiar_texto(valor):
    if pd.isna(valor):
        return None

    texto = str(valor).strip()

    if texto == "":
        return None

    return texto


def limpiar_numero(valor, default=None):
    if pd.isna(valor):
        return default

    try:
        return float(valor)
    except Exception:
        return default


def limpiar_entero(valor, default=None):
    if pd.isna(valor):
        return default

    try:
        return int(float(valor))
    except Exception:
        return default


def limpiar_fecha(valor):
    if pd.isna(valor):
        return None

    try:
        fecha = pd.to_datetime(valor)
        return fecha.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None


# =====================================================
# EVIDENCIAS FOTOGRÁFICAS
# =====================================================

BUCKET_EVIDENCIAS = "evidencias-ots"


def comprimir_imagen(
    archivo,
    max_dimension=1600,
    calidad=80
):
    """
    Comprime automáticamente fotografías provenientes
    de celular o PC y devuelve bytes JPEG optimizados.
    """

    archivo.seek(0)

    imagen = Image.open(archivo)

    # Corrige la orientación EXIF de fotografías de celular
    imagen = ImageOps.exif_transpose(imagen)

    # Convierte PNG / WEBP / transparencias a RGB
    if imagen.mode in ("RGBA", "LA", "P"):

        if imagen.mode == "P":
            imagen = imagen.convert("RGBA")

        fondo = Image.new(
            "RGB",
            imagen.size,
            "white"
        )

        if imagen.mode in ("RGBA", "LA"):
            fondo.paste(
                imagen,
                mask=imagen.getchannel("A")
            )
        else:
            fondo.paste(imagen)

        imagen = fondo

    elif imagen.mode != "RGB":
        imagen = imagen.convert("RGB")

    # Reduce resolución manteniendo proporción
    imagen.thumbnail(
        (max_dimension, max_dimension),
        Image.Resampling.LANCZOS
    )

    salida = io.BytesIO()

    imagen.save(
        salida,
        format="JPEG",
        quality=calidad,
        optimize=True,
        progressive=True
    )

    salida.seek(0)

    return salida.getvalue()


def subir_evidencia(
    archivo,
    ot,
    codigo_actividad,
    tipo_evidencia
):
    """
    Comprime y sube una fotografía al bucket evidencias-ots.
    Retorna la metadata que se almacenará en el JSONB
    avances_actividad.evidencias.
    """

    bytes_originales = archivo.getvalue()
    tamano_original = len(bytes_originales)

    bytes_comprimidos = comprimir_imagen(
        archivo,
        max_dimension=1600,
        calidad=80
    )

    tamano_comprimido = len(bytes_comprimidos)

    ahorro = (
        (1 - tamano_comprimido / tamano_original) * 100
        if tamano_original > 0
        else 0
    )

    ot_segura = "".join(
        caracter
        for caracter in str(ot)
        if caracter.isalnum() or caracter in "-_"
    )

    actividad_segura = "".join(
        caracter
        for caracter in str(codigo_actividad)
        if caracter.isalnum() or caracter in "-_"
    )

    tipo_seguro = "".join(
        caracter
        for caracter in str(tipo_evidencia).lower()
        if caracter.isalnum() or caracter in "-_"
    )

    nombre_archivo = (
        f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_"
        f"{uuid.uuid4().hex[:10]}.jpg"
    )

    ruta = (
        f"{ot_segura}/"
        f"{actividad_segura}/"
        f"{tipo_seguro}/"
        f"{nombre_archivo}"
    )

    (
        supabase
        .storage
        .from_(BUCKET_EVIDENCIAS)
        .upload(
            path=ruta,
            file=bytes_comprimidos,
            file_options={
                "content-type": "image/jpeg",
                "upsert": "false"
            }
        )
    )

    url_publica = (
        supabase
        .storage
        .from_(BUCKET_EVIDENCIAS)
        .get_public_url(ruta)
    )

    return {
        "url": url_publica,
        "path": ruta,
        "nombre_original": archivo.name,
        "tipo": tipo_evidencia,
        "tamano_original": tamano_original,
        "tamano_comprimido": tamano_comprimido,
        "ahorro_pct": round(ahorro, 1)
    }


def subir_evidencias(
    archivos,
    ot,
    codigo_actividad,
    tipo_evidencia
):
    """
    Procesa varias fotografías y devuelve una lista JSON.
    """

    evidencias = []

    for archivo in archivos or []:

        evidencia = subir_evidencia(
            archivo,
            ot,
            codigo_actividad,
            tipo_evidencia
        )

        evidencias.append(evidencia)

    return evidencias


# =====================================================
# FUNCIONES DEL DASHBOARD
# =====================================================

def latest_progress(progress: pd.DataFrame) -> pd.DataFrame:
    if progress.empty:
        return pd.DataFrame(
            columns=["actividad_id", "avance"]
        )

    data = progress.copy()

    data["fecha_registro"] = pd.to_datetime(
        data["fecha_registro"],
        errors="coerce",
        utc=True
    )

    return (
        data
        .sort_values("fecha_registro")
        .groupby("actividad_id", as_index=False)
        .tail(1)
    )


def build_activity_status(
    activities: pd.DataFrame,
    progress: pd.DataFrame
) -> pd.DataFrame:

    if activities.empty:
        return activities.copy()

    latest = latest_progress(progress)

    if latest.empty:
        result = activities.copy()
        result["avance_real"] = 0.0

    else:
        columnas_avance = [
            "actividad_id",
            "avance",
            "descripcion_avance",
            "observaciones",
            "fecha_registro"
        ]

        columnas_disponibles = [
            c for c in columnas_avance
            if c in latest.columns
        ]

        result = activities.merge(
            latest[columnas_disponibles],
            left_on="id",
            right_on="actividad_id",
            how="left"
        )

        result["avance_real"] = pd.to_numeric(
            result.get("avance", 0),
            errors="coerce"
        ).fillna(0)

    if "peso" not in result.columns:
        result["peso"] = 1.0

    result["peso"] = pd.to_numeric(
        result["peso"],
        errors="coerce"
    ).fillna(1)

    return result


def weighted_progress(
    activity_status: pd.DataFrame
) -> float:

    if activity_status.empty:
        return 0.0

    denominator = activity_status["peso"].sum()

    if denominator <= 0:
        return float(
            activity_status["avance_real"].mean()
        )

    return float(
        (
            activity_status["avance_real"]
            * activity_status["peso"]
        ).sum()
        / denominator
    )


def compute_kpis(
    activities: pd.DataFrame,
    progress: pd.DataFrame
) -> dict:

    status = build_activity_status(
        activities,
        progress
    )

    if status.empty:
        return {
            "avance_general": 0.0,
            "actividades": 0,
            "culminadas": 0,
            "parciales": 0,
            "no_iniciadas": 0,
            "pendientes": 0,
            "spi": 0.0,
            "hh_plan": 0.0,
            "hh_ganadas": 0.0
        }

    # REAL general con la misma metodología de la Curva S original:
    # promedio simple del último avance de TODAS las actividades.
    avance_general = float(
        status["avance_real"].mean()
    ) if not status.empty else 0.0

    culminadas = int(
        (status["avance_real"] >= 100).sum()
    )

    parciales = int(
        (
            (status["avance_real"] > 0)
            & (status["avance_real"] < 100)
        ).sum()
    )

    no_iniciadas = int(
        (status["avance_real"] <= 0).sum()
    )

    pendientes = int(
        (status["avance_real"] < 100).sum()
    )

    if "hh_plan" in status.columns:
        hh_plan_series = pd.to_numeric(
            status["hh_plan"],
            errors="coerce"
        ).fillna(0)
    else:
        hh_plan_series = pd.Series(
            0.0,
            index=status.index
        )

    hh_plan = float(
        hh_plan_series.sum()
    )

    hh_ganadas = float(
        (
            hh_plan_series
            * status["avance_real"]
            / 100
        ).sum()
    )

    # =====================================================
    # PLAN ACTUAL
    # Misma metodología de la Curva S:
    # promedio simple del avance esperado de todas
    # las actividades según la fecha/hora actual.
    # =====================================================

    inicio = pd.to_datetime(
        status["inicio_plan"],
        errors="coerce"
    )

    fin = pd.to_datetime(
        status["fin_plan"],
        errors="coerce"
    )

    ahora = pd.Timestamp.now(tz="America/Lima").tz_localize(None)

    avances_plan_actual = []

    for fecha_inicio, fecha_fin in zip(inicio, fin):

        if pd.isna(fecha_inicio) or pd.isna(fecha_fin):
            avances_plan_actual.append(0.0)
            continue

        if fecha_fin <= fecha_inicio:
            fecha_fin = (
                fecha_inicio
                + pd.Timedelta(minutes=1)
            )

        if ahora <= fecha_inicio:
            avance_plan_actividad = 0.0

        elif ahora >= fecha_fin:
            avance_plan_actividad = 100.0

        else:
            duracion = (
                fecha_fin - fecha_inicio
            ).total_seconds()

            transcurrido = (
                ahora - fecha_inicio
            ).total_seconds()

            avance_plan_actividad = (
                transcurrido
                / duracion
                * 100.0
                if duracion > 0
                else 100.0
            )

        avances_plan_actual.append(
            max(
                0.0,
                min(
                    100.0,
                    avance_plan_actividad
                )
            )
        )

    plan_actual = (
        float(
            sum(avances_plan_actual)
            / len(avances_plan_actual)
        )
        if avances_plan_actual
        else 0.0
    )

    spi = (
        avance_general / plan_actual
        if plan_actual > 0
        else 0.0
    )
    return {
        "avance_general": avance_general,
        "avance_plan": plan_actual,
        "actividades": len(status),
        "culminadas": culminadas,
        "parciales": parciales,
        "no_iniciadas": no_iniciadas,
        "pendientes": pendientes,
        "spi": spi,
        "hh_plan": hh_plan,
        "hh_ganadas": hh_ganadas
    }


def build_s_curve(
    activities: pd.DataFrame,
    progress: pd.DataFrame
) -> pd.DataFrame:

    if activities.empty:
        return pd.DataFrame(
            columns=["fecha", "PLAN", "REAL"]
        )

    acts = activities.copy()

    acts["inicio_plan"] = pd.to_datetime(
        acts["inicio_plan"],
        errors="coerce"
    )

    acts["fin_plan"] = pd.to_datetime(
        acts["fin_plan"],
        errors="coerce"
    )

    valid = acts.dropna(
        subset=[
            "id",
            "inicio_plan",
            "fin_plan"
        ]
    ).copy()

    if valid.empty:
        return pd.DataFrame(
            columns=["fecha", "PLAN", "REAL"]
        )

    invalidas = (
        valid["fin_plan"]
        <= valid["inicio_plan"]
    )

    valid.loc[
        invalidas,
        "fin_plan"
    ] = (
        valid.loc[
            invalidas,
            "inicio_plan"
        ]
        + pd.Timedelta(minutes=1)
    )

    inicio_programa = (
        valid["inicio_plan"].min()
    )

    fin_programa = (
        valid["fin_plan"].max()
    )

    cortes = [inicio_programa]

    dia = inicio_programa.normalize()
    dia_final = fin_programa.normalize()

    horas_corte = [0, 7, 14, 19]

    while dia <= dia_final:

        for hora in horas_corte:

            corte = (
                dia
                + pd.Timedelta(hours=hora)
            )

            if (
                inicio_programa
                < corte
                < fin_programa
            ):
                cortes.append(corte)

        dia += pd.Timedelta(days=1)

    cortes.append(fin_programa)

    # =====================================================
    # PUNTO EN VIVO
    # =====================================================
    # Los cortes oficiales se mantienen en:
    # 00:00 / 07:00 / 14:00 / 19:00.
    #
    # Además agregamos la hora actual mientras la parada
    # está en ejecución. Esto permite que la curva REAL
    # muestre el avance acumulado registrado hasta este
    # momento, aunque el último reporte haya ocurrido
    # después del último corte oficial.
    ahora_lima = (
        pd.Timestamp.now(
            tz="America/Lima"
        )
        .tz_localize(None)
    )

    if (
        inicio_programa
        < ahora_lima
        < fin_programa
    ):
        cortes.append(ahora_lima)

    cortes = sorted(
        pd.Series(cortes)
        .drop_duplicates()
        .tolist()
    )

    total_actividades = len(valid)

    plan_values = []

    for corte in cortes:

        suma_plan = 0.0

        for _, actividad in valid.iterrows():

            inicio_act = (
                actividad["inicio_plan"]
            )

            fin_act = (
                actividad["fin_plan"]
            )

            if corte <= inicio_act:
                avance = 0.0

            elif corte >= fin_act:
                avance = 100.0

            else:
                duracion = (
                    fin_act - inicio_act
                ).total_seconds()

                transcurrido = (
                    corte - inicio_act
                ).total_seconds()

                avance = (
                    transcurrido
                    / duracion
                    * 100
                    if duracion > 0
                    else 100
                )

            suma_plan += max(
                0,
                min(100, avance)
            )

        plan_values.append(
            suma_plan
            / total_actividades
        )

    prog = progress.copy()

    if not prog.empty:

        prog["fecha_registro"] = (
            pd.to_datetime(
                prog["fecha_registro"],
                errors="coerce",
                utc=True
            )
            .dt.tz_convert("America/Lima")
            .dt.tz_localize(None)
        )

        prog["avance"] = pd.to_numeric(
            prog["avance"],
            errors="coerce"
        ).fillna(0).clip(0, 100)

        prog = prog.dropna(
            subset=[
                "actividad_id",
                "fecha_registro"
            ]
        )

    real_values = []

    ids_actividades = (
        valid["id"].tolist()
    )

    for corte in cortes:

        if prog.empty:

            real_values.append(
                0.0
                if corte <= ahora_lima
                else None
            )

            continue

        # IMPORTANTE:
        # La curva REAL debe mantener el último avance conocido
        # hasta la hora actual. No debe desaparecer solo porque
        # el último reporte ocurrió antes que el punto EN VIVO.
        #
        # Únicamente ocultamos puntos que realmente están en el futuro.
        if corte > ahora_lima:
            real_values.append(None)
            continue

        disponibles = prog[
            prog["fecha_registro"] <= corte
        ]

        if disponibles.empty:

            real_values.append(0.0)
            continue

        ultimos = (
            disponibles
            .sort_values("fecha_registro")
            .groupby(
                "actividad_id",
                as_index=False
            )
            .tail(1)
            .set_index("actividad_id")[
                "avance"
            ]
            .to_dict()
        )

        suma_real = sum(
            float(
                ultimos.get(
                    actividad_id,
                    0
                )
            )
            for actividad_id
            in ids_actividades
        )

        real_values.append(
            suma_real
            / total_actividades
        )

    curva = pd.DataFrame({
        "fecha": pd.to_datetime(cortes),
        "PLAN": plan_values,
        "REAL": real_values
    })

    curva["PLAN"] = (
        pd.to_numeric(
            curva["PLAN"],
            errors="coerce"
        )
        .fillna(0)
        .clip(0, 100)
        .cummax()
    )

    indices_real = (
        curva.index[
            curva["REAL"].notna()
        ]
        .tolist()
    )

    if indices_real:

        curva.loc[
            indices_real,
            "REAL"
        ] = (
            pd.to_numeric(
                curva.loc[
                    indices_real,
                    "REAL"
                ],
                errors="coerce"
            )
            .fillna(0)
            .clip(0, 100)
            .cummax()
        )

    curva.loc[
        curva.index[0],
        "PLAN"
    ] = 0.0

    curva.loc[
        curva.index[-1],
        "PLAN"
    ] = 100.0

    if pd.isna(
        curva.loc[
            curva.index[0],
            "REAL"
        ]
    ):
        curva.loc[
            curva.index[0],
            "REAL"
        ] = 0.0

    return curva


# =====================================================
# INFORME DIARIO AUTOMÁTICO
# =====================================================

def construir_resumen_diario(
    ots: pd.DataFrame,
    actividades: pd.DataFrame,
    avances: pd.DataFrame,
    nombre_area: str,
    fecha_objetivo
) -> str:

    if actividades.empty:
        return (
            f"Informe diario - {nombre_area}\n\n"
            "No existen actividades cargadas para esta área."
        )

    estado = build_activity_status(
        actividades,
        avances
    )

    kpis = compute_kpis(
        actividades,
        avances
    )

    if avances.empty:

        diarios = pd.DataFrame()

    else:

        fechas_lima = pd.to_datetime(
            avances["fecha_registro"],
            errors="coerce",
            utc=True
        ).dt.tz_convert("America/Lima")

        diarios = avances[
            fechas_lima.dt.date == fecha_objetivo
        ].copy()

        if not diarios.empty:
            diarios["fecha_lima"] = fechas_lima.loc[
                diarios.index
            ]

    lineas = [
        (
            f"INFORME DIARIO DE CONTROL DE OTs - "
            f"{nombre_area.upper()}"
        ),
        f"Fecha: {fecha_objetivo.strftime('%d/%m/%Y')}",
        "",
        "RESUMEN EJECUTIVO",
        (
            f"- OTs registradas: "
            f"{ots['id'].nunique() if not ots.empty else 0}."
        ),
        (
            f"- Actividades programadas: "
            f"{kpis['actividades']}."
        ),
        (
            f"- Avance general acumulado: "
            f"{kpis['avance_general']:.1f}%."
        ),
        (
            f"- Actividades culminadas: "
            f"{kpis['culminadas']}."
        ),
        (
            f"- Actividades en ejecución: "
            f"{kpis['parciales']}."
        ),
        (
            f"- Actividades no iniciadas: "
            f"{kpis['no_iniciadas']}."
        ),
        (
            f"- HH planificadas: "
            f"{kpis['hh_plan']:.0f}."
        ),
        (
            f"- HH ganadas: "
            f"{kpis['hh_ganadas']:.0f}."
        ),
        (
            f"- SPI: "
            f"{kpis['spi']:.2f}."
        ),
        "",
        (
            f"REGISTROS REALIZADOS EL DÍA: "
            f"{len(diarios)}"
        )
    ]

    if diarios.empty:

        lineas += [
            "",
            "No se registraron avances durante la fecha seleccionada."
        ]

    else:

        actividad_lookup = (
            actividades
            .set_index("id")
        )

        ot_lookup = (
            ots
            .set_index("id")
            if not ots.empty
            else pd.DataFrame()
        )

        principales = diarios.sort_values(
            "fecha_lima",
            ascending=False
        ).head(10)

        lineas += [
            "",
            "PRINCIPALES ACTUALIZACIONES"
        ]

        for _, registro in principales.iterrows():

            actividad_id = registro.get(
                "actividad_id"
            )

            codigo = ""
            descripcion_actividad = ""
            ot_numero = ""
            equipo = ""

            if (
                actividad_id in actividad_lookup.index
            ):

                actividad = actividad_lookup.loc[
                    actividad_id
                ]

                codigo = str(
                    actividad.get(
                        "codigo_actividad",
                        ""
                    )
                )

                descripcion_actividad = str(
                    actividad.get(
                        "descripcion",
                        ""
                    )
                )

                ot_id = actividad.get(
                    "ot_id"
                )

                if (
                    not ot_lookup.empty
                    and ot_id in ot_lookup.index
                ):

                    ot_info = ot_lookup.loc[
                        ot_id
                    ]

                    ot_numero = str(
                        ot_info.get(
                            "ot",
                            ""
                        )
                    )

                    equipo = str(
                        ot_info.get(
                            "equipo",
                            ""
                        )
                    )

            hora = ""

            fecha_registro = registro.get(
                "fecha_lima"
            )

            if pd.notna(fecha_registro):
                hora = fecha_registro.strftime(
                    "%H:%M"
                )

            descripcion_reporte = (
                registro.get(
                    "descripcion_avance"
                )
                or descripcion_actividad
                or ""
            )

            lineas.append(
                f"- {hora} | OT {ot_numero} | "
                f"{equipo} | {codigo} | "
                f"{registro.get('avance', 0)}% | "
                f"{descripcion_reporte}"
            )

        observaciones = (
            diarios.get(
                "observaciones",
                pd.Series(
                    dtype="object"
                )
            )
            .fillna("")
            .astype(str)
        )

        observaciones = [
            texto.strip()
            for texto in observaciones
            if texto.strip()
        ]

        if observaciones:

            lineas += [
                "",
                "OBSERVACIONES / RESTRICCIONES"
            ]

            for observacion in observaciones[:10]:
                lineas.append(
                    f"- {observacion}"
                )

        criticos = diarios[
            diarios.get(
                "critica",
                False
            ).fillna(False)
            if "critica" in diarios.columns
            else pd.Series(
                False,
                index=diarios.index
            )
        ]

        if not criticos.empty:

            lineas += [
                "",
                "ACTIVIDADES MARCADAS COMO CRÍTICAS"
            ]

            for _, registro in criticos.head(
                10
            ).iterrows():

                actividad_id = registro.get(
                    "actividad_id"
                )

                if (
                    actividad_id
                    in actividad_lookup.index
                ):

                    actividad = actividad_lookup.loc[
                        actividad_id
                    ]

                    lineas.append(
                        f"- "
                        f"{actividad.get('codigo_actividad', '')}: "
                        f"{registro.get('avance', 0)}% - "
                        f"{registro.get('descripcion_avance', '')}"
                    )

    pendientes = estado[
        estado["avance_real"] < 100
    ].copy()

    if not pendientes.empty:

        pendientes = pendientes.sort_values(
            [
                "critica",
                "avance_real"
            ],
            ascending=[
                False,
                True
            ]
        )

        lineas += [
            "",
            "PENDIENTES PRINCIPALES"
        ]

        for _, actividad in pendientes.head(
            10
        ).iterrows():

            lineas.append(
                f"- "
                f"{actividad.get('codigo_actividad', '')}: "
                f"{actividad.get('descripcion', '')} | "
                f"Avance {actividad.get('avance_real', 0):.1f}%"
            )

    return "\n".join(lineas)



# =====================================================
# SECCIONES EDITABLES DEL INFORME DIARIO
# =====================================================

def construir_secciones_informe_diario(
    ots: pd.DataFrame,
    actividades: pd.DataFrame,
    avances: pd.DataFrame,
    nombre_area: str,
    fecha_objetivo
) -> dict:

    estado = build_activity_status(
        actividades,
        avances
    )

    kpis = compute_kpis(
        actividades,
        avances
    )

    # Avances de la fecha seleccionada
    if avances.empty:
        diarios = pd.DataFrame()
    else:
        fechas_lima = pd.to_datetime(
            avances["fecha_registro"],
            errors="coerce",
            utc=True
        ).dt.tz_convert("America/Lima")

        diarios = avances[
            fechas_lima.dt.date == fecha_objetivo
        ].copy()

        if not diarios.empty:
            diarios["fecha_lima"] = fechas_lima.loc[
                diarios.index
            ]

    # -------------------------------------------------
    # RESUMEN EJECUTIVO
    # -------------------------------------------------
    resumen = (
        f"OTs registradas: "
        f"{ots['id'].nunique() if not ots.empty else 0}\n"
        f"Actividades programadas: {kpis['actividades']}\n"
        f"Avance general acumulado: {kpis['avance_general']:.1f}%\n"
        f"Actividades culminadas: {kpis['culminadas']}\n"
        f"Actividades en ejecución: {kpis['parciales']}\n"
        f"Actividades no iniciadas: {kpis['no_iniciadas']}\n"
        f"HH planificadas: {kpis['hh_plan']:.0f}\n"
        f"HH ganadas: {kpis['hh_ganadas']:.0f}\n"
        f"SPI: {kpis['spi']:.2f}"
    )

    # -------------------------------------------------
    # PRINCIPALES ACTUALIZACIONES
    # -------------------------------------------------
    actualizaciones = []

    if not diarios.empty:
        actividad_lookup = actividades.set_index("id")
        ot_lookup = (
            ots.set_index("id")
            if not ots.empty
            else pd.DataFrame()
        )

        principales = diarios.sort_values(
            "fecha_lima",
            ascending=False
        ).head(10)

        for _, registro in principales.iterrows():

            actividad_id = registro.get("actividad_id")
            codigo = ""
            ot_numero = ""
            equipo = ""

            if actividad_id in actividad_lookup.index:
                actividad = actividad_lookup.loc[actividad_id]

                codigo = str(
                    actividad.get("codigo_actividad", "")
                )

                ot_id = actividad.get("ot_id")

                if (
                    not ot_lookup.empty
                    and ot_id in ot_lookup.index
                ):
                    ot_info = ot_lookup.loc[ot_id]
                    ot_numero = str(ot_info.get("ot", ""))
                    equipo = str(ot_info.get("equipo", ""))

            hora = ""
            fecha_registro = registro.get("fecha_lima")

            if pd.notna(fecha_registro):
                hora = fecha_registro.strftime("%H:%M")

            detalle = (
                registro.get("descripcion_avance")
                or ""
            )

            actualizaciones.append(
                f"{hora} | OT {ot_numero} | {equipo} | "
                f"{codigo} | {registro.get('avance', 0)}% | "
                f"{detalle}"
            )

    if not actualizaciones:
        actualizaciones = [
            "No se registraron avances durante la fecha seleccionada."
        ]

    # -------------------------------------------------
    # OBSERVACIONES / RESTRICCIONES
    # -------------------------------------------------
    observaciones = []

    if not diarios.empty and "observaciones" in diarios.columns:

        actividad_lookup_obs = (
            actividades.set_index("id")
            if not actividades.empty
            else pd.DataFrame()
        )

        ot_lookup_obs = (
            ots.set_index("id")
            if not ots.empty
            else pd.DataFrame()
        )

        for _, registro_obs in diarios.iterrows():

            observacion = str(
                registro_obs.get(
                    "observaciones",
                    ""
                )
                or ""
            ).strip()

            if not observacion:
                continue

            actividad_id_obs = registro_obs.get(
                "actividad_id"
            )

            codigo_obs = ""
            descripcion_obs = ""
            ot_numero_obs = ""
            equipo_obs = ""

            if (
                not actividad_lookup_obs.empty
                and actividad_id_obs
                in actividad_lookup_obs.index
            ):

                actividad_obs = (
                    actividad_lookup_obs.loc[
                        actividad_id_obs
                    ]
                )

                codigo_obs = str(
                    actividad_obs.get(
                        "codigo_actividad",
                        ""
                    )
                )

                descripcion_obs = str(
                    actividad_obs.get(
                        "descripcion",
                        ""
                    )
                )

                ot_id_obs = actividad_obs.get(
                    "ot_id"
                )

                if (
                    not ot_lookup_obs.empty
                    and ot_id_obs
                    in ot_lookup_obs.index
                ):

                    ot_obs = ot_lookup_obs.loc[
                        ot_id_obs
                    ]

                    ot_numero_obs = str(
                        ot_obs.get(
                            "ot",
                            ""
                        )
                    )

                    equipo_obs = str(
                        ot_obs.get(
                            "equipo",
                            ""
                        )
                    )

            observaciones.append(
                f"OT {ot_numero_obs} | "
                f"{descripcion_obs} | "
                f"{observacion}"
            )

    if not observaciones:
        observaciones = [
            "Sin observaciones o restricciones registradas."
        ]

    # -------------------------------------------------
    # ACTIVIDADES CRÍTICAS
    # -------------------------------------------------
    criticas = []

    if not diarios.empty and "critica" in diarios.columns:
        actividad_lookup = actividades.set_index("id")

        for _, registro in diarios[
            diarios["critica"].fillna(False)
        ].head(10).iterrows():

            actividad_id = registro.get("actividad_id")

            if actividad_id in actividad_lookup.index:
                actividad = actividad_lookup.loc[actividad_id]

                criticas.append(
                    f"{actividad.get('codigo_actividad', '')} | "
                    f"{registro.get('avance', 0)}% | "
                    f"{registro.get('descripcion_avance', '')}"
                )

    if not criticas:
        criticas = [
            "No se registraron actividades críticas en la fecha seleccionada."
        ]

    # -------------------------------------------------
    # PENDIENTES PRINCIPALES
    # -------------------------------------------------
    pendientes = estado[
        estado["avance_real"] < 100
    ].copy()

    pendientes_texto = []

    if not pendientes.empty:

        if "critica" in pendientes.columns:
            pendientes["critica"] = (
                pendientes["critica"]
                .fillna(False)
            )
            pendientes = pendientes.sort_values(
                ["critica", "avance_real"],
                ascending=[False, True]
            )
        else:
            pendientes = pendientes.sort_values(
                "avance_real",
                ascending=True
            )

        for _, actividad in pendientes.head(10).iterrows():
            pendientes_texto.append(
                f"{actividad.get('codigo_actividad', '')} | "
                f"{actividad.get('descripcion', '')} | "
                f"Avance {float(actividad.get('avance_real', 0)):.1f}%"
            )

    if not pendientes_texto:
        pendientes_texto = [
            "No existen actividades pendientes."
        ]

    return {
        "resumen": resumen,
        "actualizaciones": "\n".join(
            f"• {item}" for item in actualizaciones
        ),
        "observaciones": "\n".join(
            f"• {item}" for item in observaciones
        ),
        "criticas": "\n".join(
            f"• {item}" for item in criticas
        ),
        "pendientes": "\n".join(
            f"• {item}" for item in pendientes_texto
        )
    }




# =====================================================
# COMPONENTES GERENCIALES PARA PDF
# =====================================================

def calcular_semaforo_pdf(
    actividades: pd.DataFrame,
    avances: pd.DataFrame
) -> pd.DataFrame:

    estado = build_activity_status(
        actividades,
        avances
    )

    if estado.empty:
        return estado

    ahora = pd.Timestamp.now(tz="America/Lima").tz_localize(None)

    inicio = pd.to_datetime(
        estado.get("inicio_plan"),
        errors="coerce"
    )

    fin = pd.to_datetime(
        estado.get("fin_plan"),
        errors="coerce"
    )

    real = pd.to_numeric(
        estado.get("avance_real", 0),
        errors="coerce"
    ).fillna(0)

    planes = []

    for ini, fn in zip(inicio, fin):

        if pd.isna(ini) or pd.isna(fn):
            planes.append(0.0)
            continue

        if fn <= ini:
            fn = ini + pd.Timedelta(minutes=1)

        if ahora <= ini:
            plan = 0.0
        elif ahora >= fn:
            plan = 100.0
        else:
            total = (fn - ini).total_seconds()
            transcurrido = (ahora - ini).total_seconds()
            plan = (
                transcurrido / total * 100
                if total > 0
                else 100.0
            )

        planes.append(
            max(0.0, min(100.0, float(plan)))
        )

    estado["PLAN ACTUAL (%)"] = planes
    estado["DESVIACIÓN (pp)"] = (
        real - estado["PLAN ACTUAL (%)"]
    ).round(1)

    if "critica" not in estado.columns:
        estado["critica"] = False

    estado["critica"] = (
        estado["critica"].fillna(False)
    )

    def clasificar(fila):

        real_f = float(
            fila.get("avance_real", 0) or 0
        )
        plan_f = float(
            fila.get("PLAN ACTUAL (%)", 0) or 0
        )
        critica = bool(
            fila.get("critica", False)
        )
        fin_f = fila.get("fin_plan")
        desviacion = real_f - plan_f

        if real_f >= 100:
            return (
                "VERDE",
                "Culminada",
                "Sin acción requerida",
                90
            )

        if (
            pd.notna(fin_f)
            and ahora > pd.Timestamp(fin_f)
            and real_f < 100
        ):
            return (
                "ROJO",
                "Crítica vencida"
                if critica else "Vencida",
                "Escalar y definir recuperación inmediata",
                1 if critica else 2
            )

        if critica:
            if desviacion < -10:
                return (
                    "ROJO",
                    "Crítica atrasada",
                    "Escalar y definir recuperación inmediata",
                    3
                )
            if desviacion < -5:
                return (
                    "NARANJA",
                    "Crítica en riesgo",
                    "Aplicar plan de recuperación",
                    5
                )
            return (
                "VERDE",
                "Crítica en línea",
                "Mantener seguimiento cercano",
                30
            )

        if desviacion < -20:
            return (
                "ROJO",
                "Atraso crítico",
                "Intervención inmediata / reprogramar recursos",
                4
            )
        if desviacion < -10:
            return (
                "NARANJA",
                "Atrasada",
                "Definir plan de recuperación",
                6
            )
        if desviacion < -5:
            return (
                "AMARILLO",
                "En riesgo",
                "Seguimiento del supervisor",
                10
            )

        return (
            "VERDE",
            "En línea",
            "Sin acción requerida",
            40
        )

    resultado = estado.apply(
        clasificar,
        axis=1
    )

    estado["NIVEL"] = resultado.map(
        lambda x: x[0]
    )
    estado["ALERTA"] = resultado.map(
        lambda x: x[1]
    )
    estado["ACCIÓN REQUERIDA"] = resultado.map(
        lambda x: x[2]
    )
    estado["_PRIORIDAD"] = resultado.map(
        lambda x: x[3]
    )

    return estado


def construir_curva_s_pdf(
    actividades: pd.DataFrame,
    avances: pd.DataFrame
):

    curva = build_s_curve(
        actividades,
        avances
    )

    if curva.empty:
        return None

    curva = curva.copy()

    if "fecha" not in curva.columns:
        return None

    curva["fecha"] = pd.to_datetime(
        curva["fecha"],
        errors="coerce"
    )

    curva = curva.dropna(
        subset=["fecha"]
    )

    if curva.empty:
        return None

    # Reducir puntos si la curva es muy extensa.
    if len(curva) > 24:
        indices = np.linspace(
            0,
            len(curva) - 1,
            24
        ).astype(int)
        curva = curva.iloc[
            sorted(set(indices))
        ].copy()

    width = 500
    height = 220

    left = 48
    right = 18
    bottom = 38
    top = 22

    plot_w = width - left - right
    plot_h = height - bottom - top

    drawing = Drawing(
        width,
        height
    )

    # Ejes y grilla discreta.
    for valor in [0, 25, 50, 75, 100]:

        y = bottom + (
            valor / 100.0
        ) * plot_h

        drawing.add(
            Line(
                left,
                y,
                width - right,
                y,
                strokeColor=colors.HexColor("#E4E7EC"),
                strokeWidth=0.6
            )
        )

        drawing.add(
            String(
                12,
                y - 3,
                f"{valor}%",
                fontName="Helvetica",
                fontSize=7,
                fillColor=colors.HexColor("#667085")
            )
        )

    drawing.add(
        Line(
            left,
            bottom,
            left,
            height - top,
            strokeColor=colors.HexColor("#98A2B3"),
            strokeWidth=0.8
        )
    )

    drawing.add(
        Line(
            left,
            bottom,
            width - right,
            bottom,
            strokeColor=colors.HexColor("#98A2B3"),
            strokeWidth=0.8
        )
    )

    n = len(curva)

    def puntos(columna):

        valores = pd.to_numeric(
            curva[columna],
            errors="coerce"
        ).fillna(0).clip(
            lower=0,
            upper=100
        )

        resultado = []

        for i, valor in enumerate(valores):

            x = (
                left
                if n <= 1
                else left + (
                    i / (n - 1)
                ) * plot_w
            )

            y = bottom + (
                float(valor) / 100.0
            ) * plot_h

            resultado.extend(
                [x, y]
            )

        return resultado

    if "PLAN" in curva.columns:
        drawing.add(
            PolyLine(
                puntos("PLAN"),
                strokeColor=colors.HexColor("#082D55"),
                strokeWidth=2
            )
        )

    if "REAL" in curva.columns:
        drawing.add(
            PolyLine(
                puntos("REAL"),
                strokeColor=colors.HexColor("#D92D20"),
                strokeWidth=2
            )
        )

    # Etiquetas de fechas: inicio, medio y fin.
    posiciones = sorted(
        set(
            [
                0,
                max(0, n // 2),
                max(0, n - 1)
            ]
        )
    )

    for idx in posiciones:

        fecha = curva.iloc[idx]["fecha"]

        x = (
            left
            if n <= 1
            else left + (
                idx / (n - 1)
            ) * plot_w
        )

        drawing.add(
            String(
                x - 20,
                16,
                fecha.strftime("%d/%m %H:%M"),
                fontName="Helvetica",
                fontSize=6.5,
                fillColor=colors.HexColor("#667085")
            )
        )

    drawing.add(
        Line(
            340,
            205,
            360,
            205,
            strokeColor=colors.HexColor("#082D55"),
            strokeWidth=2
        )
    )
    drawing.add(
        String(
            365,
            201,
            "PLAN",
            fontName="Helvetica-Bold",
            fontSize=7,
            fillColor=colors.HexColor("#344054")
        )
    )

    drawing.add(
        Line(
            415,
            205,
            435,
            205,
            strokeColor=colors.HexColor("#D92D20"),
            strokeWidth=2
        )
    )
    drawing.add(
        String(
            440,
            201,
            "REAL",
            fontName="Helvetica-Bold",
            fontSize=7,
            fillColor=colors.HexColor("#344054")
        )
    )

    return drawing


# =====================================================
# REPORTE PDF EJECUTIVO POR ÁREA
# =====================================================

def construir_pdf_ejecutivo_area(
    ots: pd.DataFrame,
    actividades: pd.DataFrame,
    avances: pd.DataFrame,
    nombre_area: str
) -> bytes:

    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=28,
        leftMargin=28,
        topMargin=30,
        bottomMargin=28
    )

    styles = getSampleStyleSheet()

    estilo_titulo = ParagraphStyle(
        "TituloMainin",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#082D55"),
        spaceAfter=8
    )

    estilo_subtitulo = ParagraphStyle(
        "SubtituloMainin",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#667085"),
        spaceAfter=14
    )

    estilo_h2 = ParagraphStyle(
        "H2Mainin",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#082D55"),
        spaceBefore=8,
        spaceAfter=8
    )

    story = []

    story.append(
        Paragraph(
            "PDP CONTROL CENTER CHINALCO - MAININ",
            estilo_titulo
        )
    )

    story.append(
        Paragraph(
            f"Informe Ejecutivo - {nombre_area}",
            estilo_subtitulo
        )
    )

    story.append(
        Paragraph(
            f"Fecha de emisión: "
            f"{datetime.now():%d/%m/%Y %H:%M}",
            styles["Normal"]
        )
    )

    story.append(Spacer(1, 12))

    kpis = compute_kpis(
        actividades,
        avances
    )

    total_ots = (
        int(ots["id"].nunique())
        if not ots.empty and "id" in ots.columns
        else 0
    )

    resumen_data = [
        ["Indicador", "Valor"],
        ["OTs", str(total_ots)],
        ["Actividades", str(kpis["actividades"])],
        [
            "Avance general",
            f"{kpis['avance_general']:.1f}%"
        ],
        [
            "SPI",
            f"{kpis['spi']:.2f}"
        ],
        [
            "HH planificadas",
            f"{kpis['hh_plan']:.0f}"
        ],
        [
            "HH ganadas",
            f"{kpis['hh_ganadas']:.0f}"
        ],
        [
            "Culminadas",
            str(kpis["culminadas"])
        ],
        [
            "En ejecución",
            str(kpis["parciales"])
        ],
        [
            "No iniciadas",
            str(kpis["no_iniciadas"])
        ]
    ]

    tabla_resumen = Table(
        resumen_data,
        colWidths=[240, 160]
    )

    tabla_resumen.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor("#082D55")
            ),
            (
                "TEXTCOLOR",
                (0, 0),
                (-1, 0),
                colors.white
            ),
            (
                "FONTNAME",
                (0, 0),
                (-1, 0),
                "Helvetica-Bold"
            ),
            (
                "ALIGN",
                (1, 1),
                (1, -1),
                "CENTER"
            ),
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor("#D0D5DD")
            ),
            (
                "ROWBACKGROUNDS",
                (0, 1),
                (-1, -1),
                [
                    colors.white,
                    colors.HexColor("#F3F6F9")
                ]
            ),
            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "MIDDLE"
            ),
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                6
            ),
            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                6
            )
        ])
    )

    story.append(
        Paragraph(
            "Indicadores principales",
            estilo_h2
        )
    )

    story.append(tabla_resumen)
    story.append(Spacer(1, 14))

    # =================================================
    # CURVA S
    # =================================================

    story.append(
        Paragraph(
            "Curva S - Plan vs Real",
            estilo_h2
        )
    )

    curva_pdf = construir_curva_s_pdf(
        actividades,
        avances
    )

    if curva_pdf is not None:
        story.append(curva_pdf)
    else:
        story.append(
            Paragraph(
                "No existe información suficiente para construir la Curva S.",
                styles["BodyText"]
            )
        )

    story.append(Spacer(1, 12))

    # =================================================
    # SEMÁFORO EJECUTIVO
    # =================================================

    estado_gerencial = calcular_semaforo_pdf(
        actividades,
        avances
    )

    story.append(
        Paragraph(
            "Semáforo ejecutivo",
            estilo_h2
        )
    )

    if estado_gerencial.empty:

        story.append(
            Paragraph(
                "No existe información suficiente para calcular alertas.",
                styles["BodyText"]
            )
        )

    else:

        conteos = {
            nivel: int(
                (
                    estado_gerencial["NIVEL"]
                    == nivel
                ).sum()
            )
            for nivel in [
                "VERDE",
                "AMARILLO",
                "NARANJA",
                "ROJO"
            ]
        }

        resumen_semaforo = [
            [
                "En línea",
                "En riesgo",
                "Recuperación",
                "Intervención"
            ],
            [
                str(conteos["VERDE"]),
                str(conteos["AMARILLO"]),
                str(conteos["NARANJA"]),
                str(conteos["ROJO"])
            ]
        ]

        tabla_semaforo = Table(
            resumen_semaforo,
            colWidths=[100, 100, 100, 100]
        )

        tabla_semaforo.setStyle(
            TableStyle([
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#F2F4F7")
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#344054")
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    "Helvetica-Bold"
                ),
                (
                    "FONTNAME",
                    (0, 1),
                    (-1, 1),
                    "Helvetica-Bold"
                ),
                (
                    "FONTSIZE",
                    (0, 1),
                    (-1, 1),
                    14
                ),
                (
                    "ALIGN",
                    (0, 0),
                    (-1, -1),
                    "CENTER"
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor("#D0D5DD")
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    7
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    7
                )
            ])
        )

        story.append(tabla_semaforo)
        story.append(Spacer(1, 10))

        foco = (
            estado_gerencial[
                estado_gerencial[
                    "NIVEL"
                ].isin(
                    [
                        "ROJO",
                        "NARANJA",
                        "AMARILLO"
                    ]
                )
            ]
            .sort_values(
                [
                    "_PRIORIDAD",
                    "avance_real"
                ],
                ascending=[
                    True,
                    True
                ]
            )
            .head(10)
            .copy()
        )

        if foco.empty:

            story.append(
                Paragraph(
                    "No existen desviaciones que requieran atención gerencial.",
                    styles["BodyText"]
                )
            )

        else:

            story.append(
                Paragraph(
                    "Foco de atención gerencial",
                    styles["Heading3"]
                )
            )

            foco_data = [
                [
                    "Nivel",
                    "Actividad",
                    "Plan",
                    "Real",
                    "Desv.",
                    "Acción requerida"
                ]
            ]

            for _, fila in foco.iterrows():

                foco_data.append([
                    str(
                        fila.get(
                            "NIVEL",
                            ""
                        )
                    ),
                    Paragraph(
                        (
                            str(
                                fila.get(
                                    "codigo_actividad",
                                    ""
                                )
                            )
                            + " - "
                            + str(
                                fila.get(
                                    "descripcion",
                                    ""
                                )
                            )
                        )[:120],
                        styles["BodyText"]
                    ),
                    f"{float(fila.get('PLAN ACTUAL (%)', 0)):.0f}%",
                    f"{float(fila.get('avance_real', 0)):.0f}%",
                    f"{float(fila.get('DESVIACIÓN (pp)', 0)):.0f}",
                    Paragraph(
                        str(
                            fila.get(
                                "ACCIÓN REQUERIDA",
                                ""
                            )
                        ),
                        styles["BodyText"]
                    )
                ])

            tabla_foco = Table(
                foco_data,
                colWidths=[
                    48,
                    150,
                    38,
                    38,
                    38,
                    120
                ],
                repeatRows=1
            )

            tabla_foco.setStyle(
                TableStyle([
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        colors.HexColor("#082D55")
                    ),
                    (
                        "TEXTCOLOR",
                        (0, 0),
                        (-1, 0),
                        colors.white
                    ),
                    (
                        "FONTNAME",
                        (0, 0),
                        (-1, 0),
                        "Helvetica-Bold"
                    ),
                    (
                        "FONTSIZE",
                        (0, 0),
                        (-1, -1),
                        6.8
                    ),
                    (
                        "VALIGN",
                        (0, 0),
                        (-1, -1),
                        "TOP"
                    ),
                    (
                        "GRID",
                        (0, 0),
                        (-1, -1),
                        0.35,
                        colors.HexColor("#D0D5DD")
                    ),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [
                            colors.white,
                            colors.HexColor("#F8FAFC")
                        ]
                    ),
                    (
                        "TOPPADDING",
                        (0, 0),
                        (-1, -1),
                        4
                    ),
                    (
                        "BOTTOMPADDING",
                        (0, 0),
                        (-1, -1),
                        4
                    )
                ])
            )

            story.append(tabla_foco)

    story.append(Spacer(1, 14))

    if not avances.empty:

        story.append(
            Paragraph(
                "Resumen de avances",
                estilo_h2
            )
        )

        fecha_hoy = pd.Timestamp.now(
            tz="America/Lima"
        ).date()

        secciones = construir_secciones_informe_diario(
            ots,
            actividades,
            avances,
            nombre_area,
            fecha_hoy
        )

        for titulo, clave in [
            (
                "Resumen ejecutivo",
                "resumen"
            ),
            (
                "Principales actualizaciones",
                "actualizaciones"
            ),
            (
                "Observaciones / Restricciones",
                "observaciones"
            ),
            (
                "Actividades críticas",
                "criticas"
            ),
            (
                "Pendientes principales",
                "pendientes"
            )
        ]:

            story.append(
                Paragraph(
                    titulo,
                    styles["Heading3"]
                )
            )

            contenido = (
                secciones.get(clave, "")
                or ""
            )

            for linea in contenido.splitlines():

                if linea.strip():

                    linea_segura = (
                        linea
                        .replace("&", "&amp;")
                        .replace("<", "&lt;")
                        .replace(">", "&gt;")
                    )

                    story.append(
                        Paragraph(
                            linea_segura,
                            styles["BodyText"]
                        )
                    )

                else:
                    story.append(
                        Spacer(1, 4)
                    )

            story.append(
                Spacer(1, 6)
            )

    story.append(
        Paragraph(
            "Detalle por OT",
            estilo_h2
        )
    )

    estado = build_activity_status(
        actividades,
        avances
    )

    if (
        not estado.empty
        and not ots.empty
        and "ot_id" in estado.columns
    ):

        detalle_ot = (
            estado
            .groupby(
                "ot_id",
                dropna=False
            )
            .agg(
                actividades=("id", "count"),
                culminadas=(
                    "avance_real",
                    lambda serie: int(
                        (serie >= 100).sum()
                    )
                ),
                en_ejecucion=(
                    "avance_real",
                    lambda serie: int(
                        (
                            (serie > 0)
                            & (serie < 100)
                        ).sum()
                    )
                ),
                no_iniciadas=(
                    "avance_real",
                    lambda serie: int(
                        (serie <= 0).sum()
                    )
                ),
                avance_ot=(
                    "avance_real",
                    "mean"
                )
            )
            .reset_index()
            .merge(
                ots[
                    [
                        "id",
                        "ot",
                        "equipo"
                    ]
                ],
                left_on="ot_id",
                right_on="id",
                how="left"
            )
        )

        tabla_ot_data = [
            [
                "OT",
                "Equipo",
                "Act.",
                "Avance",
                "Culm.",
                "Ejec.",
                "No inic."
            ]
        ]

        for _, fila in detalle_ot.sort_values(
            "ot"
        ).iterrows():

            tabla_ot_data.append([
                str(
                    fila.get(
                        "ot",
                        ""
                    )
                ),
                str(
                    fila.get(
                        "equipo",
                        ""
                    )
                ),
                str(
                    int(
                        fila.get(
                            "actividades",
                            0
                        )
                    )
                ),
                f"{float(fila.get('avance_ot', 0)):.1f}%",
                str(
                    int(
                        fila.get(
                            "culminadas",
                            0
                        )
                    )
                ),
                str(
                    int(
                        fila.get(
                            "en_ejecucion",
                            0
                        )
                    )
                ),
                str(
                    int(
                        fila.get(
                            "no_iniciadas",
                            0
                        )
                    )
                )
            ])

        tabla_ot = Table(
            tabla_ot_data,
            colWidths=[
                68,
                120,
                42,
                55,
                42,
                42,
                48
            ],
            repeatRows=1
        )

        tabla_ot.setStyle(
            TableStyle([
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#082D55")
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    "Helvetica-Bold"
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    7.5
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor("#D0D5DD")
                ),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [
                        colors.white,
                        colors.HexColor("#F8FAFC")
                    ]
                ),
                (
                    "ALIGN",
                    (2, 1),
                    (-1, -1),
                    "CENTER"
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE"
                )
            ])
        )

        story.append(tabla_ot)

    else:

        story.append(
            Paragraph(
                "No existe información disponible por OT.",
                styles["BodyText"]
            )
        )

    story.append(Spacer(1, 16))

    story.append(
        Paragraph(
            "MAININ - Mantenimiento e Ingeniería Industrial",
            estilo_subtitulo
        )
    )

    doc.build(story)

    buffer.seek(0)

    return buffer.getvalue()



# =====================================================
# PREPARAR DATAFRAME PARA EXCEL
# =====================================================

def preparar_dataframe_excel(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte columnas no compatibles con Excel:
    - timestamps con zona horaria -> timestamps sin zona horaria
    - listas/diccionarios -> texto
    """

    salida = df.copy()

    for columna in salida.columns:

        serie = salida[columna]

        # Datetime con timezone
        if pd.api.types.is_datetime64tz_dtype(serie):
            salida[columna] = serie.dt.tz_localize(None)
            continue

        # Datetime normal
        if pd.api.types.is_datetime64_any_dtype(serie):
            continue

        # Objetos que pueden contener Timestamp con timezone,
        # listas o diccionarios.
        if serie.dtype == "object":

            def limpiar_valor(valor):

                if isinstance(valor, pd.Timestamp):

                    if valor.tzinfo is not None:
                        return valor.tz_localize(None)

                    return valor

                if isinstance(valor, (list, dict, tuple)):
                    return str(valor)

                return valor

            salida[columna] = serie.map(
                limpiar_valor
            )

    return salida



# =====================================================
# IDENTIDAD VISUAL MAININ - SIDEBAR
# =====================================================

LOGO_MAININ = Path(__file__).parent / "logo_mainin.png"


def mostrar_logo_mainin_sidebar():
    """
    Muestra el logo corporativo MAININ una sola vez en el panel lateral.
    Funciona para ADMIN y todos los usuarios REPORTER.
    """

    with st.sidebar:

        if LOGO_MAININ.exists():

            st.image(
                str(LOGO_MAININ),
                use_container_width=True
            )

        else:

            # Respaldo si el archivo todavía no fue cargado al repositorio.
            st.markdown(
                """
                <div style="
                    text-align:center;
                    font-weight:700;
                    font-size:24px;
                    margin-bottom:4px;
                ">
                    MAININ
                </div>
                """,
                unsafe_allow_html=True
            )

        st.markdown(
            """
            <div style="
                text-align:center;
                font-size:13px;
                font-weight:600;
                letter-spacing:0.4px;
                color:#475467;
                margin-top:-4px;
                margin-bottom:2px;
            ">
                PDP CONTROL CENTER
            </div>

            <div style="
                text-align:center;
                font-size:12px;
                font-weight:700;
                color:#155EEF;
                margin-bottom:12px;
            ">
                CHINALCO
            </div>
            """,
            unsafe_allow_html=True
        )

        st.divider()



# =====================================================
# CONTROL DE ROLES Y CONTRASEÑAS
# =====================================================

ROLES_PERMITIDOS = {
    "admin",
    "planner",
    "supervisor",
    "lider"
}


def normalizar_rol(rol):
    """
    Mantiene compatibilidad con usuarios REPORTER existentes.
    REPORTER se interpreta temporalmente como PLANNER.
    """
    rol_normalizado = str(rol or "").strip().lower()

    if rol_normalizado == "reporter":
        return "planner"

    return rol_normalizado


def verificar_contrasena(password_plano, password_hash):
    """
    Formato esperado:
    pbkdf2_sha256$260000$SALT$HASH_HEX
    """

    if not password_hash:
        return False

    try:
        algoritmo, iteraciones, salt, hash_guardado = (
            password_hash.split("$", 3)
        )

        if algoritmo != "pbkdf2_sha256":
            return False

        hash_calculado = hashlib.pbkdf2_hmac(
            "sha256",
            password_plano.encode("utf-8"),
            salt.encode("utf-8"),
            int(iteraciones)
        ).hex()

        return hmac.compare_digest(
            hash_calculado,
            hash_guardado
        )

    except Exception:
        return False


def menu_por_rol(rol):
    """
    ADMIN: menú administrativo completo.
    PLANNER: menú completo de su área.
    SUPERVISOR / LIDER: solo registro de avances.
    """

    rol = normalizar_rol(rol)

    if rol == "planner":
        return [
            "Dashboard",
            "Registrar avance",
            "Detalle por OT",
            "Evidencias",
            "Informe diario",
            "Reportes"
        ]

    if rol in {"supervisor", "lider"}:
        return [
            "Registrar avance"
        ]

    return []


# =====================================================
# LOGIN Y CONTROL DE ACCESO
# =====================================================

def obtener_usuario(username):
    resultado = (
        supabase
        .table("usuarios_app")
        .select(
            "id,username,nombre,rol,area_id,activo,password_hash,"
            "areas(id,codigo,nombre)"
        )
        .eq("username", username)
        .eq("activo", True)
        .limit(1)
        .execute()
    )

    datos = resultado.data or []

    if not datos:
        return None

    return datos[0]


if "usuario_logueado" not in st.session_state:
    st.session_state["usuario_logueado"] = None


# =====================================================
# PANTALLA DE LOGIN
# =====================================================

if st.session_state["usuario_logueado"] is None:

    st.title("PDP CONTROL CENTER CHINALCO - MAININ")

    st.caption(
        "Sistema integrado de seguimiento y control de la Parada de Planta"
    )

    st.divider()

    st.subheader("Acceso al sistema")

    username = st.text_input(
        "Usuario",
        placeholder="Ingrese su usuario"
    )

    password = st.text_input(
        "Contraseña",
        type="password",
        placeholder="Ingrese su contraseña"
    )

    if st.button(
        "Ingresar",
        type="primary",
        use_container_width=True
    ):

        usuario = obtener_usuario(username.strip())

        if usuario is None:
            st.error("Usuario no encontrado o inactivo.")

        else:

            rol_login = normalizar_rol(
                usuario.get("rol")
            )

            if rol_login not in ROLES_PERMITIDOS:
                st.error(
                    "El usuario tiene un rol no permitido. "
                    "Contacte al administrador."
                )

            elif (
                rol_login != "admin"
                and not usuario.get("area_id")
            ):
                st.error(
                    "El usuario no tiene un área asignada."
                )

            elif verificar_contrasena(
                password.strip(),
                usuario.get("password_hash")
            ):

                usuario["rol"] = rol_login

                st.session_state[
                    "usuario_logueado"
                ] = usuario

                st.rerun()

            else:
                st.error("Contraseña incorrecta.")

    st.stop()


# =====================================================
# USUARIO LOGUEADO
# =====================================================

usuario = st.session_state["usuario_logueado"]

rol = normalizar_rol(
    usuario.get("rol")
)

usuario["rol"] = rol

area_info = usuario.get("areas")

if rol == "admin":
    codigo_area = "TODAS"
    nombre_area = "Todas las áreas"
else:
    codigo_area = area_info["codigo"]
    nombre_area = area_info["nombre"]


# =====================================================
# SIDEBAR
# =====================================================

mostrar_logo_mainin_sidebar()

with st.sidebar:

    st.divider()

    st.write("Usuario:")
    st.success(usuario["nombre"])

    st.write("Rol:")

    nombre_rol_sidebar = {
        "admin": "ADMIN",
        "planner": "PLANNER",
        "supervisor": "SUPERVISOR",
        "lider": "LÍDER"
    }.get(
        rol,
        rol.upper()
    )

    st.info(nombre_rol_sidebar)

    st.write("Área:")

    if rol == "admin":
        st.warning("TODAS LAS ÁREAS")
    else:
        st.info(nombre_area)

    st.divider()

    if st.button(
        "Cerrar sesión",
        use_container_width=True
    ):
        st.session_state["usuario_logueado"] = None
        st.rerun()


# =====================================================
# PANTALLA PRINCIPAL
# =====================================================

st.title("PDP CONTROL CENTER CHINALCO - MAININ")

st.caption(
    "Sistema integrado de seguimiento y control de la Parada de Planta"
)

st.divider()


# =====================================================
# ADMINISTRADOR
# =====================================================

if rol == "admin":

    # =====================================================
    # MENÚ ADMINISTRADOR
    # =====================================================

    with st.sidebar:

        st.divider()

        pagina_admin = st.radio(
            "Menú administrador",
            [
                "Dashboard general",
                "Importar planificación",
                "Administrar OTs",
                "Reportes"
            ]
        )


    # =====================================================
    # DASHBOARD GENERAL
    # =====================================================

    if pagina_admin == "Dashboard general":

        st.subheader("Dashboard Consolidado Chinalco")

        st.caption(
            "Vista administrativa con selector dinámico por área. "
            "Puede revisar Todas las áreas o ingresar al detalle "
            "de Molinos, Chancado, Flotación o Relaves sin cerrar sesión."
        )

        # =================================================
        # 1. CARGAR ÁREAS ACTIVAS
        # =================================================

        resultado_areas_admin = (
            supabase
            .table("areas")
            .select("id,codigo,nombre")
            .eq("activo", True)
            .order("id")
            .execute()
        )

        areas_admin = (
            resultado_areas_admin.data
            or []
        )

        if not areas_admin:

            st.warning(
                "No existen áreas activas configuradas."
            )

        else:

            # =============================================
            # SELECTOR DE VISTA ADMINISTRATIVA
            # =============================================

            mapa_vistas_admin = {
                "Todas las áreas": None
            }

            for area in areas_admin:
                mapa_vistas_admin[
                    area["nombre"]
                ] = area["id"]

            vista_admin = st.selectbox(
                "Seleccionar vista",
                list(mapa_vistas_admin.keys()),
                key="selector_vista_admin"
            )

            area_id_seleccionada_admin = (
                mapa_vistas_admin[
                    vista_admin
                ]
            )

            if area_id_seleccionada_admin is None:

                areas_vista_admin = areas_admin

                st.info(
                    "Vista actual: TODAS LAS ÁREAS"
                )

            else:

                areas_vista_admin = [
                    area
                    for area in areas_admin
                    if area["id"]
                    == area_id_seleccionada_admin
                ]

                st.info(
                    f"Vista actual: {vista_admin}"
                )

            ids_areas_admin = [
                area["id"]
                for area in areas_vista_admin
            ]

            # =============================================
            # 2. OTs DE LA VISTA SELECCIONADA
            # =============================================


            ots_admin = (
                supabase
                .table("ots")
                .select(
                    "id,ot,area_id,equipo,descripcion,activo"
                )
                .in_(
                    "area_id",
                    ids_areas_admin
                )
                .eq(
                    "activo",
                    True
                )
                .execute()
            ).data or []

            df_ots_admin = pd.DataFrame(
                ots_admin
            )

            if not ots_admin:

                st.warning(
                    "Todavía no existen OTs activas "
                    "en las áreas configuradas."
                )

            else:

                ids_ots_admin = [
                    ot["id"]
                    for ot in ots_admin
                ]

                # =========================================
                # 3. ACTIVIDADES CONSOLIDADAS
                # =========================================

                actividades_admin = (
                    supabase
                    .table("actividades")
                    .select(
                        "id,ot_id,codigo_actividad,descripcion,"
                        "supervisor,especialidad,grupo,peso,"
                        "inicio_plan,fin_plan,seccion,personal,"
                        "duracion_h,hh_plan,critica,activo"
                    )
                    .in_(
                        "ot_id",
                        ids_ots_admin
                    )
                    .eq(
                        "activo",
                        True
                    )
                    .execute()
                ).data or []

                df_actividades_admin = pd.DataFrame(
                    actividades_admin
                )

                if actividades_admin:

                    ids_actividades_admin = [
                        actividad["id"]
                        for actividad in actividades_admin
                    ]

                    avances_admin = (
                        supabase
                        .table("avances_actividad")
                        .select(
                            "id,actividad_id,avance,"
                            "descripcion_avance,observaciones,"
                            "tipo_evidencia,critica,evidencias,"
                            "usuario,fecha_registro"
                        )
                        .in_(
                            "actividad_id",
                            ids_actividades_admin
                        )
                        .execute()
                    ).data or []

                else:

                    avances_admin = []

                df_avances_admin = pd.DataFrame(
                    avances_admin
                )

                # =========================================
                # 4. ESTADO GENERAL DE LA PDP
                # =========================================

                st.markdown("### Estado general de la PDP")
                st.caption(
                    "Indicadores ejecutivos de la vista seleccionada. "
                    "La información se actualiza con los avances registrados."
                )

                kpis_admin = compute_kpis(
                    df_actividades_admin,
                    df_avances_admin
                )

                total_ots_admin = len(
                    df_ots_admin
                )

                a1, a2, a3, a4, a5, a6 = st.columns(
                    6
                )

                with a1:
                    st.metric(
                        "OTs",
                        total_ots_admin
                    )

                with a2:
                    st.metric(
                        "Actividades",
                        kpis_admin[
                            "actividades"
                        ]
                    )

                with a3:
                    st.metric(
                        "Avance general",
                        f"{kpis_admin['avance_general']:.1f}%"
                    )

                with a4:
                    st.metric(
                        "Culminadas",
                        kpis_admin[
                            "culminadas"
                        ]
                    )

                with a5:
                    st.metric(
                        "En ejecución",
                        kpis_admin[
                            "parciales"
                        ]
                    )

                with a6:
                    st.metric(
                        "No iniciadas",
                        kpis_admin[
                            "no_iniciadas"
                        ]
                    )

                b1, b2, b3, b4 = st.columns(
                    4
                )

                with b1:
                    st.metric(
                        "Plan actual",
                        f"{kpis_admin.get('avance_plan', 0):.1f}%"
                    )

                with b2:
                    st.metric(
                        "SPI",
                        f"{kpis_admin['spi']:.2f}"
                    )

                with b3:
                    st.metric(
                        "HH planificadas",
                        f"{kpis_admin['hh_plan']:.0f}"
                    )

                with b4:
                    st.metric(
                        "HH ganadas",
                        f"{kpis_admin['hh_ganadas']:.0f}"
                    )

                st.divider()

                # =========================================
                # 5. CURVA S - PLAN VS REAL
                # =========================================

                if area_id_seleccionada_admin is None:
                    st.subheader(
                        "Curva S consolidada - Plan vs Real"
                    )
                else:
                    st.subheader(
                        f"Curva S - {vista_admin}"
                    )

                curva_admin = build_s_curve(
                    df_actividades_admin,
                    df_avances_admin
                )

                if curva_admin.empty:

                    st.info(
                        "No existe información suficiente "
                        "para construir la Curva S consolidada."
                    )

                else:

                    curva_admin_long = (
                        curva_admin
                        .melt(
                            id_vars=["fecha"],
                            value_vars=[
                                "PLAN",
                                "REAL"
                            ],
                            var_name="Curva",
                            value_name="Avance"
                        )
                    )

                    figura_curva_admin = go.Figure()

                    for nombre_curva, posicion_texto in [
                        ("PLAN", "top center"),
                        ("REAL", "bottom center")
                    ]:

                        datos_curva_admin = (
                            curva_admin_long[
                                curva_admin_long["Curva"]
                                == nombre_curva
                            ]
                            .copy()
                        )

                        etiquetas_admin = [
                            f"{float(valor):.1f}%"
                            if pd.notna(valor)
                            else ""
                            for valor in datos_curva_admin[
                                "Avance"
                            ]
                        ]

                        figura_curva_admin.add_trace(
                            go.Scatter(
                                x=datos_curva_admin["fecha"],
                                y=datos_curva_admin["Avance"],
                                mode="lines+markers+text",
                                name=nombre_curva,
                                text=etiquetas_admin,
                                textposition=posicion_texto,
                                textfont=dict(
                                    size=10
                                ),
                                line=dict(
                                    width=4,
                                    shape="spline",
                                    smoothing=1.05
                                ),
                                marker=dict(
                                    size=7,
                                    line=dict(
                                        width=1
                                    )
                                ),
                                connectgaps=False,
                                hovertemplate=(
                                    f"<b>{nombre_curva}</b><br>"
                                    "%{x|%d/%m/%Y %H:%M}<br>"
                                    "Avance: %{y:.1f}%"
                                    "<extra></extra>"
                                )
                            )
                        )

                    figura_curva_admin.update_layout(
                        height=520,
                        hovermode="x unified",
                        xaxis=dict(
                            title="Fecha / hora",
                            tickformat="%d/%m\n%H:%M",
                            showgrid=True,
                            gridwidth=1
                        ),
                        yaxis=dict(
                            title="Acumulado (%)",
                            range=[0, 108],
                            dtick=20,
                            ticksuffix="%",
                            showgrid=True,
                            gridwidth=1,
                            zeroline=False
                        ),
                        legend=dict(
                            orientation="h",
                            yanchor="bottom",
                            y=1.04,
                            xanchor="center",
                            x=0.5
                        ),
                        margin=dict(
                            l=50,
                            r=35,
                            t=60,
                            b=55
                        )
                    )

                    st.plotly_chart(
                        figura_curva_admin,
                        use_container_width=True,
                        config={
                            "displaylogo": False,
                            "responsive": True
                        }
                    )

                st.divider()

                # =========================================
                # 6. SEMÁFORO EJECUTIVO
                # =========================================

                st.markdown("### Semáforo ejecutivo")
                st.caption(
                    "Clasificación automática por desviación PLAN vs REAL, "
                    "criticidad y vencimiento. Se muestran primero las "
                    "situaciones que requieren decisión gerencial."
                )

                estado_semaforo_admin = build_activity_status(
                    df_actividades_admin,
                    df_avances_admin
                )

                if estado_semaforo_admin.empty:

                    st.info(
                        "No existe información suficiente para "
                        "calcular el semáforo ejecutivo."
                    )

                else:

                    estado_semaforo_admin = (
                        estado_semaforo_admin
                        .merge(
                            df_ots_admin[
                                [
                                    "id",
                                    "ot",
                                    "area_id",
                                    "equipo"
                                ]
                            ],
                            left_on="ot_id",
                            right_on="id",
                            how="left",
                            suffixes=(
                                "",
                                "_ot"
                            )
                        )
                    )

                    mapa_area_sem_admin = {
                        area["id"]: area["nombre"]
                        for area in areas_vista_admin
                    }

                    estado_semaforo_admin["Área"] = (
                        estado_semaforo_admin[
                            "area_id"
                        ].map(
                            mapa_area_sem_admin
                        )
                    )

                    ahora_sem_admin = pd.Timestamp.now(tz="America/Lima").tz_localize(None)

                    inicio_sem_admin = pd.to_datetime(
                        estado_semaforo_admin.get(
                            "inicio_plan"
                        ),
                        errors="coerce"
                    )

                    fin_sem_admin = pd.to_datetime(
                        estado_semaforo_admin.get(
                            "fin_plan"
                        ),
                        errors="coerce"
                    )

                    real_sem_admin = pd.to_numeric(
                        estado_semaforo_admin.get(
                            "avance_real",
                            0
                        ),
                        errors="coerce"
                    ).fillna(0)

                    plan_sem_admin = []

                    for ini_sem, fin_sem in zip(
                        inicio_sem_admin,
                        fin_sem_admin
                    ):

                        if (
                            pd.isna(ini_sem)
                            or pd.isna(fin_sem)
                        ):
                            plan_sem_admin.append(0.0)
                            continue

                        if fin_sem <= ini_sem:
                            fin_sem = (
                                ini_sem
                                + pd.Timedelta(minutes=1)
                            )

                        if ahora_sem_admin <= ini_sem:
                            valor_plan_sem = 0.0

                        elif ahora_sem_admin >= fin_sem:
                            valor_plan_sem = 100.0

                        else:
                            duracion_sem = (
                                fin_sem - ini_sem
                            ).total_seconds()

                            transcurrido_sem = (
                                ahora_sem_admin - ini_sem
                            ).total_seconds()

                            valor_plan_sem = (
                                transcurrido_sem
                                / duracion_sem
                                * 100
                                if duracion_sem > 0
                                else 100.0
                            )

                        plan_sem_admin.append(
                            max(
                                0.0,
                                min(
                                    100.0,
                                    float(valor_plan_sem)
                                )
                            )
                        )

                    estado_semaforo_admin[
                        "PLAN ACTUAL (%)"
                    ] = plan_sem_admin

                    estado_semaforo_admin[
                        "DESVIACIÓN (pp)"
                    ] = (
                        real_sem_admin
                        - estado_semaforo_admin[
                            "PLAN ACTUAL (%)"
                        ]
                    ).round(1)

                    if (
                        "critica"
                        not in estado_semaforo_admin.columns
                    ):
                        estado_semaforo_admin[
                            "critica"
                        ] = False

                    estado_semaforo_admin[
                        "critica"
                    ] = (
                        estado_semaforo_admin[
                            "critica"
                        ]
                        .fillna(False)
                    )

                    def semaforo_gerencial_admin(fila):

                        real = float(
                            fila.get(
                                "avance_real",
                                0
                            )
                            or 0
                        )

                        plan = float(
                            fila.get(
                                "PLAN ACTUAL (%)",
                                0
                            )
                            or 0
                        )

                        critica = bool(
                            fila.get(
                                "critica",
                                False
                            )
                        )

                        fin = fila.get(
                            "fin_plan"
                        )

                        desviacion = real - plan

                        if real >= 100:
                            return (
                                "🟢",
                                "VERDE",
                                "Culminada",
                                "Sin acción requerida",
                                90
                            )

                        if (
                            pd.notna(fin)
                            and ahora_sem_admin
                            > pd.Timestamp(fin)
                            and real < 100
                        ):
                            return (
                                "🔴",
                                "ROJO",
                                (
                                    "Crítica vencida"
                                    if critica
                                    else "Vencida"
                                ),
                                (
                                    "Escalar y definir "
                                    "recuperación inmediata"
                                ),
                                1 if critica else 2
                            )

                        if critica:

                            if desviacion < -10:
                                return (
                                    "🔴",
                                    "ROJO",
                                    "Crítica atrasada",
                                    (
                                        "Escalar y definir "
                                        "recuperación inmediata"
                                    ),
                                    3
                                )

                            if desviacion < -5:
                                return (
                                    "🟠",
                                    "NARANJA",
                                    "Crítica en riesgo",
                                    (
                                        "Aplicar plan de "
                                        "recuperación"
                                    ),
                                    5
                                )

                            return (
                                "🟢",
                                "VERDE",
                                "Crítica en línea",
                                "Mantener seguimiento cercano",
                                30
                            )

                        if desviacion < -20:
                            return (
                                "🔴",
                                "ROJO",
                                "Atraso crítico",
                                (
                                    "Intervención inmediata / "
                                    "reprogramar recursos"
                                ),
                                4
                            )

                        if desviacion < -10:
                            return (
                                "🟠",
                                "NARANJA",
                                "Atrasada",
                                "Definir plan de recuperación",
                                6
                            )

                        if desviacion < -5:
                            return (
                                "🟡",
                                "AMARILLO",
                                "En riesgo",
                                "Seguimiento del supervisor",
                                10
                            )

                        return (
                            "🟢",
                            "VERDE",
                            "En línea",
                            "Sin acción requerida",
                            40
                        )

                    resultado_sem_admin = (
                        estado_semaforo_admin
                        .apply(
                            semaforo_gerencial_admin,
                            axis=1
                        )
                    )

                    estado_semaforo_admin[
                        "SEMÁFORO"
                    ] = resultado_sem_admin.map(
                        lambda item: item[0]
                    )

                    estado_semaforo_admin[
                        "NIVEL"
                    ] = resultado_sem_admin.map(
                        lambda item: item[1]
                    )

                    estado_semaforo_admin[
                        "ALERTA"
                    ] = resultado_sem_admin.map(
                        lambda item: item[2]
                    )

                    estado_semaforo_admin[
                        "ACCIÓN REQUERIDA"
                    ] = resultado_sem_admin.map(
                        lambda item: item[3]
                    )

                    estado_semaforo_admin[
                        "_PRIORIDAD"
                    ] = resultado_sem_admin.map(
                        lambda item: item[4]
                    )

                    verdes_sem_admin = int(
                        (
                            estado_semaforo_admin[
                                "NIVEL"
                            ] == "VERDE"
                        ).sum()
                    )

                    amarillos_sem_admin = int(
                        (
                            estado_semaforo_admin[
                                "NIVEL"
                            ] == "AMARILLO"
                        ).sum()
                    )

                    naranjas_sem_admin = int(
                        (
                            estado_semaforo_admin[
                                "NIVEL"
                            ] == "NARANJA"
                        ).sum()
                    )

                    rojos_sem_admin = int(
                        (
                            estado_semaforo_admin[
                                "NIVEL"
                            ] == "ROJO"
                        ).sum()
                    )

                    gs1, gs2, gs3, gs4 = st.columns(4)

                    with gs1:
                        st.metric(
                            "🟢 En línea",
                            verdes_sem_admin
                        )

                    with gs2:
                        st.metric(
                            "🟡 En riesgo",
                            amarillos_sem_admin
                        )

                    with gs3:
                        st.metric(
                            "🟠 Recuperación",
                            naranjas_sem_admin
                        )

                    with gs4:
                        st.metric(
                            "🔴 Intervención",
                            rojos_sem_admin
                        )

                    foco_gerencial_admin = (
                        estado_semaforo_admin[
                            estado_semaforo_admin[
                                "NIVEL"
                            ].isin(
                                [
                                    "ROJO",
                                    "NARANJA",
                                    "AMARILLO"
                                ]
                            )
                        ]
                        .sort_values(
                            [
                                "_PRIORIDAD",
                                "avance_real"
                            ],
                            ascending=[
                                True,
                                True
                            ]
                        )
                        .head(12)
                        .copy()
                    )

                    if foco_gerencial_admin.empty:

                        st.success(
                            "No existen desviaciones que "
                            "requieran atención en este momento."
                        )

                    else:

                        st.markdown(
                            "#### Foco de atención gerencial"
                        )

                        columnas_foco_admin = [
                            "SEMÁFORO",
                            "ALERTA",
                            "Área",
                            "ot",
                            "equipo",
                            "codigo_actividad",
                            "PLAN ACTUAL (%)",
                            "avance_real",
                            "DESVIACIÓN (pp)",
                            "supervisor",
                            "ACCIÓN REQUERIDA"
                        ]

                        columnas_foco_admin = [
                            columna
                            for columna
                            in columnas_foco_admin
                            if columna
                            in foco_gerencial_admin.columns
                        ]

                        tabla_foco_admin = (
                            foco_gerencial_admin[
                                columnas_foco_admin
                            ]
                            .rename(
                                columns={
                                    "ot": "OT",
                                    "equipo": "EQUIPO",
                                    "codigo_actividad":
                                        "ACTIVIDAD",
                                    "avance_real":
                                        "REAL (%)",
                                    "supervisor":
                                        "SUPERVISOR"
                                }
                            )
                        )

                        st.dataframe(
                            tabla_foco_admin,
                            use_container_width=True,
                            hide_index=True,
                            height=320
                        )

                st.divider()

                # =========================================
                # 7. COMPARATIVO POR ÁREA
                # =========================================

                if area_id_seleccionada_admin is None:
                    st.subheader(
                        "Comparativo por área"
                    )
                else:
                    st.subheader(
                        f"Indicadores de {vista_admin}"
                    )

                resumen_areas = []

                for area in areas_vista_admin:

                    area_id_admin = area["id"]

                    ots_area_admin = (
                        df_ots_admin[
                            df_ots_admin["area_id"]
                            == area_id_admin
                        ].copy()
                        if not df_ots_admin.empty
                        else pd.DataFrame()
                    )

                    ids_ots_area_admin = (
                        ots_area_admin["id"]
                        .dropna()
                        .tolist()
                        if not ots_area_admin.empty
                        else []
                    )

                    if (
                        ids_ots_area_admin
                        and not df_actividades_admin.empty
                    ):

                        actividades_area_admin = (
                            df_actividades_admin[
                                df_actividades_admin["ot_id"]
                                .isin(
                                    ids_ots_area_admin
                                )
                            ].copy()
                        )

                    else:

                        actividades_area_admin = (
                            pd.DataFrame()
                        )

                    ids_actividades_area_admin = (
                        actividades_area_admin["id"]
                        .dropna()
                        .tolist()
                        if not actividades_area_admin.empty
                        else []
                    )

                    if (
                        ids_actividades_area_admin
                        and not df_avances_admin.empty
                    ):

                        avances_area_admin = (
                            df_avances_admin[
                                df_avances_admin[
                                    "actividad_id"
                                ].isin(
                                    ids_actividades_area_admin
                                )
                            ].copy()
                        )

                    else:

                        avances_area_admin = (
                            pd.DataFrame()
                        )

                    kpis_area_admin = compute_kpis(
                        actividades_area_admin,
                        avances_area_admin
                    )

                    resumen_areas.append({
                        "Área": area["nombre"],
                        "Código": area["codigo"],
                        "OTs": len(ots_area_admin),
                        "Actividades": kpis_area_admin[
                            "actividades"
                        ],
                        "Plan (%)": round(
                            kpis_area_admin.get(
                                "avance_plan",
                                0
                            ),
                            1
                        ),
                        "Real (%)": round(
                            kpis_area_admin[
                                "avance_general"
                            ],
                            1
                        ),
                        "SPI": round(
                            kpis_area_admin[
                                "spi"
                            ],
                            2
                        ),
                        "Culminadas": kpis_area_admin[
                            "culminadas"
                        ],
                        "En ejecución": kpis_area_admin[
                            "parciales"
                        ],
                        "No iniciadas": kpis_area_admin[
                            "no_iniciadas"
                        ],
                        "Pendientes": kpis_area_admin[
                            "pendientes"
                        ],
                        "HH plan": round(
                            kpis_area_admin[
                                "hh_plan"
                            ],
                            0
                        ),
                        "HH ganadas": round(
                            kpis_area_admin[
                                "hh_ganadas"
                            ],
                            0
                        )
                    })

                df_resumen_areas = pd.DataFrame(
                    resumen_areas
                )

                if not df_resumen_areas.empty:

                    figura_areas = go.Figure()

                    figura_areas.add_bar(
                        x=df_resumen_areas["Área"],
                        y=df_resumen_areas["Plan (%)"],
                        name="PLAN"
                    )

                    figura_areas.add_bar(
                        x=df_resumen_areas["Área"],
                        y=df_resumen_areas["Real (%)"],
                        name="REAL"
                    )

                    figura_areas.update_layout(
                        barmode="group",
                        yaxis=dict(
                            title="Avance (%)",
                            range=[0, 100]
                        ),
                        xaxis_title="Área",
                        legend_title="Curva",
                        height=430,
                        margin=dict(
                            l=20,
                            r=20,
                            t=20,
                            b=20
                        )
                    )

                    st.plotly_chart(
                        figura_areas,
                        use_container_width=True
                    )

                    st.dataframe(
                        df_resumen_areas,
                        use_container_width=True,
                        hide_index=True,
                        height=280
                    )

                st.divider()

                # =========================================
                # 8. DESEMPEÑO POR SUPERVISOR
                # =========================================

                if area_id_seleccionada_admin is None:
                    st.subheader(
                        "Desempeño por Supervisor - Todas las áreas"
                    )
                else:
                    st.subheader(
                        f"Desempeño por Supervisor - {vista_admin}"
                    )

                st.caption(
                    "Seguimiento gerencial del cumplimiento y disciplina "
                    "de reporte por supervisor. Las actividades futuras "
                    "todavía no iniciadas no se consideran como falta de reporte."
                )

                estado_supervisor_admin = build_activity_status(
                    df_actividades_admin,
                    df_avances_admin
                )

                if estado_supervisor_admin.empty:

                    st.info(
                        "No existen actividades para evaluar "
                        "el desempeño de supervisores."
                    )

                elif (
                    "supervisor"
                    not in estado_supervisor_admin.columns
                ):

                    st.warning(
                        "Las actividades cargadas no contienen "
                        "información de supervisor."
                    )

                else:

                    # -----------------------------------------
                    # Incorporar OT y área
                    # -----------------------------------------

                    estado_supervisor_admin = (
                        estado_supervisor_admin
                        .merge(
                            df_ots_admin[
                                [
                                    "id",
                                    "ot",
                                    "area_id",
                                    "equipo"
                                ]
                            ],
                            left_on="ot_id",
                            right_on="id",
                            how="left",
                            suffixes=(
                                "",
                                "_ot"
                            )
                        )
                    )

                    mapa_area_supervisor_admin = {
                        area["id"]: area["nombre"]
                        for area in areas_vista_admin
                    }

                    estado_supervisor_admin[
                        "Área"
                    ] = (
                        estado_supervisor_admin[
                            "area_id"
                        ].map(
                            mapa_area_supervisor_admin
                        )
                    )

                    # -----------------------------------------
                    # Normalizar campos
                    # -----------------------------------------

                    estado_supervisor_admin[
                        "supervisor"
                    ] = (
                        estado_supervisor_admin[
                            "supervisor"
                        ]
                        .fillna("")
                        .astype(str)
                        .str.strip()
                    )

                    estado_supervisor_admin = (
                        estado_supervisor_admin[
                            estado_supervisor_admin[
                                "supervisor"
                            ] != ""
                        ]
                        .copy()
                    )

                    if estado_supervisor_admin.empty:

                        st.info(
                            "No existen supervisores asignados "
                            "en la planificación seleccionada."
                        )

                    else:

                        ahora_supervisor_admin = (
                            pd.Timestamp.now(tz="America/Lima").tz_localize(None)
                        )

                        inicio_supervisor_admin = (
                            pd.to_datetime(
                                estado_supervisor_admin[
                                    "inicio_plan"
                                ],
                                errors="coerce"
                            )
                        )

                        fin_supervisor_admin = (
                            pd.to_datetime(
                                estado_supervisor_admin[
                                    "fin_plan"
                                ],
                                errors="coerce"
                            )
                        )

                        real_supervisor_admin = (
                            pd.to_numeric(
                                estado_supervisor_admin[
                                    "avance_real"
                                ],
                                errors="coerce"
                            )
                            .fillna(0)
                            .clip(0, 100)
                        )

                        # -----------------------------------------
                        # Plan esperado actual por actividad
                        # -----------------------------------------

                        planes_supervisor_admin = []

                        for (
                            fecha_inicio_sup,
                            fecha_fin_sup
                        ) in zip(
                            inicio_supervisor_admin,
                            fin_supervisor_admin
                        ):

                            if (
                                pd.isna(fecha_inicio_sup)
                                or pd.isna(fecha_fin_sup)
                            ):
                                planes_supervisor_admin.append(
                                    0.0
                                )
                                continue

                            if (
                                fecha_fin_sup
                                <= fecha_inicio_sup
                            ):
                                fecha_fin_sup = (
                                    fecha_inicio_sup
                                    + pd.Timedelta(minutes=1)
                                )

                            if (
                                ahora_supervisor_admin
                                <= fecha_inicio_sup
                            ):
                                plan_sup = 0.0

                            elif (
                                ahora_supervisor_admin
                                >= fecha_fin_sup
                            ):
                                plan_sup = 100.0

                            else:

                                duracion_sup = (
                                    fecha_fin_sup
                                    - fecha_inicio_sup
                                ).total_seconds()

                                transcurrido_sup = (
                                    ahora_supervisor_admin
                                    - fecha_inicio_sup
                                ).total_seconds()

                                plan_sup = (
                                    transcurrido_sup
                                    / duracion_sup
                                    * 100.0
                                    if duracion_sup > 0
                                    else 100.0
                                )

                            planes_supervisor_admin.append(
                                max(
                                    0.0,
                                    min(
                                        100.0,
                                        float(plan_sup)
                                    )
                                )
                            )

                        estado_supervisor_admin[
                            "PLAN ACTUAL (%)"
                        ] = planes_supervisor_admin

                        estado_supervisor_admin[
                            "REAL ACTUAL (%)"
                        ] = real_supervisor_admin

                        estado_supervisor_admin[
                            "DESVIACIÓN (pp)"
                        ] = (
                            estado_supervisor_admin[
                                "REAL ACTUAL (%)"
                            ]
                            - estado_supervisor_admin[
                                "PLAN ACTUAL (%)"
                            ]
                        ).round(1)

                        # -----------------------------------------
                        # Disciplina de reporte
                        # -----------------------------------------

                        if (
                            "fecha_registro"
                            in estado_supervisor_admin.columns
                        ):

                            fechas_registro_sup = (
                                pd.to_datetime(
                                    estado_supervisor_admin[
                                        "fecha_registro"
                                    ],
                                    errors="coerce",
                                    utc=True
                                )
                            )

                            estado_supervisor_admin[
                                "_fecha_registro_lima"
                            ] = (
                                fechas_registro_sup
                                .dt.tz_convert(
                                    "America/Lima"
                                )
                            )

                        else:

                            estado_supervisor_admin[
                                "_fecha_registro_lima"
                            ] = pd.NaT

                        # Actividad exigible:
                        # ya llegó su inicio plan y aún no culmina.
                        estado_supervisor_admin[
                            "_exigible"
                        ] = (
                            inicio_supervisor_admin.notna()
                            & (
                                inicio_supervisor_admin
                                <= ahora_supervisor_admin
                            )
                            & (
                                estado_supervisor_admin[
                                    "REAL ACTUAL (%)"
                                ] < 100
                            )
                        )

                        # Sin reporte:
                        # actividad exigible sin ningún avance registrado.
                        estado_supervisor_admin[
                            "_sin_reporte"
                        ] = (
                            estado_supervisor_admin[
                                "_exigible"
                            ]
                            & estado_supervisor_admin[
                                "_fecha_registro_lima"
                            ].isna()
                        )

                        # Vencida:
                        # fin plan superado y avance < 100%.
                        estado_supervisor_admin[
                            "_vencida"
                        ] = (
                            fin_supervisor_admin.notna()
                            & (
                                fin_supervisor_admin
                                < ahora_supervisor_admin
                            )
                            & (
                                estado_supervisor_admin[
                                    "REAL ACTUAL (%)"
                                ] < 100
                            )
                        )

                        # Atrasada:
                        # desviación mayor a 10 pp o actividad vencida.
                        estado_supervisor_admin[
                            "_atrasada"
                        ] = (
                            (
                                estado_supervisor_admin[
                                    "DESVIACIÓN (pp)"
                                ] < -10
                            )
                            | estado_supervisor_admin[
                                "_vencida"
                            ]
                        )

                        # -----------------------------------------
                        # Consolidado por Supervisor + Área
                        # -----------------------------------------

                        resumen_supervisores_admin = []

                        grupos_supervisor_admin = (
                            estado_supervisor_admin
                            .groupby(
                                [
                                    "Área",
                                    "supervisor"
                                ],
                                dropna=False
                            )
                        )

                        for (
                            area_sup,
                            supervisor_sup
                        ), grupo_sup in grupos_supervisor_admin:

                            total_actividades_sup = len(
                                grupo_sup
                            )

                            plan_promedio_sup = float(
                                grupo_sup[
                                    "PLAN ACTUAL (%)"
                                ].mean()
                            )

                            real_promedio_sup = float(
                                grupo_sup[
                                    "REAL ACTUAL (%)"
                                ].mean()
                            )

                            desviacion_sup = (
                                real_promedio_sup
                                - plan_promedio_sup
                            )

                            atrasadas_sup = int(
                                grupo_sup[
                                    "_atrasada"
                                ].sum()
                            )

                            vencidas_sup = int(
                                grupo_sup[
                                    "_vencida"
                                ].sum()
                            )

                            sin_reporte_sup = int(
                                grupo_sup[
                                    "_sin_reporte"
                                ].sum()
                            )

                            exigibles_sup = int(
                                grupo_sup[
                                    "_exigible"
                                ].sum()
                            )

                            reportadas_sup = max(
                                0,
                                exigibles_sup
                                - sin_reporte_sup
                            )

                            cumplimiento_reporte_sup = (
                                (
                                    reportadas_sup
                                    / exigibles_sup
                                    * 100
                                )
                                if exigibles_sup > 0
                                else None
                            )

                            fechas_validas_sup = (
                                grupo_sup[
                                    "_fecha_registro_lima"
                                ]
                                .dropna()
                            )

                            if fechas_validas_sup.empty:
                                ultimo_reporte_sup = (
                                    "Sin reporte"
                                )
                            else:
                                ultimo_reporte_sup = (
                                    fechas_validas_sup
                                    .max()
                                    .strftime(
                                        "%d/%m %H:%M"
                                    )
                                )

                            # ---------------------------------
                            # Estado gerencial del supervisor
                            # ---------------------------------

                            if exigibles_sup == 0:
                                estado_gestion_sup = (
                                    "⚪ PROGRAMADO"
                                )

                            elif (
                                vencidas_sup > 0
                                or desviacion_sup < -20
                            ):
                                estado_gestion_sup = (
                                    "🔴 INTERVENCIÓN"
                                )

                            elif (
                                atrasadas_sup > 0
                                or desviacion_sup < -10
                            ):
                                estado_gestion_sup = (
                                    "🟠 RECUPERACIÓN"
                                )

                            elif (
                                sin_reporte_sup > 0
                                or desviacion_sup < -5
                            ):
                                estado_gestion_sup = (
                                    "🟡 SEGUIMIENTO"
                                )

                            else:
                                estado_gestion_sup = (
                                    "🟢 EN LÍNEA"
                                )

                            resumen_supervisores_admin.append({
                                "Estado":
                                    estado_gestion_sup,
                                "Área":
                                    area_sup,
                                "Supervisor":
                                    supervisor_sup,
                                "Actividades":
                                    total_actividades_sup,
                                "Plan (%)":
                                    round(
                                        plan_promedio_sup,
                                        1
                                    ),
                                "Real (%)":
                                    round(
                                        real_promedio_sup,
                                        1
                                    ),
                                "Desv. (pp)":
                                    round(
                                        desviacion_sup,
                                        1
                                    ),
                                "Atrasadas":
                                    atrasadas_sup,
                                "Vencidas":
                                    vencidas_sup,
                                "Sin reporte":
                                    sin_reporte_sup,
                                "Reporte (%)":
                                    (
                                        round(
                                            cumplimiento_reporte_sup,
                                            0
                                        )
                                        if cumplimiento_reporte_sup
                                        is not None
                                        else None
                                    ),
                                "Último reporte":
                                    ultimo_reporte_sup
                            })

                        df_supervisores_admin = (
                            pd.DataFrame(
                                resumen_supervisores_admin
                            )
                        )

                        if df_supervisores_admin.empty:

                            st.info(
                                "No existe información suficiente "
                                "para evaluar supervisores."
                            )

                        else:

                            # ---------------------------------
                            # KPIs gerenciales compactos
                            # ---------------------------------

                            total_supervisores_admin = (
                                len(
                                    df_supervisores_admin
                                )
                            )

                            supervisores_alerta_admin = int(
                                (
                                    ~df_supervisores_admin[
                                        "Estado"
                                    ].isin(
                                        [
                                            "🟢 EN LÍNEA",
                                            "⚪ PROGRAMADO"
                                        ]
                                    )
                                ).sum()
                            )

                            total_atrasadas_admin = int(
                                df_supervisores_admin[
                                    "Atrasadas"
                                ].sum()
                            )

                            total_sin_reporte_admin = int(
                                df_supervisores_admin[
                                    "Sin reporte"
                                ].sum()
                            )

                            sup1, sup2, sup3, sup4 = (
                                st.columns(4)
                            )

                            with sup1:
                                st.metric(
                                    "Supervisores",
                                    total_supervisores_admin
                                )

                            with sup2:
                                st.metric(
                                    "Con alerta",
                                    supervisores_alerta_admin
                                )

                            with sup3:
                                st.metric(
                                    "Actividades atrasadas",
                                    total_atrasadas_admin
                                )

                            with sup4:
                                st.metric(
                                    "Actividades sin reporte",
                                    total_sin_reporte_admin
                                )

                            # ---------------------------------
                            # Orden gerencial:
                            # rojos -> naranjas -> amarillos -> verdes
                            # ---------------------------------

                            prioridad_estado_supervisor = {
                                "🔴 INTERVENCIÓN": 1,
                                "🟠 RECUPERACIÓN": 2,
                                "🟡 SEGUIMIENTO": 3,
                                "🟢 EN LÍNEA": 4,
                                "⚪ PROGRAMADO": 5
                            }

                            df_supervisores_admin[
                                "_orden"
                            ] = (
                                df_supervisores_admin[
                                    "Estado"
                                ]
                                .map(
                                    prioridad_estado_supervisor
                                )
                                .fillna(9)
                            )

                            df_supervisores_admin = (
                                df_supervisores_admin
                                .sort_values(
                                    [
                                        "_orden",
                                        "Desv. (pp)",
                                        "Supervisor"
                                    ],
                                    ascending=[
                                        True,
                                        True,
                                        True
                                    ]
                                )
                                .drop(
                                    columns=["_orden"]
                                )
                            )

                            st.dataframe(
                                df_supervisores_admin,
                                use_container_width=True,
                                hide_index=True,
                                height=min(
                                    460,
                                    42
                                    + (
                                        len(
                                            df_supervisores_admin
                                        )
                                        * 35
                                    )
                                ),
                                column_config={
                                    "Plan (%)":
                                        st.column_config.NumberColumn(
                                            "Plan (%)",
                                            format="%.1f%%"
                                        ),
                                    "Real (%)":
                                        st.column_config.NumberColumn(
                                            "Real (%)",
                                            format="%.1f%%"
                                        ),
                                    "Desv. (pp)":
                                        st.column_config.NumberColumn(
                                            "Desv. (pp)",
                                            format="%.1f"
                                        ),
                                    "Reporte (%)":
                                        st.column_config.NumberColumn(
                                            "Reporte (%)",
                                            format="%.0f%%"
                                        )
                                }
                            )

                            st.caption(
                                "Criterio: el % de reporte comienza a medirse "
                                "recién cuando llega la hora de inicio planificada "
                                "de al menos una actividad del supervisor. "
                                "Antes de ese momento el estado es PROGRAMADO y "
                                "el % de reporte queda sin valor. "
                                "'Sin reporte' solo considera actividades cuyo "
                                "inicio plan ya ocurrió y que aún no tienen ningún "
                                "avance registrado. 'Atrasadas' considera "
                                "desviación menor a -10 pp o actividades vencidas "
                                "sin culminar."
                            )



                st.divider()

                # =========================================
                # 9. CENTRO DE CONTROL OPERATIVO
                # =========================================

                if area_id_seleccionada_admin is None:

                    st.subheader(
                        "Centro de Control Operativo - Todas las áreas"
                    )

                    st.caption(
                        "Detalle consolidado de todas las actividades. "
                        "Puede filtrar por área, OT, estado, supervisor "
                        "y especialidad sin salir de la sesión ADMIN."
                    )

                else:

                    st.subheader(
                        f"Centro de Control Operativo - {vista_admin}"
                    )

                    st.caption(
                        "Detalle completo del área seleccionada: "
                        "OTs, actividades, avance, responsables, "
                        "fechas, HH, criticidad y última actualización."
                    )

                # Reconstruimos el estado completo para mostrar
                # también actividades culminadas y no iniciadas.
                detalle_operativo_admin = build_activity_status(
                    df_actividades_admin,
                    df_avances_admin
                )

                if detalle_operativo_admin.empty:

                    st.info(
                        "No existen actividades para mostrar "
                        "en la vista seleccionada."
                    )

                else:

                    # -----------------------------------------
                    # Incorporar OT, equipo y área
                    # -----------------------------------------

                    detalle_operativo_admin = (
                        detalle_operativo_admin
                        .merge(
                            df_ots_admin[
                                [
                                    "id",
                                    "ot",
                                    "area_id",
                                    "equipo"
                                ]
                            ],
                            left_on="ot_id",
                            right_on="id",
                            how="left",
                            suffixes=(
                                "",
                                "_ot"
                            )
                        )
                    )

                    mapa_area_detalle_admin = {
                        area["id"]: area["nombre"]
                        for area in areas_vista_admin
                    }

                    detalle_operativo_admin[
                        "Área"
                    ] = (
                        detalle_operativo_admin[
                            "area_id"
                        ].map(
                            mapa_area_detalle_admin
                        )
                    )

                    # -----------------------------------------
                    # Estado operativo
                    # -----------------------------------------

                    detalle_operativo_admin[
                        "ESTADO"
                    ] = np.where(
                        detalle_operativo_admin[
                            "avance_real"
                        ] >= 100,
                        "CULMINADA",
                        np.where(
                            detalle_operativo_admin[
                                "avance_real"
                            ] > 0,
                            "EN EJECUCIÓN",
                            "NO INICIADA"
                        )
                    )

                    if (
                        "critica"
                        not in detalle_operativo_admin.columns
                    ):
                        detalle_operativo_admin[
                            "critica"
                        ] = False

                    detalle_operativo_admin[
                        "critica"
                    ] = (
                        detalle_operativo_admin[
                            "critica"
                        ]
                        .fillna(False)
                    )

                    detalle_operativo_admin[
                        "CRITICIDAD"
                    ] = np.where(
                        detalle_operativo_admin[
                            "critica"
                        ],
                        "CRÍTICA",
                        "NORMAL"
                    )

                    # -----------------------------------------
                    # Última actualización en hora Perú
                    # -----------------------------------------

                    if (
                        "fecha_registro"
                        in detalle_operativo_admin.columns
                    ):

                        fecha_ultima_admin = pd.to_datetime(
                            detalle_operativo_admin[
                                "fecha_registro"
                            ],
                            errors="coerce",
                            utc=True
                        )

                        detalle_operativo_admin[
                            "ÚLTIMA ACTUALIZACIÓN"
                        ] = (
                            fecha_ultima_admin
                            .dt.tz_convert(
                                "America/Lima"
                            )
                            .dt.strftime(
                                "%d/%m/%Y %H:%M"
                            )
                        )

                    else:

                        detalle_operativo_admin[
                            "ÚLTIMA ACTUALIZACIÓN"
                        ] = ""

                    # -----------------------------------------
                    # Normalizar números
                    # -----------------------------------------

                    for columna_num_admin in [
                        "avance_real",
                        "personal",
                        "hh_plan"
                    ]:

                        if (
                            columna_num_admin
                            in detalle_operativo_admin.columns
                        ):

                            detalle_operativo_admin[
                                columna_num_admin
                            ] = pd.to_numeric(
                                detalle_operativo_admin[
                                    columna_num_admin
                                ],
                                errors="coerce"
                            ).fillna(0)


                    # -----------------------------------------
                    # SEMÁFOROS Y ALERTAS DE ATRASO
                    # -----------------------------------------

                    ahora_admin = pd.Timestamp.now(tz="America/Lima").tz_localize(None)

                    inicio_admin = pd.to_datetime(
                        detalle_operativo_admin.get(
                            "inicio_plan"
                        ),
                        errors="coerce"
                    )

                    fin_admin = pd.to_datetime(
                        detalle_operativo_admin.get(
                            "fin_plan"
                        ),
                        errors="coerce"
                    )

                    avance_real_admin = pd.to_numeric(
                        detalle_operativo_admin.get(
                            "avance_real",
                            0
                        ),
                        errors="coerce"
                    ).fillna(0)

                    avance_plan_admin = []

                    for fecha_inicio_admin, fecha_fin_admin in zip(
                        inicio_admin,
                        fin_admin
                    ):

                        if (
                            pd.isna(fecha_inicio_admin)
                            or pd.isna(fecha_fin_admin)
                        ):
                            avance_plan_admin.append(0.0)
                            continue

                        if (
                            fecha_fin_admin
                            <= fecha_inicio_admin
                        ):
                            fecha_fin_admin = (
                                fecha_inicio_admin
                                + pd.Timedelta(minutes=1)
                            )

                        if ahora_admin <= fecha_inicio_admin:

                            plan_actividad_admin = 0.0

                        elif ahora_admin >= fecha_fin_admin:

                            plan_actividad_admin = 100.0

                        else:

                            duracion_admin = (
                                fecha_fin_admin
                                - fecha_inicio_admin
                            ).total_seconds()

                            transcurrido_admin = (
                                ahora_admin
                                - fecha_inicio_admin
                            ).total_seconds()

                            plan_actividad_admin = (
                                (
                                    transcurrido_admin
                                    / duracion_admin
                                )
                                * 100
                                if duracion_admin > 0
                                else 100.0
                            )

                        avance_plan_admin.append(
                            max(
                                0.0,
                                min(
                                    100.0,
                                    float(plan_actividad_admin)
                                )
                            )
                        )

                    detalle_operativo_admin[
                        "PLAN ACTUAL (%)"
                    ] = avance_plan_admin

                    detalle_operativo_admin[
                        "DESVIACIÓN (pp)"
                    ] = (
                        avance_real_admin
                        - detalle_operativo_admin[
                            "PLAN ACTUAL (%)"
                        ]
                    ).round(1)

                    def clasificar_alerta_admin(fila):
                        """
                        Semaforización PDP:
                        - Verde: desviación >= -5 pp
                        - Amarillo: entre -5 y -10 pp
                        - Naranja: entre -10 y -20 pp
                        - Rojo: desviación < -20 pp
                        - Vencida: fin_plan < ahora y avance < 100%

                        Actividades críticas:
                        - Verde: desviación >= -5 pp
                        - Naranja: entre -5 y -10 pp
                        - Rojo: desviación < -10 pp
                        """

                        real = float(
                            fila.get("avance_real", 0) or 0
                        )

                        plan = float(
                            fila.get("PLAN ACTUAL (%)", 0) or 0
                        )

                        critica = bool(
                            fila.get("critica", False)
                        )

                        inicio = fila.get("inicio_plan")
                        fin = fila.get("fin_plan")

                        desviacion = real - plan

                        # -------------------------------------
                        # 1. CULMINADA
                        # -------------------------------------

                        if real >= 100:
                            return {
                                "semaforo": "🟢",
                                "nivel": "VERDE",
                                "alerta": "Culminada",
                                "accion": "Sin acción requerida",
                                "prioridad": 90
                            }

                        # -------------------------------------
                        # 2. ACTIVIDAD VENCIDA
                        # -------------------------------------

                        if (
                            pd.notna(fin)
                            and ahora_admin > pd.Timestamp(fin)
                            and real < 100
                        ):
                            return {
                                "semaforo": "🔴",
                                "nivel": "ROJO",
                                "alerta": (
                                    "Crítica vencida"
                                    if critica
                                    else "Vencida"
                                ),
                                "accion": (
                                    "Escalar y definir recuperación inmediata"
                                ),
                                "prioridad": 1 if critica else 2
                            }

                        # -------------------------------------
                        # 3. AÚN NO DEBE INICIAR
                        # -------------------------------------

                        if (
                            pd.notna(inicio)
                            and ahora_admin < pd.Timestamp(inicio)
                        ):
                            return {
                                "semaforo": "⚪",
                                "nivel": "PROGRAMADA",
                                "alerta": (
                                    "Crítica por iniciar"
                                    if critica
                                    else "Por iniciar"
                                ),
                                "accion": (
                                    "Verificar recursos y liberación"
                                    if critica
                                    else "Seguimiento según programa"
                                ),
                                "prioridad": 80
                            }

                        # -------------------------------------
                        # 4. REGLA ESPECIAL: CRÍTICAS
                        # -------------------------------------

                        if critica:

                            if desviacion < -10:
                                return {
                                    "semaforo": "🔴",
                                    "nivel": "ROJO",
                                    "alerta": "Crítica atrasada",
                                    "accion": (
                                        "Escalar y definir recuperación inmediata"
                                    ),
                                    "prioridad": 3
                                }

                            if desviacion < -5:
                                return {
                                    "semaforo": "🟠",
                                    "nivel": "NARANJA",
                                    "alerta": "Crítica en riesgo",
                                    "accion": (
                                        "Aplicar plan de recuperación"
                                    ),
                                    "prioridad": 5
                                }

                            return {
                                "semaforo": "🟢",
                                "nivel": "VERDE",
                                "alerta": "Crítica en línea",
                                "accion": (
                                    "Mantener seguimiento cercano"
                                ),
                                "prioridad": 30
                            }

                        # -------------------------------------
                        # 5. ACTIVIDAD NORMAL
                        # -------------------------------------

                        if desviacion < -20:
                            return {
                                "semaforo": "🔴",
                                "nivel": "ROJO",
                                "alerta": "Atraso crítico",
                                "accion": (
                                    "Intervención inmediata / reprogramar recursos"
                                ),
                                "prioridad": 4
                            }

                        if desviacion < -10:
                            return {
                                "semaforo": "🟠",
                                "nivel": "NARANJA",
                                "alerta": "Atrasada",
                                "accion": (
                                    "Definir plan de recuperación"
                                ),
                                "prioridad": 6
                            }

                        if desviacion < -5:
                            return {
                                "semaforo": "🟡",
                                "nivel": "AMARILLO",
                                "alerta": "En riesgo",
                                "accion": (
                                    "Seguimiento del supervisor"
                                ),
                                "prioridad": 10
                            }

                        return {
                            "semaforo": "🟢",
                            "nivel": "VERDE",
                            "alerta": "En línea",
                            "accion": "Sin acción requerida",
                            "prioridad": 40
                        }


                    clasificacion_admin = (
                        detalle_operativo_admin
                        .apply(
                            clasificar_alerta_admin,
                            axis=1
                        )
                    )

                    detalle_operativo_admin[
                        "SEMÁFORO"
                    ] = clasificacion_admin.map(
                        lambda item: item["semaforo"]
                    )

                    detalle_operativo_admin[
                        "NIVEL"
                    ] = clasificacion_admin.map(
                        lambda item: item["nivel"]
                    )

                    detalle_operativo_admin[
                        "ALERTA"
                    ] = clasificacion_admin.map(
                        lambda item: item["alerta"]
                    )

                    detalle_operativo_admin[
                        "ACCIÓN REQUERIDA"
                    ] = clasificacion_admin.map(
                        lambda item: item["accion"]
                    )

                    detalle_operativo_admin[
                        "_prioridad_alerta"
                    ] = clasificacion_admin.map(
                        lambda item: item["prioridad"]
                    )

                    # -----------------------------------------
                    # RESUMEN EJECUTIVO DE SEMÁFOROS
                    # -----------------------------------------

                    verdes_admin = int(
                        (
                            detalle_operativo_admin[
                                "NIVEL"
                            ]
                            == "VERDE"
                        ).sum()
                    )

                    amarillos_admin = int(
                        (
                            detalle_operativo_admin[
                                "NIVEL"
                            ]
                            == "AMARILLO"
                        ).sum()
                    )

                    naranjas_admin = int(
                        (
                            detalle_operativo_admin[
                                "NIVEL"
                            ]
                            == "NARANJA"
                        ).sum()
                    )

                    rojos_admin = int(
                        (
                            detalle_operativo_admin[
                                "NIVEL"
                            ]
                            == "ROJO"
                        ).sum()
                    )

                    sem1, sem2, sem3, sem4 = st.columns(4)

                    with sem1:
                        st.metric(
                            "🟢 En línea",
                            verdes_admin
                        )

                    with sem2:
                        st.metric(
                            "🟡 En riesgo",
                            amarillos_admin
                        )

                    with sem3:
                        st.metric(
                            "🟠 Recuperación",
                            naranjas_admin
                        )

                    with sem4:
                        st.metric(
                            "🔴 Intervención",
                            rojos_admin
                        )

                    alertas_prioritarias_admin = (
                        detalle_operativo_admin[
                            detalle_operativo_admin[
                                "NIVEL"
                            ].isin(
                                [
                                    "ROJO",
                                    "NARANJA",
                                    "AMARILLO"
                                ]
                            )
                        ]
                        .sort_values(
                            [
                                "_prioridad_alerta",
                                "avance_real"
                            ],
                            ascending=[
                                True,
                                True
                            ]
                        )
                        .copy()
                    )

                    if not alertas_prioritarias_admin.empty:

                        st.markdown(
                            "#### Situaciones que requieren atención"
                        )

                        st.caption(
                            "Prioridad automática según desviación "
                            "PLAN vs REAL, criticidad y vencimiento."
                        )

                        columnas_alertas_admin = [
                            "SEMÁFORO",
                            "ALERTA",
                            "Área",
                            "ot",
                            "equipo",
                            "codigo_actividad",
                            "descripcion",
                            "PLAN ACTUAL (%)",
                            "avance_real",
                            "DESVIACIÓN (pp)",
                            "supervisor",
                            "fin_plan",
                            "ACCIÓN REQUERIDA"
                        ]

                        columnas_alertas_admin = [
                            columna
                            for columna
                            in columnas_alertas_admin
                            if columna
                            in alertas_prioritarias_admin.columns
                        ]

                        tabla_alertas_admin = (
                            alertas_prioritarias_admin[
                                columnas_alertas_admin
                            ]
                            .head(20)
                            .copy()
                        )

                        tabla_alertas_admin = (
                            tabla_alertas_admin
                            .rename(
                                columns={
                                    "ot": "OT",
                                    "equipo": "EQUIPO",
                                    "codigo_actividad":
                                        "ACTIVIDAD",
                                    "descripcion":
                                        "DESCRIPCIÓN",
                                    "avance_real":
                                        "REAL (%)",
                                    "supervisor":
                                        "SUPERVISOR",
                                    "fin_plan":
                                        "FIN PLAN"
                                }
                            )
                        )

                        st.dataframe(
                            tabla_alertas_admin,
                            use_container_width=True,
                            hide_index=True,
                            height=360
                        )

                    # -----------------------------------------
                    # KPIs rápidos de la vista operativa
                    # -----------------------------------------

                    total_operativo_admin = len(
                        detalle_operativo_admin
                    )

                    ejecucion_operativo_admin = int(
                        (
                            detalle_operativo_admin[
                                "ESTADO"
                            ]
                            == "EN EJECUCIÓN"
                        ).sum()
                    )

                    culminadas_operativo_admin = int(
                        (
                            detalle_operativo_admin[
                                "ESTADO"
                            ]
                            == "CULMINADA"
                        ).sum()
                    )

                    no_iniciadas_operativo_admin = int(
                        (
                            detalle_operativo_admin[
                                "ESTADO"
                            ]
                            == "NO INICIADA"
                        ).sum()
                    )

                    criticas_operativo_admin = int(
                        detalle_operativo_admin[
                            "critica"
                        ].sum()
                    )

                    op1, op2, op3, op4, op5 = st.columns(
                        5
                    )

                    with op1:

                        st.metric(
                            "Total actividades",
                            total_operativo_admin
                        )

                    with op2:

                        st.metric(
                            "En ejecución",
                            ejecucion_operativo_admin
                        )

                    with op3:

                        st.metric(
                            "Culminadas",
                            culminadas_operativo_admin
                        )

                    with op4:

                        st.metric(
                            "No iniciadas",
                            no_iniciadas_operativo_admin
                        )

                    with op5:

                        st.metric(
                            "Críticas",
                            criticas_operativo_admin
                        )

                    st.markdown(
                        "#### Filtros operativos"
                    )

                    # -----------------------------------------
                    # FILTROS FILA 1
                    # -----------------------------------------

                    filtro1, filtro2, filtro3 = st.columns(
                        3
                    )

                    with filtro1:

                        if (
                            area_id_seleccionada_admin
                            is None
                        ):

                            opciones_area_operativa = (
                                ["TODAS"]
                                + sorted(
                                    detalle_operativo_admin[
                                        "Área"
                                    ]
                                    .dropna()
                                    .astype(str)
                                    .unique()
                                    .tolist()
                                )
                            )

                            filtro_area_operativa = (
                                st.selectbox(
                                    "Área",
                                    opciones_area_operativa,
                                    key=(
                                        "admin_operativo_area"
                                    )
                                )
                            )

                        else:

                            filtro_area_operativa = (
                                vista_admin
                            )

                    with filtro2:

                        opciones_ot_operativa = (
                            ["TODAS"]
                            + sorted(
                                detalle_operativo_admin[
                                    "ot"
                                ]
                                .dropna()
                                .astype(str)
                                .unique()
                                .tolist()
                            )
                        )

                        filtro_ot_operativa = st.selectbox(
                            "OT",
                            opciones_ot_operativa,
                            key="admin_operativo_ot"
                        )

                    with filtro3:

                        opciones_estado_operativo = [
                            "TODOS",
                            "NO INICIADA",
                            "EN EJECUCIÓN",
                            "CULMINADA"
                        ]

                        filtro_estado_operativo = (
                            st.selectbox(
                                "Estado",
                                opciones_estado_operativo,
                                key=(
                                    "admin_operativo_estado"
                                )
                            )
                        )

                    # -----------------------------------------
                    # FILTROS FILA 2
                    # -----------------------------------------

                    filtro4, filtro5, filtro6 = st.columns(
                        3
                    )

                    with filtro4:

                        supervisores_operativos = (
                            ["TODOS"]
                            + sorted(
                                detalle_operativo_admin[
                                    "supervisor"
                                ]
                                .dropna()
                                .astype(str)
                                .loc[
                                    lambda serie:
                                    serie.str.strip()
                                    != ""
                                ]
                                .unique()
                                .tolist()
                            )
                            if (
                                "supervisor"
                                in detalle_operativo_admin.columns
                            )
                            else ["TODOS"]
                        )

                        filtro_supervisor_operativo = (
                            st.selectbox(
                                "Supervisor",
                                supervisores_operativos,
                                key=(
                                    "admin_operativo_supervisor"
                                )
                            )
                        )

                    with filtro5:

                        especialidades_operativas = (
                            ["TODAS"]
                            + sorted(
                                detalle_operativo_admin[
                                    "especialidad"
                                ]
                                .dropna()
                                .astype(str)
                                .loc[
                                    lambda serie:
                                    serie.str.strip()
                                    != ""
                                ]
                                .unique()
                                .tolist()
                            )
                            if (
                                "especialidad"
                                in detalle_operativo_admin.columns
                            )
                            else ["TODAS"]
                        )

                        filtro_especialidad_operativa = (
                            st.selectbox(
                                "Especialidad",
                                especialidades_operativas,
                                key=(
                                    "admin_operativo_especialidad"
                                )
                            )
                        )

                    with filtro6:

                        filtro_alerta_operativa = (
                            st.selectbox(
                                "Semáforo",
                                [
                                    "TODOS",
                                    "ROJO",
                                    "NARANJA",
                                    "AMARILLO",
                                    "VERDE",
                                    "PROGRAMADA"
                                ],
                                key=(
                                    "admin_operativo_alerta"
                                )
                            )
                        )

                    busqueda_operativa_admin = st.text_input(
                        "Buscar por OT, equipo, actividad o descripción",
                        placeholder=(
                            "Ejemplo: 7169908, SAG, ACT-009..."
                        ),
                        key="admin_operativo_busqueda"
                    )

                    # -----------------------------------------
                    # APLICAR FILTROS
                    # -----------------------------------------

                    detalle_filtrado_admin = (
                        detalle_operativo_admin.copy()
                    )

                    if (
                        area_id_seleccionada_admin
                        is None
                        and filtro_area_operativa
                        != "TODAS"
                    ):

                        detalle_filtrado_admin = (
                            detalle_filtrado_admin[
                                detalle_filtrado_admin[
                                    "Área"
                                ].astype(str)
                                == filtro_area_operativa
                            ]
                        )

                    if filtro_ot_operativa != "TODAS":

                        detalle_filtrado_admin = (
                            detalle_filtrado_admin[
                                detalle_filtrado_admin[
                                    "ot"
                                ].astype(str)
                                == filtro_ot_operativa
                            ]
                        )

                    if (
                        filtro_estado_operativo
                        != "TODOS"
                    ):

                        detalle_filtrado_admin = (
                            detalle_filtrado_admin[
                                detalle_filtrado_admin[
                                    "ESTADO"
                                ]
                                == filtro_estado_operativo
                            ]
                        )

                    if (
                        filtro_supervisor_operativo
                        != "TODOS"
                        and "supervisor"
                        in detalle_filtrado_admin.columns
                    ):

                        detalle_filtrado_admin = (
                            detalle_filtrado_admin[
                                detalle_filtrado_admin[
                                    "supervisor"
                                ].astype(str)
                                == filtro_supervisor_operativo
                            ]
                        )

                    if (
                        filtro_especialidad_operativa
                        != "TODAS"
                        and "especialidad"
                        in detalle_filtrado_admin.columns
                    ):

                        detalle_filtrado_admin = (
                            detalle_filtrado_admin[
                                detalle_filtrado_admin[
                                    "especialidad"
                                ].astype(str)
                                == filtro_especialidad_operativa
                            ]
                        )

                    if (
                        filtro_alerta_operativa
                        != "TODOS"
                    ):

                        detalle_filtrado_admin = (
                            detalle_filtrado_admin[
                                detalle_filtrado_admin[
                                    "NIVEL"
                                ]
                                == filtro_alerta_operativa
                            ]
                        )

                    if busqueda_operativa_admin.strip():

                        termino_operativo_admin = (
                            busqueda_operativa_admin
                            .strip()
                            .lower()
                        )

                        mascara_busqueda_admin = (
                            pd.Series(
                                False,
                                index=(
                                    detalle_filtrado_admin.index
                                )
                            )
                        )

                        for columna_busqueda_admin in [
                            "ot",
                            "equipo",
                            "codigo_actividad",
                            "descripcion"
                        ]:

                            if (
                                columna_busqueda_admin
                                in detalle_filtrado_admin.columns
                            ):

                                mascara_busqueda_admin = (
                                    mascara_busqueda_admin
                                    |
                                    detalle_filtrado_admin[
                                        columna_busqueda_admin
                                    ]
                                    .fillna("")
                                    .astype(str)
                                    .str.lower()
                                    .str.contains(
                                        termino_operativo_admin,
                                        regex=False
                                    )
                                )

                        detalle_filtrado_admin = (
                            detalle_filtrado_admin[
                                mascara_busqueda_admin
                            ]
                        )

                    # -----------------------------------------
                    # RESULTADO FILTRADO
                    # -----------------------------------------

                    st.caption(
                        f"{len(detalle_filtrado_admin)} "
                        "actividad(es) encontradas con los "
                        "filtros seleccionados."
                    )

                    columnas_operativas_admin = [
                        "SEMÁFORO",
                        "ALERTA",
                        "Área",
                        "ot",
                        "equipo",
                        "codigo_actividad",
                        "descripcion",
                        "ESTADO",
                        "PLAN ACTUAL (%)",
                        "avance_real",
                        "DESVIACIÓN (pp)",
                        "CRITICIDAD",
                        "supervisor",
                        "especialidad",
                        "grupo",
                        "inicio_plan",
                        "fin_plan",
                        "personal",
                        "hh_plan",
                        "ÚLTIMA ACTUALIZACIÓN",
                        "ACCIÓN REQUERIDA",
                        "descripcion_avance",
                        "observaciones"
                    ]

                    columnas_operativas_admin = [
                        columna
                        for columna
                        in columnas_operativas_admin
                        if columna
                        in detalle_filtrado_admin.columns
                    ]

                    detalle_filtrado_admin = (
                        detalle_filtrado_admin
                        .sort_values(
                            [
                                "_prioridad_alerta",
                                "avance_real"
                            ],
                            ascending=[
                                True,
                                True
                            ]
                        )
                    )

                    tabla_operativa_admin = (
                        detalle_filtrado_admin[
                            columnas_operativas_admin
                        ]
                        .copy()
                    )

                    tabla_operativa_admin = (
                        tabla_operativa_admin
                        .rename(
                            columns={
                                "ot": "OT",
                                "equipo": "EQUIPO",
                                "codigo_actividad":
                                    "ACTIVIDAD",
                                "descripcion":
                                    "DESCRIPCIÓN",
                                "avance_real":
                                    "AVANCE (%)",
                                "supervisor":
                                    "SUPERVISOR",
                                "especialidad":
                                    "ESPECIALIDAD",
                                "grupo":
                                    "GRUPO",
                                "inicio_plan":
                                    "INICIO PLAN",
                                "fin_plan":
                                    "FIN PLAN",
                                "personal":
                                    "PERSONAL",
                                "hh_plan":
                                    "HH PLAN",
                                "descripcion_avance":
                                    "ÚLTIMO AVANCE",
                                "observaciones":
                                    "OBSERVACIONES"
                            }
                        )
                    )

                    if "AVANCE (%)" in (
                        tabla_operativa_admin.columns
                    ):

                        tabla_operativa_admin[
                            "AVANCE (%)"
                        ] = (
                            tabla_operativa_admin[
                                "AVANCE (%)"
                            ]
                            .round(1)
                        )

                    if "HH PLAN" in (
                        tabla_operativa_admin.columns
                    ):

                        tabla_operativa_admin[
                            "HH PLAN"
                        ] = (
                            tabla_operativa_admin[
                                "HH PLAN"
                            ]
                            .round(0)
                        )

                    st.dataframe(
                        tabla_operativa_admin,
                        use_container_width=True,
                        hide_index=True,
                        height=600
                    )

                    # -----------------------------------------
                    # DETALLE RÁPIDO DE UNA ACTIVIDAD
                    # -----------------------------------------

                    if not detalle_filtrado_admin.empty:

                        st.markdown(
                            "#### Detalle rápido de actividad"
                        )

                        opciones_actividad_admin = {}

                        for _, fila_admin in (
                            detalle_filtrado_admin.iterrows()
                        ):

                            etiqueta_admin = (
                                f"OT {fila_admin.get('ot', '')} | "
                                f"{fila_admin.get('codigo_actividad', '')} | "
                                f"{fila_admin.get('descripcion', '')}"
                            )

                            opciones_actividad_admin[
                                etiqueta_admin
                            ] = fila_admin

                        actividad_admin_texto = st.selectbox(
                            "Seleccionar actividad",
                            list(
                                opciones_actividad_admin.keys()
                            ),
                            key=(
                                "admin_operativo_actividad"
                            )
                        )

                        actividad_admin_detalle = (
                            opciones_actividad_admin[
                                actividad_admin_texto
                            ]
                        )

                        det1, det2, det3, det4 = st.columns(
                            4
                        )

                        with det1:

                            st.metric(
                                "Avance",
                                f"{float(actividad_admin_detalle.get('avance_real', 0)):.1f}%"
                            )

                        with det2:

                            st.metric(
                                "Estado",
                                actividad_admin_detalle.get(
                                    "ESTADO",
                                    ""
                                )
                            )

                        with det3:

                            st.metric(
                                "Personal",
                                int(
                                    float(
                                        actividad_admin_detalle.get(
                                            "personal",
                                            0
                                        )
                                        or 0
                                    )
                                )
                            )

                        with det4:

                            st.metric(
                                "HH plan",
                                f"{float(actividad_admin_detalle.get('hh_plan', 0) or 0):.0f}"
                            )

                        dta1, dta2 = st.columns(
                            2
                        )

                        with dta1:

                            st.write(
                                "**Supervisor:** "
                                f"{actividad_admin_detalle.get('supervisor') or '-'}"
                            )

                            st.write(
                                "**Especialidad:** "
                                f"{actividad_admin_detalle.get('especialidad') or '-'}"
                            )

                            st.write(
                                "**Grupo:** "
                                f"{actividad_admin_detalle.get('grupo') or '-'}"
                            )

                            st.write(
                                "**Criticidad:** "
                                f"{actividad_admin_detalle.get('CRITICIDAD') or '-'}"
                            )

                        with dta2:

                            st.write(
                                "**Inicio plan:** "
                                f"{actividad_admin_detalle.get('inicio_plan') or '-'}"
                            )

                            st.write(
                                "**Fin plan:** "
                                f"{actividad_admin_detalle.get('fin_plan') or '-'}"
                            )

                            st.write(
                                "**Última actualización:** "
                                f"{actividad_admin_detalle.get('ÚLTIMA ACTUALIZACIÓN') or 'Sin reporte'}"
                            )

                        ultimo_avance_admin = (
                            actividad_admin_detalle.get(
                                "descripcion_avance"
                            )
                            or ""
                        )

                        observaciones_admin = (
                            actividad_admin_detalle.get(
                                "observaciones"
                            )
                            or ""
                        )

                        if ultimo_avance_admin:

                            st.info(
                                "**Último avance reportado:** "
                                f"{ultimo_avance_admin}"
                            )

                        if observaciones_admin:

                            st.warning(
                                "**Observaciones / Restricciones:** "
                                f"{observaciones_admin}"
                            )


    # =====================================================
    # IMPORTAR PLANIFICACIÓN
    # =====================================================

    elif pagina_admin == "Importar planificación":

        st.subheader("Importar planificación por área")

        st.warning(
            "La planificación que se cargue corresponderá "
            "únicamente al área seleccionada."
        )

        resultado_areas = (
            supabase
            .table("areas")
            .select("id,codigo,nombre")
            .eq("activo", True)
            .order("id")
            .execute()
        )

        areas_disponibles = resultado_areas.data or []

        mapa_areas = {
            f"{area['codigo']} - {area['nombre']}": area
            for area in areas_disponibles
        }

        if not mapa_areas:

            st.error(
                "No existen áreas disponibles en la base de datos."
            )

        else:

            area_texto = st.selectbox(
                "Seleccione el área",
                list(mapa_areas.keys())
            )

            area_seleccionada = mapa_areas[area_texto]

            st.info(
                f"Área seleccionada: "
                f"{area_seleccionada['nombre']}"
            )

            archivo = st.file_uploader(
                "Seleccione el Excel de planificación",
                type=["xlsx"]
            )

            if archivo is not None:

                try:

                    df_ots = pd.read_excel(
                        archivo,
                        sheet_name="OTs"
                    )

                    df_actividades = pd.read_excel(
                        archivo,
                        sheet_name="Actividades"
                    )

                    st.success(
                        f"Archivo leído correctamente: "
                        f"{len(df_ots)} OTs y "
                        f"{len(df_actividades)} actividades."
                    )

                    st.write("Vista previa de OTs")

                    st.dataframe(
                        df_ots.head(10),
                        use_container_width=True,
                        hide_index=True
                    )

                    st.divider()

                    confirmar = st.checkbox(
                        f"Confirmo que deseo reemplazar la planificación de "
                        f"{area_seleccionada['nombre']}."
                    )

                    texto_confirmacion = st.text_input(
                        "Para confirmar escriba exactamente: REEMPLAZAR"
                    )

                    puede_importar = (
                        confirmar
                        and texto_confirmacion.strip().upper() == "REEMPLAZAR"
                    )

                    if st.button(
                        "REEMPLAZAR PLANIFICACIÓN DEL ÁREA",
                        type="primary",
                        use_container_width=True,
                        disabled=not puede_importar
                    ):

                        try:

                            area_id = area_seleccionada["id"]

                            progreso = st.progress(
                                5,
                                text="Preparando información..."
                            )

                            # ==========================================
                            # VALIDAR COLUMNAS
                            # ==========================================

                            columnas_ots = {
                                "ot",
                                "equipo",
                                "descripcion"
                            }

                            columnas_actividades = {
                                "ot",
                                "codigo_actividad",
                                "descripcion",
                                "supervisor",
                                "especialidad",
                                "grupo",
                                "peso",
                                "inicio_plan",
                                "fin_plan",
                                "seccion",
                                "personal",
                                "duracion_h",
                                "hh_plan"
                            }

                            faltantes_ots = (
                                columnas_ots - set(df_ots.columns)
                            )

                            faltantes_act = (
                                columnas_actividades
                                - set(df_actividades.columns)
                            )

                            if faltantes_ots:
                                raise ValueError(
                                    "Faltan columnas en OTs: "
                                    + ", ".join(sorted(faltantes_ots))
                                )

                            if faltantes_act:
                                raise ValueError(
                                    "Faltan columnas en Actividades: "
                                    + ", ".join(sorted(faltantes_act))
                                )

                            progreso.progress(
                                15,
                                text="Limpiando OTs..."
                            )

                            # ==========================================
                            # PREPARAR OTs
                            # ==========================================

                            ots_limpias = []

                            for _, row in df_ots.iterrows():

                                ot = limpiar_texto(row.get("ot"))

                                if not ot:
                                    continue

                                ots_limpias.append({
                                    "ot": ot,
                                    "area_id": area_id,
                                    "equipo": limpiar_texto(
                                        row.get("equipo")
                                    ),
                                    "descripcion": limpiar_texto(
                                        row.get("descripcion")
                                    ),
                                    "activo": True
                                })

                            if not ots_limpias:
                                raise ValueError(
                                    "No existen OTs válidas para importar."
                                )

                            # ==========================================
                            # BUSCAR INFORMACIÓN EXISTENTE DEL ÁREA
                            # ==========================================

                            progreso.progress(
                                25,
                                text="Revisando planificación anterior..."
                            )

                            ots_actuales = (
                                supabase_admin
                                .table("ots")
                                .select("id")
                                .eq("area_id", area_id)
                                .execute()
                            ).data or []

                            ot_ids = [
                                x["id"]
                                for x in ots_actuales
                            ]

                            # ==========================================
                            # ELIMINAR AVANCES Y ACTIVIDADES ANTERIORES
                            # ==========================================

                            if ot_ids:

                                actividades_actuales = (
                                    supabase_admin
                                    .table("actividades")
                                    .select("id,ot_id")
                                    .in_("ot_id", ot_ids)
                                    .execute()
                                ).data or []

                                actividad_ids = [
                                    x["id"]
                                    for x in actividades_actuales
                                ]

                                if actividad_ids:

                                    supabase_admin.table(
                                        "avances_actividad"
                                    ).delete().in_(
                                        "actividad_id",
                                        actividad_ids
                                    ).execute()

                                    supabase_admin.table(
                                        "actividades"
                                    ).delete().in_(
                                        "id",
                                        actividad_ids
                                    ).execute()

                                progreso.progress(
                                    40,
                                    text="Eliminando OTs anteriores..."
                                )

                                supabase_admin.table(
                                    "ots"
                                ).delete().eq(
                                    "area_id",
                                    area_id
                                ).execute()

                            # ==========================================
                            # INSERTAR NUEVAS OTs
                            # ==========================================

                            progreso.progress(
                                55,
                                text="Cargando nuevas OTs..."
                            )

                            (
                                supabase_admin
                                .table("ots")
                                .insert(ots_limpias)
                                .execute()
                            )

                            # ==========================================
                            # RECUPERAR IDs DE LAS NUEVAS OTs
                            # ==========================================

                            ots_nuevas = (
                                supabase_admin
                                .table("ots")
                                .select("id,ot")
                                .eq("area_id", area_id)
                                .execute()
                            ).data or []

                            mapa_ots = {
                                str(x["ot"]): x["id"]
                                for x in ots_nuevas
                            }

                            progreso.progress(
                                65,
                                text="Preparando actividades..."
                            )

                            # ==========================================
                            # PREPARAR ACTIVIDADES
                            # ==========================================

                            actividades_limpias = []
                            ots_no_encontradas = []

                            for _, row in df_actividades.iterrows():

                                ot = limpiar_texto(
                                    row.get("ot")
                                )

                                codigo = limpiar_texto(
                                    row.get("codigo_actividad")
                                )

                                descripcion = limpiar_texto(
                                    row.get("descripcion")
                                )

                                if not ot or not codigo or not descripcion:
                                    continue

                                if ot not in mapa_ots:
                                    ots_no_encontradas.append(ot)
                                    continue

                                actividades_limpias.append({
                                    "ot_id": mapa_ots[ot],
                                    "codigo_actividad": codigo,
                                    "descripcion": descripcion,
                                    "supervisor": limpiar_texto(
                                        row.get("supervisor")
                                    ),
                                    "especialidad": limpiar_texto(
                                        row.get("especialidad")
                                    ),
                                    "grupo": limpiar_texto(
                                        row.get("grupo")
                                    ),
                                    "peso": limpiar_numero(
                                        row.get("peso"),
                                        1
                                    ),
                                    "inicio_plan": limpiar_fecha(
                                        row.get("inicio_plan")
                                    ),
                                    "fin_plan": limpiar_fecha(
                                        row.get("fin_plan")
                                    ),
                                    "seccion": limpiar_texto(
                                        row.get("seccion")
                                    ),
                                    "personal": limpiar_entero(
                                        row.get("personal")
                                    ),
                                    "duracion_h": limpiar_numero(
                                        row.get("duracion_h")
                                    ),
                                    "hh_plan": limpiar_numero(
                                        row.get("hh_plan")
                                    ),
                                    "critica": False,
                                    "activo": True
                                })

                            if ots_no_encontradas:
                                raise ValueError(
                                    "Estas OTs aparecen en Actividades "
                                    "pero no en la hoja OTs: "
                                    + ", ".join(
                                        sorted(set(ots_no_encontradas))
                                    )
                                )

                            if not actividades_limpias:
                                raise ValueError(
                                    "No existen actividades válidas."
                                )

                            # ==========================================
                            # INSERTAR ACTIVIDADES
                            # ==========================================

                            progreso.progress(
                                80,
                                text="Cargando actividades..."
                            )

                            batch_size = 200

                            for inicio in range(
                                0,
                                len(actividades_limpias),
                                batch_size
                            ):

                                lote = actividades_limpias[
                                    inicio:inicio + batch_size
                                ]

                                (
                                    supabase_admin
                                    .table("actividades")
                                    .insert(lote)
                                    .execute()
                                )

                            progreso.progress(
                                100,
                                text="Importación completada."
                            )

                            st.success(
                                f"Planificación de "
                                f"{area_seleccionada['nombre']} "
                                f"actualizada correctamente: "
                                f"{len(ots_limpias)} OTs y "
                                f"{len(actividades_limpias)} actividades."
                            )

                            st.balloons()

                        except Exception as import_error:

                            st.error(
                                "No fue posible importar la planificación: "
                                f"{import_error}"
                            )

                    st.write("Vista previa de actividades")

                    st.dataframe(
                        df_actividades.head(10),
                        use_container_width=True,
                        hide_index=True
                    )

                except Exception as exc:

                    st.error(
                        f"No fue posible leer el Excel: {exc}"
                    )


    # =====================================================
    # ADMINISTRAR OTs
    # =====================================================

    elif pagina_admin == "Administrar OTs":

        st.subheader("Administrar OTs")

        st.info(
            "Aquí administraremos las OTs "
            "de todas las áreas."
        )


    # =====================================================
    # REPORTES
    # =====================================================

    elif pagina_admin == "Reportes":

        st.subheader("Reportes gerenciales")

        st.caption(
            "Genere el informe ejecutivo de Todas las áreas "
            "o de un área específica sin salir de la sesión ADMIN."
        )

        resultado_areas_reporte_admin = (
            supabase
            .table("areas")
            .select("id,codigo,nombre")
            .eq("activo", True)
            .order("id")
            .execute()
        )

        areas_reporte_admin = (
            resultado_areas_reporte_admin.data
            or []
        )

        if not areas_reporte_admin:

            st.warning(
                "No existen áreas activas configuradas."
            )

        else:

            opciones_reporte_admin = {
                "Todas las áreas": None
            }

            for area in areas_reporte_admin:
                opciones_reporte_admin[
                    area["nombre"]
                ] = area["id"]

            vista_reporte_admin = st.selectbox(
                "Seleccionar reporte",
                list(
                    opciones_reporte_admin.keys()
                ),
                key="selector_reporte_admin"
            )

            area_reporte_admin_id = (
                opciones_reporte_admin[
                    vista_reporte_admin
                ]
            )

            if area_reporte_admin_id is None:

                ids_area_reporte_admin = [
                    area["id"]
                    for area in areas_reporte_admin
                ]

                nombre_reporte_admin = (
                    "Todas las áreas"
                )

                codigo_reporte_admin = (
                    "consolidado"
                )

            else:

                ids_area_reporte_admin = [
                    area_reporte_admin_id
                ]

                area_obj_reporte_admin = next(
                    area
                    for area in areas_reporte_admin
                    if area["id"]
                    == area_reporte_admin_id
                )

                nombre_reporte_admin = (
                    area_obj_reporte_admin[
                        "nombre"
                    ]
                )

                codigo_reporte_admin = (
                    area_obj_reporte_admin[
                        "codigo"
                    ]
                )

            ots_reporte_admin = (
                supabase
                .table("ots")
                .select(
                    "id,ot,equipo,descripcion,activo,area_id"
                )
                .in_(
                    "area_id",
                    ids_area_reporte_admin
                )
                .eq(
                    "activo",
                    True
                )
                .execute()
            ).data or []

            if not ots_reporte_admin:

                st.warning(
                    "No existen OTs activas para "
                    "la vista seleccionada."
                )

            else:

                df_ots_reporte_admin = pd.DataFrame(
                    ots_reporte_admin
                )

                ids_ots_reporte_admin = [
                    ot["id"]
                    for ot in ots_reporte_admin
                ]

                actividades_reporte_admin = (
                    supabase
                    .table("actividades")
                    .select(
                        "id,ot_id,codigo_actividad,descripcion,"
                        "supervisor,especialidad,grupo,peso,"
                        "inicio_plan,fin_plan,seccion,personal,"
                        "duracion_h,hh_plan,critica,activo"
                    )
                    .in_(
                        "ot_id",
                        ids_ots_reporte_admin
                    )
                    .eq(
                        "activo",
                        True
                    )
                    .execute()
                ).data or []

                if not actividades_reporte_admin:

                    st.warning(
                        "No existen actividades para "
                        "la vista seleccionada."
                    )

                else:

                    df_actividades_reporte_admin = (
                        pd.DataFrame(
                            actividades_reporte_admin
                        )
                    )

                    ids_act_reporte_admin = (
                        df_actividades_reporte_admin[
                            "id"
                        ]
                        .dropna()
                        .tolist()
                    )

                    avances_reporte_admin = (
                        supabase
                        .table("avances_actividad")
                        .select(
                            "id,actividad_id,avance,"
                            "descripcion_avance,observaciones,"
                            "tipo_evidencia,critica,evidencias,"
                            "usuario,fecha_registro"
                        )
                        .in_(
                            "actividad_id",
                            ids_act_reporte_admin
                        )
                        .execute()
                    ).data or []

                    df_avances_reporte_admin = (
                        pd.DataFrame(
                            avances_reporte_admin
                        )
                    )

                    kpis_reporte_admin = compute_kpis(
                        df_actividades_reporte_admin,
                        df_avances_reporte_admin
                    )

                    ar1, ar2, ar3, ar4 = st.columns(
                        4
                    )

                    with ar1:
                        st.metric(
                            "OTs",
                            len(
                                df_ots_reporte_admin
                            )
                        )

                    with ar2:
                        st.metric(
                            "Actividades",
                            kpis_reporte_admin[
                                "actividades"
                            ]
                        )

                    with ar3:
                        st.metric(
                            "Avance general",
                            f"{kpis_reporte_admin['avance_general']:.1f}%"
                        )

                    with ar4:
                        st.metric(
                            "SPI",
                            f"{kpis_reporte_admin['spi']:.2f}"
                        )

                    st.divider()

                    st.markdown(
                        "### Informe ejecutivo para gerencia"
                    )

                    st.write(
                        "Incluye KPIs, Curva S PLAN vs REAL, "
                        "semáforo ejecutivo, foco de atención, "
                        "acciones requeridas, resumen operativo "
                        "y detalle por OT."
                    )

                    try:

                        pdf_admin_bytes = (
                            construir_pdf_ejecutivo_area(
                                df_ots_reporte_admin,
                                df_actividades_reporte_admin,
                                df_avances_reporte_admin,
                                nombre_reporte_admin
                            )
                        )

                        st.download_button(
                            "Descargar informe gerencial PDF",
                            data=pdf_admin_bytes,
                            file_name=(
                                "PDP_Chinalco_"
                                f"{str(codigo_reporte_admin).lower()}_"
                                f"{datetime.now():%Y%m%d_%H%M}.pdf"
                            ),
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True
                        )

                    except Exception as exc:

                        st.error(
                            "No fue posible generar el "
                            f"reporte gerencial: {exc}"
                        )


else:

    # =====================================================
    # MENÚ DEL USUARIO POR ÁREA
    # =====================================================

    with st.sidebar:

        st.divider()

        opciones_menu = menu_por_rol(
            rol
        )

        if not opciones_menu:
            st.error(
                "Este usuario no tiene permisos "
                "de menú configurados."
            )
            st.stop()

        pagina = st.radio(
            "Menú",
            opciones_menu
        )


    # =====================================================
    # OBTENER OTs DEL ÁREA DEL USUARIO
    # =====================================================

    resultado_ots = (
        supabase
        .table("ots")
        .select("id,ot,equipo,descripcion,activo,area_id")
        .eq("area_id", usuario["area_id"])
        .eq("activo", True)
        .execute()
    )

    ots_area = resultado_ots.data or []


    # =====================================================
    # DASHBOARD
    # =====================================================

    if pagina == "Dashboard":

        st.subheader(f"Dashboard - {nombre_area}")

        # =================================================
        # 1. CARGAR ACTIVIDADES DEL ÁREA
        # =================================================

        ot_ids = [ot["id"] for ot in ots_area]

        if ot_ids:

            actividades_data = (
                supabase
                .table("actividades")
                .select(
                    "id,ot_id,codigo_actividad,descripcion,"
                    "supervisor,especialidad,grupo,peso,"
                    "inicio_plan,fin_plan,seccion,personal,"
                    "duracion_h,hh_plan,critica,activo"
                )
                .in_("ot_id", ot_ids)
                .eq("activo", True)
                .execute()
            ).data or []

        else:
            actividades_data = []

        df_ots = pd.DataFrame(ots_area)
        df_actividades = pd.DataFrame(actividades_data)

        # =================================================
        # 2. CARGAR AVANCES
        # =================================================

        if not df_actividades.empty:

            actividad_ids = (
                df_actividades["id"]
                .dropna()
                .tolist()
            )

            avances_data = (
                supabase
                .table("avances_actividad")
                .select(
                    "id,actividad_id,avance,"
                    "descripcion_avance,observaciones,"
                    "tipo_evidencia,critica,evidencias,"
                    "usuario,fecha_registro"
                )
                .in_("actividad_id", actividad_ids)
                .execute()
            ).data or []

        else:
            avances_data = []

        df_avances = pd.DataFrame(avances_data)

        # =================================================
        # 3. SI TODAVÍA NO HAY PLANIFICACIÓN
        # =================================================

        if df_actividades.empty:

            st.warning(
                "No existen actividades cargadas para esta área."
            )

        else:

            # =============================================
            # 4. PREPARAR DATOS
            # =============================================

            df_estado = build_activity_status(
                df_actividades,
                df_avances
            )

            kpis = compute_kpis(
                df_actividades,
                df_avances
            )

            curva_s = build_s_curve(
                df_actividades,
                df_avances
            )

            # Incorporar información de OT y equipo
            if not df_ots.empty:

                datos_ot = (
                    df_ots[
                        [
                            "id",
                            "ot",
                            "equipo",
                            "descripcion"
                        ]
                    ]
                    .rename(
                        columns={
                            "id": "ot_id",
                            "descripcion": "descripcion_ot"
                        }
                    )
                )

                df_estado = df_estado.merge(
                    datos_ot,
                    on="ot_id",
                    how="left"
                )

            # =============================================
            # 5. ENCABEZADO
            # =============================================

            st.caption(
                f"Control operativo exclusivo de {nombre_area} · "
                f"{len(df_ots)} OTs · "
                f"{len(df_actividades)} actividades"
            )

            # =============================================
            # 6. KPIs PRINCIPALES
            # =============================================

            avance_real = float(
                kpis.get("avance_general", 0)
            )

            avance_plan = float(
                kpis.get("avance_plan", 0)
            )

            desviacion = (
                avance_real - avance_plan
            )

            spi = float(
                kpis.get("spi", 0)
            )

            hh_plan = float(
                kpis.get("hh_plan", 0)
            )

            hh_ganadas = float(
                kpis.get("hh_ganadas", 0)
            )

            # ========================================================= 
            # INDICADORES PRINCIPALES DEL DASHBOARD
            # =========================================================        
            total_ots = len(ots_area)
            total_actividades = kpis["actividades"]

            avance_general = kpis["avance_general"]
            culminadas = kpis["culminadas"]
            en_ejecucion = kpis["parciales"]
            no_iniciadas = kpis["no_iniciadas"]

            spi = kpis["spi"]
            hh_plan = kpis["hh_plan"]
            hh_ganadas = kpis["hh_ganadas"] 

            # =========================================================
            # FILA 1
            # =========================================================

            c1, c2, c3, c4, c5, c6 = st.columns(6)

            with c1:
                st.metric(
                    "OTs",
                    total_ots
                )

            with c2:
                st.metric(
                    "Actividades",
                    total_actividades
                )

            with c3:
                st.metric(
                    "Avance general",
                    f"{avance_general:.1f}%"
                )    

            with c4:
                st.metric(
                    "Culminadas",
                    culminadas
                )      

            with c5:
                st.metric(
                    "En ejecución",
                    en_ejecucion
                )  

            with c6:
                st.metric(
                    "No iniciadas",
                    no_iniciadas
                )    

            # =========================================================
            # FILA 2
            # =========================================================   

            c7, c8, c9 = st.columns(3)

            with c7:
                st.metric(
                    "SPI",
                    f"{spi:.2f}",
                    help="SPI = Avance Real / Avance Plan"
                )

            with c8:
                st.metric(
                    "HH planificadas",
                    f"{hh_plan:.0f}"
                ) 

            with c9:
                st.metric(
                    "HH ganadas",
                    f"{hh_ganadas:.0f}"
                )

            st.divider()    

            # =============================================
            # 7. SEMÁFORO DEL PROYECTO
            # =============================================

            if avance_plan <= 0:

                st.info(
                    "La planificación aún no ha iniciado "
                    "o no existe un avance plan calculable."
                )

            elif spi >= 1:

                st.success(
                    f"🟢 EN LÍNEA / ADELANTADO · "
                    f"SPI {spi:.2f}"
                )

            elif spi >= 0.90:

                st.warning(
                    f"🟡 DESVIACIÓN CONTROLABLE · "
                    f"SPI {spi:.2f}"
                )

            else:

                st.error(
                    f"🔴 DESVIACIÓN CRÍTICA · "
                    f"SPI {spi:.2f}"
                )        

            st.divider()

            # =============================================
            # 8. CURVA S
            # =============================================

            st.subheader("Curva S - Plan vs Real")

            if curva_s.empty:

                st.info(
                    "No existen fechas suficientes para "
                    "construir la Curva S."
                )

            else:

                fig_s = go.Figure()

                # Etiquetas de porcentaje por cada punto.
                texto_plan = [
                    f"{float(valor):.1f}%"
                    if pd.notna(valor)
                    else ""
                    for valor in curva_s["PLAN"]
                ]

                texto_real = [
                    f"{float(valor):.1f}%"
                    if pd.notna(valor)
                    else ""
                    for valor in curva_s["REAL"]
                ]

                # PLAN
                fig_s.add_trace(
                    go.Scatter(
                        x=curva_s["fecha"],
                        y=curva_s["PLAN"],
                        mode="lines+markers+text",
                        name="PLAN",
                        text=texto_plan,
                        textposition="top center",
                        textfont=dict(
                            size=11
                        ),
                        line=dict(
                            width=4,
                            shape="spline",
                            smoothing=1.05
                        ),
                        marker=dict(
                            size=8,
                            line=dict(
                                width=1
                            )
                        ),
                        hovertemplate=(
                            "<b>PLAN</b><br>"
                            "%{x|%d/%m/%Y %H:%M}<br>"
                            "Avance: %{y:.1f}%"
                            "<extra></extra>"
                        )
                    )
                )

                # REAL
                fig_s.add_trace(
                    go.Scatter(
                        x=curva_s["fecha"],
                        y=curva_s["REAL"],
                        mode="lines+markers+text",
                        name="REAL",
                        text=texto_real,
                        textposition="bottom center",
                        textfont=dict(
                            size=11
                        ),
                        line=dict(
                            width=4,
                            shape="spline",
                            smoothing=1.05
                        ),
                        marker=dict(
                            size=8,
                            line=dict(
                                width=1
                            )
                        ),
                        connectgaps=False,
                        hovertemplate=(
                            "<b>REAL</b><br>"
                            "%{x|%d/%m/%Y %H:%M}<br>"
                            "Avance: %{y:.1f}%"
                            "<extra></extra>"
                        )
                    )
                )

                fig_s.update_layout(
                    xaxis_title="Fecha / Hora",
                    yaxis_title="Avance acumulado (%)",
                    yaxis=dict(
                        range=[0, 108],
                        ticksuffix="%",
                        dtick=20,
                        showgrid=True,
                        gridwidth=1,
                        zeroline=False
                    ),
                    xaxis=dict(
                        showgrid=True,
                        gridwidth=1,
                        tickformat="%d/%m\n%H:%M"
                    ),
                    hovermode="x unified",
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.04,
                        xanchor="center",
                        x=0.5
                    ),
                    margin=dict(
                        l=50,
                        r=35,
                        t=65,
                        b=55
                    ),
                    height=560
                )

                st.plotly_chart(
                    fig_s,
                    use_container_width=True,
                    config={
                        "displaylogo": False,
                        "responsive": True
                    }
                )

            st.divider()

            # =============================================
            # 9. AVANCE POR OT
            # =============================================

            st.subheader("Avance por OT")

            if "ot" in df_estado.columns:

                df_ot = (
                    df_estado
                    .groupby(
                        ["ot", "equipo"],
                        dropna=False
                    )
                    .apply(
                        lambda grupo: pd.Series({
                            "Avance": weighted_progress(
                                grupo
                            ),
                            "Actividades": len(grupo),
                            "Pendientes": int(
                                (
                                    grupo["avance_real"] < 100
                                ).sum()
                            )
                        })
                    )
                    .reset_index()
                )

                df_ot["OT / Equipo"] = (
                    df_ot["ot"].fillna("").astype(str)
                    + " - "
                    + df_ot["equipo"].fillna(
                        "Sin equipo"
                    ).astype(str)
                )

                df_ot = df_ot.sort_values(
                    "Avance",
                    ascending=True
                )

                fig_ot = px.bar(
                    df_ot,
                    x="Avance",
                    y="OT / Equipo",
                    orientation="h",
                    text="Avance",
                    hover_data=[
                        "Actividades",
                        "Pendientes"
                    ]
                )

                fig_ot.update_traces(
                    texttemplate="%{text:.1f}%",
                    textposition="outside"
                )

                fig_ot.update_layout(
                    xaxis_title="Avance (%)",
                    yaxis_title="",
                    xaxis=dict(
                        range=[0, 105]
                    ),
                    height=max(
                        420,
                        len(df_ot) * 32
                    )
                )

                st.plotly_chart(
                    fig_ot,
                    use_container_width=True
                )

            # =============================================
            # 10. ESTADO DE ACTIVIDADES
            # =============================================

            st.subheader("Estado de actividades")

            estado_resumen = pd.DataFrame({
                "Estado": [
                    "Culminadas",
                    "En ejecución",
                    "No iniciadas"
                ],
                "Cantidad": [
                    int(kpis.get("culminadas", 0)),
                    int(kpis.get("parciales", 0)),
                    int(kpis.get("no_iniciadas", 0))
                ]
            })

            fig_estado = px.bar(
                estado_resumen,
                x="Estado",
                y="Cantidad",
                text="Cantidad"
            )

            fig_estado.update_traces(
                textposition="outside"
            )

            fig_estado.update_layout(
                yaxis_title="N.º de actividades",
                xaxis_title="",
                height=380
            )

            st.plotly_chart(
                fig_estado,
                use_container_width=True
            )

            st.divider()

            # =============================================
            # 11. AVANCE POR ESPECIALIDAD
            # =============================================

            c_esp, c_sup = st.columns(2)

            with c_esp:

                st.subheader(
                    "Avance por especialidad"
                )

                if "especialidad" in df_estado.columns:

                    especialidad = (
                        df_estado
                        .groupby(
                            "especialidad",
                            dropna=False
                        )
                        .apply(
                            lambda grupo: pd.Series({
                                "Avance": weighted_progress(
                                    grupo
                                ),
                                "Actividades": len(grupo),
                                "Pendientes": int(
                                    (
                                        grupo["avance_real"]
                                        < 100
                                    ).sum()
                                )
                            })
                        )
                        .reset_index()
                    )

                    especialidad[
                        "especialidad"
                    ] = (
                        especialidad[
                            "especialidad"
                        ]
                        .fillna("SIN ESPECIALIDAD")
                    )

                    especialidad = (
                        especialidad
                        .sort_values(
                            "Avance",
                            ascending=True
                        )
                    )

                    fig_esp = px.bar(
                        especialidad,
                        x="Avance",
                        y="especialidad",
                        orientation="h",
                        text="Avance"
                    )

                    fig_esp.update_traces(
                        texttemplate="%{text:.1f}%",
                        textposition="outside"
                    )

                    fig_esp.update_layout(
                        xaxis_title="Avance (%)",
                        yaxis_title="",
                        xaxis=dict(
                            range=[0, 105]
                        ),
                        height=420
                    )

                    st.plotly_chart(
                        fig_esp,
                        use_container_width=True
                    )

            # =============================================
            # 12. AVANCE POR SUPERVISOR
            # =============================================

            with c_sup:

                st.subheader(
                    "Avance por supervisor"
                )

                if "supervisor" in df_estado.columns:

                    supervisor = (
                        df_estado
                        .groupby(
                            "supervisor",
                            dropna=False
                        )
                        .apply(
                            lambda grupo: pd.Series({
                                "Avance": weighted_progress(
                                    grupo
                                ),
                                "Actividades": len(grupo),
                                "Pendientes": int(
                                    (
                                        grupo["avance_real"]
                                        < 100
                                    ).sum()
                                )
                            })
                        )
                        .reset_index()
                    )

                    supervisor[
                        "supervisor"
                    ] = (
                        supervisor[
                            "supervisor"
                        ]
                        .fillna("SIN SUPERVISOR")
                    )

                    supervisor = (
                        supervisor
                        .sort_values(
                            "Avance",
                            ascending=True
                        )
                    )

                    fig_sup = px.bar(
                        supervisor,
                        x="Avance",
                        y="supervisor",
                        orientation="h",
                        text="Avance"
                    )

                    fig_sup.update_traces(
                        texttemplate="%{text:.1f}%",
                        textposition="outside"
                    )

                    fig_sup.update_layout(
                        xaxis_title="Avance (%)",
                        yaxis_title="",
                        xaxis=dict(
                            range=[0, 105]
                        ),
                        height=420
                    )

                    st.plotly_chart(
                        fig_sup,
                        use_container_width=True
                    )

            st.divider()

            # =============================================
            # 13. FILTROS DE DETALLE
            # =============================================

            st.subheader(
                "Detalle de planificación y avance"
            )

            f1, f2, f3 = st.columns(3)

            lista_ots = ["TODAS"]

            if "ot" in df_estado.columns:
                lista_ots += sorted(
                    df_estado["ot"]
                    .dropna()
                    .astype(str)
                    .unique()
                    .tolist()
                )

            with f1:

                filtro_ot = st.selectbox(
                    "Filtrar por OT",
                    lista_ots,
                    key="dash_filtro_ot"
                )

            lista_especialidades = ["TODAS"]

            if "especialidad" in df_estado.columns:
                lista_especialidades += sorted(
                    df_estado["especialidad"]
                    .dropna()
                    .astype(str)
                    .unique()
                    .tolist()
                )

            with f2:

                filtro_especialidad = st.selectbox(
                    "Filtrar por especialidad",
                    lista_especialidades,
                    key="dash_filtro_especialidad"
                )

            with f3:

                filtro_estado = st.selectbox(
                    "Estado",
                    [
                        "TODOS",
                        "CULMINADAS",
                        "EN EJECUCIÓN",
                        "NO INICIADAS",
                        "PENDIENTES"
                    ],
                    key="dash_filtro_estado"
                )

            detalle = df_estado.copy()

            if filtro_ot != "TODAS":

                detalle = detalle[
                    detalle["ot"].astype(str)
                    == filtro_ot
                ]

            if filtro_especialidad != "TODAS":

                detalle = detalle[
                    detalle[
                        "especialidad"
                    ].astype(str)
                    == filtro_especialidad
                ]

            if filtro_estado == "CULMINADAS":

                detalle = detalle[
                    detalle["avance_real"] >= 100
                ]

            elif filtro_estado == "EN EJECUCIÓN":

                detalle = detalle[
                    (
                        detalle["avance_real"] > 0
                    )
                    & (
                        detalle["avance_real"] < 100
                    )
                ]

            elif filtro_estado == "NO INICIADAS":

                detalle = detalle[
                    detalle["avance_real"] <= 0
                ]

            elif filtro_estado == "PENDIENTES":

                detalle = detalle[
                    detalle["avance_real"] < 100
                ]

            # =============================================
            # 14. ESTADO TEXTUAL
            # =============================================

            detalle["estado"] = np.where(
                detalle["avance_real"] >= 100,
                "CULMINADA",
                np.where(
                    detalle["avance_real"] > 0,
                    "EN EJECUCIÓN",
                    "NO INICIADA"
                )
            )

            columnas_tabla = [
                "ot",
                "equipo",
                "codigo_actividad",
                "descripcion",
                "especialidad",
                "supervisor",
                "grupo",
                "inicio_plan",
                "fin_plan",
                "hh_plan",
                "avance_real",
                "estado"
            ]

            columnas_tabla = [
                columna
                for columna in columnas_tabla
                if columna in detalle.columns
            ]

            tabla = detalle[
                columnas_tabla
            ].copy()

            tabla = tabla.rename(
                columns={
                    "ot": "OT",
                    "equipo": "EQUIPO",
                    "codigo_actividad": "ACTIVIDAD",
                    "descripcion": "DESCRIPCIÓN",
                    "especialidad": "ESPECIALIDAD",
                    "supervisor": "SUPERVISOR",
                    "grupo": "GRUPO",
                    "inicio_plan": "INICIO PLAN",
                    "fin_plan": "FIN PLAN",
                    "hh_plan": "HH PLAN",
                    "avance_real": "AVANCE REAL (%)",
                    "estado": "ESTADO"
                }
            )

            st.dataframe(
                tabla,
                use_container_width=True,
                hide_index=True,
                height=500
            )

            # =============================================
            # 15. RESUMEN FINAL
            # =============================================

            st.caption(
                f"Mostrando {len(tabla)} actividades · "
                f"{int(kpis.get('culminadas', 0))} culminadas · "
                f"{int(kpis.get('parciales', 0))} en ejecución · "
                f"{int(kpis.get('no_iniciadas', 0))} no iniciadas."
            )    
    
    # =====================================================
    # REGISTRAR AVANCE
    # =====================================================

    elif pagina == "Registrar avance":

        st.subheader(f"Registrar avance - {nombre_area}")

        if not ots_area:
            st.warning(
                "Todavía no existen OTs cargadas para esta área."
            )

        else:

            # ============================================
            # FILTRO SUPERVISOR + SELECCIÓN DE OT
            # MISMA LÓGICA DEL APP ANTAPACCAY
            # ============================================

            ids_ots_area_registro = [
                ot["id"]
                for ot in ots_area
            ]

            actividades_area_registro = []

            if ids_ots_area_registro:
                actividades_area_registro = (
                    supabase
                    .table("actividades")
                    .select(
                        "id,ot_id,supervisor,activo"
                    )
                    .in_(
                        "ot_id",
                        ids_ots_area_registro
                    )
                    .eq("activo", True)
                    .execute()
                ).data or []

            supervisores_area = sorted(
                {
                    str(
                        actividad_sup.get(
                            "supervisor",
                            ""
                        )
                    ).strip()
                    for actividad_sup
                    in actividades_area_registro
                    if str(
                        actividad_sup.get(
                            "supervisor",
                            ""
                        )
                    ).strip()
                }
            )

            col_supervisor, col_ot = st.columns(2)

            with col_supervisor:

                supervisor_seleccionado = st.selectbox(
                    "Seleccione supervisor",
                    ["TODOS"] + supervisores_area,
                    key=(
                        f"supervisor_registro_"
                        f"{usuario.get('area_id')}"
                    )
                )

            # OTs permitidas según supervisor
            if supervisor_seleccionado == "TODOS":

                ots_filtradas_registro = ots_area

            else:

                ids_ot_supervisor = {
                    actividad_sup["ot_id"]
                    for actividad_sup
                    in actividades_area_registro
                    if str(
                        actividad_sup.get(
                            "supervisor",
                            ""
                        )
                    ).strip()
                    == supervisor_seleccionado
                }

                ots_filtradas_registro = [
                    ot
                    for ot in ots_area
                    if ot["id"] in ids_ot_supervisor
                ]

            mapa_ots = {
                (
                    f"{ot['ot']} - "
                    f"{ot.get('equipo') or 'Sin equipo'}"
                ): ot
                for ot in ots_filtradas_registro
            }

            with col_ot:

                ot_texto = st.selectbox(
                    "Escriba o seleccione la OT *",
                    list(mapa_ots.keys()),
                    index=None,
                    placeholder="Buscar OT...",
                    key=(
                        f"ot_registro_"
                        f"{usuario.get('area_id')}_"
                        f"{supervisor_seleccionado}"
                    )
                )

            if supervisor_seleccionado == "TODOS":
                st.caption(
                    f"Mostrando todas las OTs disponibles: "
                    f"{len(ots_filtradas_registro)} OT(s)."
                )
            else:
                st.caption(
                    f"Mostrando OTs de "
                    f"{supervisor_seleccionado}: "
                    f"{len(ots_filtradas_registro)} OT(s)."
                )

            if not mapa_ots:

                st.warning(
                    "No existen OTs activas para "
                    "el supervisor seleccionado."
                )
                st.stop()

            if not ot_texto:

                st.info(
                    "Seleccione una OT para continuar."
                )
                st.stop()

            ot_seleccionada = mapa_ots[ot_texto]

            st.info(
                f"Equipo: "
                f"{ot_seleccionada.get('equipo') or 'Sin equipo'}"
            )

            # ============================================
            # OBTENER ACTIVIDADES DE LA OT
            # ============================================

            actividades_resultado = (
                supabase
                .table("actividades")
                .select(
                    "id,codigo_actividad,descripcion,supervisor,"
                    "especialidad,grupo,peso,inicio_plan,fin_plan,"
                    "seccion,personal,duracion_h,hh_plan,critica,activo"
                )
                .eq(
                    "ot_id",
                    ot_seleccionada["id"]
                )
                .eq("activo", True)
                .order("codigo_actividad")
                .execute()
            )

            actividades_ot = (
                actividades_resultado.data
                or []
            )

            # Si se seleccionó un supervisor específico,
            # mostrar únicamente sus actividades dentro de la OT.
            if supervisor_seleccionado != "TODOS":

                actividades_ot = [
                    actividad_ot
                    for actividad_ot in actividades_ot
                    if str(
                        actividad_ot.get(
                            "supervisor",
                            ""
                        )
                    ).strip()
                    == supervisor_seleccionado
                ]

            if not actividades_ot:

                st.warning(
                    "Esta OT no tiene actividades registradas."
                )

            else:

                mapa_actividades = {
                    f"{act['codigo_actividad']} - {act['descripcion']}": act
                    for act in actividades_ot
                }

                actividad_texto = st.selectbox(
                    "Seleccione una actividad",
                    list(mapa_actividades.keys()),
                    key=f"selector_actividad_ot_{ot_seleccionada['id']}"
                )

                actividad = mapa_actividades[actividad_texto]

                st.divider()

                # ============================================
                # DATOS PLANIFICADOS
                # ============================================

                c1, c2, c3, c4 = st.columns(4)

                with c1:
                    st.text_input(
                        "Supervisor",
                        value=str(actividad.get("supervisor") or ""),
                        disabled=True
                    )

                with c2:
                    st.text_input(
                        "Especialidad",
                        value=str(actividad.get("especialidad") or ""),
                        disabled=True
                    )

                with c3:
                    st.text_input(
                        "Grupo",
                        value=str(actividad.get("grupo") or ""),
                        disabled=True
                    )

                with c4:
                    st.text_input(
                        "Sección",
                        value=str(actividad.get("seccion") or ""),
                        disabled=True
                    )

                c5, c6, c7, c8 = st.columns(4)

                with c5:
                    st.text_input(
                        "Inicio planificado",
                        value=str(actividad.get("inicio_plan") or ""),
                        disabled=True
                    )

                with c6:
                    st.text_input(
                        "Fin planificado",
                        value=str(actividad.get("fin_plan") or ""),
                        disabled=True
                    )

                with c7:
                    st.text_input(
                        "Personal",
                        value=str(actividad.get("personal") or ""),
                        disabled=True
                    )

                with c8:
                    st.text_input(
                        "HH planificadas",
                        value=str(actividad.get("hh_plan") or ""),
                        disabled=True
                    )

                st.text_area(
                    "Descripción de actividad",
                    value=str(actividad.get("descripcion") or ""),
                    disabled=True
                )

                st.divider()

                # ============================================
                # FORMULARIO DE AVANCE
                # ============================================

                # Obtener el último avance GUARDADO de la actividad
                # seleccionada. Así, al cambiar de actividad, el campo
                # no hereda el porcentaje de la actividad anterior.
                ultimo_avance_resultado = (
                    supabase
                    .table("avances_actividad")
                    .select("avance,fecha_registro")
                    .eq(
                        "actividad_id",
                        actividad["id"]
                    )
                    .order(
                        "fecha_registro",
                        desc=True
                    )
                    .limit(1)
                    .execute()
                )

                ultimo_avance_data = (
                    ultimo_avance_resultado.data
                    or []
                )

                ultimo_avance_guardado = (
                    int(
                        float(
                            ultimo_avance_data[0].get(
                                "avance",
                                0
                            )
                            or 0
                        )
                    )
                    if ultimo_avance_data
                    else 0
                )

                st.caption(
                    f"Último avance registrado de esta actividad: "
                    f"{ultimo_avance_guardado}%"
                )

                avance = st.number_input(
                    "Porcentaje de avance de la actividad (%)",
                    min_value=0,
                    max_value=100,
                    value=ultimo_avance_guardado,
                    step=5,
                    key=f"avance_actividad_{actividad['id']}"
                )

                tipo_evidencia = st.selectbox(
                    "Tipo de evidencia",
                    [
                        "INICIO",
                        "DURANTE",
                        "FINAL"
                    ],
                    key=f"tipo_evidencia_{actividad['id']}"
                )

                critica = st.checkbox(
                    "Marcar actividad como crítica",
                    key=f"critica_actividad_{actividad['id']}"
                )

                descripcion_avance = st.text_area(
                    "Descripción breve del avance realizado *",
                    key=f"descripcion_avance_{actividad['id']}"
                )

                observaciones = st.text_area(
                    "Observaciones",
                    key=f"observaciones_avance_{actividad['id']}"
                )

                archivos_evidencia = st.file_uploader(
                    "Evidencias fotográficas",
                    type=["jpg", "jpeg", "png", "webp"],
                    accept_multiple_files=True,
                    key=f"evidencias_actividad_{actividad['id']}",
                    help=(
                        "Puede tomar fotografías desde el celular "
                        "o seleccionarlas desde la PC. "
                        "Las imágenes se comprimirán automáticamente."
                    )
                )

                if archivos_evidencia:

                    st.caption(
                        f"{len(archivos_evidencia)} "
                        "fotografía(s) seleccionada(s)."
                    )

                guardar = st.button(
                    "Guardar avance",
                    type="primary",
                    use_container_width=True
                )

                if guardar:

                    if not descripcion_avance.strip():

                        st.error(
                            "Debe ingresar una descripción del avance."
                        )

                    else:

                        try:

                            evidencias_urls = []

                            if archivos_evidencia:

                                with st.spinner(
                                    "Comprimiendo y cargando evidencias..."
                                ):

                                    evidencias_urls = subir_evidencias(
                                        archivos_evidencia,
                                        ot_seleccionada["ot"],
                                        actividad["codigo_actividad"],
                                        tipo_evidencia
                                    )

                            payload = {
                                "actividad_id": actividad["id"],
                                "avance": avance,
                                "descripcion_avance": descripcion_avance.strip(),
                                "observaciones": observaciones.strip(),
                                "tipo_evidencia": tipo_evidencia,
                                "critica": critica,
                                "evidencias": evidencias_urls,
                                "usuario": usuario["username"]
                            }

                            (
                                supabase
                                .table("avances_actividad")
                                .insert(payload)
                                .execute()
                            )

                            if evidencias_urls:

                                total_original = sum(
                                    evidencia.get(
                                        "tamano_original",
                                        0
                                    )
                                    for evidencia in evidencias_urls
                                )

                                total_comprimido = sum(
                                    evidencia.get(
                                        "tamano_comprimido",
                                        0
                                    )
                                    for evidencia in evidencias_urls
                                )

                                ahorro_total = (
                                    (
                                        1
                                        - total_comprimido
                                        / total_original
                                    )
                                    * 100
                                    if total_original > 0
                                    else 0
                                )

                                st.success(
                                    f"Avance registrado correctamente con "
                                    f"{len(evidencias_urls)} evidencia(s). "
                                    f"Compresión aproximada: "
                                    f"{ahorro_total:.0f}%."
                                )

                            else:

                                st.success(
                                    "Avance registrado correctamente."
                                )

                        except Exception as exc:

                            st.error(
                                f"No fue posible guardar el avance: {exc}"
                            )
    
    # =====================================================
    # DETALLE POR OT
    # =====================================================

    elif pagina == "Detalle por OT":

        st.subheader(f"Detalle por OT - {nombre_area}")

        if not ots_area:

            st.warning(
                "Todavía no existen OTs cargadas para esta área."
            )

        else:

            # ================================================
            # SELECCIÓN DE OT
            # ================================================

            mapa_detalle_ots = {
                f"{ot['ot']} - {ot.get('equipo') or 'Sin equipo'}": ot
                for ot in ots_area
            }

            ot_detalle_texto = st.selectbox(
                "Seleccione una OT",
                list(mapa_detalle_ots.keys()),
                key="detalle_ot_selector"
            )

            ot_detalle = mapa_detalle_ots[
                ot_detalle_texto
            ]

            # ================================================
            # INFORMACIÓN GENERAL DE LA OT
            # ================================================

            c1, c2 = st.columns(2)

            with c1:
                st.info(
                    f"**OT:** {ot_detalle['ot']}"
                )

            with c2:
                st.info(
                    f"**Equipo:** "
                    f"{ot_detalle.get('equipo') or 'Sin equipo'}"
                )

            if ot_detalle.get("descripcion"):

                st.caption(
                    f"Descripción: "
                    f"{ot_detalle['descripcion']}"
                )

            # ================================================
            # OBTENER ACTIVIDADES DE LA OT
            # ================================================

            resultado_actividades_detalle = (
                supabase
                .table("actividades")
                .select(
                    "id,ot_id,codigo_actividad,descripcion,"
                    "supervisor,especialidad,grupo,peso,"
                    "inicio_plan,fin_plan,seccion,personal,"
                    "duracion_h,hh_plan,critica,activo"
                )
                .eq(
                    "ot_id",
                    ot_detalle["id"]
                )
                .eq(
                    "activo",
                    True
                )
                .order(
                    "codigo_actividad"
                )
                .execute()
            )

            actividades_detalle = (
                resultado_actividades_detalle.data
                or []
            )

            if not actividades_detalle:

                st.warning(
                    "Esta OT no tiene actividades registradas."
                )

            else:

                df_actividades_detalle = pd.DataFrame(
                    actividades_detalle
                )

                # ============================================
                # OBTENER AVANCES DE LAS ACTIVIDADES
                # ============================================

                ids_actividades_detalle = (
                    df_actividades_detalle["id"]
                    .dropna()
                    .tolist()
                )

                resultado_avances_detalle = (
                    supabase
                    .table("avances_actividad")
                    .select(
                        "id,actividad_id,avance,"
                        "descripcion_avance,observaciones,"
                        "tipo_evidencia,critica,evidencias,"
                        "usuario,fecha_registro"
                    )
                    .in_(
                        "actividad_id",
                        ids_actividades_detalle
                    )
                    .execute()
                )

                avances_detalle = (
                    resultado_avances_detalle.data
                    or []
                )

                df_avances_detalle = pd.DataFrame(
                    avances_detalle
                )

                # ============================================
                # ESTADO ACTUAL DE LAS ACTIVIDADES
                # ============================================

                estado_ot = build_activity_status(
                    df_actividades_detalle,
                    df_avances_detalle
                )

                kpis_ot = compute_kpis(
                    df_actividades_detalle,
                    df_avances_detalle
                )

                # ============================================
                # INDICADORES DE LA OT
                # ============================================

                o1, o2, o3, o4, o5, o6 = st.columns(6)

                with o1:

                    st.metric(
                        "Actividades",
                        kpis_ot["actividades"]
                    )

                with o2:

                    st.metric(
                        "Avance OT",
                        f"{kpis_ot['avance_general']:.1f}%"
                    )

                with o3:

                    st.metric(
                        "Culminadas",
                        kpis_ot["culminadas"]
                    )

                with o4:

                    st.metric(
                        "En ejecución",
                        kpis_ot["parciales"]
                    )

                with o5:

                    st.metric(
                        "No iniciadas",
                        kpis_ot["no_iniciadas"]
                    )

                with o6:

                    st.metric(
                        "Pendientes",
                        kpis_ot["pendientes"]
                    )

                hh1, hh2 = st.columns(2)

                with hh1:

                    st.metric(
                        "HH planificadas",
                        f"{kpis_ot['hh_plan']:.0f}"
                    )

                with hh2:

                    st.metric(
                        "HH ganadas",
                        f"{kpis_ot['hh_ganadas']:.0f}"
                    )

                st.divider()

                # ============================================
                # BARRA DE AVANCE
                # ============================================

                avance_ot = float(
                    kpis_ot["avance_general"]
                )

                st.write(
                    f"**Avance general de la OT: "
                    f"{avance_ot:.1f}%**"
                )

                st.progress(
                    min(
                        max(
                            avance_ot / 100,
                            0
                        ),
                        1
                    )
                )

                st.divider()

                # ============================================
                # ESTADO TEXTUAL
                # ============================================

                estado_ot["estado"] = np.where(
                    estado_ot["avance_real"] >= 100,
                    "CULMINADA",
                    np.where(
                        estado_ot["avance_real"] > 0,
                        "EN EJECUCIÓN",
                        "NO INICIADA"
                    )
                )

                # ============================================
                # ÚLTIMO REPORTE
                # ============================================

                if not df_avances_detalle.empty:

                    ultimos_reportes = latest_progress(
                        df_avances_detalle
                    )

                    columnas_reporte = [
                        columna
                        for columna in [
                            "actividad_id",
                            "descripcion_avance",
                            "observaciones",
                            "tipo_evidencia",
                            "usuario",
                            "fecha_registro"
                        ]
                        if columna in ultimos_reportes.columns
                    ]

                    columnas_reporte = [
                        columna
                        for columna in columnas_reporte
                        if columna not in estado_ot.columns
                        or columna == "actividad_id"
                    ]

                    if columnas_reporte:

                        estado_ot = estado_ot.merge(
                            ultimos_reportes[
                                columnas_reporte
                            ],
                            left_on="id",
                            right_on="actividad_id",
                            how="left",
                            suffixes=(
                                "",
                                "_ultimo"
                            )
                        )

                # ============================================
                # TABLA DE ACTIVIDADES
                # ============================================

                columnas_detalle_ot = [
                    "codigo_actividad",
                    "descripcion",
                    "supervisor",
                    "especialidad",
                    "grupo",
                    "inicio_plan",
                    "fin_plan",
                    "personal",
                    "hh_plan",
                    "avance_real",
                    "estado"
                ]

                columnas_detalle_ot = [
                    columna
                    for columna in columnas_detalle_ot
                    if columna in estado_ot.columns
                ]

                tabla_ot = estado_ot[
                    columnas_detalle_ot
                ].copy()

                tabla_ot = tabla_ot.rename(
                    columns={
                        "codigo_actividad":
                            "ACTIVIDAD",
                        "descripcion":
                            "DESCRIPCIÓN",
                        "supervisor":
                            "SUPERVISOR",
                        "especialidad":
                            "ESPECIALIDAD",
                        "grupo":
                            "GRUPO",
                        "inicio_plan":
                            "INICIO PLAN",
                        "fin_plan":
                            "FIN PLAN",
                        "personal":
                            "PERSONAL",
                        "hh_plan":
                            "HH PLAN",
                        "avance_real":
                            "AVANCE (%)",
                        "estado":
                            "ESTADO"
                    }
                )

                st.subheader(
                    "Actividades de la OT"
                )

                st.dataframe(
                    tabla_ot,
                    use_container_width=True,
                    hide_index=True,
                    height=450
                )

                # ============================================
                # ACTIVIDADES EN EJECUCIÓN
                # ============================================

                actividades_ejecucion = estado_ot[
                    (
                        estado_ot["avance_real"] > 0
                    )
                    &
                    (
                        estado_ot["avance_real"] < 100
                    )
                ]

                if not actividades_ejecucion.empty:

                    st.subheader(
                        "Actividades actualmente en ejecución"
                    )

                    for _, actividad_actual in (
                        actividades_ejecucion.iterrows()
                    ):

                        with st.expander(
                            f"{actividad_actual.get('codigo_actividad', '')} "
                            f"- {actividad_actual.get('descripcion', '')}"
                        ):

                            x1, x2, x3 = st.columns(3)

                            with x1:

                                st.metric(
                                    "Avance",
                                    f"{float(actividad_actual.get('avance_real', 0)):.1f}%"
                                )

                            with x2:

                                st.write(
                                    "**Supervisor:**"
                                )

                                st.write(
                                    actividad_actual.get(
                                        "supervisor"
                                    )
                                    or "-"
                                )

                            with x3:

                                st.write(
                                    "**Grupo:**"
                                )

                                st.write(
                                    actividad_actual.get(
                                        "grupo"
                                    )
                                    or "-"
                                )

                            descripcion_ultimo = (
                                actividad_actual.get(
                                    "descripcion_avance"
                                )
                                or actividad_actual.get(
                                    "descripcion_avance_ultimo"
                                )
                            )

                            if descripcion_ultimo:

                                st.write(
                                    "**Último avance reportado:**"
                                )

                                st.write(
                                    descripcion_ultimo
                                )

                            observacion_ultima = (
                                actividad_actual.get(
                                    "observaciones"
                                )
                                or actividad_actual.get(
                                    "observaciones_ultimo"
                                )
                            )

                            if observacion_ultima:

                                st.write(
                                    "**Observaciones:**"
                                )

                                st.write(
                                    observacion_ultima
                                )

    # =====================================================
    # EVIDENCIAS
    # =====================================================

    elif pagina == "Evidencias":

        st.subheader(f"Evidencias - {nombre_area}")

        if not ots_area:

            st.warning(
                "Todavía no existen OTs cargadas para esta área."
            )

        else:

            ids_ots_evidencias = [
                ot["id"]
                for ot in ots_area
            ]

            actividades_evidencias = (
                supabase
                .table("actividades")
                .select(
                    "id,ot_id,codigo_actividad,descripcion"
                )
                .in_("ot_id", ids_ots_evidencias)
                .eq("activo", True)
                .execute()
            ).data or []

            if not actividades_evidencias:

                st.info(
                    "No existen actividades disponibles."
                )

            else:

                ids_actividades_evidencias = [
                    actividad["id"]
                    for actividad in actividades_evidencias
                ]

                registros_evidencias = (
                    supabase
                    .table("avances_actividad")
                    .select(
                        "id,actividad_id,avance,"
                        "descripcion_avance,observaciones,"
                        "tipo_evidencia,evidencias,"
                        "usuario,fecha_registro"
                    )
                    .in_(
                        "actividad_id",
                        ids_actividades_evidencias
                    )
                    .order(
                        "fecha_registro",
                        desc=True
                    )
                    .execute()
                ).data or []

                registros_con_fotos = [
                    registro
                    for registro in registros_evidencias
                    if registro.get("evidencias")
                ]

                if not registros_con_fotos:

                    st.info(
                        "Todavía no existen evidencias fotográficas "
                        "registradas para esta área."
                    )

                else:

                    mapa_ots_evidencias = {
                        ot["id"]: ot
                        for ot in ots_area
                    }

                    mapa_actividades_evidencias = {
                        actividad["id"]: actividad
                        for actividad in actividades_evidencias
                    }

                    opciones_ot = ["TODAS"] + sorted(
                        {
                            str(ot.get("ot", ""))
                            for ot in ots_area
                        }
                    )

                    f1, f2 = st.columns(2)

                    with f1:

                        filtro_ot_evidencias = st.selectbox(
                            "Filtrar por OT",
                            opciones_ot,
                            key="filtro_evidencias_ot"
                        )

                    with f2:

                        filtro_tipo_evidencias = st.selectbox(
                            "Tipo de evidencia",
                            [
                                "TODAS",
                                "INICIO",
                                "DURANTE",
                                "FINAL"
                            ],
                            key="filtro_evidencias_tipo"
                        )

                    registros_filtrados = []

                    for registro in registros_con_fotos:

                        actividad = (
                            mapa_actividades_evidencias.get(
                                registro["actividad_id"],
                                {}
                            )
                        )

                        ot = mapa_ots_evidencias.get(
                            actividad.get("ot_id"),
                            {}
                        )

                        if (
                            filtro_ot_evidencias != "TODAS"
                            and str(ot.get("ot", ""))
                            != filtro_ot_evidencias
                        ):
                            continue

                        if (
                            filtro_tipo_evidencias != "TODAS"
                            and str(
                                registro.get(
                                    "tipo_evidencia",
                                    ""
                                )
                            ).upper()
                            != filtro_tipo_evidencias
                        ):
                            continue

                        registros_filtrados.append(
                            (
                                registro,
                                actividad,
                                ot
                            )
                        )

                    st.caption(
                        f"{len(registros_filtrados)} "
                        "registro(s) con evidencia."
                    )

                    for (
                        registro,
                        actividad,
                        ot
                    ) in registros_filtrados:

                        titulo = (
                            f"OT {ot.get('ot', '')} · "
                            f"{actividad.get('codigo_actividad', '')} · "
                            f"{registro.get('avance', 0)}%"
                        )

                        with st.expander(
                            titulo,
                            expanded=False
                        ):

                            d1, d2, d3 = st.columns(3)

                            with d1:
                                st.write(
                                    "**Tipo:** "
                                    f"{registro.get('tipo_evidencia', '')}"
                                )

                            with d2:
                                st.write(
                                    "**Usuario:** "
                                    f"{registro.get('usuario', '')}"
                                )

                            with d3:
                                fecha_evidencia = pd.to_datetime(
                                    registro.get("fecha_registro"),
                                    errors="coerce",
                                    utc=True
                                )

                                if not pd.isna(fecha_evidencia):

                                    fecha_evidencia = (
                                        fecha_evidencia
                                        .tz_convert("America/Lima")
                                    )

                                    fecha_texto = (
                                        fecha_evidencia.strftime(
                                            "%d/%m/%Y %H:%M"
                                        )
                                    )

                                else:
                                    fecha_texto = ""

                                st.write(
                                    "**Fecha:** "
                                    f"{fecha_texto}"
                                )

                            st.write(
                                "**Actividad:** "
                                f"{actividad.get('descripcion', '')}"
                            )

                            st.write(
                                "**Avance reportado:** "
                                f"{registro.get('descripcion_avance', '')}"
                            )

                            observacion = (
                                registro.get("observaciones")
                                or ""
                            )

                            if observacion:
                                st.write(
                                    "**Observaciones:** "
                                    f"{observacion}"
                                )

                            evidencias_lista = (
                                registro.get("evidencias")
                                or []
                            )

                            columnas_fotos = st.columns(
                                min(
                                    len(evidencias_lista),
                                    3
                                )
                            )

                            for indice, evidencia in enumerate(
                                evidencias_lista
                            ):

                                if isinstance(
                                    evidencia,
                                    str
                                ):
                                    url_evidencia = evidencia
                                    nombre_evidencia = (
                                        f"Evidencia {indice + 1}"
                                    )

                                else:
                                    url_evidencia = evidencia.get(
                                        "url",
                                        ""
                                    )
                                    nombre_evidencia = (
                                        evidencia.get(
                                            "nombre_original"
                                        )
                                        or f"Evidencia {indice + 1}"
                                    )

                                if not url_evidencia:
                                    continue

                                with columnas_fotos[
                                    indice % len(columnas_fotos)
                                ]:

                                    st.image(
                                        url_evidencia,
                                        caption=nombre_evidencia,
                                        use_container_width=True
                                    )


    # =====================================================
    # INFORME DIARIO
    # =====================================================

    elif pagina == "Informe diario":

        st.subheader(
            f"Informe diario - {nombre_area}"
        )

        st.caption(
            "Resumen automático de avances, restricciones, "
            "actividades críticas y pendientes del área."
        )

        if not ots_area:

            st.warning(
                "Todavía no existen OTs cargadas para esta área."
            )

        else:

            # =============================================
            # CARGAR ACTIVIDADES DEL ÁREA
            # =============================================

            ids_ots_informe = [
                ot["id"]
                for ot in ots_area
            ]

            actividades_informe = (
                supabase
                .table("actividades")
                .select(
                    "id,ot_id,codigo_actividad,descripcion,"
                    "supervisor,especialidad,grupo,peso,"
                    "inicio_plan,fin_plan,seccion,personal,"
                    "duracion_h,hh_plan,critica,activo"
                )
                .in_(
                    "ot_id",
                    ids_ots_informe
                )
                .eq(
                    "activo",
                    True
                )
                .execute()
            ).data or []

            if not actividades_informe:

                st.warning(
                    "No existen actividades cargadas para esta área."
                )

            else:

                df_ots_informe = pd.DataFrame(
                    ots_area
                )

                df_actividades_informe = pd.DataFrame(
                    actividades_informe
                )

                ids_actividades_informe = (
                    df_actividades_informe["id"]
                    .dropna()
                    .tolist()
                )

                avances_informe = (
                    supabase
                    .table("avances_actividad")
                    .select(
                        "id,actividad_id,avance,"
                        "descripcion_avance,observaciones,"
                        "tipo_evidencia,critica,evidencias,"
                        "usuario,fecha_registro"
                    )
                    .in_(
                        "actividad_id",
                        ids_actividades_informe
                    )
                    .order(
                        "fecha_registro",
                        desc=True
                    )
                    .execute()
                ).data or []

                df_avances_informe = pd.DataFrame(
                    avances_informe
                )

                fecha_hoy_lima = pd.Timestamp.now(
                    tz="America/Lima"
                ).date()

                fecha_informe = st.date_input(
                    "Fecha del informe",
                    value=fecha_hoy_lima,
                    key="fecha_informe_diario"
                )

                # =============================================
                # KPIs DEL ÁREA
                # =============================================

                kpis_informe = compute_kpis(
                    df_actividades_informe,
                    df_avances_informe
                )

                i1, i2, i3, i4, i5, i6 = st.columns(
                    6
                )

                with i1:
                    st.metric(
                        "OTs",
                        len(df_ots_informe)
                    )

                with i2:
                    st.metric(
                        "Actividades",
                        kpis_informe[
                            "actividades"
                        ]
                    )

                with i3:
                    st.metric(
                        "Avance general",
                        f"{kpis_informe['avance_general']:.1f}%"
                    )

                with i4:
                    st.metric(
                        "Culminadas",
                        kpis_informe[
                            "culminadas"
                        ]
                    )

                with i5:
                    st.metric(
                        "En ejecución",
                        kpis_informe[
                            "parciales"
                        ]
                    )

                with i6:
                    st.metric(
                        "No iniciadas",
                        kpis_informe[
                            "no_iniciadas"
                        ]
                    )

                st.divider()

                # =============================================
                # INFORME DIARIO POR SECCIONES EDITABLES
                # =============================================

                secciones = construir_secciones_informe_diario(
                    df_ots_informe,
                    df_actividades_informe,
                    df_avances_informe,
                    nombre_area,
                    fecha_informe
                )

                st.subheader("Resumen ejecutivo")

                resumen_editado = st.text_area(
                    "Editar resumen ejecutivo",
                    value=secciones["resumen"],
                    height=250,
                    key=(
                        "resumen_ejecutivo_"
                        f"{codigo_area}_"
                        f"{fecha_informe}"
                    ),
                    label_visibility="collapsed"
                )

                st.subheader("Principales actualizaciones")

                actualizaciones_editadas = st.text_area(
                    "Editar principales actualizaciones",
                    value=secciones["actualizaciones"],
                    height=230,
                    key=(
                        "actualizaciones_diarias_"
                        f"{codigo_area}_"
                        f"{fecha_informe}"
                    ),
                    label_visibility="collapsed"
                )

                col_obs, col_crit = st.columns(2)

                with col_obs:

                    st.subheader(
                        "Observaciones / Restricciones"
                    )

                    observaciones_editadas = st.text_area(
                        "Editar observaciones y restricciones",
                        value=secciones["observaciones"],
                        height=220,
                        key=(
                            "observaciones_diarias_"
                            f"{codigo_area}_"
                            f"{fecha_informe}"
                        ),
                        label_visibility="collapsed"
                    )

                with col_crit:

                    st.subheader(
                        "Actividades críticas"
                    )

                    criticas_editadas = st.text_area(
                        "Editar actividades críticas",
                        value=secciones["criticas"],
                        height=220,
                        key=(
                            "criticas_diarias_"
                            f"{codigo_area}_"
                            f"{fecha_informe}"
                        ),
                        label_visibility="collapsed"
                    )

                st.subheader("Pendientes principales")

                pendientes_editados = st.text_area(
                    "Editar pendientes principales",
                    value=secciones["pendientes"],
                    height=260,
                    key=(
                        "pendientes_diarios_"
                        f"{codigo_area}_"
                        f"{fecha_informe}"
                    ),
                    label_visibility="collapsed"
                )

                informe_final = (
                    f"INFORME DIARIO DE CONTROL DE OTs - "
                    f"{nombre_area.upper()}\n"
                    f"Fecha: {fecha_informe.strftime('%d/%m/%Y')}\n\n"
                    "RESUMEN EJECUTIVO\n"
                    f"{resumen_editado}\n\n"
                    "PRINCIPALES ACTUALIZACIONES\n"
                    f"{actualizaciones_editadas}\n\n"
                    "OBSERVACIONES / RESTRICCIONES\n"
                    f"{observaciones_editadas}\n\n"
                    "ACTIVIDADES CRÍTICAS\n"
                    f"{criticas_editadas}\n\n"
                    "PENDIENTES PRINCIPALES\n"
                    f"{pendientes_editados}"
                )

                descarga1, descarga2 = st.columns(
                    2
                )

                with descarga1:

                    st.download_button(
                        "Descargar informe diario en TXT",
                        data=informe_final.encode(
                            "utf-8"
                        ),
                        file_name=(
                            f"informe_diario_"
                            f"{codigo_area.lower()}_"
                            f"{fecha_informe:%Y%m%d}.txt"
                        ),
                        mime="text/plain",
                        use_container_width=True
                    )

                # =============================================
                # REGISTROS DEL DÍA
                # =============================================

                if df_avances_informe.empty:

                    diarios_informe = pd.DataFrame()

                else:

                    fechas_registro_lima = pd.to_datetime(
                        df_avances_informe[
                            "fecha_registro"
                        ],
                        errors="coerce",
                        utc=True
                    ).dt.tz_convert(
                        "America/Lima"
                    )

                    diarios_informe = (
                        df_avances_informe[
                            fechas_registro_lima.dt.date
                            == fecha_informe
                        ]
                        .copy()
                    )

                    if not diarios_informe.empty:
                        diarios_informe[
                            "fecha_lima"
                        ] = (
                            fechas_registro_lima.loc[
                                diarios_informe.index
                            ]
                        )

                with descarga2:

                    if diarios_informe.empty:

                        st.button(
                            "Sin registros para exportar",
                            disabled=True,
                            use_container_width=True
                        )

                    else:

                        export_diario = (
                            diarios_informe
                            .merge(
                                df_actividades_informe[
                                    [
                                        "id",
                                        "ot_id",
                                        "codigo_actividad",
                                        "descripcion",
                                        "supervisor",
                                        "especialidad",
                                        "grupo"
                                    ]
                                ],
                                left_on="actividad_id",
                                right_on="id",
                                how="left",
                                suffixes=(
                                    "",
                                    "_actividad"
                                )
                            )
                            .merge(
                                df_ots_informe[
                                    [
                                        "id",
                                        "ot",
                                        "equipo"
                                    ]
                                ],
                                left_on="ot_id",
                                right_on="id",
                                how="left",
                                suffixes=(
                                    "",
                                    "_ot"
                                )
                            )
                        )

                        if (
                            "fecha_lima"
                            in export_diario.columns
                        ):

                            export_diario[
                                "fecha_lima"
                            ] = pd.to_datetime(
                                export_diario[
                                    "fecha_lima"
                                ],
                                errors="coerce"
                            ).dt.tz_localize(
                                None
                            )

                        buffer_excel = io.BytesIO()

                        with pd.ExcelWriter(
                            buffer_excel,
                            engine="openpyxl"
                        ) as writer:

                            export_diario.to_excel(
                                writer,
                                index=False,
                                sheet_name="Informe_Diario"
                            )

                        st.download_button(
                            "Descargar detalle diario en Excel",
                            data=buffer_excel.getvalue(),
                            file_name=(
                                f"detalle_diario_"
                                f"{codigo_area.lower()}_"
                                f"{fecha_informe:%Y%m%d}.xlsx"
                            ),
                            mime=(
                                "application/vnd.openxmlformats-"
                                "officedocument.spreadsheetml.sheet"
                            ),
                            use_container_width=True
                        )

                st.divider()

                # =============================================
                # TABLA DE REGISTROS DEL DÍA
                # =============================================

                st.subheader(
                    "Registros de avance del día"
                )

                if diarios_informe.empty:

                    st.info(
                        "No existen avances registrados "
                        "para la fecha seleccionada."
                    )

                else:

                    detalle_diario = (
                        diarios_informe
                        .merge(
                            df_actividades_informe[
                                [
                                    "id",
                                    "ot_id",
                                    "codigo_actividad",
                                    "descripcion",
                                    "supervisor",
                                    "especialidad"
                                ]
                            ],
                            left_on="actividad_id",
                            right_on="id",
                            how="left",
                            suffixes=(
                                "",
                                "_actividad"
                            )
                        )
                        .merge(
                            df_ots_informe[
                                [
                                    "id",
                                    "ot",
                                    "equipo"
                                ]
                            ],
                            left_on="ot_id",
                            right_on="id",
                            how="left",
                            suffixes=(
                                "",
                                "_ot"
                            )
                        )
                    )

                    detalle_diario[
                        "HORA"
                    ] = pd.to_datetime(
                        detalle_diario[
                            "fecha_lima"
                        ],
                        errors="coerce"
                    ).dt.strftime(
                        "%H:%M"
                    )

                    columnas_diario = [
                        "HORA",
                        "ot",
                        "equipo",
                        "codigo_actividad",
                        "descripcion",
                        "avance",
                        "tipo_evidencia",
                        "descripcion_avance",
                        "observaciones",
                        "usuario"
                    ]

                    columnas_diario = [
                        columna
                        for columna in columnas_diario
                        if columna
                        in detalle_diario.columns
                    ]

                    tabla_diaria = detalle_diario[
                        columnas_diario
                    ].copy()

                    tabla_diaria = tabla_diaria.rename(
                        columns={
                            "ot": "OT",
                            "equipo": "EQUIPO",
                            "codigo_actividad":
                                "ACTIVIDAD",
                            "descripcion":
                                "DESCRIPCIÓN",
                            "avance":
                                "AVANCE (%)",
                            "tipo_evidencia":
                                "ETAPA",
                            "descripcion_avance":
                                "AVANCE REPORTADO",
                            "observaciones":
                                "OBSERVACIONES",
                            "usuario":
                                "USUARIO"
                        }
                    )

                    st.dataframe(
                        tabla_diaria,
                        use_container_width=True,
                        hide_index=True,
                        height=420
                    )


    # =====================================================
    # REPORTES
    # =====================================================

    elif pagina == "Reportes":

        st.subheader(
            f"Reportes - {nombre_area}"
        )

        st.caption(
            "Generación de reporte ejecutivo del área "
            "con indicadores, resumen operativo y detalle por OT."
        )

        if not ots_area:

            st.warning(
                "Todavía no existen OTs cargadas para esta área."
            )

        else:

            ids_ots_reporte = [
                ot["id"]
                for ot in ots_area
            ]

            actividades_reporte = (
                supabase
                .table("actividades")
                .select(
                    "id,ot_id,codigo_actividad,descripcion,"
                    "supervisor,especialidad,grupo,peso,"
                    "inicio_plan,fin_plan,seccion,personal,"
                    "duracion_h,hh_plan,critica,activo"
                )
                .in_(
                    "ot_id",
                    ids_ots_reporte
                )
                .eq(
                    "activo",
                    True
                )
                .execute()
            ).data or []

            if not actividades_reporte:

                st.warning(
                    "No existen actividades cargadas "
                    "para esta área."
                )

            else:

                df_ots_reporte = pd.DataFrame(
                    ots_area
                )

                df_actividades_reporte = pd.DataFrame(
                    actividades_reporte
                )

                ids_actividades_reporte = (
                    df_actividades_reporte[
                        "id"
                    ]
                    .dropna()
                    .tolist()
                )

                avances_reporte = (
                    supabase
                    .table("avances_actividad")
                    .select(
                        "id,actividad_id,avance,"
                        "descripcion_avance,observaciones,"
                        "tipo_evidencia,critica,evidencias,"
                        "usuario,fecha_registro"
                    )
                    .in_(
                        "actividad_id",
                        ids_actividades_reporte
                    )
                    .execute()
                ).data or []

                df_avances_reporte = pd.DataFrame(
                    avances_reporte
                )

                kpis_reporte = compute_kpis(
                    df_actividades_reporte,
                    df_avances_reporte
                )

                r1, r2, r3, r4 = st.columns(4)

                with r1:
                    st.metric(
                        "OTs",
                        len(df_ots_reporte)
                    )

                with r2:
                    st.metric(
                        "Actividades",
                        kpis_reporte[
                            "actividades"
                        ]
                    )

                with r3:
                    st.metric(
                        "Avance general",
                        f"{kpis_reporte['avance_general']:.1f}%"
                    )

                with r4:
                    st.metric(
                        "SPI",
                        f"{kpis_reporte['spi']:.2f}"
                    )

                st.divider()

                st.subheader(
                    "Reporte ejecutivo PDF"
                )

                st.write(
                    "El PDF incluye indicadores principales, "
                    "resumen del día, actividades críticas, "
                    "pendientes y detalle consolidado por OT."
                )

                try:

                    pdf_bytes = construir_pdf_ejecutivo_area(
                        df_ots_reporte,
                        df_actividades_reporte,
                        df_avances_reporte,
                        nombre_area
                    )

                    st.download_button(
                        "Descargar reporte ejecutivo PDF",
                        data=pdf_bytes,
                        file_name=(
                            f"PDP_Chinalco_"
                            f"{codigo_area.lower()}_"
                            f"{datetime.now():%Y%m%d_%H%M}.pdf"
                        ),
                        mime="application/pdf",
                        type="primary",
                        use_container_width=True
                    )

                except Exception as exc:

                    st.error(
                        "No fue posible generar el PDF: "
                        f"{exc}"
                    )

                st.divider()

                st.subheader(
                    "Exportación completa a Excel"
                )

                estado_reporte = build_activity_status(
                    df_actividades_reporte,
                    df_avances_reporte
                )

                if not estado_reporte.empty:

                    estado_reporte = (
                        estado_reporte
                        .merge(
                            df_ots_reporte[
                                [
                                    "id",
                                    "ot",
                                    "equipo"
                                ]
                            ],
                            left_on="ot_id",
                            right_on="id",
                            how="left",
                            suffixes=(
                                "",
                                "_ot"
                            )
                        )
                    )

                buffer_reporte_excel = io.BytesIO()

                # Excel no admite fechas con timezone.
                # También limpiamos listas/diccionarios antes de exportar.
                excel_ots = preparar_dataframe_excel(
                    df_ots_reporte
                )

                excel_actividades = preparar_dataframe_excel(
                    df_actividades_reporte
                )

                excel_avances = preparar_dataframe_excel(
                    df_avances_reporte
                )

                excel_estado = preparar_dataframe_excel(
                    estado_reporte
                )

                with pd.ExcelWriter(
                    buffer_reporte_excel,
                    engine="openpyxl"
                ) as writer:

                    excel_ots.to_excel(
                        writer,
                        index=False,
                        sheet_name="OTs"
                    )

                    excel_actividades.to_excel(
                        writer,
                        index=False,
                        sheet_name="Actividades"
                    )

                    excel_avances.to_excel(
                        writer,
                        index=False,
                        sheet_name="Avances"
                    )

                    excel_estado.to_excel(
                        writer,
                        index=False,
                        sheet_name="Estado_Actual"
                    )

                st.download_button(
                    "Descargar reporte completo en Excel",
                    data=buffer_reporte_excel.getvalue(),
                    file_name=(
                        f"PDP_Chinalco_"
                        f"{codigo_area.lower()}_"
                        f"{datetime.now():%Y%m%d_%H%M}.xlsx"
                    ),
                    mime=(
                        "application/vnd.openxmlformats-"
                        "officedocument.spreadsheetml.sheet"
                    ),
                    use_container_width=True
                )
