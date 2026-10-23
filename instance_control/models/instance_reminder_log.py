# -*- coding: utf-8 -*-
from odoo import fields, models


class InstanceReminderLog(models.Model):
    """Journal des rappels/alertes envoyés (déduplication des envois)."""
    _name = 'instance.reminder.log'
    _description = 'Journal des rappels instances'
    _order = 'sent_on desc'

    cycle_id = fields.Many2one(
        'instance.billing.cycle', string='Cycle',
        required=True, ondelete='cascade', index=True)
    days_before = fields.Integer(string='Jours avant suspension')
    type = fields.Selection([
        ('reminder', 'Rappel'),
        ('suspension_alert', 'Alerte de suspension'),
    ], string='Type', required=True)
    sent_on = fields.Datetime(string='Envoyé le', default=fields.Datetime.now)

    _sql_constraints = [
        ('cycle_reminder_unique', 'UNIQUE(cycle_id, days_before, type)',
         'Ce rappel a déjà été envoyé pour ce cycle.'),
    ]
