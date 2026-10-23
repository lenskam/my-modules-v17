# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    """Paramètres de l'abonnement Odoo (Paramètres → Abonnement).

    Jour de facturation, délai de paiement, intervalles de rappel,
    destinataires et modèles d'email : tout est paramétrable ici.
    """
    _inherit = 'res.config.settings'

    subscription_billing_day = fields.Integer(
        string="Jour de facturation", default=25,
        config_parameter='subscription.billing_day')
    subscription_payment_delay_days = fields.Integer(
        string="Délai de paiement (jours)", default=15,
        config_parameter='subscription.payment_delay_days')
    subscription_reminder_days = fields.Char(
        string="Intervalles de rappel (J-X)", default='10,5,2,1',
        config_parameter='subscription.reminder_days')
    subscription_suspension_alert = fields.Boolean(
        string="Alerte le jour de la suspension", default=True)
    subscription_recipient_partner_ids = fields.Many2many(
        'res.partner', string="Destinataires (contacts)",
        domain=[('email', '!=', False)])
    subscription_recipient_emails = fields.Char(
        string="Emails supplémentaires",
        help="Adresses email séparées par des virgules")
    subscription_reminder_template_id = fields.Many2one(
        'mail.template', string="Modèle d'email de rappel (défaut)",
        domain=[('model', '=', 'subscription.billing.cycle')],
        config_parameter='subscription.reminder_template_id',
        help="Modèle utilisé quand aucun modèle par intervalle de rappel "
             "ne correspond (Modèles d'email par intervalle).")
    subscription_suspension_template_id = fields.Many2one(
        'mail.template', string="Modèle d'email de suspension",
        domain=[('model', '=', 'subscription.billing.cycle')],
        config_parameter='subscription.suspension_template_id')
    subscription_login_message_top = fields.Char(
        string="Message au-dessus du formulaire de connexion",
        default=lambda self: self.env['subscription.control'].LOGIN_MSG_DEFAULT,
        config_parameter='subscription.login_message_top')
    subscription_login_message_bottom = fields.Char(
        string="Message sous le formulaire de connexion",
        config_parameter='subscription.login_message_bottom')
    # --- Blocage d'accès : mode d'expiration des sessions ---
    subscription_enforcement_mode = fields.Selection([
        ('session', "Expiration des sessions (recommandé)"),
        ('groups', "Révocation des groupes d'accès"),
        ('none', "Aucun blocage local (instance centrale)"),
    ], string="Mode de blocage à l'expiration",
        default='session',
        config_parameter='subscription.enforcement_mode',
        help="Mécanisme appliqué quand l'abonnement est expiré : « Expiration "
             "des sessions » déconnecte les utilisateurs actifs après le délai "
             "et bloque la connexion ; « Révocation des groupes » retire les "
             "droits (comportement historique) ; « Aucun » délègue le blocage "
             "à l'instance centrale (instance_control).")
    subscription_force_session_expiry_delay = fields.Integer(
        string="Durée de vie des sessions (minutes)",
        default=60,
        config_parameter='subscription.force_session_expiry_delay',
        help="Durée après laquelle une session expirée est supprimée une fois "
             "l'abonnement échu. Appliquée uniquement si le mode de blocage "
             "est « Expiration des sessions ».")
    # --- Toggles de fonctionnalités (cohabitation instance centrale) ---
    subscription_billing_engine_enabled = fields.Boolean(
        string="Moteur de facturation local",
        default=True,
        help="Création des cycles, rappels et suspension locale. Désactivez "
             "si l'instance centrale (instance_control) gère la facturation ; "
             "les cycles restent affichés en lecture seule.")
    subscription_email_alerts_enabled = fields.Boolean(
        string="Alertes par email",
        default=True,
        help="Envoi des emails de rappel et de suspension. Désactivez si les "
             "emails sont envoyés par l'instance centrale.")
    subscription_internal_alerts_enabled = fields.Boolean(
        string="Alertes natives Odoo",
        default=True,
        help="Messages dans le chatter, Discuss et fenêtres modales. Désactivez "
             "si les alertes sont gérées par l'instance centrale.")
    # --- Odoo de facturation distant (synchro paiement) ---
    subscription_remote_enabled = fields.Boolean(
        string="Synchroniser les paiements depuis l'Odoo de facturation",
        default=False,
        help="Active la synchronisation automatique : le statut de paiement des "
             "factures est lu toutes les 4 heures sur l'Odoo externe via XML-RPC "
             "et le cycle est marqué payé automatiquement dès réception.")
    subscription_remote_odoo_url = fields.Char(
        string="URL de l'Odoo de facturation",
        config_parameter='subscription.remote_odoo_url')
    subscription_remote_odoo_db = fields.Char(
        string="Base de données distante",
        config_parameter='subscription.remote_odoo_db')
    subscription_remote_odoo_user = fields.Char(
        string="Utilisateur API",
        config_parameter='subscription.remote_odoo_user')
    subscription_remote_odoo_api_key = fields.Char(
        string="Clé API",
        config_parameter='subscription.remote_odoo_api_key',
        help="Clé API de l'utilisateur distant (recommandé), jamais le mot de passe "
             "en clair dans le code.")
    subscription_client_name = fields.Char(
        string="Nom du client (alertes)",
        config_parameter='subscription.client_name',
        help="Nom affiché dans les alertes et emails. Si vide et qu'une facture "
             "distante existe, le nom du partenaire distant est utilisé.")
    subscription_remote_partner_id = fields.Integer(
        string="ID du partenaire distant",
        config_parameter='subscription.remote_partner_id',
        help="ID du res.partner sur l'Odoo de facturation (secours si la référence "
             "de facture attendue n'est pas trouvée).")

    # many2many non supporté par config_parameter : stockage manuel en JSON
    # (liste d'IDs séparés par des virgules)
    @api.model
    def get_values(self):
        res = super().get_values()
        param = self.env['ir.config_parameter'].sudo()
        partner_ids = []
        for part in str(param.get_param('subscription.recipient_partner_ids') or '').split(','):
            part = part.strip()
            if part.isdigit():
                partner_ids.append(int(part))
        res['subscription_recipient_partner_ids'] = [(6, 0, partner_ids)]
        res['subscription_recipient_emails'] = param.get_param(
            'subscription.recipient_emails') or ''
        # Booléen : stockage manuel 'True'/'False' (set_param(False) supprime
        # le paramètre, on ne peut pas utiliser config_parameter ici)
        res['subscription_suspension_alert'] = str(
            param.get_param('subscription.suspension_alert') or 'True'
        ).strip().lower() in ('true', '1', 'yes')
        res['subscription_remote_enabled'] = str(
            param.get_param('subscription.remote_enabled') or 'False'
        ).strip().lower() in ('true', '1', 'yes')
        res['subscription_billing_engine_enabled'] = str(
            param.get_param('subscription.billing_engine_enabled') or 'True'
        ).strip().lower() in ('true', '1', 'yes')
        res['subscription_email_alerts_enabled'] = str(
            param.get_param('subscription.email_alerts_enabled') or 'True'
        ).strip().lower() in ('true', '1', 'yes')
        res['subscription_internal_alerts_enabled'] = str(
            param.get_param('subscription.internal_alerts_enabled') or 'True'
        ).strip().lower() in ('true', '1', 'yes')
        res['subscription_enforcement_mode'] = \
            self.env['subscription.control'].get_enforcement_mode()
        return res

    def set_values(self):
        super().set_values()
        param = self.env['ir.config_parameter'].sudo()
        param.set_param(
            'subscription.recipient_partner_ids',
            ','.join(str(pid) for pid in self.subscription_recipient_partner_ids.ids))
        param.set_param(
            'subscription.recipient_emails',
            (self.subscription_recipient_emails or '').strip())
        param.set_param(
            'subscription.suspension_alert',
            'True' if self.subscription_suspension_alert else 'False')
        param.set_param(
            'subscription.remote_enabled',
            'True' if self.subscription_remote_enabled else 'False')
        param.set_param(
            'subscription.billing_engine_enabled',
            'True' if self.subscription_billing_engine_enabled else 'False')
        param.set_param(
            'subscription.email_alerts_enabled',
            'True' if self.subscription_email_alerts_enabled else 'False')
        param.set_param(
            'subscription.internal_alerts_enabled',
            'True' if self.subscription_internal_alerts_enabled else 'False')
        # Le mode de blocage est persisté automatiquement via config_parameter.

    def action_open_reminder_template(self):
        """Ouvre le modèle d'email de rappel (par défaut ou configuré)."""
        self.ensure_one()
        # Priorité au modèle configuré, sinon le modèle par défaut du module
        template_id = self.subscription_reminder_template_id.id
        if not template_id:
            template_id = self.env.ref('subscription_control.subscription_mail_template_reminder').id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mail.template',
            'res_id': template_id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_suspension_template(self):
        """Ouvre le modèle d'email de suspension (par défaut ou configuré)."""
        self.ensure_one()
        template_id = self.subscription_suspension_template_id.id
        if not template_id:
            template_id = self.env.ref('subscription_control.subscription_mail_template_suspension').id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mail.template',
            'res_id': template_id,
            'view_mode': 'form',
            'target': 'current',
        }
