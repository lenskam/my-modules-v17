# -*- coding: utf-8 -*-
from datetime import date
from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAlertTemplate(TransactionCase):

    def setUp(self):
        super().setUp()
        self.AlertTemplate = self.env['subscription.alert.template']
        self.Cycle = self.env['subscription.billing.cycle']
        self.Param = self.env['ir.config_parameter'].sudo()
        # Retire les modeles seeds (contrainte unique type/trigger_days)
        self.AlertTemplate.search([]).unlink()
        self.Param.set_param('subscription.billing_day', '25')
        self.Param.set_param('subscription.payment_delay_days', '15')
        self.Param.set_param('subscription.client_name', '')

    def _tpl(self, name, type_, days, body, subject=''):
        return self.AlertTemplate.create({
            'name': name, 'type': type_, 'trigger_days': days,
            'subject': subject, 'body': body,
        })

    # --------- Rendu des placeholders ---------

    def test_render_body_substitutes_placeholders(self):
        cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        cycle.write({'client_name': 'ACME', 'invoice_ref': 'INV-001',
                     'invoice_amount': 99.5, 'invoice_currency': 'EUR'})
        tpl = self._tpl('T', 'reminder', 10,
                        'Client ${client_name}, facture ${invoice_ref} : '
                        '${invoice_amount} ${invoice_currency}, suspension le '
                        '${suspension_date} (J-${days_before}).')
        result = tpl.render_body(cycle._build_alert_context(10))
        self.assertIn('ACME', result)
        self.assertIn('INV-001', result)
        self.assertIn('99.50 EUR', result)
        self.assertIn('09/11/2026', result)
        self.assertIn('J-10', result)

    def test_render_body_keeps_unknown_placeholders(self):
        tpl = self._tpl('T', 'reminder', 10, 'Bonjour ${unknown_token}')
        cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        self.assertIn('${unknown_token}',
                      tpl.render_body(cycle._build_alert_context(10)))

    def test_client_name_falls_back_to_config(self):
        self.Param.set_param('subscription.client_name', 'Client Config')
        cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        self.assertEqual(cycle._build_alert_context()['client_name'],
                         'Client Config')

    # --------- Sélection du modèle par trigger_days ---------

    def test_pick_reminder_template_closest_lower_trigger(self):
        t10 = self._tpl('T10', 'reminder', 10, 'r10')
        t5 = self._tpl('T5', 'reminder', 5, 'r5')
        t2 = self._tpl('T2', 'reminder', 2, 'r2')
        self.assertEqual(
            self.AlertTemplate.pick_reminder_template(10), t10)
        self.assertEqual(
            self.AlertTemplate.pick_reminder_template(5), t5)
        # J-2 et J-1 utilisent le modèle de trigger 2
        self.assertEqual(
            self.AlertTemplate.pick_reminder_template(2), t2)
        self.assertEqual(
            self.AlertTemplate.pick_reminder_template(1), t2)

    def test_pick_reminder_template_falls_back_to_smallest(self):
        t = self._tpl('T5', 'reminder', 5, 'r5')
        # Aucun trigger <= 3 : prend le plus petit trigger
        self.assertEqual(self.AlertTemplate.pick_reminder_template(3), t)

    def test_suspension_template_selected(self):
        susp = self._tpl('S', 'suspension', 0, 'suspendu')
        self.assertEqual(
            self.AlertTemplate.get_suspension_template(), susp)


