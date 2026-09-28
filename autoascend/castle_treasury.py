"""Bounded Castle wishing-chest retrieval using public observations and commands.

The four candidate cells come from NetHack 3.6.6 dat/castle.des. They are
alternatives, not knowledge of which tower contains this game's reward.
Only actual floor chests are inspected; only a wand seen in their contents
is taken. The cursed scare scroll on the floor is left untouched.
"""

from dataclasses import dataclass, field

import nle.nethack as nh
from nle.nethack import actions as A

from .exceptions import AgentChangeStrategy, AgentFinished, AgentPanic


TOWERS = ((4, 2), (4, 14), (58, 2), (58, 14))  # Castle map (x, y)
MAX_ACTIONS = 240
MAX_STEPS = 1200
MAX_TURNS = 400
MAX_STALL = 10
MAX_UNLOCKS = 8
MIN_HP = 15
MIN_HP_FRACTION = 0.45
UNLOCKERS = ('skeleton key', 'lock pick', 'credit card')


@dataclass
class TreasuryState:
    started_turn: int
    started_step: int
    visited: set = field(default_factory=set)
    unlocks: dict = field(default_factory=dict)
    target: tuple | None = None
    actions: int = 0
    same_position: int = 0
    last_position: tuple | None = None
    acquired_glyph: int | None = None
    acquired: bool = False
    identified: bool = False
    done: bool = False
    reason: str = ''


def _log(castle, message):
    castle.agent.log(f'CASTLE TREASURY {message}')


def _finish(castle, state, reason):
    state.done = True
    state.reason = reason
    _log(castle, f'{reason}; resuming Castle descent')
    return False


def _wand_count(items, glyph):
    return sum(i.count for i in items if i.category == nh.WAND_CLASS and glyph in i.glyphs)


def _is_wishing(item):
    return item.category == nh.WAND_CLASS and item.is_unambiguous() and item.object.name == 'wishing'


def _identify_acquired(castle, state):
    """A normal zap establishes identity; cancel any unexpected direction prompt."""
    agent = castle.agent
    inv = agent.inventory
    wand = next((i for i in inv.items if i.category == nh.WAND_CLASS and
                 state.acquired_glyph in i.glyphs), None)
    if wand is None:
        return _finish(castle, state, 'acquired wand no longer carried')
    if not _is_wishing(wand):
        letter = inv.items.get_letter(wand)
        agent._last_wand_use_step = agent.step_count
        with agent.atom_operation():
            agent.step(A.Command.ZAP)
            if 'What do you want to zap?' in agent.single_message:
                agent.type_text(letter)
            if 'In what direction?' in agent.single_message:
                agent.step(A.Command.ESC)
        inv.items.update(force=True)
        wand = next((i for i in inv.items if i.category == nh.WAND_CLASS and
                     state.acquired_glyph in i.glyphs), None)
    state.identified = wand is not None and _is_wishing(wand)
    _finish(castle, state, 'wishing wand identified in inventory' if state.identified else
            'wand acquired; zap did not establish wishing identity')
    return True


def _unlock(castle, state, chest):
    agent = castle.agent
    pos = castle._pos()
    tools = [i for i in agent.inventory.items if i.is_unambiguous() and i.object.name in UNLOCKERS]
    if not tools or state.unlocks.get(pos, 0) >= MAX_UNLOCKS:
        return _finish(castle, state, 'treasury chest locked; no available opener or unlock budget')
    tool = min(tools, key=lambda i: UNLOCKERS.index(i.object.name))
    letter = agent.inventory.items.get_letter(tool)
    state.unlocks[pos] = state.unlocks.get(pos, 0) + 1

    def responses():
        if 'What do you want to use or apply?' not in agent.single_message and \
                'What do you want to apply?' not in agent.single_message:
            return
        yield letter
        if 'direction' in agent.single_message.lower():
            yield '.'
        prompt = agent.single_message.lower()
        if ('unlock' in prompt or 'pick its lock' in prompt) and '[yn' in prompt:
            yield 'y'

    with agent.atom_operation():
        agent.step(A.Command.APPLY, responses())
    _log(castle, f'unlock attempt {state.unlocks[pos]} at {pos}: {agent.message[:100]!r}')
    return True


