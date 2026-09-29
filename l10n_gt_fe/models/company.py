# -*- coding: utf-8 -*-

import logging

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


_logger = logging.getLogger(__name__)

INFILE_LOOKUP_TIMEOUT = (10, 30)


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
    cosume_date = fields.Char(
        string="Fecha de obtención del token",
        readonly=True,
        copy=False,
        groups="account.group_account_manager,l10n_gt_fe.group_fel_manager",
    )
    token = fields.Char(
        string="Token de consulta CUI",
        readonly=True,
        copy=False,
        groups="account.group_account_manager,l10n_gt_fe.group_fel_manager",
    )
    due_date = fields.Char(
        string="Vencimiento del token",
        readonly=True,
        copy=False,
        groups="account.group_account_manager,l10n_gt_fe.group_fel_manager",
    )
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

    @staticmethod
    def _normalize_fiscal_identifier(value):
        return (value or "").replace("-", "").replace(" ", "").upper()

    def _get_lookup_url(self, parameter, operation):
        url = self.env["ir.config_parameter"].sudo().get_param(parameter)
        if not url:
            raise ValidationError(
                _(
                    "The Infile URL for %(operation)s is not configured.",
                    operation=operation,
                )
            )
        return url

    @staticmethod
    def _decode_lookup_response(response, operation):
        try:
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as error:
            _logger.warning("Infile %s request failed: %s", operation, error)
            raise UserError(
                _(
                    "Could not communicate with Infile during %(operation)s: %(error)s",
                    operation=operation,
                    error=error,
                )
            ) from error
        except ValueError as error:
            raise UserError(
                _("Infile returned an invalid response during %s.") % operation
            ) from error
        if not isinstance(data, dict):
            raise UserError(
                _("Infile returned an unexpected response during %s.") % operation
            )
        return data

    def _lookup_post(self, url, operation, **request_values):
        try:
            response = requests.post(
                url=url,
                timeout=INFILE_LOOKUP_TIMEOUT,
                **request_values,
            )
        except requests.RequestException as error:
            _logger.warning("Infile %s request failed: %s", operation, error)
            raise UserError(
                _(
                    "Could not communicate with Infile during %(operation)s: %(error)s",
                    operation=operation,
                    error=error,
                )
            ) from error
        return self._decode_lookup_response(response, operation)

    def _get_sign_token_cui(self):
        company = self.sudo()
        company.ensure_one()
        if not company.fe_user or not company.fe_key_webservice:
            raise ValidationError(
                _("Configure the Infile API user and key on the company.")
            )
        return {"llave": company.fe_key_webservice, "prefijo": company.fe_user}

    def _get_sign_nit_service(self):
        company = self.sudo()
        company.ensure_one()
        if not company.fe_user or not company.fe_key_webservice:
            raise ValidationError(
                _("Configure the Infile API user and key on the company.")
            )
        return {
            "emisor_codigo": company.fe_user,
            "emisor_clave": company.fe_key_webservice,
        }

    def _refresh_cui_token(self):
        company = self.sudo()
        company.ensure_one()
        url = company._get_lookup_url(
            "url.webservice.token.access",
            _("CUI token request"),
        )
        data = company._lookup_post(
            url,
            _("CUI token request"),
            data=company._get_sign_token_cui(),
            headers={"Accept": "application/json"},
        )
        token = data.get("token")
        if not token or data.get("resultado") is False:
            raise UserError(
                data.get("mensaje")
                or data.get("descripcion")
                or _("Infile did not return a valid CUI access token.")
            )
        company.write(
            {
                "token": token,
                "cosume_date": data.get("fecha") or False,
                "due_date": data.get("fecha_de_vencimiento") or False,
            }
        )
        return token

    def get_token_cui(self):
        self.ensure_one()
        self._refresh_cui_token()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("FEL / Infile"),
                "message": _("The CUI lookup token was refreshed successfully."),
                "type": "success",
                "sticky": False,
            },
        }

    def consulta_nit(self, nit):
        company = self.sudo()
        company.ensure_one()
        identifier = company._normalize_fiscal_identifier(nit)
        if not identifier:
            raise ValidationError(_("Enter a NIT before consulting Infile."))
        url = company._get_lookup_url(
            "url.webservice.nit.service",
            _("NIT lookup"),
        )
        payload = company._get_sign_nit_service()
        payload["nit_consulta"] = identifier
        return company._lookup_post(
            url,
            _("NIT lookup"),
            json=payload,
            headers={"Accept": "application/json"},
        )

    def consulta_cui(self, cui):
        company = self.sudo()
        company.ensure_one()
        identifier = company._normalize_fiscal_identifier(cui)
        if not identifier:
            raise ValidationError(_("Enter a CUI before consulting Infile."))
        url = company._get_lookup_url(
            "url.webservice.cui.service",
            _("CUI lookup"),
        )
        token = company.token or company._refresh_cui_token()
        for attempt in range(2):
            try:
                response = requests.post(
                    url=url,
                    data={"cui": identifier},
                    headers={
                        "Authorization": "Bearer %s" % token,
                        "Accept": "application/json",
                    },
                    timeout=INFILE_LOOKUP_TIMEOUT,
                )
            except requests.RequestException as error:
                _logger.warning("Infile CUI lookup request failed: %s", error)
                raise UserError(
                    _("Could not communicate with Infile during CUI lookup: %s")
                    % error
                ) from error
            if response.status_code == 401 and attempt == 0:
                token = company._refresh_cui_token()
                continue
            return company._decode_lookup_response(response, _("CUI lookup"))
        raise UserError(_("Infile rejected the CUI lookup token."))


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
        domain=[("country_id.code", "=", "GT")],
    )
