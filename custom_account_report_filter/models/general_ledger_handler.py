# -*- coding: utf-8 -*-

from odoo import models


class GeneralLedgerCustomHandler(models.AbstractModel):
    """General Ledger: hide accounts without move lines on the selected period."""

    _inherit = 'account.general.ledger.report.handler'

    def _get_custom_display_config(self):
        res = super()._get_custom_display_config()
        res.setdefault('components', {})['AccountReportFilters'] = \
            'custom_account_report_filter.SapReportFilters'
        return res

    def _dynamic_lines_generator(self, report, options, all_column_groups_expression_totals, warnings=None):
        lines = super()._dynamic_lines_generator(
            report, options, all_column_groups_expression_totals, warnings=warnings)

        if not options.get('hide_partners_without_moves'):
            return lines

        # An account title line is only unfoldable when it has at least one
        # move line on the period. Accounts shown solely for their opening
        # balance (dormant) are therefore dropped from the report.
        filtered_lines = []
        for command, line in lines:
            if (
                line.get('expand_function') == '_report_expand_unfoldable_line_general_ledger'
                and not line.get('unfoldable')
            ):
                continue
            filtered_lines.append((command, line))
        return filtered_lines