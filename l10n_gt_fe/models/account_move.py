# -*- coding: utf-8 -*-

import base64
import logging
from datetime import datetime, time, timedelta, timezone
from io import BytesIO
from zoneinfo import ZoneInfo

import requests
from dateutil.parser import parse
from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from xml.etree import ElementTree as ET


_logger = logging.getLogger(__name__)

INFILE_TIMEOUT = (10, 60)
GUATEMALA_TZ = ZoneInfo("America/Guatemala")
OUTGOING_MOVE_TYPES = ("out_invoice", "out_refund")
NOTE_TYPES = ("NCRE", "NDEB")


class AccountFePhrase(models.Model):
    _name = "account.fe.phrase"
    _description = "FEL Phrase"
    _order = "type, code, name"

    name = fields.Char(string="Name", required=True)
    description = fields.Char(string="Description")
    type = fields.Char(string="Type", required=True)
    code = fields.Char(string="Code", required=True)


class AccountMove(models.Model):
    _inherit = "account.move"

    partner_type = fields.Selection(
        string="Tipo de documento",
        related="partner_id.partner_type",
        readonly=True,
    )
    partner_vat = fields.Char(
        string="NIT / Identificación",
        compute="_compute_partner_vat",
    )
    is_fel = fields.Boolean(string="FEL", related="journal_id.active_fel")
    fe_type = fields.Selection(
        string="Tipo de DTE",
        related="journal_id.fe_type",
        readonly=True,
    )
    fe_phrase_ids = fields.Many2many(
        "account.fe.phrase",
        string="Frases FEL",
        default=lambda self: self.env.company.fe_phrase_ids,
    )

    process_status = fields.Selection(
        [
            ("process", "En proceso"),
            ("ok", "Certificado"),
            ("fail", "Fallido"),
            ("cancel", "Anulado"),
        ],
        string="Estado FEL",
        copy=False,
        readonly=True,
    )
    fe_errors = fields.Text(string="Errores FEL", copy=False, readonly=True)
    no_acceso = fields.Char(
        string="Identificador Infile",
        copy=False,
        readonly=True,
        help="Identificador idempotente enviado a Infile para evitar certificaciones duplicadas.",
    )

    fe_uuid = fields.Char(string="UUID FEL", readonly=True, copy=False)
    fe_serie = fields.Char(string="Serie FEL", readonly=True, copy=False)
    fe_number = fields.Char(string="Número FEL", readonly=True, copy=False)
    fe_certification_date = fields.Datetime(
        string="Fecha de certificación",
        readonly=True,
        copy=False,
    )
    certificador_fel = fields.Char(
        string="Certificador FEL",
        readonly=True,
        copy=False,
    )

    arch_xml = fields.Text(
        string="Contenido XML certificado",
        copy=False,
        readonly=True,
    )
    sent_arch_xml = fields.Text(
        string="XML enviado",
        copy=False,
        readonly=True,
    )
    xml_request = fields.Text(string="XML solicitado", copy=False, readonly=True)
    xml_response = fields.Text(string="XML de respuesta", copy=False, readonly=True)
    xml_response_cancel = fields.Text(
        string="Contenido XML de anulación",
        copy=False,
        readonly=True,
    )

    fe_xml_file = fields.Binary(
        string="XML certificado",
        copy=False,
        attachment=True,
    )
    fe_xml_file_name = fields.Char(
        string="Nombre XML certificado",
        copy=False,
        readonly=True,
    )
    fe_pdf_file = fields.Binary(
        string="Representación gráfica",
        copy=False,
        attachment=True,
    )
    fe_pdf_file_name = fields.Char(
        string="Nombre PDF",
        copy=False,
        readonly=True,
    )
    fe_cancel_xml_file = fields.Binary(
        string="XML de anulación",
        copy=False,
        attachment=True,
    )
    fe_cancel_xml_file_name = fields.Char(
        string="Nombre XML de anulación",
        copy=False,
        readonly=True,
    )

    complement_ids = fields.One2many(
        "account.move.complement",
        "move_id",
        string="Retenciones de factura especial",
        copy=True,
    )
    third_party_account_ids = fields.One2many(
        "charge.third.party.account",
        "move_id",
        string="Cobros por cuenta ajena",
        copy=True,
    )
    fe_count_payment = fields.Integer(string="Número de abonos", default=1)
    fe_payment_frequency = fields.Integer(string="Frecuencia (días)", default=1)
    fe_payment_line_ids = fields.One2many(
        "account.move.payment",
        "move_id",
        string="Abonos",
        copy=True,
    )
    fe_use_new_vat = fields.Boolean(
        string="Facturar a una identificación diferente",
        help="Use un receptor distinto del contacto de la factura.",
        copy=False,
    )
    fe_new_vat_id = fields.Many2one(
        "res.partner",
        string="Receptor FEL",
        help="Contacto cuya identificación se enviará como receptor del DTE.",
        copy=False,
        check_company=True,
    )
    rel_establishment_user = fields.Many2one(
        "res.company.establishment",
        string="Establecimiento del vendedor",
        related="invoice_user_id.fe_establishment_id",
    )

    motivo_fel = fields.Char(string="Motivo del ajuste FEL")
    factura_original_id = fields.Many2one(
        "account.move",
        string="Documento FEL original",
        copy=False,
        check_company=True,
        domain="[('move_type', '=', 'out_invoice'), ('process_status', '=', 'ok')]",
    )
    tipo_gasto = fields.Selection(
        [
            ("mixto", "Mixto"),
            ("compra", "Compra/Bien"),
            ("servicio", "Servicio"),
            ("importacion", "Importación/Exportación"),
            ("combustible", "Combustible"),
        ],
        string="Tipo de gasto",
        default="mixto",
    )
    consignatario_fel = fields.Many2one(
        "res.partner",
        string="Consignatario FEL",
        check_company=True,
    )
    comprador_fel = fields.Many2one(
        "res.partner",
        string="Comprador FEL",
        check_company=True,
    )
    exportador_fel = fields.Many2one(
        "res.partner",
        string="Exportador FEL",
        check_company=True,
    )
    incoterm_fel = fields.Char(string="INCOTERM FEL", default="FOB")
    frase_exento_fel = fields.Integer(string="Escenario de exención FEL")
    active_contingencia = fields.Boolean(
        string="Contingencia FEL",
        default=False,
        copy=False,
    )
    fe_exhangerate = fields.Char(string="Tasa de cambio", size=16, default="1.00")

    # Campos heredados conservados para compatibilidad con integraciones existentes.
    documento_xml_fel = fields.Binary(string="Documento XML FEL", copy=False)
    documento_xml_fel_name = fields.Char(
        string="Nombre documento XML FEL",
        default="documento_xml_fel.xml",
    )
    resultado_xml_fel = fields.Binary(string="Resultado XML FEL", copy=False)
    resultado_xml_fel_name = fields.Char(
        string="Nombre resultado XML FEL",
        default="resultado_xml_fel.xml",
    )
    pdf_fel = fields.Binary(string="PDF FEL", copy=False)
    pdf_fel_name = fields.Char(string="Nombre PDF FEL", default="pdf_fel.pdf")
    firma_fel = fields.Char(string="UUID FEL (legado)", copy=False)
    serie_fel = fields.Char(string="Serie FEL (legado)", copy=False)
    numero_fel = fields.Char(string="Número FEL (legado)", copy=False)
    fel_date = fields.Char(string="Fecha certificación (legado)", copy=False)

    @api.depends(
        "partner_id.vat",
        "fe_use_new_vat",
        "fe_new_vat_id.vat",
    )
    def _compute_partner_vat(self):
        for move in self:
            receiver = move.fe_new_vat_id if move.fe_use_new_vat else move.partner_id
            move.partner_vat = receiver.vat or False

    @api.onchange("journal_id")
    def _onchange_fel_journal(self):
        if self.fe_type == "FESP" and not self.complement_ids:
            self.complement_ids = [
                (0, 0, {"complement": "IVA"}),
                (0, 0, {"complement": "ISR"}),
            ]

    def _is_outgoing_fel(self):
        self.ensure_one()
        return bool(
            self.move_type in OUTGOING_MOVE_TYPES
            and self.journal_id.active_fel
            and self.fe_type
            and self.fe_type != "OTRO"
        )

    @staticmethod
    def _normalize_identifier(value):
        return (value or "").replace("-", "").replace(" ", "").upper()

    @staticmethod
    def _is_infile_success(data):
        result = data.get("resultado")
        return result is True or str(result).strip().lower() in (
            "true",
            "1",
            "si",
            "sí",
        )

    @staticmethod
    def _format_infile_errors(data):
        errors = data.get("descripcion_errores") or data.get("errores") or []
        if isinstance(errors, dict):
            errors = [errors]
        if isinstance(errors, str):
            errors = [errors]
        messages = []
        for error in errors:
            if isinstance(error, dict):
                message = (
                    error.get("mensaje_error")
                    or error.get("mensaje")
                    or error.get("descripcion")
                    or str(error)
                )
            else:
                message = str(error)
            if message:
                messages.append(message)
        return "\n".join(
            "%s. %s" % (index, message)
            for index, message in enumerate(messages, start=1)
        ) or _("Infile rejected the request without returning an error description.")

    @staticmethod
    def _address(partner):
        return (
            " ".join(
                value.strip()
                for value in (partner.street, partner.street2)
                if value and value.strip()
            )
            or "CIUDAD"
        )

    @staticmethod
    def _xml_text(xml_value):
        if isinstance(xml_value, bytes):
            return xml_value.decode("utf-8")
        return xml_value or ""

    def _receiver_partner(self):
        self.ensure_one()
        return self.fe_new_vat_id if self.fe_use_new_vat else self.partner_id

    def _origin_fel_move(self):
        self.ensure_one()
        return self.factura_original_id or self.reversed_entry_id

    def _validate_fel_document(self):
        self.ensure_one()
        if not self._is_outgoing_fel():
            return

        company = self.company_id
        establishment = self.journal_id.fe_establishment_id
        receiver = self._receiver_partner()
        today = fields.Date.context_today(self)
        invoice_date = self.invoice_date or today

        company._get_headers()
        company._get_sign_token()

        missing = []
        if not company.vat:
            missing.append(_("company NIT"))
        if not company.country_id.code:
            missing.append(_("company country"))
        if not establishment:
            missing.append(_("FEL establishment"))
        else:
            if not establishment.fe_code:
                missing.append(_("establishment code"))
            if not establishment.fe_tradename:
                missing.append(_("establishment trade name"))
            if not establishment.fe_tradename_street and not company.street:
                missing.append(_("establishment address"))
            if not establishment.fe_tradename_city and not company.city:
                missing.append(_("establishment municipality"))
        if not receiver:
            missing.append(_("receiver"))
        else:
            if not receiver.name:
                missing.append(_("receiver name"))
            if not receiver.vat:
                missing.append(_("receiver identification"))

        product_lines = self.invoice_line_ids.filtered(
            lambda line: line.display_type == "product" and line.price_total > 0
        )
        if not product_lines:
            missing.append(_("at least one invoice line with a positive total"))

        if self.fe_type in NOTE_TYPES:
            origin = self._origin_fel_move()
            if not origin or not origin.fe_uuid:
                missing.append(_("certified original FEL document"))
            if not (self.motivo_fel or self.ref):
                missing.append(_("adjustment reason"))

        if self.fe_type == "FAEX":
            if not establishment or not establishment.export_code:
                missing.append(_("exporter code"))
            if not receiver.country_id.code:
                missing.append(_("receiver country"))
            if not self.incoterm_fel:
                missing.append(_("INCOTERM"))

        if self.fe_type == "FCAM":
            if self.fe_count_payment <= 0:
                missing.append(_("number of payments greater than zero"))
            if self.fe_payment_frequency <= 0:
                missing.append(_("payment frequency greater than zero"))

        if missing:
            raise ValidationError(
                _("Complete the following FEL information before posting:\n- %s")
                % "\n- ".join(missing)
            )
        if invoice_date > today:
            raise ValidationError(_("The FEL issue date cannot be in the future."))
        if invoice_date < today - timedelta(days=5):
            raise ValidationError(
                _("The FEL issue date cannot be more than 5 days old.")
            )

    def action_post(self):
        fel_moves = self.filtered(lambda move: move._is_outgoing_fel())
        if len(fel_moves) > 1:
            raise UserError(
                _(
                    "Post FEL documents one at a time to keep certification transactions consistent."
                )
            )
        for move in fel_moves:
            if not move.invoice_date:
                move.invoice_date = fields.Date.context_today(move)
            move._validate_fel_document()

        result = super().action_post()
        for move in fel_moves:
            move.send_invoice()
        return result

    def compute_fe_payment_line(self):
        self.ensure_one()
        if self.fe_type != "FCAM":
            return False
        if self.fe_count_payment <= 0 or self.fe_payment_frequency <= 0:
            raise ValidationError(
                _("The number of payments and frequency must be greater than zero.")
            )
        if not self.amount_total:
            raise ValidationError(_("The invoice total cannot be zero."))

        due_date = self.invoice_date or fields.Date.context_today(self)
        amount = self.currency_id.round(self.amount_total / self.fe_count_payment)
        remaining = self.amount_total
        commands = [(5, 0, 0)]
        for sequence in range(1, self.fe_count_payment + 1):
            due_date += timedelta(days=self.fe_payment_frequency)
            installment = remaining if sequence == self.fe_count_payment else amount
            remaining -= installment
            commands.append(
                (
                    0,
                    0,
                    {
                        "sequence": sequence,
                        "date": due_date,
                        "amount": installment,
                    },
                )
            )
        self.fe_payment_line_ids = commands
        return True

    def _line_tax_values(self, line, ratio, export_document=False):
        self.ensure_one()
        tax_values = {}
        taxes = line.tax_ids.filtered(lambda tax: not tax.tax_group_id.withhold)
        if not taxes:
            return tax_values

        discounted_price = line.price_unit * (1 - (line.discount / 100.0))
        result = taxes.compute_all(
            discounted_price,
            currency=line.currency_id,
            quantity=line.quantity,
            product=line.product_id,
            partner=self._receiver_partner(),
            is_refund=line.is_refund,
        )
        tax_by_id = {tax.id: tax for tax in taxes.flatten_taxes_hierarchy()}
        for tax_data in result.get("taxes", []):
            tax = tax_by_id.get(tax_data["id"])
            if not tax or tax.tax_group_id.withhold:
                continue
            shortname = (
                tax.tax_group_id.shortname or tax.description or tax.name or "IVA"
            )
            values = tax_values.setdefault(
                shortname,
                {
                    "base": 0.0,
                    "amount": 0.0,
                    "code": "2" if export_document else "1",
                },
            )
            values["base"] += abs(tax_data.get("base", 0.0) * ratio)
            values["amount"] += abs(tax_data.get("amount", 0.0) * ratio)
        return tax_values

    def _append_third_party_complement(self, complementos):
        complemento = ET.SubElement(
            complementos,
            "dte:Complemento",
            {
                "IDComplemento": "CobroXCuentaAjena",
                "NombreComplemento": "CobroXCuentaAjena",
                "URIComplemento": "http://www.sat.gob.gt/face2/CobroXCuentaAjena/0.1.0",
            },
        )
        collection = ET.SubElement(
            complemento,
            "cca:CobroXCuentaAjena",
            {
                "xmlns:cca": "http://www.sat.gob.gt/face2/CobroXCuentaAjena/0.1.0",
                "Version": "1",
                "xsi:schemaLocation": "http://www.sat.gob.gt/face2/CobroXCuentaAjena/0.1.0 schema.xsd",
            },
        )
        for account in self.third_party_account_ids:
            item = ET.SubElement(collection, "cca:ItemCuentaAjena")
            ET.SubElement(item, "cca:NITtercero").text = self._normalize_identifier(
                account.vat
            )
            ET.SubElement(item, "cca:NumeroDocumento").text = account.number
            ET.SubElement(item, "cca:FechaDocumento").text = fields.Date.to_string(
                account.date
            )
            ET.SubElement(item, "cca:Descripcion").text = account.name
            ET.SubElement(item, "cca:BaseImponible").text = (
                "%.2f" % account.amount_untaxes
            )
            ET.SubElement(item, "cca:MontoCobroDAI").text = "%.2f" % account.amount_dai
            ET.SubElement(item, "cca:MontoCobroIVA").text = (
                "%.2f" % account.amount_taxes
            )
            ET.SubElement(item, "cca:MontoCobroOtros").text = (
                "%.2f" % account.other_amount
            )
            ET.SubElement(item, "cca:MontoCobroTotal").text = (
                "%.2f" % account.amount_total
            )

    def _append_document_complement(self, complementos):
        if self.fe_type in NOTE_TYPES:
            origin = self._origin_fel_move()
            complemento = ET.SubElement(
                complementos,
                "dte:Complemento",
                {
                    "IDComplemento": "ReferenciasNota",
                    "NombreComplemento": (
                        "Nota de Credito"
                        if self.fe_type == "NCRE"
                        else "Nota de Debito"
                    ),
                    "URIComplemento": "http://www.sat.gob.gt/face2/ComplementoReferenciaNota/0.1.0",
                },
            )
            ET.SubElement(
                complemento,
                "cno:ReferenciasNota",
                {
                    "xmlns:cno": "http://www.sat.gob.gt/face2/ComplementoReferenciaNota/0.1.0",
                    "FechaEmisionDocumentoOrigen": fields.Date.to_string(
                        origin.invoice_date
                    ),
                    "MotivoAjuste": self.motivo_fel or self.ref,
                    "NumeroAutorizacionDocumentoOrigen": origin.fe_uuid,
                    "NumeroDocumentoOrigen": origin.fe_number or origin.name,
                    "SerieDocumentoOrigen": origin.fe_serie,
                    "Version": "0.0",
                },
            )
        elif self.fe_type == "FESP":
            complemento = ET.SubElement(
                complementos,
                "dte:Complemento",
                {
                    "IDComplemento": "RetencionesFacturaEspecial",
                    "NombreComplemento": "RetencionesFacturaEspecial",
                    "URIComplemento": "http://www.sat.gob.gt/face2/ComplementoFacturaEspecial/0.1.0",
                },
            )
            retenciones = ET.SubElement(
                complemento,
                "cfe:RetencionesFacturaEspecial",
                {
                    "xmlns:cfe": "http://www.sat.gob.gt/face2/ComplementoFacturaEspecial/0.1.0",
                    "Version": "1",
                    "xsi:schemaLocation": "http://www.sat.gob.gt/face2/ComplementoFacturaEspecial/0.1.0",
                },
            )
            amounts = {line.complement: line.amount for line in self.complement_ids}
            ET.SubElement(retenciones, "cfe:RetencionISR").text = "%.2f" % amounts.get(
                "ISR", 0.0
            )
            ET.SubElement(retenciones, "cfe:RetencionIVA").text = "%.2f" % amounts.get(
                "IVA", 0.0
            )
            total_less_withholdings = self.amount_total - sum(amounts.values())
            ET.SubElement(retenciones, "cfe:TotalMenosRetenciones").text = (
                "%.2f" % total_less_withholdings
            )
        elif self.fe_type == "FCAM":
            if not self.fe_payment_line_ids:
                self.compute_fe_payment_line()
            complemento = ET.SubElement(
                complementos,
                "dte:Complemento",
                {
                    "IDComplemento": "Cambiaria",
                    "NombreComplemento": "Cambiaria",
                    "URIComplemento": "http://www.sat.gob.gt/dte/fel/CompCambiaria/0.1.0",
                },
            )
            abonos = ET.SubElement(
                complemento,
                "cfc:AbonosFacturaCambiaria",
                {
                    "xmlns:cfc": "http://www.sat.gob.gt/dte/fel/CompCambiaria/0.1.0",
                    "Version": "1",
                    "xsi:schemaLocation": "http://www.sat.gob.gt/dte/fel/CompCambiaria/0.1.0",
                },
            )
            for payment in self.fe_payment_line_ids.sorted("sequence"):
                abono = ET.SubElement(abonos, "cfc:Abono")
                ET.SubElement(abono, "cfc:NumeroAbono").text = str(payment.sequence)
                ET.SubElement(
                    abono, "cfc:FechaVencimiento"
                ).text = fields.Date.to_string(payment.date)
                ET.SubElement(abono, "cfc:MontoAbono").text = "%.2f" % payment.amount
        elif self.fe_type == "FAEX":
            consignee = self.consignatario_fel or self.partner_id
            buyer = self.comprador_fel or self.partner_id
            exporter = self.exportador_fel or self.company_id.partner_id
            complemento = ET.SubElement(
                complementos,
                "dte:Complemento",
                {
                    "IDComplemento": "Exportacion",
                    "NombreComplemento": "Complemento_Exportacion",
                    "URIComplemento": "http://www.sat.gob.gt/face2/ComplementoExportaciones/0.1.0",
                },
            )
            exportacion = ET.SubElement(
                complemento,
                "cex:Exportacion",
                {
                    "xmlns:cex": "http://www.sat.gob.gt/face2/ComplementoExportaciones/0.1.0",
                    "Version": "1",
                    "xsi:schemaLocation": "http://www.sat.gob.gt/face2/ComplementoExportaciones/0.1.0",
                },
            )
            ET.SubElement(
                exportacion, "cex:NombreConsignatarioODestinatario"
            ).text = consignee.name
            ET.SubElement(
                exportacion, "cex:DireccionConsignatarioODestinatario"
            ).text = self._address(consignee)
            ET.SubElement(
                exportacion, "cex:CodigoConsignatarioODestinatario"
            ).text = self._normalize_identifier(consignee.vat)
            ET.SubElement(exportacion, "cex:NombreComprador").text = buyer.name
            ET.SubElement(
                exportacion, "cex:CodigoComprador"
            ).text = self._normalize_identifier(buyer.vat)
            ET.SubElement(exportacion, "cex:OtraReferencia").text = (
                self.ref or "EXPORTACION"
            )
            ET.SubElement(exportacion, "cex:INCOTERM").text = self.incoterm_fel.upper()
            ET.SubElement(exportacion, "cex:NombreExportador").text = exporter.name
            ET.SubElement(
                exportacion, "cex:CodigoExportador"
            ).text = self.journal_id.fe_establishment_id.export_code

    def _xml(self):
        self.ensure_one()
        self._validate_fel_document()

        invoice_date = self.invoice_date or fields.Date.context_today(self)
        issue_datetime = datetime.combine(
            invoice_date, time(0, 0, 1), tzinfo=GUATEMALA_TZ
        )
        company = self.company_id
        establishment = self.journal_id.fe_establishment_id
        receiver = self._receiver_partner()
        origin = self._origin_fel_move()
        export_document = self.fe_type == "FAEX" or bool(
            self.fe_type == "NCRE" and origin and origin.fe_type == "FAEX"
        )

        root = ET.Element(
            "dte:GTDocumento",
            {
                "xmlns:ds": "http://www.w3.org/2000/09/xmldsig#",
                "xmlns:dte": "http://www.sat.gob.gt/dte/fel/0.2.0",
                "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                "Version": "0.1",
            },
        )
        sat = ET.SubElement(root, "dte:SAT", {"ClaseDocumento": "dte"})
        dte = ET.SubElement(sat, "dte:DTE", {"ID": "DatosCertificados"})
        datos_emision = ET.SubElement(dte, "dte:DatosEmision", {"ID": "DatosEmision"})

        general_values = {
            "CodigoMoneda": self.currency_id.name,
            "FechaHoraEmision": issue_datetime.isoformat(),
            "Tipo": "FACT" if self.fe_type == "FAEX" else self.fe_type,
        }
        if export_document:
            general_values["Exp"] = "SI"
        ET.SubElement(datos_emision, "dte:DatosGenerales", general_values)

        emisor_values = {
            "AfiliacionIVA": company.fe_vat_affiliation,
            "CodigoEstablecimiento": str(establishment.fe_code),
            "NITEmisor": self._normalize_identifier(company.vat),
            "NombreComercial": establishment.fe_tradename,
            "NombreEmisor": company.name,
        }
        issuer_email = company.email or company.fe_other_email
        if issuer_email:
            emisor_values["CorreoEmisor"] = issuer_email
        emisor = ET.SubElement(datos_emision, "dte:Emisor", emisor_values)
        issuer_address = ET.SubElement(emisor, "dte:DireccionEmisor")
        ET.SubElement(issuer_address, "dte:Direccion").text = (
            establishment.fe_tradename_street or self._address(company.partner_id)
        )
        ET.SubElement(issuer_address, "dte:CodigoPostal").text = company.zip or "01001"
        ET.SubElement(issuer_address, "dte:Municipio").text = (
            establishment.fe_tradename_city or company.city
        )
        ET.SubElement(issuer_address, "dte:Departamento").text = (
            establishment.fe_tradename_state_id.name
            or company.state_id.name
            or "Guatemala"
        )
        ET.SubElement(issuer_address, "dte:Pais").text = company.country_id.code

        receiver_values = {
            "IDReceptor": self._normalize_identifier(receiver.vat),
            "NombreReceptor": receiver.name,
        }
        receiver_email = receiver.email or company.fe_other_email
        if receiver_email:
            receiver_values["CorreoReceptor"] = receiver_email
        if self.fe_type == "FESP":
            receiver_values["TipoEspecial"] = "CUI"
        elif receiver.partner_type in ("CUI", "EXT"):
            receiver_values["TipoEspecial"] = receiver.partner_type
        receptor = ET.SubElement(datos_emision, "dte:Receptor", receiver_values)
        receiver_address = ET.SubElement(receptor, "dte:DireccionReceptor")
        ET.SubElement(receiver_address, "dte:Direccion").text = self._address(receiver)
        ET.SubElement(receiver_address, "dte:CodigoPostal").text = (
            receiver.zip or "01001"
        )
        ET.SubElement(receiver_address, "dte:Municipio").text = (
            receiver.city or "Guatemala"
        )
        ET.SubElement(receiver_address, "dte:Departamento").text = (
            receiver.state_id.name or "Guatemala"
        )
        ET.SubElement(receiver_address, "dte:Pais").text = (
            receiver.country_id.code or "GT"
        )

        if self.fe_phrase_ids:
            frases = ET.SubElement(datos_emision, "dte:Frases")
            for phrase in self.fe_phrase_ids.sorted(
                lambda item: (item.type, item.code)
            ):
                ET.SubElement(
                    frases,
                    "dte:Frase",
                    {"CodigoEscenario": phrase.code, "TipoFrase": phrase.type},
                )

        items = ET.SubElement(datos_emision, "dte:Items")
        positive_lines = self.invoice_line_ids.filtered(
            lambda line: line.display_type == "product" and line.price_total > 0
        )
        negative_lines = self.invoice_line_ids.filtered(
            lambda line: line.display_type == "product" and line.price_total < 0
        )
        total_negative = sum(
            abs(line.price_unit * line.quantity * (1 - line.discount / 100.0))
            for line in negative_lines
        )
        positive_total = sum(
            line.price_unit * line.quantity * (1 - line.discount / 100.0)
            for line in positive_lines
        )
        if total_negative >= positive_total:
            raise ValidationError(
                _(
                    "Negative invoice lines cannot equal or exceed the positive FEL line total."
                )
            )
        tax_totals = {}
        grand_total = 0.0

        for sequence, line in enumerate(positive_lines, start=1):
            discounted_line_price = (
                line.price_unit * line.quantity * (1 - line.discount / 100.0)
            )
            fixed_discount = (
                total_negative * (discounted_line_price / positive_total)
                if total_negative and positive_total
                else 0.0
            )
            ratio = (
                max(discounted_line_price - fixed_discount, 0.0) / discounted_line_price
                if discounted_line_price
                else 1.0
            )
            line_total = line.price_total * ratio
            percent_discount = line.price_unit * line.quantity * (line.discount / 100.0)
            discount = percent_discount + fixed_discount
            product_type = line.product_id.type if line.product_id else "service"
            item = ET.SubElement(
                items,
                "dte:Item",
                {
                    "BienOServicio": "B"
                    if product_type in ("consu", "product")
                    else "S",
                    "NumeroLinea": str(sequence),
                },
            )
            ET.SubElement(item, "dte:Cantidad").text = "%.6f" % abs(line.quantity)
            unit_name = line.product_uom_id.name if line.product_uom_id else "UNI"
            ET.SubElement(item, "dte:UnidadMedida").text = unit_name.upper()[:3]
            ET.SubElement(item, "dte:Descripcion").text = (
                line.name or line.product_id.display_name or _("Product / Service")
            )
            ET.SubElement(item, "dte:PrecioUnitario").text = "%.6f" % abs(
                line.price_unit
            )
            ET.SubElement(item, "dte:Precio").text = "%.6f" % abs(
                line.price_unit * line.quantity
            )
            ET.SubElement(item, "dte:Descuento").text = "%.6f" % abs(discount)

            line_taxes = (
                {}
                if self.fe_type == "NABN"
                else self._line_tax_values(
                    line,
                    ratio,
                    export_document=export_document,
                )
            )
            if line_taxes:
                impuestos = ET.SubElement(item, "dte:Impuestos")
                for shortname, values in line_taxes.items():
                    impuesto = ET.SubElement(impuestos, "dte:Impuesto")
                    ET.SubElement(impuesto, "dte:NombreCorto").text = shortname
                    ET.SubElement(impuesto, "dte:CodigoUnidadGravable").text = values[
                        "code"
                    ]
                    ET.SubElement(impuesto, "dte:MontoGravable").text = (
                        "%.2f" % values["base"]
                    )
                    ET.SubElement(impuesto, "dte:MontoImpuesto").text = (
                        "%.2f" % values["amount"]
                    )
                    tax_totals[shortname] = (
                        tax_totals.get(shortname, 0.0) + values["amount"]
                    )
            ET.SubElement(item, "dte:Total").text = "%.2f" % line_total
            grand_total += line_total

        totals = ET.SubElement(datos_emision, "dte:Totales")
        if tax_totals:
            total_taxes = ET.SubElement(totals, "dte:TotalImpuestos")
            for shortname, amount in tax_totals.items():
                ET.SubElement(
                    total_taxes,
                    "dte:TotalImpuesto",
                    {
                        "NombreCorto": shortname,
                        "TotalMontoImpuesto": "%.2f" % amount,
                    },
                )
        ET.SubElement(totals, "dte:GranTotal").text = "%.2f" % grand_total

        needs_document_complement = self.fe_type in (
            "FESP",
            "NDEB",
            "NCRE",
            "FCAM",
            "FAEX",
        )
        if self.third_party_account_ids or needs_document_complement:
            complementos = ET.SubElement(datos_emision, "dte:Complementos")
            if self.third_party_account_ids:
                self._append_third_party_complement(complementos)
            if needs_document_complement:
                self._append_document_complement(complementos)

        adenda = ET.SubElement(sat, "dte:Adenda")
        if self.fe_type == "FCAM":
            ET.SubElement(adenda, "auto-generated_for-wildcard")
        elif self.fe_type == "NABN" and origin:
            payment_term = origin.invoice_payment_term_id.name or "CONTADO"
            ET.SubElement(adenda, "tipopago").text = payment_term.upper()
            ET.SubElement(adenda, "factura_referencia").text = origin.name
        ET.SubElement(adenda, "cliente").text = self._normalize_identifier(receiver.vat)

        output = BytesIO()
        ET.ElementTree(root).write(output, encoding="UTF-8", xml_declaration=True)
        return output.getvalue()

    def _infile_post(self, url, payload, headers, operation):
        try:
            response = requests.post(
                url=url,
                json=payload,
                headers=headers,
                timeout=INFILE_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as error:
            _logger.exception("Infile %s request failed", operation)
            raise UserError(
                _(
                    "Could not communicate with Infile during %(operation)s: %(error)s",
                    operation=operation,
                    error=error,
                )
            ) from error
        except ValueError as error:
            _logger.exception("Infile %s returned invalid JSON", operation)
            raise UserError(
                _("Infile returned an invalid response during %s.") % operation
            ) from error
        if not isinstance(data, dict):
            raise UserError(
                _("Infile returned an unexpected response during %s.") % operation
            )
        return data

    def _sign_invoice(self, xml_b64, cancel=False):
        self.ensure_one()
        url = self.env["ir.config_parameter"].sudo().get_param("url.sign.webservice.fe")
        if not url:
            raise ValidationError(_("The Infile signing URL is not configured."))
        payload = self.company_id._get_sign_token()
        payload.update(
            {
                "codigo": str(self.journal_id.fe_establishment_id.fe_code),
                "archivo": xml_b64,
                "es_anulacion": "S" if cancel else "N",
            }
        )
        data = self._infile_post(
            url,
            payload,
            {"Content-Type": "application/json"},
            _("XML signing"),
        )
        if data.get("resultado") is False or not data.get("archivo"):
            raise UserError(self._format_infile_errors(data))
        return data["archivo"]

    def send_invoice(self):
        self.ensure_one()
        if not self._is_outgoing_fel():
            raise UserError(
                _("This document is not configured as an outgoing FEL document.")
            )
        if self.state != "posted":
            raise UserError(_("Post the invoice before certifying the DTE."))
        if self.process_status == "cancel":
            raise UserError(_("An annulled DTE cannot be certified again."))
        if self.process_status == "ok" and self.fe_uuid:
            return self._fel_notification(_("The DTE is already certified."))

        self._validate_fel_document()
        identifier = self.no_acceso or "ODOO-%s-%s" % (self.company_id.id, self.id)
        source_xml = self._xml()
        source_xml_b64 = base64.b64encode(source_xml).decode("ascii")
        self.write(
            {
                "no_acceso": identifier,
                "sent_arch_xml": source_xml.decode("utf-8"),
                "xml_request": source_xml.decode("utf-8"),
                "documento_xml_fel": source_xml_b64,
                "documento_xml_fel_name": "%s-solicitud.xml" % identifier,
                "process_status": "process",
                "fe_errors": False,
            }
        )

        signed_xml = self._sign_invoice(source_xml_b64)
        url = self.env["ir.config_parameter"].sudo().get_param("url.webservice.fe")
        if not url:
            raise ValidationError(_("The Infile certification URL is not configured."))
        headers = self.company_id._get_headers()
        headers["identificador"] = identifier
        data = self._infile_post(
            url,
            {
                "nit_emisor": self._normalize_identifier(self.company_id.vat),
                "correo_copia": self.partner_id.email
                or self.company_id.fe_other_email
                or "",
                "xml_dte": signed_xml,
            },
            headers,
            _("DTE certification"),
        )
        if not self._is_infile_success(data):
            error_message = self._format_infile_errors(data)
            self.write({"fe_errors": error_message, "process_status": "fail"})
            raise UserError(error_message)

        required_keys = ("xml_certificado", "fecha", "uuid", "serie", "numero")
        if any(not data.get(key) for key in required_keys):
            raise UserError(_("Infile returned an incomplete certification response."))
        encoded_xml = data["xml_certificado"]
        try:
            certified_xml = base64.b64decode(encoded_xml, validate=True)
            certified_xml_text = certified_xml.decode("utf-8")
            certification_date = parse(data["fecha"])
        except (TypeError, ValueError, UnicodeDecodeError) as error:
            raise UserError(_("Infile returned invalid certification data.")) from error

        serie = str(data["serie"])
        number = str(data["numero"])
        filename = "%s-%s.xml" % (serie, number)
        self.write(
            {
                "fe_uuid": data["uuid"],
                "fe_serie": serie,
                "fe_number": number,
                "fe_certification_date": fields.Datetime.to_string(
                    certification_date.astimezone(timezone.utc).replace(tzinfo=None)
                    if certification_date.tzinfo
                    else certification_date
                ),
                "certificador_fel": "INFILE",
                "fe_xml_file": encoded_xml,
                "fe_xml_file_name": filename,
                "resultado_xml_fel": encoded_xml,
                "resultado_xml_fel_name": filename,
                "arch_xml": certified_xml_text,
                "xml_response": certified_xml_text,
                "process_status": "ok",
                "fe_errors": False,
                "firma_fel": data["uuid"],
                "serie_fel": serie,
                "numero_fel": number,
                "fel_date": str(data["fecha"]),
            }
        )
        return self._fel_notification(
            _("DTE certified successfully."),
            notification_type="success",
        )

    def _cancellation_xml(self):
        self.ensure_one()
        invoice_date = self.invoice_date or fields.Date.context_today(self)
        issued_at = datetime.combine(invoice_date, time(0, 0, 1), tzinfo=GUATEMALA_TZ)
        cancelled_at = datetime.now(GUATEMALA_TZ).replace(microsecond=0)
        receiver = self._receiver_partner()
        root = ET.Element(
            "dte:GTAnulacionDocumento",
            {
                "xmlns:ds": "http://www.w3.org/2000/09/xmldsig#",
                "xmlns:dte": "http://www.sat.gob.gt/dte/fel/0.1.0",
                "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                "Version": "0.1",
            },
        )
        sat = ET.SubElement(root, "dte:SAT")
        annulment = ET.SubElement(sat, "dte:AnulacionDTE", {"ID": "DatosCertificados"})
        ET.SubElement(
            annulment,
            "dte:DatosGenerales",
            {
                "FechaEmisionDocumentoAnular": issued_at.isoformat(),
                "FechaHoraAnulacion": cancelled_at.isoformat(),
                "ID": "DatosAnulacion",
                "IDReceptor": self._normalize_identifier(receiver.vat),
                "MotivoAnulacion": self.motivo_fel or _("Annulment"),
                "NITEmisor": self._normalize_identifier(self.company_id.vat),
                "NumeroDocumentoAAnular": self.fe_uuid,
            },
        )
        output = BytesIO()
        ET.ElementTree(root).write(output, encoding="UTF-8", xml_declaration=True)
        return output.getvalue()

    def cancel_dte(self):
        self.ensure_one()
        if (
            not self._is_outgoing_fel()
            or self.process_status != "ok"
            or not self.fe_uuid
        ):
            raise UserError(
                _("Only a certified FEL document can be annulled in Infile.")
            )
        if self.state != "posted":
            raise UserError(
                _("The accounting document must be posted before FEL annulment.")
            )

        cancellation_xml = self._cancellation_xml()
        cancellation_b64 = base64.b64encode(cancellation_xml).decode("ascii")
        signed_xml = self._sign_invoice(cancellation_b64, cancel=True)
        url = (
            self.env["ir.config_parameter"].sudo().get_param("url.webservice.cancel.fe")
        )
        if not url:
            raise ValidationError(_("The Infile annulment URL is not configured."))
        headers = self.company_id._get_headers()
        headers["identificador"] = "%s-ANULACION" % (self.no_acceso or self.id)

        # Validate the local transition before the irreversible external request.
        super(AccountMove, self).button_cancel()
        data = self._infile_post(
            url,
            {
                "nit_emisor": self._normalize_identifier(self.company_id.vat),
                "correo_copia": self.partner_id.email
                or self.company_id.fe_other_email
                or "",
                "xml_dte": signed_xml,
            },
            headers,
            _("DTE annulment"),
        )
        if not self._is_infile_success(data):
            error_message = self._format_infile_errors(data)
            self.write({"fe_errors": error_message})
            raise UserError(error_message)

        encoded_xml = data.get("xml_certificado")
        try:
            cancellation_response = base64.b64decode(encoded_xml, validate=True).decode(
                "utf-8"
            )
        except (TypeError, ValueError, UnicodeDecodeError) as error:
            raise UserError(
                _("Infile returned an invalid annulment XML file.")
            ) from error
        filename = "ANULACION-%s.xml" % self.fe_uuid
        self.write(
            {
                "fe_cancel_xml_file": encoded_xml,
                "fe_cancel_xml_file_name": filename,
                "xml_response_cancel": cancellation_response,
                "process_status": "cancel",
                "fe_errors": False,
            }
        )
        return self._fel_notification(
            _("DTE annulled successfully."),
            notification_type="success",
        )

    def button_cancel(self):
        certified = self.filtered(
            lambda move: move._is_outgoing_fel() and move.process_status == "ok"
        )
        if certified:
            raise UserError(
                _(
                    "Annul the certified DTE in Infile before cancelling the accounting document."
                )
            )
        return super().button_cancel()

    def get_pdf(self):
        self.ensure_one()
        if not self.fe_uuid or self.process_status not in ("ok", "cancel"):
            raise UserError(_("The DTE must be certified before downloading its PDF."))
        url = "https://report.feel.com.gt/ingfacereport/ingfacereport_documento"
        try:
            response = requests.get(
                url,
                params={"uuid": self.fe_uuid},
                timeout=INFILE_TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException as error:
            _logger.exception("Infile PDF download failed")
            raise UserError(
                _("Could not download the PDF from Infile: %s") % error
            ) from error
        if not response.content.startswith(b"%PDF"):
            raise UserError(_("Infile did not return a valid PDF file."))

        filename = "%s-%s.pdf" % (self.fe_serie or "FEL", self.fe_number or self.id)
        encoded_pdf = base64.b64encode(response.content)
        self.write(
            {
                "fe_pdf_file": encoded_pdf,
                "fe_pdf_file_name": filename,
                "pdf_fel": encoded_pdf,
                "pdf_fel_name": filename,
            }
        )
        return self._fel_notification(
            _("PDF downloaded successfully."),
            notification_type="success",
        )

    @staticmethod
    def _fel_notification(message, notification_type="info"):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("FEL / Infile"),
                "message": message,
                "type": notification_type,
                "sticky": False,
            },
        }

    @staticmethod
    def pretty_xml(xml_bytes_or_str):
        try:
            xml_string = AccountMove._xml_text(xml_bytes_or_str)
            parser = etree.XMLParser(remove_blank_text=True)
            root = etree.fromstring(xml_string.encode("utf-8"), parser)
            return etree.tostring(root, pretty_print=True, encoding="unicode")
        except (ValueError, etree.XMLSyntaxError, UnicodeDecodeError) as error:
            return _("Error parsing XML: %s") % error


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    price_tax = fields.Monetary(
        string="Impuestos",
        compute="_compute_fel_amounts",
        currency_field="currency_id",
    )
    price_discount = fields.Monetary(
        string="Descuento",
        compute="_compute_fel_amounts",
        currency_field="currency_id",
    )

    @api.depends(
        "display_type",
        "quantity",
        "discount",
        "price_unit",
        "price_subtotal",
        "price_total",
    )
    def _compute_fel_amounts(self):
        for line in self:
            if line.display_type != "product":
                line.price_tax = 0.0
                line.price_discount = 0.0
                continue
            line.price_tax = line.price_total - line.price_subtotal
            line.price_discount = (
                line.price_unit * line.quantity * line.discount / 100.0
            )


