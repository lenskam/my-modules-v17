# -*- coding: utf-8 -*-

from odoo import _, fields, models


class AccountReport(models.Model):
    _inherit = 'account.report'

    filter_hide_partners_without_moves = fields.Boolean(
        string=_("Masquer les tiers sans mouvement"),
        help=_("N'afficher que les comptes et tiers ayant au moins une ligne "
               "d'écriture comptable (account.move.line) sur la période "
               "sélectionnée."),
        compute=lambda self: self._compute_report_option_filter(
            'filter_hide_partners_without_moves'),
        readonly=False,
        store=True,
        depends=['root_report_id', 'section_main_report_ids'],
    )

    _SARPTI_CUSTOM_HANDLERS = (
        'account.general.ledger.report.handler',
        'account.partner.ledger.report.handler',
    )

    def _sarpti_is_active(self, options):
        """Whether the "hide partners without moves" option applies to this run.

        The option is toggled from the report options bar (stored per-run in
        ``options``) and may also be set as a default on the report record.
        It is only meaningful on the General Ledger and Partner Ledger reports.
        """
        if self._get_custom_handler_model() not in self._SARPTI_CUSTOM_HANDLERS:
            return False
        return bool(options.get('hide_partners_without_moves'))

    def _init_options_hide_partners_without_moves(self, options, previous_options=None):
        """Initializer called by the report engine (get_options).

        The option is available on the General Ledger and the Partner Ledger
        only. It is always exposed in the report options bar (default off), and
        the report record field ``filter_hide_partners_without_moves`` only
        decides its default state.

        For the Partner Ledger, when active, restricts the move lines to the
        partners having at least one line on the period, so dormant partners
        disappear from the report (including their opening balance).
        """
        if self._get_custom_handler_model() not in self._SARPTI_CUSTOM_HANDLERS:
            return

        active = self.filter_hide_partners_without_moves
        if previous_options:
            active = bool(previous_options.get(
                'hide_partners_without_moves', self.filter_hide_partners_without_moves))
        options['hide_partners_without_moves'] = active

        if not active:
            return

        date_from = options.get('date', {}).get('date_from')
        date_to = options.get('date', {}).get('date_to')
        if not date_from or not date_to:
            return

        if self._get_custom_handler_model() == 'account.partner.ledger.report.handler':
            active_partner_ids = self._get_partner_ids_with_moves(date_from, date_to)
            # 'partner_id' in [-1] forces an empty report when no partner is active
            # on the period, instead of falling back to the "all partners" behavior.
            options['forced_domain'] = options.get('forced_domain', []) + [
                ('partner_id', 'in', active_partner_ids or [-1]),
            ]

    def _get_partner_ids_with_moves(self, date_from, date_to):
        """Return the ids of partners having at least one move line in the period.

        Optimized with a single DISTINCT SQL query to stay responsive on
        large accounting histories.
        """
        if not date_from or not date_to:
            return []
        self.env.cr.execute("""
            SELECT DISTINCT partner_id
            FROM account_move_line
            WHERE date >= %s
              AND date <= %s
              AND partner_id IS NOT NULL
        """, (date_from, date_to))
        return [partner_id for (partner_id,) in self.env.cr.fetchall()]

    def get_report_information(self, options):
        result = super().get_report_information(options)
        result['filters']['show_hide_partners_without_moves'] = \
            self.filter_hide_partners_without_moves
        return result
