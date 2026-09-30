Astra-inspired gnome Healer policy

Objective: hea-gno-neu-mal (male, neutral, gnome Healer).
This is executable Python policy. It makes no LLM or network calls in a game.

Starting point: vlomshakov/nethacker at 4ed08da3bdd3f11e120678005877d4a56009ccd0.
The manifest preserves the AutoAscend lineage and pinned Astra influence.

Evaluate with the official sealed arena:
  nethackers eval bots/healer-astra --objective hea-gno-neu-mal

Submit and evaluate through the official hub:
  nethackers submit bots/healer-astra --objective hea-gno-neu-mal

The local experiments directory contains public evaluation records and focused
regression checks. Public progress is a milestone score; it is not an ascension
rate. Private verification is performed separately by the hub.

Known inherited limitation: the low-success stone-to-flesh food strategy references
missing object constants when attempting to remove metal armor. The agent catches
this internally. Both tested repairs reduced public progress and are retained
as experiments rather than included in this milestone submission.

Evaluation variability: the same policy produced 40.59% in local validation,
39.33% in its first submission evaluation, and approximately 40.67% in a repeat.
These public results do not establish private-seed performance. The hub retains
the first evaluation for an immutable commit. All trial records remain local.

Final descent setting: prefer nearby stairs within three squares through depth
11; use the original eight-square stair preference starting at depth 12.

Blindness recovery also accepts positively identified blessed ordinary healing.
Unblessed ordinary healing is excluded from this sight-restoration strategy.

Rest policy: while digging, rest below 50% HP at depths under 24; restore the
original 60% threshold from depth 24. Gehennom retains its own 30% threshold.
This hybrid evaluated at 40.42599% mean progress across 15 public games.
