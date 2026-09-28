"""Minimal lawful Valkyrie quest route, gated by the Norn's public dialogue.

Source: NetHack 3.6.7 quest.c and dat/quest.txt. XL14 alone is insufficient:
the leader also checks alignment record and conversion. Only her assignment
message authorizes descent; the policy never reads the private quest flags.
"""
from dataclasses import dataclass, field
from collections import deque

import nle.nethack as nh
from nle.nethack import actions as A

from . import utils
from .character import Character
from .glyph import G, MON
from .item import Item, flatten_items
from .level import Level


MAX_CHAT = 3
MAX_LEVEL_TURNS = 2500
MAX_TOTAL_TURNS = 12000
MAX_STAIR_FAILURES = 3
REVISIT_MAX_TURNS = 5000
REVISIT_LEVEL_TURNS = 800
REVISIT_MAX_STEPS = 20000
REVISIT_MAX_ACTIONS = 3000
LEADER = 'Norn'


@dataclass
class QuestState:
    started: int
    approved: bool = False
    declined: bool = False
    returning: bool = False
    offered: bool = False
    chats: int = 0
    return_chats: int = 0
    level_started: dict = field(default_factory=dict)
    stair_failures: dict = field(default_factory=dict)
    pickup_failures: dict = field(default_factory=dict)
    reason: str = ''


@dataclass
class RevisitState:
    started: int
    started_step: int
    actions: int = 0
    level_started: dict = field(default_factory=dict)
    refused: dict = field(default_factory=dict)
    done: bool = False
    reason: str = ''


def state(dive):
    if not hasattr(dive, '_valkyrie_quest'):
        dive._valkyrie_quest = QuestState(int(dive.agent.blstats.time))
    return dive._valkyrie_quest


def ready(agent):
    return (agent.character.role == Character.VALKYRIE and
            agent.character.alignment == Character.LAWFUL and
            int(agent.blstats.alignment) == 1 and
            agent.blstats.experience_level >= 14)


def is_bell(item):
    return item.is_unambiguous() and item.object.name.lower() == 'bell of opening'


def is_orb(item):
    return (item.is_unambiguous() and item.object.name == 'crystal ball' and
            (getattr(item, 'naming', '') or '').lower().removeprefix('the ') == 'orb of fate')


def _has(agent, predicate):
    return any(predicate(i) for i in flatten_items(agent.inventory.items))


def note(dive):
    """Read full public message/pop-up text, including automatic leader speech."""
    agent = dive.agent
    in_quest = agent.current_level().dungeon_number == Level.QUEST
    revisit = getattr(dive, '_quest_revisit', None)
    if in_quest and revisit is not None and not revisit.done:
        revisit.done = True
        revisit.reason = 'entered the Quest through the observed portal'
        agent.log('QUEST REVISIT reached Home; handing over to leader route')
    # Rejection expels the hero immediately, so its final message may already
    # arrive in the parent dungeon. Retain that public refusal across exit.
    if not in_quest and not hasattr(dive, '_valkyrie_quest'):
        return
    if not hasattr(dive, '_valkyrie_quest') and not ready(agent):
        return
    q = state(dive)
    text = ' '.join((agent.message + ' ' + ' '.join(agent.popup)).lower().split())
    if in_quest and ('it is now likely that you can defeat lord surtur' in text or
                     'find the cave of surtur; defeat lord surtur;' in text):
        if not q.approved:
            agent.log('QUEST Norn assignment observed; descent approved')
        q.approved = True
    if any(s in text for s in ('grow more experienced at the ways of war',
                               'you have strayed from the lawful path',
                               'begone from my presence',
                               'you are not yet ready for this quest',
                               'a mysterious force prevents you from descending')):
        q.declined = q.returning = True
        q.reason = 'leader or stairs refused the quest'
        agent.log('QUEST refusal observed; returning without retrying descent')
    if 'take the orb of fate' in text and ('amulet' in text or 'search' in text):
        q.offered = True


def active(dive):
    agent = dive.agent
    if agent.current_level().dungeon_number != Level.QUEST:
        return False
    q = getattr(dive, '_valkyrie_quest', None)
    return ready(agent) or (q is not None and (q.approved or q.returning))


def _leader(agent):
    if agent.character.prop.hallu:
        return None
    glyph = MON.from_name(LEADER)
    detected = nh.GLYPH_DETECT_OFF + MON.id_from_name(LEADER)
    positions = list(zip(*utils.isin(agent.glyphs, [glyph, detected]).nonzero()))
    if not positions:
        return None
    y, x = min(positions, key=lambda p: max(abs(p[0] - agent.blstats.y), abs(p[1] - agent.blstats.x)))
    return int(y), int(x)


