import streamlit as st
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


supabase = conectar_supabase()


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

    st.subheader("Dashboard Consolidado Chinalco")

    st.info(
        "Acceso administrativo a Molinos, Chancado, "
        "Flotación y Relaves."
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

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("OTs registradas", total_ots)

        with col2:
            st.metric("Actividades", "0")

        with col3:
            st.metric("Avance general", "0%")

        with col4:
            st.metric("Pendientes", "0")

        st.divider()

        st.info(
            "El dashboard todavía no tiene actividades cargadas. "
            "En el siguiente paso conectaremos las actividades y los avances."
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
