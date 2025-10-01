import psycopg2

def conectar():
    try:
        conexion = psycopg2.connect(
            user="neondb_owner",
            password="npg_wLtJlWEPA8r6",
            host="ep-dry-firefly-ad3cstda-pooler.c-2.us-east-1.aws.neon.tech",
            port="5432",
            database="neondb",
            sslmode="require"
        )
        print("✅ Conexión a Neon PostgreSQL establecida correctamente")
        return conexion
    except (Exception, psycopg2.Error) as error:
        print("❌ Error al conectar a Neon PostgreSQL:", error)
        return None

def desconectar(conexion):
    if conexion is not None:
        conexion.close()
        print("🔒 Conexión cerrada")

