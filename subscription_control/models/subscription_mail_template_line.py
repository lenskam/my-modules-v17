# -*- coding: utf-8 -*-
from odoo import fields, models


class SubscriptionMailTemplateLine(models.Model):
    """Modèle d'email de rappel lié à un intervalle précis.

    Pour un rappel envoyé à J-N, le modèle dont l'intervalle est le plus
    proche inférieur ou égal à N est utilisé (ex. interval 2 : J-2 et J-1).
    Si aucun intervalle ne correspond, le modèle de rappel par défaut
    (Paramètres → Abonnement) est utilisé.
    """
    _name = 'subscription.mail.template.line'
    _description = "Modèle d'email par intervalle de rappel"
    _order = 'trigger_days desc'
    _rec_name = 'mail_template_id'

    mail_template_id = fields.Many2one(
        'mail.template', string="Modèle d'email", required=True,
        domain=[('model', '=', 'subscription.billing.cycle')])
    trigger_days = fields.Integer(
        string='Intervalle de déclenchement (J-X)', required=True, default=0,
        help="Ce modèle est utilisé pour le rappel J-N dont N est le plus "
             "proche supérieur ou égal à cet intervalle "
             "(ex. 2 = utilisé pour J-2 et J-1).")

    _sql_constraints = [
        ('trigger_unique', 'UNIQUE(trigger_days)',
         "Un seul modèle d'email par intervalle."),
    ]
