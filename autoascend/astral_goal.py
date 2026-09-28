"""Astral altar selection and the final offering, using public observations.

This implements the last stage only. It does not obtain the Amulet or imply
that the preceding quest, invocation, and elemental-plane stages are solved.
"""
import re

import nle.nethack as nh
from nle.nethack import actions as A

from .character import Character
from .glyph import G
from .strategy import Strategy


class AstralGoal:
    PLANES = 7
    ASTRAL = 1

    def __init__(self, agent):
        self.agent = agent
        self.unreadable = {}
        self.offered = set()

    def amulet(self):
        # In NLE the raw public inventory glyphs distinguish these two fixed
        # object types, although their displayed text can be identical and the
        # inherited ItemManager incorrectly narrows both names to the real one.
        # Do not use its inferred item.glyphs or hallucinated observations.
        obs = self.agent.last_observation
        if int(obs['blstats'][nh.NLE_BL_CONDITION]) & nh.BL_MASK_HALLU:
            return None
        raw = {chr(int(letter)): int(glyph) for letter, glyph in
               zip(obs['inv_letters'], obs['inv_glyphs']) if letter}

        def real(item):
            glyph = raw.get(self.agent.inventory.items.get_letter(item))
            return glyph is not None and nh.glyph_is_normal_object(glyph) and \
                nh.objdescr.from_idx(nh.glyph_to_obj(glyph)).oc_name == 'Amulet of Yendor'

        return next((item for item in self.agent.inventory.items
                     if real(item) and
                     (self.agent.inventory.items.get_letter(item), item.text) not in self.offered), None)

    def active(self):
        level = self.agent.current_level()
        return (level.dungeon_number, level.level_number) == (self.PLANES, self.ASTRAL) and \
            self.amulet() is not None

    def _pos(self):
        return (self.agent.blstats.y, self.agent.blstats.x)

    def _aligned(self, pos):
        alignment = self.agent.current_level().altars.get(pos, Character.UNKNOWN)
        return alignment != Character.UNKNOWN and alignment == self._alignment()

    def _alignment(self):
        # Character.alignment caches the starting identity. A helm of opposite
        # alignment can change the live value, which blstats reports directly.
        return {-1: Character.CHAOTIC, 0: Character.NEUTRAL, 1: Character.LAWFUL}.get(
            self.agent.blstats.alignment, Character.UNKNOWN)

    def _inspect_altar(self):
        agent = self.agent
        pos = self._pos()
        with agent.atom_operation():
            agent.step(A.Command.LOOK)
        text = ' '.join([agent.message or '', *(agent.popup or [])])
        match = re.search(r'(?:high )?altar to [^\n()]+ \((lawful|neutral|chaotic|unaligned)\)', text)
        if match:
            agent.current_level().altars[pos] = Character.name_to_alignment[match.group(1)]
            return True
        # Do not spend every action LOOKing at stale or obscured terrain.
        self.unreadable[pos] = agent.blstats.time + 50
        return False

    def _offer(self):
        agent = self.agent
        item = self.amulet()
        if item is None or not self.active() or not self._aligned(self._pos()):
            return False
        letter = agent.inventory.items.get_letter(item)
        answered = [False]

        def answer():
            if 'What do you want to sacrifice?' in agent.single_message:
                answered[0] = True
                yield letter

        agent.log('ASCENSION offering the real Amulet on a confirmed coaligned Astral altar')
        with agent.atom_operation():
            agent.step(A.Command.OFFER, answer())
        if answered[0]:
            self.offered.add((letter, item.text))
        return True

    @Strategy.wrap
    def winning_offer(self):
        # This one action takes priority even over emergency healing: a
        # correctly aligned real-Amulet offering ends the game immediately.
        if not self.active() or not self._aligned(self._pos()):
            yield False
            return
        yield True
        self._offer()

    def _targets(self):
        agent = self.agent
        dis = agent.bfs()
        targets = []
        for pos, alignment in agent.current_level().altars.items():
            if alignment not in (Character.UNKNOWN, self._alignment()):
                continue
            if self.unreadable.get(pos, -1) > agent.blstats.time:
                continue
            if dis[pos] >= 0:
                targets.append((alignment == Character.UNKNOWN, int(dis[pos]), pos))
        return sorted(targets)

    def plan_step(self):
        agent = self.agent
        if not self.active():
            return False
        pos = self._pos()
        level = agent.current_level()
        if self._aligned(pos):
            return self._offer()
        if (pos in level.altars or level.objects[pos] in G.ALTAR) and \
                level.altars.get(pos, Character.UNKNOWN) == Character.UNKNOWN and \
                self.unreadable.get(pos, -1) <= agent.blstats.time:
            self._inspect_altar()
            return True
        targets = self._targets()
        if targets:
            agent.go_to(*targets[0][2])
            return True
        # Existing movement and combat handle doors, priests, and hostile
        # monsters. Search until another eligible altar is reachable.
        agent.global_logic.exploration_strategy(None).until(
            agent, lambda: bool(self._targets())).run()
        return True
