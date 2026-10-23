# Session — 2026-10-15 : module `instance_control` (contrôleur central)

## Accompli
1. **Brainstorming + spec** (`docs/dev/specs/2026-10-15-instance-control-spec.md`) :
   design approuvé en 3 parties, puis **modifié par l'utilisateur** → alertes **email
   uniquement** (pas de popup bus, pas de Discuss côté central).
2. **Implémentation complète** du module `instance_control` (Odoo 17, depends:
   base/mail/web/account) :
   - `instance.management` : registre des instances (XML-RPC, client, montant), actions
     test connexion / suspendre / rétablir / prolonger / sync statut, crons de miroir.
   - `instance.billing.cycle` : cycles mensuels (jour 25 défaut, délai 15 j → date de
     suspension), génération de factures clients au centre, rappels dédupliqués,
     suspension distante avec réessai, synchro paiement facture → rétablissement distant.
   - `instance.reminder.log` (dédup SQL), `instance.alert.template` (placeholders),
     `OdooXmlrpcClient` autonome, wizards prolongation + report, `res.config.settings`.
   - Sécurité : groupe `group_instance_control_manager` + ACL (lecture interne).
   - Data : 3 crons, 2 `mail.template`, 4 templates d'alerte seed.
   - Vues : instances, cycles, templates, Paramètres → Instances Odoo, menus.
3. **Vérification réelle** : installation + tests sur une base PostgreSQL dédiée
   (`instance_control_test`, créée avec les creds du serveur) via le venv du serveur.
   - Corrections faites en chemin : related `Monetary` (pas Float), retrait
     `password=True` du champ (attribut vue), champs related pour la vue facture.
   - Corrections de tests : `assertRaises` Odoo 17 annule le savepoint (l'écriture
     d'état dans le bloc est revertue), clés `cls.partner_a` d'AccountTestInvoicingCommon,
     groupe manager accordé à l'utilisateur de test, patchers déballés, destinataires
     configurés, `action_mark_paid` synchonise toujours l'expiration distante.
4. **Résultat final : 47 tests — 0 failed, 0 error** (log : artefact).
5. Nettoyage : base de test supprimée ; commande de recréation documentée dans
   MASTER_IMPLEMENTATION.md.

## Reste à faire (prochaines sessions)
- Désactiver le cron client `subscription_control.cron_billing_cycle` sur les instances
  gérées (le contrôleur devient la source de vérité) — procédure à documenter/déployer.
- Configurer : produit d'abonnement + destinataires dans Paramètres → Instances Odoo.
- Saisir les instances réelles (URL, base, login, clé API) et tester la connexion.
- Éventuel widget kanban/dashboard si besoin futur (hors périmètre actuel).

## Correctif 2026-10-22 (v17.0.2.0.1) — collision m2m res.config.settings
- **Symptôme** : `TypeError: Many2many fields ...instance_recipient_partner_ids and
  ...subscription_recipient_partner_ids use the same table and columns` à
  l'installation sur une base ayant déjà `subscription_control`.
- **Cause** : Odoo déduit la table de relation m2m par défaut des tables
  modèle/comodel triées (fields.py : `'%s_%s_rel' % tuple(sorted(tables))`), pas du
  nom du champ → les deux champs (même modèle, même comodel) calculaient la même
  table `res_config_settings_res_partner_rel` + mêmes colonnes.
- **Correctif** : relation explicite `instance_control_settings_res_partner_rel`
  (config_id, partner_id) sur `instance_recipient_partner_ids`.
- **Vérifié** : installation combinée `subscription_control` + `instance_control` sur
  base neuve avec la suite de tests → 47 tests, 0 failed / 0 error ; deux tables de
  relation distinctes en base.
- Artefact : docs/dev/artifacts/2026-10-22_instance-control-coexistence-fix.log
- Leçon : tester l'installation en coexistence avec les modules existants, pas seul.

## Mise à jour 2026-10-22 (v17.0.3.0.0) — configuration par instance
- **Destinataires et modèles d'email par instance** : `recipient_partner_ids`,
  `recipient_emails`, `reminder_template_id`, `suspension_template_id`,
  `suspension_alert_enabled` déplacés vers `instance.management` (onglet
  « Alertes & Notifications »). Chaque instance reçoit ses propres emails.
- **Facturation surchargable par instance** : `billing_day`,
  `payment_delay_days`, `reminder_days`, `product_id` (onglet « Facturation »).
  Vide/0 = repli sur la valeur globale (Paramètres → Instances Odoo).
- Priorité des getters : **Instance → Global (ir.config_parameter) → Défaut module**.
- `res.config.settings` ne garde que les valeurs par défaut globales ; migration
  17.0.3.0.0 copiant l'ancienne config globale sur les instances existantes
  (vérifiée sur un upgrade réel simulé 17.0.2.0.1 → 17.0.3.0.0).
- CRUD instances : création/modification/suppression déjà opérationnels (vues
  tree/form/search + ACL manager, suppression en cascade des cycles).
- **57 tests verts (0 failed / 0 error)** en coexistence avec subscription_control
  (10 nouveaux tests : overrides par instance, destinataires, templates).
- Artefact : docs/dev/artifacts/2026-10-22_instance-control-per-instance-tests.log

## Questions ouvertes
- Aucune bloquante.

## Piège récurrent documenté — code Python vs process en cours
Rappel important pour tout futur déploiement : un process Odoo ne recharge JAMAIS le
code Python d'un module déjà importé (cache sys.modules). Installer/upgrader depuis
l'UI d'un serveur qui tourne avec du code ancien provoque des erreurs du type
« Field X does not exist in model Y » ou « same table and columns », alors que le
disque est correct. TOUJOURS : 1) redémarrer le service, 2) puis upgrade
(-u instance_control ou bouton UI). Vérifié à deux reprises (install v17.0.1, upgrade
v17.0.3 — erreur product_id sur tree view, corrigée par redémarrage).

