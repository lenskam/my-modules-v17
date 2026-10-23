# -*- coding: utf-8 -*-

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestHideInitialBalanceOption(TransactionCase):

    def setUp(self):
        super().setUp()
        self.report_model = self.env['account.report']
        self.general_ledger = self.env.ref('account_reports.general_ledger_report')

    def _date_options(self):
        return {'date': {'date_from': '2026-01-01', 'date_to': '2026-12-31'}}

    def test_option_key_is_scoped_to_general_ledger(self):
        plain_report = self.report_model.create({'name': 'Rapport simple'})

        self.general_ledger._init_options_hide_initial_balance(self._date_options())
        plain_report._init_options_hide_initial_balance(self._date_options())

        # La clé est posée par l'initializer du grand livre seulement lorsqu'il
        # est appelé sur lui-même ; le rapport simple n'a pas de handler GL.
        self.assertFalse(plain_report._get_custom_handler_model()
                         == 'account.general.ledger.report.handler')

    def test_option_key_is_off_by_default(self):
        options = self._date_options()
        self.general_ledger._init_options_hide_initial_balance(options)

        self.assertEqual(options['hide_initial_balance'], False)

    def test_previous_options_enable_option_even_when_record_field_is_off(self):
        options = self._date_options()
        self.general_ledger._init_options_hide_initial_balance(
            options, previous_options={'hide_initial_balance': True})

        self.assertEqual(options['hide_initial_balance'], True)

    def test_record_field_is_used_as_default_when_no_previous_options(self):
        self.general_ledger.write({'filter_hide_initial_balance': True})

        options = self._date_options()
        self.general_ledger._init_options_hide_initial_balance(options)

        self.assertEqual(options['hide_initial_balance'], True)

    def test_previous_options_override_record_field(self):
        self.general_ledger.write({'filter_hide_initial_balance': True})

        options = self._date_options()
        self.general_ledger._init_options_hide_initial_balance(
            options, previous_options={'hide_initial_balance': False})

        self.assertEqual(options['hide_initial_balance'], False)


