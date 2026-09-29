# alerts

**Task:** Task 3  
**Status:** planned

## Purpose

Visual flags in the Excel view of the Topic Log so the editor sees what needs attention at a glance: gated rows, tier, large moves, data quality problems.

## Inputs

`2_topic_log`; alert thresholds (to be added to `config/`).

## Outputs

Conditional formatting rules and flag columns in the Topic Log workbook.

## Depends on

`scoring/` output; `schema/` column names.

## Contents

Planned: the rule definitions (which column, which condition, which colour) and a script that applies them to the workbook.

## Usage

To be written. Alert thresholds belong in `config/`, not in the workbook formulas, so they are versioned with everything else.

---

Back to the [project README](../README.md).
