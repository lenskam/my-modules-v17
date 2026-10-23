# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.home import Home


class SubscriptionHome(Home):
    """Affiche une modale d'alerte de suspension sur la page de connexion
    lorsque le blocage provient de l'expiration de l'abonnement."""

    @http.route()
    def web_login(self, redirect=None, **kw):
        response = super().web_login(redirect=redirect, **kw)
        if hasattr(response, 'qcontext'):
            sub = request.env['subscription.control']
            response.qcontext['sc_login_message_top'] = sub.get_login_message_top()
            response.qcontext['sc_login_message_bottom'] = sub.get_login_message_bottom()
            if response.qcontext.get('error') == sub.get_suspension_login_message():
                response.qcontext['subscription_suspended_modal'] = True
        return response
