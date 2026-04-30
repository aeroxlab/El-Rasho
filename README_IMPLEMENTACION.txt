EL RASHO - VERSION FINAL AJUSTADA

Usuario maestro:
Usuario: 73221820
Contraseña: jdiazg20
Nombre visible: Jorge Diaz

Ajustes incluidos:
- Intro solo con letras EL RASHO, humo y destello/rayo.
- Estilo de letra preparado para Overseer con fallback si el navegador no tiene esa fuente.
- Sin carro en la animación.
- Sin texto inferior en la intro.
- Sin mensaje de bienvenida al entrar.
- Usuario/contraseña automáticos si se dejan vacíos al crear pasajeros o conductores.
- Botón eliminar para pasajeros/conductores.
- Botón adelanto por pasajero.
- Adelantos descuentan del total pendiente.
- Movimientos debajo de pasajeros y antes de conductores.
- Eliminar carrera desde movimientos.
- WhatsApp con formato:
  Hola, te comparto el detalle de tus carreras:
  [Link público].
  Total pendiente: *S/ XX.XX*
- PDF/ticket más profesional con adelantos y total final.

Render:
Build Command:
pip install -r requirements.txt

Start Command:
gunicorn app:app


Ajuste adicional:
- Tarjeta temporal de acceso creado con iconos, copiar usuario, copiar contraseña y enviar datos por WhatsApp.


Ajuste final:
- Mensaje WhatsApp de acceso simplificado sin texto extra final.


Ajuste final:
- WhatsApp de acceso con salto de línea antes del link.
