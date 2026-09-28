"""Public-observation wish planning, enabled only by an actual wish prompt.

Charging is deliberately conservative: a wishing wand explodes on its second
recharge. Never infer its history from its appearance or from an empty zap.
"""
import re

import nle.nethack as nh
from nle.nethack import actions as A

from . import objects as O
from .character import Character
from .item import flatten_items
from .strategy import Strategy


GDSM = 'blessed greased +2 gray dragon scale mail'
MR_CLOAK = 'blessed greased +2 cloak of magic resistance'
REFLECTION = 'blessed greased +2 shield of reflection'
REFLECTION_AMULET = 'blessed amulet of reflection'
SPEED = 'blessed greased +2 speed boots'
LIFE_SAVING = 'blessed amulet of life saving'
LEVITATION = 'blessed ring of levitation'
CHARGING = '2 blessed scrolls of charging'
IDENTIFY = '2 blessed scrolls of identify'
GAIN_LEVEL = '3 blessed potions of gain level'
HORN = 'blessed unicorn horn'
FULL_HEALING = '3 blessed potions of full healing'

WISH_OBJECTS = {
    GDSM: O.from_name('gray dragon scale mail'),
    MR_CLOAK: O.from_name('cloak of magic resistance'),
    REFLECTION: O.from_name('shield of reflection'),
    REFLECTION_AMULET: O.from_name('amulet of reflection'),
    SPEED: O.from_name('speed boots'),
    LIFE_SAVING: O.from_name('amulet of life saving'),
    LEVITATION: O.from_name('levitation', nh.RING_CLASS),
    CHARGING: O.from_name('charging', nh.SCROLL_CLASS),
    IDENTIFY: O.from_name('identify', nh.SCROLL_CLASS),
    GAIN_LEVEL: O.from_name('gain level', nh.POTION_CLASS),
    HORN: O.from_name('unicorn horn'),
    FULL_HEALING: O.from_name('full healing', nh.POTION_CLASS),
}
MR_NAMES = frozenset(('gray dragon scale mail', 'gray dragon scales', 'cloak of magic resistance'))
REFLECTION_NAMES = frozenset(('shield of reflection', 'silver dragon scale mail',
                              'silver dragon scales', 'amulet of reflection'))
_CHARGES = re.compile(r'\((\d+):(-?\d+)\)')
_KNOWN_BUC = re.compile(r'^(?:an?|the|\d+) (blessed|uncursed|cursed)\b')


def active(agent):
    return bool(getattr(agent, '_ascension_wish_active', False))


def _name(item):
    return item.object.name if item.is_unambiguous() else None


def beatitude(item):
    # ItemManager rewrites UNKNOWN to UNCURSED: the enum is not evidence.
    match = _KNOWN_BUC.match(item.text or '')
    return match.group(1) if match else None


def charges(item):
    match = _CHARGES.search(item.text or '')
    return tuple(map(int, match.groups())) if match else None


def _items(agent, ready=False):
    return list(agent.inventory.items) if ready else list(flatten_items(agent.inventory.items))


def _find(agent, name, category=None, ready=False):
    return next((i for i in _items(agent, ready) if _name(i) == name and
                 (category is None or i.category == category)), None)


def _has(agent, names):
    return any(_name(i) in names for i in _items(agent))


def _level(agent):
    return int(agent.last_observation['blstats'][nh.NLE_BL_XP])


def choose(agent, purpose=None):
    """Pure selection: ownership is checked again after every granted wish.

    Requests for two/three items may grant fewer; no counts, enchantments or BUC
    are assumed. XL14 only removes the Quest's level barrier, not its alignment
    requirement. Equipment in a container still avoids duplicate wishes.
    """
    if not _has(agent, MR_NAMES):
        return MR_CLOAK if _has(agent, {'silver dragon scale mail', 'silver dragon scales'}) else GDSM

    wand = _find(agent, 'wishing', nh.WAND_CLASS, ready=True)
    recharge = _find(agent, 'charging', nh.SCROLL_CLASS, ready=True)
    identify = _find(agent, 'identify', nh.SCROLL_CLASS, ready=True)
    state = charges(wand) if wand is not None else None
    if wand is not None:
        # Identify an unknown history before budgeting a recharge. With a fresh
        # Castle wand this follows the first armor wish while two charges remain.
        if state is None and identify is None:
            return IDENTIFY
        if state is not None and state[0] == 0:
            if recharge is None:
                # Keep an identify scroll for the wished charging scroll's BUC.
                # With two charges left, both requests fit before exhaustion.
                if state[1] > 1 and identify is None:
                    return IDENTIFY
                return CHARGING
            if beatitude(recharge) is None and identify is None:
                return IDENTIFY

    if not _has(agent, REFLECTION_NAMES):
        weapon = getattr(agent.inventory.items, 'main_hand', None)
        two_handed = weapon is not None and weapon.is_unambiguous() and getattr(weapon.object, 'bi', False)
        return REFLECTION_AMULET if two_handed else REFLECTION
    # The Castle moat can stop an otherwise healthy hero indefinitely. Secure
    # its reusable crossing before optional speed or a one-time extra life.
    if _find(agent, 'levitation', nh.RING_CLASS) is None:
        return LEVITATION
    if not _has(agent, {'speed boots'}):
        return SPEED
    # A reflection amulet cannot share its slot with life saving.
    other_reflection = _has(agent, REFLECTION_NAMES - {'amulet of reflection'})
    if other_reflection and not _has(agent, {'amulet of life saving'}):
        return LIFE_SAVING
    if (agent.character.role == Character.VALKYRIE and _level(agent) < 14 and
            _find(agent, 'gain level', nh.POTION_CLASS) is None):
        return GAIN_LEVEL
    if not _has(agent, {'unicorn horn'}):
        return HORN
    # Identification also reveals wished potion BUC before using it.
    if identify is None and identification_targets(agent):
        return IDENTIFY
    return FULL_HEALING


