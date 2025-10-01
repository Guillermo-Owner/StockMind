import os
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, send_file, flash
from werkzeug.utils import secure_filename
from config import conectar, desconectar
import bcrypt

# Librerías para PDF
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from io import BytesIO

# Extras de psycopg2
import psycopg2
from psycopg2.extras import RealDictCursor

# Librerías para correos
import smtplib
from email.mime.text import MIMEText
from datetime import date

app = Flask(__name__)
app.secret_key = 'clave_super_secreta'

# Carpeta para subir imágenes
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Configuración SMTP
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_USER = "StockMind21@gmail.com"
EMAIL_PASS = "arnh yzvg ckii urcd"  # contraseña de aplicación de Gmail


@app.route('/uploads/<path:filename>')
def uploads(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# ---------- LOGIN ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form["usuario"]
        clave = request.form["clave"]
        rol = request.form["tipo_usuario"]

        conexion = conectar()
        if not conexion:
            return "No se pudo conectar a la base de datos"

        try:
            cursor = conexion.cursor()
            cursor.execute("""
                SELECT id_usu, nombre, usuario, rol, clave
                FROM usuarios
                WHERE usuario = %s AND rol = %s
            """, (usuario, rol))
            user = cursor.fetchone()
            cursor.close()
        finally:
            desconectar(conexion)

        if user:
            hash_db = user[4].encode('utf-8')
            if bcrypt.checkpw(clave.encode('utf-8'), hash_db):
                session.update({
                    'id_usuario': user[0],
                    'nombre': user[1],
                    'usuario': user[2],
                    'rol': user[3],
                })
                # actualizar ultimo login
                conexion = conectar()
                cur = conexion.cursor()
                cur.execute("UPDATE usuarios SET ultimo_login = CURRENT_TIMESTAMP WHERE id_usu=%s", (user[0],))
                conexion.commit()
                cur.close()
                desconectar(conexion)

                return redirect(url_for("index"))
            else:
                return render_template("login.html", error="Contraseña incorrecta")
        else:
            return render_template("login.html", error="Usuario no encontrado")

    return render_template("login.html")


# ---------- INDEX ----------
@app.route("/index")
def index():
    conexion = conectar()
    if not conexion:
        return "No se pudo conectar a la base de datos", 500

    productos = []
    try:
        cur = conexion.cursor()
        cur.execute("""
            SELECT id_prod, nombre, cantidad, imagen, lugar, descripcion
            FROM producto
            ORDER BY id_prod DESC
        """)
        productos = [
            {
                "id_prod": r[0],
                "nombre": r[1],
                "cantidad": r[2],
                "imagen": r[3],
                "lugar": r[4],
                "descripcion": r[5]
            }
            for r in cur.fetchall()
        ]
        cur.close()
    except Exception as e:
        return f"Error consultando productos: {e}", 500
    finally:
        desconectar(conexion)

    return render_template("index.html", productos=productos)


# ---------- FUNCIONES DE CORREO ----------
def enviar_correo(destinatario, asunto, cuerpo_html):
    msg = MIMEText(cuerpo_html, "html")
    msg["Subject"] = asunto
    msg["From"] = EMAIL_USER
    msg["To"] = destinatario

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(msg["From"], [msg["To"]], msg.as_string())
    print(f"✅ Correo enviado a {destinatario}")


def notificacion_prestamo(id_prestamo):
    """Se envía cuando se registra un préstamo nuevo"""
    conn = psycopg2.connect(dbname="inventario2", user="postgres", password="123456", host="localhost", port="5432")
    cur = conn.cursor()

    cur.execute("""
        SELECT u.correo, u.nombre, p.nombre, pr.fecha_devolucion
        FROM prestamos pr
        JOIN usuarios u ON pr.id_usu = u.id_usu
        JOIN producto p ON pr.id_prod = p.id_prod
        WHERE pr.id_prestamo = %s;
    """, (id_prestamo,))
    
    correo, usuario, producto, fecha_dev = cur.fetchone()
    dias_restantes = (fecha_dev.date() - date.today()).days

    cuerpo = f"""
    <h2>📢 Confirmación de préstamo</h2>
    <p>Hola {usuario},</p>
    <p>Has solicitado el producto: <b>{producto}</b></p>
    <p><b>Fecha de devolución:</b> {fecha_dev.date()}</p>
    <p><b>Días restantes:</b> {dias_restantes}</p>
    """

    enviar_correo(correo, "Confirmación de tu préstamo 📌", cuerpo)

    cur.close()
    conn.close()


def notificacion_recordatorios():
    """Se ejecuta cada día: si falta 1 día, manda recordatorio"""
    conn = psycopg2.connect(dbname="inventario2", user="postgres", password="123456", host="localhost", port="5432")
    cur = conn.cursor()

    cur.execute("""
        SELECT u.correo, u.nombre, p.nombre, pr.fecha_devolucion
        FROM prestamos pr
        JOIN usuarios u ON pr.id_usu = u.id_usu
        JOIN producto p ON pr.id_prod = p.id_prod
        WHERE pr.estado = 'pendiente';
    """)

    prestamos = cur.fetchall()
    for correo, usuario, producto, fecha_dev in prestamos:
        dias_restantes = (fecha_dev.date() - date.today()).days
        if dias_restantes == 1:
            cuerpo = f"""
            <h2>⏰ Recordatorio de devolución</h2>
            <p>Hola {usuario},</p>
            <p>Recuerda devolver el producto: <b>{producto}</b></p>
            <p><b>Fecha de devolución:</b> {fecha_dev.date()}</p>
            <p>⚠️ Te queda <b>1 día</b> para entregarlo</p>
            """
            enviar_correo(correo, "Recordatorio: entrega mañana 📌", cuerpo)

    cur.close()
    conn.close()

def notificacion_devolucion(id_prestamo):
    """Se envía cuando un préstamo es devuelto"""
    conn = psycopg2.connect(dbname="inventario2", user="postgres", password="123456", host="localhost", port="5432")
    cur = conn.cursor()

    cur.execute("""
        SELECT u.correo, u.nombre, p.nombre, pr.fecha_devolucion
        FROM prestamos pr
        JOIN usuarios u ON pr.id_usu = u.id_usu
        JOIN producto p ON pr.id_prod = p.id_prod
        WHERE pr.id_prestamo = %s;
    """, (id_prestamo,))
    
    correo, usuario, producto, fecha_dev = cur.fetchone()

    cuerpo = f"""
    <h2>✅ Confirmación de devolución</h2>
    <p>Hola {usuario},</p>
    <p>Se ha registrado la devolución del producto: <b>{producto}</b>.</p>
    <p><b>Fecha de devolución registrada:</b> {fecha_dev.date()}</p>
    <hr>
    <p>¡Gracias por cumplir con los tiempos del préstamo! 🎉</p>
    """

    enviar_correo(correo, "Confirmación de devolución ✅", cuerpo)

    cur.close()
    conn.close()


# ---------- AGREGAR PRODUCTO ----------
@app.route("/agregar", methods=["POST"])
def agregar():
    nombre = request.form["nombre"]
    cantidad = request.form["cantidad"]
    lugar = request.form["lugar"]
    descripcion = request.form["descripcion"]
    imagen = request.files.get("imagen")

    # Valor por defecto
    imagen_nombre = "default_prod.png"
    if imagen and imagen.filename:
        imagen_nombre = secure_filename(imagen.filename)
        imagen.save(os.path.join(UPLOAD_FOLDER, imagen_nombre))

    conexion = conectar()
    try:
        cur = conexion.cursor()
        cur.execute("""
            INSERT INTO producto (nombre, cantidad, lugar, descripcion, imagen)
            VALUES (%s, %s, %s, %s, %s)
        """, (nombre, cantidad, lugar, descripcion, imagen_nombre))
        conexion.commit()
        cur.close()
    except Exception as e:
        return f"Error insertando producto: {e}", 500
    finally:
        desconectar(conexion)

    return redirect(url_for("index"))


# ---------- ELIMINAR PRODUCTO ----------
@app.route("/eliminar/<int:id_prod>")
def eliminar(id_prod):
    conexion = conectar()
    try:
        cur = conexion.cursor()
        cur.execute("DELETE FROM producto WHERE id_prod = %s", (id_prod,))
        conexion.commit()
        cur.close()
    except Exception as e:
        return f"Error eliminando producto: {e}", 500
    finally:
        desconectar(conexion)

    return redirect(url_for("index"))


# ---------- ACTUALIZAR PRODUCTO ----------
@app.route("/actualizar_producto", methods=["POST"])
def actualizar_producto():
    id_prod = request.form["id_prod"]
    nombre = request.form["nombre"]
    cantidad = request.form["cantidad"]
    lugar = request.form["lugar"]
    descripcion = request.form["descripcion"]

    conexion = None
    try:
        conexion = conectar()
        cursor = conexion.cursor()
        consulta = """
            UPDATE producto SET
            nombre = %s,
            cantidad = %s,
            lugar = %s,
            descripcion = %s
            WHERE id_prod = %s
        """
        datos = (nombre, cantidad, lugar, descripcion, id_prod)
        cursor.execute(consulta, datos)
        conexion.commit()
        cursor.close()
    except Exception as e:
        print(f"Error al actualizar producto: {e}")
        return "Error al actualizar el producto"
    finally:
        if conexion:
            desconectar(conexion)

    return redirect(url_for("index"))


# ---------- LISTAR USUARIOS ----------
@app.route("/usuarios")
def listar_usuarios():
    conexion = conectar()
    usuarios = []
    try:
        cur = conexion.cursor()
        cur.execute("SELECT id_usu, nombre, usuario, rol, telefono, correo, direccion, foto FROM usuarios ORDER BY id_usu")
        usuarios = [
            {"id_usu": r[0], "nombre": r[1], "usuario": r[2], "rol": r[3], "telefono": r[4], "correo": r[5], "direccion": r[6], "foto": r[7]}
            for r in cur.fetchall()
        ]
        cur.close()
    finally:
        desconectar(conexion)

    return render_template("usuarios.html", usuarios=usuarios)


# ---------- AGREGAR USUARIO ----------
@app.route("/usuarios/agregar", methods=["POST"])
def agregar_usuario():
    nombre = request.form["nombre"]
    usuario = request.form["usuario"]
    rol = request.form["tipo_usuario"]
    clave = request.form["clave"]
    telefono = request.form["telefono"]
    correo = request.form.get("correo")
    direccion = request.form.get("direccion")
    foto = request.files.get("foto")

    # Guardar clave encriptada
    hashed = bcrypt.hashpw(clave.encode('utf-8'), bcrypt.gensalt())

    foto_nombre = "default.png"
    if foto and foto.filename:
        foto_nombre = secure_filename(f"{usuario}_{foto.filename}")
        foto.save(os.path.join(UPLOAD_FOLDER, foto_nombre))

    conexion = conectar()
    try:
        cur = conexion.cursor()
        cur.execute("""
            INSERT INTO usuarios (nombre, usuario, rol, clave, telefono, correo, direccion, foto)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (nombre, usuario, rol, hashed.decode('utf-8'), telefono, correo, direccion, foto_nombre))
        conexion.commit()
        cur.close()
    finally:
        desconectar(conexion)

    return redirect(url_for("listar_usuarios"))


# ---------- EDITAR USUARIO ----------
@app.route("/usuarios/editar", methods=["POST"])
def editar_usuario():
    id_usu_form = request.form.get("id_usu")
    if id_usu_form:
        id_usu = int(id_usu_form)
    else:
        # Si no viene desde el form, tomar el id del usuario en sesión (perfil)
        id_usu = session.get("id_usuario")

    nombre = request.form.get("nombre")
    usuario = request.form.get("usuario")
    telefono = request.form.get("telefono")
    clave = request.form.get("clave")
    rol = request.form.get("tipo_usuario")
    correo = request.form.get("correo")
    direccion = request.form.get("direccion")
    foto = request.files.get("foto")

    conexion = conectar()
    try:
        cur = conexion.cursor()

        # Obtener foto actual si no se sube nueva
        cur.execute("SELECT foto FROM usuarios WHERE id_usu=%s", (id_usu,))
        foto_actual = cur.fetchone()[0] if cur.rowcount > 0 else "default.png"
        foto_nombre = foto_actual

        if foto and foto.filename:
            foto_nombre = secure_filename(f"{id_usu}_{foto.filename}")
            foto.save(os.path.join(UPLOAD_FOLDER, foto_nombre))

        if clave:
            hashed = bcrypt.hashpw(clave.encode('utf-8'), bcrypt.gensalt())
            consulta = """
                UPDATE usuarios
                SET nombre=%s, usuario=%s, rol=%s, clave=%s,
                    telefono=%s, correo=%s, direccion=%s, foto=%s
                WHERE id_usu=%s
            """
            cur.execute(consulta, (nombre, usuario, rol, hashed.decode('utf-8'),
                                   telefono, correo, direccion, foto_nombre, id_usu))
        else:
            consulta = """
                UPDATE usuarios
                SET nombre=%s, usuario=%s, rol=%s,
                    telefono=%s, correo=%s, direccion=%s, foto=%s
                WHERE id_usu=%s
            """
            cur.execute(consulta, (nombre, usuario, rol, telefono,
                                   correo, direccion, foto_nombre, id_usu))

        conexion.commit()
        cur.close()
    finally:
        desconectar(conexion)

    if "id_usuario" in session and session["id_usuario"] == id_usu:
        return redirect(url_for("perfil"))

    return redirect(url_for("listar_usuarios"))


# ---------- ELIMINAR USUARIO ----------
@app.route("/usuarios/eliminar/<int:id_usu>")
def eliminar_usuario(id_usu):
    conexion = conectar()
    try:
        cur = conexion.cursor()
        cur.execute("DELETE FROM usuarios WHERE id_usu=%s", (id_usu,))
        conexion.commit()
        cur.close()
    finally:
        desconectar(conexion)

    return redirect(url_for("listar_usuarios"))


# ---------- PERFIL ----------
@app.route("/perfil")
def perfil():
    conexion = conectar()
    usuario = None
    prestamos_pendientes = []
    try:
        cur = conexion.cursor()

        # Datos del usuario
        cur.execute("""
            SELECT id_usu, nombre, usuario, rol, telefono, correo, direccion, ultimo_login, foto
            FROM usuarios
            WHERE id_usu=%s
        """, (session["id_usuario"],))
        row = cur.fetchone()
        if row:
            usuario = {
                "id": row[0], "nombre": row[1], "usuario": row[2], "rol": row[3],
                "telefono": row[4], "correo": row[5], "direccion": row[6],
                "ultimo_login": row[7], "foto": row[8]
            }

        # Préstamos pendientes del usuario
        cur.execute("""
            SELECT pr.id_prestamo, p.nombre AS producto, pr.cantidad, 
                pr.fecha_prestamo, pr.fecha_devolucion, pr.estado
            FROM prestamos pr
            JOIN producto p ON pr.id_prod = p.id_prod
            WHERE pr.id_usu = %s AND pr.estado = 'pendiente'
            ORDER BY pr.fecha_devolucion ASC
        """, (session["id_usuario"],))

        prestamos_pendientes = []
        for row in cur.fetchall():
            id_prestamo, producto, cantidad, fecha_prestamo, fecha_devolucion, estado = row
            prestamos_pendientes.append((
                id_prestamo,
                producto,
                cantidad,
                fecha_prestamo.date(),    # 👈 convertimos a date
                fecha_devolucion.date(),  # 👈 convertimos a date
                estado
            ))


        cur.close()
    finally:
        desconectar(conexion)

    # 🔹 Pasamos también la fecha de hoy
    return render_template("perfil_usuarios.html", usuario=usuario, prestamos=prestamos_pendientes, hoy=date.today())


# ---------- REPORTES ----------
@app.route("/reportes")
def reportes():
    return render_template("reportes.html")


@app.route("/ver_reporte/<tipo>")
def ver_reporte(tipo):
    """Genera el PDF en memoria y lo muestra o descarga según parámetro"""
    descargar = request.args.get("descargar")  # si viene ?descargar=1 → descarga
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    styles = getSampleStyleSheet()
    elements = []

    # ----- ENCABEZADO -----
    logo_path = os.path.join("static", "logo.png.png")
    if os.path.exists(logo_path):
        elements.append(Image(logo_path, width=90, height=100))
    elements.append(Paragraph(f"Reporte de {tipo.title()} - {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    conexion = conectar()
    cur = conexion.cursor()

    if tipo == "productos":
        cur.execute("SELECT id_prod, nombre, cantidad, lugar, descripcion, imagen FROM producto")
        data = cur.fetchall()
        headers = ["ID", "Nombre", "Cantidad", "Lugar", "Descripción", "Imagen"]
        table_data = [headers]

        for row in data:
            imagen_path = os.path.join(UPLOAD_FOLDER, row[5]) if row[5] else None
            if imagen_path and os.path.exists(imagen_path):
                imagen_img = Image(imagen_path, width=40, height=40)
            else:
                imagen_img = "Sin foto"

            table_data.append([row[0], row[1], row[2], row[3], row[4], imagen_img])

        col_widths = [50, 120, 80, 100, 200, 60]


    elif tipo == "usuarios":
        cur.execute("SELECT id_usu, nombre, usuario, rol, telefono, correo, direccion, foto FROM usuarios")
        data = cur.fetchall()
        headers = ["ID", "Nombre", "Usuario", "Rol", "Teléfono", "Correo", "Dirección", "Foto"]
        table_data = [headers]

        for row in data:
            # Todos los usuarios tienen foto, usar la ruta directamente
            foto_path = os.path.join(UPLOAD_FOLDER, row[7])  # row[7] es la columna 'foto'
            foto_img = Image(foto_path, width=40, height=40)
            table_data.append([row[0], row[1], row[2], row[3], row[4], row[5], row[6], foto_img])

        col_widths = [20, 170, 80, 70, 70, 180, 130, 60]


    cur.close()
    desconectar(conexion)

    # ----- TABLA -----
    table = Table(table_data, repeatRows=1, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightblue),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer,
        download_name=f"reporte_{tipo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
        mimetype="application/pdf",
        as_attachment=True if descargar else False
    )

# ---------- Dashboard de préstamos ----------
@app.route("/prestamos")
def prestamos():
    if "usuario" not in session:
        return redirect(url_for("login"))

    conexion = conectar()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)

    cursor.execute("""
        SELECT pr.id_prestamo, u.nombre AS usuario, p.nombre AS producto, pr.cantidad,
               pr.fecha_prestamo, pr.fecha_devolucion, pr.estado
        FROM prestamos pr
        JOIN usuarios u ON pr.id_usu = u.id_usu
        JOIN producto p ON pr.id_prod = p.id_prod
        ORDER BY pr.fecha_prestamo DESC
    """)
    prestamos = cursor.fetchall()

    cursor.execute("SELECT id_usu, nombre FROM usuarios")
    usuarios = cursor.fetchall()

    cursor.execute("SELECT id_prod, nombre, cantidad FROM producto")
    productos = cursor.fetchall()

    cursor.close()
    desconectar(conexion)

    return render_template("prestamos.html", prestamos=prestamos, usuarios=usuarios, productos=productos)


# ---------- Registrar préstamo ----------
# ---------- Registrar préstamo ----------
@app.route("/registrar_prestamo", methods=["POST"])
def registrar_prestamo():
    try:
        id_usu = int(request.form["usuario"])
        id_prod = int(request.form["producto"])
        cantidad = int(request.form["cantidad"])
        fecha_prestamo = request.form["fecha_prestamo"]
        fecha_devolucion = request.form["fecha_devolucion"]
    except Exception as e:
        flash(f"Datos inválidos: {e}", "danger")
        return redirect(url_for("prestamos"))

    conexion = conectar()
    if not conexion:
        flash("No se pudo conectar a la base de datos", "danger")
        return redirect(url_for("prestamos"))

    try:
        cursor = conexion.cursor()

        # Verificar stock
        cursor.execute("SELECT cantidad FROM producto WHERE id_prod=%s", (id_prod,))
        prod = cursor.fetchone()
        if not prod:
            flash("Producto no encontrado", "danger")
            return redirect(url_for("prestamos"))

        stock_actual = prod[0]
        if stock_actual < cantidad:
            flash(f"No hay suficiente stock. Disponible: {stock_actual}", "danger")
            return redirect(url_for("prestamos"))

        # Insertar préstamo y obtener id
        cursor.execute("""
            INSERT INTO prestamos (id_usu, id_prod, cantidad, fecha_prestamo, fecha_devolucion, estado)
            VALUES (%s, %s, %s, %s, %s, 'pendiente')
            RETURNING id_prestamo
        """, (id_usu, id_prod, cantidad, fecha_prestamo, fecha_devolucion))

        id_prestamo = cursor.fetchone()[0]

        # Actualizar stock
        cursor.execute("UPDATE producto SET cantidad = cantidad - %s WHERE id_prod = %s", (cantidad, id_prod))

        conexion.commit()
        cursor.close()

        # 🔹 Aquí se envía el correo automáticamente al usuario del perfil
        notificacion_prestamo(id_prestamo)

        flash("Préstamo registrado correctamente y notificación enviada", "success")

    except Exception as e:
        conexion.rollback()
        flash(f"Error registrando préstamo: {e}", "danger")
    finally:
        desconectar(conexion)

    return redirect(url_for("prestamos"))

# ---------- Registrar devolución ----------
@app.route("/devolucion", methods=["POST"])
def devolucion():
    id_prestamo = request.form.get("id_prestamo")
    estado = request.form.get("estado", "").strip()

    if not id_prestamo:
        flash("No se especificó el préstamo", "danger")
        return redirect(url_for("prestamos"))

    if not estado:
        estado = "devuelto"

    try:
        id_prestamo = int(id_prestamo)
    except ValueError:
        flash("ID de préstamo inválido", "danger")
        return redirect(url_for("prestamos"))

    conexion = conectar()
    if not conexion:
        flash("No se pudo conectar a la base de datos", "danger")
        return redirect(url_for("prestamos"))

    try:
        cursor = conexion.cursor()

        cursor.execute("SELECT id_prod, cantidad, estado FROM prestamos WHERE id_prestamo=%s", (id_prestamo,))
        pr = cursor.fetchone()

        if not pr:
            flash("Préstamo no encontrado", "danger")
            return redirect(url_for("prestamos"))

        id_prod, cantidad, estado_actual = pr

        if estado_actual != "pendiente":
            flash("Este préstamo ya fue devuelto", "warning")
            return redirect(url_for("prestamos"))

        # Actualizar estado del préstamo
        cursor.execute("UPDATE prestamos SET estado=%s WHERE id_prestamo=%s", (estado, id_prestamo))
        # Devolver stock
        cursor.execute("UPDATE producto SET cantidad = cantidad + %s WHERE id_prod=%s", (cantidad, id_prod))

        conexion.commit()
        cursor.close()

        # 🔹 Enviar notificación al usuario
        notificacion_devolucion(id_prestamo)

        flash("Producto devuelto correctamente y correo enviado", "success")

    except Exception as e:
        conexion.rollback()
        flash(f"Error al registrar la devolución: {e}", "danger")
    finally:
        desconectar(conexion)

    return redirect(url_for("prestamos"))

# ---------- LOGOUT ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == '__main__':
    app.run(host="172.20.10.2", port=5000, debug=True)