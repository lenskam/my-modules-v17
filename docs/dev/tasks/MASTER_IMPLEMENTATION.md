# Master Implementation Plan

## Project Overview
Ensemble de modules Odoo 17 personnalisés (my-modules). Le module `subscription_control`
(client, installé sur chaque instance gérée) contrôle localement l'abonnement. Le module
`instance_control` (contrôleur central) gère à distance l'ensemble des instances.

## Phases

### Phase 1: Contrôle d'abonnement côté instance (subscription_control)
- **Goal**: Bloquer l'accès, cycles locaux, rappels, synchro paiement distant.
- **Status**: Existant (17.0.4.0.0) — hors périmètre de cette phase.
- **Completion Date**: 2026-10-12

### Phase 2: Contrôleur central d'instances (instance_control)
- **Goal**: Facturer, suspendre, prolonger par API les instances Odoo gérées ; alertes email.
- **Spec**: [docs/dev/specs/2026-10-15-instance-control-spec.md](../specs/2026-10-15-instance-control-spec.md)
- **Status**: Completed
- **Completion Date**: 2026-10-15
- **Notes**: 47 tests verts (0 failed / 0 error) sur base de test dédiée
  `instance_control_test` — log : [docs/dev/artifacts/2026-10-15_instance-control-tests-passe.log](../artifacts/2026-10-15_instance-control-tests-passe.log)

## Skills
(none)

## Procédure de test (reproductible)
```bash
cd "/mnt/d/DONGMO DYLAN/ODOO/Odoo 17.0/server"
./venv/bin/python odoo-bin -c odoo.conf -d instance_control_test -r odoo -w odoo \
  -i instance_control --test-enable --test-tags=/instance_control \
  --stop-after-init --log-level=info --logfile=
# puis : dropdb -h localhost -U odoo instance_control_test
```
