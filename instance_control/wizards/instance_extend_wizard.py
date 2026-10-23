# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class InstanceExtendWizard(models.TransientModel):
    """Wizard de prolongation de l'abonnement d'une instance gérée."""
    _name = 'instance.extend.wizard'
    _description = 'Prolongation instance'

    instance_id = fields.Many2one(
        'instance.management', string='Instance', required=True)
    days = fields.Integer(
        string='Nombre de jours', default=30,
        help="L'expiration distante est repoussée à aujourd'hui + ce nombre "
             "de jours. Laissez la nouvelle date vide pour utiliser ce champ.")
    new_expiration_date = fields.Date(
        string='Nouvelle date d expiration',
        help="Si renseignée, cette date remplace le calcul en jours.")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'days' in fields_list and 'days' not in res:
            res['days'] = self.env['instance.management'].get_extend_days()
        return res

    def _get_target_date(self):
        self.ensure_one()
        if self.new_expiration_date:
            return self.new_expiration_date
        days = self.days or self.env['instance.management'].get_extend_days()
        return fields.Date.context_today(self) + timedelta(days=days)

    def action_extend(self):
        self.ensure_one()
        instance = self.instance_id
        target = self._get_target_date()
        client = instance._get_client()
        client.set_expiration_date(target)
        client.restore_access()
        instance.write({
            'state': 'active',
            'expiration_date': target,
            'last_check': fields.Datetime.now(),
            'last_error': False,
        })
        instance.message_post(body=_(
            "Abonnement prolongé : nouvelle expiration distante %s.",
            instance._fmt_date(target)))
        cycle = self.env['instance.billing.cycle'].search([
            ('instance_id', '=', instance.id),
            ('state', 'in', ('draft', 'awaiting_payment', 'suspended')),
        ], limit=1, order='billing_date desc')
        if cycle and cycle.suspension_date and cycle.suspension_date < target:
            cycle.reminder_log_ids.unlink()
            cycle.write({
                'suspension_date': target,
                'state': 'awaiting_payment' if cycle.state != 'draft' else 'draft',
                'remote_suspended': False,
            })
            cycle.message_post(body=_(
                "Prolongation : suspension repoussée au %s.",
                instance._fmt_date(target)))
        return {'type': 'ir.actions.act_window_close'}