## Correctif 2026-10-23 (v17.0.3.0.1) — boutons Créer/Modifier/Archiver absents
- **Symptôme** : la liste des instances s'ouvre depuis Paramètres mais sans bouton
  « Nouveau » ni modification/archivage possibles.
- **Cause** : les droits RW n'étaient portés que par le groupe custom
  group_instance_control_manager, auquel les admins (base.group_system)
  n'appartiennent pas automatiquement ; le bouton du bloc Paramètres ouvrait
  l'action sans filtrage menu → lecture seule (ACL base.group_user).
- **Correctif** : base.group_system implique désormais
  group_instance_control_manager (security.xml) → tout admin obtient
  automatiquement créer/modifier/archiver ; propagation vérifiée pour un admin
  existant avant upgrade ; menu « Instances Odoo » visible pour les admins.
- **Vérifié** : admin group_system seul → CREATE/WRITE/UNLINK True, création +
  modification + archivage réussis en shell ; 57 tests verts en coexistence.

## Mise à jour 2026-10-23 (v17.0.4.0.0) — modèles d'email par intervalle
- Nouveau modèle instance.mail.template.line (par instance) : trigger_days +
  mail_template_id. Pour un rappel J-N, le modèle dont l'intervalle est le plus proche
  inférieur ou égal à N est utilisé (ex. interval 2 = J-2 et J-1) — même design que les
  modèles d'alerte texte.
- Chaîne complète : lignes par intervalle → reminder_template_id de l'instance (gardé
  comme repli, validé par l'utilisateur) → global → défaut du module.
- Onglet Helpdesk : laissé tel quel (décision utilisateur).
- UI : liste éditable dans l'onglet « Alertes & Notifications » de la fiche instance.
- ACL ligne user/manager ; contrainte UNIQUE(instance_id, trigger_days).
- 62 tests verts en coexistence (5 nouveaux). Artefact :
  docs/dev/artifacts/2026-10-23_instance-control-interval-emails-tests.log

