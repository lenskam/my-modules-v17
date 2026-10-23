# -*- coding: utf-8 -*-
{
    'name': 'Grand Livre - Masquer le solde initiale',
    'version': '17.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Ajoute l\'option "Masquer le solde initiale" sur le rapport Grand livre',
    'description': """
Grand Livre - Masquer le solde initiale
=======================================

Ajoute une option "Masquer le solde initiale" dans la barre d'options du
rapport "Grand livre" (General Ledger) d'Odoo 17.

Lorsque l'option est cochée, la ligne "Solde initiale" n'apparaît plus
lors du dépliage d'un compte dans le rapport.

Les montants cumulés des lignes d'écriture restent identiques au
comportement standard : le solde initial est toujours pris en compte
dans le calcul des cumuls, seule la ligne est masquée.

L'option peut être définie par défaut sur la fiche du rapport
(modèle account.report) et reste mémorisée pour l'utilisateur pendant
sa session. Elle est désactivée par défaut afin de préserver le
comportement standard d'Odoo.
    """,
    'author': 'ITS / Lens Kamdem',
    'website': 'https://www.its-nh.com',
    'depends': ['account', 'account_reports'],
    'data': [
        'views/account_report_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'account_general_ledger_hide_initial_balance/static/src/components/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
