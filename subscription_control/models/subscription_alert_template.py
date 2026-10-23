# -*- coding: utf-8 -*-
import logging
import string

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class SubscriptionAlertTemplate(models.Model):
    """Modele de message d'alerte (rappels et suspension).

    Chaque alerte a un corps de message avec des placeholders au format
    ${variable} (rendu via string.Template.safe_substitute, securise).
    Disponibles : ${client_name}, ${invoice_ref}, ${invoice_amount},
    ${invoice_currency}, ${suspension_date}, ${days_before}, ${db_name},
    ${cycle_name}.

    selection du modele : pour un rappel a J-N, on prend le modele actif
    de type « Rappel » dont trigger_days est le plus proche <= N
    (ex. avec 10/5/2 : J-10 -> T10, J-5 -> T5, J-2 et J-1 -> T2).
    Un seul modele de type « Suspension » actif est attendu.
    """
    _name = 'subscription.alert.template'
    _description = "Modele d'alerte abonnement"
    _order = 'type desc, trigger_days desc'

    name = fields.Char(string='Nom', required=True)
    type = fields.Selection([
        ('reminder', 'Rappel'),
        ('suspension', 'Suspension'),
    ], string='Type', required=True, default='reminder')
    trigger_days = fields.Integer(
        string='Jours avant suspension (declenchement)', default=0,
        help="Pour un rappel : nombre de jours avant suspension ou ce modele "
             "est utilise. Le modele avec le trigger le plus proche inferieur "
             "ou egal au rappel envoye est choisi. Pour la suspension : 0.")
    subject = fields.Char(
        string='Sujet',
        help="Sujet de l'alerte (notifications, discuss). "
             "Si vide, un sujet par defaut est genere.")
    body = fields.Text(
        string='Corps du message', required=True,
        help="Texte avec placeholders : ${client_name}, ${invoice_ref}, "
             "${invoice_amount}, ${invoice_currency}, ${suspension_date}, "
             "${days_before}, ${db_name}, ${cycle_name}")
    active = fields.Boolean(string='Actif', default=True)

    _sql_constraints = [
        ('type_trigger_unique', 'UNIQUE(type, trigger_days)',
         'Un seul modèle par type et par déclencheur.'),
    ]

    @api.model
    def render_body(self, context):
        """Rendu securise (safe_substitute) du corps avec le contexte."""
        self.ensure_one()
        return string.Template(self.body or '').safe_substitute(context or {})

    @api.model
    def pick_reminder_template(self, reminder_day):
        """Choisit le modele de rappel avec le trigger le plus proche <= N."""
        template = self.search([
            ('type', '=', 'reminder'),
            ('active', '=', True),
            ('trigger_days', '<=', reminder_day),
        ], order='trigger_days desc', limit=1)
        if not template:
            # Aucun trigger <= N : on prend le plus petit trigger disponible
            template = self.search([
                ('type', '=', 'reminder'), ('active', '=', True),
            ], order='trigger_days asc', limit=1)
        return template

    @api.model
    def get_suspension_template(self):
        """Modele d'alerte de suspension actif (le premier si plusieurs)."""
        return self.search([
            ('type', '=', 'suspension'), ('active', '=', True),
        ], limit=1)
