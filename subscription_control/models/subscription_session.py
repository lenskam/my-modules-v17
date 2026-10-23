# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

DELAY_PARAM = 'subscription.force_session_expiry_delay'


class SubscriptionSession(models.Model):
    """Suivi des sessions utilisateur pour le mecanisme d'expiration forcee.

    Alternative a la revocation de groupe : quand l'option est activee,
    chaque connexion enregistre une session avec une duree de vie limitee.
    Si l'abonnement est expire, le cron supprime les sessions Odoo
    correspondantes : l'utilisateur est redirige vers la page de connexion
    (et la connexion reste bloquee tant que l'abonnement est expire).
    """
    _name = 'subscription.session'
    _description = "Session utilisateur - expiration forcee"
    _rec_name = 'user_id'

    user_id = fields.Many2one(
        'res.users', string='Utilisateur', required=True,
        index=True, ondelete='cascade')
    expiry_datetime = fields.Datetime(
        string="Date d'expiration", required=True, index=True)

    @api.model
    def _is_enabled(self):
        """Mécanisme actif uniquement en mode de blocage « session »."""
        return self.env['subscription.control'].get_enforcement_mode() == 'session'

    @api.model
    def _get_configured_delay(self):
        value = self.env['ir.config_parameter'].sudo().get_param(DELAY_PARAM, 60)
        try:
            return int(value or 60)
        except (TypeError, ValueError):
            return 60

    @api.model
    def register_user_session(self, user):
        """Cree ou rafraichit la session forcee d'un utilisateur."""
        if user._is_admin() or not self._is_enabled():
            return
        delay = self._get_configured_delay()
        if delay <= 0:
            return
        expiry = fields.Datetime.now() + timedelta(minutes=delay)
        session = self.sudo().search([('user_id', '=', user.id)], limit=1)
        if session:
            session.write({'expiry_datetime': expiry})
        else:
            self.sudo().create({'user_id': user.id, 'expiry_datetime': expiry})
        _logger.info("Session forcee enregistree pour %s (expiration : %s)",
                     user.login, expiry)

    @api.model
    def _kill_user_sessions(self, user):
        """Supprime toutes les sessions Odoo actives d'un utilisateur.

        La suppression de la session cote serveur invalide le cookie de
        session : a la prochaine requete, l'utilisateur est redirige vers
        la page de connexion.
        """
        import odoo.http
        store = getattr(odoo.http.root, 'session_store', None)
        if store is None:
            _logger.error("Session store introuvable, expiration forcee "
                          "impossible pour %s", user.login)
            return 0
        dbname = self.env.cr.dbname
        killed = 0
        for sid in store.list():
            try:
                session = store.get(sid)
                if (session.get('db') == dbname
                        and session.get('uid') == user.id):
                    store.delete(session)
                    killed += 1
            except Exception:
                _logger.exception("Erreur en supprimant la session %s", sid)
        if killed:
            _logger.info("Expiration forcee : %s session(s) Odoo supprimee(s) "
                         "pour %s (redirection vers la page de connexion)",
                         killed, user.login)
        return killed

    @api.model
    def _check_expired_sessions(self):
        """Cron : expire les sessions Odoo dont la duree de vie est ecoulee.

        Ne s'applique que si l'abonnement est expire et le mecanisme active :
        les utilisateurs concernes sont deconnectes immediatement.
        """
        if not self._is_enabled():
            self.sudo().search([]).unlink()
            return
        control = self.env['subscription.control'].sudo()
        if not control.check_expiration():
            return
        expired_sessions = self.sudo().search(
            [('expiry_datetime', '<=', fields.Datetime.now())])
        for session in expired_sessions:
            user = session.user_id
            session.unlink()
            if not user.active or user._is_admin():
                continue
            self._kill_user_sessions(user)
