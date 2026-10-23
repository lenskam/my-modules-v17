from odoo.tests import TransactionCase, tagged


@tagged('standard', '-at_install', 'post_install')
class TestGetPartnerIdsWithMoves(TransactionCase):

    def setUp(self):
        super().setUp()
        self.report_model = self.env['account.report']
        self.partner_active = self.env['res.partner'].create({'name': 'Client avec mouvement'})
        self.partner_dormant = self.env['res.partner'].create({'name': 'Client sans mouvement'})
        self.journal = self.env['account.journal'].search(
            [('company_id', '=', self.env.company.id)], limit=1)
        self.account = self.env['account.account'].search(
            [('company_id', '=', self.env.company.id), ('deprecated', '=', False)], limit=1)

    def _create_move_line(self, partner, date):
        self.env['account.move'].create({
            'journal_id': self.journal.id,
            'date': date,
            'line_ids': [(0, 0, {
                'name': 'Ligne de test',
                'account_id': self.account.id,
                'partner_id': partner.id,
            })],
        })
        self.env.flush_all()

    def test_only_partners_with_move_lines_in_period_are_returned(self):
        self._create_move_line(self.partner_active, '2026-03-15')
        self._create_move_line(self.partner_dormant, '2025-01-01')

        result = self.report_model._get_partner_ids_with_moves('2026-01-01', '2026-12-31')

        self.assertEqual(result, [self.partner_active.id])

    def test_partner_without_moves_is_not_returned(self):
        self._create_move_line(self.partner_dormant, '2025-01-01')

        result = self.report_model._get_partner_ids_with_moves('2026-01-01', '2026-12-31')

        self.assertEqual(result, [])

    def test_move_lines_outside_period_are_ignored(self):
        self._create_move_line(self.partner_active, '2025-12-31')
        self._create_move_line(self.partner_dormant, '2026-01-01')

        result = self.report_model._get_partner_ids_with_moves('2026-01-01', '2026-12-31')

        self.assertEqual(result, [self.partner_dormant.id])

    def test_inverted_period_returns_no_partners(self):
        self._create_move_line(self.partner_active, '2026-03-15')

        result = self.report_model._get_partner_ids_with_moves('2026-12-31', '2026-01-01')

        self.assertEqual(result, [])

    def test_missing_period_returns_no_partners(self):
        result = self.report_model._get_partner_ids_with_moves(False, False)

        self.assertEqual(result, [])


