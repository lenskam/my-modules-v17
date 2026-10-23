# Session compacte — instance_control + subscription_control (2026-10-15 → 2026-10-23)

> Résumé dense pour restauration de contexte. Détails complets dans
> `docs/dev/sessions/2026-10-15_instance-control-summary.md` et la spécification
> `docs/dev/specs/2026-10-15-instance-control-spec.md`.

## État final des modules (tous deux commités, dépôt git `my-modules` sur branche `main`)

| Module | Version | Tests | Rôle |
|---|---|---|---|
| `instance_control` | 17.0.4.0.1 | 62 (coexistence vérifiée) | **Contrôleur central** installé sur l'Odoo maître : pilote à distance N instances via XML-RPC vers `subscription_control` |
| `subscription_control` | 17.0.6.0.1 | 80 (142 au total avec instance_control) | **Module client** installé sur chaque instance gérée : bloque l'accès local, cycles locaux, alertes |

## instance_control — fonctionnalités livrées

- **Registre des instances** (`instance.management`) : URL/base/login/clé API (masquée),
  client à facturer, montant mensuel, état (active/suspendue/injoignable), chatter.
  Actions : tester connexion, suspendre, rétablir, prolonger (wizard), report, push Helpdesk Odoo 11.
- **Cycles de facturation** (`instance.billing.cycle`) : jour 25 (défaut) + délai 15 j → date
  de suspension ; **facture générée au centre** (produit + montant de l'instance) ; suspension
  distante si impayé (avec réessai quotidien, flag `remote_suspended`) ; **paiement de la
  facture → rétablissement automatique** (cron horaire `_sync_invoice_payments`).
- **Config par instance** (repli : global → défaut module) : destinataires (partenaires + emails),
  modèles d'email, `suspension_alert_enabled`, et overrides facturation
  (`billing_day`, `payment_delay_days`, `reminder_days`, `product_id`).
- **Modèles d'email par intervalle** (`instance.mail.template.line`, par instance) : pour un
  rappel J-N, l'intervalle le plus proche ≤ N est utilisé (ex. interval 2 = J-2 **et** J-1) ;
  repli sur `reminder_template_id` de l'instance → global → défaut module
  (`_get_reminder_email_template(days_until)`).
- **Alertes email uniquement** (pas de bus/popup côté central) ; `instance.alert.template`
  (texte, placeholders `${instance_name}`, `${client_name}`…) ; rappels dédupliqués
  (`instance.reminder.log`, contrainte SQL).
- **Sécurité** : `group_instance_control_manager` **impliqué par `base.group_system`**
  (les admins voient les boutons Créer/Modifier/Archiver sans ajout manuel au groupe).
- **UI** : aucun menu — accès uniquement via **Paramètres → Instances Odoo** (boutons
  Instances gérées / Cycles / Configurer par instance / Modèles d'alerte).
- Crons : `run_billing_cycles` (quotidien), `_sync_invoice_payments` (horaire),
  `_sync_all_status` (quotidien), `cron_push_helpdesk_signals` (quotidien).
- ACL manager/user ; `api_key` masquée en vue (`password="True"`), jamais en code.
- Helpdesk (Odoo 11) : tab par instance conservé tel quel (décision utilisateur) — pousse
  l'état d'abonnement vers le module distant `helpdesk_subscription_control`.

## subscription_control — évolutions livrées (côté client)

- `subscription.mail.template.line` **global** (trigger_days + mail_template_id,
  UNIQUE(trigger_days)) ; même sélection « plus proche ≤ N » via
  `subscription.control._get_reminder_email_template(N)` dans `_send_reminder` ; repli
  sur le modèle de rappel par défaut (paramètre → défaut module).
- Paramètres → Abonnement : bloc « Modèles d'email par défaut (repli) » (champ relabellisé
  « (défaut) » + boutons d'ouverture) + réglages **« Modèles d'email par intervalle »**
  (bouton) et **« Modèles d'alerte (texte) »** (bouton vers l'action, menu retiré).
- Menu Abonnement conservé : Configuration manuelle, Cycles, Modèles d'email par intervalle.
- Fonctionnalités préexistantes de l'utilisateur préservées : modes de blocage
  (`session`/`groups`/`none`), alertes internes Odoo configurables, enforcement mode avec
  fallback legacy `subscription.force_session_expiry`.

## Historique des corrections clés (leçons)

1. **Collision m2m** `res_config_settings` → `res.partner` entre les deux modules : la table
   par défaut d'un m2m dérive des **tables modèle/comodel triées** (fields.py), pas du nom du
   champ → relation explicite `instance_control_settings_res_partner_rel` (v17.0.2.0.1).
2. **« Je ne vois pas les changements » / erreurs bizarres à l'upgrade** : un process Odoo ne
   **recharge jamais le code Python déjà importé** (cache `sys.modules`). TOUJOURS :
   redémarrer le service PUIS `-u module`. Documenté comme piège récurrent.
3. **Boutons Créer/Modifier/Archiver absents** : droits RW portés par le groupe custom que
   les admins n'avaient pas → `base.group_system` implique désormais le groupe manager.
4. **« Odoo Session Expired » toutes les ~2 min (incident 23/10)** :
   - PAS les modules (cron sessions no-op en mode groups ; admins exemptés — prouvé en logs).
   - Causes : sessions stockées sur **/mnt/d (drvfs/9p)** avec erreurs E/S **avalées
     silencieusement** par `odoo/http.py` (`contextlib.suppress`) → sessions mortes en 20-60 s ;
     **double serveur Odoo 17 (Windows + WSL) sur la même base** ; état parasite : abonnement
     de la base centrale expiré (cycle test suspendu + mode groups).
   - Correctifs : `data_dir` → `/home/lenskamdem/.local/share/Odoo17` (ext4, filestore copié
     11 612 fichiers, ancien chemin en commentaire dans odoo.conf) ; base centrale réparée
     via ORM (enforcement_mode=none, expiration 2027-10-23, cycle #72 payé,
     `restore_access()` → groupes utilisateurs 9/15 rétablis).

## Environnement de test (reproductible)

```bash
cd "/mnt/d/DONGMO DYLAN/ODOO/Odoo 17.0/server"
./venv/bin/python odoo-bin -c odoo.conf -d <db_test> -r odoo -w odoo \
  -i subscription_control,instance_control --test-enable \
  --test-tags=/subscription_control,/instance_control --stop-after-init --log-level=info --logfile=
# psql : rôles test_db_v17 (lecture) / odoo (CREATEDB, mot de passe « odoo »)
```
Ne jamais installer/tester dans une base existante sans accord ; toujours `-i` coexistence
(les deux modules ensemble) et tester le chemin de migration (`migrations/17.0.3.0.0/`).

## Git (dépôt `my-modules`, branche `main`, 4 commits)

`bbad9f9` chore (gitignore) · `8ece263` feat(instance_control) ·
`0d2b06f` feat(subscription_control) · `dbf589d` docs(dev).
Non commités (non demandés) : account_general_ledger_hide_initial_balance,
custom_account_report_filter, web_responsive. Pas de remote configuré.

## Actions restantes côté utilisateur (état à la date de compaction)

1. **Redémarrer l'Odoo WSL** (terminal pts/8) après le changement de `data_dir`.
2. **Arrêter l'Odoo 17 côté Windows** (double serveur sur matrix-export-db = interdit).
3. Ctrl+F5 navigateur : liens « Modèles d'alerte (texte) » / « Modèles d'email par
   intervalle » déjà présents en base (vérifiés en SQL).
4. Sur les instances gérées : upgrade `subscription_control` (redémarrage d'abord) et
   désactiver leur cron local `cron_billing_cycle` si le contrôleur central pilote la facturation.
5. Configurer les instances réelles (URL, base, login, clé API) + Test de connexion.
