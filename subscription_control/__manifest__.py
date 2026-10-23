# -*- coding: utf-8 -*-
{
    'name': 'Subscription Control',
    'version': '17.0.6.0.1',
    'category': 'Tools',
    'summary': "Contrôle de l'abonnement : facturation, rappels, alertes, blocage configurable, instance centrale",
    'description': """
Module permettant de contrôler la période d'abonnement d'une instance Odoo.

- Bloque l'accès aux applications après la date d'expiration.
- Cycles de facturation mensuels : à la date de facturation (25 par défaut), le délai de paiement (15 jours par défaut) sert à calculer la date de suspension du service.
- Rappels et alertes envoyés à intervalles définis sur Odoo (message, popup modal) et par email, à des destinataires configurables.
- Modèles d'email de rappel configurables par intervalle : pour un rappel J-N, le
  modèle dont l'intervalle est le plus proche inférieur ou égal à N est utilisé
  (ex. interval 2 = J-2 et J-1), avec repli sur le modèle de rappel par défaut.
- Expiration forcée des sessions utilisateur : mécanisme alternatif (configurable) à la révocation de groupe, avec durée de vie paramétrable.
- Tout est paramétrable dans Paramètres → Abonnement.
    """,
    'author': 'ITS',
    'website': 'https://www.its-nh.com',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'web', 'bus'],
    'data': [
        'security/ir.model.access.csv',
        'data/config_data.xml',
        'data/cron_data.xml',
        'data/mail_templates.xml',
        'data/alert_templates.xml',
        'views/subscription_views.xml',
        'views/subscription_alert_template_views.xml',
        'views/subscription_mail_template_line_views.xml',
        'views/res_config_settings_views.xml',
        'views/web_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'subscription_control/static/src/css/subscription_alert.css',
        ],
        'web.assets_backend': [
            'subscription_control/static/src/services/subscription_alert_dialog.js',
            'subscription_control/static/src/services/subscription_alert_dialog.xml',
            'subscription_control/static/src/services/subscription_alert_service.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
