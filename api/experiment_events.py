"""Feeds Flagsmith's Experiments tab: who saw which variant, and what they went on to do.

Two kinds of event, both sent through the Flagsmith SDK's buffered sender (so a request never waits
for them, and a Flagsmith outage never breaks the app):

  exposure    `expose()`: "this visitor was served a variant". Sent when the flag actually shaped
              what the visitor saw. Only visitors Flagsmith has put in the experiment count: a
              demo identity pinned with an identity override is never part of an experiment.
  conversion  `convert()`: "this visitor did the thing the experiment measures", for example
              `alternative_selected` or `match_accepted`.

Everything here is a silent no-op when Flagsmith is not configured, when events are switched off
(FLAGSMITH_EVENTS=0), or when anything goes wrong. Synthetic visitors (identity `sim-...`) are tagged
`simulated` in each event's metadata so they stay recognisable in Flagsmith's own data.
"""

from __future__ import annotations

import logging

import flags

log = logging.getLogger("gharchalo.experiments")

SIMULATED_PREFIX = "sim-"


def _metadata(user_id: str) -> dict[str, object]:
    return {"simulated": user_id.startswith(SIMULATED_PREFIX)}


def expose(feature_name: str, user_id: str | None) -> None:
    """Record that `user_id` was served `feature_name`'s variant (only if they are in its experiment)."""
    if not user_id:
        return
    client = flags.client()
    if client is None:
        return
    try:
        # Resolves the flag for this identity and, if they are enrolled in a running experiment,
        # sends the exposure with the right variant key. A no-op for everyone else.
        client.get_experiment_flag(feature_name, user_id)
    except Exception as exc:  # analytics must never break a request
        log.debug("exposure for %s skipped: %s", feature_name, exc)


def convert(event: str, user_id: str | None) -> None:
    """Record that `user_id` did something an experiment measures."""
    if not user_id:
        return
    client = flags.client()
    if client is None:
        return
    try:
        client.track_event(event, identifier=user_id, metadata=_metadata(user_id))
    except Exception as exc:
        log.debug("event %s skipped: %s", event, exc)
