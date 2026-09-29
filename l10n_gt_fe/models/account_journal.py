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

FEL_JOURNAL_DATA = (
    ("FACT", "Ventas FEL - Factura", "FFACT", "sale"),
    ("FCAM", "Ventas FEL - Factura cambiaria", "FFCAM", "sale"),
    ("NDEB", "Ventas FEL - Nota de débito", "FNDEB", "sale"),
    ("NCRE", "Ventas FEL - Nota de crédito", "FNCRE", "sale"),
    ("NABN", "Ventas FEL - Nota de abono", "FNABN", "sale"),
    ("FAEX", "Ventas FEL - Factura de exportación", "FFAEX", "sale"),
    ("FESP", "Compras FEL - Factura especial", "FFESP", "purchase"),
)


class AccountJournal(models.Model):
    _inherit = "account.journal"

    active_fel = fields.Boolean(string="Usar FEL / Infile")
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
            if journal.type == "purchase" and journal.fe_type != "FESP":
                raise ValidationError(
                    _("Only special invoices (FESP) can use a FEL purchase journal.")
                )
            if journal.type not in ("sale", "purchase"):
                raise ValidationError(
                    _("FEL can only be enabled on sales or purchase journals.")
                )
            if not journal.fe_type or journal.fe_type == "OTRO":
                raise ValidationError(_("Select a valid FEL document type."))
            if not journal.fe_establishment_id:
                raise ValidationError(
                    _("Select the FEL establishment for the journal.")
                )

    @api.model
    def _available_fel_journal_code(self, company, preferred_code):
        """Return a five-character code that is free in the target company."""
        journals = self.sudo().with_context(active_test=False)
        if not journals.search(
            [("company_id", "=", company.id), ("code", "=", preferred_code)],
            limit=1,
        ):
            return preferred_code

        for number in range(1, 10000):
            suffix = str(number)
            candidate = "%s%s" % (preferred_code[: 5 - len(suffix)], suffix)
            if not journals.search(
                [("company_id", "=", company.id), ("code", "=", candidate)],
                limit=1,
            ):
                return candidate
        raise ValidationError(
            _("Could not generate an available FEL journal code for %s.")
            % company.display_name
        )

    @api.model
    def _ensure_fel_journals(self):
        """Create the supported FEL journals once for every existing company."""
        journals = self.sudo().with_context(active_test=False)
        companies = (
            self.env["res.company"]
            .sudo()
            .with_context(active_test=False)
            .search([])
        )
        for company in companies:
            for fe_type, name, preferred_code, journal_type in FEL_JOURNAL_DATA:
                existing = journals.search(
                    [
                        ("company_id", "=", company.id),
                        ("type", "=", journal_type),
                        ("fe_type", "=", fe_type),
                    ],
                    limit=1,
                )
                if existing:
                    continue
                journals.create(
                    {
                        "name": name,
                        "code": self._available_fel_journal_code(
                            company, preferred_code
                        ),
                        "type": journal_type,
                        "company_id": company.id,
                        "fe_type": fe_type,
                        "active_fel": False,
                        "sequence": 50,
                    }
                )
        return True
