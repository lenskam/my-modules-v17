# Spécification — Module `instance_control` (Contrôleur Central d'Instances Odoo)

- **Date** : 2026-10-15
- **Statut** : Validé (design approuvé par l'utilisateur)
- **Auteur** : ITS (généré avec l'assistance IA)
- **Approche choisie** : A — Module autonome, communique avec les instances via les méthodes existantes de `subscription_control`

---

## 1. Objectif

Module installé sur **un seul Odoo central** (le contrôleur) permettant de gérer à distance
**plusieurs instances Odoo clientes** (les gérées) :

- Contrôler la **facturation, le paiement, la suspension et la prolongation par API**
  des instances Odoo gérées.
- Cycles de facturation mensuels : à la date de facturation (25 par défaut), le délai de
  paiement (15 jours par défaut) sert à calculer la date de suspension du service.
- Gestion des instances gérées : suspension, prolongation, rétablissement, test de connexion.
- Rappels et alertes envoyés à intervalles définis par email (uniquement), à des destinataires configurables.
- Configuration des templates des mails à envoyer (modèles d'alerte personnalisables +
  `mail.template` par défaut).

Le module client `subscription_control` (déjà déployé sur chaque instance gérée) **n'est pas
modifié** : le contrôleur appelle ses méthodes exposées via XML-RPC
(`set_expiration_date`, `block_access_if_expired`, `restore_access`, `extend_subscription`,
`get_expiration_date`).

## 2. Exigences

### Fonctionnelles

- FR-1 : Registre des instances gérées (URL, base, login, clé API, client, montant mensuel).
- FR-2 : Test de connexion XML-RPC vers chaque instance.
- FR-3 : Cycle de facturation mensuel par instance : création automatique à la date de
  facturation, génération d'une facture client dans l'Odoo central, suspension distante si
  impayé à la date de suspension.
- FR-4 : Factures générées dans l'Odoo central (module `account`) ; paiement de la facture →
  cycle payé → rétablissement distant automatique.
- FR-5 : Rappels aux intervalles configurés (défaut J-10, J-5, J-2, J-1) : notification par email.
- FR-6 : Alerte de suspension le jour de la suspension (désactivable).
- FR-7 : Actions manuelles : suspendre maintenant, rétablir, prolonger (wizard jours),
  reporter la suspension, marquer payé.
- FR-8 : Templates d'alerte personnalisables avec placeholders `${...}`.
- FR-9 : Configuration globale dans Paramètres (jour de facturation, délai de paiement,
  intervalles de rappel, produit d'abonnement, destinataires, templates emails).
- FR-10 : Synchronisation quotidienne du statut distant (date d'expiration connue).

### Non fonctionnelles

- NF-1 : Aucune modification requise sur les instances gérées.
- NF-2 : Une instance injoignable ne bloque pas le traitement des autres (isolation d'erreurs).
- NF-3 : Déduplication stricte des rappels (contrainte SQL + log).
- NF-4 : Clé API masquée dans l'interface (`password="True"`).
- NF-5 : Style et conventions identiques au module `subscription_control` (nommage, i18n FR,
  logging, structure de tests).

## 3. Contraintes

- Odoo 17.0, dépendances : `base`, `mail`, `web`, `account`.
- Communication : XML-RPC `/xmlrpc/2/common` + `/xmlrpc/2/object` (bibliothèque standard
  `xmlrpc.client`), timeout 10 s, compatible Odoo 11 → 17+.
- Les instances gérées doivent avoir `subscription_control` ≥ 17.0.4.0.0 installé.
- Sur les instances gérées, le cron local `cron_billing_cycle` de `subscription_control`
  doit être désactivé (le contrôleur est la source de vérité) — procédure documentée.
- Le nom du module est `instance_control`.

## 4. Architecture

```
┌─────────────────────────────┐         XML-RPC          ┌──────────────────────────┐
│  Odoo CENTRAL               │  set_expiration_date     │  Instance gérée n°1      │
│  module instance_control    │  block_access_if_expired │  module subscription_    │
│                             │  restore_access          │  control (bloque l'accès │
│  • instance.management      │  extend_subscription     │  local, popups, sessions)│
│  • instance.billing.cycle   │  get_expiration_date     └──────────────────────────┘
│  • invoices (account)       │         ┌──────────────────────────┐
│  • crons                    ├────────►│  Instance gérée n°2 ...  │
└─────────────────────────────┘         └──────────────────────────┘
```

### Modèles

#### 4.1 `instance.management` — Registre des instances gérées

| Champ | Type | Description |
|---|---|---|
| `name` | Char (required) | Nom affiché, ex. « Client A – Production » |
| `url` | Char (required) | URL de base, ex. `https://client1.example.com` |
| `database` | Char (required) | Nom de la base distante |
| `login` | Char (required) | Utilisateur XML-RPC distant |
| `api_key` | Char (required, password) | Clé API distante (masquée) |
| `partner_id` | Many2one `res.partner` | Client à facturer |
| `monthly_amount` | Float | Montant mensuel de l'abonnement |
| `currency_id` | Many2one `res.currency` (related partner) | Devise de facturation |
| `state` | Selection : `active`, `suspended`, `unreachable` | Dernier état connu |
| `expiration_date` | Date (readonly) | Dernière date d'expiration lue à distance |
| `last_check` | Datetime (readonly) | Dernier contact API réussi |
| `last_error` | Char (readonly) | Dernière erreur API |
| `active` | Boolean (default True) | Archive si non géré |
| `_inherit` | `mail.thread`, `mail.activity.mixin` | Chatter |

Méthodes :

- `_get_client()` → fabrique `OdooXmlrpcClient` (substituable dans les tests).
- `action_test_connection()` : authentifie et lit `get_expiration_date()` distant ;
  met à jour `expiration_date`, `last_check`, `last_error`, `state`.
- `action_suspend_now()` : distant `set_expiration_date(today)` + `block_access_if_expired()` ;
  état local `suspended` ; journal dans le chatter.
- `action_restore()` : distant `restore_access()` ; état local `active`.
- `action_extend()` : ouvre le wizard `instance.extend.wizard` (nb de jours / nouvelle date) ;
  distant `set_expiration_date(nouvelle date)` + `restore_access()`.
- `action_sync_status()` : lecture distante de la date d'expiration.
- Contrainte SQL : `UNIQUE(database, url)`.

#### 4.2 `instance.billing.cycle` — Cycle de facturation par instance

| Champ | Type | Description |
|---|---|---|
| `instance_id` | Many2one `instance.management` (required, cascade, index) | Instance concernée |
| `name` | Char (computed, store) | « Nom instance – Mois Année » |
| `billing_date` | Date (required, index, tracking) | Date de facturation |
| `suspension_date` | Date (computed store, readonly=False, tracking) | facturation + délai global |
| `state` | Selection : `draft`, `awaiting_payment`, `suspended`, `paid` (tracking) | Statut |
| `invoice_id` | Many2one `account.move` (readonly) | Facture générée au centre |
| `invoice_state` | Related `invoice_id.state` / `invoice_id.payment_state` | Suivi paiement |
| `paid_on` | Date (tracking) | Date de paiement |
| `days_until_suspension` | Integer (computed) | Jours avant suspension |
| `reminder_log_ids` | One2many `instance.reminder.log` | Rappels envoyés |
| `_inherit` | `mail.thread`, `mail.activity.mixin` | Chatter |

Contrainte SQL : `UNIQUE(instance_id, billing_date)`.

Méthodes (moteur appelé par cron quotidien) :

- `run_billing_cycles()` : pour chaque instance active → `_ensure_current_cycle`,
  `_process_state`, `_process_invoicing`, `_process_reminders`, `_process_suspension`.
- `_billing_date_for_period(today, billing_day)` : reprise exacte de la logique du module
  client (jour 25, clamp au dernier jour du mois).
- `_ensure_current_cycle(today)` : crée le cycle de la période courante s'il n'existe pas.
- `_process_state(today)` : `draft` → `awaiting_payment` quand `today >= billing_date`.
- `_process_invoicing()` : à l'entrée en `awaiting_payment`, crée la facture client si absente
  (partner = instance, ligne produit global, qty 1, prix = `monthly_amount`,
  ref `SUB-<db>-<YYYY-MM>`), la poste, et log dans le chatter.
- `_process_reminders(today)` : envoi des rappels dont l'intervalle correspond à aujourd'hui
  (dédup via log), même mécanique que le module client.
- `_process_suspension(today)` : si `awaiting_payment` et `today >= suspension_date` →
  `state=suspended`, appel distant `set_expiration_date(today)` +
  `block_access_if_expired()`, alerte de suspension ; en cas d'échec distant, le cycle reste
  `suspended` et une nouvelle tentative a lieu au prochain passage quotidien.
- `_sync_invoice_payments()` (cron horaire) : cycles `awaiting_payment`/`suspended` dont la
  facture est payée → `action_mark_paid()` → rétablissement distant.
- `action_mark_paid()` : cycle → `paid`, `paid_on`, synchronisation distante systématique
  (`set_expiration_date(aujourd'hui + prolongation par défaut)` + `restore_access()`,
  garde-fou si déjà payé).
- `action_postpone_suspension()` : wizard de report (nouvelle date) + mise à jour distante
  (`set_expiration_date`) + nettoyage des logs de rappel.

#### 4.3 `instance.reminder.log` — Journal de déduplication

Identique à `subscription.reminder.log` : `cycle_id`, `days_before`, `type`
(`reminder` / `suspension_alert`), `sent_on`, contrainte
`UNIQUE(cycle_id, days_before, type)`.

#### 4.4 `instance.alert.template` — Templates d'alerte

Identique à `subscription.alert.template` :

- Champs : `name`, `type` (`reminder` / `suspension`), `trigger_days`, `subject`, `body`,
  `active`, contrainte `UNIQUE(type, trigger_days)`.
- Rendu sécurisé via `string.Template.safe_substitute`.
- `pick_reminder_template(days)` : trigger le plus proche ≤ N.
- `get_suspension_template()` : le template `suspension` actif.
- Placeholders : `${instance_name}`, `${client_name}`, `${invoice_ref}`,
  `${invoice_amount}`, `${invoice_currency}`, `${suspension_date}`, `${days_before}`,
  `${db_name}`, `${cycle_name}`.

#### 4.5 `OdooXmlrpcClient` — Client XML-RPC

Copie autonome du client du module client (93 lignes, indépendante), méthodes :
`execute_kw`, `search_read`, plus les helpers du contrôleur :

- `call_control_method(method, *args)` : exécute `execute_kw('subscription.control', method, ...)`.
- `get_expiration_date()` / `set_expiration_date(date)` / `block_access_if_expired()` /
  `restore_access()` / `extend_subscription(days)`.
- Erreurs → `UserError` explicites (connexion, authentification), timeout 10 s.

#### 4.6 `res.config.settings` — Paramètres globaux

| Paramètre (ir.config_parameter) | Défaut |
|---|---|
| `instance_control.billing_day` | `25` |
| `instance_control.payment_delay_days` | `15` |
| `instance_control.reminder_days` | `10,5,2,1` |
| `instance_control.suspension_alert_enabled` | `True` |
| `instance_control.product_id` | (obligatoire pour facturer) |
| `instance_control.recipient_partner_ids` | (csv d'ids) |
| `instance_control.recipient_emails` | (csv d'emails) |
| `instance_control.reminder_template_id` | template module par défaut |
| `instance_control.suspension_template_id` | template module par défaut |
| `instance_control.extend_days` | `30` (prolongation par défaut) |

### Wizards

- `instance.extend.wizard` : `instance_id`, `days` ou `new_expiration_date` → prolongation
  distante + chatter + report du cycle en attente si nécessaire.

## 5. Flux de données

### Cron quotidien `cron_billing_engine` → `instance.billing.cycle.run_billing_cycles()`

1. Pour chaque instance **active** (traitement isolé try/except par instance) :
   1. Création du cycle de la période si absent (`draft`).
   2. À la date de facturation : `awaiting_payment` + génération/poste de la facture.
   3. Rappels J-N (templates d'alerte + email uniquement ; le chatter du cycle
      conserve la trace interne des envois).
   4. À la date de suspension si impayé : suspension distante + alerte.

### Cron horaire `cron_payment_sync` → `_sync_invoice_payments()`

Facture payée (manuellement ou règlement dans l'Odoo central) → cycle `paid` →
rétablissement distant (`set_expiration_date(today + extend_days)` + `restore_access()`).

### Cron quotidien `cron_status_sync` → `instance.management._sync_all_status()`

Lit à distance la date d'expiration de chaque instance active (miroir d'état).

### Canaux d'alerte (email uniquement, conformément à FR-5)

- Email via `mail.template` (configuré ou défaut du module) aux `recipient_partner_ids`
  + `recipient_emails`, `force_send=True`.
- `message_post` sur le chatter du cycle comme trace interne (pas de notification inbox).
- Pas de popup modale bus, pas de messages Discuss côté central (supprimés) : le module
  client `subscription_control` gère ses propres notifications locales sur les instances
  gérées.

## 6. Gestion des erreurs

- Chaque instance est traitée dans son propre `try/except` ; une erreur est enregistrée
  (`last_error`, `last_check`) et n'interrompt pas les autres instances.
- Suspension distante : retentée chaque jour jusqu'à succès ; cycle reste `suspended`.
- Échec de synchro/facturation → email aux destinataires (pattern
  `_notify_sync_failure` du module client).
- `OdooXmlrpcClient` : `UserError` explicites (paramètres incomplets, connexion,
  authentification), timeout 10 s, restauration du timeout global dans `finally`.
- Templates absents → textes par défaut bilingues FR (comme le module client).

## 7. Sécurité

- `security/ir.model.access.csv` :
  - Groupe `group_instance_control_manager` (hérite `base.group_user`) : RW sur
    `instance.management`, `instance.billing.cycle`, `instance.alert.template`, `reminder.log`.
  - Utilisateur interne : lecture seule sur les modèles.
  - Wizards : RW pour le groupe manager.
- Paramètres et crons réservés à `base.group_system` (héritage du comportement standard).
- `api_key` affiché avec `password="True"` (masqué à l'écran).

## 8. Structure du module

```
instance_control/
├── __init__.py
├── __manifest__.py                  # depends: base, mail, web, account
├── models/
│   ├── __init__.py
│   ├── instance_management.py
│   ├── instance_billing_cycle.py    # + wizard report intégré ou wizards/
│   ├── instance_reminder_log.py
│   ├── instance_alert_template.py
│   ├── odoo_xmlrpc_client.py
│   └── res_config_settings.py
├── wizards/
│   ├── __init__.py
│   ├── instance_extend_wizard.py
│   └── instance_postpone_wizard.py
├── data/
│   ├── config_data.xml              # paramètres par défaut
│   ├── cron_data.xml                # 3 crons
│   ├── mail_templates.xml           # mail.template rappel + suspension
│   └── alert_templates.xml          # instance.alert.template par défaut
├── security/
│   └── ir.model.access.csv
├── views/
│   ├── instance_management_views.xml
│   ├── instance_billing_cycle_views.xml
│   ├── instance_alert_template_views.xml
│   └── res_config_settings_views.xml
└── tests/
    ├── __init__.py
    ├── test_billing_cycle.py
    ├── test_invoice_flow.py
    ├── test_remote_actions.py
    └── test_templates.py
```

## 9. Tests

Même structure que `subscription_control/tests` (client XML-RPC mocké via `_get_client`) :

- `test_billing_cycle.py` : `_billing_date_for_period` (mois 31/28 jours, jour 25),
  création unique du cycle, calcul `suspension_date`, dédup rappels (contrainte SQL),
  transitions d'état.
- `test_invoice_flow.py` : génération facture (partner, produit, montant, ref), paiement
  facture → cycle `paid` + appel restore (mock), `action_mark_paid` garde-fous.
- `test_remote_actions.py` : suspend/restore/extend avec client mocké, gestion d'échec
  distant (cycle reste suspendu, `last_error` renseigné).
- `test_templates.py` : rendu placeholders, `pick_reminder_template`, template suspension.

Commande de test :
`odoo-bin -d <db_test> -i instance_control --test-enable --stop-after-init`

## 10. Critères de succès

- SC-1 : L'installation du module sur l'Odoo central ne nécessite aucun changement sur les
  instances gérées.
- SC-2 : À la date de facturation, une facture client est générée par instance dans l'Odoo
  central.
- SC-3 : Sans paiement à la date de suspension (facturation + 15 j), l'instance distante est
  bloquée (accès applications révoqué) et une alerte de suspension est envoyée.
- SC-4 : Paiement de la facture → rétablissement automatique de l'instance distante.
- SC-5 : Rappels envoyés une seule fois par intervalle (dédup vérifiable).
- SC-6 : Templates d'alerte et emails personnalisables depuis l'interface.
- SC-7 : Une instance injoignable n'empêche pas le traitement des autres.
- SC-8 : Tous les tests passent (`--test-enable`).

## 11. Hors périmètre (YAGNI)

- Modification du module client `subscription_control`.
- Portail client / paiement en ligne.
- Multi-devises avancées (la devise suit le partenaire).
- Tableau de bord graphique avancé (vues liste/kanban/form suffisent).