def _chat(dive, returning=False):
    agent, q = dive.agent, state(dive)
    target = _leader(agent)
    if target is None:
        return False
    here = (agent.blstats.y, agent.blstats.x)
    if not utils.adjacent(here, target):
        if dive._neighbour_distance(agent.bfs(), *target) is None:
            return False
        agent.go_to(*target, stop_one_before=True)
        return True
    attempts = q.return_chats if returning else q.chats
    if attempts >= MAX_CHAT:
        q.returning = True
        q.reason = 'leader dialogue did not establish approval'
        return False
    if returning:
        q.return_chats += 1
    else:
        q.chats += 1
    direction = agent.calc_direction(*here, *target)

    def responses():
        if 'direction' in agent.single_message.lower():
            yield direction

    agent.log(f'QUEST chatting with the Norn at {target}')
    with agent.atom_operation():
        agent.step(A.Command.CHAT, responses())
    note(dive)
    return True


def _reward_positions(agent):
    level = agent.current_level()
    positions = []
    for y, x in zip(*(level.item_count > 0).nonzero()):
        if any(is_bell(i) or is_orb(i) for i in level.items[y, x]):
            positions.append((int(y), int(x)))
    return positions


def _pickup_rewards(dive):
    agent, q = dive.agent, state(dive)
    inv = agent.inventory
    here = (int(agent.blstats.y), int(agent.blstats.x))
    key = (agent.current_level().key(), here)
    if q.pickup_failures.get(key, 0) < 2:
        inv.get_items_below_me()
        wanted = [i for i in inv.items_below_me if (is_bell(i) or is_orb(i)) and i.shop_status == Item.NOT_SHOP]
        if wanted:
            before = sum(i.count for i in inv.items if is_bell(i) or is_orb(i))
            inv.pickup(wanted)
            inv.items.update(force=True)
            after = sum(i.count for i in inv.items if is_bell(i) or is_orb(i))
            if after <= before:
                q.pickup_failures[key] = q.pickup_failures.get(key, 0) + 1
            else:
                agent.log('QUEST reward acquired and confirmed in inventory')
            return True
    distance = agent.bfs()
    targets = [p for p in _reward_positions(agent) if p != here and distance[p] >= 0 and
               q.pickup_failures.get((agent.current_level().key(), p), 0) < 2]
    if targets:
        agent.go_to(*min(targets, key=lambda p: distance[p]))
        return True
    return False


def _stairs(dive, direction):
    agent, q = dive.agent, state(dive)
    level = agent.current_level()
    glyphs = G.STAIR_DOWN if direction == '>' else G.STAIR_UP
    targets = [(int(y), int(x)) for y, x in zip(*utils.isin(level.objects, glyphs).nonzero())]
    # Known observed stairs may currently be covered by a monster or object.
    for p, destination in level.stair_destination.items():
        if destination is not None and destination[0][0] == Level.QUEST and \
                (destination[0][1] - level.level_number) * (1 if direction == '>' else -1) > 0:
            if p not in targets:
                targets.append(p)
    targets = [p for p in targets if q.stair_failures.get((level.key(), p, direction), 0) < MAX_STAIR_FAILURES]
    if not targets:
        return False
    before_key = level.key()
    before = (int(agent.blstats.y), int(agent.blstats.x))
    if before in targets:
        _climb(dive, direction)
        acted = True
    else:
        acted = dive._take_stairs(targets, direction)
    if before in targets and agent.current_level().key() == before_key and acted:
        failure = (before_key, before, direction)
        q.stair_failures[failure] = q.stair_failures.get(failure, 0) + 1
        if direction == '>' and level.level_number == 1:
            # Even an earlier approval can become invalid after alignment loss.
            q.declined = q.returning = True
            q.reason = 'Home downstairs did not change level; no forced retries'
            agent.log('QUEST Home descent failed; returning to the portal')
    return acted


def _climb(dive, direction):
    """Ordinary stairs without Agent.move's assertion on a refused transition."""
    agent = dive.agent
    before_level = agent.current_level()
    before = (int(agent.blstats.y), int(agent.blstats.x))
    with agent.atom_operation():
        agent.direction(direction)
    after_level = agent.current_level()
    if before_level.key() == after_level.key():
        return False
    after = (int(agent.blstats.y), int(agent.blstats.x))
    before_level.stair_destination[before] = (after_level.key(), after)
    after_level.stair_destination[after] = (before_level.key(), before)
    return True


