# -*- coding: utf-8 -*-

from odoo import models


class GeneralLedgerHideInitialBalanceHandler(models.AbstractModel):
    """Grand Livre : masquer la ligne "Solde initiale" lors du dépliage
    d'un compte lorsque l'option "Masquer le solde initiale" est activée.

    Les montants cumulés des lignes d'écriture restent identiques au
    comportement standard : le solde initial continue d'être pris en
    compte dans le calcul du cumul (progress), seule la ligne est masquée.
    """

    _inherit = 'account.general.ledger.report.handler'

    def _get_custom_display_config(self):
        res = super()._get_custom_display_config()
        res.setdefault('components', {})['AccountReportFilters'] = \
            'account_general_ledger_hide_initial_balance.GLHideInitialBalanceFilters'
        return res

    def _report_expand_unfoldable_line_general_ledger(self, line_dict_id, groupby, options, progress, offset, unfold_all_batch_data=None):
        expansion = super()._report_expand_unfoldable_line_general_ledger(
            line_dict_id, groupby, options, progress, offset,
            unfold_all_batch_data=unfold_all_batch_data)

        if not options.get('hide_initial_balance'):
            return expansion

        # La ligne "Solde initiale" est la seule ligne générée avec le
        # markup 'initial' (cf. _get_partner_and_general_ledger_initial_balance_line).
        # Le super a déjà utilisé ses valeurs pour initialiser le progress,
        # garantissant des montants cumulés identiques au standard.
        expansion['lines'] = [
            line for line in expansion['lines']
            if not self._is_initial_balance_line(line)
        ]
        return expansion

    def _is_initial_balance_line(self, line):
        line_id = line.get('id')
        if not line_id:
            return False
        last_id_tuple = self.env['account.report']._parse_line_id(line_id)[-1]
        return last_id_tuple[0] == 'initial'
