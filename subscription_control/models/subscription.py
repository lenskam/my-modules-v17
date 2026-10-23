# -*- coding: utf-8 -*-
import json
import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SubscriptionControl(models.TransientModel):
    """Modèle pour gérer les paramètres d'abonnement"""
    _name = 'subscription.control'
    _description = 'Subscription Control'

    # Paramètres système utilisés
    EXPIRATION_DATE_PARAM = 'subscription.expiration_date'
    EXPIRATION_REASON_PARAM = 'subscription.expiration_reason'
    IS_EXPIRED_PARAM = 'subscription.is_expired'
    GROUPS_BACKUP_PARAM = 'subscription.groups_backup'
    GRACE_PERIOD_DAYS = 7  # Période de grâce avant blocage (jours)

    # Paramètres de facturation / suspension (configurables dans Paramètres)
    BILLING_DAY_PARAM = 'subscription.billing_day'
    PAYMENT_DELAY_PARAM = 'subscription.payment_delay_days'
    REMINDER_DAYS_PARAM = 'subscription.reminder_days'
    SUSPENSION_ALERT_PARAM = 'subscription.suspension_alert'
    RECIPIENT_PARTNERS_PARAM = 'subscription.recipient_partner_ids'
    RECIPIENT_EMAILS_PARAM = 'subscription.recipient_emails'
    REMINDER_TEMPLATE_PARAM = 'subscription.reminder_template_id'
    SUSPENSION_TEMPLATE_PARAM = 'subscription.suspension_template_id'
    LOGIN_MSG_TOP_PARAM = 'subscription.login_message_top'
    LOGIN_MSG_BOTTOM_PARAM = 'subscription.login_message_bottom'

    LOGIN_MSG_DEFAULT = "Cette instance est désormais sous contrôle d'abonnement automatique"

    BILLING_DAY_DEFAULT = 25
    PAYMENT_DELAY_DEFAULT = 15
    REMINDER_DAYS_DEFAULT = '10,5,2,1'

    # Champs de l'interface
    expiration_date = fields.Date(string="Date d'expiration")
    is_expired = fields.Boolean(string="Expiré", compute='_compute_expiration_status')
    days_left = fields.Integer(string="Jours restants", compute='_compute_expiration_status')
    status = fields.Selection([
        ('active', 'Actif'),
        ('expiring_soon', 'Expire bientôt'),
        ('expired', 'Expiré')
    ], string="Statut", compute='_compute_expiration_status')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'expiration_date' in fields_list:
            res['expiration_date'] = self.get_expiration_date()
        return res

    @api.depends('expiration_date')
    def _compute_expiration_status(self):
        """Calcule le statut d'expiration pour l'interface"""
        for record in self:
            expiration_date = record.expiration_date
            if not expiration_date:
                record.is_expired = False
                record.days_left = 0
                record.status = 'active'
                continue

            today = fields.Date.context_today(record)
            is_expired = today > expiration_date
            days_left = (expiration_date - today).days

            record.is_expired = is_expired
            record.days_left = days_left

            if is_expired:
                record.status = 'expired'
            elif days_left <= self.GRACE_PERIOD_DAYS:
                record.status = 'expiring_soon'
            else:
                record.status = 'active'

    @api.model
    def get_expiration_date(self):
        """Récupère la date d'expiration depuis les paramètres système"""
        param = self.env['ir.config_parameter'].sudo()
        date_str = param.get_param(self.EXPIRATION_DATE_PARAM)
        if date_str:
            try:
                return fields.Date.to_date(date_str)
            except ValueError:
                return None
        return None

    @api.model
    def set_expiration_date(self, date_obj):
        """Définit la date d'expiration dans les paramètres système"""
        param = self.env['ir.config_parameter'].sudo()
        if date_obj:
            param.set_param(self.EXPIRATION_DATE_PARAM, fields.Date.to_string(date_obj))
            param.set_param(self.IS_EXPIRED_PARAM, 'False')
        else:
            param.set_param(self.EXPIRATION_DATE_PARAM, '')
            param.set_param(self.IS_EXPIRED_PARAM, 'False')
        _logger.info("Date d'expiration définie au %s", date_obj)

    def save_expiration_date(self):
        """Bouton : enregistre la date saisie dans l'interface"""
        self.ensure_one()
        if not self.expiration_date:
            raise UserError(_("Veuillez saisir une date d'expiration."))
        self.set_expiration_date(self.expiration_date)
        return {'type': 'ir.actions.act_window_close'}

    def check_expiration(self):
        """
        Vérifie si la date d'expiration est dépassée ou si un cycle de
        facturation est suspendu (non payé après la date de suspension).
        Retourne True si expiré/suspendu, False sinon.
        """
        expiration_date = self.get_expiration_date()
        today = fields.Date.context_today(self)
        is_expired = bool(expiration_date and today > expiration_date)
        if not is_expired:
            is_expired = self._is_cycle_suspended()

        # Met à jour le paramètre is_expired
        param = self.env['ir.config_parameter'].sudo()
        param.set_param(self.IS_EXPIRED_PARAM, str(is_expired))

        if is_expired:
            _logger.warning("Instance ODOO EXPIRÉE/SUSPENDUE (échéance : %s)", expiration_date)
        else:
            days_left = (expiration_date - today).days if expiration_date else None
            if days_left is not None and days_left <= self.GRACE_PERIOD_DAYS:
                _logger.warning("Instance ODOO expire dans %s jours", days_left)

        return is_expired

    def _is_cycle_suspended(self):
        """True si au moins un cycle de facturation est en état « Suspendu »."""
        return bool(self.env['subscription.billing.cycle'].search_count(
            [('state', '=', 'suspended')]))

    @api.model
    def block_access_if_expired(self):
        """
        Bloque l'accès aux applications si la date d'expiration est dépassée.
        Appelé par le cron job ou à chaque connexion.

        La révocation des groupes n'est appliquée que si le mode de blocage
        configuré est « groups » (les modes « session » et « none » ne
        révoquent pas les groupes).
        """
        if self.check_expiration():
            if self.get_enforcement_mode() == 'groups':
                self._revoke_app_access()
            return True
        return False

    def _revoke_app_access(self):
        """
        Sauvegarde puis retire les droits d'accès aux applications pour tous
        les utilisateurs non-administrateurs. Les groupes d'origine sont
        conservés pour pouvoir être restaurés via restore_access().
        """
        users = self.env['res.users'].search([
            ('share', '=', False),
            ('active', '=', True)
        ])
        admin_group = self.env.ref('base.group_system')
        base_group = self.env.ref('base.group_user')

        backup = {}
        for user in users:
            if admin_group.id in user.groups_id.ids:
                continue
            backup[str(user.id)] = user.groups_id.ids

        # Conserve la sauvegarde existante si un blocage a déjà eu lieu
        param = self.env['ir.config_parameter'].sudo()
        existing = param.get_param(self.GROUPS_BACKUP_PARAM)
        if existing:
            try:
                existing_backup = json.loads(existing)
                for uid, group_ids in existing_backup.items():
                    backup.setdefault(uid, group_ids)
            except (ValueError, TypeError):
                pass

        param.set_param(self.GROUPS_BACKUP_PARAM, json.dumps(backup))

        for user in users:
            if admin_group.id in user.groups_id.ids:
                continue
            user.write({'groups_id': [(6, 0, [base_group.id])]})

        _logger.info("Accès aux applications bloqué pour %s utilisateurs", len(backup))

    @api.model
    def restore_access(self):
        """Restaure l'accès aux applications après réinitialisation"""
        param = self.env['ir.config_parameter'].sudo()
        param.set_param(self.IS_EXPIRED_PARAM, 'False')

        backup_str = param.get_param(self.GROUPS_BACKUP_PARAM)
        if backup_str:
            try:
                backup = json.loads(backup_str)
            except (ValueError, TypeError):
                backup = {}
            for uid, group_ids in backup.items():
                user = self.env['res.users'].browse(int(uid))
                if user.exists():
                    user.write({'groups_id': [(6, 0, group_ids)]})
            param.set_param(self.GROUPS_BACKUP_PARAM, '')

        _logger.info("Accès aux applications restauré")

    # ------------------------------------------------------------------
    # Paramètres de facturation (configurables dans Paramètres Odoo)
    # ------------------------------------------------------------------

    @api.model
    def get_billing_day(self):
        """Jour du mois de facturation (défaut : 25)."""
        val = self.env['ir.config_parameter'].sudo().get_param(self.BILLING_DAY_PARAM)
        if not val:
            return self.BILLING_DAY_DEFAULT
        try:
            day = int(val)
        except (ValueError, TypeError):
            return self.BILLING_DAY_DEFAULT
        return day if 1 <= day <= 31 else self.BILLING_DAY_DEFAULT

    @api.model
    def get_payment_delay_days(self):
        """Délai de paiement en jours après la facturation (défaut : 15)."""
        val = self.env['ir.config_parameter'].sudo().get_param(self.PAYMENT_DELAY_PARAM)
        if not val:
            return self.PAYMENT_DELAY_DEFAULT
        try:
            delay = int(val)
        except (ValueError, TypeError):
            return self.PAYMENT_DELAY_DEFAULT
        return delay if delay >= 0 else self.PAYMENT_DELAY_DEFAULT

    @api.model
    def get_reminder_days(self):
        """Intervalles de rappel (jours avant suspension), triés du plus grand."""
        val = self.env['ir.config_parameter'].sudo().get_param(self.REMINDER_DAYS_PARAM)
        if not val:
            val = self.REMINDER_DAYS_DEFAULT
        days = set()
        for part in str(val).split(','):
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
    def is_suspension_alert_enabled(self):
        """Alerte envoyée le jour de la suspension (défaut : True)."""
        val = self.env['ir.config_parameter'].sudo().get_param(self.SUSPENSION_ALERT_PARAM)
        if val in (None, '', False):
            return True
        return str(val).strip().lower() in ('true', '1', 'yes')

    @api.model
    def get_client_name(self):
        """Nom du client affiché dans les alertes (config, vide = nom BD)."""
        val = self.env['ir.config_parameter'].sudo().get_param(
            'subscription.client_name')
        return str(val).strip() if val else ''

    # ------------------------------------------------------------------
    # Configurabilité : mode de blocage + toggles de fonctionnalités
    # ------------------------------------------------------------------

    ENFORCEMENT_PARAM = 'subscription.enforcement_mode'
    LEGACY_SESSION_PARAM = 'subscription.force_session_expiry'
    ENGINE_PARAM = 'subscription.billing_engine_enabled'
    EMAIL_ALERTS_PARAM = 'subscription.email_alerts_enabled'
    INTERNAL_ALERTS_PARAM = 'subscription.internal_alerts_enabled'

    @api.model
    def get_enforcement_mode(self):
        """Mode de blocage d'accès : 'session' (défaut), 'groups' ou 'none'.

        Fallback de migration pour les instances existantes : si le nouveau
        paramètre n'est pas encore défini, on déduit le mode de l'ancien
        booléen « Forcer l'expiration des sessions » (True -> session,
        False -> groups), afin de préserver le comportement en vigueur.
        Pour une installation neuve (aucun des deux paramètres), le défaut
        est 'session'.
        """
        param = self.env['ir.config_parameter'].sudo()
        mode = param.get_param(self.ENFORCEMENT_PARAM)
        if mode in ('session', 'groups', 'none'):
            return mode
        legacy = param.get_param(self.LEGACY_SESSION_PARAM)
        if legacy:
            return 'session' if str(legacy).strip().lower() in (
                'true', '1', 'yes') else 'groups'
        return 'session'

    @api.model
    def is_billing_engine_enabled(self):
        """Moteur de facturation local actif (défaut : True).

        Désactivé lorsque l'instance centrale (instance_control) gère
        cycles, rappels et suspensions. Les cycles restent affichés.
        """
        param = self.env['ir.config_parameter'].sudo()
        val = param.get_param(self.ENGINE_PARAM)
        if val in (None, '', False):
            return True
        return str(val).strip().lower() in ('true', '1', 'yes')

    @api.model
    def is_email_alerts_enabled(self):
        """Envoi d'emails (rappels/alertes) actif (défaut : True)."""
        param = self.env['ir.config_parameter'].sudo()
        val = param.get_param(self.EMAIL_ALERTS_PARAM)
        if val in (None, '', False):
            return True
        return str(val).strip().lower() in ('true', '1', 'yes')

    @api.model
    def is_internal_alerts_enabled(self):
        """Alertes natives Odoo (chatter, Discuss, modal) actives (défaut True)."""
        param = self.env['ir.config_parameter'].sudo()
        val = param.get_param(self.INTERNAL_ALERTS_PARAM)
        if val in (None, '', False):
            return True
        return str(val).strip().lower() in ('true', '1', 'yes')

    @api.model
    def get_recipient_partner_ids(self):
        """Contacts destinataires des rappels/alertes."""
        param = self.env['ir.config_parameter'].sudo()
        val = param.get_param(self.RECIPIENT_PARTNERS_PARAM) or ''
        partner_ids = []
        for part in str(val).split(','):
            part = part.strip()
            if part.isdigit():
                partner_ids.append(int(part))
        return self.env['res.partner'].browse(partner_ids).exists()

    @api.model
    def get_recipient_emails(self):
        """Adresses email supplémentaires (séparées par des virgules)."""
        val = self.env['ir.config_parameter'].sudo().get_param(self.RECIPIENT_EMAILS_PARAM) or ''
        return ','.join(part.strip() for part in str(val).split(',') if part.strip())

    @api.model
    def get_reminder_template(self):
        """Modèle d'email de rappel (configuré ou défaut du module)."""
        param = self.env['ir.config_parameter'].sudo()
        template_id = param.get_param(self.REMINDER_TEMPLATE_PARAM)
        if template_id:
            template = self.env['mail.template'].browse(int(template_id)).exists()
            if template:
                return template
        return self.env.ref(
            'subscription_control.subscription_mail_template_reminder',
            raise_if_not_found=False)

    @api.model
    def _get_reminder_email_template(self, days_until):
        """Modèle d'email de rappel effectif pour le rappel J-N.

        D'abord les modèles par intervalle : celui dont l'intervalle est
        le plus proche inférieur ou égal à N (ex. interval 2 pour J-2 et
        J-1) ; à défaut, le plus petit intervalle défini. Sans intervalles
        configurés, repli sur le modèle de rappel par défaut (paramètre,
        puis défaut du module).
        """
        line_model = self.env['subscription.mail.template.line']
        line = line_model.search(
            [('trigger_days', '<=', days_until)],
            order='trigger_days desc', limit=1)
        if not line:
            line = line_model.search([], order='trigger_days asc', limit=1)
        if line and line.mail_template_id:
            return line.mail_template_id
        return self.get_reminder_template()

    @api.model
    def get_suspension_template(self):
        """Modèle d'email de suspension (configuré ou défaut du module)."""
        param = self.env['ir.config_parameter'].sudo()
        template_id = param.get_param(self.SUSPENSION_TEMPLATE_PARAM)
        if template_id:
            template = self.env['mail.template'].browse(int(template_id)).exists()
            if template:
                return template
        return self.env.ref(
            'subscription_control.subscription_mail_template_suspension',
            raise_if_not_found=False)

    # ------------------------------------------------------------------
    # Message personnalisé de la page de connexion
    # ------------------------------------------------------------------

    @api.model
    def get_login_message_top(self):
        """Message au-dessus du formulaire de connexion (défaut si non
        configuré, vide = masqué)."""
        param = self.env['ir.config_parameter'].sudo().search(
            [('key', '=', self.LOGIN_MSG_TOP_PARAM)], limit=1)
        if not param:
            return self.LOGIN_MSG_DEFAULT
        return (param.value or '').strip()

    @api.model
    def get_login_message_bottom(self):
        """Message sous le formulaire de connexion (vide = masqué)."""
        val = self.env['ir.config_parameter'].sudo().get_param(
            self.LOGIN_MSG_BOTTOM_PARAM)
        return str(val).strip() if val else ''

    # ------------------------------------------------------------------
    # Alertes modales (bus Odoo)
    # ------------------------------------------------------------------

    def _send_bus_alert(self, partner_ids, title, message, closable=True):
        """Envoie une alerte modale via le bus aux destinataires connectés."""
        if not partner_ids:
            return
        try:
            for partner in partner_ids:
                self.env['bus.bus'].sudo()._sendone(
                    partner,
                    'subscription_control.alert',
                    {'title': title, 'message': message, 'closable': closable},
                )
        except Exception as e:
            _logger.error("Erreur envoi alerte bus : %s", e)

    @api.model
    def get_suspension_login_message(self):
        """Message d'alerte affiché à la connexion d'un utilisateur suspendu."""
        return _("Votre abonnement a expiré. Contactez l'administrateur.")

    @api.model
    def get_session_alert(self):
        """Statut d'alerte pour la session courante : modal bloquante au
        chargement du webclient si l'utilisateur connecté est suspendu."""
        if not self.is_suspension_alert_enabled():
            return {'show': False}
        if not self.is_internal_alerts_enabled():
            return {'show': False}
        if not self.check_expiration():
            return {'show': False}
        backup = self.env['ir.config_parameter'].sudo().get_param(
            self.GROUPS_BACKUP_PARAM)
        try:
            suspended_ids = json.loads(backup or '{}')
        except (ValueError, TypeError):
            return {'show': False}
        if str(self.env.uid) not in suspended_ids:
            return {'show': False}
        return {
            'show': True,
            'closable': False,
            'title': _('Abonnement suspendu'),
            'message': self.get_suspension_login_message(),
        }

    @api.model
    def get_expiration_status(self):
        """Retourne le statut complet de l'abonnement"""
        expiration_date = self.get_expiration_date()
        is_expired = self.check_expiration()

        status = {
            'expiration_date': expiration_date,
            'is_expired': is_expired,
        }

        if expiration_date:
            today = fields.Date.context_today(self)
            days_left = (expiration_date - today).days
            status['days_left'] = days_left
            status['status'] = 'expired' if is_expired else 'active'
            if days_left <= self.GRACE_PERIOD_DAYS and not is_expired:
                status['status'] = 'expiring_soon'

        return status

    def extend_subscription(self, days=30):
        """Prolonge l'abonnement de X jours et repousse la suspension du
        cycle de facturation courant si nécessaire."""
        current_date = self.get_expiration_date()
        today = fields.Date.context_today(self)
        if current_date:
            new_date = max(current_date, today) + timedelta(days=days)
        else:
            new_date = today + timedelta(days=days)
        self.set_expiration_date(new_date)
        self.restore_access()

        cycle = self.env['subscription.billing.cycle']._get_active_unpaid_cycle()
        if cycle and cycle.suspension_date and cycle.suspension_date < new_date:
            cycle.reminder_log_ids.unlink()
            cycle.write({
                'suspension_date': new_date,
                'state': 'awaiting_payment',
            })
            cycle.message_post(body=_(
                "Abonnement prolongé : suspension repoussée au %s.",
                cycle._fmt_date(new_date)))

        _logger.info("Abonnement prolongé de %s jours. Nouvelle date : %s", days, new_date)
        return new_date

    @api.model
    def check_license_file(self):
        """
        Vérifie l'existence et le contenu d'un fichier de licence
        sur le système de fichiers.
        """
        import os
        license_file_path = self.env['ir.config_parameter'].sudo().get_param(
            'subscription.license_path', '/etc/odoo/license.key')

        if not os.path.exists(license_file_path):
            return False

        try:
            with open(license_file_path, 'r') as f:
                content = f.read().strip()

            # Format attendu : expiration_date:2026-12-31
            if content.startswith('expiration_date:'):
                date_str = content.split(':')[1]
                expiration_date = fields.Date.to_date(date_str)
                self.set_expiration_date(expiration_date)
                self.restore_access()
                return True
        except Exception as e:
            _logger.error("Erreur lecture fichier licence : %s", e)

        return False
