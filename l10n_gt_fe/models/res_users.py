# -*- coding: utf-8 -*-

from odoo import models, fields


class ResUsers(models.Model):
    _inherit = "res.users"

    fe_establishment_id = fields.Many2one(
        "res.company.establishment",
        string="Establecimiento FEL",
        domain="[('company_id', 'in', company_ids)]",
    )
