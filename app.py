import streamlit as st
import pandas as pd
from datetime import datetime
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
# INTERFAZ DE PRUEBA
# =====================================================

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

            st.success(
                f"Visualización exclusiva del área {nombre_area}."
            )

            total_ots = len(ots_area)

        # ============================================
        # ACTIVIDADES DEL ÁREA
        # ============================================

        ot_ids = [ot["id"] for ot in ots_area]

        if ot_ids:
            actividades_area = (
                supabase
                .table("actividades")
                .select("id,ot_id,peso")
                .in_("ot_id", ot_ids)
                .eq("activo", True)
                .execute()
            ).data or []
        else:
            actividades_area = []

        total_actividades = len(actividades_area)

        # Al inicio todas las actividades son pendientes
        total_pendientes = total_actividades

        # Todavía no existen avances registrados
        avance_general = 0

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("OTs registradas", total_ots)

        with col2:
            st.metric("Actividades", total_actividades)

        with col3:
            st.metric("Avance general", f"{avance_general}%")

        with col4:
            st.metric("Pendientes", total_pendientes)

        st.divider()

        if total_actividades > 0:
            st.success(
                f"Planificación cargada correctamente: "
                f"{total_ots} OTs y {total_actividades} actividades."
            )
        else:
            st.warning(
                "No existen actividades cargadas para esta área."
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
            lista_ots = [
                f"{ot['ot']} - {ot.get('equipo') or 'Sin equipo'}"
                for ot in ots_area
            ]

            st.selectbox(
                "Seleccione una OT",
                lista_ots
            )

            st.info(
                "En el siguiente paso conectaremos las actividades "
                "de la OT seleccionada."
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
            st.dataframe(
                ots_area,
                use_container_width=True,
                hide_index=True
            )


    # =====================================================
    # EVIDENCIAS
    # =====================================================

    elif pagina == "Evidencias":

        st.subheader(f"Evidencias - {nombre_area}")

        st.info(
            "Aquí se mostrarán únicamente las evidencias "
            "correspondientes a esta área."
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
