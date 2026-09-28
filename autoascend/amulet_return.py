"""Carry the observed real Amulet up the main dungeon to the Plane of Earth.

Only ordinary mapped stairs, public inventory glyphs and game prompts are used.
Combat and emergency preemption remain with the surrounding strategy. This is
the return through the main dungeon, not a solution to the elemental planes.
"""
import numpy as np
from nle.nethack import actions as A

from .glyph import G


class AmuletReturn:
    def __init__(self, agent):
        self.agent = agent
        self.refused = {}
        self.branch_exits = {}

    def active(self):
        level = self.agent.current_level()
        return (level.dungeon_number in (0, 1) or level.key() in self.branch_exits) and \
            self.agent.global_logic.astral.amulet() is not None

    def _stairs(self):
        agent = self.agent
        level = agent.current_level()
        coords = {tuple(map(int, pos)) for pos in zip(*np.isin(
            level.objects, list(G.STAIR_UP)).nonzero())}
        # A hero or object can cover the stair glyph. The agent records the
        # connection when it actually traverses it; this is ordinary map memory.
        for pos, destination in level.stair_destination.items():
            if destination is None:
                continue
            dnum, dlevel = destination[0]
            if dnum not in (0, 1, 7, 1000):
                # E.g. a known upstairs branch into Sokoban or Vlad's Tower
                # makes no upward progress along the route to the surface.
                coords.discard(pos)
                continue
            if (dnum == level.dungeon_number and dlevel < level.level_number) or \
                    (level.dungeon_number == 1 and dnum == 0) or \
                    (level.key() == (0, 1) and dnum in (7, 1000)):
                coords.add(pos)
        if level.key() in self.branch_exits:
            # We entered this branch through a previously unknown upstairs.
            # Its reciprocal downstairs is the actual observed arrival cell.
            coords = {self.branch_exits[level.key()]}
        distances = agent.bfs()
        return sorted((int(distances[pos]), pos) for pos in coords
                      if distances[pos] >= 0 and
                      self.refused.get((level.key(), pos), -1) <= agent.blstats.time)

    def _climb(self):
        agent = self.agent
        if not self.active():
            return False
        level = agent.current_level()
        pos = (agent.blstats.y, agent.blstats.x)
        if pos not in {p for _, p in self._stairs()}:
            return False
        before = level.key()
        command = A.MiscDirection.DOWN if before in self.branch_exits else A.MiscDirection.UP

        def answers():
            # Without a real Amulet this prompt would end the game by escape.
            # Recheck the inventory at the actual confirmation boundary.
            if 'Beware, there will be no return!' in agent.single_message and \
                    'Still climb?' in agent.single_message:
                yield 'y' if before == (0, 1) and self.active() else 'n'

        agent.log(f'AMULET RETURN taking mapped stairs on {before}')
        with agent.atom_operation():
            agent.step(command, answers())
        after = agent.current_level().key()
        if after != before and 'A mysterious force' not in agent.message:
            arrived = (agent.blstats.y, agent.blstats.x)
            level.stair_destination[pos] = (after, arrived)
            if before[0] in (0, 1) and after[0] not in (0, 1, 7):
                self.branch_exits[after] = arrived
        if after == before:
            # A held hero, excessive burden, pet, or mysterious force can deny
            # the move. Replan instead of issuing an unbounded prompt loop.
            self.refused[(before, pos)] = agent.blstats.time + 10
        return True

    def plan_step(self):
        if not self.active():
            return False
        agent = self.agent
        targets = self._stairs()
        if targets:
            pos = targets[0][1]
            if pos == (agent.blstats.y, agent.blstats.x):
                self._climb()
            else:
                agent.go_to(*pos, max_steps=40)
            return True
        # The earlier dive often dug past these stairs. Discover them through
        # the existing door/search movement policy, never dig deeper here.
        start = agent.blstats.time
        agent.global_logic.exploration_strategy(None).until(
            agent, lambda: not self.active() or bool(self._stairs()) or
            agent.blstats.time - start >= 100).run()
        return True
