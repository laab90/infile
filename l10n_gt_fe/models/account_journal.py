# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

TYPE_FE = [
    ("FACT", "Factura"),
    ("FESP", "Factura Especial"),
    ("FCAM", "Factura Cambiaria"),
    ("NDEB", "Nota de Débito"),
    ("NCRE", "Nota de Crédito"),
    ("NABN", "Nota de Abono"),
    ("FAEX", "Factura Exportación"),
    ("OTRO", "Otro"),
]


class AccountJournal(models.Model):
    _inherit = "account.journal"

    active_fel = fields.Boolean(string="Usar FEL / Infile", default=False)
    fe_type = fields.Selection(TYPE_FE, string="Tipo de DTE")
    fe_establishment_id = fields.Many2one(
        "res.company.establishment",
        string="Establecimiento FEL",
        check_company=True,
        domain="[('company_id', '=', company_id)]",
    )

    @api.constrains("active_fel", "type", "fe_type", "fe_establishment_id")
    def _check_fel_configuration(self):
        for journal in self:
            if not journal.active_fel:
                continue
            if journal.type != "sale":
                raise ValidationError(_("FEL can only be enabled on sales journals."))
            if not journal.fe_type or journal.fe_type == "OTRO":
                raise ValidationError(_("Select a valid FEL document type."))
            if not journal.fe_establishment_id:
                raise ValidationError(
                    _("Select the FEL establishment for the journal.")
                )
