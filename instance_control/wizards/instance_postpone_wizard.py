# -*- coding: utf-8 -*-
import logging

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class InstancePostponeWizard(models.TransientModel):
    """Wizard de report de la date de suspension d'un cycle."""
    _name = 'instance.postpone.wizard'
    _description = 'Report de suspension instance'

    cycle_id = fields.Many2one(
        'instance.billing.cycle', string='Cycle', required=True)
    new_suspension_date = fields.Date(
        string='Nouvelle date de suspension', required=True)

    def action_postpone(self):
        self.ensure_one()
        if not self.new_suspension_date:
            raise UserError(_('Veuillez saisir une nouvelle date.'))
        cycle = self.cycle_id
        if cycle.state in ('draft', 'awaiting_payment', 'suspended'):
            was_suspended = cycle.state == 'suspended'
            cycle.reminder_log_ids.unlink()
            cycle.write({
                'suspension_date': self.new_suspension_date,
                'state': 'awaiting_payment' if cycle.state != 'draft' else 'draft',
                'remote_suspended': False,
            })
            if was_suspended:
                cycle._remote_restore_with_note(
                    _('Suspension repoussée au %s : accès distant rétabli.',
                      cycle._fmt_date(self.new_suspension_date)),
                    expiration_date=self.new_suspension_date)
            cycle.message_post(body=_(
                'Suspension repoussée au %s.',
                cycle._fmt_date(self.new_suspension_date)))
        return {'type': 'ir.actions.act_window_close'}
