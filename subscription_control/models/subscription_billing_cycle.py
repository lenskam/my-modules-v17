# -*- coding: utf-8 -*-
import calendar
import logging
import string
from datetime import timedelta

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

MONTHS = [
    'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
    'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre',
]


class SubscriptionBillingCycle(models.Model):
    """Cycle de facturation mensuel de l'abonnement.

    Un cycle est créé automatiquement à la date de facturation (paramétrable,
    25 par défaut). La date de suspension est calculée à partir de la date de
    facturation + délai de paiement (paramétrable, 15 jours par défaut).
    Des rappels sont envoyés aux intervalles configurés, puis le service est
    suspendu à la date de suspension si le paiement n'est pas enregistré.
    """
    _name = 'subscription.billing.cycle'
    _description = 'Cycle de facturation abonnement'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'billing_date desc'

    name = fields.Char(string='Référence', compute='_compute_name', store=True)
    billing_date = fields.Date(
        string='Date de facturation', required=True, index=True, tracking=True)
    suspension_date = fields.Date(
        string='Date de suspension', compute='_compute_suspension_date',
        store=True, readonly=False, index=True, tracking=True,
        help='Calculée par défaut : date de facturation + délai de paiement. '
             'Modifiable manuellement pour prolonger le cycle.')
    state = fields.Selection([
        ('draft', 'À venir'),
        ('awaiting_payment', 'Paiement en attente'),
        ('suspended', 'Suspendu'),
        ('paid', 'Payé'),
    ], string='Statut', default='draft', index=True, tracking=True)
    paid_on = fields.Date(string='Payé le', tracking=True)
    days_until_suspension = fields.Integer(
        string='Jours avant suspension', compute='_compute_days_until_suspension')
    reminder_log_ids = fields.One2many(
        'subscription.reminder.log', 'cycle_id', string='Rappels envoyés')
    # Donnees de facturation (Odoo distant ou configuration locale)
    client_name = fields.Char(
        string='Client', tracking=True,
        help="Nom du client affiche dans les alertes. S'il est vide, "
             "le nom de la configuration est utilise.")
    expected_invoice_ref = fields.Char(
        string='Référence de facture attendue',
        help="Référence recherchee en premier sur l'Odoo de facturation. "
             "Vide = recherche par partenaire uniquement.")
    invoice_ref = fields.Char(string='Référence facture', readonly=True)
    invoice_amount = fields.Float(string='Montant facture', readonly=True)
    invoice_currency = fields.Char(string='Devise facture', readonly=True)
    remote_move_state = fields.Char(
        string='État distant', readonly=True,
        help="État de la facture sur l'Odoo de facturation (payment_state).")
    remote_sync_on = fields.Datetime(
        string='Dernière synchro', readonly=True)
    remote_sync_error = fields.Char(
        string='Erreur de synchro', readonly=True, tracking=True)

    @api.depends('billing_date')
    def _compute_name(self):
        for rec in self:
            if rec.billing_date:
                rec.name = '%s %s' % (MONTHS[rec.billing_date.month - 1], rec.billing_date.year)
            else:
                rec.name = '/'

    @api.depends('billing_date')
    def _compute_suspension_date(self):
        delay = self.env['subscription.control'].get_payment_delay_days()
        for rec in self:
            if rec.billing_date:
                rec.suspension_date = rec.billing_date + timedelta(days=delay)
            else:
                rec.suspension_date = False

    @api.depends('suspension_date')
    def _compute_days_until_suspension(self):
        for rec in self:
            if rec.suspension_date:
                today = fields.Date.context_today(rec)
                rec.days_until_suspension = (rec.suspension_date - today).days
            else:
                rec.days_until_suspension = 0

    # ------------------------------------------------------------------
    # Moteur (appelé par le cron quotidien)
    # ------------------------------------------------------------------

    @api.model
    def run_billing_cycle(self):
        """Gère le cycle courant : création, rappels, suspension.

        Désactivé lorsque le moteur de facturation local est coupé
        (gestion déléguée à l'instance centrale) : les cycles restent
        affichés mais ne sont plus créés ni traités localement.
        """
        if not self.env['subscription.control'].is_billing_engine_enabled():
            return
        today = fields.Date.context_today(self)
        cycle = self._ensure_current_cycle(today)
        if not cycle:
            return
        cycle._process_state(today)
        cycle._process_reminders(today)
        cycle._process_suspension(today)

    @api.model
    def _billing_date_for_period(self, today, billing_day):
        """Retourne la date de facturation de la période courante."""
        day = min(billing_day, calendar.monthrange(today.year, today.month)[1])
        if today.day >= day:
            return today.replace(day=day)
        prev = today.replace(day=1) - timedelta(days=1)
        day_prev = min(billing_day, calendar.monthrange(prev.year, prev.month)[1])
        return prev.replace(day=day_prev)

    @api.model
    def _ensure_current_cycle(self, today):
        """Crée le cycle de la période courante s'il n'existe pas encore."""
        billing_day = self.env['subscription.control'].get_billing_day()
        if not 1 <= billing_day <= 31:
            return self.browse()
        billing_date = self._billing_date_for_period(today, billing_day)
        cycle = self.search([('billing_date', '=', billing_date)], limit=1)
        if not cycle:
            cycle = self.create({'billing_date': billing_date})
            _logger.info(
                "Cycle de facturation créé : %s (suspension prévue le %s)",
                cycle.name, cycle.suspension_date)
        return cycle

    def _process_state(self, today):
        """Passe le cycle de 'À venir' à 'Paiement en attente' à la facturation."""
        self.ensure_one()
        if self.state == 'draft' and self.billing_date and today >= self.billing_date:
            self.write({'state': 'awaiting_payment'})

    def _process_reminders(self, today):
        """Envoie les rappels dont l'intervalle correspond à aujourd'hui."""
        self.ensure_one()
        if not self.suspension_date or self.state not in ('draft', 'awaiting_payment'):
            return
        days_until = (self.suspension_date - today).days
        for reminder_day in self.env['subscription.control'].get_reminder_days():
            if days_until != reminder_day:
                continue
            already_sent = self.env['subscription.reminder.log'].search_count([
                ('cycle_id', '=', self.id),
                ('days_before', '=', reminder_day),
                ('type', '=', 'reminder'),
            ])
            if not already_sent:
                self._send_reminder(reminder_day, days_until)

    def _process_suspension(self, today):
        """Suspend le service à la date de suspension si non payé."""
        self.ensure_one()
        if self.state != 'awaiting_payment':
            return
        if not self.suspension_date or today < self.suspension_date:
            return
        self.write({'state': 'suspended'})
        self.env['subscription.control'].block_access_if_expired()
        if self.env['subscription.control'].is_suspension_alert_enabled():
            self._send_suspension_alert()

    # ------------------------------------------------------------------
    # Envois : rappel, alerte de suspension, email, bus
    # ------------------------------------------------------------------

    def _build_alert_context(self, days_until=0):
        """Contexte de placeholders pour les modeles d'alerte.

        ${client_name} : champ du cycle, sinon config client_name, sinon nom BD
        ${invoice_ref}/${invoice_amount}/${invoice_currency} : derniere synchro
        ${suspension_date}, ${days_before}, ${db_name}, ${cycle_name}
        """
        self.ensure_one()
        control = self.env['subscription.control']
        client = self.client_name or control.get_client_name() or self.env.cr.dbname
        amount = ''
        if self.invoice_ref and self.invoice_amount != 0:
            amount = '%.2f' % self.invoice_amount
        return {
            'client_name': client,
            'invoice_ref': self.invoice_ref or '-',
            'invoice_amount': amount or '-',
            'invoice_currency': self.invoice_currency or '',
            'suspension_date': self._fmt_date(self.suspension_date) or '-',
            'days_before': str(days_until),
            'db_name': self.env.cr.dbname,
            'cycle_name': self.name or '-',
        }

    def _send_reminder(self, reminder_day, days_until):
        """Rappel : notification Odoo (message + inbox), email et popup modal."""
        self.ensure_one()
        control = self.env['subscription.control']
        db_name = self.env.cr.dbname
        context = self._build_alert_context(days_until)
        template = self.env['subscription.alert.template'].pick_reminder_template(
            reminder_day)
        if template:
            title = (string.Template(template.subject).safe_substitute(context)
                     if template.subject else
                     _('[%s] Rappel abonnement Odoo (J-%s)', db_name, days_until))
            body = template.render_body(context)
        elif days_until > 0:
            title = _('[%s] Rappel abonnement Odoo (J-%s)', db_name, days_until)
            body = _(
                "Rappel : l'abonnement de l'instance « %(db)s » sera suspendu le "
                "%(date)s (dans %(days)s jours) si le paiement n'est pas enregistré.",
                db=db_name, date=self._fmt_date(self.suspension_date), days=days_until)
        else:
            title = _('[%s] Dernier rappel : suspension de votre abonnement Odoo', db_name)
            body = _(
                "Dernier rappel : l'abonnement de l'instance « %(db)s » est suspendu "
                "aujourd'hui (%(date)s) faute de paiement.",
                db=db_name, date=self._fmt_date(self.suspension_date))
        partner_ids = control.get_recipient_partner_ids()
        if control.is_internal_alerts_enabled():
            self.message_post(
                body=body, subject=title, message_type='comment',
                partner_ids=partner_ids.ids)
        self._send_cycle_email(
            control._get_reminder_email_template(days_until), title)
        if control.is_internal_alerts_enabled():
            control._send_bus_alert(partner_ids, title, body, closable=True)
            self._send_discuss_messages(partner_ids, body)
        self.env['subscription.reminder.log'].create({
            'cycle_id': self.id,
            'days_before': reminder_day,
            'type': 'reminder',
        })
        _logger.info("Rappel J-%s envoyé pour le cycle %s", reminder_day, self.name)

    def _send_suspension_alert(self):
        """Alerte de suspension : notification Odoo, email et popup modal."""
        self.ensure_one()
        control = self.env['subscription.control']
        db_name = self.env.cr.dbname
        context = self._build_alert_context(0)
        template = self.env['subscription.alert.template'].get_suspension_template()
        if template:
            title = (string.Template(template.subject).safe_substitute(context)
                     if template.subject else
                     _('[%s] Abonnement Odoo suspendu', db_name))
            body = template.render_body(context)
        else:
            title = _('[%s] Abonnement Odoo suspendu', db_name)
            body = _(
                "L'abonnement Odoo de l'instance « %(db)s » a été suspendu le "
                "%(date)s faute de paiement dans le délai imparti. Contactez "
                "l'administrateur pour rétablir l'accès au service.",
                db=db_name, date=self._fmt_date(self.suspension_date))
        partner_ids = control.get_recipient_partner_ids()
        if control.is_internal_alerts_enabled():
            self.message_post(
                body=body, subject=title, message_type='comment',
                partner_ids=partner_ids.ids)
        self._send_cycle_email(control.get_suspension_template(), title)
        if control.is_internal_alerts_enabled():
            control._send_bus_alert(partner_ids, title, body, closable=False)
            self._send_discuss_messages(partner_ids, body)
        self.env['subscription.reminder.log'].create({
            'cycle_id': self.id,
            'days_before': 0,
            'type': 'suspension_alert',
        })
        _logger.info("Alerte de suspension envoyée pour le cycle %s", self.name)

    def _send_cycle_email(self, template, title):
        """Envoie l'email du cycle via le modèle configuré (ou en fallback).

        Désactivé lorsque l'option « Alertes par email » est coupée
        (emails gérés par l'instance centrale).
        """
        self.ensure_one()
        control = self.env['subscription.control']
        if not control.is_email_alerts_enabled():
            return False
        partner_ids = control.get_recipient_partner_ids()
        email_to = control.get_recipient_emails()
        if not partner_ids and not email_to:
            return False
        try:
            if template:
                template.send_mail(self.id, email_values={
                    'recipient_ids': [(6, 0, partner_ids.ids)],
                    'email_to': email_to,
                    'subject': title,
                }, force_send=True)
            else:
                self.env['mail.mail'].sudo().create({
                    'subject': title,
                    'body_html': '<p>%s</p>' % title,
                    'email_to': email_to,
                    'recipient_ids': [(6, 0, partner_ids.ids)],
                    'auto_delete': True,
                }).send()
        except Exception as e:
            _logger.error("Erreur envoi email abonnement : %s", e)
            return False
        return True

    def _send_discuss_messages(self, partners, body):
        """Envoie le message dans le Discuss de chaque destinataire
        (discussion directe avec OdooBot, canal privé créé ou réutilisé)."""
        channel_model = self.env['discuss.channel'] if 'discuss.channel' in self.env \
            else self.env['mail.channel']
        for partner in partners:
            if not partner.user_ids:
                continue
            try:
                channel = channel_model.sudo().channel_get(
                    partners_to=[partner.id])
                channel.message_post(
                    body=body, message_type='comment',
                    subtype_xmlid='mail.mt_comment')
            except Exception as e:
                _logger.error(
                    "Erreur envoi message Discuss à %s : %s", partner.name, e)

    def _fmt_date(self, date_val):
        return date_val.strftime('%d/%m/%Y') if date_val else ''

    # ------------------------------------------------------------------
    # Synchronisation des paiements (Odoo de facturation distant)
    # ------------------------------------------------------------------

    @api.model
    def _get_remote_config(self):
        """Parametres de connexion a l'Odoo de facturation externe."""
        param = self.env['ir.config_parameter'].sudo()
        return {
            'enabled': str(param.get_param('subscription.remote_enabled') or ''
                           ).strip().lower() in ('true', '1', 'yes'),
            'url': param.get_param('subscription.remote_odoo_url') or '',
            'db': param.get_param('subscription.remote_odoo_db') or '',
            'user': param.get_param('subscription.remote_odoo_user') or '',
            'api_key': param.get_param('subscription.remote_odoo_api_key') or '',
            'partner_id': int(param.get_param('subscription.remote_partner_id') or 0),
        }

    @api.model
    def _get_xmlrpc_client(self, conf):
        """Fabrique le client XML-RPC (remplaceable dans les tests)."""
        from odoo.addons.subscription_control.models.odoo_xmlrpc_client import \
            OdooXmlrpcClient
        return OdooXmlrpcClient(conf['url'], conf['db'], conf['user'], conf['api_key'])

    def _expected_invoice_ref(self):
        """Reference attendue : SUB-<base>-<AAAA-MM> si non definie."""
        self.ensure_one()
        if self.expected_invoice_ref:
            return self.expected_invoice_ref
        if self.billing_date:
            return 'SUB-%s-%s' % (self.env.cr.dbname,
                                  self.billing_date.strftime('%Y-%m'))
        return False

    @api.model
    def _notify_sync_failure(self, message):
        """Journalise l'echec et notifie les destinataires par email."""
        _logger.error("Synchro paiement echouee : %s", message)
        control = self.env['subscription.control']
        email_to = control.get_recipient_emails()
        partner_ids = control.get_recipient_partner_ids()
        if not email_to and not partner_ids:
            return
        self.env['mail.mail'].sudo().create({
            'subject': '[%s] Erreur de synchronisation des factures' % self.env.cr.dbname,
            'body_html': '<p>%s</p>' % message,
            'email_to': email_to,
            'recipient_ids': [(6, 0, partner_ids.ids)],
            'auto_delete': True,
        }).send()

    @api.model
    def _sync_remote_payments(self):
        """Cron : interroge l'Odoo de facturation et marque payes les cycles regles.

        Matching hybride (B3) : d'abord la reference attendue, puis le
        partenaire configure. En cas d'echec : log + email aux destinataires.
        """
        conf = self._get_remote_config()
        if not conf['enabled']:
            return
        cycles = self.search([('state', 'in', ('awaiting_payment', 'suspended'))])
        if not cycles:
            return
        try:
            client = self._get_xmlrpc_client(conf)
        except Exception as e:
            self._notify_sync_failure(
                "Connexion à l'Odoo de facturation impossible : %s" % e)
            return
        errors = []
        for cycle in cycles:
            try:
                invoice = client.find_invoice(
                    expected_ref=cycle._expected_invoice_ref(),
                    partner_id=conf['partner_id'] or None)
            except Exception as e:
                cycle.write({
                    'remote_sync_error': str(e)[:255],
                    'remote_sync_on': fields.Datetime.now(),
                })
                errors.append("%s : %s" % (cycle.name, e))
                continue
            currency = invoice.get('currency_id')
            cycle.write({
                'invoice_ref': invoice.get('name') or invoice.get('ref') or '',
                'invoice_amount': invoice.get('amount_total') or 0.0,
                'invoice_currency': currency and currency[1] or '',
                'remote_move_state': invoice.get('payment_state') or '',
                'remote_sync_on': fields.Datetime.now(),
                'remote_sync_error': False,
            })
            partner = invoice.get('partner_id')
            if partner and partner[1] and not cycle.client_name:
                cycle.write({'client_name': partner[1]})
            if invoice.get('payment_state') in ('paid', 'in_payment'):
                cycle.message_post(body=_(
                    'Paiement détecté sur l\'Odoo de facturation '
                    '(facture %s, statut %s).',
                    cycle.invoice_ref, invoice.get('payment_state')))
                cycle.action_mark_paid()
                _logger.info("Cycle %s marqué payé via synchro API", cycle.name)
        if errors:
            self._notify_sync_failure(
                "Erreurs de synchronisation des cycles :<br/>%s" % '<br/>'.join(errors))

    # ------------------------------------------------------------------
    # Actions manuelles
    # ------------------------------------------------------------------

    def action_mark_paid(self):
        """Bouton « Paiement reçu » : paye le cycle et restaure l'accès."""
        self.ensure_one()
        if self.state == 'paid':
            raise UserError(_('Ce cycle est déjà payé.'))
        was_suspended = self.state == 'suspended'
        self.write({
            'state': 'paid',
            'paid_on': fields.Date.context_today(self),
        })
        if was_suspended:
            self.env['subscription.control'].restore_access()
            self.message_post(
                body=_('Paiement enregistré. Accès aux applications restauré.'))
        else:
            self.message_post(body=_('Paiement enregistré.'))
        return True

    def action_postpone_suspension(self):
        """Ouvre un wizard pour repousser la date de suspension du cycle."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'subscription.postpone.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_cycle_id': self.id},
        }

    # ------------------------------------------------------------------
    # Consultation (webclient)
    # ------------------------------------------------------------------

    @api.model
    def get_session_alert(self):
        """Statut d'alerte pour l'utilisateur courant (webclient JS)."""
        user = self.env.user
        if user.has_group('base.group_system'):
            return {'show': False}
        sub = self.env['subscription.control']
        if not sub.is_internal_alerts_enabled():
            return {'show': False}
        if sub.check_expiration():
            return {
                'show': True,
                'title': _('Abonnement suspendu'),
                'message': _(
                    "Votre abonnement Odoo a été suspendu faute de paiement. "
                    "Contactez l'administrateur pour rétablir l'accès."),
                'closable': False,
            }
        return {'show': False}

    @api.model
    def _get_active_unpaid_cycle(self):
        """Cycle le plus récent non payé (à venir, en attente ou suspendu)."""
        return self.search([
            ('state', 'in', ('draft', 'awaiting_payment', 'suspended')),
        ], limit=1, order='billing_date desc')


class SubscriptionPostponeWizard(models.TransientModel):
    """Wizard de report de la date de suspension d'un cycle."""
    _name = 'subscription.postpone.wizard'
    _description = 'Report de suspension'

    cycle_id = fields.Many2one(
        'subscription.billing.cycle', string='Cycle', required=True)
    new_suspension_date = fields.Date(
        string='Nouvelle date de suspension', required=True)

    def action_postpone(self):
        self.ensure_one()
        if not self.new_suspension_date:
            raise UserError(_('Veuillez saisir une nouvelle date.'))
        cycle = self.cycle_id
        if cycle.state in ('draft', 'awaiting_payment', 'suspended'):
            was_suspended = cycle.state == 'suspended'
            cycle.reminder_log_ids.unlink()
            cycle.write({
                'suspension_date': self.new_suspension_date,
                'state': 'awaiting_payment' if cycle.state != 'draft' else 'draft',
            })
            if was_suspended:
                self.env['subscription.control'].restore_access()
            cycle.message_post(body=_(
                'Suspension repoussée au %s.',
                cycle._fmt_date(self.new_suspension_date)))
        return {'type': 'ir.actions.act_window_close'}


class SubscriptionReminderLog(models.Model):
    """Journal des rappels/alertes envoyés (déduplication des envois)."""
    _name = 'subscription.reminder.log'
    _description = 'Journal des rappels abonnement'
    _order = 'sent_on desc'

    cycle_id = fields.Many2one(
        'subscription.billing.cycle', string='Cycle',
        required=True, ondelete='cascade', index=True)
    days_before = fields.Integer(string='Jours avant suspension')
    type = fields.Selection([
        ('reminder', 'Rappel'),
        ('suspension_alert', 'Alerte de suspension'),
    ], string='Type', required=True)
    sent_on = fields.Datetime(string='Envoyé le', default=fields.Datetime.now)

    _sql_constraints = [
        ('cycle_reminder_unique', 'UNIQUE(cycle_id, days_before, type)',
         'Ce rappel a déjà été envoyé pour ce cycle.'),
    ]