def begin(agent, purpose=None):
    agent._ascension_wish_active = True
    return choose(agent, purpose)


def armor_priority(agent, item):
    if not active(agent):
        return 0
    name = _name(item)
    return 100 if name in MR_NAMES else 80 if name in REFLECTION_NAMES else 60 if name == 'speed boots' else 0


def keep(agent, item):
    if not active(agent) or not item.is_unambiguous():
        return False
    return item.object in WISH_OBJECTS.values() or (item.category == nh.WAND_CLASS and _name(item) == 'wishing')


def identification_targets(agent):
    """Ready items where identification unlocks a safe, useful action."""
    wand = _find(agent, 'wishing', nh.WAND_CLASS, ready=True)
    result = [wand] if wand is not None and charges(wand) is None else []
    for item in _items(agent, ready=True):
        if (item.category == nh.SCROLL_CLASS and _name(item) == 'charging' or
                item.category == nh.POTION_CLASS and _name(item) == 'gain level') and beatitude(item) is None:
            result.append(item)
    return result


def recharge_plan(agent):
    """Only an explicitly unrecharged, empty wand and known noncursed scroll."""
    if not active(agent):
        return None
    wand = next((i for i in _items(agent, True) if i.category == nh.WAND_CLASS and
                 _name(i) == 'wishing' and charges(i) == (0, 0)), None)
    scrolls = [i for i in _items(agent, True) if i.category == nh.SCROLL_CLASS and
               _name(i) == 'charging' and beatitude(i) in ('blessed', 'uncursed')]
    if wand is None or not scrolls:
        return None
    scrolls.sort(key=lambda i: beatitude(i) != 'blessed')
    return wand, scrolls[0]


def wrest_plan(agent):
    """A known empty, already recharged wand still has one wrestable wish.

    One normal zap per strategy invocation leaves combat/hunger preemptible.
    The 500-attempt bound gives a fresh decision every turn and avoids an
    infinite no-charge loop. Negative charges mean the final wish is spent.
    """
    if not active(agent) or int(agent.last_observation['blstats'][nh.NLE_BL_HUNGER]) >= 2:
        return None
    attempts = getattr(agent, '_ascension_wrest_attempts', {})
    for wand in _items(agent, True):
        if wand.category != nh.WAND_CLASS or _name(wand) != 'wishing' or charges(wand) != (1, 0) or \
                beatitude(wand) not in ('blessed', 'uncursed'):
            continue
        key = (agent.inventory.items.get_letter(wand), wand.text)
        if attempts.get(key, 0) < 500:
            return wand, key
    return None


def amulet_plan(agent):
    equipped = [i for i in _items(agent, True) if i.equipped]
    worn = next((i for i in equipped if i.category == nh.AMULET_CLASS), None)
    other_reflection = any(_name(i) in REFLECTION_NAMES - {'amulet of reflection'} for i in equipped)
    reflection = _find(agent, 'amulet of reflection', nh.AMULET_CLASS, ready=True)
    saving = _find(agent, 'amulet of life saving', nh.AMULET_CLASS, ready=True)
    target = reflection if not other_reflection and reflection is not None else saving
    if target is None or target.equipped:
        return None
    if worn is not None:
        return ('remove', worn) if beatitude(worn) in ('blessed', 'uncursed') else None
    return 'puton', target


def _amulet_action(agent, action, item):
    command, prompt = ((A.Command.REMOVE, 'What do you want to remove?') if action == 'remove'
                       else (A.Command.PUTON, 'What do you want to put on?'))
    letter = agent.inventory.items.get_letter(item)

    def reply():
        if prompt in agent.single_message:
            yield letter

    with agent.atom_operation():
        agent.step(command, reply())
    agent.inventory.items.update(force=True)


