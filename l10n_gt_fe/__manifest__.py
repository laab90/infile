# -*- coding: utf-8 -*-

{
    "name": "Factura Electrónica Guatemala - Infile",
    "summary": "Certificación de documentos FEL de Guatemala con Infile",
    "version": "17.0.3.1.1",
    "category": "Accounting/Localizations/EDI",
    "author": "J2L Technologies",
    "depends": ["account", "l10n_gt"],
    "data": [
        "data/webservice_data.xml",
        "data/account_fe_phrase_data.xml",
        "data/account_journal_data.xml",
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/company_views.xml",
        "views/account_move_views.xml",
        "views/account_journal_views.xml",
        "views/account_tax_views.xml",
        "views/res_users_views.xml",
        "views/res_partner_views.xml",
    ],
    "application": True,
    "sequence": 1,
    "license": "GPL-3",
    "installable": True,
}