def _inspect(castle, state):
    agent = castle.agent
    inv = agent.inventory
    pos = castle._pos()
    inv.get_items_below_me()
    chests = [i for i in inv.items_below_me if i.is_unambiguous() and i.object.name == 'chest']
    if len(chests) != 1:
        state.visited.add(pos)
        state.target = None
        _log(castle, f'checked tower {pos}: {len(chests)} floor chests')
        return True
    chest = chests[0]
    inv.check_container_content(chest)
    if chest.content is None:
        return _finish(castle, state, 'could not inspect treasury chest')
    if chest.content.locked:
        return _unlock(castle, state, chest)
    wands = [i for i in chest.content.items if i.category == nh.WAND_CLASS]
    if not wands:
        state.visited.add(pos)
        state.target = None
        _log(castle, f'checked tower {pos}: no wand in chest')
        return True
    if inv.items.free_slots() < 1:
        return _finish(castle, state, 'no inventory slot for treasury wand')
    # No guessed object IDs or hidden contents: this wand was in the #loot menu.
    wand = next((i for i in wands if _is_wishing(i)), wands[0])
    glyph = wand.glyphs[0]
    before = _wand_count(inv.items, glyph)
    inv.use_container(chest, [], [wand])
    inv.items.update(force=True)
    if _wand_count(inv.items, glyph) <= before:
        return _finish(castle, state, 'loot command did not add the treasury wand to inventory')
    state.acquired = True
    state.acquired_glyph = glyph
    _log(castle, f'acquired wand from tower {pos}; confirmed in inventory (appearance {glyph})')
    return True


def step(castle):
    """True iff the treasury acted; False immediately resumes the original route."""
    from . import castle_cross

    agent = castle.agent
    state = getattr(castle, '_treasury', None)
    if state is not None and state.done:
        return False
    if agent.current_level().key() != castle.castle_key or not castle_cross.wallwalker(agent):
        if state is not None:
            _finish(castle, state, 'left the Castle or lost the wall-walking form')
        return False
    if state is None:
        # An already obtained wish wand does not justify another detour.
        if any(_is_wishing(i) for i in agent.inventory.items):
            return False
        state = castle._treasury = TreasuryState(agent.blstats.time, agent.step_count)
        _log(castle, 'beginning bounded tower search')
    bl = agent.blstats
    if bl.hitpoints < max(MIN_HP, MIN_HP_FRACTION * bl.max_hitpoints):
        return _finish(castle, state, 'low HP abort')
    if state.actions >= MAX_ACTIONS or agent.step_count - state.started_step >= MAX_STEPS or \
            bl.time - state.started_turn >= MAX_TURNS:
        return _finish(castle, state, 'search budget exhausted')
    state.actions += 1
    try:
        if state.acquired:
            return _identify_acquired(castle, state)
        pos = castle._pos()
        if pos in TOWERS and pos not in state.visited:
            return _inspect(castle, state)
        remaining = set(TOWERS) - state.visited
        if not remaining:
            return _finish(castle, state, 'all four towers checked without a wand')
        goals = {state.target} if state.target in remaining else remaining
        path = castle_cross._xorn_path(castle, pos, goals=goals, blocked=castle_cross.TRAPDOORS)
        if not path or len(path) < 2:
            return _finish(castle, state, 'no tower path')
        state.target = path[-1]
        nxt = path[1]
        y, x = castle_cross.to_bot(*nxt)
        d = agent.calc_direction(bl.y, bl.x, y, x)
        if castle._monster_at(*nxt):
            # Let the pre-existing trapdoor route choose a way around a defender.
            # This detour does not spend a fragile xorn form fighting for loot.
            return _finish(castle, state, f'tower path blocked by a monster at {nxt}')
        agent.direction(d)
        after = castle._pos()
        state.same_position = state.same_position + 1 if after == pos else 0
        state.last_position = after
        if state.same_position >= MAX_STALL:
            _finish(castle, state, 'tower approach stalled')
        return True
    except (AgentChangeStrategy, AgentFinished):
        raise
    except AgentPanic:
        _finish(castle, state, 'container or movement panic')
        raise
    except Exception as exc:
        # Do not let an optional side trip terminate a live episode. The main
        # recovery loop cancels the current menu before it resumes the route.
        _finish(castle, state, f'optional treasury failed: {type(exc).__name__}: {exc}')
        raise AgentPanic('treasury operation failed') from exc
