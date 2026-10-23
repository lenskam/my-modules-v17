/** @odoo-module */

import { AccountReport } from "@account_reports/components/account_report/account_report";
import { AccountReportFilters } from "@account_reports/components/account_report/filters/filters";

export class SapReportFilters extends AccountReportFilters {
    static template = "custom_account_report_filter.SapReportFilters";
}

AccountReport.registerCustomComponent(SapReportFilters);