def _read(agent, scroll, target=None, identify_targets=()):
    letter = agent.inventory.items.get_letter(scroll)
    target_letter = agent.inventory.items.get_letter(target) if target is not None else None
    wanted = [agent.inventory.items.get_letter(i) for i in identify_targets]

    def replies():
        if 'What do you want to read?' not in agent.single_message:
            return
        yield letter
        identifying = False
        for _ in range(40):
            observation = getattr(agent, '_observation', None) or agent.last_observation
            screen = '\n'.join(bytes(row).decode().rstrip() for row in observation['tty_chars'])
            if target_letter and 'What do you want to charge?' in agent.single_message:
                yield target_letter
                return
            if 'What would you like to identify' in screen:
                identifying = True
            identify_menu = identifying and ('What would you like to identify' in screen or
                                             re.search(r'\(\d+ of \d+\)|\(end\)', screen))
            if wanted and identify_menu:
                choice = next((l for l in wanted if re.search(r'^\s*' + re.escape(l) + r' [-+] ', screen, re.M)), None)
                if choice:
                    wanted.remove(choice)
                    yield choice
                    yield '\n'
                elif '(end)' not in screen:
                    yield ' '
                else:
                    yield A.Command.ESC
                    return
            elif identify_menu:
                yield A.Command.ESC
                return
            elif observation['misc'][2]:
                yield ' '
            else:
                return

    with agent.atom_operation():
        agent.step(A.Command.READ, replies())
    agent.inventory.items.update(force=True)


@Strategy.wrap
def maintain(agent):
    """Single bounded inventory action. Never prepare equipment next to enemies."""
    if not active(agent) or agent.character.prop.polymorph or agent.hands_welded():
        yield False
        return
    conditions = int(agent.last_observation['blstats'][nh.NLE_BL_CONDITION])
    harmful = (nh.BL_MASK_STONE | nh.BL_MASK_SLIME | nh.BL_MASK_STRNGL | nh.BL_MASK_FOODPOIS |
               nh.BL_MASK_TERMILL | nh.BL_MASK_BLIND | nh.BL_MASK_STUN | nh.BL_MASK_CONF | nh.BL_MASK_HALLU)
    if conditions & harmful or agent.get_visible_monsters():
        yield False
        return
    plan = recharge_plan(agent)
    identify = _find(agent, 'identify', nh.SCROLL_CLASS, ready=True)
    targets = identification_targets(agent)
    gain = _find(agent, 'gain level', nh.POTION_CLASS, ready=True)
    gain_ok = (gain is not None and beatitude(gain) in ('blessed', 'uncursed') and
               agent.character.role == Character.VALKYRIE and _level(agent) < 14)
    amulet = amulet_plan(agent)
    wrest = wrest_plan(agent)
    operation = None
    if plan:
        operation = ('charge', *(i.text for i in plan))
    elif identify is not None and targets:
        operation = ('identify', identify.text, *(i.text for i in targets))
    elif amulet:
        operation = (amulet[0], amulet[1].text)
    elif gain_ok:
        operation = ('gain', gain.text, _level(agent))
    elif wrest:
        wand, key = wrest
        attempts = getattr(agent, '_ascension_wrest_attempts', {})
        operation = ('wrest', key, attempts.get(key, 0))
    attempted = getattr(agent, '_ascension_inventory_attempts', set())
    if operation is None or operation in attempted:
        yield False
        return
    yield True
    # A refusal, interrupted menu or failed effect cannot loop on the same
    # unchanged inventory. Successful actions change the public text or XP.
    attempted.add(operation)
    agent._ascension_inventory_attempts = attempted
    before = (tuple(i.text for i in _items(agent, True)), _level(agent))
    if plan:
        wand, scroll = plan
        old_text = wand.text
        agent.log(f'ASCENSION recharging known fresh empty wand: {old_text!r}')
        _read(agent, scroll, target=wand)
        # Remove only this wand's stale empty mark; (1:n) is still checked by
        # recharge_plan and can never be charged again.
        agent.inventory.empty_wands.discard(old_text)
    elif identify is not None and targets:
        _read(agent, identify, identify_targets=targets)
    elif amulet:
        _amulet_action(agent, *amulet)
    elif not gain_ok and wrest:
        wand, key = wrest
        attempts = getattr(agent, '_ascension_wrest_attempts', {})
        attempts[key] = attempts.get(key, 0) + 1
        agent._ascension_wrest_attempts = attempts
        agent.log(f'ASCENSION attempting last wish from known empty recharged wand ({attempts[key]}/500)')
        agent.zap(wand, None)
        agent.inventory.items.update(force=True)
    else:
        agent.inventory.quaff(gain)
    after = (tuple(i.text for i in _items(agent, True)), _level(agent))
    if after != before:
        attempted.discard(operation)
