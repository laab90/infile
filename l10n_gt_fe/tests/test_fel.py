from xml.etree import ElementTree as ET

from odoo import Command, fields
from odoo.tests.common import TransactionCase, tagged


@tagged("at_install")
class TestFelXml(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.country = cls.env.ref("base.gt")
        cls.state = cls.env["res.country.state"].search(
            [("country_id", "=", cls.country.id)], limit=1
        )
        if not cls.state:
            cls.state = cls.env["res.country.state"].create(
                {"name": "Guatemala", "code": "GT", "country_id": cls.country.id}
            )
        cls.company.write(
            {
                "vat": "1234567K",
                "country_id": cls.country.id,
                "state_id": cls.state.id,
                "street": "Zona 1",
                "city": "Guatemala",
                "zip": "01001",
                "email": "fel@example.com",
                "fe_user": "TEST_USER",
                "fe_key_webservice": "TEST_API_KEY",
                "fe_sign_token": "TEST_SIGN_KEY",
            }
        )
        cls.establishment = cls.env["res.company.establishment"].create(
            {
                "fe_tradename": "Comercio de Prueba",
                "fe_code": 1,
                "company_id": cls.company.id,
                "fe_tradename_street": "Zona 1",
                "fe_tradename_city": "Guatemala",
                "fe_tradename_state_id": cls.state.id,
            }
        )
        cls.journal = cls.env["account.journal"].create(
            {
                "name": "Ventas FEL",
                "code": "TFEL",
                "type": "sale",
                "company_id": cls.company.id,
                "active_fel": True,
                "fe_type": "FACT",
                "fe_establishment_id": cls.establishment.id,
            }
        )
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Cliente de Prueba",
                "vat": "CF",
                "partner_type": "NIT",
                "country_id": cls.country.id,
                "state_id": cls.state.id,
                "street": "Ciudad",
                "city": "Guatemala",
                "zip": "01001",
            }
        )
        cls.income_account = cls.env["account.account"].create(
            {
                "name": "Ingresos FEL de prueba",
                "code": "TFELINC",
                "account_type": "income",
                "company_id": cls.company.id,
            }
        )
        cls.receivable_account = cls.env["account.account"].create(
            {
                "name": "Clientes FEL de prueba",
                "code": "TFELREC",
                "account_type": "asset_receivable",
                "reconcile": True,
                "company_id": cls.company.id,
            }
        )
        cls.partner.property_account_receivable_id = cls.receivable_account
        cls.tax_group = cls.env["account.tax.group"].create(
            {
                "name": "IVA FEL de prueba",
                "shortname": "IVA",
                "company_id": cls.company.id,
                "country_id": cls.country.id,
            }
        )
        cls.tax = cls.env["account.tax"].create(
            {
                "name": "IVA 12% FEL de prueba",
                "amount": 12.0,
                "amount_type": "percent",
                "type_tax_use": "sale",
                "price_include": True,
                "company_id": cls.company.id,
                "country_id": cls.country.id,
                "tax_group_id": cls.tax_group.id,
            }
        )

    def _create_invoice(self, extra_lines=None):
        lines = [
            Command.create(
                {
                    "name": "Servicio FEL",
                    "quantity": 1.0,
                    "price_unit": 112.0,
                    "account_id": self.income_account.id,
                    "tax_ids": [Command.set(self.tax.ids)],
                }
            )
        ]
        lines.extend(extra_lines or [])
        return self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner.id,
                "journal_id": self.journal.id,
                "invoice_date": fields.Date.context_today(self.env.user),
                "invoice_line_ids": lines,
            }
        )

    @staticmethod
    def _find(root, path):
        return root.find(path, {"dte": "http://www.sat.gob.gt/dte/fel/0.2.0"})

    def test_odoo_17_totals_are_preserved(self):
        invoice = self._create_invoice()
        line = invoice.invoice_line_ids

        self.assertAlmostEqual(line.price_subtotal, 100.0, places=2)
        self.assertAlmostEqual(line.price_total, 112.0, places=2)
        self.assertAlmostEqual(line.price_tax, 12.0, places=2)
        self.assertEqual(invoice.fe_count_payment, 1)
        self.assertEqual(invoice.fe_payment_frequency, 1)
        self.assertEqual(invoice.incoterm_fel, "FOB")

    def test_auxiliary_currency_fields_are_not_stored(self):
        for model_name in (
            "account.move.complement",
            "account.move.payment",
            "charge.third.party.account",
        ):
            with self.subTest(model=model_name):
                self.assertFalse(self.env[model_name]._fields["currency_id"].store)

    def test_defaults_do_not_backfill_existing_business_tables(self):
        fields_without_schema_defaults = {
            "account.move": (
                "fe_count_payment",
                "fe_payment_frequency",
                "tipo_gasto",
                "incoterm_fel",
                "active_contingencia",
                "fe_exhangerate",
                "documento_xml_fel_name",
                "resultado_xml_fel_name",
                "pdf_fel_name",
            ),
            "res.partner": ("partner_type",),
            "res.company": ("fe_vat_affiliation",),
            "account.tax.group": ("shortname",),
            "account.journal": ("active_fel",),
        }
        for model_name, field_names in fields_without_schema_defaults.items():
            for field_name in field_names:
                with self.subTest(model=model_name, field=field_name):
                    self.assertFalse(self.env[model_name]._fields[field_name].default)

        move_defaults = self.env["account.move"].default_get(
            [
                "fe_count_payment",
                "fe_payment_frequency",
                "tipo_gasto",
                "incoterm_fel",
                "fe_exhangerate",
            ]
        )
        self.assertEqual(move_defaults["fe_count_payment"], 1)
        self.assertEqual(move_defaults["fe_payment_frequency"], 1)
        self.assertEqual(move_defaults["tipo_gasto"], "mixto")
        self.assertEqual(move_defaults["incoterm_fel"], "FOB")
        self.assertEqual(move_defaults["fe_exhangerate"], "1.00")
        self.assertEqual(
            self.env["res.partner"].default_get(["partner_type"])["partner_type"],
            "NIT",
        )
        self.assertEqual(
            self.env["res.company"].default_get(["fe_vat_affiliation"])[
                "fe_vat_affiliation"
            ],
            "GEN",
        )
        self.assertEqual(
            self.env["account.tax.group"].default_get(["shortname"])["shortname"],
            "IVA",
        )

    def test_establishment_list_uses_full_group_width(self):
        view = self.env.ref("l10n_gt_fe.view_company_form")
        field = ET.fromstring(view.arch_db).find(
            ".//field[@name='fe_establishment_ids']"
        )

        self.assertIsNotNone(field)
        self.assertEqual(field.attrib.get("colspan"), "2")
        self.assertIn("w-100", field.attrib.get("class", "").split())

    def test_fact_xml_contains_valid_amounts_and_timezone(self):
        self.company.fe_vat_affiliation = "PEQ"
        invoice = self._create_invoice()
        root = ET.fromstring(invoice._xml())

        general = self._find(root, ".//dte:DatosGenerales")
        issuer = self._find(root, ".//dte:Emisor")
        self.assertTrue(general.attrib["FechaHoraEmision"].endswith("-06:00"))
        self.assertEqual(general.attrib["Tipo"], "FACT")
        self.assertEqual(issuer.attrib["AfiliacionIVA"], "PEQ")
        self.assertEqual(self._find(root, ".//dte:MontoGravable").text, "100.00")
        self.assertEqual(self._find(root, ".//dte:MontoImpuesto").text, "12.00")
        self.assertEqual(self._find(root, ".//dte:GranTotal").text, "112.00")

    def test_negative_line_is_prorated_as_fel_discount(self):
        invoice = self._create_invoice(
            [
                Command.create(
                    {
                        "name": "Descuento global",
                        "quantity": 1.0,
                        "price_unit": -10.0,
                        "account_id": self.income_account.id,
                        "tax_ids": [Command.set(self.tax.ids)],
                    }
                )
            ]
        )
        root = ET.fromstring(invoice._xml())

        self.assertEqual(
            len(
                root.findall(
                    ".//dte:Item", {"dte": "http://www.sat.gob.gt/dte/fel/0.2.0"}
                )
            ),
            1,
        )
        self.assertEqual(self._find(root, ".//dte:Descuento").text, "10.000000")
        self.assertEqual(self._find(root, ".//dte:GranTotal").text, "102.00")

    def test_third_party_total_includes_taxable_base(self):
        invoice = self._create_invoice()
        charge = self.env["charge.third.party.account"].create(
            {
                "move_id": invoice.id,
                "vat": "1234567K",
                "number": "A-1",
                "date": fields.Date.context_today(self.env.user),
                "name": "Cobro por cuenta ajena",
                "amount_untaxes": 100.0,
                "amount_dai": 5.0,
                "other_amount": 3.0,
            }
        )

        self.assertAlmostEqual(charge.amount_taxes, 12.0, places=2)
        self.assertAlmostEqual(charge.amount_total, 120.0, places=2)
        self.assertEqual(charge.currency_id, invoice.currency_id)
