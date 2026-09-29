# visuals

**Status:** planned

## Purpose

Live charts of Topic Log data built with Plotly and rendered as assets for the MYCAST video composed in Shotstack.

## Inputs

`2_topic_log` and `1_market_snapshots` (for intraday probability paths and strike ladders); the chosen angle from `3_episode_log`.

## Outputs

Chart images or clips sized for the Shotstack timeline.

## Depends on

`scoring/` output; the angle mapping in `playbook/README.md` section 7 (each angle needs a specific chart).

## Contents

Planned: one chart per angle (direction, distribution, touch, updown_vs_option, range) and an export step for Shotstack.

## Usage

To be written.

---

Back to the [project README](../README.md).
