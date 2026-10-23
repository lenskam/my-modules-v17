# -*- coding: utf-8 -*-
from datetime import date
from unittest.mock import patch

from odoo.exceptions import AccessDenied
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEnforcementMode(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Control = self.env['subscription.control']
        self.Param = self.env['ir.config_parameter'].sudo()
        # Etat propre : plus aucun parametre de mode ni ancien booleen
        for key in ('subscription.enforcement_mode',
                    'subscription.force_session_expiry',
                    'subscription.force_session_expiry_delay'):
            self.Param.set_param(key, '')

    def _set_legacy_bool(self, value):
        # set_param('') supprimerait le parametre : on stocke 'False' explicitement
        self.Param.set_param('subscription.force_session_expiry', value)

    def test_mode_explicit_wins(self):
        self.Param.set_param('subscription.enforcement_mode', 'none')
        self._set_legacy_bool('True')
        self.assertEqual(self.Control.get_enforcement_mode(), 'none')

    def test_mode_fallback_from_legacy_true(self):
        # Instance existante avec l'ancien booleen actif -> session preserve
        self._set_legacy_bool('True')
        self.assertEqual(self.Control.get_enforcement_mode(), 'session')

    def test_mode_fallback_from_legacy_false(self):
        # Instance existante sans l'ancien booleen -> revocation preservee
        self._set_legacy_bool('False')
        self.assertEqual(self.Control.get_enforcement_mode(), 'groups')

    def test_mode_default_session_for_fresh_install(self):
        self.assertEqual(self.Control.get_enforcement_mode(), 'session')

    def test_block_access_revokes_only_in_groups_mode(self):
        self.Control.set_expiration_date(date(2020, 1, 1))
        user = self.env['res.users'].create({
            'name': 'Revoke Mode', 'login': 'revoke_mode',
            'email': 'revoke_mode@test.com',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('base.group_multi_company').id,
            ])],
        })
        self.Param.set_param('subscription.enforcement_mode', 'groups')
        self.Control.block_access_if_expired()
        self.assertFalse(user.has_group('base.group_multi_company'))
        # En mode session : pas de revocation
        self.Param.set_param('subscription.enforcement_mode', 'session')
        self.Control.restore_access()
        user.groups_id = [(4, self.env.ref('base.group_multi_company').id)]
        self.Control.block_access_if_expired()
        self.assertTrue(user.has_group('base.group_multi_company'))

    def test_login_blocked_in_session_and_groups_but_not_none(self):
        user = self.env['res.users'].create({
            'name': 'Login Mode', 'login': 'login_mode',
            'email': 'login_mode@test.com',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        user.password = 'secret123'
        self.Control.set_expiration_date(date(2020, 1, 1))
        for mode in ('session', 'groups'):
            self.Param.set_param('subscription.enforcement_mode', mode)
            with self.assertRaises(AccessDenied):
                user.with_user(user)._check_credentials('secret123', {})
        self.Param.set_param('subscription.enforcement_mode', 'none')
        user.with_user(user)._check_credentials('secret123', {})

    def test_session_expiry_active_only_in_session_mode(self):
        Session = self.env['subscription.session']
        self.Param.set_param('subscription.enforcement_mode', 'session')
        self.assertTrue(Session._is_enabled())
        for mode in ('groups', 'none'):
            self.Param.set_param('subscription.enforcement_mode', mode)
            self.assertFalse(Session._is_enabled())

    def test_session_cron_runs_without_error(self):
        # Regression : le cron ne doit jamais lever (get_current_record etc.)
        Session = self.env['subscription.session']
        user = self.env['res.users'].create({
            'name': 'Sess Cron', 'login': 'sess_cron',
            'email': 'sess_cron@test.com',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        Session.create({'user_id': user.id,
                        'expiry_datetime': '2020-01-01 00:00:00'})
        self.Param.set_param('subscription.enforcement_mode', 'session')
        self.Control.set_expiration_date(None)  # abonnement actif
        Session._check_expired_sessions()  # ne doit pas lever
        self.Param.set_param('subscription.enforcement_mode', 'none')
        Session._check_expired_sessions()  # ne doit pas lever non plus


@tagged('post_install', '-at_install')
class TestFeatureToggles(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Control = self.env['subscription.control']
        self.Cycle = self.env['subscription.billing.cycle']
        self.Param = self.env['ir.config_parameter'].sudo()
        for key in ('subscription.billing_engine_enabled',
                    'subscription.email_alerts_enabled',
                    'subscription.internal_alerts_enabled'):
            self.Param.set_param(key, '')
        self.Param.set_param('subscription.enforcement_mode', 'groups')
        self.Control.set_expiration_date(None)
        self.Cycle.search([]).unlink()
        self.Param.set_param('subscription.recipient_emails', 'admin@test.com')
        self.Param.set_param('subscription.recipient_partner_ids', '')
        self.Param.set_param('subscription.reminder_days', '1')

    def test_toggles_default_true_when_missing(self):
        self.assertTrue(self.Control.is_billing_engine_enabled())
        self.assertTrue(self.Control.is_email_alerts_enabled())
        self.assertTrue(self.Control.is_internal_alerts_enabled())

    def test_billing_engine_disabled_skips_cycle_creation(self):
        self.Param.set_param('subscription.billing_engine_enabled', 'False')
        self.Cycle.run_billing_cycle()
        self.assertFalse(self.Cycle.search([]))

    def test_billing_engine_enabled_creates_cycle(self):
        today = date.today()
        self.Cycle.run_billing_cycle()
        self.assertTrue(self.Cycle.search([]))

    def test_email_alerts_disabled_skips_email(self):
        cycle = self.Cycle.create({'billing_date': date(2020, 1, 25)})
        cycle.write({'state': 'awaiting_payment'})
        self.Param.set_param('subscription.email_alerts_enabled', 'False')
        sent = cycle._send_cycle_email(False, '[sc-test] titre email')
        self.assertFalse(sent)
        self.assertFalse(self.env['mail.mail'].search([
            ('subject', '=', '[sc-test] titre email')]))

    def test_internal_alerts_disabled_skips_chatter_and_discuss(self):
        cycle = self.Cycle.create({'billing_date': date(2020, 1, 25)})
        cycle.write({'state': 'awaiting_payment'})
        before = self.env['mail.message'].search_count([])
        self.Param.set_param('subscription.internal_alerts_enabled', 'False')
        cycle._send_reminder(1, 1)
        self.assertEqual(
            self.env['mail.message'].search_count([]), before,
            "Aucun message ne doit être posté quand les alertes natives sont coupées")

    def test_internal_alerts_enabled_posts_chatter(self):
        cycle = self.Cycle.create({'billing_date': date(2020, 1, 25)})
        cycle.write({'state': 'awaiting_payment'})
        before = self.env['mail.message'].search_count([])
        cycle._send_reminder(1, 1)
        self.assertGreater(
            self.env['mail.message'].search_count([]), before)

    def test_session_alert_hidden_when_internal_alerts_disabled(self):
        self.Param.set_param('subscription.suspension_alert', 'True')
        self.Param.set_param('subscription.internal_alerts_enabled', 'False')
        alert = self.env['subscription.billing.cycle'].get_session_alert()
        self.assertFalse(alert['show'])
