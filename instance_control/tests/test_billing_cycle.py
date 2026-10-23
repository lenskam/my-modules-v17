# -*- coding: utf-8 -*-
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

FIXED_TODAY = date(2026, 10, 26)


@tagged('post_install', '-at_install')
class TestBillingCycle(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Cycle = self.env['instance.billing.cycle']
        self.Instance = self.env['instance.management']
        self.ReminderLog = self.env['instance.reminder.log']
        # Configuration par défaut explicite : facturation le 25, délai 15 jours
        param = self.env['ir.config_parameter'].sudo()
        param.set_param('instance_control.billing_day', '25')
        param.set_param('instance_control.payment_delay_days', '15')
        param.set_param('instance_control.reminder_days', '10,5,2,1')
        param.set_param('instance_control.suspension_alert_enabled', 'True')
        self.assertEqual(self.Instance.get_billing_day(), 25)
        self.assertEqual(self.Instance.get_payment_delay_days(), 15)

    def _create_instance(self, **kwargs):
        vals = {
            'name': 'Client A – Production',
            'url': 'https://clienta.test',
            'database': 'clienta_db',
            'login': 'api_user',
            'api_key': 'secret',
            'monthly_amount': 150.0,
        }
        vals.update(kwargs)
        return self.Instance.create(vals)

    def _mock_client(self, **attrs):
        client = MagicMock()
        for attr, value in attrs.items():
            setattr(client, attr, value)
        return patch.object(
            type(self.env['instance.management']),
            '_get_client', return_value=client), client

    def _patch_today(self, day=FIXED_TODAY):
        return patch.object(
            fields.Date, 'context_today', return_value=day)

    # ------------------------------------------------------------------
    # Calcul des dates : facturation + délai de paiement
    # ------------------------------------------------------------------

    def test_suspension_date_is_billing_date_plus_payment_delay(self):
        instance = self._create_instance()
        cycle = self.Cycle.create({
            'instance_id': instance.id,
            'billing_date': date(2026, 10, 25),
        })
        self.assertEqual(cycle.suspension_date, date(2026, 11, 9))

    def test_suspension_date_recomputed_when_billing_date_changes(self):
        instance = self._create_instance()
        cycle = self.Cycle.create({
            'instance_id': instance.id,
            'billing_date': date(2026, 10, 25),
        })
        cycle.billing_date = date(2026, 11, 25)
        self.assertEqual(cycle.suspension_date, date(2026, 12, 10))

    def test_suspension_date_follows_configured_delay(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'instance_control.payment_delay_days', '30')
        instance = self._create_instance()
        cycle = self.Cycle.create({
            'instance_id': instance.id,
            'billing_date': date(2026, 10, 25),
        })
        self.assertEqual(cycle.suspension_date, date(2026, 11, 24))

    # ------------------------------------------------------------------
    # Création du cycle au jour de facturation (par instance)
    # ------------------------------------------------------------------

    def test_billing_date_for_period_after_billing_day(self):
        today = date(2026, 10, 27)
        self.assertEqual(
            self.Cycle._billing_date_for_period(today, 25), date(2026, 10, 25))

    def test_billing_date_for_period_before_billing_day(self):
        today = date(2026, 10, 7)
        self.assertEqual(
            self.Cycle._billing_date_for_period(today, 25), date(2026, 9, 25))

    def test_billing_date_for_period_on_billing_day(self):
        today = date(2026, 10, 25)
        self.assertEqual(
            self.Cycle._billing_date_for_period(today, 25), date(2026, 10, 25))

    def test_billing_date_for_period_clamps_to_month_end(self):
        today = date(2026, 4, 30)
        self.assertEqual(
            self.Cycle._billing_date_for_period(today, 31), date(2026, 4, 30))

    def test_ensure_current_cycle_creates_once_per_instance(self):
        instance = self._create_instance()
        cycle = self.Cycle._ensure_current_cycle(FIXED_TODAY, instance)
        self.assertEqual(cycle.billing_date, date(2026, 10, 25))
        self.assertEqual(cycle.state, 'draft')
        again = self.Cycle._ensure_current_cycle(FIXED_TODAY, instance)
        self.assertEqual(cycle, again)
        self.assertEqual(self.Cycle.search_count([
            ('instance_id', '=', instance.id),
            ('billing_date', '=', date(2026, 10, 25)),
        ]), 1)

    def test_run_billing_cycles_activates_cycle_on_billing_day(self):
        instance = self._create_instance()
        with self._patch_today(), \
                patch.object(
                    type(self.Cycle), '_process_invoicing'), \
                patch.object(type(self.Cycle), '_process_reminders'), \
                patch.object(type(self.Cycle), '_process_suspension'), \
                patch.object(type(self.Cycle), '_retry_remote_suspension'):
            self.Cycle.run_billing_cycles()
        cycle = self.Cycle.search([('instance_id', '=', instance.id)])
        self.assertEqual(cycle.billing_date, date(2026, 10, 25))
        self.assertEqual(cycle.state, 'awaiting_payment')

    # ------------------------------------------------------------------
    # Rappels aux intervalles configurés + déduplication
    # ------------------------------------------------------------------

    def test_reminder_sent_at_configured_interval(self):
        instance = self._create_instance()
        cycle = self.Cycle.create({
            'instance_id': instance.id,
            'billing_date': date(2026, 10, 25),
        })
        cycle.state = 'awaiting_payment'
        # 25 oct + 15j = 9 nov ; J-5 = 4 nov
        cycle._process_reminders(date(2026, 11, 4))
        logs = self.ReminderLog.search([('cycle_id', '=', cycle.id)])
        self.assertEqual(logs.mapped('days_before'), [5])
        comments = cycle.message_ids.filtered(
            lambda m: m.message_type == 'comment')
        self.assertEqual(len(comments), 1)

    def test_reminder_message_contains_instance_name(self):
        instance = self._create_instance()
        cycle = self.Cycle.create({
            'instance_id': instance.id,
            'billing_date': date(2026, 10, 25),
        })
        cycle.state = 'awaiting_payment'
        cycle._process_reminders(date(2026, 11, 4))
        comments = cycle.message_ids.filtered(
            lambda m: m.message_type == 'comment')
        self.assertEqual(len(comments), 1)
        self.assertIn(instance.name, comments[0].body)

    def test_reminder_not_sent_outside_intervals(self):
        instance = self._create_instance()
        cycle = self.Cycle.create({
            'instance_id': instance.id,
            'billing_date': date(2026, 10, 25),
        })
        cycle.state = 'awaiting_payment'
        cycle._process_reminders(date(2026, 11, 6))  # J-3 : pas dans 10,5,2,1
        self.assertFalse(self.ReminderLog.search([('cycle_id', '=', cycle.id)]))

    def test_reminder_sent_only_once_per_interval(self):
        instance = self._create_instance()
        cycle = self.Cycle.create({
            'instance_id': instance.id,
            'billing_date': date(2026, 10, 25),
        })
        cycle.state = 'awaiting_payment'
        cycle._process_reminders(date(2026, 11, 4))
        cycle._process_reminders(date(2026, 11, 4))
        logs = self.ReminderLog.search([('cycle_id', '=', cycle.id)])
        self.assertEqual(len(logs), 1)

    def test_reminder_not_sent_after_suspension(self):
        instance = self._create_instance()
        cycle = self.Cycle.create({
            'instance_id': instance.id,
            'billing_date': date(2026, 10, 25),
        })
        cycle.state = 'suspended'
        cycle._process_reminders(date(2026, 11, 4))
        self.assertFalse(self.ReminderLog.search([('cycle_id', '=', cycle.id)]))

    # ------------------------------------------------------------------
    # Suspension à échéance via l'API distante
    # ------------------------------------------------------------------

    def test_suspension_on_due_date_calls_remote_api(self):
        instance = self._create_instance()
        cycle = self.Cycle.create({
            'instance_id': instance.id,
            'billing_date': date(2026, 10, 25),
        })
        cycle.state = 'awaiting_payment'
        patcher, client = self._mock_client()
        with patcher:
            cycle._process_suspension(date(2026, 11, 9))
        self.assertEqual(cycle.state, 'suspended')
        self.assertTrue(cycle.remote_suspended)
        client.set_expiration_date.assert_called_once_with(date(2026, 11, 9))
        client.block_access_if_expired.assert_called_once()
        self.assertEqual(instance.state, 'suspended')
        self.assertEqual(instance.expiration_date, date(2026, 11, 9))

    def test_suspension_not_triggered_before_due_date(self):
        instance = self._create_instance()
        cycle = self.Cycle.create({
            'instance_id': instance.id,
            'billing_date': date(2026, 10, 25),
        })
        cycle.state = 'awaiting_payment'
        patcher, client = self._mock_client()
        with patcher:
            cycle._process_suspension(date(2026, 11, 8))
        self.assertEqual(cycle.state, 'awaiting_payment')
        client.set_expiration_date.assert_not_called()

    def test_remote_failure_keeps_cycle_suspended_and_retries(self):
        instance = self._create_instance()
        cycle = self.Cycle.create({
            'instance_id': instance.id,
            'billing_date': date(2026, 10, 25),
        })
        cycle.state = 'awaiting_payment'
        failing = MagicMock()
        failing.set_expiration_date.side_effect = Exception('Instance down')
        with patch.object(
                type(self.env['instance.management']),
                '_get_client', return_value=failing):
            cycle._process_suspension(date(2026, 11, 9))
        self.assertEqual(cycle.state, 'suspended')
        self.assertFalse(cycle.remote_suspended)

        # Le passage suivant retente avec un client fonctionnel
        patcher, client = self._mock_client()
        with patcher:
            cycle._retry_remote_suspension(date(2026, 11, 10))
        self.assertTrue(cycle.remote_suspended)
        client.set_expiration_date.assert_called_once_with(date(2026, 11, 10))
        client.block_access_if_expired.assert_called_once()

    # ------------------------------------------------------------------
    # Paiement reçu : restauration distante
    # ------------------------------------------------------------------

    def test_mark_paid_restores_remote_access_after_suspension(self):
        instance = self._create_instance()
        instance.state = 'suspended'
        cycle = self.Cycle.create({
            'instance_id': instance.id,
            'billing_date': date(2026, 10, 25),
        })
        cycle.write({'state': 'suspended', 'remote_suspended': True})
        patcher, client = self._mock_client()
        with patcher:
            cycle.action_mark_paid()
        self.assertEqual(cycle.state, 'paid')
        self.assertEqual(cycle.paid_on, date.today())
        client.restore_access.assert_called_once()
        client.set_expiration_date.assert_called_once_with(
            date.today() + timedelta(days=30))
        self.assertEqual(instance.state, 'active')

    def test_mark_paid_on_awaiting_cycle(self):
        instance = self._create_instance()
        cycle = self.Cycle.create({
            'instance_id': instance.id,
            'billing_date': date(2026, 10, 25),
        })
        cycle.state = 'awaiting_payment'
        patcher, client = self._mock_client()
        with patcher:
            cycle.action_mark_paid()
        self.assertEqual(cycle.state, 'paid')
        client.set_expiration_date.assert_called_once_with(
            date.today() + timedelta(days=30))
        client.restore_access.assert_called_once()

    def test_mark_paid_twice_raises(self):
        instance = self._create_instance()
        cycle = self.Cycle.create({
            'instance_id': instance.id,
            'billing_date': date(2026, 10, 25),
        })
        cycle.state = 'awaiting_payment'
        patcher, _ = self._mock_client()
        with patcher:
            cycle.action_mark_paid()
        with self.assertRaises(Exception):
            cycle.action_mark_paid()

    # ------------------------------------------------------------------
    # Isolation d'erreurs entre instances (NF-2)
    # ------------------------------------------------------------------

    def test_run_billing_cycles_isolates_failing_instance(self):
        partner = self.env['res.partner'].create({'name': 'Client OK'})
        product = self.env['product.product'].create({
            'name': 'Abonnement Test',
            'type': 'service',
            'list_price': 150.0,
            'taxes_id': [(5, 0, 0)],
        })
        self.env['ir.config_parameter'].sudo().set_param(
            'instance_control.product_id', str(product.id))
        ok_instance = self._create_instance(
            name='OK', database='ok_db', url='https://ok.test',
            partner_id=partner.id)
        bad_instance = self._create_instance(
            name='KO', database='ko_db', url='https://ko.test',
            partner_id=False)
        with self._patch_today(), \
                patch.object(type(self.Cycle), '_process_reminders'), \
                patch.object(type(self.Cycle), '_process_suspension'), \
                patch.object(type(self.Cycle), '_retry_remote_suspension'):
            self.Cycle.run_billing_cycles()
        # L'instance sans client échoue sans casser les autres
        self.assertTrue(bad_instance.last_error)
        ok_cycle = self.Cycle.search([('instance_id', '=', ok_instance.id)])
        self.assertEqual(ok_cycle.state, 'awaiting_payment')
        self.assertTrue(ok_cycle.invoice_id)

    # ------------------------------------------------------------------
    # Configuration par instance (override → global)
    # ------------------------------------------------------------------

    def test_instance_billing_day_override(self):
        instance = self._create_instance(billing_day=5)
        cycle = self.Cycle._ensure_current_cycle(FIXED_TODAY, instance)
        # Le jour global est 25, l'instance impose le 5
        self.assertEqual(cycle.billing_date, date(2026, 10, 5))
        self.assertEqual(cycle.suspension_date, date(2026, 10, 20))

    def test_instance_payment_delay_override(self):
        instance = self._create_instance(payment_delay_days=10)
        cycle = self.Cycle.create({
            'instance_id': instance.id,
            'billing_date': date(2026, 10, 25),
        })
        # Le délai global est 15, l'instance impose 10
        self.assertEqual(cycle.suspension_date, date(2026, 11, 4))

    def test_instance_reminder_days_override(self):
        instance = self._create_instance(reminder_days='3')
        cycle = self.Cycle.create({
            'instance_id': instance.id,
            'billing_date': date(2026, 10, 25),
        })
        cycle.state = 'awaiting_payment'
        # Suspension le 9 nov : J-3 = 6 nov (intervalle de l'instance)
        cycle._process_reminders(date(2026, 11, 6))
        logs = self.ReminderLog.search([('cycle_id', '=', cycle.id)])
        self.assertEqual(logs.mapped('days_before'), [3])

    def test_instance_reminder_days_override_beats_global(self):
        instance = self._create_instance(reminder_days='3')
        cycle = self.Cycle.create({
            'instance_id': instance.id,
            'billing_date': date(2026, 10, 25),
        })
        cycle.state = 'awaiting_payment'
        # J-5 serait un intervalle GLOBAL : ignoré car l'instance impose '3'
        cycle._process_reminders(date(2026, 11, 4))
        self.assertFalse(self.ReminderLog.search([('cycle_id', '=', cycle.id)]))

    def test_suspension_alert_disabled_per_instance(self):
        instance = self._create_instance(suspension_alert_enabled=False)
        cycle = self.Cycle.create({
            'instance_id': instance.id,
            'billing_date': date(2026, 10, 25),
        })
        cycle.state = 'awaiting_payment'
        patcher, client = self._mock_client()
        with patcher:
            cycle._process_suspension(date(2026, 11, 9))
        self.assertEqual(cycle.state, 'suspended')
        client.set_expiration_date.assert_called_once()
        # Aucune alerte de suspension envoyée pour cette instance
        alerts = self.ReminderLog.search([
            ('cycle_id', '=', cycle.id),
            ('type', '=', 'suspension_alert'),
        ])
        self.assertFalse(alerts)
