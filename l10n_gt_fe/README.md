# Factura Electrónica Guatemala - Infile (Odoo 17)

Integra facturas, notas de crédito/débito, facturas cambiarias, facturas
especiales y exportaciones FEL con los servicios de firma, certificación,
anulación y representación gráfica de Infile.

## Configuración

1. En **Ajustes > Usuarios**, asigne el establecimiento FEL al vendedor.
2. En **Ajustes > Compañías > FEL / Infile**, configure usuario API, llave API,
   llave de firma, afiliación IVA, correo de copia y establecimientos.
3. En **Contabilidad > Configuración > Diarios**, active FEL únicamente en los
   diarios de ventas y seleccione el tipo de DTE y establecimiento.
4. En los grupos de impuestos configure el **Nombre corto FEL** (por ejemplo,
   `IVA`) y marque los grupos de retención cuando corresponda.

Las credenciales no se incluyen en el repositorio. Los endpoints productivos de
Infile se crean como parámetros de sistema con `noupdate="1"`, por lo que pueden
ser sustituidos sin que una actualización del módulo los sobrescriba.

## Flujo operativo

- Al contabilizar un documento de un diario FEL se valida y certifica el DTE.
- El identificador estable enviado a Infile permite reintentos idempotentes.
- Un documento certificado debe anularse con **Anular DTE** antes de cancelar el
  asiento contable.
- Los XML de emisión y anulación se conservan por separado; el PDF puede
  recuperarse desde la pestaña **FEL / Infile**.

La certificación requiere comunicación con servicios externos. Pruebe primero
la configuración y los tipos de DTE con las credenciales de implementación
proporcionadas por Infile antes de operar en producción.
