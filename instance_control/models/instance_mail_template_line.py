# -*- coding: utf-8 -*-
from odoo import fields, models


class InstanceMailTemplateLine(models.Model):
    """Modèle d'email de rappel lié à un intervalle précis (par instance).

    Pour un rappel envoyé à J-N, le modèle dont l'intervalle est le plus
    proche inférieur ou égal à N est utilisé (ex. interval 2 : J-2 et J-1).
    Si aucun intervalle ne correspond, le modèle de rappel par défaut de
    l'instance est utilisé (repli : global, puis défaut du module).
    """
    _name = 'instance.mail.template.line'
    _description = "Modèle d'email par intervalle de rappel"
    _order = 'trigger_days desc'
    _rec_name = 'mail_template_id'

    instance_id = fields.Many2one(
        'instance.management', string='Instance',
        required=True, ondelete='cascade', index=True)
    mail_template_id = fields.Many2one(
        'mail.template', string="Modèle d'email", required=True,
        domain=[('model', '=', 'instance.billing.cycle')])
    trigger_days = fields.Integer(
        string='Intervalle de déclenchement (J-X)', required=True, default=0,
        help="Ce modèle est utilisé pour le rappel J-N dont N est le plus "
             "proche supérieur ou égal à cet intervalle "
             "(ex. 2 = utilisé pour J-2 et J-1).")

    _sql_constraints = [
        ('instance_trigger_unique', 'UNIQUE(instance_id, trigger_days)',
         "Un seul modèle d'email par intervalle pour cette instance."),
    ]
