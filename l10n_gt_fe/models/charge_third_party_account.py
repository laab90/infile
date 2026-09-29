from odoo import api, fields, models


class ChargeThirdPartyAccount(models.Model):
    _name = "charge.third.party.account"
    _description = "Charge Third Party Account"

    vat = fields.Char(string="NIT Tercero", required=True)
    number = fields.Char(string="N. Doc.", required=True)
    date = fields.Date(string="Fecha Doc.", required=True)
    name = fields.Char(string="Descripcion", required=True)
    currency_id = fields.Many2one(
        related="move_id.currency_id",
        store=True,
        readonly=True,
    )
    amount_untaxes = fields.Monetary(string="Base Imponible", required=True)
    amount_dai = fields.Monetary(string="DAI", required=True, default=0.0)
    amount_taxes = fields.Monetary(string="IVA", compute="_compute_all")
    other_amount = fields.Monetary(string="Otros", required=True, default=0.0)
    amount_total = fields.Monetary(string="Total", compute="_compute_all")
    move_id = fields.Many2one(
        "account.move",
        string="Invoice",
        required=True,
        ondelete="cascade",
        index=True,
    )

    @api.depends("amount_untaxes", "amount_dai", "other_amount")
    def _compute_all(self):
        for record in self:
            record.amount_taxes = record.amount_untaxes * 0.12
            record.amount_total = (
                record.amount_untaxes
                + record.amount_dai
                + record.amount_taxes
                + record.other_amount
            )
