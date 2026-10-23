# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBillingCycle(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Cycle = self.env['subscription.billing.cycle']
        self.Control = self.env['subscription.control']
        self.ReminderLog = self.env['subscription.reminder.log']
        # Configuration par défaut explicite : facturation le 25, délai 15 jours
        param = self.env['ir.config_parameter'].sudo()
        param.set_param('subscription.billing_day', '25')
        param.set_param('subscription.payment_delay_days', '15')
        param.set_param('subscription.reminder_days', '10,5,2,1')
        param.set_param('subscription.suspension_alert', 'True')
        # Mode de blocage explicite : les tests de ce module couvrent la
        # révocation de groupes (comportement historique)
        param.set_param('subscription.enforcement_mode', 'groups')
        # Rend les tests hermetiques : ignore la configuration reelle de la BD
        self.Control.set_expiration_date(None)
        self.Cycle.search([]).unlink()
        self.assertEqual(self.Control.get_billing_day(), 25)
        self.assertEqual(self.Control.get_payment_delay_days(), 15)

    def _create_user(self, login):
        return self.env['res.users'].create({
            'name': login.title(),
            'login': login,
            'email': '%s@test.com' % login,
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })

    # ------------------------------------------------------------------
    # Calcul de la date de suspension : facturation + délai de paiement
    # ------------------------------------------------------------------

    def test_suspension_date_is_billing_date_plus_payment_delay(self):
        cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        self.assertEqual(cycle.suspension_date, date(2026, 11, 9))

    def test_suspension_date_recomputed_when_billing_date_changes(self):
        cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        cycle.billing_date = date(2026, 11, 25)
        self.assertEqual(cycle.suspension_date, date(2026, 12, 10))

    def test_suspension_date_follows_configured_delay(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'subscription.payment_delay_days', '30')
        cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        self.assertEqual(cycle.suspension_date, date(2026, 11, 24))

    # ------------------------------------------------------------------
    # Création du cycle au jour de facturation
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

    def test_ensure_current_cycle_creates_once(self):
        today = date(2026, 10, 26)
        cycle = self.Cycle._ensure_current_cycle(today)
        self.assertEqual(cycle.billing_date, date(2026, 10, 25))
        again = self.Cycle._ensure_current_cycle(today)
        self.assertEqual(cycle, again)
        self.assertEqual(
            self.Cycle.search_count([('billing_date', '=', date(2026, 10, 25))]), 1)

    def test_run_billing_cycle_activates_cycle_on_billing_day(self):
        self.Cycle.create({'billing_date': date(2026, 10, 25)})
        today = date(2026, 10, 26)
        cycle = self.Cycle.search([('billing_date', '=', date(2026, 10, 25))])
        cycle._process_state(today)
        self.assertEqual(cycle.state, 'awaiting_payment')

    # ------------------------------------------------------------------
    # Rappels aux intervalles configurés + déduplication
    # ------------------------------------------------------------------

    def test_reminder_sent_at_configured_interval(self):
        cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        cycle.state = 'awaiting_payment'
        # 25 oct + 15j = 9 nov ; J-5 = 4 nov
        cycle._process_reminders(date(2026, 11, 4))
        logs = self.ReminderLog.search([('cycle_id', '=', cycle.id)])
        self.assertEqual(logs.mapped('days_before'), [5])
        comments = cycle.message_ids.filtered(
            lambda m: m.message_type == 'comment')
        self.assertEqual(len(comments), 1)

    def test_reminder_message_contains_database_name(self):
        cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        cycle.state = 'awaiting_payment'
        cycle._process_reminders(date(2026, 11, 4))
        comments = cycle.message_ids.filtered(
            lambda m: m.message_type == 'comment')
        self.assertEqual(len(comments), 1)
        self.assertIn(self.env.cr.dbname, comments[0].body)

    def test_reminder_not_sent_outside_intervals(self):
        cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        cycle.state = 'awaiting_payment'
        cycle._process_reminders(date(2026, 11, 6))  # J-3 : pas dans 10,5,2,1
        self.assertFalse(self.ReminderLog.search([('cycle_id', '=', cycle.id)]))

    def test_reminder_sent_only_once_per_interval(self):
        cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        cycle.state = 'awaiting_payment'
        cycle._process_reminders(date(2026, 11, 4))
        cycle._process_reminders(date(2026, 11, 4))
        logs = self.ReminderLog.search([('cycle_id', '=', cycle.id)])
        self.assertEqual(len(logs), 1)

    def test_reminder_not_sent_after_suspension(self):
        cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        cycle.state = 'suspended'
        cycle._process_reminders(date(2026, 11, 4))
        self.assertFalse(self.ReminderLog.search([('cycle_id', '=', cycle.id)]))

    # ------------------------------------------------------------------
    # Suspension à échéance + blocage d'accès
    # ------------------------------------------------------------------

    def test_suspension_on_due_date_revokes_access(self):
        user = self._create_user('suspended_user')
        # Groupe applicatif (non implicite de group_user) pour vérifier la révocation
        user.groups_id = [(4, self.env.ref('base.group_multi_company').id)]
        self.assertTrue(user.has_group('base.group_multi_company'))
        cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        cycle.state = 'awaiting_payment'
        # 9 novembre : date de suspension
        cycle._process_suspension(date(2026, 11, 9))
        self.assertEqual(cycle.state, 'suspended')
        self.assertFalse(user.has_group('base.group_multi_company'))
        self.assertTrue(user.has_group('base.group_user'))

    def test_suspension_not_triggered_before_due_date(self):
        cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        cycle.state = 'awaiting_payment'
        cycle._process_suspension(date(2026, 11, 8))
        self.assertEqual(cycle.state, 'awaiting_payment')

    def test_check_expiration_true_when_cycle_suspended(self):
        self.Cycle.create({
            'billing_date': date(2026, 10, 25),
            'state': 'suspended',
        })
        self.assertTrue(self.Control.check_expiration())

    def test_check_expiration_false_when_cycle_paid(self):
        self.Cycle.create({
            'billing_date': date(2026, 10, 25),
            'state': 'paid',
        })
        self.assertFalse(self.Control.check_expiration())

    def test_check_expiration_false_when_no_cycle(self):
        self.assertFalse(self.Control.check_expiration())

    def test_check_credentials_blocked_when_suspended(self):
        from odoo.exceptions import AccessDenied
        user = self._create_user('blocked_login')
        user.password = 'secret123'
        self.Cycle.create({
            'billing_date': date(2026, 10, 25),
            'state': 'suspended',
        })
        with self.assertRaises(AccessDenied):
            user.with_user(user)._check_credentials('secret123', {})

    def test_check_credentials_allowed_when_paid(self):
        user = self._create_user('allowed_login')
        user.password = 'secret123'
        self.Cycle.create({
            'billing_date': date(2026, 10, 25),
            'state': 'paid',
        })
        user.with_user(user)._check_credentials('secret123', {})

    # ------------------------------------------------------------------
    # Paiement reçu : restauration de l'accès
    # ------------------------------------------------------------------

    def test_mark_paid_restores_access_after_suspension(self):
        user = self._create_user('restored_user')
        user.groups_id = [(4, self.env.ref('base.group_multi_company').id)]
        cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        cycle.state = 'awaiting_payment'
        cycle._process_suspension(date(2026, 11, 9))
        self.assertEqual(cycle.state, 'suspended')
        self.assertTrue(self.Control.check_expiration())
        self.assertFalse(user.has_group('base.group_multi_company'))

        cycle.action_mark_paid()
        self.assertEqual(cycle.state, 'paid')
        self.assertEqual(cycle.paid_on, date.today())
        self.assertFalse(self.Control.check_expiration())
        self.assertTrue(user.has_group('base.group_user'))
        self.assertTrue(user.has_group('base.group_multi_company'))

    def test_mark_paid_on_awaiting_cycle(self):
        cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        cycle.state = 'awaiting_payment'
        cycle.action_mark_paid()
        self.assertEqual(cycle.state, 'paid')

    def test_mark_paid_twice_raises(self):
        cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        cycle.state = 'awaiting_payment'
        cycle.action_mark_paid()
        with self.assertRaises(Exception):
            cycle.action_mark_paid()

    # ------------------------------------------------------------------
    # Extension : repousse la suspension du cycle courant
    # ------------------------------------------------------------------

    def test_extend_subscription_postpones_cycle_suspension(self):
        cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        cycle.state = 'suspended'
        self.Control.set_expiration_date(date(2026, 11, 1))
        self.Control.extend_subscription(days=30)
        cycle.invalidate_model(['suspension_date', 'state'])
        self.assertEqual(cycle.state, 'awaiting_payment')
        self.assertEqual(cycle.suspension_date, date(2026, 12, 1))

    def test_extend_resets_reminder_logs(self):
        cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        cycle.state = 'awaiting_payment'
        cycle._process_reminders(date(2026, 11, 4))
        self.assertTrue(cycle.reminder_log_ids)
        self.Control.set_expiration_date(date(2026, 11, 1))
        self.Control.extend_subscription(days=30)
        self.assertFalse(cycle.reminder_log_ids)

    # ------------------------------------------------------------------
    # Alerte de session (modal au chargement du webclient)
    # ------------------------------------------------------------------

    def test_session_alert_blocking_for_suspended_user(self):
        user = self._create_user('alert_suspended')
        self.Cycle.create({
            'billing_date': date(2026, 10, 25),
            'state': 'suspended',
        })
        self.Control._revoke_app_access()
        alert = self.Control.with_user(user).get_session_alert()
        self.assertTrue(alert['show'])
        self.assertFalse(alert['closable'])

    def test_session_alert_hidden_for_active_session(self):
        self.assertEqual(self.Control.get_session_alert(), {'show': False})

    def test_session_alert_hidden_when_alerts_disabled(self):
        user = self._create_user('alert_disabled')
        self.Cycle.create({
            'billing_date': date(2026, 10, 25),
            'state': 'suspended',
        })
        self.Control._revoke_app_access()
        self.env['ir.config_parameter'].sudo().set_param(
            'subscription.suspension_alert', 'False')
        alert = self.Control.with_user(user).get_session_alert()
        self.assertEqual(alert, {'show': False})

    # ------------------------------------------------------------------
    # Message Discuss (discussion directe avec OdooBot)
    # ------------------------------------------------------------------

    def test_discuss_message_sent_to_recipient(self):
        user = self._create_user('discuss_user')
        partner = user.partner_id
        cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        cycle.state = 'awaiting_payment'
        self.env['ir.config_parameter'].sudo().set_param(
            'subscription.recipient_partner_ids', str(partner.id))
        cycle._send_reminder(5, 5)
        channel_model = self.env['discuss.channel'] if 'discuss.channel' in self.env \
            else self.env['mail.channel']
        channel = channel_model.sudo().channel_get(partners_to=[partner.id])
        comments = channel.message_ids.filtered(
            lambda m: m.message_type == 'comment')
        self.assertEqual(len(comments), 1)

    def test_discuss_message_skipped_for_partner_without_user(self):
        partner = self.env['res.partner'].create({
            'name': 'Contact Sans Compte',
            'email': 'sans.compte@test.com',
        })
        self.Cycle._send_discuss_messages(partner, 'Test message')
        channel_model = self.env['discuss.channel'] if 'discuss.channel' in self.env \
            else self.env['mail.channel']
        channels = channel_model.search([('channel_member_ids.partner_id', '=', partner.id)])
        self.assertFalse(channels)


@tagged('post_install', '-at_install')
class TestReminderDaysConfig(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Control = self.env['subscription.control']
        param = self.env['ir.config_parameter'].sudo()
        param.set_param('subscription.reminder_days', '10, 5 ,2, 1, 10')

    def test_reminder_days_parsed_sorted_deduplicated(self):
        self.assertEqual(self.Control.get_reminder_days(), [10, 5, 2, 1])

    def test_reminder_days_default_when_missing(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'subscription.reminder_days', '')
        self.assertEqual(self.Control.get_reminder_days(), [10, 5, 2, 1])

    def test_reminder_days_ignores_invalid_values(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'subscription.reminder_days', 'abc,7,-3,3')
        self.assertEqual(self.Control.get_reminder_days(), [7, 3])
