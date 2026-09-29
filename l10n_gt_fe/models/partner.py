# -*- coding: utf-8 -*-

from odoo import api, fields, models


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
