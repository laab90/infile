# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ResPartner(models.Model):
    _inherit = "res.partner"

    country_id = fields.Many2one(default=lambda s: s.env.ref("base.gt"))
    partner_type = fields.Selection(
        [
            ("NIT", "NIT"),
            ("CUI", "DPI"),
            ("EXT", "Pasaporte / identificación extranjera"),
        ],
        string="Tipo de documento FEL",
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if "partner_type" in fields_list and "partner_type" not in values:
            values["partner_type"] = "NIT"
        return values

    @staticmethod
    def _lookup_error_message(data):
        return (
            data.get("mensaje")
            or data.get("descripcion")
            or data.get("error")
            or _("Infile did not return a fiscal name for this identifier.")
        )

    def get_fiscal_name(self):
        """Retrieve the receiver name from Infile without deleting duplicate contacts."""
        self.ensure_one()
        identifier = self.env.company._normalize_fiscal_identifier(self.vat)
        document_type = self.partner_type or "NIT"

        if not identifier:
            raise ValidationError(_("Enter a NIT or CUI before consulting Infile."))
        if identifier in ("CF", "C/F"):
            raise UserError(_("Consumer Final does not require a fiscal-name lookup."))
        if document_type == "EXT":
            raise UserError(
                _("Foreign identifications cannot be consulted with this service.")
            )

        company = self.company_id or self.env.company
        if document_type == "CUI":
            if not identifier.isdigit() or len(identifier) != 13:
                raise ValidationError(_("The CUI must contain exactly 13 digits."))
            data = company.consulta_cui(identifier)
            cui_data = data.get("cui")
            name = cui_data.get("nombre") if isinstance(cui_data, dict) else False
            name = name or data.get("nombre")
            success = str(data.get("descripcion", "")).strip().upper() == "OK"
            if not success or not name:
                raise UserError(self._lookup_error_message(data))
        else:
            data = company.consulta_nit(identifier)
            name = data.get("nombre")
            if not name:
                raise UserError(self._lookup_error_message(data))

        self.write({"vat": identifier, "name": str(name).strip()})
        duplicate_count = self.search_count(
            [("id", "!=", self.id), ("vat", "=", identifier)]
        )
        message = _("Fiscal name updated from Infile.")
        if duplicate_count:
            message += " " + _(
                "There are %(count)s other contacts with the same identifier.",
                count=duplicate_count,
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("FEL / Infile"),
                "message": message,
                "type": "success",
                "sticky": bool(duplicate_count),
            },
        }
