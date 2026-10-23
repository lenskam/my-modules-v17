/** @odoo-module **/

import { registry } from "@web/core/registry";
import { SubscriptionAlertDialog } from "./subscription_alert_dialog";

export const subscriptionAlertService = {
    dependencies: ["bus_service", "dialog", "orm"],

    start(env, { bus_service, dialog, orm }) {
        const showAlert = (payload) => {
            dialog.add(SubscriptionAlertDialog, {
                title: payload.title || "Abonnement",
                message: payload.message || "",
                closable: payload.closable !== false,
                size: "md",
            });
        };

        // Rappels et alertes poussés en temps réel (cron, suspensions)
        bus_service.subscribe("subscription_control.alert", showAlert);
        bus_service.start();

        // Statut au chargement : modal bloquante si l'utilisateur est suspendu
        orm.silent
            .call("subscription.control", "get_session_alert", [])
            .then((alert) => {
                if (alert && alert.show) {
                    showAlert(alert);
                }
            })
            .catch(() => {});
    },
};

registry.category("services").add("subscription_alert", subscriptionAlertService);
