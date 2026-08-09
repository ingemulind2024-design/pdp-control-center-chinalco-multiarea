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


# =====================================================
# USUARIOS POR ÁREA
# =====================================================

else:

    st.subheader(f"Área: {nombre_area}")

    st.success(
        f"Acceso autorizado únicamente para {nombre_area}."
    )

    st.write(
        "Las OTs, actividades y avances que se mostrarán "
        "en este acceso estarán filtrados automáticamente "
        "por esta área."
    )

st.title("PDP CONTROL CENTER CHINALCO - MAININ")

st.caption(
    "Sistema integrado de seguimiento y control de la Parada de Planta"
)

st.divider()

st.subheader("Áreas operativas")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.info("⚙️ MOLINOS\n\nFase 1 y Fase 2")

with col2:
    st.info("⛏️ CHANCADO")

with col3:
    st.info("🔵 FLOTACIÓN")

with col4:
    st.info("🌊 RELAVES")


# =====================================================
# PRUEBA DE CONEXIÓN
# =====================================================

st.divider()

st.subheader("Estado del sistema")

try:

    resultado = (
        supabase
        .table("areas")
        .select("id,codigo,nombre")
        .order("id")
        .execute()
    )

    areas_db = resultado.data or []

    st.success("✅ Conexión con Supabase establecida correctamente.")

    if areas_db:

        st.write("Áreas encontradas en la base de datos:")

        for area in areas_db:
            st.write(
                f"✅ {area['codigo']} — {area['nombre']}"
            )

    else:
        st.warning("La conexión funciona, pero no se encontraron áreas.")

except Exception as e:

    st.error("❌ No se pudo consultar Supabase.")

    st.code(str(e))