## Mise à jour 2026-10-23 — subscription_control v17.0.6.0.0 (même design)
- Application du même mécanisme au module client subscription_control :
  nouveau modèle global subscription.mail.template.line (trigger_days +
  mail_template_id, UNIQUE(trigger_days)), sélection « plus proche ≤ N » via
  subscription.control._get_reminder_email_template(days_until) utilisée par
  _send_reminder ; repli sur le modèle de rappel par défaut (paramètre, puis
  défaut du module) — chaîne identique à instance_control.
- Page Paramètres → Abonnement mise à jour : bloc « Modèles d'email par défaut
  (repli) » + nouveau réglage « Modèles d'email par intervalle » avec bouton
  vers l'action ; menu « Modèles d'email par intervalle » (séquence 40).
- Baseline pré-modification : 75 tests verts ; après : 142 tests verts en
  coexistence (75+5 subscription, 62 instance). Artefact :
  docs/dev/artifacts/2026-10-23_subscription-control-interval-emails-tests.log

## Mise à jour 2026-10-23 — allègement des menus (instance 17.0.4.0.1, sub 17.0.6.0.1)
- instance_control : menu « Instances Odoo » et tous ses sous-menus supprimés ;
  accès unique via Paramètres → Instances Odoo (boutons Instances gérées,
  Cycles de facturation — ajouté — , Configurer par instance, Modèles d'alerte).
- subscription_control : menu « Modèles d'alerte » supprimé de Abonnement ;
  accès via Paramètres → Abonnement → Alertes et destinataires → nouveau réglage
  « Modèles d'alerte (texte) » avec bouton. (Menu « Modèles d'email par
  intervalle » conservé sous Abonnement.)
- Les actions restent toutes définies ; suppression effective à l'upgrade
  (données non-noupdate supprimées automatiquement).
- 142 tests verts en coexistence. Artefact :
  docs/dev/artifacts/2026-10-23_menus-cleanup-tests.log

## Incident 2026-10-23 — « Odoo Session Expired » toutes les ~2 min (RESOLU côté config)
- **Symptôme** : sessions mortes 20-60 s après login (log : SessionExpiredException, toast
  « Odoo Session Expired »), y compris admin. Début 10h28. PAS lié aux modules (cron
  sessions no-op en mode groups, admins exemptés — vérifié dans les logs).
- **Causes trouvées** :
  1. Magasin de sessions sur /mnt/d (drvfs/9p WSL) : odoo/http.py avale les erreurs
     d'E/S de sessions (contextlib.suppress) -> écritures perdues = expiration immédiate.
  2. Un Odoo 17 tournait AUSSI côté Windows (confirmé par l'utilisateur) sur la même
     base/le même dossier de sessions -> double serveur.
  3. État parasite : abonnement de la base centrale expiré (2026-10-10, mode groups,
     cycle #72 Septembre 2026 suspendu) -> utilisateurs 9/15 révoqués quotidiennement.
- **Correctifs appliqués** :
  1. odoo.conf : data_dir = /home/lenskamdem/.local/share/Odoo17 (ext4 natif),
     filestore complet copie (11 612 fichiers, 341+ Mo), ancien chemin en commentaire.
  2. Base centrale réparée via ORM : enforcement_mode=none, expiration=2027-10-23,
     cycle 72 marqué payé, restore_access (groupes 9/15 rétablis, backup vidé),
     check_expiration() = False.
- **Reste à faire (utilisateur)** : redémarrer l'Odoo WSL (Ctrl+C dans le terminal
  pts/8 puis relancer), ARRÊTER l'Odoo 17 Windows (double serveur sur la même base =
  comportement indéfini), Ctrl+F5 navigateur pour les liens Paramètres (déjà en base).
