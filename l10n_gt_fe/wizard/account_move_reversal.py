# -*- coding: utf-8 -*-

from odoo import _, models
from odoo.exceptions import UserError


class AccountMoveReversal(models.TransientModel):
    _inherit = "account.move.reversal"

    def _prepare_default_reversal(self, move):
        """Carry FEL references to the credit note without mutating the source invoice."""
        values = super()._prepare_default_reversal(move)
        if move._is_outgoing_fel():
            if not self.journal_id.active_fel or self.journal_id.fe_type != "NCRE":
                raise UserError(
                    _("Select a FEL sales journal configured as a credit note (NCRE).")
                )
            values.update(
                {
                    "factura_original_id": move.id,
                    "fe_phrase_ids": [(5, 0, 0)],
                    "fe_use_new_vat": move.fe_use_new_vat,
                    "fe_new_vat_id": move.fe_new_vat_id.id,
                    "motivo_fel": self.reason,
                }
            )
        return values
