# -*- coding: utf-8 -*-
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRemoteActions(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Instance = self.env['instance.management']
        self.Cycle = self.env['instance.billing.cycle']
        self.instance = self.Instance.create({
            'name': 'Client Remote',
            'url': 'https://remote.test',
            'database': 'remote_db',
            'login': 'api_user',
            'api_key': 'secret',
        })

    def _mock_client(self, **attrs):
        client = MagicMock()
        for attr, value in attrs.items():
            setattr(client, attr, value)
        return patch.object(
            type(self.env['instance.management']),
            '_get_client', return_value=client), client

    # ------------------------------------------------------------------
    # Actions de suspension / rétablissement
    # ------------------------------------------------------------------

    def test_action_suspend_now_calls_remote_api(self):
        patcher, client = self._mock_client()
        with patcher:
            self.instance.action_suspend_now()
        self.assertEqual(self.instance.state, 'suspended')
        self.assertEqual(
            self.instance.expiration_date, date.today())
        client.set_expiration_date.assert_called_once_with(date.today())
        client.block_access_if_expired.assert_called_once()

    def test_action_restore_calls_remote_api(self):
        self.instance.state = 'suspended'
        patcher, client = self._mock_client()
        with patcher:
            self.instance.action_restore()
        self.assertEqual(self.instance.state, 'active')
        client.restore_access.assert_called_once()
        client.set_expiration_date.assert_called_once_with(
            date.today() + timedelta(days=30))

    # ------------------------------------------------------------------
    # Synchronisation du statut distant
    # ------------------------------------------------------------------

    def test_sync_status_reads_remote_expiration(self):
        patcher, client = self._mock_client()
        client.get_expiration_date.return_value = date(2026, 12, 31)
        with patcher:
            self.instance.action_sync_status()
        self.assertEqual(self.instance.expiration_date, date(2026, 12, 31))
        self.assertTrue(self.instance.last_check)
        self.assertFalse(self.instance.last_error)
        self.assertEqual(self.instance.state, 'active')

    def test_sync_status_failure_records_error_silently(self):
        client = MagicMock()
        client.get_expiration_date.side_effect = Exception('Connexion refusée')
        with patch.object(
                type(self.env['instance.management']),
                '_get_client', return_value=client):
            self.instance.action_sync_status()
        self.assertEqual(self.instance.state, 'unreachable')
        self.assertIn('Connexion refusée', self.instance.last_error)

    def test_test_connection_raises_for_unreachable_instance(self):
        client = MagicMock()
        client.get_expiration_date.side_effect = Exception('Timeout')
        with patch.object(
                type(self.env['instance.management']),
                '_get_client', return_value=client):
            # NB : assertRaises annule le savepoint à la levée (framework
            # Odoo 17), l'état 'unreachable' écrit dans le bloc est revertu ;
            # l'enregistrement de l'erreur est couvert par le test silencieux.
            with self.assertRaises(UserError):
                self.instance.action_test_connection()

    def test_sync_all_status_isolates_failing_instances(self):
        ok = self.Instance.create({
            'name': 'OK',
            'url': 'https://ok.test',
            'database': 'ok_db',
            'login': 'api_user',
            'api_key': 'secret',
        })
        bad = self.Instance.create({
            'name': 'BAD',
            'url': 'https://bad.test',
            'database': 'bad_db',
            'login': 'api_user',
            'api_key': 'secret',
        })
        good_client = MagicMock()
        good_client.get_expiration_date.return_value = date(2027, 1, 15)
        bad_client = MagicMock()
        bad_client.get_expiration_date.side_effect = Exception('KO')

        def fake_get_client(self_instance):
            return bad_client if self_instance == bad else good_client

        with patch.object(
                type(self.env['instance.management']),
                '_get_client', fake_get_client):
            self.Instance._sync_all_status()
        self.assertEqual(ok.expiration_date, date(2027, 1, 15))
        self.assertEqual(bad.state, 'unreachable')
        self.assertIn('KO', bad.last_error)

    # ------------------------------------------------------------------
    # Wizard de prolongation
    # ------------------------------------------------------------------

    def test_extend_wizard_updates_remote_and_cycle(self):
        cycle = self.Cycle.create({
            'instance_id': self.instance.id,
            'billing_date': date(2026, 10, 25),
        })
        cycle.write({'state': 'suspended', 'remote_suspended': True})
        target = date(2026, 12, 15)
        patcher, client = self._mock_client()
        with patcher:
            wizard = self.env['instance.extend.wizard'].create({
                'instance_id': self.instance.id,
                'new_expiration_date': target,
            })
            wizard.action_extend()
        self.assertEqual(self.instance.state, 'active')
        self.assertEqual(self.instance.expiration_date, target)
        client.set_expiration_date.assert_called_once_with(target)
        client.restore_access.assert_called_once()
        self.assertEqual(cycle.state, 'awaiting_payment')
        self.assertEqual(cycle.suspension_date, target)
        self.assertFalse(cycle.remote_suspended)

    def test_extend_wizard_defaults_to_days(self):
        patcher, client = self._mock_client()
        with patcher:
            wizard = self.env['instance.extend.wizard'].create({
                'instance_id': self.instance.id,
                'days': 45,
            })
            wizard.action_extend()
        client.set_expiration_date.assert_called_once_with(
            date.today() + timedelta(days=45))

    # ------------------------------------------------------------------
    # Wizard de report de suspension
    # ------------------------------------------------------------------

    def test_postpone_wizard_restores_remote_when_suspended(self):
        cycle = self.Cycle.create({
            'instance_id': self.instance.id,
            'billing_date': date(2026, 10, 25),
        })
        cycle.write({'state': 'suspended', 'remote_suspended': True})
        new_date = date(2026, 12, 1)
        patcher, client = self._mock_client()
        with patcher:
            wizard = self.env['instance.postpone.wizard'].create({
                'cycle_id': cycle.id,
                'new_suspension_date': new_date,
            })
            wizard.action_postpone()
        self.assertEqual(cycle.state, 'awaiting_payment')
        self.assertEqual(cycle.suspension_date, new_date)
        client.set_expiration_date.assert_called_once_with(new_date)
        client.restore_access.assert_called_once()