def revisit_active(dive):
    """One return opportunity after the earlier unready visit, before more diving."""
    agent = dive.agent
    if agent.current_level().dungeon_number not in (0, 1, 2, 4, 5) or not ready(agent) or \
            not dive.visited_quest or dive.portal_level is None or _has(agent, is_bell):
        return False
    q = getattr(dive, '_valkyrie_quest', None)
    if q is not None and (q.declined or q.returning):
        return False
    r = getattr(dive, '_quest_revisit', None)
    return r is None or not r.done


def _stair_direction(level, pos, destination):
    glyph = level.objects[pos]
    if glyph in G.STAIR_UP:
        return '<'
    if glyph in G.STAIR_DOWN:
        return '>'
    # Only infer covered stairs from a traversed connection within a branch.
    if destination is not None and destination[0][0] == level.dungeon_number:
        delta = destination[0][1] - level.level_number
        return '>' if delta > 0 else '<' if delta < 0 else None
    return None


def _known_route(dive):
    """Breadth-first route over actual recorded stair transitions only."""
    agent = dive.agent
    start, target = agent.current_level().key(), dive.portal_level
    todo, seen = deque([(start, [])]), {start}
    r = dive._quest_revisit
    while todo:
        key, path = todo.popleft()
        if key == target:
            return path
        level = agent.levels.get(key)
        if level is None:
            continue
        for pos, dest in level.stair_destination.items():
            if dest is None or dest[0] in seen or dest[0][0] not in (0, 1, 2, 4, 5):
                continue
            direction = _stair_direction(level, pos, dest)
            if direction is None or r.refused.get((key, pos, direction), 0) >= MAX_STAIR_FAILURES:
                continue
            seen.add(dest[0])
            todo.append((dest[0], path + [(pos, direction, dest[0])]))
    return None


def _revisit_targets(dive):
    """When digging left gaps in map memory, discover ordinary stairs upward."""
    agent = dive.agent
    level = agent.current_level()
    target = dive.portal_level
    if level.dungeon_number == target[0]:
        direction = '<' if level.level_number > target[1] else '>'
    elif level.dungeon_number in (1, Level.GNOMISH_MINES):
        direction = '<'
    elif level.dungeon_number in (Level.SOKOBAN, 5):  # inverse-branch stairs
        direction = '>'
    else:
        return []
    glyphs = G.STAIR_UP if direction == '<' else G.STAIR_DOWN
    positions = set(zip(*utils.isin(level.objects, glyphs).nonzero()))
    for pos, destination in level.stair_destination.items():
        if destination is not None and _stair_direction(level, pos, destination) == direction:
            positions.add(pos)
    r = dive._quest_revisit
    ret = []
    for pos in positions:
        dest = level.stair_destination.get(pos)
        # Do not re-enter a known side branch while seeking the parent portal.
        if dest is not None and level.dungeon_number in (0, 1) and dest[0][0] not in (0, 1):
            continue
        if r.refused.get((level.key(), pos, direction), 0) < MAX_STAIR_FAILURES:
            ret.append((tuple(map(int, pos)), direction))
    return ret


def _revisit_portals(dive):
    from .dive_logic import PORTAL
    level = dive.agent.current_level()
    ret = set(zip(*utils.isin(level.objects, PORTAL).nonzero()))
    known = getattr(dive, '_quest_parent_portal', None)
    if known is not None and known[0] == level.key():
        ret.add(known[1])
    return [tuple(map(int, p)) for p in ret]


def _finish_revisit(dive, reason):
    r = dive._quest_revisit
    r.done, r.reason = True, reason
    dive.agent.log(f'QUEST REVISIT stopped: {reason}; resuming ordinary route')


def _enter_portal(dive, pos):
    agent = dive.agent
    here = (int(agent.blstats.y), int(agent.blstats.x))
    if here == pos:
        dis = agent.bfs()
        for p in agent.neighbors(*here, shuffle=False):
            if dis[p] == 1 and not agent.monster_tracker.monster_mask[p]:
                agent.direction(agent.calc_direction(*here, *p))
                return True
        return False
    if not utils.adjacent(here, pos):
        if dive._neighbour_distance(agent.bfs(), *pos) is None:
            return False
        agent.go_to(*pos, stop_one_before=True, max_steps=40)
        return True
    before = agent.current_level().key()
    with agent.atom_operation():
        agent.direction(agent.calc_direction(*here, *pos))
    if agent.current_level().dungeon_number == Level.QUEST:
        note(dive)
    elif agent.current_level().key() == before:
        # A sealed, stale, or non-triggering portal must not make a move loop.
        r = dive._quest_revisit
        key = (before, pos, 'portal')
        r.refused[key] = r.refused.get(key, 0) + 1
        if r.refused[key] >= MAX_STAIR_FAILURES:
            _finish_revisit(dive, 'observed portal did not enter the Quest')
    return True


