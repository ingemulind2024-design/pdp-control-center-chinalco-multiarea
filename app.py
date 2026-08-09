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
