# -*- coding: utf-8 -*-

from odoo import api, fields, models

SHORTNAMES = [
    ("IVA", "IVA"),
    ("ISR", "ISR"),
    ("PETROLEO", "PETROLEO"),
    ("TURISMO HOSPEDAJE", "TURISMO HOSPEDAJE"),
    ("TIMBRE DE PRENSA", "TIMBRE DE PRENSA"),
    ("BOMBEROS", "BOMBEROS"),
    ("TASA MUNICIPAL", "TASA MUNICIPAL"),
    ("BEBIDAS ALCOHOLICAS", "BEBIDAS ALCOHOLICAS"),
    ("TABACO", "TABACO"),
    ("CEMENTO", "CEMENTO"),
    ("BEBIDAS NO ALCOHOLICAS", "BEBIDAS NO ALCOHOLICAS"),
    ("TARIFA PORTUARIA", "TARIFA PORTUARIA"),
]


class AccountTaxGroup(models.Model):
    _inherit = "account.tax.group"

    shortname = fields.Selection(
        SHORTNAMES,
        string="Nombre corto FEL",
        default="IVA",
        help="Código de impuesto enviado en el XML FEL.",
    )
    withhold = fields.Boolean(
        string="Es retención",
        help="Las retenciones no se incluyen como impuestos sumables del DTE.",
    )

    @api.onchange("shortname")
    def _onchange_shortname(self):
        if self.shortname:
            self.name = self.shortname
