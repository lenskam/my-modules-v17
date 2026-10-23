# -*- coding: utf-8 -*-
{
    'name': 'SAPTis - Account Report Filter',
    'version': '17.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Masquer les tiers sans mouvement dans les rapports Grand livre et Livre des Tiers',
    'description': """
SAPTis - Masquer les tiers sans mouvement
==========================================

Ajoute l'option "Masquer les tiers sans mouvement" sur les rapports
"Grand livre" (General Ledger) et "Livre des Tiers" (Partner Ledger)
d'Odoo 17.

Lorsque l'option est cochée :

- le rapport "Livre des Tiers" n'affiche que les partenaires (clients
  et fournisseurs) ayant au moins une ligne d'écriture comptable
  (account.move.line) sur la période sélectionnée ;
- le rapport "Grand livre" n'affiche que les comptes ayant au moins une
  ligne d'écriture comptable sur la période sélectionnée.

L'option est désactivée par défaut afin de préserver le comportement
standard d'Odoo.
    """,
    'author': 'ITS / Lens Kamdem',
    'website': 'https://www.its-nh.com',
    'depends': ['account', 'account_reports'],
    'data': [
        'views/account_report_view.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'custom_account_report_filter/static/src/components/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
