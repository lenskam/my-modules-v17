# -*- coding: utf-8 -*-

from odoo import models


class PartnerLedgerCustomHandler(models.AbstractModel):
    """Partner Ledger: expose the "hide partners without moves" filter.

    The actual partner restriction is applied by the report options
    initializer (options['forced_domain']), so no line override is needed here.
    """

    _inherit = 'account.partner.ledger.report.handler'

    def _get_custom_display_config(self):
        res = super()._get_custom_display_config()
        res.setdefault('components', {})['AccountReportFilters'] = \
            'custom_account_report_filter.SapReportFilters'
        return res