import os
import requests
import pandas as pd
from dotenv import load_dotenv
import streamlit as st
from helper.helper import Helper

# Cargar las variables de entorno
load_dotenv()

# Obtener la clave de la API de Groq
groq_api_key = os.getenv("GROQ_API_KEY")

# URL de la API de Groq
groq_url = "https://api.groq.com/openai/v1/chat/completions"

# Conexión a Impala usando Helper
helper = Helper(dsn="impala-prod-cdppc", username="lrivera")

# Función para cambiar la base de datos a 'proceso_apis'
def switch_to_proceso_apis():
    """Conectar a la base de datos proceso_apis."""
    sql_query = "USE proceso_apis"
    helper.ejecutar_consulta(sql_query)

# Función para obtener información de las tablas
def get_table_info():
    """Obtener las tablas de la base de datos proceso_apis."""
    switch_to_proceso_apis()
    sql_query = "SHOW TABLES"
    result = helper.ejecutar_consulta(sql_query)
    if not result:
        raise ValueError("No se pudieron obtener las tablas. Verifique la conexión y la base de datos.")
    return result

# Función para obtener el esquema de una tabla
def get_schema(table_name):
    """Obtener el esquema de la tabla seleccionada."""
    if not table_name:
        raise ValueError("No se ha seleccionado ninguna tabla.")
    sql_query = f"DESCRIBE proceso_apis.{table_name}"  # Asegurarse de usar el nombre de la base de datos
    result = helper.ejecutar_consulta(sql_query)
    if not result:
        raise ValueError(f"No se pudo obtener el esquema de la tabla: {table_name}")
    return result

# Función para ejecutar y formatear consultas SQL
def execute_and_format_query(database_name, table_name, sql_query):
    try:
        results = helper.ejecutar_consulta(sql_query)
        if results:
            # Get column names from the result set
            column_names = [desc[0] for desc in results.description]
            # Convert the result set to a list of lists, handling variable column counts
            result_list = []
            for row in results:
                row_list = list(row)  # Convert each row to a list
                result_list.append(row_list)
            # Create DataFrame with correct column names
            df = pd.DataFrame(result_list, columns=column_names)
            return df
        else:
            return None
    except Exception as e:
        st.error(f"Error al ejecutar la consulta: {e}")
        return None

# Función para consultar a Groq
def query_groq(user_message: str, schema: str, chat_history: str):
    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "llama3-8b-8192",
        "messages": [
            {
                "role": "user",
                "content": f"""
                You are a data analyst at a company. Based on the schema below and the conversation history, 
                please generate a SQL query and provide a response.

                SCHEMA:
                {schema}

                Conversation History: {chat_history}

                User question: {user_message}
                """
            }
        ]
    }
    try:
        response = requests.post(groq_url, json=data, headers=headers)
        response.raise_for_status()

        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error al consultar a Groq: {e}")
        return None

# Procesar la respuesta de Groq
def process_groq_response(response):
    """Extrae la consulta SQL de la respuesta de Groq sin texto adicional."""
    try:
        # Acceder al contenido de la respuesta de Groq
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        if "SELECT" in content:
            # Asegurarse de obtener solo la consulta SQL
            start_index = content.find("SELECT")
            sql_query = content[start_index:].strip()  # Extraer la consulta SQL

            # Encontrar el primer punto y coma y cortar todo después de él
            semicolon_index = sql_query.find(';')
            if semicolon_index != -1:
                sql_query = sql_query[:semicolon_index + 1]  # Incluir el punto y coma final

            return sql_query  
        else:
            raise ValueError("La respuesta no contiene una consulta SQL válida.")
    except Exception as e:
        st.error(f"Error al procesar la respuesta de Groq: {e}")
        return None  # Devolvemos solo None en caso de error


# Configuración de Streamlit
st.set_page_config(page_title="Chat with the LZ", page_icon=":speech_balloon:")
st.title("Chat with the LZ")

# Configuración de la conexión
with st.sidebar:
    st.subheader("Configuración de conexión")
    st.write("Conéctate a la base de datos y empieza a hacer preguntas.")
    if st.button("Conectar"):
        try:
            st.session_state.db = helper
            switch_to_proceso_apis()
            st.success("¡Conectado a la base de datos proceso_apis!")
            st.session_state.tables = get_table_info()
        except Exception as e:
            st.error(f"Error de conexión: {e}")

# Configuración inicial
DEFAULT_TABLE = "maestro_septiembre"

# Selección de tabla
if "tables" in st.session_state:
    st.session_state.selected_table = DEFAULT_TABLE

# Chat interactivo
if "selected_table" in st.session_state and "db" in st.session_state:
    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []

    user_query = st.chat_input("Escribe una pregunta...")

    if user_query:
        with st.chat_message("user"):
            st.markdown(f"**Usuario:** {user_query}")
        st.session_state.chat_history.append(f"Usuario: {user_query}")

        try:
            # Obtener el esquema de la tabla
            table_name = st.session_state.selected_table
            schema = get_schema(table_name)
            schema_str = "\n".join([f"{col[0]}: {col[1]}" for col in schema])

            if "último registro" in user_query.lower() and "api_name" in user_query.lower():
                sql_query = f"""
                SELECT product_name, app_name
                FROM proceso_apis.{table_name}  # Asegurarse de incluir la base de datos
                WHERE api_name = 'security-authorization-code'
                ORDER BY kudu_update DESC
                LIMIT 1;
                """
                summary = f"Mostrando el último registro de `{table_name}` para `api_name = 'security-authorization-code'`."
            else:
                # Consultar a Groq
                response = query_groq(user_query, schema_str, "\n".join(st.session_state.chat_history))
                if response:
                    sql_query = process_groq_response(response)
                    if not sql_query:
                        st.warning("No se generó una consulta SQL válida.")
                        sql_query = ""  # Evitar ejecución de consulta vacía
                        summary = "No se generó una consulta SQL válida."
                    else:
                        summary = f"Consulta SQL generada: {sql_query}"
                else:
                    summary = "Hubo un error al generar la consulta SQL."
                    sql_query = ""  # Evitar ejecución de consulta vacía

            # Ejecutar consulta y mostrar resultados
            if sql_query:
                df = execute_and_format_query("proceso_apis", table_name, sql_query)  # Asegurarse de ejecutar en 'proceso_apis'
                with st.chat_message("AI"):
                    st.markdown(f"**Respuesta:** {summary}")
                    if df is not None:
                        st.dataframe(df)
                    else:
                        st.warning("La consulta no devolvió resultados.")
        except Exception as e:
            with st.chat_message("AI"):
                st.error(f"Error: {e}")
