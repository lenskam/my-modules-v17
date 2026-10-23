# -*- coding: utf-8 -*-

from odoo import _, fields, models


class AccountReport(models.Model):
    _inherit = 'account.report'

    filter_hide_initial_balance = fields.Boolean(
        string=_("Masquer le solde initiale"),
        help=_("Ne pas afficher la ligne \"Solde initiale\" lors du dépliage "
               "d'un compte dans le rapport Grand livre. Les montants cumulés "
               "des lignes d'écriture incluent toujours le solde initial."),
        compute=lambda self: self._compute_report_option_filter(
            'filter_hide_initial_balance'),
        readonly=False,
        store=True,
        depends=['root_report_id', 'section_main_report_ids'],
    )

    def _init_options_hide_initial_balance(self, options, previous_options=None):
        """Initialise l'option "Masquer le solde initiale" (appelée par le
        moteur de reporting via get_options).

        L'option est disponible uniquement sur le rapport Grand livre. Elle
        est toujours exposée dans la barre d'options du rapport (désactivée
        par défaut), et le champ ``filter_hide_initial_balance`` de la fiche
        du rapport ne décide que de son état par défaut.
        """
        if self._get_custom_handler_model() != 'account.general.ledger.report.handler':
            return

        active = self.filter_hide_initial_balance
        if previous_options:
            active = bool(previous_options.get(
                'hide_initial_balance', self.filter_hide_initial_balance))
        options['hide_initial_balance'] = active
