# SAPTis – Masquer les tiers sans mouvement

Module Odoo **17.0** permettant de masquer, sur les rapports **Grand livre**
(General Ledger) et **Livre des Tiers** (Partner Ledger), les comptes et
partenaires (clients et fournisseurs) n'ayant aucune écriture comptable sur la
période sélectionnée.

## Prérequis

- Odoo **17.0** avec le module `account_reports` (le moteur de reporting
  `account.report` et les rapports concernés y sont définis). Sur l'instance
  SAPTis, ce module se trouve dans le répertoire d'addons
  `matrix-brokers-addons/account_reports`.
- Module `account` installé.
- Mode développeur activé pour l'installation.

## Installation

1. Copier le dossier `custom_account_report_filter` dans un répertoire d'addons
   de l'instance Odoo 17 (ex. `server/my-modules/`), puis **mettre à jour la
   liste des applications**.
2. **Important** : si une ancienne copie du module (version `16.0.1.0.0`) est
   déjà présente, elle doit être remplacée par cette version `17.0.1.0.0` avant
   tout redémarrage — Odoo 17 refuse de charger un manifest en version 16
   (`ValueError: Invalid version '16.0.1.0.0'`).
3. Installer ou mettre à niveau le module `SAPTis - Account Report Filter`
   (`-u custom_account_report_filter` pour une mise à niveau).

## Utilisation

1. Accéder à **Comptabilité ▸ Reporting ▸ Grand livre** ou **Livre des Tiers**.
2. Le bouton **« Masquer les tiers sans mouvement »** est directement visible
   dans la **barre d'options avancées** du rapport (à côté des critères de
   période et de sélection des journaux). Il est **décoché par défaut**.
3. Cocher le bouton, sélectionner la période souhaitée et générer le rapport.

Seuls les tiers ayant au moins une ligne d'écriture comptable
(`account.move.line`) dans la période apparaissent ; sur le Grand livre, les
comptes sans mouvement de la période (uniquement un solde d'ouverture) sont
également masqués. L'option étant décochée par défaut, le comportement
historique d'Odoo est conservé.

Sur la **fiche de configuration** du rapport (Configuration ▸ Filtres), la case
**« Masquer les tiers sans mouvement »** sert de **valeur par défaut** : si elle
est cochée, le filtre est actif par défaut à l'ouverture du rapport (il reste
désactivable dans la barre d'options).

Le filtre s'applique également aux exports PDF / XLSX (la restriction est
injectée dans les options du rapport via `options['forced_domain']`).

## Points d'attention pour le déploiement

- L'option est un champ calculé stocké (`store=True`) sur `account.report`
  (modèle `account.report`), dans la continuité des filtres standard
  (`filter_partner`, `filter_unreconciled`, etc.). Les vues héritées référencent
  la vue de formulaire `account_reports.account_report_form` (module
  `account_reports` Odoo 17).
- Le filtre s'applique exclusivement aux rapports **Grand livre**
  (`general_ledger_report`) et **Livre des Tiers** (`partner_ledger_report`) ;
  les autres rapports ne sont pas affectés (les autres éditions comptables ne
  sont pas concernées).
- L'activation s'opère via le **custom handler** du rapport : la restriction
  des partenaires du Livre des Tiers est portée par
  `options['forced_domain']`, et les comptes dormants du Grand livre sont
  éliminés après génération des lignes dans le handler
  `account.general.ledger.report.handler`.
- En l'absence de période renseignée (champ date vide), le filtre est neutralisé
  et le rapport se comporte comme en standard.
- Si l'utilisateur a déjà sélectionné des partenaires, le filtre calcule
  l'intersection : seuls les partenaires sélectionnés **et** actifs sur la
  période sont affichés.

## Tests

Les tests nécessitent une base avec le module `account_reports` installé :

```bash
odoo-bin -d <base> -i custom_account_report_filter --test-enable --stop-after-init
```

- Tests unitaires (`TestGetPartnerIdsWithMoves`) : logique SQL de calcul des
  partenaires actifs (sans dépendance au moteur de rapport).
- Tests d'intégration (`TestHidePartnersWithoutMovesOption`,
  `TestHideDormantAccountsGeneralLedger`) : initialisation des options
  (`forced_domain`) et génération réelle des lignes du Grand livre avec
  l'option activée/désactivée.

## Désinstallation / Rollback

1. Désinstaller le module (Applications ▸ SAPTis - Account Report Filter ▸
   Désinstaller) – le champ `filter_hide_partners_without_moves` est supprimé.
2. Si nécessaire, restaurer la sauvegarde de base effectuée avant installation.

## Risques et limites connus

- **Performance** : la requête de calcul des partenaires actifs est optimisée
  (`SELECT DISTINCT partner_id ...` sur `account_move_line`). Sur de très gros
  volumes, valider les temps de réponse en pré-production.
- **Régression** : le comportement standard est inchangé tant que l'option est
  décochée (comportement par défaut).
- **Exports** : les exports PDF/XLSX respectent le filtre tant que l'option est
  active dans la barre d'options avant l'export.

## Structure du module

```
custom_account_report_filter/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── account_report.py          # champ + initialiseur d'options + SQL optimisé
│   └── general_ledger_handler.py  # masquage des comptes dormants (Grand livre)
├── static/src/components/account_report/filters/
│   ├── filters.js                 # composant OWL (AccountReportFilters)
│   ├── filters.xml                # héritage du template de la barre d'options
│   └── filter_hide_partners_without_moves.xml
├── views/
│   └── account_report_view.xml    # champ sur la fiche de rapport
└── tests/
    ├── __init__.py
    └── test_account_report.py
```
