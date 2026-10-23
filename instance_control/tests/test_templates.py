# -*- coding: utf-8 -*-
from datetime import date
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAlertTemplate(TransactionCase):

    def setUp(self):
        super().setUp()
        self.AlertTemplate = self.env['instance.alert.template']
        self.Instance = self.env['instance.management']
        self.Cycle = self.env['instance.billing.cycle']
        self.Param = self.env['ir.config_parameter'].sudo()
        # Retire les modèles seeds (contrainte unique type/trigger_days)
        self.AlertTemplate.search([]).unlink()
        self.Param.set_param('instance_control.billing_day', '25')
        self.Param.set_param('instance_control.payment_delay_days', '15')
        self.instance = self.Instance.create({
            'name': 'Client A – Production',
            'url': 'https://clienta.test',
            'database': 'clienta_db',
            'login': 'api_user',
            'api_key': 'secret',
        })

    def _tpl(self, name, type_, days, body, subject=''):
        return self.AlertTemplate.create({
            'name': name, 'type': type_, 'trigger_days': days,
            'subject': subject, 'body': body,
        })

    def _cycle(self, **kwargs):
        vals = {
            'instance_id': self.instance.id,
            'billing_date': date(2026, 10, 25),
        }
        vals.update(kwargs)
        return self.Cycle.create(vals)

    # --------- Rendu des placeholders ---------

    def test_render_body_substitutes_placeholders(self):
        cycle = self._cycle()
        context = cycle._build_alert_context(10)
        context.update({
            'invoice_ref': 'INV/2026/0001',
            'invoice_amount': '99.50',
            'invoice_currency': 'EUR',
        })
        tpl = self._tpl('T', 'reminder', 10,
                        'Instance ${instance_name}, client ${client_name}, '
                        'base ${db_name}, facture ${invoice_ref} : '
                        '${invoice_amount} ${invoice_currency}, suspension le '
                        '${suspension_date} (J-${days_before}).')
        result = tpl.render_body(context)
        self.assertIn('Client A – Production', result)
        self.assertIn('clienta_db', result)
        self.assertIn('INV/2026/0001', result)
        self.assertIn('99.50 EUR', result)
        self.assertIn('09/11/2026', result)
        self.assertIn('J-10', result)

    def test_render_body_keeps_unknown_placeholders(self):
        tpl = self._tpl('T', 'reminder', 10, 'Bonjour ${unknown_token}')
        cycle = self._cycle()
        self.assertIn('${unknown_token}',
                      tpl.render_body(cycle._build_alert_context(10)))

    def test_client_name_falls_back_to_instance_name(self):
        cycle = self._cycle()
        self.assertEqual(
            cycle._build_alert_context()['client_name'], self.instance.name)

    def test_client_name_uses_partner_when_set(self):
        partner = self.env['res.partner'].create({
            'name': 'ACME Corp',
        })
        self.instance.partner_id = partner
        cycle = self._cycle()
        self.assertEqual(
            cycle._build_alert_context()['client_name'], 'ACME Corp')

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

    # --------- Envoi email (déduplication + destinataires) ---------

    def test_reminder_email_sent_to_configured_recipients(self):
        cycle = self._cycle()
        cycle.state = 'awaiting_payment'
        self.Param.set_param(
            'instance_control.recipient_emails', 'admin@test.com')
        with patch.object(type(self.env['mail.mail']), 'send'):
            cycle._send_reminder(5, 5)
        mail = self.env['mail.mail'].search([
            ('subject', 'ilike', 'clienta_db'),
        ], limit=1)
        self.assertTrue(mail)

    def test_reminder_email_skipped_without_recipients(self):
        cycle = self._cycle()
        cycle.state = 'awaiting_payment'
        result = cycle._send_cycle_email(False, 'Sujet test', 'Corps test')
        self.assertFalse(result)
        self.assertFalse(self.env['mail.mail'].search([
            ('subject', '=', 'Sujet test')]))

    def test_suspension_alert_logged_once(self):
        cycle = self._cycle()
        cycle.state = 'suspended'
        with patch.object(type(self.env['mail.mail']), 'send'):
            cycle._send_suspension_alert()
            with self.assertRaises(Exception):
                # Contrainte unique (cycle_id, days_before, type)
                self.env['instance.reminder.log'].create({
                    'cycle_id': cycle.id,
                    'days_before': 0,
                    'type': 'suspension_alert',
                })
        logs = self.env['instance.reminder.log'].search([
            ('cycle_id', '=', cycle.id),
            ('type', '=', 'suspension_alert'),
        ])
        self.assertEqual(len(logs), 1)

    # --------- Configuration par instance (destinataires, modèles) ---------

    def test_instance_recipients_override_global(self):
        cycle = self._cycle()
        cycle.state = 'awaiting_payment'
        self.Param.set_param(
            'instance_control.recipient_emails', 'global@test.com')
        self.instance.recipient_emails = 'inst@test.com'
        with patch.object(type(self.env['mail.mail']), 'send'):
            cycle._send_reminder(5, 5)
        mail = self.env['mail.mail'].search([], limit=1, order='id desc')
        self.assertTrue(mail)
        self.assertEqual(mail.email_to, 'inst@test.com')

    def test_instance_recipients_fallback_to_global(self):
        cycle = self._cycle()
        cycle.state = 'awaiting_payment'
        self.Param.set_param(
            'instance_control.recipient_emails', 'global@test.com')
        with patch.object(type(self.env['mail.mail']), 'send'):
            cycle._send_reminder(5, 5)
        mail = self.env['mail.mail'].search([], limit=1, order='id desc')
        self.assertTrue(mail)
        self.assertEqual(mail.email_to, 'global@test.com')

    def test_instance_template_override(self):
        cycle = self._cycle()
        cycle.state = 'awaiting_payment'
        template = self.env['mail.template'].create({
            'name': 'Rappel spécifique instance',
            'model_id': self.env.ref(
                'instance_control.model_instance_billing_cycle').id,
            'subject': 'Sujet spécifique',
            'body_html': '<p>CORPS-SPECIFIQUE-INSTANCE</p>',
        })
        self.instance.reminder_template_id = template
        self.instance.recipient_emails = 'inst@test.com'
        with patch.object(type(self.env['mail.mail']), 'send'):
            cycle._send_reminder(5, 5)
        mail = self.env['mail.mail'].search([], limit=1, order='id desc')
        self.assertTrue(mail)
        self.assertIn('CORPS-SPECIFIQUE-INSTANCE', mail.body_html)

    def test_instance_suspension_template_used(self):
        cycle = self._cycle()
        cycle.state = 'suspended'
        template = self.env['mail.template'].create({
            'name': 'Suspension spécifique instance',
            'model_id': self.env.ref(
                'instance_control.model_instance_billing_cycle').id,
            'subject': 'Sujet suspension',
            'body_html': '<p>SUSPENSION-SPECIFIQUE-INSTANCE</p>',
        })
        self.instance.suspension_template_id = template
        self.instance.recipient_emails = 'inst@test.com'
        with patch.object(type(self.env['mail.mail']), 'send'):
            cycle._send_suspension_alert()
        mail = self.env['mail.mail'].search([], limit=1, order='id desc')
        self.assertTrue(mail)
        self.assertIn('SUSPENSION-SPECIFIQUE-INSTANCE', mail.body_html)

    # --------- Modèles d'email par intervalle de rappel ---------

    def _mail_template(self, name, marker):
        return self.env['mail.template'].create({
            'name': name,
            'model_id': self.env.ref(
                'instance_control.model_instance_billing_cycle').id,
            'subject': name,
            'body_html': '<p>%s</p>' % marker,
        })

    def _last_mail(self):
        return self.env['mail.mail'].search([], limit=1, order='id desc')

    def _interval_line(self, trigger_days, template):
        return self.env['instance.mail.template.line'].create({
            'instance_id': self.instance.id,
            'trigger_days': trigger_days,
            'mail_template_id': template.id,
        })

    def test_interval_template_used_for_j2_and_j1(self):
        t10 = self._mail_template('T10', 'MARKER-J10')
        t5 = self._mail_template('T5', 'MARKER-J5')
        t2 = self._mail_template('T2', 'MARKER-J2')
        self._interval_line(10, t10)
        self._interval_line(5, t5)
        self._interval_line(2, t2)
        cycle = self._cycle()
        cycle.state = 'awaiting_payment'
        self.instance.recipient_emails = 'inst@test.com'
        with patch.object(type(self.env['mail.mail']), 'send'):
            cycle._send_reminder(10, 10)
            cycle._send_reminder(5, 5)
            cycle._send_reminder(2, 2)
            cycle._send_reminder(1, 1)
        mails = self.env['mail.mail'].search([], order='id desc', limit=4)
        # J-1 → interval 2 ; J-2 → interval 2 ; J-5 → interval 5 ; J-10 → 10
        self.assertIn('MARKER-J2', mails[0].body_html)
        self.assertIn('MARKER-J2', mails[1].body_html)
        self.assertIn('MARKER-J5', mails[2].body_html)
        self.assertIn('MARKER-J10', mails[3].body_html)

    def test_interval_template_closest_lower(self):
        t10 = self._mail_template('T10b', 'MARKER-J10B')
        t2 = self._mail_template('T2b', 'MARKER-J2B')
        self._interval_line(10, t10)
        self._interval_line(2, t2)
        cycle = self._cycle()
        cycle.state = 'awaiting_payment'
        self.instance.recipient_emails = 'inst@test.com'
        with patch.object(type(self.env['mail.mail']), 'send'):
            # J-3 : plus proche inférieur ou égal → interval 2
            cycle._send_reminder(3, 3)
        self.assertIn('MARKER-J2B', self._last_mail().body_html)

    def test_no_interval_lines_falls_back_to_default_template(self):
        cycle = self._cycle()
        cycle.state = 'awaiting_payment'
        self.instance.recipient_emails = 'inst@test.com'
        with patch.object(type(self.env['mail.mail']), 'send'):
            cycle._send_reminder(5, 5)
        # Aucune ligne ni modèle d'instance : le défaut du module est
        # utilisé (son corps mentionne l'instance)
        mail = self._last_mail()
        self.assertTrue(mail)
        self.assertIn(self.instance.name, mail.body_html)

    def test_interval_line_unique_per_instance(self):
        template = self._mail_template('T-uniq', 'M')
        self._interval_line(2, template)
        with self.assertRaises(Exception):
            self._interval_line(2, template)

    def test_interval_template_overrides_instance_default(self):
        default_tpl = self._mail_template('Defaut', 'MARKER-DEFAULT')
        interval_tpl = self._mail_template('Interval', 'MARKER-INTERVAL')
        self.instance.reminder_template_id = default_tpl
        self._interval_line(2, interval_tpl)
        cycle = self._cycle()
        cycle.state = 'awaiting_payment'
        self.instance.recipient_emails = 'inst@test.com'
        with patch.object(type(self.env['mail.mail']), 'send'):
            # J-2 correspond à l'intervalle : il prime sur le défaut
            cycle._send_reminder(2, 2)
            # J-7 n'a pas d'intervalle ≤ : repli sur le plus petit (2)
            cycle._send_reminder(7, 7)
        mails = self.env['mail.mail'].search([], order='id desc', limit=2)
        self.assertIn('MARKER-INTERVAL', mails[0].body_html)
        self.assertIn('MARKER-INTERVAL', mails[1].body_html)
        # Le modèle par défaut n'est jamais utilisé tant qu'un intervalle existe
        for mail in mails:
            self.assertNotIn('MARKER-DEFAULT', mail.body_html)
