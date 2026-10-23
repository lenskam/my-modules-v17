# -*- coding: utf-8 -*-
{
    'name': 'Instance Control',
    'version': '17.0.4.0.1',
    'category': 'Tools',
    'summary': "Contrôleur central : facturation, paiement, suspension ou prolongation par API des instances Odoo gérées",
    'description': """
Module installé sur l'Odoo central permettant de contrôler la facturation, le paiement,
la suspension ou la prolongation par API des instances Odoo gérées et d'envoyer les
alertes / emails de suspension.

- Cycles de facturation mensuels : à la date de facturation (25 par défaut), le délai de
  paiement (15 jours par défaut) sert à calculer la date de suspension du service.
- Gestion des instances Odoo gérées (suspension, prolongation des instances configurées)
  via les méthodes exposées par le module client subscription_control (XML-RPC).
- Génération des factures clients dans l'Odoo central ; le paiement de la facture
  rétablit automatiquement l'instance distante.
- Rappels et alertes envoyés à intervalles définis par email, à des destinataires
  configurables INSTANCE PAR INSTANCE (onglet « Alertes & Notifications » de chaque
  instance gérée) ; les modèles d'email de rappel et de suspension sont également
  définis par instance, avec repli sur les valeurs globales.
- Facturation surchargable par instance : jour de facturation, délai de paiement,
  intervalles de rappel et produit d'abonnement (vide/0 = valeur globale).
- Modèles d'email de rappel configurables par intervalle : pour un rappel J-N, le
  modèle dont l'intervalle est le plus proche inférieur ou égal à N est utilisé
  (ex. interval 2 = J-2 et J-1), avec repli sur le modèle par défaut de l'instance.
- Push de l'état d'abonnement vers le Helpdesk des instances Odoo 11 équipées du
  module helpdesk_subscription_control : blocage de la création de tickets à la
  suspension, rétablissement au paiement.
- Configuration des templates des mails à envoyer (modèles d'alerte personnalisables +
  mail.template par défaut).

Prérequis : subscription_control >= 17.0.4.0.0 installé sur chaque instance gérée.
    """,
    'author': 'ITS',
    'website': 'https://www.its-nh.com',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'web', 'account'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/config_data.xml',
        'data/cron_data.xml',
        'data/mail_templates.xml',
        'data/alert_templates.xml',
        'views/instance_management_views.xml',
        'views/instance_billing_cycle_views.xml',
        'views/instance_alert_template_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
