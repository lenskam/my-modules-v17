# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from odoo.addons.instance_control.models.odoo_xmlrpc_client import OdooXmlrpcClient

_logger = logging.getLogger(__name__)


class InstanceManagement(models.Model):
    """Registre des instances Odoo gérées par le contrôleur central.

    Chaque enregistrement décrit une instance distante (connexion XML-RPC vers
    le module client subscription_control), son client et son montant mensuel.
    Les paramètres globaux de facturation et d'alertes sont également portés
    par ce modèle (Paramètres → Instances Odoo).
    """
    _name = 'instance.management'
    _description = 'Instance Odoo gérée'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    # Paramètres système (configurables dans Paramètres → Instances Odoo)
    BILLING_DAY_PARAM = 'instance_control.billing_day'
    PAYMENT_DELAY_PARAM = 'instance_control.payment_delay_days'
    REMINDER_DAYS_PARAM = 'instance_control.reminder_days'
    SUSPENSION_ALERT_PARAM = 'instance_control.suspension_alert_enabled'
    PRODUCT_PARAM = 'instance_control.product_id'
    RECIPIENT_PARTNERS_PARAM = 'instance_control.recipient_partner_ids'
    RECIPIENT_EMAILS_PARAM = 'instance_control.recipient_emails'
    REMINDER_TEMPLATE_PARAM = 'instance_control.reminder_template_id'
    SUSPENSION_TEMPLATE_PARAM = 'instance_control.suspension_template_id'
    EXTEND_DAYS_PARAM = 'instance_control.extend_days'

    BILLING_DAY_DEFAULT = 25
    PAYMENT_DELAY_DEFAULT = 15
    REMINDER_DAYS_DEFAULT = '10,5,2,1'
    EXTEND_DAYS_DEFAULT = 30

    name = fields.Char(string='Nom', required=True, tracking=True)
    url = fields.Char(string='URL', required=True, tracking=True,
                      help="URL de base de l'instance distante, "
                           "ex : https://client1.exemple.com")
    database = fields.Char(string='Base de données', required=True, tracking=True)
    login = fields.Char(string='Utilisateur API', required=True,
                        help="Utilisateur administrateur (base.group_system) "
                             "sur l'instance distante, avec une clé API.")
    api_key = fields.Char(string='Clé API', required=True)
    partner_id = fields.Many2one(
        'res.partner', string='Client à facturer', tracking=True)
    monthly_amount = fields.Float(
        string='Montant mensuel', digits='Product Price', tracking=True)
    currency_id = fields.Many2one(
        'res.currency', string='Devise',
        default=lambda self: self.env.company.currency_id)
    state = fields.Selection([
        ('active', 'Active'),
        ('suspended', 'Suspendue'),
        ('unreachable', 'Injoignable'),
    ], string='État', default='active', index=True, tracking=True)
    expiration_date = fields.Date(
        string='Expiration distante', readonly=True,
        help="Dernière date d'expiration lue sur l'instance distante.")
    last_check = fields.Datetime(string='Dernier contact API', readonly=True)
    last_error = fields.Char(string='Dernière erreur API', readonly=True)
    active = fields.Boolean(string='Actif', default=True,
                            help="Décochez pour archiver une instance non gérée.")
    cycle_ids = fields.One2many(
        'instance.billing.cycle', 'instance_id', string='Cycles de facturation')
    cycle_count = fields.Integer(string='Cycles', compute='_compute_cycle_count')

    # Facturation : override par instance (0/vide = utilise la valeur globale)
    billing_day = fields.Integer(
        string='Jour de facturation', tracking=True,
        help="Jour du mois de facturation propre à cette instance. "
             "0 = utilise la valeur globale (Paramètres → Instances Odoo).")
    payment_delay_days = fields.Integer(
        string='Délai de paiement (jours)', tracking=True,
        help="Délai de paiement propre à cette instance, utilisé pour "
             "calculer la date de suspension. 0 = utilise la valeur globale.")
    reminder_days = fields.Char(
        string='Intervalles de rappel (J-X)',
        help="Intervalles de rappel propres à cette instance, séparés par "
             "des virgules (ex : 10,5,2,1). Vide = utilise la valeur globale.")
    product_id = fields.Many2one(
        'product.product', string="Produit d'abonnement",
        tracking=True,
        help="Produit facturé sur les factures de cette instance. "
             "Vide = utilise le produit global.")

    # Alertes : configuration propre à chaque instance (destinataires, emails)
    suspension_alert_enabled = fields.Boolean(
        string='Alerte le jour de la suspension',
        default=lambda self:
            self.env['instance.management'].is_suspension_alert_enabled(),
        tracking=True,
        help="Envoie l'alerte de suspension par email pour cette instance.")
    recipient_partner_ids = fields.Many2many(
        'res.partner', 'instance_control_instance_partner_rel',
        'instance_id', 'partner_id', string='Destinataires (contacts)',
        domain=[('email', '!=', False)],
        help="Contacts destinataires des rappels et alertes de CETTE "
             "instance. Vide = utilise les destinataires globaux.")
    recipient_emails = fields.Char(
        string='Emails supplémentaires',
        help="Adresses email séparées par des virgules, spécifiques à cette "
             "instance. Vide = utilise les destinataires globaux.")
    reminder_template_id = fields.Many2one(
        'mail.template', string="Modèle d'email de rappel (défaut)",
        domain=[('model', '=', 'instance.billing.cycle')],
        help="Modèle utilisé quand aucun modèle par intervalle ne "
             "correspond au rappel (repli : modèle global, puis défaut "
             "du module).")
    suspension_template_id = fields.Many2one(
        'mail.template', string="Modèle d'email de suspension",
        domain=[('model', '=', 'instance.billing.cycle')],
        help="Modèle d'email de suspension pour cette instance. "
             "Vide = utilise le modèle global (ou le défaut du module).")
    mail_template_line_ids = fields.One2many(
        'instance.mail.template.line', 'instance_id',
        string="Modèles d'email par intervalle de rappel",
        help="Pour un rappel J-N, le modèle dont l'intervalle est le plus "
             "proche inférieur ou égal à N est utilisé "
             "(ex. interval 2 = J-2 et J-1).")

    # Push Helpdesk (module helpdesk_subscription_control, Odoo 11)
    helpdesk_push_enabled = fields.Boolean(
        string='Contrôle Helpdesk', default=False, tracking=True,
        help="Pousse l'état d'abonnement vers le module Helpdesk de cette "
             "instance (Odoo 11) : la création de tickets y est bloquée dès "
             "que l'abonnement est suspendu.")
    helpdesk_signal_token = fields.Char(
        string='Token Helpdesk',
        help="Token configuré sur l'instance Helpdesk (Paramètres → "
             "Abonnement Helpdesk).")
    last_helpdesk_push_on = fields.Datetime(
        string='Dernier push Helpdesk', readonly=True)
    last_helpdesk_push_state = fields.Char(
        string='Dernier état Helpdesk', readonly=True)
    last_helpdesk_push_error = fields.Text(
        string='Erreur push Helpdesk', readonly=True)

    _sql_constraints = [
        ('database_url_unique', 'UNIQUE(database, url)',
         'Cette instance (URL + base de données) est déjà enregistrée.'),
    ]

    @api.depends('cycle_ids')
    def _compute_cycle_count(self):
        for instance in self:
            instance.cycle_count = len(instance.cycle_ids)

    # ------------------------------------------------------------------
    # Paramètres globaux (facturation, rappels, alertes)
    # ------------------------------------------------------------------

    def _get_param(self, key, default=None):
        val = self.env['ir.config_parameter'].sudo().get_param(key)
        return val if val not in (None, '') else default

    @api.model
    def get_billing_day(self):
        """Jour du mois de facturation (défaut : 25)."""
        try:
            day = int(self._get_param(self.BILLING_DAY_PARAM,
                                      self.BILLING_DAY_DEFAULT))
        except (ValueError, TypeError):
            return self.BILLING_DAY_DEFAULT
        return day if 1 <= day <= 31 else self.BILLING_DAY_DEFAULT

    @api.model
    def get_payment_delay_days(self):
        """Délai de paiement en jours après la facturation (défaut : 15)."""
        try:
            delay = int(self._get_param(self.PAYMENT_DELAY_PARAM,
                                        self.PAYMENT_DELAY_DEFAULT))
        except (ValueError, TypeError):
            return self.PAYMENT_DELAY_DEFAULT
        return delay if delay >= 0 else self.PAYMENT_DELAY_DEFAULT

    @api.model
    def _parse_reminder_days(self, val):
        """Parse une liste d'intervalles '10,5,2,1' (dédupliquée, triée)."""
        days = set()
        for part in str(val or '').split(','):
            part = part.strip()
            if not part:
                continue
            try:
                day = int(part)
            except ValueError:
                continue
            if day >= 0:
                days.add(day)
        return sorted(days, reverse=True)

    @api.model
    def get_reminder_days(self):
        """Intervalles de rappel globaux (jours avant suspension), triés du plus grand."""
        val = self._get_param(self.REMINDER_DAYS_PARAM, self.REMINDER_DAYS_DEFAULT)
        return self._parse_reminder_days(val)

    @api.model
    def is_suspension_alert_enabled(self):
        """Alerte envoyée le jour de la suspension (défaut : True)."""
        val = self._get_param(self.SUSPENSION_ALERT_PARAM, 'True')
        return str(val).strip().lower() in ('true', '1', 'yes')

    @api.model
    def get_product(self):
        """Produit d'abonnement facturé sur l'Odoo central."""
        pid = self._get_param(self.PRODUCT_PARAM)
        if pid and str(pid).isdigit():
            return self.env['product.product'].browse(int(pid)).exists()
        return self.env['product.product']

    @api.model
    def get_extend_days(self):
        """Durée de prolongation par défaut en jours (défaut : 30)."""
        try:
            days = int(self._get_param(self.EXTEND_DAYS_PARAM,
                                       self.EXTEND_DAYS_DEFAULT))
        except (ValueError, TypeError):
            return self.EXTEND_DAYS_DEFAULT
        return days if days > 0 else self.EXTEND_DAYS_DEFAULT

    @api.model
    def get_recipient_partner_ids(self):
        """Contacts destinataires des rappels/alertes."""
        val = self._get_param(self.RECIPIENT_PARTNERS_PARAM) or ''
        partner_ids = []
        for part in str(val).split(','):
            part = part.strip()
            if part.isdigit():
                partner_ids.append(int(part))
        return self.env['res.partner'].browse(partner_ids).exists()

    @api.model
    def get_recipient_emails(self):
        """Adresses email supplémentaires (séparées par des virgules)."""
        val = self._get_param(self.RECIPIENT_EMAILS_PARAM) or ''
        return ','.join(part.strip() for part in str(val).split(',') if part.strip())

    @api.model
    def get_reminder_template(self):
        """Modèle d'email de rappel (configuré ou défaut du module)."""
        template_id = self._get_param(self.REMINDER_TEMPLATE_PARAM)
        if template_id and str(template_id).isdigit():
            template = self.env['mail.template'].browse(int(template_id)).exists()
            if template:
                return template
        return self.env.ref(
            'instance_control.instance_mail_template_reminder',
            raise_if_not_found=False)

    @api.model
    def get_suspension_template(self):
        """Modèle d'email de suspension (configuré ou défaut du module)."""
        template_id = self._get_param(self.SUSPENSION_TEMPLATE_PARAM)
        if template_id and str(template_id).isdigit():
            template = self.env['mail.template'].browse(int(template_id)).exists()
            if template:
                return template
        return self.env.ref(
            'instance_control.instance_mail_template_suspension',
            raise_if_not_found=False)

    # ------------------------------------------------------------------
    # Configuration EFFECTIVE par instance (instance → global → défaut)
    # Utilisée par le moteur de facturation pour chaque instance.
    # ------------------------------------------------------------------

    def _get_billing_day(self):
        """Jour de facturation effectif (instance, sinon global)."""
        self.ensure_one()
        if self.billing_day and 1 <= self.billing_day <= 31:
            return self.billing_day
        return self.get_billing_day()

    def _get_payment_delay_days(self):
        """Délai de paiement effectif (instance, sinon global)."""
        self.ensure_one()
        if self.payment_delay_days and self.payment_delay_days > 0:
            return self.payment_delay_days
        return self.get_payment_delay_days()

    def _get_reminder_days(self):
        """Intervalles de rappel effectifs (instance, sinon global)."""
        self.ensure_one()
        val = (self.reminder_days or '').strip()
        if not val:
            val = self._get_param(self.REMINDER_DAYS_PARAM,
                                  self.REMINDER_DAYS_DEFAULT)
        return self._parse_reminder_days(val)

    def _get_product(self):
        """Produit d'abonnement effectif (instance, sinon global)."""
        self.ensure_one()
        return self.product_id or self.get_product()

    def _is_suspension_alert_enabled(self):
        """Alerte de suspension activée pour cette instance."""
        self.ensure_one()
        return self.suspension_alert_enabled

    def _get_recipient_partner_ids(self):
        """Contacts destinataires effectifs (instance, sinon global)."""
        self.ensure_one()
        return self.recipient_partner_ids or self.get_recipient_partner_ids()

    def _get_recipient_emails(self):
        """Emails destinataires effectifs (instance, sinon global)."""
        self.ensure_one()
        val = (self.recipient_emails or '').strip()
        if val:
            return ','.join(p.strip() for p in val.split(',') if p.strip())
        return self.get_recipient_emails()

    def _get_reminder_template(self):
        """Modèle d'email de rappel effectif (instance, sinon global/défaut)."""
        self.ensure_one()
        if self.reminder_template_id:
            return self.reminder_template_id
        return self.get_reminder_template()

    def _get_reminder_email_template(self, days_until):
        """Modèle d'email de rappel effectif pour le rappel J-N.

        D'abord les modèles par intervalle de l'instance : celui dont
        l'intervalle est le plus proche inférieur ou égal à N (ex. interval
        2 pour J-2 et J-1) ; à défaut, le plus petit intervalle défini.
        Sans intervalles configurés, repli sur le modèle par défaut de
        l'instance, puis global, puis défaut du module.
        """
        self.ensure_one()
        line_model = self.env['instance.mail.template.line']
        line = line_model.search([
            ('instance_id', '=', self.id),
            ('trigger_days', '<=', days_until),
        ], order='trigger_days desc', limit=1)
        if not line:
            line = line_model.search([
                ('instance_id', '=', self.id),
            ], order='trigger_days asc', limit=1)
        if line and line.mail_template_id:
            return line.mail_template_id
        return self._get_reminder_template()

    def _get_suspension_template(self):
        """Modèle d'email de suspension effectif (instance, sinon global/défaut)."""
        self.ensure_one()
        if self.suspension_template_id:
            return self.suspension_template_id
        return self.get_suspension_template()

    # ------------------------------------------------------------------
    # Communication XML-RPC avec l'instance distante
    # ------------------------------------------------------------------

    def _get_client(self):
        """Fabrique le client XML-RPC (remplaçable dans les tests)."""
        self.ensure_one()
        return OdooXmlrpcClient(self.url, self.database, self.login, self.api_key)

    def _fmt_date(self, date_val):
        return date_val.strftime('%d/%m/%Y') if date_val else ''

    def _sync_status(self, silent=False):
        """Synchronise l'état distant (authentification + date d'expiration).

        silent=True : enregistre l'erreur et continue (crons) ;
        silent=False : lève une UserError (bouton de test).
        """
        for instance in self:
            try:
                client = instance._get_client()
                expiration = client.get_expiration_date()
                instance.write({
                    'expiration_date': expiration,
                    'last_check': fields.Datetime.now(),
                    'last_error': False,
                    'state': ('active'
                              if instance.state in ('unreachable', False, None)
                              else instance.state),
                })
                if not silent:
                    instance.message_post(body=_(
                        "Connexion réussie. Expiration distante : %s.",
                        instance._fmt_date(expiration) or '—'))
            except Exception as e:
                instance.write({
                    'state': 'unreachable',
                    'last_error': str(e)[:255],
                })
                if not silent:
                    raise UserError(_(
                        "Connexion à l'instance « %s » impossible : %s",
                        instance.name, e))
                _logger.error("Instance %s injoignable : %s", instance.name, e)

    def action_test_connection(self):
        """Bouton « Tester la connexion » : valide la connexion distante."""
        self._sync_status(silent=False)
        return True

    def action_sync_status(self):
        """Bouton « Synchroniser l'état » : lecture silencieuse du statut."""
        self._sync_status(silent=True)
        return True

    @api.model
    def _sync_all_status(self):
        """Cron quotidien : miroir du statut de toutes les instances actives."""
        self.search([('active', '=', True)])._sync_status(silent=True)

    def _remote_suspend(self, today):
        """Suspend l'instance distante (expiration + blocage d'accès)."""
        self.ensure_one()
        client = self._get_client()
        client.set_expiration_date(today)
        client.block_access_if_expired()
        self.write({
            'state': 'suspended',
            'expiration_date': today,
            'last_check': fields.Datetime.now(),
            'last_error': False,
        })
        # Le Helpdesk distant bloque la création de tickets immédiatement
        self.push_helpdesk_signal()

    def _remote_restore(self, expiration_date=None, raise_on_error=False):
        """Rétablit l'instance distante (nouvelle expiration + restauration).

        Retourne True en cas de succès ; en échec, enregistre l'erreur sur
        l'instance (et lève si raise_on_error, pour les boutons manuels).
        """
        self.ensure_one()
        try:
            client = self._get_client()
            if not expiration_date:
                expiration_date = fields.Date.context_today(self) + timedelta(
                    days=self.get_extend_days())
            client.set_expiration_date(expiration_date)
            client.restore_access()
            self.write({
                'state': 'active',
                'expiration_date': expiration_date,
                'last_check': fields.Datetime.now(),
                'last_error': False,
            })
            # Le Helpdesk distant est rétabli immédiatement
            self.push_helpdesk_signal()
            return True
        except Exception as e:
            self.write({'state': 'unreachable', 'last_error': str(e)[:255]})
            if raise_on_error:
                raise UserError(_(
                    "Rétablissement distant impossible pour « %s » : %s",
                    self.name, e))
            _logger.error("Rétablissement distant échoué (%s) : %s",
                          self.name, e)
            return False

    # ------------------------------------------------------------------
    # Push Helpdesk (Odoo 11, module helpdesk_subscription_control)
    # ------------------------------------------------------------------

    def _build_helpdesk_payload(self):
        """Construit le signal d'état d'abonnement de cette instance pour
        son module Helpdesk (helpdesk_subscription_control, Odoo 11)."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        is_expired = self.state == 'suspended' or (
            self.expiration_date and today > self.expiration_date)
        cycle = self.env['instance.billing.cycle'].search([
            ('instance_id', '=', self.id),
            ('state', 'in', ('awaiting_payment', 'suspended')),
        ], limit=1, order='billing_date desc')
        suspension = billing = False
        invoice_ref = ''
        invoice_amount = 0.0
        invoice_currency = ''
        if cycle:
            suspension = cycle.suspension_date
            billing = cycle.billing_date
            invoice = cycle.invoice_id
            if invoice:
                invoice_ref = invoice.name or ''
                invoice_amount = invoice.amount_total or 0.0
                invoice_currency = invoice.currency_id.name or ''
        return {
            'expiration_date': fields.Date.to_string(self.expiration_date)
                if self.expiration_date else False,
            'is_expired': is_expired,
            'suspension_date': fields.Date.to_string(suspension)
                if suspension else False,
            'billing_date': fields.Date.to_string(billing)
                if billing else False,
            'invoice_ref': invoice_ref,
            'invoice_amount': invoice_amount,
            'invoice_currency': invoice_currency,
            'client_name': self.partner_id.name or self.name,
        }

    def push_helpdesk_signal(self):
        """Pousse l'état d'abonnement vers le Helpdesk de l'instance
        distante (endpoint /helpdesk_subscription/signal)."""
        for instance in self:
            if not instance.helpdesk_push_enabled:
                continue
            payload = instance._build_helpdesk_payload()
            payload['db'] = instance.database
            payload['token'] = instance.helpdesk_signal_token or ''
            state_label = _('Suspendu') if payload['is_expired'] else _('Actif')
            try:
                response = requests.post(
                    (instance.url or '').rstrip('/') +
                    '/helpdesk_subscription/signal',
                    json=payload, timeout=15)
                response.raise_for_status()
                data = response.json()
                if data.get('status') != 'ok':
                    raise UserError(
                        data.get('message') or _('Réponse inattendue'))
                instance.write({
                    'last_helpdesk_push_on': fields.Datetime.now(),
                    'last_helpdesk_push_state': state_label,
                    'last_helpdesk_push_error': False,
                })
                _logger.info(
                    "État abonnement poussé vers le Helpdesk de %s : %s",
                    instance.name, state_label)
            except Exception as e:
                instance.write({
                    'last_helpdesk_push_on': fields.Datetime.now(),
                    'last_helpdesk_push_state': state_label,
                    'last_helpdesk_push_error': str(e)[:1000],
                })
                _logger.error(
                    "Push Helpdesk échoué pour %s : %s", instance.name, e)

    def action_push_helpdesk_signal(self):
        """Bouton « Tester le push Helpdesk »."""
        self.push_helpdesk_signal()
        return True

    @api.model
    def cron_push_helpdesk_signals(self):
        """Cron : garde les Helpdesk des instances actives synchronisés."""
        self.search([
            ('active', '=', True),
            ('helpdesk_push_enabled', '=', True),
        ]).push_helpdesk_signal()

    # ------------------------------------------------------------------
    # Actions manuelles
    # ------------------------------------------------------------------

    def action_suspend_now(self):
        """Bouton « Suspendre maintenant » : blocage immédiat à distance."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        self._remote_suspend(today)
        self.message_post(body=_(
            "Instance suspendue manuellement (expiration distante : %s).",
            self._fmt_date(today)))
        return True

    def action_restore(self):
        """Bouton « Rétablir » : restauration immédiate à distance."""
        self.ensure_one()
        if self._remote_restore(raise_on_error=True):
            self.message_post(body=_("Instance rétablie manuellement."))
        return True

    def action_extend(self):
        """Bouton « Prolonger » : ouvre le wizard de prolongation."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'instance.extend.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_instance_id': self.id},
        }

    def action_view_cycles(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cycles de facturation'),
            'res_model': 'instance.billing.cycle',
            'view_mode': 'tree,form',
            'domain': [('instance_id', '=', self.id)],
        }
