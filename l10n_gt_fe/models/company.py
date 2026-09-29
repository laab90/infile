# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = "res.company"

    fe_user = fields.Char(
        string="Usuario API / alias Infile",
        groups="account.group_account_manager,l10n_gt_fe.group_fel_manager",
    )
    fe_key_webservice = fields.Char(
        string="Llave API Infile",
        groups="account.group_account_manager,l10n_gt_fe.group_fel_manager",
    )
    fe_sign_token = fields.Char(
        string="Llave de firma Infile",
        groups="account.group_account_manager,l10n_gt_fe.group_fel_manager",
    )
    fe_vat_affiliation = fields.Selection(
        [
            ("GEN", "General"),
            ("EXE", "Exento"),
            ("PEQ", "Pequeño contribuyente"),
        ],
        string="Afiliación IVA FEL",
        help="Régimen de IVA del emisor que se informa en el DTE.",
    )
    fe_other_email = fields.Char(string="Correo de copia FEL")
    fe_establishment_ids = fields.One2many(
        "res.company.establishment",
        "company_id",
        string="Establecimientos FEL",
    )
    fe_phrase_ids = fields.Many2many("account.fe.phrase", string="Frases FEL")

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if (
            "fe_vat_affiliation" in fields_list
            and "fe_vat_affiliation" not in values
        ):
            values["fe_vat_affiliation"] = "GEN"
        return values

    def _get_headers(self):
        self.ensure_one()
        headers = {"Content-Type": "application/json"}
        if not self.fe_user or not self.fe_key_webservice:
            raise ValidationError(
                _("Configure the Infile API user and key on the company.")
            )
        headers.update({"usuario": self.fe_user, "llave": self.fe_key_webservice})
        return headers

    def _get_sign_token(self):
        self.ensure_one()
        if not self.fe_user or not self.fe_sign_token:
            raise ValidationError(
                _("Configure the Infile signing alias and key on the company.")
            )
        return {"llave": self.fe_sign_token, "alias": self.fe_user}


class ResCompanyEstablishment(models.Model):
    _name = "res.company.establishment"
    _description = "Company Establishment"
    _rec_name = "fe_tradename"
    _check_company_auto = True

    fe_tradename = fields.Char(string="Nombre comercial", required=True)
    fe_code = fields.Integer(string="Código de establecimiento", required=True)
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
        ondelete="cascade",
        index=True,
    )
    export_code = fields.Char(string="Código de exportador")
    fe_tradename_street = fields.Char(string="Dirección")
    fe_tradename_city = fields.Char(string="Municipio")
    fe_tradename_state_id = fields.Many2one(
        "res.country.state",
        string="Departamento",
        domain="[('country_id', '=', company_id.country_id)]",
    )
