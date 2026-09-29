# -*- coding: utf-8 -*-

from odoo import fields, models


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
        required=True,
        default="NIT",
    )
