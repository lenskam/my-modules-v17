# -*- coding: utf-8 -*-
from odoo import api, models, _
from odoo.exceptions import AccessDenied


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _check_credentials(self, password, env):
        res = super()._check_credentials(password, env)
        if self.has_group('base.group_system'):
            return res
        sub = self.env['subscription.control']
        self.env['subscription.session'].register_user_session(self)
        if sub.check_expiration() and sub.get_enforcement_mode() != 'none':
            # Bloqué en modes « session » et « groups » ; en mode « none »,
            # le blocage est délégué à l'instance centrale (instance_control).
            raise AccessDenied(sub.get_suspension_login_message())
        return res
