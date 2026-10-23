# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    """Valeurs par défaut GLOBALES du contrôleur d'instances.

    Ces valeurs servent de repli quand une instance ne définit pas sa
    propre configuration (jour de facturation, délai de paiement,
    intervalles de rappel, produit) et de défaut pour les nouvelles
    instances (alerte de suspension). Les destinataires et les modèles
    d'email sont configurés instance par instance sur la fiche de chaque
    instance gérée (onglets « Facturation » et « Alertes & Notifications »).
    """
    _inherit = 'res.config.settings'

    instance_billing_day = fields.Integer(
        string="Jour de facturation", default=25,
        config_parameter='instance_control.billing_day',
        help="Valeur par défaut quand l'instance ne définit pas son propre "
             "jour de facturation.")
    instance_payment_delay_days = fields.Integer(
        string="Délai de paiement (jours)", default=15,
        config_parameter='instance_control.payment_delay_days',
        help="Valeur par défaut quand l'instance ne définit pas son propre "
             "délai de paiement.")
    instance_reminder_days = fields.Char(
        string="Intervalles de rappel (J-X)", default='10,5,2,1',
        config_parameter='instance_control.reminder_days',
        help="Valeur par défaut quand l'instance ne définit pas ses "
             "intervalles de rappel.")
    instance_suspension_alert = fields.Boolean(
        string="Alerte de suspension (défaut nouvelles instances)",
        default=True,
        help="Valeur appliquée par défaut aux nouvelles instances ; chaque "
             "instance peut ensuite être ajustée individuellement sur sa "
             "fiche (onglet « Alertes & Notifications »).")
    instance_product_id = fields.Many2one(
        'product.product', string="Produit d'abonnement (défaut)",
        config_parameter='instance_control.product_id',
        help="Produit facturé par défaut sur les factures générées dans "
             "l'Odoo central ; un produit spécifique peut être défini sur "
             "chaque instance.")
    instance_extend_days = fields.Integer(
        string="Prolongation par défaut (jours)", default=30,
        config_parameter='instance_control.extend_days',
        help="Durée (en jours) appliquée lors d'un rétablissement ou d'une "
             "prolongation (ex : 30).")

    # Booléen : stockage manuel 'True'/'False' (set_param(False) supprime
    # le paramètre, on ne peut pas utiliser config_parameter ici)
    @api.model
    def get_values(self):
        res = super().get_values()
        param = self.env['ir.config_parameter'].sudo()
        res['instance_suspension_alert'] = str(
            param.get_param('instance_control.suspension_alert_enabled')
            or 'True'
        ).strip().lower() in ('true', '1', 'yes')
        return res

    def set_values(self):
        super().set_values()
        param = self.env['ir.config_parameter'].sudo()
        param.set_param(
            'instance_control.suspension_alert_enabled',
            'True' if self.instance_suspension_alert else 'False')
