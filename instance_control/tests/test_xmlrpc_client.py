# -*- coding: utf-8 -*-
"""Régression client XML-RPC : xmlrpc.client ne sait pas marshaler les
objets datetime.date — ni en argument de requête (côté contrôleur), ni
en retour de réponse (côté instance distante). Le client doit donc
n'échanger que des chaînes 'YYYY-MM-DD' côté contrôleur."""
import xmlrpc.client
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from odoo.addons.instance_control.models.odoo_xmlrpc_client import (
    OdooXmlrpcClient,
)
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOdooXmlrpcClient(TransactionCase):

    def _make_client(self, execute_result=None):
        proxy = MagicMock()
        proxy.authenticate.return_value = 1
        proxy.execute_kw.return_value = execute_result
        with patch.object(xmlrpc.client, 'ServerProxy', return_value=proxy):
            client = OdooXmlrpcClient(
                'http://remote.test', 'remote_db', 'api_user', 'secret')
        return client, proxy

    def _sent_args(self, proxy):
        """Arguments positionnels transmis au modèle distant."""
        call_args, _kwargs = proxy.execute_kw.call_args
        return call_args[5]

    def test_set_expiration_date_sends_string_not_date(self):
        client, proxy = self._make_client()
        client.set_expiration_date(date(2026, 12, 31))
        sent = self._sent_args(proxy)
        self.assertEqual(sent, ['2026-12-31'])
        # Preuve « câble » : la requête doit être marshallable telle quelle
        xmlrpc.client.dumps((sent,), methodresponse=1, allow_none=False)

    def test_set_expiration_date_accepts_datetime(self):
        client, proxy = self._make_client()
        client.set_expiration_date(datetime(2026, 12, 31, 8, 30))
        self.assertEqual(self._sent_args(proxy), ['2026-12-31'])

    def test_set_expiration_date_falsy_sends_false(self):
        client, proxy = self._make_client()
        client.set_expiration_date(None)
        self.assertEqual(self._sent_args(proxy), [False])

    def test_get_expiration_date_parses_string_response(self):
        client, _proxy = self._make_client(execute_result='2026-12-31')
        self.assertEqual(client.get_expiration_date(), date(2026, 12, 31))

    def test_get_expiration_date_handles_false_response(self):
        client, _proxy = self._make_client(execute_result=False)
        self.assertIsNone(client.get_expiration_date())
