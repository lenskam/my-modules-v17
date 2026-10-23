/** @odoo-module */

import { AccountReport } from "@account_reports/components/account_report/account_report";
import { AccountReportFilters } from "@account_reports/components/account_report/filters/filters";
import { registry } from "@web/core/registry";

const customComponentsRegistry = registry.category("account_reports_custom_components");

const SIBLING_FILTERS_TEMPLATE = "custom_account_report_filter.SapReportFilters";

export class GLHideInitialBalanceFilters extends AccountReportFilters {
    static template = "account_general_ledger_hide_initial_balance.GLHideInitialBalanceFilters";

    get contentTemplate() {
        // Si le module frere custom_account_report_filter est installe, sa
        // composante personnalise deja la barre de filtres : on chaine sur son
        // gabarit pour que les deux boutons personnalises s'affichent.
        if (customComponentsRegistry.contains(SIBLING_FILTERS_TEMPLATE)) {
            return SIBLING_FILTERS_TEMPLATE;
        }
        return "account_reports.AccountReportFiltersCustomizable";
    }
}

AccountReport.registerCustomComponent(GLHideInitialBalanceFilters);

// Le module frere custom_account_report_filter customise lui aussi la barre de
// filtres du Grand Livre via `_get_custom_display_config`. Selon l'ordre de
// chargement des modules (alphabetique : account_* avant custom_*), c'est SON
// gabarit qui est reference dans la config d'affichage. On re-enregistre donc
// notre composante sous la cle de son gabarit : le rendu utilise alors notre
// composante (qui re-appelle son gabarit et ajoute notre bouton), quel que soit
// l'ordre de chargement. Sur le Livre des Tiers, notre bloc reste masque car
// l'option n'y est pas initialisee.
//
// L'ordre de chargement des fichiers JS n'etant pas garanti non plus, on
// reagit aussi a l'evenement UPDATE du registre (couvre le cas ou le module
// frere s'enregistre apres nous).
function chainOnSiblingFilters() {
    if (!customComponentsRegistry.contains(SIBLING_FILTERS_TEMPLATE)) {
        return false;
    }
    customComponentsRegistry.add(SIBLING_FILTERS_TEMPLATE, GLHideInitialBalanceFilters);
    return true;
}

if (!chainOnSiblingFilters()) {
    const listener = (payload) => {
        if (
            payload.operation === "add" &&
            payload.key === SIBLING_FILTERS_TEMPLATE &&
            payload.value !== GLHideInitialBalanceFilters &&
            chainOnSiblingFilters()
        ) {
            off();
        }
    };
    const off = () => customComponentsRegistry.removeEventListener("UPDATE", listener);
    customComponentsRegistry.addEventListener("UPDATE", listener);
}
