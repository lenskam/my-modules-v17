# -*- coding: utf-8 -*-
"""Client XML-RPC minimal pour piloter une instance Odoo gérée à distance.

Utilise la bibliothèque standard xmlrpc.client (endpoints /xmlrpc/2/common et
/xmlrpc/2/object, compatibles Odoo 11 à 17+). Timeout configurable, erreurs
explicites pour ne jamais casser le cron du contrôleur. Les commandes de
contrôle ciblent le modèle `subscription.control` exposé par le module client.
"""
import logging
import xmlrpc.client
from datetime import date, datetime
from socket import setdefaulttimeout, getdefaulttimeout

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

CONTROL_MODEL = 'subscription.control'


class RemoteInstanceUnreachable(Exception):
    """L'instance distante n'a pas pu être jointe ou authentifiée."""


class OdooXmlrpcClient:
    """Client léger pour piloter une instance Odoo distante."""

    def __init__(self, url, db, user, api_key, timeout=10):
        if not all([url, db, user, api_key]):
            raise UserError(_(
                "Connexion à l'instance incomplète : "
                "URL, base, utilisateur et clé API sont requis."))
        self.url = url.rstrip('/')
        self.db = db
        self.user = user
        self.api_key = api_key
        self.timeout = timeout
        common = xmlrpc.client.ServerProxy('%s/xmlrpc/2/common' % self.url)
        old_timeout = getdefaulttimeout()
        try:
            setdefaulttimeout(timeout)
            self.uid = common.authenticate(db, user, api_key, {})
        except Exception as e:
            raise RemoteInstanceUnreachable(
                _("Impossible de joindre l'instance distante : %s") % e)
        finally:
            setdefaulttimeout(old_timeout)
        if not self.uid:
            raise RemoteInstanceUnreachable(_(
                "Authentification échouée sur l'instance distante "
                "(utilisateur/clé API invalides)."))
        self.models = xmlrpc.client.ServerProxy('%s/xmlrpc/2/object' % self.url)

    def execute_kw(self, model, method, args, kwargs=None):
        old_timeout = getdefaulttimeout()
        try:
            setdefaulttimeout(self.timeout)
            return self.models.execute_kw(
                self.db, self.uid, self.api_key, model, method, args,
                kwargs or {})
        finally:
            setdefaulttimeout(old_timeout)

    def call_control_method(self, method, *args):
        """Exécute une méthode publique de `subscription.control` à distance."""
        return self.execute_kw(CONTROL_MODEL, method, list(args))

    @staticmethod
    def _to_date(value):
        """Normalise la valeur distante (date, datetime, str) en datetime.date."""
        if not value:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
        except ValueError:
            return None

    def get_expiration_date(self):
        """Lit la date d'expiration distante (None si non définie)."""
        return self._to_date(self.call_control_method('get_expiration_date'))

    def set_expiration_date(self, date_obj):
        """Définit la date d'expiration distante.

        XML-RPC ne sait pas marshaler les objets datetime.date (côté
        client comme côté serveur) : la date est envoyée en chaîne
        'YYYY-MM-DD', acceptée par subscription.control distant.
        """
        if isinstance(date_obj, datetime):
            date_obj = date_obj.date()
        if isinstance(date_obj, date):
            date_obj = date_obj.isoformat()
        return self.call_control_method('set_expiration_date', date_obj or False)

    def block_access_if_expired(self):
        """Bloque l'accès aux applications sur l'instance distante."""
        return self.call_control_method('block_access_if_expired')

    def restore_access(self):
        """Rétablit l'accès aux applications sur l'instance distante."""
        return self.call_control_method('restore_access')

    def extend_subscription(self, days):
        """Prolonge l'abonnement distant de X jours (méthode client)."""
        return self.call_control_method('extend_subscription', int(days))
