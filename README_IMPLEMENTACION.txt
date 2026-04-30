EL RASHO - PYTHON + RENDER V2

Cambios integrados:
- Login único con animación inicial letra por letra, destello de rayo y auto rojo armado antes de mostrar login.
- Admin maestro interno: usuario 73221820 / contraseña jdiazg20. Nombre interno actualizado a Jorge Diaz.
- Se eliminó el mensaje de bienvenida tipo "Admin Maestro El Rasho".
- Panel admin/conductor más ordenado: pasajeros primero, luego movimientos, luego conductores y pagos.
- Usuario y contraseña pueden generarse automáticamente si se dejan vacíos.
- Pasajeros y conductores tienen botón eliminar con confirmación sensible.
- Movimientos/carreras tienen opción editar y eliminar.
- Botón Adelanto en pasajero: registra monto y lo descuenta del total pendiente.
- Link público muestra animación previa antes de enseñar el detalle.
- WhatsApp envía: Hola, te comparto el detalle de tus carreras: [link]. Total pendiente: *S/ XX.XX*
- PDF/ticket rediseñado más profesional, con nombre del cliente, subtotal, adelanto descontado y total final.
- Se quitó “responsable de cobro” del link público y PDF.
- QR/pagos por propietario: admin y cada conductor pueden configurar su propio QR.
- Al subir QR permite ajustar/recortar desde la pantalla antes de guardar.

PARA ACTUALIZAR EN GITHUB:
Sube/reemplaza TODO el contenido del proyecto:
app.py
requirements.txt
runtime.txt
render.yaml
README_IMPLEMENTACION.txt
templates/
static/
instance/uploads/.gitkeep

EN RENDER:
Build Command:
pip install -r requirements.txt

Start Command:
gunicorn app:app

Si ya está creado el servicio, solo sube cambios a GitHub y Render hará redeploy automático.
