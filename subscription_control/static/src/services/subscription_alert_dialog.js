/** @odoo-module **/

import { Dialog } from "@web/core/dialog/dialog";

export class SubscriptionAlertDialog extends Dialog {
    setup() {
        super.setup();
        if (!this.props.closable) {
            this.data.close = () => {};
        }
    }
}
SubscriptionAlertDialog.template = "subscription_control.SubscriptionAlertDialog";
SubscriptionAlertDialog.props = {
    message: String,
    closable: { type: Boolean, optional: true },
    title: { type: String, optional: true },
    size: {
        type: String,
        optional: true,
        validate: (s) => ["sm", "md", "lg", "xl", "fs"].includes(s),
    },
    modalRef: { type: Function, optional: true },
};