class AccountMoveComplement(models.Model):
    _name = "account.move.complement"
    _description = "Special Invoice Withholding"
    _order = "complement"

    amount = fields.Monetary(
        string="Amount",
        compute="_compute_complement",
        currency_field="currency_id",
    )
    complement = fields.Selection(
        [("IVA", "RETENCIÓN IVA"), ("ISR", "RETENCIÓN ISR")],
        string="Complement",
        required=True,
    )
    base = fields.Monetary(
        string="Base Amount",
        compute="_compute_complement",
        currency_field="currency_id",
    )
    move_id = fields.Many2one(
        "account.move",
        string="Invoice",
        required=True,
        ondelete="cascade",
        index=True,
    )
    currency_id = fields.Many2one(
        related="move_id.currency_id",
        store=True,
        readonly=True,
    )

    @api.depends("move_id.invoice_line_ids.price_subtotal", "complement")
    def _compute_complement(self):
        for record in self:
            base = sum(record.move_id.invoice_line_ids.mapped("price_subtotal"))
            record.base = base
            record.amount = base * (0.12 if record.complement == "IVA" else 0.05)


class AccountMovePayment(models.Model):
    _name = "account.move.payment"
    _description = "FEL Exchange Invoice Payment"
    _rec_name = "move_id"
    _order = "sequence, date"

    sequence = fields.Integer(string="Sequence", required=True)
    date = fields.Date(string="Date", required=True)
    currency_id = fields.Many2one(
        related="move_id.currency_id",
        store=True,
        readonly=True,
    )
    amount = fields.Monetary(
        string="Amount",
        required=True,
        currency_field="currency_id",
    )
    move_id = fields.Many2one(
        "account.move",
        string="Invoice",
        required=True,
        ondelete="cascade",
        index=True,
    )
