"""The invocation ritual at a square proved by the public vibration message.

NetHack 3.6.7: hack.c invocation_message, apply.c use_candelabrum/use_bell,
spell.c deadbook, mklev.c mkinvokearea. No search for the square or acquisition
of the three unique objects is implemented here. All inputs are observations.
"""
import re

import nle.nethack as nh
from nle.nethack import actions as A

from .exceptions import AgentChangeStrategy, AgentFinished, AgentPanic

BELL = 'Bell of Opening'
BOOK = 'Book of the Dead'
CANDELABRUM = 'Candelabrum of Invocation'
NAMES = (BELL, BOOK, CANDELABRUM)
VIBRATION = re.compile(r'You feel a strange vibration (?:under your [^.]+|beneath [^.]+)\.')
CANDLES = re.compile(r'\((\d+) candles?(?: (attached)|, (lit))\)')
CURSED = re.compile(r'^(?:the|an?|\d+) cursed\b')
SUCCESS = 'You are standing at the top of a stairwell leading down!'
MAX_ATTEMPTS = 2


class InvocationRitual:
    def __init__(self, agent):
        self.agent = agent
        self.squares = set()
        self.completed = set()
        self.attempts = 0
        self.failed_kit = None
        self.reason = ''
        self.preparation_attempts = 0
        self.failed_preparations = set()

    def _position(self):
        bl = self.agent.last_observation['blstats']
        return tuple(int(bl[i]) for i in (nh.NLE_BL_DNUM, nh.NLE_BL_DLEVEL, nh.NLE_BL_Y, nh.NLE_BL_X))

    def observe(self):
        # DiveLogic.update receives the original message after the ordinary
        # inventory/terrain updates; it is paired with current public blstats.
        if self._position()[0] == 1 and VIBRATION.search(self.agent.message or ''):
            self.squares.add(self._position())

    def _kit(self):
        obs = self.agent.last_observation
        if int(obs['blstats'][nh.NLE_BL_CONDITION]) & nh.BL_MASK_HALLU:
            return {}
        kit = {}
        # These three object types have fixed, unique appearances. Match the
        # raw public glyph, not a user-supplied name or parser inference.
        for letter, glyph, row in zip(obs['inv_letters'], obs['inv_glyphs'], obs['inv_strs']):
            if not letter or not nh.glyph_is_normal_object(int(glyph)):
                continue
            name = nh.objdescr.from_idx(nh.glyph_to_obj(int(glyph))).oc_name
            if name in NAMES:
                text = bytes(row).split(b'\0', 1)[0].decode()
                kit[name] = (chr(int(letter)), text)
        return kit

    @staticmethod
    def _signature(kit):
        return tuple(kit.get(name) for name in NAMES)

    @staticmethod
    def _candles(kit):
        found = CANDLES.search(kit.get(CANDELABRUM, ('', ''))[1])
        return (int(found[1]), found[3] == 'lit') if found else (0, False)

    def _safe(self):
        bl = self.agent.last_observation['blstats']
        bad = (nh.BL_MASK_BLIND | nh.BL_MASK_CONF | nh.BL_MASK_STUN | nh.BL_MASK_HALLU |
               nh.BL_MASK_STONE | nh.BL_MASK_SLIME | nh.BL_MASK_STRNGL |
               nh.BL_MASK_TERMILL | nh.BL_MASK_FOODPOIS)
        return not (int(bl[nh.NLE_BL_CONDITION]) & bad) and \
            int(bl[nh.NLE_BL_HP]) >= max(15, .45 * int(bl[nh.NLE_BL_HPMAX]))

    def prepare(self):
        """Attach actually carried candles, without lighting them prematurely."""
        kit = self._kit()
        if CANDELABRUM not in kit or self._candles(kit)[0] >= 7 or \
                self.preparation_attempts >= 9 or not self._safe():
            return False
        # Unlike the ritual, attaching candles does not depend on the candle
        # beatitude (apply.c use_candle); unknown BUC need not waste an identify.
        obs = self.agent.last_observation
        candidates = []
        for letter, glyph, row in zip(obs['inv_letters'], obs['inv_glyphs'], obs['inv_strs']):
            if not letter or not nh.glyph_is_normal_object(int(glyph)):
                continue
            name = nh.objdescr.from_idx(nh.glyph_to_obj(int(glyph))).oc_name
            text = bytes(row).split(b'\0', 1)[0].decode()
            if name in ('wax candle', 'tallow candle') and 'unpaid' not in text:
                candidates.append((chr(int(letter)), text))
        for letter, text in candidates:
            signature = (kit[CANDELABRUM], letter, text)
            if signature in self.failed_preparations:
                continue
            self.preparation_attempts += 1
            self.failed_preparations.add(signature)
            before = self._candles(kit)[0]

            def responses():
                if 'What do you want to use or apply?' in self.agent.single_message:
                    yield letter
                prompt = self.agent.single_message.lower()
                if prompt.startswith('attach ') and 'candelabrum' in prompt:
                    yield 'y'

            with self.agent.atom_operation():
                self.agent.step(A.Command.APPLY, responses())
            after = self._candles(self._kit())[0]
            self.agent.log(f'INVOCATION candle attachment observed {before} -> {after}')
            return True
        return False

    def ready(self):
        pos = self._position()
        if pos[0] != 1 or pos not in self.squares or pos in self.completed or \
                self.attempts >= MAX_ATTEMPTS or not self._safe():
            return False
        kit = self._kit()
        if len(kit) != 3 or self._candles(kit)[0] != 7 or \
                any(CURSED.search(text) for _, text in kit.values()):
            return False
        # A known-empty Bell cannot perform the ritual. Unknown charges are
        # allowed only as a single tested attempt, confirmed by its sound.
        if re.search(r'\(\d+:0\)', kit[BELL][1]):
            return False
        return self._signature(kit) != self.failed_kit

    def _use(self, command, letter, prompt):
        answered = [False]

        def response():
            if prompt in self.agent.single_message:
                answered[0] = True
                yield letter

        self.agent.step(command, response())
        return answered[0], self.agent.message or ''

    def _fail(self, reason):
        self.reason = reason
        self.failed_kit = self._signature(self._kit())
        self.agent.log('INVOCATION stopped: ' + reason)
        return True

    def perform(self):
        if not self.ready():
            return False
        self.attempts += 1
        origin = self._position()
        # Record the attempt before any command/callback can interrupt it.
        self.failed_kit = self._signature(self._kit())
        try:
            with self.agent.atom_operation():
                kit = self._kit()
                if not self._candles(kit)[1]:
                    answered, _ = self._use(A.Command.APPLY, kit[CANDELABRUM][0],
                                           'What do you want to use or apply?')
                    kit = self._kit()
                    if not answered or self._candles(kit) != (7, True):
                        return self._fail('seven candles did not light')
                if self._position() != origin or not self._safe():
                    return self._fail('position or condition changed before ringing')
                bell_turn = int(self.agent.last_observation['blstats'][nh.NLE_BL_TIME])
                answered, message = self._use(A.Command.APPLY, kit[BELL][0],
                                              'What do you want to use or apply?')
                if not answered or 'an unsettling shrill sound' not in message:
                    return self._fail('Bell did not produce the invocation sound')
                # use_bell stores its age before consuming this action's turn.
                # Requiring <4 elapsed turns since the command began is stricter
                # than deadbook's (moves-age)<5 even at slow speed.
                kit = self._kit()
                if self._position() != origin or not self._safe() or len(kit) != 3 or \
                        self._candles(kit) != (7, True) or \
                        any(CURSED.search(text) for _, text in kit.values()):
                    return self._fail('ritual prerequisites changed after ringing')
                if int(self.agent.last_observation['blstats'][nh.NLE_BL_TIME]) - bell_turn >= 4:
                    return self._fail('Bell sound expired')
                answered, message = self._use(A.Command.READ, kit[BOOK][0], 'What do you want to read?')
                if not answered or SUCCESS not in message:
                    return self._fail('reading did not reveal the Sanctum staircase')
                self.completed.add(origin)
                self.reason = 'Sanctum staircase appeared'
                self.agent.log('INVOCATION confirmed: Sanctum staircase appeared')
                # The avatar hides terrain. Cache only the staircase explicitly
                # reported by the game so the existing dive can descend it.
                from .glyph import SS
                self.agent.current_level().objects[origin[2], origin[3]] = SS.S_dnstair
            return True
        except (AgentChangeStrategy, AgentFinished):
            raise
        except AgentPanic:
            self._fail('command interrupted by policy recovery')
            raise
        except Exception as exc:
            self._fail('command protocol failed: ' + type(exc).__name__)
            raise AgentPanic('invocation command failed') from exc
