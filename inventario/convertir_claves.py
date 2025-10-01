import bcrypt
from config import conectar, desconectar

conexion = conectar()
cur = conexion.cursor()
cur.execute("SELECT id_usu, clave FROM usuarios;")
rows = cur.fetchall()

for id_usu, clave in rows:
    if clave and not clave.startswith("$2b$"):  # bcrypt hashes empiezan con $2b$
        hashed = bcrypt.hashpw(clave.encode("utf-8"), bcrypt.gensalt())
        cur.execute("UPDATE usuarios SET clave = %s WHERE id_usu = %s", (hashed.decode("utf-8"), id_usu))

conexion.commit()
cur.close()
desconectar(conexion)
print("✅ Todas las contraseñas han sido convertidas a bcrypt")
