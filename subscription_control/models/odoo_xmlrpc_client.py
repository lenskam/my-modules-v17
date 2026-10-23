# -*- coding: utf-8 -*-
"""Client XML-RPC minimal pour interroger un Odoo distant (facturation).

Utilise la bibliotheque standard xmlrpc.client (endpoints /xmlrpc/2/common
et /xmlrpc/2/object, compatibles Odoo 11 a 17+). Timeout configurable,
erreurs explicites pour ne jamais casser le cron de facturation.
"""
import logging
import xmlrpc.client
from socket import setdefaulttimeout, getdefaulttimeout

from odoo.exceptions import UserError
from odoo import _

_logger = logging.getLogger(__name__)


class RemoteInvoiceNotFound(Exception):
    """Aucune facture distante ne correspond aux criteres."""


class OdooXmlrpcClient:
    """Client leger pour un Odoo distant."""

    def __init__(self, url, db, user, api_key, timeout=10):
        if not all([url, db, user, api_key]):
            raise UserError(_(
                "Connexion à l'Odoo de facturation incomplète : "
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
            raise UserError(_(
                "Impossible de se connecter à l'Odoo de facturation : %s") % e)
        finally:
            setdefaulttimeout(old_timeout)
        if not self.uid:
            raise UserError(_(
                "Authentification échouée sur l'Odoo de facturation "
                "(utilisateur/clé API invalides)."))
        self.models = xmlrpc.client.ServerProxy('%s/xmlrpc/2/object' % self.url)

    def execute_kw(self, model, method, args, kwargs=None):
        old_timeout = getdefaulttimeout()
        try:
            setdefaulttimeout(self.timeout)
            return self.models.execute_kw(
                self.db, self.uid, self.api_key, model, method, args, kwargs or {})
        finally:
            setdefaulttimeout(old_timeout)

    def search_read(self, model, domain, fields, limit=1, order=None):
        kwargs = {'fields': fields, 'limit': limit}
        if order:
            kwargs['order'] = order
        return self.execute_kw(model, 'search_read', [domain], kwargs)

    def find_invoice(self, expected_ref=None, partner_id=None):
        """Recherche hybride (B3) : d'abord par reference, puis par partenaire.

        Retourne un dict avec : id, name, ref, amount_total, payment_state,
        currency_id, partner_id, invoice_date. Leve RemoteInvoiceNotFound
        si aucune facture correspondante n'est trouvee.
        """
        base_fields = ['name', 'ref', 'amount_total', 'payment_state',
                       'currency_id', 'partner_id', 'invoice_date']
        base_domain = [('move_type', '=', 'out_invoice'), ('state', '=', 'posted')]
        if expected_ref:
            domain = base_domain + [
                '|', ('ref', '=', expected_ref), ('name', '=', expected_ref)]
            results = self.search_read('account.move', domain, base_fields, limit=1)
            if results:
                _logger.info("Facture trouvee par reference %s", expected_ref)
                return results[0]
        if partner_id:
            domain = base_domain + [('partner_id', '=', partner_id)]
            results = self.search_read(
                'account.move', domain, base_fields,
                limit=1, order='invoice_date desc')
            if results:
                _logger.info("Facture trouvee pour le partenaire %s", partner_id)
                return results[0]
        raise RemoteInvoiceNotFound(
            "Aucune facture trouvee (ref=%s, partner_id=%s)"
            % (expected_ref, partner_id))
