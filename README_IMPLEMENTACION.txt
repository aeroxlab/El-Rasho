EL RASHO - Sistema Python + Render
===================================

Contenido del paquete:
- app.py: backend Flask completo.
- templates/: pantallas HTML.
- static/css/styles.css: diseño responsive rojo/amarillo/negro estilo El Rasho.
- static/js/app.js: modales, copiar número, loading de botones.
- requirements.txt: librerías necesarias.
- render.yaml: configuración para Render.

Acceso inicial:
Usuario admin maestro: 73221820
Contraseña: jdiazg20

Flujo principal:
1. Aparece logo animado El Rasho.
2. Luego aparece el login único.
3. Admin entra y puede crear pasajeros y conductores.
4. Conductores pueden crear sus propios pasajeros.
5. Pasajeros ven sus carreras, total, QR de pago, PDF y link público.

Roles:
- Admin: controla todo, pasajeros propios, conductores, carreras, pagos y QR.
- Conductor: controla solo sus pasajeros, carreras y QR propio.
- Pasajero: ve su deuda; si está como editor limitado puede modificar origen, destino y precio.

QR y pagos:
- El admin configura su QR para sus propios clientes.
- Cada conductor configura su propio QR para sus propios pasajeros.
- Si el pasajero pertenece al admin, ve el QR del admin.
- Si pertenece a un conductor, ve el QR del conductor.

Instalación local:
1. Instalar Python 3.11.
2. Entrar a la carpeta del proyecto.
3. Ejecutar: pip install -r requirements.txt
4. Ejecutar: python app.py
5. Abrir: http://127.0.0.1:5000

Despliegue en Render:
1. Sube esta carpeta a GitHub.
2. En Render crea un nuevo Web Service conectado al repositorio.
3. Build Command: pip install -r requirements.txt
4. Start Command: gunicorn app:app
5. Variable SECRET_KEY: Render puede generarla.
6. Si quieres usar PostgreSQL, crea una base PostgreSQL en Render y agrega DATABASE_URL al servicio.

Nota importante:
La versión funciona con SQLite por defecto para pruebas. Para producción real conviene usar PostgreSQL en Render para no perder datos al redeploy. Los QR se guardan en instance/uploads; render.yaml incluye un disco persistente para esa carpeta.