@tagged('post_install', '-at_install')
class TestRemotePaymentSync(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Cycle = self.env['subscription.billing.cycle']
        self.CycleModel = type(self.env['subscription.billing.cycle'])
        self.Param = self.env['ir.config_parameter'].sudo()
        self.Param.set_param('subscription.remote_enabled', 'True')
        self.Param.set_param('subscription.remote_odoo_url', 'https://remote.test')
        self.Param.set_param('subscription.remote_odoo_db', 'remote_db')
        self.Param.set_param('subscription.remote_odoo_user', 'api_user')
        self.Param.set_param('subscription.remote_odoo_api_key', 'secret')
        self.Param.set_param('subscription.remote_partner_id', '42')
        self.Param.set_param('subscription.recipient_emails', 'admin@test.com')
        self.cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        self.cycle.write({'state': 'awaiting_payment'})

    def _mock_client(self, invoices):
        client = MagicMock()
        client.find_invoice.return_value = invoices
        return patch.object(
            self.CycleModel, '_get_xmlrpc_client', return_value=client)

    def test_sync_marks_cycle_paid_when_remote_paid(self):
        with self._mock_client({
            'name': 'INV/2026/0001', 'ref': 'SUB-testdb-2026-10',
            'amount_total': 120.0, 'payment_state': 'paid',
            'currency_id': (1, 'EUR'), 'partner_id': (42, 'ACME'),
            'invoice_date': '2026-10-25'}):
            self.Cycle._sync_remote_payments()
        self.assertEqual(self.cycle.state, 'paid')
        self.assertEqual(self.cycle.invoice_ref, 'INV/2026/0001')
        self.assertEqual(self.cycle.invoice_amount, 120.0)
        self.assertEqual(self.cycle.invoice_currency, 'EUR')
        self.assertEqual(self.cycle.client_name, 'ACME')
        self.assertFalse(self.cycle.remote_sync_error)

    def test_sync_does_not_mark_paid_when_partial(self):
        with self._mock_client({
            'name': 'INV/2026/0002', 'amount_total': 120.0,
            'payment_state': 'partial', 'currency_id': (1, 'EUR'),
            'partner_id': (42, 'ACME'), 'invoice_date': '2026-10-25'}):
            self.Cycle._sync_remote_payments()
        self.assertEqual(self.cycle.state, 'awaiting_payment')

    def test_sync_error_is_logged_and_email_sent(self):
        client = MagicMock()
        client.find_invoice.side_effect = Exception('Network timeout')
        # Desactive l'envoi reel (auto_delete supprimerait le mail dans le test)
        with patch.object(
                self.CycleModel, '_get_xmlrpc_client', return_value=client), \
                patch.object(type(self.env['mail.mail']), 'send'):
            self.Cycle._sync_remote_payments()
        self.assertIn('Network timeout', self.cycle.remote_sync_error)
        mail = self.env['mail.mail'].search([
            ('subject', 'ilike', 'Erreur de synchronisation'),
        ], limit=1)
        self.assertTrue(mail)

    def test_sync_skipped_when_disabled(self):
        self.Param.set_param('subscription.remote_enabled', 'False')
        with patch.object(self.CycleModel, '_get_xmlrpc_client') as factory:
            self.Cycle._sync_remote_payments()
        factory.assert_not_called()
        self.assertEqual(self.cycle.state, 'awaiting_payment')


@tagged('post_install', '-at_install')
class TestReminderEmailIntervals(TransactionCase):
    """Modèles d'email de rappel par intervalle : pour un rappel J-N, le
    modèle dont l'intervalle est le plus proche inférieur ou égal à N est
    utilisé (ex. interval 2 = J-2 et J-1), sinon repli sur le modèle par
    défaut."""

    def setUp(self):
        super().setUp()
        self.Cycle = self.env['subscription.billing.cycle']
        self.Line = self.env['subscription.mail.template.line']
        self.Param = self.env['ir.config_parameter'].sudo()
        self.Line.search([]).unlink()
        self.Param.set_param('subscription.recipient_emails', 'alerts@test.com')
        self.Param.set_param('subscription.reminder_days', '10,5,2,1')
        self.Param.set_param('subscription.payment_delay_days', '15')
        self.Param.set_param('subscription.reminder_template_id', '')
        self.cycle = self.Cycle.create({'billing_date': date(2026, 10, 25)})
        self.cycle.write({'state': 'awaiting_payment'})

    def _mail_template(self, name, marker):
        return self.env['mail.template'].create({
            'name': name,
            'model_id': self.env.ref(
                'subscription_control.model_subscription_billing_cycle').id,
            'subject': name,
            'body_html': '<p>%s</p>' % marker,
        })

    def _last_mail(self):
        return self.env['mail.mail'].search([], limit=1, order='id desc')

    def _send(self, n):
        with patch.object(type(self.env['mail.mail']), 'send'):
            self.cycle._send_reminder(n, n)
        return self._last_mail()

    def test_interval_template_used_for_j2_and_j1(self):
        t10 = self._mail_template('T10', 'MARKER-J10')
        t5 = self._mail_template('T5', 'MARKER-J5')
        t2 = self._mail_template('T2', 'MARKER-J2')
        self.Line.create({'trigger_days': 10, 'mail_template_id': t10.id})
        self.Line.create({'trigger_days': 5, 'mail_template_id': t5.id})
        self.Line.create({'trigger_days': 2, 'mail_template_id': t2.id})
        with patch.object(type(self.env['mail.mail']), 'send'):
            self.cycle._send_reminder(10, 10)
            self.cycle._send_reminder(5, 5)
            self.cycle._send_reminder(2, 2)
            self.cycle._send_reminder(1, 1)
        mails = self.env['mail.mail'].search([], order='id desc', limit=4)
        # J-1 → interval 2 ; J-2 → interval 2 ; J-5 → 5 ; J-10 → 10
        self.assertIn('MARKER-J2', mails[0].body_html)
        self.assertIn('MARKER-J2', mails[1].body_html)
        self.assertIn('MARKER-J5', mails[2].body_html)
        self.assertIn('MARKER-J10', mails[3].body_html)

    def test_interval_template_closest_lower(self):
        t10 = self._mail_template('T10b', 'MARKER-J10B')
        t2 = self._mail_template('T2b', 'MARKER-J2B')
        self.Line.create({'trigger_days': 10, 'mail_template_id': t10.id})
        self.Line.create({'trigger_days': 2, 'mail_template_id': t2.id})
        # J-3 : plus proche inférieur ou égal → interval 2
        self.assertIn('MARKER-J2B', self._send(3).body_html)

    def test_no_interval_lines_falls_back_to_default_template(self):
        # Aucune ligne ni modèle configuré : le défaut du module est utilisé
        mail = self._send(5)
        self.assertTrue(mail)
        self.assertIn('suspendu', mail.body_html)

    def test_interval_line_unique(self):
        template = self._mail_template('T-uniq', 'M')
        self.Line.create({'trigger_days': 2, 'mail_template_id': template.id})
        with self.assertRaises(Exception):
            self.Line.create({'trigger_days': 2, 'mail_template_id': template.id})

    def test_interval_template_overrides_configured_default(self):
        default_tpl = self._mail_template('Defaut', 'MARKER-DEFAULT')
        interval_tpl = self._mail_template('Interval', 'MARKER-INTERVAL')
        self.Param.set_param(
            'subscription.reminder_template_id', str(default_tpl.id))
        self.Line.create({'trigger_days': 2, 'mail_template_id': interval_tpl.id})
        # J-2 correspond à l'intervalle : il prime sur le modèle par défaut
        mail = self._send(2)
        self.assertIn('MARKER-INTERVAL', mail.body_html)
        self.assertNotIn('MARKER-DEFAULT', mail.body_html)