@tagged('post_install', '-at_install')
class TestHideInitialBalanceGeneralLedger(TransactionCase):

    def setUp(self):
        super().setUp()
        self.report = self.env.ref('account_reports.general_ledger_report')
        self.handler = self.env['account.general.ledger.report.handler']
        self.journal = self.env['account.journal'].create({
            'name': 'Journal test grand livre',
            'code': 'TJGL',
            'type': 'general',
            'company_id': self.env.company.id,
        })
        self.acc = self.env['account.account'].create({
            'name': 'Compte test solde initiale',
            'code': 'AABI01',
            'account_type': 'asset_current',
            'include_initial_balance': True,
            'company_id': self.env.company.id,
        })
        self.acc_counter = self.env['account.account'].create({
            'name': 'Contrepartie test',
            'code': 'AABI02',
            'account_type': 'asset_current',
            'include_initial_balance': True,
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

    def _get_options(self, hide=False, unfold_all=False):
        previous_options = {
            'date': {
                'date_from': '2026-01-01',
                'date_to': '2026-12-31',
                'mode': 'range',
                'filter': 'custom',
            },
        }
        if hide:
            previous_options['hide_initial_balance'] = True
        if unfold_all:
            previous_options['unfold_all'] = True
        return self.report.get_options(previous_options=previous_options)

    def _expand_account(self, options):
        line_dict_id = self.report._get_generic_line_id('account.account', self.acc.id)
        return self.handler._report_expand_unfoldable_line_general_ledger(
            line_dict_id, None, options, 0, 0)

    def _initial_lines(self, lines):
        return [
            line for line in lines
            if line.get('id')
            and self.env['account.report']._parse_line_id(line['id'])[-1][0] == 'initial'
        ]

    def _aml_lines(self, lines):
        return [
            line for line in lines
            if line.get('id')
            and self.env['account.report']._parse_line_id(line['id'])[-1][1] == 'account.move.line'
        ]

    def test_initial_balance_line_present_when_option_disabled(self):
        self._post_move('2025-12-31', [
            {'name': 'Solde initial', 'account_id': self.acc.id, 'debit': 100.0},
            {'name': 'Contrepartie', 'account_id': self.acc_counter.id, 'credit': 100.0},
        ])
        self._post_move('2026-03-15', [
            {'name': 'Ecriture periode', 'account_id': self.acc.id, 'debit': 50.0},
            {'name': 'Contrepartie', 'account_id': self.acc_counter.id, 'credit': 50.0},
        ])

        result = self._expand_account(self._get_options(hide=False))

        self.assertEqual(len(self._initial_lines(result['lines'])), 1)

    def test_initial_balance_line_hidden_when_option_enabled(self):
        self._post_move('2025-12-31', [
            {'name': 'Solde initial', 'account_id': self.acc.id, 'debit': 100.0},
            {'name': 'Contrepartie', 'account_id': self.acc_counter.id, 'credit': 100.0},
        ])
        self._post_move('2026-03-15', [
            {'name': 'Ecriture periode', 'account_id': self.acc.id, 'debit': 50.0},
            {'name': 'Contrepartie', 'account_id': self.acc_counter.id, 'credit': 50.0},
        ])

        result = self._expand_account(self._get_options(hide=True))

        self.assertEqual(self._initial_lines(result['lines']), [])
        self.assertEqual(len(self._aml_lines(result['lines'])), 1)

    def test_cumul_of_aml_still_includes_initial_balance_when_hidden(self):
        self._post_move('2025-12-31', [
            {'name': 'Solde initial', 'account_id': self.acc.id, 'debit': 100.0},
            {'name': 'Contrepartie', 'account_id': self.acc_counter.id, 'credit': 100.0},
        ])
        self._post_move('2026-03-15', [
            {'name': 'Ecriture periode', 'account_id': self.acc.id, 'debit': 50.0},
            {'name': 'Contrepartie', 'account_id': self.acc_counter.id, 'credit': 50.0},
        ])

        options = self._get_options(hide=True)
        result = self._expand_account(options)

        aml_line = self._aml_lines(result['lines'])[0]
        balance_column = next(
            column for column, line_col in zip(options['columns'], aml_line['columns'])
            if column['expression_label'] == 'balance'
        )
        # 100 (solde initial) + 50 (ecriture de la periode)
        self.assertEqual(balance_column['no_format'], 150.0)

    def test_no_initial_balance_line_when_no_pre_period_moves(self):
        self._post_move('2026-03-15', [
            {'name': 'Ecriture periode', 'account_id': self.acc.id, 'debit': 50.0},
            {'name': 'Contrepartie', 'account_id': self.acc_counter.id, 'credit': 50.0},
        ])

        result = self._expand_account(self._get_options(hide=False))

        self.assertEqual(self._initial_lines(result['lines']), [])
        self.assertEqual(len(self._aml_lines(result['lines'])), 1)

    def test_initial_balance_hidden_in_full_report_with_unfold_all(self):
        self._post_move('2025-12-31', [
            {'name': 'Solde initial', 'account_id': self.acc.id, 'debit': 100.0},
            {'name': 'Contrepartie', 'account_id': self.acc_counter.id, 'credit': 100.0},
        ])
        self._post_move('2026-03-15', [
            {'name': 'Ecriture periode', 'account_id': self.acc.id, 'debit': 50.0},
            {'name': 'Contrepartie', 'account_id': self.acc_counter.id, 'credit': 50.0},
        ])

        lines = self.report._get_lines(self._get_options(hide=True, unfold_all=True))

        self.assertEqual(self._initial_lines(lines), [])

    def test_initial_balance_present_in_full_report_without_option(self):
        self._post_move('2025-12-31', [
            {'name': 'Solde initial', 'account_id': self.acc.id, 'debit': 100.0},
            {'name': 'Contrepartie', 'account_id': self.acc_counter.id, 'credit': 100.0},
        ])
        self._post_move('2026-03-15', [
            {'name': 'Ecriture periode', 'account_id': self.acc.id, 'debit': 50.0},
            {'name': 'Contrepartie', 'account_id': self.acc_counter.id, 'credit': 50.0},
        ])

        lines = self.report._get_lines(self._get_options(hide=False, unfold_all=True))

        self.assertEqual(len(self._initial_lines(lines)), 1)
