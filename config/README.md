# config

**Status:** w0 draft

## Purpose

Holds every tunable number in the Topic Log: gate thresholds, component weights, quality and cooldown multipliers, tier conditions, angle rules and override codes. Scoring, alerts and visuals read from here; nothing is hard-coded elsewhere.

## Inputs

Decisions from the weekly review (see `playbook/README.md`, section 9).

## Outputs

`weights_wN.yaml`, read by `scoring/` and referenced by `playbook/`.

## Depends on

Nothing.

## Contents

| File | Purpose |
|---|---|
| `weights_w0.yaml` | Active parameter set (draft). |
| `CHANGELOG.md` | One entry per parameter change, newest first. |

## Usage

1. Never edit a version that has already been used to select an episode.
2. To change a value: copy to `weights_wN+1.yaml`, change **one** value, set `version`, add a `CHANGELOG.md` entry.
3. Point the scoring job at the new file.

```python
import yaml
cfg = yaml.safe_load(open("config/weights_w0.yaml"))
weights = {k: v["weight"] for k, v in cfg["components"].items()}
```

---

Back to the [project README](../README.md).