@tagged('post_install', '-at_install')
class TestHidePartnersWithoutMovesOption(TransactionCase):

    def setUp(self):
        super().setUp()
        self.report_model = self.env['account.report']
        self.partner_active = self.env['res.partner'].create({'name': 'Client avec mouvement'})
        self.partner_dormant = self.env['res.partner'].create({'name': 'Client sans mouvement'})
        self.journal = self.env['account.journal'].search(
            [('company_id', '=', self.env.company.id)], limit=1)
        self.account = self.env['account.account'].search(
            [('company_id', '=', self.env.company.id), ('deprecated', '=', False)], limit=1)

    def _create_move_line(self, partner, date):
        self.env['account.move'].create({
            'journal_id': self.journal.id,
            'date': date,
            'line_ids': [(0, 0, {
                'name': 'Ligne de test',
                'account_id': self.account.id,
                'partner_id': partner.id,
            })],
        })
        self.env.flush_all()

    def _date_options(self):
        return {'date': {'date_from': '2026-01-01', 'date_to': '2026-12-31'}}

    def test_option_is_scoped_to_general_ledger_and_partner_ledger(self):
        general_ledger = self.env.ref('account_reports.general_ledger_report')
        partner_ledger = self.env.ref('account_reports.partner_ledger_report')
        plain_report = self.report_model.create({'name': 'Rapport simple'})

        self.assertTrue(general_ledger._sarpti_is_active(
            {'hide_partners_without_moves': True}))
        self.assertTrue(partner_ledger._sarpti_is_active(
            {'hide_partners_without_moves': True}))
        self.assertFalse(plain_report._sarpti_is_active(
            {'hide_partners_without_moves': True}))
        self.assertFalse(partner_ledger._sarpti_is_active({}))

    def test_option_key_is_always_set_and_off_by_default(self):
        partner_ledger = self.env.ref('account_reports.partner_ledger_report')

        options = self._date_options()
        partner_ledger._init_options_hide_partners_without_moves(options)

        self.assertEqual(options['hide_partners_without_moves'], False)
        self.assertNotIn('forced_domain', options)

    def test_previous_options_enable_filter_even_when_record_field_is_off(self):
        partner_ledger = self.env.ref('account_reports.partner_ledger_report')
        self._create_move_line(self.partner_active, '2026-03-15')

        options = self._date_options()
        partner_ledger._init_options_hide_partners_without_moves(
            options, previous_options={'hide_partners_without_moves': True})

        self.assertEqual(options['hide_partners_without_moves'], True)
        self.assertEqual(options['forced_domain'],
                         [('partner_id', 'in', [self.partner_active.id])])

    def test_record_field_is_used_as_default_when_no_previous_options(self):
        partner_ledger = self.env.ref('account_reports.partner_ledger_report')
        partner_ledger.write({'filter_hide_partners_without_moves': True})
        self._create_move_line(self.partner_active, '2026-03-15')

        options = self._date_options()
        partner_ledger._init_options_hide_partners_without_moves(options)

        self.assertTrue(options['hide_partners_without_moves'])
        self.assertEqual(options['forced_domain'],
                         [('partner_id', 'in', [self.partner_active.id])])

    def test_previous_options_override_record_field(self):
        partner_ledger = self.env.ref('account_reports.partner_ledger_report')
        partner_ledger.write({'filter_hide_partners_without_moves': True})
        self._create_move_line(self.partner_active, '2026-03-15')

        options = self._date_options()
        partner_ledger._init_options_hide_partners_without_moves(
            options, previous_options={'hide_partners_without_moves': False})

        self.assertEqual(options['hide_partners_without_moves'], False)
        self.assertNotIn('forced_domain', options)

    def test_forced_domain_only_contains_partners_with_moves(self):
        partner_ledger = self.env.ref('account_reports.partner_ledger_report')
        partner_ledger.write({'filter_hide_partners_without_moves': True})
        self._create_move_line(self.partner_active, '2026-03-15')
        self._create_move_line(self.partner_dormant, '2025-01-01')

        options = self._date_options()
        partner_ledger._init_options_hide_partners_without_moves(
            options, previous_options={'hide_partners_without_moves': True})

        self.assertEqual(options['forced_domain'],
                         [('partner_id', 'in', [self.partner_active.id])])

    def test_forced_domain_empty_when_no_partner_has_moves(self):
        partner_ledger = self.env.ref('account_reports.partner_ledger_report')
        partner_ledger.write({'filter_hide_partners_without_moves': True})

        options = self._date_options()
        partner_ledger._init_options_hide_partners_without_moves(
            options, previous_options={'hide_partners_without_moves': True})

        # 'partner_id' in [-1] forces an empty report instead of all partners.
        self.assertEqual(options['forced_domain'], [('partner_id', 'in', [-1])])

    def test_general_ledger_does_not_restrict_partners(self):
        general_ledger = self.env.ref('account_reports.general_ledger_report')
        general_ledger.write({'filter_hide_partners_without_moves': True})

        options = self._date_options()
        general_ledger._init_options_hide_partners_without_moves(
            options, previous_options={'hide_partners_without_moves': True})

        self.assertTrue(options['hide_partners_without_moves'])
        self.assertNotIn('forced_domain', options)

    def test_missing_date_period_does_not_restrict_partners(self):
        partner_ledger = self.env.ref('account_reports.partner_ledger_report')
        partner_ledger.write({'filter_hide_partners_without_moves': True})

        options = {'date': {}}
        partner_ledger._init_options_hide_partners_without_moves(
            options, previous_options={'hide_partners_without_moves': True})

        self.assertTrue(options['hide_partners_without_moves'])
        self.assertNotIn('forced_domain', options)


