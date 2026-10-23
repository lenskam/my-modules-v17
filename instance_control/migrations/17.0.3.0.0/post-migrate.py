# -*- coding: utf-8 -*-
"""Migration 17.0.3.0.0 : notifications et modèles d'email par instance.

Copie la configuration globale (destinataires, modèles d'email, alerte de
suspension) sur chaque instance existante lors du passage à la 17.0.3.0.0 :
la configuration des notifications devient instance par instance. Les
instances dont les champs restent vides continuent de replier sur les
valeurs globales (ir.config_parameter), donc le comportement existant est
préservé même sans cette copie.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    instances = env['instance.management'].search([])
    if not instances:
        return
    param = env['ir.config_parameter'].sudo()

    def _int(val):
        return int(val) if val and str(val).isdigit() else False

    partner_ids = [int(p) for p in str(
        param.get_param('instance_control.recipient_partner_ids') or ''
    ).split(',') if p.strip().isdigit()]
    emails = (param.get_param('instance_control.recipient_emails') or '').strip()
    reminder_tpl = _int(param.get_param('instance_control.reminder_template_id'))
    suspension_tpl = _int(
        param.get_param('instance_control.suspension_template_id'))
    alert_enabled = str(
        param.get_param('instance_control.suspension_alert_enabled') or 'True'
    ).strip().lower() in ('true', '1', 'yes')

    vals = {'suspension_alert_enabled': alert_enabled}
    if partner_ids:
        vals['recipient_partner_ids'] = [(6, 0, partner_ids)]
    if emails:
        vals['recipient_emails'] = emails
    if reminder_tpl:
        vals['reminder_template_id'] = reminder_tpl
    if suspension_tpl:
        vals['suspension_template_id'] = suspension_tpl
    instances.write(vals)