def revisit_step(dive):
    if not revisit_active(dive):
        return
    agent = dive.agent
    if not hasattr(dive, '_quest_revisit'):
        dive._quest_revisit = RevisitState(int(agent.blstats.time), int(agent.step_count))
        agent.log(f'QUEST REVISIT returning to known portal level {dive.portal_level}')
    r = dive._quest_revisit
    key = agent.current_level().key()
    r.level_started.setdefault(key, int(agent.blstats.time))
    if agent.blstats.time - r.started >= REVISIT_MAX_TURNS or \
            agent.blstats.time - r.level_started[key] >= REVISIT_LEVEL_TURNS or \
            agent.step_count - r.started_step >= REVISIT_MAX_STEPS or r.actions >= REVISIT_MAX_ACTIONS:
        _finish_revisit(dive, 'bounded return budget exhausted')
        return
    r.actions += 1
    if key == dive.portal_level:
        for pos in _revisit_portals(dive):
            if _enter_portal(dive, pos):
                return
    else:
        route = _known_route(dive)
        targets = [(route[0][0], route[0][1])] if route else _revisit_targets(dive)
        dis = agent.bfs()
        targets.sort(key=lambda t: dis[t[0]] if dis[t[0]] >= 0 else 10 ** 9)
        for pos, direction in targets:
            if pos == (agent.blstats.y, agent.blstats.x):
                if not _climb(dive, direction):
                    failure = (key, pos, direction)
                    r.refused[failure] = r.refused.get(failure, 0) + 1
                return
            if dive._take_stairs([pos], direction):
                return
    start, steps = int(agent.blstats.time), int(agent.step_count)

    def replan():
        if agent.current_level().key() != key or not revisit_active(dive):
            return True
        if agent.blstats.time - start >= 80 or agent.step_count - steps >= 300:
            return True
        dis = agent.bfs()
        if key == dive.portal_level:
            return any(dive._neighbour_distance(dis, *p) is not None for p in _revisit_portals(dive))
        return any(dis[pos] >= 0 for pos, _ in _revisit_targets(dive))

    dive.exploration(None).until(agent, replan).run()
    if agent.step_count == steps:
        # Exhausted exploration must still advance the bounded return budget.
        agent.search()


def step(dive):
    agent, q = dive.agent, state(dive)
    note(dive)
    level = agent.current_level()
    q.level_started.setdefault(level.key(), int(agent.blstats.time))
    if not ready(agent) or q.declined or agent.blstats.time - q.started > MAX_TOTAL_TURNS or \
            agent.blstats.time - q.level_started[level.key()] > MAX_LEVEL_TURNS:
        q.returning = True
    if _pickup_rewards(dive):
        return
    if _has(agent, is_bell):
        q.returning = True
        q.reason = 'Bell acquired; returning from quest'
    if q.returning:
        if level.level_number == 1:
            if _has(agent, is_orb) and not q.offered and q.return_chats < MAX_CHAT and _chat(dive, returning=True):
                return
            return dive.leave_quest()
        if _stairs(dive, '<'):
            return
    elif level.level_number == 1 and not q.approved:
        if _chat(dive):
            return
        if q.returning:
            return dive.leave_quest()
    elif q.approved and _stairs(dive, '>'):
        return
    elif not q.approved:
        # Never infer quest permission from XL, branch depth, or a map layout.
        q.returning = True
        return
    started = int(agent.blstats.time)
    old_key = level.key()

    def replan():
        if agent.current_level().key() != old_key or agent.blstats.time - started >= 100:
            return True
        dis = agent.bfs()
        leader = _leader(agent)
        if not q.approved and not q.returning and leader is not None and \
                dive._neighbour_distance(dis, *leader) is not None:
            return True
        if any(dis[p] >= 0 and q.pickup_failures.get((old_key, p), 0) < 2
               for p in _reward_positions(agent)):
            return True
        if q.returning or q.approved:
            direction = '<' if q.returning else '>'
            glyphs = G.STAIR_UP if q.returning else G.STAIR_DOWN
            return any(dis[p] >= 0 and q.stair_failures.get((old_key, p, direction), 0) < MAX_STAIR_FAILURES
                       for p in zip(*utils.isin(agent.current_level().objects, glyphs).nonzero()))
        return False

    dive.exploration(None).until(agent, replan).run()
