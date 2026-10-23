# -*- coding: utf-8 -*-
import calendar
import logging
import string
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MONTHS = [
    'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
    'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre',
]


class InstanceBillingCycle(models.Model):
    """Cycle de facturation mensuel d'une instance gérée.

    Un cycle est créé automatiquement à la date de facturation (paramétrable,
    25 par défaut). La date de suspension est calculée à partir de la date de
    facturation + délai de paiement (paramétrable, 15 jours par défaut). Une
    facture client est générée dans l'Odoo central à la date de facturation ;
    des rappels sont envoyés par email aux intervalles configurés, puis
    l'instance distante est suspendue à la date de suspension si le paiement
    n'est pas enregistré. Le paiement de la facture rétablit l'instance.
    """
    _name = 'instance.billing.cycle'
    _description = 'Cycle de facturation instance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'billing_date desc, id desc'

    instance_id = fields.Many2one(
        'instance.management', string='Instance',
        required=True, ondelete='cascade', index=True, tracking=True)
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
    invoice_id = fields.Many2one(
        'account.move', string='Facture', readonly=True)
    invoice_state = fields.Selection(
        related='invoice_id.state', string='État facture', readonly=True)
    invoice_payment_state = fields.Selection(
        related='invoice_id.payment_state', string='Paiement facture',
        readonly=True)
    invoice_partner_id = fields.Many2one(
        related='invoice_id.partner_id', string='Client', readonly=True)
    invoice_currency_id = fields.Many2one(
        related='invoice_id.currency_id', string='Devise facture', readonly=True)
    invoice_amount = fields.Monetary(
        related='invoice_id.amount_total', string='Montant facture',
        currency_field='invoice_currency_id', readonly=True)
    invoice_date = fields.Date(
        related='invoice_id.invoice_date', string='Date facture', readonly=True)
    paid_on = fields.Date(string='Payé le', tracking=True)
    remote_suspended = fields.Boolean(
        string='Suspendue à distance', default=False, copy=False,
        help="La suspension a été appliquée avec succès sur l'instance "
             "distante (réessai quotidien sinon).")
    days_until_suspension = fields.Integer(
        string='Jours avant suspension', compute='_compute_days_until_suspension')
    reminder_log_ids = fields.One2many(
        'instance.reminder.log', 'cycle_id', string='Rappels envoyés')

    _sql_constraints = [
        ('instance_billing_unique', 'UNIQUE(instance_id, billing_date)',
         'Un cycle existe déjà pour cette instance et cette période.'),
    ]

    @api.depends('instance_id.name', 'billing_date')
    def _compute_name(self):
        for rec in self:
            if rec.billing_date:
                rec.name = '%s – %s %s' % (
                    rec.instance_id.name or 'Instance',
                    MONTHS[rec.billing_date.month - 1],
                    rec.billing_date.year)
            else:
                rec.name = '/'

    @api.depends('billing_date', 'instance_id.payment_delay_days')
    def _compute_suspension_date(self):
        for rec in self:
            if rec.billing_date:
                rec.suspension_date = rec.billing_date + timedelta(
                    days=rec.instance_id._get_payment_delay_days())
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

    def _fmt_date(self, date_val):
        return date_val.strftime('%d/%m/%Y') if date_val else ''

    def _expected_invoice_ref(self):
        """Référence attendue : SUB-<base_distante>-<AAAA-MM>."""
        self.ensure_one()
        if self.billing_date:
            return 'SUB-%s-%s' % (
                self.instance_id.database,
                self.billing_date.strftime('%Y-%m'))
        return False

    # ------------------------------------------------------------------
    # Moteur (appelé par le cron quotidien)
    # ------------------------------------------------------------------

    @api.model
    def run_billing_cycles(self):
        """Gère le cycle courant de chaque instance active :
        création, facturation, rappels, suspension.
        Une erreur sur une instance n'interrompt pas les autres."""
        today = fields.Date.context_today(self)
        instances = self.env['instance.management'].search([('active', '=', True)])
        for instance in instances:
            try:
                cycle = self._ensure_current_cycle(today, instance)
                if not cycle:
                    continue
                cycle._process_state(today)
                cycle._process_invoicing()
                cycle._process_reminders(today)
                cycle._process_suspension(today)
                cycle._retry_remote_suspension(today)
            except Exception as e:
                _logger.error(
                    "Erreur cycle pour l'instance %s : %s", instance.name, e)
                instance.write({'last_error': str(e)[:255]})
                self._notify_failure(
                    instance,
                    "[%s] Erreur cycle de facturation (%s)"
                    % (self.env.cr.dbname, instance.name),
                    "Le traitement du cycle de l'instance « %s » a échoué :"
                    "<br/><pre>%s</pre>" % (instance.name, e))

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
    def _ensure_current_cycle(self, today, instance):
        """Crée le cycle de la période courante pour l'instance s'il n'existe pas."""
        billing_day = instance._get_billing_day()
        if not 1 <= billing_day <= 31:
            return self.browse()
        billing_date = self._billing_date_for_period(today, billing_day)
        cycle = self.search([
            ('instance_id', '=', instance.id),
            ('billing_date', '=', billing_date),
        ], limit=1)
        if not cycle:
            cycle = self.create({
                'instance_id': instance.id,
                'billing_date': billing_date,
            })
            _logger.info(
                "Cycle créé : %s (instance %s, suspension prévue le %s)",
                cycle.name, instance.name, cycle.suspension_date)
        return cycle

    def _process_state(self, today):
        """Passe le cycle de 'À venir' à 'Paiement en attente' à la facturation."""
        self.ensure_one()
        if self.state == 'draft' and self.billing_date and today >= self.billing_date:
            self.write({'state': 'awaiting_payment'})

    def _process_invoicing(self):
        """Génère et poste la facture client au centre si absente."""
        self.ensure_one()
        if self.state != 'awaiting_payment' or self.invoice_id:
            return
        invoice = self._create_invoice()
        self.invoice_id = invoice
        self.message_post(body=_(
            "Facture %s générée (%s %s) pour la période %s.",
            invoice.name, '%.2f' % invoice.amount_total,
            invoice.currency_id.name or '', self.name))

    def _create_invoice(self):
        """Crée la facture client (produit d'abonnement, montant mensuel)."""
        self.ensure_one()
        instance = self.instance_id
        if not instance.partner_id:
            raise UserError(_(
                "Aucun client à facturer configuré sur l'instance « %s ».",
                instance.name))
        product = instance._get_product()
        if not product:
            raise UserError(_(
                "Aucun produit d'abonnement configuré pour l'instance « %s » "
                "(ni sur l'instance, ni dans Paramètres → Instances Odoo).",
                instance.name))
        company = self.env.company
        journal = self.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', company.id)], limit=1)
        if not journal:
            raise UserError(_("Aucun journal de vente trouvé."))
        taxes = product.taxes_id.filtered(lambda t: t.company_id == company)
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': instance.partner_id.id,
            'currency_id': (instance.currency_id or company.currency_id).id,
            'invoice_date': fields.Date.context_today(self),
            'ref': self._expected_invoice_ref(),
            'invoice_line_ids': [(0, 0, {
                'product_id': product.id,
                'name': _('Abonnement Odoo – %s (%s)', instance.name, self.name),
                'quantity': 1,
                'price_unit': instance.monthly_amount,
                'tax_ids': [(6, 0, taxes.ids)],
            })],
        })
        move.action_post()
        return move

    def _process_reminders(self, today):
        """Envoie les rappels dont l'intervalle correspond à aujourd'hui."""
        self.ensure_one()
        if not self.suspension_date or self.state not in ('draft', 'awaiting_payment'):
            return
        days_until = (self.suspension_date - today).days
        for reminder_day in self.instance_id._get_reminder_days():
            if days_until != reminder_day:
                continue
            already_sent = self.env['instance.reminder.log'].search_count([
                ('cycle_id', '=', self.id),
                ('days_before', '=', reminder_day),
                ('type', '=', 'reminder'),
            ])
            if not already_sent:
                self._send_reminder(reminder_day, days_until)

    def _process_suspension(self, today):
        """Suspend le cycle et l'instance distante à la date de suspension."""
        self.ensure_one()
        if self.state != 'awaiting_payment':
            return
        if not self.suspension_date or today < self.suspension_date:
            return
        self.write({'state': 'suspended'})
        self._apply_remote_suspension(today)
        if self.instance_id._is_suspension_alert_enabled():
            self._send_suspension_alert()

    def _apply_remote_suspension(self, today):
        """Appelle la suspension distante ; journalise l'échec sans lever."""
        self.ensure_one()
        try:
            self.instance_id._remote_suspend(today)
            self.remote_suspended = True
        except Exception as e:
            self.remote_suspended = False
            self.message_post(body=_(
                "Échec de la suspension distante : %s. "
                "Nouvelle tentative au prochain passage quotidien.", e))
            _logger.error(
                "Suspension distante échouée (%s) : %s", self.instance_id.name, e)

    def _retry_remote_suspension(self, today):
        """Réessaie la suspension distante des cycles suspendus non appliqués."""
        self.ensure_one()
        if self.state == 'suspended' and not self.remote_suspended:
            self._apply_remote_suspension(today)

    # ------------------------------------------------------------------
    # Envois : rappel, alerte de suspension, email (uniquement)
    # ------------------------------------------------------------------

    def _build_alert_context(self, days_until=0):
        """Contexte de placeholders pour les modèles d'alerte.

        ${instance_name}, ${client_name}, ${invoice_ref}, ${invoice_amount},
        ${invoice_currency}, ${suspension_date}, ${days_before}, ${db_name},
        ${cycle_name}.
        """
        self.ensure_one()
        instance = self.instance_id
        client = instance.partner_id.name or instance.name
        invoice = self.invoice_id
        amount = ''
        if invoice and invoice.amount_total:
            amount = '%.2f' % invoice.amount_total
        return {
            'instance_name': instance.name,
            'client_name': client,
            'invoice_ref': (invoice and invoice.name) or '-',
            'invoice_amount': amount or '-',
            'invoice_currency': invoice and invoice.currency_id.name or '',
            'suspension_date': self._fmt_date(self.suspension_date) or '-',
            'days_before': str(days_until),
            'db_name': instance.database,
            'cycle_name': self.name or '-',
        }

    def _send_reminder(self, reminder_day, days_until):
        """Rappel : trace interne (chatter) + email aux destinataires."""
        self.ensure_one()
        context = self._build_alert_context(days_until)
        template = self.env['instance.alert.template'].pick_reminder_template(
            reminder_day)
        if template:
            title = (string.Template(template.subject).safe_substitute(context)
                     if template.subject else
                     _('[%s] Rappel abonnement Odoo (J-%s)',
                       context['db_name'], days_until))
            body = template.render_body(context)
        elif days_until > 0:
            title = _('[%s] Rappel abonnement Odoo (J-%s)',
                      context['db_name'], days_until)
            body = _(
                "Rappel : l'abonnement de l'instance « %(instance)s » sera "
                "suspendu le %(date)s (dans %(days)s jours) si le paiement "
                "n'est pas enregistré.",
                instance=context['instance_name'],
                date=context['suspension_date'], days=days_until)
        else:
            title = _('[%s] Dernier rappel : suspension de votre abonnement Odoo',
                      context['db_name'])
            body = _(
                "Dernier rappel : l'abonnement de l'instance « %(instance)s » "
                "est suspendu aujourd'hui (%(date)s) faute de paiement.",
                instance=context['instance_name'],
                date=context['suspension_date'])
        self.message_post(body=body, subject=title, message_type='comment')
        self._send_cycle_email(
            self.instance_id._get_reminder_email_template(days_until),
            title, body)
        self.env['instance.reminder.log'].create({
            'cycle_id': self.id,
            'days_before': reminder_day,
            'type': 'reminder',
        })
        _logger.info("Rappel J-%s envoyé pour le cycle %s",
                     reminder_day, self.name)

    def _send_suspension_alert(self):
        """Alerte de suspension : trace interne + email aux destinataires."""
        self.ensure_one()
        context = self._build_alert_context(0)
        template = self.env['instance.alert.template'].get_suspension_template()
        if template:
            title = (string.Template(template.subject).safe_substitute(context)
                     if template.subject else
                     _('[%s] Abonnement Odoo suspendu', context['db_name']))
            body = template.render_body(context)
        else:
            title = _('[%s] Abonnement Odoo suspendu', context['db_name'])
            body = _(
                "L'abonnement Odoo de l'instance « %(instance)s » a été "
                "suspendu le %(date)s faute de paiement dans le délai imparti. "
                "Contactez l'administrateur pour rétablir l'accès au service.",
                instance=context['instance_name'],
                date=context['suspension_date'])
        self.message_post(body=body, subject=title, message_type='comment')
        self._send_cycle_email(
            self.instance_id._get_suspension_template(), title, body)
        self.env['instance.reminder.log'].create({
            'cycle_id': self.id,
            'days_before': 0,
            'type': 'suspension_alert',
        })
        _logger.info("Alerte de suspension envoyée pour le cycle %s", self.name)

    def _send_cycle_email(self, template, title, body):
        """Envoie l'email du cycle via le modèle configuré (ou en fallback).

        Les destinataires et le modèle sont propres à l'instance du cycle
        (avec repli sur la configuration globale si non définis).
        """
        self.ensure_one()
        instance = self.instance_id
        partner_ids = instance._get_recipient_partner_ids()
        email_to = instance._get_recipient_emails()
        if not partner_ids and not email_to:
            _logger.warning(
                "Aucun destinataire configuré pour l'instance %s : "
                "email non envoyé (%s)", instance.name, title)
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
                    'body_html': '<p>%s</p>' % body.replace('\n', '<br/>'),
                    'email_to': email_to,
                    'recipient_ids': [(6, 0, partner_ids.ids)],
                    'auto_delete': True,
                }).send()
        except Exception as e:
            _logger.error("Erreur envoi email instance : %s", e)
            return False
        return True

    def _notify_failure(self, instance, subject, message_html):
        """Notifie les destinataires d'une instance d'un échec de traitement."""
        email_to = instance._get_recipient_emails()
        partner_ids = instance._get_recipient_partner_ids()
        if not email_to and not partner_ids:
            return
        self.env['mail.mail'].sudo().create({
            'subject': subject,
            'body_html': message_html,
            'email_to': email_to,
            'recipient_ids': [(6, 0, partner_ids.ids)],
            'auto_delete': True,
        }).send()

    # ------------------------------------------------------------------
    # Synchro des paiements (factures de l'Odoo central)
    # ------------------------------------------------------------------

    @api.model
    def _sync_invoice_payments(self):
        """Cron horaire : marque payés les cycles dont la facture est réglée
        et rétablit l'instance distante."""
        cycles = self.search([
            ('state', 'in', ('awaiting_payment', 'suspended')),
            ('invoice_id.payment_state', 'in', ('paid', 'in_payment')),
        ])
        for cycle in cycles:
            try:
                cycle.action_mark_paid()
                _logger.info("Cycle %s marqué payé via facture", cycle.name)
            except Exception as e:
                _logger.error(
                    "Erreur synchro paiement du cycle %s : %s", cycle.name, e)

    # ------------------------------------------------------------------
    # Actions manuelles
    # ------------------------------------------------------------------

    def action_mark_paid(self):
        """Bouton « Paiement reçu » : paye le cycle et rétablit l'instance."""
        self.ensure_one()
        if self.state == 'paid':
            raise UserError(_('Ce cycle est déjà payé.'))
        was_suspended = self.state == 'suspended'
        self.write({
            'state': 'paid',
            'paid_on': fields.Date.context_today(self),
            'remote_suspended': False,
        })
        if was_suspended:
            self._remote_restore_with_note(
                _('Paiement enregistré : accès distant rétabli.'))
        else:
            self._remote_restore_with_note(
                _('Paiement enregistré : expiration distante mise à jour (%s).',
                  self.instance_id._fmt_date(
                      fields.Date.context_today(self)
                      + timedelta(days=self.env['instance.management']
                                  .get_extend_days()))))

    def _remote_restore_with_note(self, note, expiration_date=None,
                                  raise_on_error=False):
        """Rétablit l'instance distante puis journalise dans le chatter."""
        self.ensure_one()
        restored = self.instance_id._remote_restore(
            expiration_date=expiration_date, raise_on_error=raise_on_error)
        if restored:
            self.message_post(body=note)
        else:
            self.message_post(body=_(
                "Échec du rétablissement distant : voir la fiche instance."))
        return restored

    def action_postpone_suspension(self):
        """Ouvre un wizard pour repousser la date de suspension du cycle."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'instance.postpone.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_cycle_id': self.id},
        }
