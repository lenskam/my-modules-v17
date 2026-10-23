# -*- coding: utf-8 -*-
from datetime import date
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

FIXED_TODAY = date(2026, 10, 26)


@tagged('post_install', '-at_install')
class TestInvoiceFlow(AccountTestInvoicingCommon):

    def setUp(self):
        super().setUp()
        self.Cycle = self.env['instance.billing.cycle']
        self.Instance = self.env['instance.management']
        self.Param = self.env['ir.config_parameter'].sudo()
        self.product = self.env['product.product'].create({
            'name': 'Abonnement Odoo Test',
            'type': 'service',
            'list_price': 150.0,
            'taxes_id': [(5, 0, 0)],
            'supplier_taxes_id': [(5, 0, 0)],
        })
        self.Param.set_param(
            'instance_control.product_id', str(self.product.id))
        self.Param.set_param('instance_control.billing_day', '25')
        self.Param.set_param('instance_control.payment_delay_days', '15')
        # L'utilisateur de test d'AccountTestInvoicingCommon n'est pas
        # superuser : on lui accorde le groupe manager du module
        self.env.user.groups_id = [(4, self.env.ref(
            'instance_control.group_instance_control_manager').id)]
        self.instance = self.env['instance.management'].create({
            'name': 'Client Facturé',
            'url': 'https://facture.test',
            'database': 'facture_db',
            'login': 'api_user',
            'api_key': 'secret',
            'partner_id': self.partner_a.id,
            'monthly_amount': 150.0,
            'currency_id': self.env.company.currency_id.id,
        })
        self.cycle = self.Cycle.create({
            'instance_id': self.instance.id,
            'billing_date': date(2026, 10, 25),
        })
        self.cycle.state = 'awaiting_payment'

    def _patch_today(self, day=FIXED_TODAY):
        return patch.object(
            fields.Date, 'context_today', return_value=day)

    def _mock_client(self):
        client = MagicMock()
        return patch.object(
            type(self.env['instance.management']),
            '_get_client', return_value=client), client

    # ------------------------------------------------------------------
    # Génération de la facture client au centre
    # ------------------------------------------------------------------

    def test_invoice_generated_on_billing_day(self):
        self.cycle._process_invoicing()
        invoice = self.cycle.invoice_id
        self.assertTrue(invoice)
        self.assertEqual(invoice.move_type, 'out_invoice')
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.partner_id, self.partner_a)
        self.assertEqual(invoice.amount_total, 150.0)
        self.assertEqual(
            invoice.ref,
            'SUB-%s-%s' % (self.instance.database, '2026-10'))
        line = invoice.invoice_line_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.product_id, self.product)
        self.assertEqual(line.price_unit, 150.0)

    def test_invoice_generated_only_once(self):
        self.cycle._process_invoicing()
        invoice = self.cycle.invoice_id
        self.cycle._process_invoicing()
        self.assertEqual(self.cycle.invoice_id, invoice)
        self.assertEqual(
            self.env['account.move'].search_count([
                ('ref', '=', invoice.ref),
            ]), 1)

    def test_missing_product_raises(self):
        self.Param.set_param('instance_control.product_id', '')
        with self.assertRaises(UserError):
            self.cycle._process_invoicing()

    def test_missing_partner_raises(self):
        self.instance.partner_id = False
        with self.assertRaises(UserError):
            self.cycle._process_invoicing()

    def test_instance_product_override(self):
        custom = self.env['product.product'].create({
            'name': 'Abonnement Premium Instance',
            'type': 'service',
            'list_price': 300.0,
            'taxes_id': [(5, 0, 0)],
        })
        self.instance.product_id = custom
        self.cycle._process_invoicing()
        line = self.cycle.invoice_id.invoice_line_ids
        self.assertEqual(line.product_id, custom)
        # Le montant facturé reste le montant mensuel de l'instance
        self.assertEqual(self.cycle.invoice_id.amount_total, 150.0)

    # ------------------------------------------------------------------
    # Paiement de la facture → cycle payé → rétablissement distant
    # ------------------------------------------------------------------

    def test_invoice_payment_marks_cycle_paid_and_restores_remote(self):
        self.cycle._process_invoicing()
        invoice = self.cycle.invoice_id
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=[invoice.id],
        ).create({})
        wizard.action_create_payments()
        self.assertEqual(invoice.payment_state, 'paid')

        patcher, client = self._mock_client()
        with patcher:
            self.Cycle._sync_invoice_payments()
        self.assertEqual(self.cycle.state, 'paid')
        self.assertEqual(self.cycle.paid_on, date.today())
        client.set_expiration_date.assert_called_once()
        client.restore_access.assert_called_once()
        self.assertEqual(self.instance.state, 'active')

    def test_payment_sync_skips_unpaid_invoice(self):
        self.cycle._process_invoicing()
        patcher, _ = self._mock_client()
        with patcher:
            self.Cycle._sync_invoice_payments()
        self.assertEqual(self.cycle.state, 'awaiting_payment')

    # ------------------------------------------------------------------
    # Le moteur complet : facturation à la date de facturation
    # ------------------------------------------------------------------

    def test_run_billing_cycles_generates_invoice(self):
        with self._patch_today(), \
                patch.object(type(self.Cycle), '_process_reminders'), \
                patch.object(type(self.Cycle), '_process_suspension'), \
                patch.object(type(self.Cycle), '_retry_remote_suspension'):
            self.Cycle.run_billing_cycles()
        cycle = self.Cycle.search([('instance_id', '=', self.instance.id)])
        self.assertEqual(cycle.state, 'awaiting_payment')
        self.assertTrue(cycle.invoice_id)
