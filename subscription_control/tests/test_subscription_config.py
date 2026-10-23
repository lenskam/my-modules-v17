# -*- coding: utf-8 -*-
from datetime import date

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSubscriptionConfig(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Control = self.env['subscription.control']

    def test_billing_day_default_is_25(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'subscription.billing_day', '')
        self.assertEqual(self.Control.get_billing_day(), 25)

    def test_billing_day_invalid_falls_back_to_default(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'subscription.billing_day', 'abc')
        self.assertEqual(self.Control.get_billing_day(), 25)

    def test_billing_day_out_of_range_falls_back_to_default(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'subscription.billing_day', '99')
        self.assertEqual(self.Control.get_billing_day(), 25)

    def test_payment_delay_default_is_15(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'subscription.payment_delay_days', '')
        self.assertEqual(self.Control.get_payment_delay_days(), 15)

    def test_suspension_alert_enabled_by_default(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'subscription.suspension_alert', '')
        self.assertTrue(self.Control.is_suspension_alert_enabled())

    def test_suspension_alert_can_be_disabled(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'subscription.suspension_alert', 'False')
        self.assertFalse(self.Control.is_suspension_alert_enabled())

    def test_recipient_partner_ids_round_trip(self):
        partner = self.env['res.partner'].create({
            'name': 'Destinataire Test',
            'email': 'destinataire@test.com',
        })
        param = self.env['ir.config_parameter'].sudo()
        param.set_param('subscription.recipient_partner_ids', str(partner.id))
        partners = self.Control.get_recipient_partner_ids()
        self.assertEqual(partners.ids, [partner.id])

    def test_recipient_partner_ids_ignores_deleted_records(self):
        param = self.env['ir.config_parameter'].sudo()
        param.set_param('subscription.recipient_partner_ids', '999999999')
        self.assertFalse(self.Control.get_recipient_partner_ids())

    def test_recipient_emails_cleaned(self):
        param = self.env['ir.config_parameter'].sudo().set_param
        param('subscription.recipient_emails', ' a@test.com ,  b@test.com ,')
        self.assertEqual(
            self.Control.get_recipient_emails(), 'a@test.com,b@test.com')

    def test_suspension_login_message_is_defined(self):
        self.assertTrue(self.Control.get_suspension_login_message())

    def test_settings_get_values_set_values_round_trip(self):
        partner = self.env['res.partner'].create({
            'name': 'Contact Settings',
            'email': 'settings@test.com',
        })
        settings = self.env['res.config.settings'].create({
            'subscription_billing_day': 20,
            'subscription_payment_delay_days': 10,
            'subscription_reminder_days': '7,3,1',
            'subscription_suspension_alert': False,
            'subscription_recipient_partner_ids': [(6, 0, [partner.id])],
            'subscription_recipient_emails': 'extra@test.com',
        })
        settings.set_values()

        param = self.env['ir.config_parameter'].sudo()
        self.assertEqual(param.get_param('subscription.billing_day'), '20')
        self.assertEqual(param.get_param('subscription.payment_delay_days'), '10')
        self.assertEqual(param.get_param('subscription.reminder_days'), '7,3,1')
        self.assertEqual(
            param.get_param('subscription.recipient_partner_ids'), str(partner.id))
        self.assertEqual(
            param.get_param('subscription.recipient_emails'), 'extra@test.com')

        # Relecture : get_values retourne les valeurs stockées
        values = self.env['res.config.settings'].get_values()
        self.assertEqual(values.get('subscription_recipient_partner_ids'),
                         [(6, 0, [partner.id])])
        self.assertEqual(values.get('subscription_recipient_emails'), 'extra@test.com')

        # Les helpers de configuration reflètent les nouveaux paramètres.
        # NB : set_values ne stocke pas un booléen identique à la valeur
        # courante (comportement Odoo), on vérifie donc via le helper.
        self.assertEqual(self.Control.get_billing_day(), 20)
        self.assertEqual(self.Control.get_payment_delay_days(), 10)
        self.assertEqual(self.Control.get_reminder_days(), [7, 3, 1])
        self.assertFalse(self.Control.is_suspension_alert_enabled())

    def test_default_suspension_date_matches_billing_plus_delay(self):
        param = self.env['ir.config_parameter'].sudo()
        param.set_param('subscription.billing_day', '25')
        param.set_param('subscription.payment_delay_days', '15')
        cycle = self.env['subscription.billing.cycle'].create({
            'billing_date': date(2026, 10, 25)})
        # 25 oct + 15 jours = 9 nov
        self.assertEqual(cycle.suspension_date, date(2026, 11, 9))

    # ------------------------------------------------------------------
    # Messages personnalisés de la page de connexion
    # ------------------------------------------------------------------

    def test_login_message_top_default_when_missing(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'subscription.login_message_top', False)
        self.assertEqual(self.Control.get_login_message_top(),
                         self.Control.LOGIN_MSG_DEFAULT)

    def test_login_message_top_hidden_when_empty(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'subscription.login_message_top', '')
        self.assertFalse(self.Control.get_login_message_top())

    def test_login_message_bottom_hidden_by_default(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'subscription.login_message_bottom', False)
        self.assertFalse(self.Control.get_login_message_bottom())

    def test_login_messages_round_trip(self):
        param = self.env['ir.config_parameter'].sudo()
        param.set_param('subscription.login_message_top', 'Instance sous contrôle')
        param.set_param('subscription.login_message_bottom', 'Contactez le support')
        self.assertEqual(self.Control.get_login_message_top(),
                         'Instance sous contrôle')
        self.assertEqual(self.Control.get_login_message_bottom(),
                         'Contactez le support')