@tagged('post_install', '-at_install')
class TestHideDormantAccountsGeneralLedger(TransactionCase):

    def setUp(self):
        super().setUp()
        self.report = self.env.ref('account_reports.general_ledger_report')
        self.journal = self.env['account.journal'].create({
            'name': 'Journal test grand livre',
            'code': 'TJGL',
            'type': 'general',
            'company_id': self.env.company.id,
        })
        self.acc_active = self.env['account.account'].create({
            'name': 'Actif avec mouvement',
            'code': 'AAAA01',
            'account_type': 'asset_current',
            'company_id': self.env.company.id,
        })
        self.acc_dormant = self.env['account.account'].create({
            'name': 'Actif dormant',
            'code': 'AAAA02',
            'account_type': 'asset_current',
            'company_id': self.env.company.id,
        })
        self.acc_counter = self.env['account.account'].create({
            'name': 'Contrepartie',
            'code': 'AAAA03',
            'account_type': 'asset_current',
            'company_id': self.env.company.id,
        })

    def _post_move(self, date, lines):
        move = self.env['account.move'].create({
            'journal_id': self.journal.id,
            'date': date,
            'line_ids': [(0, 0, vals) for vals in lines],
        })
        move.action_post()
        self.env.flush_all()

    def _get_options(self, hide=False):
        previous_options = {
            'date': {
                'date_from': '2026-01-01',
                'date_to': '2026-12-31',
                'mode': 'range',
                'filter': 'custom',
            },
        }
        if hide:
            previous_options['hide_partners_without_moves'] = True
        return self.report.get_options(previous_options=previous_options)

    def _get_account_ids_from_lines(self, lines):
        account_ids = set()
        for command, line in lines:
            if line.get('expand_function') == '_report_expand_unfoldable_line_general_ledger':
                model, model_id = self.env['account.report']._get_model_info_from_id(line['id'])
                if model == 'account.account':
                    account_ids.add(model_id)
        return account_ids

    def _generate_lines(self, options):
        return self.env['account.general.ledger.report.handler']._dynamic_lines_generator(
            self.report, options, {})

    def test_dormant_accounts_are_hidden_when_option_enabled(self):
        self._post_move('2026-03-15', [
            {'name': 'Actif', 'account_id': self.acc_active.id, 'debit': 100.0},
            {'name': 'Contrepartie', 'account_id': self.acc_counter.id, 'credit': 100.0},
        ])
        self._post_move('2025-12-31', [
            {'name': 'Dormant', 'account_id': self.acc_dormant.id, 'debit': 100.0},
            {'name': 'Contrepartie', 'account_id': self.acc_counter.id, 'credit': 100.0},
        ])
        self.report.write({'filter_hide_partners_without_moves': True})

        account_ids = self._get_account_ids_from_lines(self._generate_lines(self._get_options(hide=True)))

        self.assertIn(self.acc_active.id, account_ids)
        self.assertNotIn(self.acc_dormant.id, account_ids)

    def test_dormant_accounts_are_kept_when_option_disabled(self):
        self._post_move('2026-03-15', [
            {'name': 'Actif', 'account_id': self.acc_active.id, 'debit': 100.0},
            {'name': 'Contrepartie', 'account_id': self.acc_counter.id, 'credit': 100.0},
        ])
        self._post_move('2025-12-31', [
            {'name': 'Dormant', 'account_id': self.acc_dormant.id, 'debit': 100.0},
            {'name': 'Contrepartie', 'account_id': self.acc_counter.id, 'credit': 100.0},
        ])

        account_ids = self._get_account_ids_from_lines(self._generate_lines(self._get_options(hide=False)))

        self.assertIn(self.acc_active.id, account_ids)
        self.assertIn(self.acc_dormant.id, account_ids)
