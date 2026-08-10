import io
import uuid

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from PIL import Image, ImageOps
from datetime import datetime, timezone
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

    ahora = pd.Timestamp.now()

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

        prog["fecha_registro"] = pd.to_datetime(
            prog["fecha_registro"],
            errors="coerce",
            utc=True
        ).dt.tz_localize(None)

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

    ultima_fecha_real = (
        prog["fecha_registro"].max()
        if not prog.empty
        else None
    )

    for corte in cortes:

        if prog.empty:

            real_values.append(
                0.0
                if corte == inicio_programa
                else None
            )

            continue

        if (
            ultima_fecha_real is not None
            and corte > ultima_fecha_real
        ):
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
# LOGIN Y CONTROL DE ACCESO
# =====================================================

def obtener_usuario(username):
    resultado = (
        supabase
        .table("usuarios_app")
        .select(
            "id,username,nombre,rol,area_id,activo,"
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
            # TEMPORAL PARA PRUEBAS
            # Luego reemplazaremos esto por contraseña cifrada
            if password.strip() == "1234":

                st.session_state["usuario_logueado"] = usuario

                st.rerun()

            else:
                st.error("Contraseña incorrecta.")

    st.stop()


# =====================================================
# USUARIO LOGUEADO
# =====================================================

usuario = st.session_state["usuario_logueado"]

rol = usuario["rol"]
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

with st.sidebar:

    st.title("MAININ")

    st.caption("PDP Control Center Chinalco")

    st.divider()

    st.write("Usuario:")
    st.success(usuario["nombre"])

    st.write("Rol:")
    st.info(rol.upper())

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

        st.info(
            "Acceso administrativo consolidado a "
            "Molinos, Chancado, Flotación y Relaves."
        )

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("MOLINOS", "0%")

        with col2:
            st.metric("CHANCADO", "0%")

        with col3:
            st.metric("FLOTACIÓN", "0%")

        with col4:
            st.metric("RELAVES", "0%")


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

        st.subheader("Reportes consolidados")

        st.info(
            "Aquí aparecerán los reportes generales "
            "de Chinalco."
        )


else:

    # =====================================================
    # MENÚ DEL USUARIO POR ÁREA
    # =====================================================

    with st.sidebar:

        st.divider()

        pagina = st.radio(
            "Menú",
            [
                "Dashboard",
                "Registrar avance",
                "Detalle por OT",
                "Evidencias",
                "Informe diario",
                "Reportes"
            ]
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

                fig_s.add_trace(
                    go.Scatter(
                        x=curva_s["fecha"],
                        y=curva_s["PLAN"],
                        mode="lines+markers",
                        name="PLAN"
                    )
                )

                fig_s.add_trace(
                    go.Scatter(
                        x=curva_s["fecha"],
                        y=curva_s["REAL"],
                        mode="lines+markers",
                        name="REAL",
                        connectgaps=False
                    )
                )

                fig_s.update_layout(
                    xaxis_title="Fecha / Hora",
                    yaxis_title="Avance acumulado (%)",
                    yaxis=dict(
                        range=[0, 105]
                    ),
                    hovermode="x unified",
                    legend_title="Curva",
                    height=500
                )

                fig_s.update_yaxes(
                    ticksuffix="%"
                )

                st.plotly_chart(
                    fig_s,
                    use_container_width=True
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
            # SELECCIÓN DE OT
            # ============================================

            mapa_ots = {
                f"{ot['ot']} - {ot.get('equipo') or 'Sin equipo'}": ot
                for ot in ots_area
            }

            ot_texto = st.selectbox(
                "Seleccione una OT",
                list(mapa_ots.keys())
            )

            ot_seleccionada = mapa_ots[ot_texto]

            st.info(
                f"Equipo: {ot_seleccionada.get('equipo') or 'Sin equipo'}"
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
                .eq("ot_id", ot_seleccionada["id"])
                .eq("activo", True)
                .order("codigo_actividad")
                .execute()
            )

            actividades_ot = actividades_resultado.data or []

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
                    list(mapa_actividades.keys())
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

                avance = st.number_input(
                    "Porcentaje de avance de la actividad (%)",
                    min_value=0,
                    max_value=100,
                    value=0,
                    step=5
                )

                tipo_evidencia = st.selectbox(
                    "Tipo de evidencia",
                    [
                        "INICIO",
                        "DURANTE",
                        "FINAL"
                    ]
                )

                critica = st.checkbox(
                    "Marcar actividad como crítica"
                )

                descripcion_avance = st.text_area(
                    "Descripción breve del avance realizado *"
                )

                observaciones = st.text_area(
                    "Observaciones"
                )

                archivos_evidencia = st.file_uploader(
                    "Evidencias fotográficas",
                    type=["jpg", "jpeg", "png", "webp"],
                    accept_multiple_files=True,
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

                    columnas_preview = st.columns(
                        min(
                            len(archivos_evidencia),
                            4
                        )
                    )

                    for indice, archivo_preview in enumerate(
                        archivos_evidencia[:4]
                    ):

                        with columnas_preview[
                            indice % len(columnas_preview)
                        ]:

                            st.image(
                                archivo_preview,
                                caption=archivo_preview.name,
                                use_container_width=True
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

        st.subheader(f"Informe diario - {nombre_area}")

        st.info(
            "Aquí construiremos el resumen diario automático "
            "del área."
        )


    # =====================================================
    # REPORTES
    # =====================================================

    elif pagina == "Reportes":

        st.subheader(f"Reportes - {nombre_area}")

        st.info(
            "Aquí construiremos los reportes de cumplimiento, "
            "avance y pendientes."
        )
