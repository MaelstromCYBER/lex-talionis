#! usr/bin/env python2.7

"""
# AI Documentation:
# AI State 1 handles the action AI
# AI State 2 handles the movement AI, if action AI fails
# Possible States for AI1:
    - 0: Nothing
    - 1: Move and Attack
    - 2: Attack
    - 3: Move and Attack and Village/HP
    - 4: Move and Chests/Doors (Locked)
    - 5: Move and Escape
    - 6: Move and ThiefEscape
    - 7: Move and Attack and ThiefEscape
# Possible States for AI2:
    - 0: Do not move
    - 1: Move towards opponents
    - 2: Move towards allies
    - 3: move towards unlooted and unclosed villages or HP
    - 4: move towards unlooted and unopened chests/doors
    - 5: move towards escape tiles
    - 6: move towards thief escape tiles
    - 7: move towards boss unit
    - A string: move towards unit whose name or event_id matches string
# Possible States for view_range (secondary AI):
    - 0: Do not look
    - 1: Look up to my Movement*2 + maximum range of item away
    - 2: Look at entire map
"""
import GlobalConstants as GC
import configuration as cf
import UnitObject, Interaction, Dialogue, Utility, AStar, Engine

import logging
logger = logging.getLogger(__name__)
 
# whether to have the AI actually test move to a position
# allows for it to recognize the effects of auras, tile statuses, etc.
# Slower by about ~2.5x
QUICK_MOVE = True

class AI(object):
    def __init__(self, unit, ai1=0, ai2=0, team_ignore=[], name_ignore=[],
                 view_range=1, ai_priority=20, ai_group=0):
        self.unit = unit
        self.ai1_state = 0
        self.ai2_state = 0
        self.change_ai(ai1, ai2)

        self.team_ignore = team_ignore
        self.name_ignore = name_ignore
        self.ai_group = ai_group
        self.ai_group_flag = False

        self.did_something = False

        self.state = 'Init'

        self.range = view_range # (0, 1, 2)
        self.priority = ai_priority # higher moves first

        # Commands
        self.clean_up()

    def clean_up(self):
        self.position_to_move_to = None
        self.item_to_use = None
        self.target_to_interact_with = None
        self.inner_ai = None
        self.valid_moves = set()
        self.available_targets = []

    def change_ai(self, ai1, ai2):
        logger.debug('AI Change. From %s %s to %s %s', self.ai1_state, self.ai2_state, ai1, ai2)
        self.ai1_state = ai1
        self.ai2_state = ai2

    def get_true_valid_moves(self, gameStateObj):
        valid_moves = self.unit.getValidMoves(gameStateObj)
        # Make sure we don't move on top of another unit... getValidMoves returns positions coincident with allied units
        other_unit_positions = {unit.position for unit in gameStateObj.allunits if unit.position and unit is not self.unit}
        return valid_moves - other_unit_positions

    # Now a state machine
    def think(self, gameStateObj):
        success = False
        self.did_something = False
        time1 = Engine.get_time()
        orig_pos = self.unit.position

        # Can do more than one pass through if it doesn't take much time (half of a frame)
        logger.debug('AI Thinking...')
        while Engine.get_true_time() - time1 < GC.FRAMERATE/2:
            logger.debug('Current State: %s', self.state)

            if self.state == 'Init':
                self.start_time = Engine.get_time()
                logger.debug('Starting AI with name: %s, position: %s, class: %s, AI1: %s, AI2 %s, Range: %s', 
                             self.unit.name, self.unit.position, self.unit.klass, self.ai1_state, self.ai2_state, self.range)
                self.clean_up()
                if self.ai1_state == 2:
                    self.valid_moves = {self.unit.position}
                elif self.ai1_state != 0: 
                    self.valid_moves = self.get_true_valid_moves(gameStateObj)
                self.state = 'Steal'

            elif self.state == 'Steal':
                if self.ai1_state not in (0, 5, 6) and 'steal' in self.unit.status_bundle and len(self.unit.items) < cf.CONSTANTS['max_items']:
                    success = self.run_steal_ai(gameStateObj, self.valid_moves)
                self.state = 'Attack_Init'

            elif self.state == 'Attack_Init':
                if self.ai1_state not in (0, 4, 5, 6):
                    self.inner_ai = Primary_AI(self.unit, self.valid_moves, self.team_ignore, self.name_ignore, gameStateObj)
                    if self.inner_ai.skip_flag:
                        self.state = 'Loot'
                    else:
                        self.state = 'Attack'
                else:
                    self.state = 'Loot'

            elif self.state == 'Attack':
                done, self.target_to_interact_with, self.position_to_move_to, self.item_to_use = self.inner_ai.run(gameStateObj)
                if done:
                    if self.target_to_interact_with:
                        self.ai_group_ping(gameStateObj)
                        success = True
                    self.state = 'Loot'
            
            elif self.state == 'Loot':
                if self.ai1_state in (3, 4, 5, 6, 7):
                    success = self.run_loot_ai(gameStateObj, self.valid_moves)
                self.state = 'Secondary_Init'

            elif self.state == 'Secondary_Init':
                if self.ai2_state == 0:
                    self.available_targets = []
                elif self.ai2_state == 1:
                    self.available_targets = [unit for unit in gameStateObj.allunits if unit.position and self.unit.checkIfEnemy(unit) and 
                                              unit.team not in self.team_ignore and unit.name not in self.name_ignore]
                elif self.ai2_state == 2:
                    self.available_targets = [unit for unit in gameStateObj.allunits if unit.position and self.unit.checkIfAlly(unit) and
                                              unit is not self.unit and unit.team not in self.team_ignore and unit.name not in self.name_ignore]
                elif self.ai2_state == 3:
                    self.available_targets = [tile for position, tile in gameStateObj.map.tiles.iteritems()
                                              if 'Village' in gameStateObj.map.tile_info_dict[position] or
                                              'HP' in gameStateObj.map.tile_info_dict[position]]
                elif self.ai2_state == 4: 
                    self.available_targets = [tile for position, tile in gameStateObj.map.tiles.iteritems()
                                              if 'Locked' in gameStateObj.map.tile_info_dict[position]]
                elif self.ai2_state == 5:
                    self.available_targets = [tile for position, tile in gameStateObj.map.tiles.iteritems() 
                                              if 'Escape' in gameStateObj.map.tile_info_dict[position]]
                elif self.ai2_state == 6:
                    self.available_targets = [tile for position, tile in gameStateObj.map.tiles.iteritems()
                                              if 'ThiefEscape' in gameStateObj.map.tile_info_dict[position]]
                elif self.ai2_state == 7:
                    self.available_targets = [unit for unit in gameStateObj.allunits if unit.position and 'Boss' in unit.tags and
                                              unit.team not in self.team_ignore and unit.name not in self.name_ignore]
                else:
                    self.available_targets = [unit for unit in gameStateObj.allunits if unit.position and
                                              (unit.name == self.ai2_state or unit.event_id == self.ai2_state)]

                self.inner_ai = Secondary_AI(self.available_targets, self.unit, self.range, gameStateObj)
                self.state = 'Secondary'

            elif self.state == 'Secondary':
                if self.inner_ai.update(gameStateObj):
                    self.position_to_move_to = self.inner_ai.position_to_move_to
                    self.inner_ai = None
                    if self.position_to_move_to:
                        self.ai_group_ping(gameStateObj)
                        success = True
                    self.state = 'Tertiary'

            elif self.state == 'Tertiary':
                # Filter using range
                if self.range == 0 or self.range == 1:
                    self.available_targets = []
                success = self.run_tertiary_ai(self.valid_moves, self.available_targets, gameStateObj)
                self.state = 'Done'

            # if cf.OPTIONS['debug']: print('AI Time Taken:', Engine.get_time() - time1)

            if success or self.state == 'Done':
                # print('AI Time Taken:', Engine.get_time() - self.start_time)
                self.did_something = success
                self.state = 'Init'
                return True
        if QUICK_MOVE:
            self.quick_move(orig_pos, gameStateObj, test=True) # Return back to original position so that the in-between frames aren't weird
        return False

    def act(self, gameStateObj):
        logger.debug('AI Act!')
        if not self.unit.hasRunMoveAI:
            if self.think(gameStateObj):
                self.move(gameStateObj)
                self.unit.hasRunMoveAI = True
        elif not self.unit.hasRunAttackAI and self.unit.hasRunMoveAI:
            self.attack(gameStateObj)
            self.unit.hasRunAttackAI = True
            # If unit does not have canto plus, we're done
            if not self.unit.has_canto_plus():
                self.unit.hasRunGeneralAI = True
        elif self.unit.hasRunMoveAI and self.unit.hasRunAttackAI and not self.unit.hasRunGeneralAI and self.unit.has_canto_plus():
            if self.unit.hasAttacked:
                self.canto_retreat(gameStateObj)
                self.move(gameStateObj)
            self.unit.hasRunGeneralAI = True

        return self.did_something

    def move(self, gameStateObj):
        # Acts only if a unit has a position to move to
        if self.position_to_move_to:
            path = self.unit.getPath(gameStateObj, self.position_to_move_to)
            if self.unit.hasAttacked: # If we've already attacked, we're done.
                self.unit.wait(gameStateObj)
            gameStateObj.stateMachine.changeState('movement')
            self.unit.beginMovement(gameStateObj, path)
            return True
        else:
            return False

    def attack(self, gameStateObj):
        if self.target_to_interact_with:
            if self.item_to_use:
                if self.item_to_use in self.unit.items:
                    self.unit.equip(self.item_to_use)
                    if self.item_to_use.weapon or self.item_to_use.spell:
                        self.unit.displaySingleAttack(gameStateObj, self.target_to_interact_with, self.item_to_use)
                    defender, splash = Interaction.convert_positions(gameStateObj, self.unit, self.unit.position, self.target_to_interact_with, self.item_to_use)
                    # print('AI', self.unit, defender, self.unit.position, defender.position)
                    gameStateObj.combatInstance = Interaction.start_combat(gameStateObj, self.unit, defender, self.target_to_interact_with, splash, self.item_to_use, ai_combat=True)
                    gameStateObj.stateMachine.changeState('combat')
                    if isinstance(defender, UnitObject.UnitObject) and self.unit.checkIfEnemy(defender):
                        self.unit.handle_fight_quote(defender, gameStateObj)
                elif 'steal' in self.unit.status_bundle:
                    unit = gameStateObj.get_unit_from_pos(self.target_to_interact_with)
                    unit.remove_item(self.item_to_use)
                    self.unit.add_item(self.item_to_use)
                    # Make most recently acquired item droppable
                    if self.unit.team != 'player':
                        for item in self.unit.items:
                            item.droppable = False
                        self.item_to_use.droppable = True
                    self.unit.handle_steal_banner(self.item_to_use, gameStateObj)
            else:
                if 'Village' in gameStateObj.map.tile_info_dict[self.target_to_interact_with]:
                    gameStateObj.map.destroy(gameStateObj.map.tiles[self.target_to_interact_with], gameStateObj)
                elif 'Locked' in gameStateObj.map.tile_info_dict[self.target_to_interact_with]:
                    locked_num = gameStateObj.map.tile_info_dict[self.target_to_interact_with]['Locked']
                    script_name = 'Data/Level' + str(gameStateObj.counters['level']) + '/unlockScript.txt'
                    unlock_script = Dialogue.Dialogue_Scene(script_name, self.unit, locked_num, self.target_to_interact_with)
                    gameStateObj.message.append(unlock_script)
                    gameStateObj.stateMachine.changeState('dialogue')
                elif 'Escape' or 'ThiefEscape' in gameStateObj.map.tile_info_dict[self.target_to_interact_with]:
                    if self.unit.position != self.target_to_interact_with:
                        return # Didn't actually reach ThiefEscape point
                    self.unit.escape(gameStateObj)

    def quick_move(self, move, gameStateObj, test=False):
        self.unit.leave(gameStateObj, serializing=test)
        self.unit.position = move
        self.unit.arrive(gameStateObj, serializing=test)

    def ai_group_ping(self, gameStateObj):
        # Notify others in my group that I am onto somebody...
        # Tells others in group to increase view range.
        if self.ai_group and not self.ai_group_flag:
            self.unit.notify_others_in_group(gameStateObj)
            self.ai_group_flag = True

    def canto_retreat(self, gameStateObj):
        logger.debug('Determining canto: my position %s', self.unit.position)
        valid_positions = self.get_true_valid_moves(gameStateObj)
        self.position_to_move_to = Utility.farthest_away_pos(self.unit, valid_positions, gameStateObj.allunits)

    def check_mount(self, gameStateObj):
        if not self.unit.my_mount:
            adj_position = self.unit.getAdjacentPositions(gameStateObj)
            ally_units = [unit for unit in gameStateObj.allunits if unit.position and self.unit.checkIfAlly(unit) and unit.position in adj_position]
            for adjunit in ally_units:
                if 'Mount' in unit.tags:
                    self.unit.mount(unit, gameStateObj)

    def check_dismount(self, gameStateObj):
        """Determines if unit should dismount from land-based mount to traverse water"""
        if self.unit.my_mount and 'fleet_of_foot' not in self.unit.status_bundle:
            adjtiles = self.unit.getAdjacentTiles(gameStateObj)
            # Determine which tile is closest to target
            closest_tile = sorted(adjtiles, key=lambda pos: Utility.calculate_distance(self.target_to_interact_with, pos.position))[0]
            if closest_tile.name in ['River', 'Coast', 'Bank', 'Floor']:
                self.unit.dismount(closest_tile.position, gameStateObj)
            elif all(adjtile.name in ['Floor', 'Throne', 'Wall'] for adjtile in adjtiles):
                self.unit.dismount(closest_tile.position, gameStateObj)

    # === STEAL AI ===
    def run_steal_ai(self, gameStateObj, valid_moves):
        max_tp = 0
        for move in valid_moves:
            if isinstance(self.team_ignore, int):
                self.team_ignore = [self.team_ignore]
            valid_targets = [unit for unit in self.unit.getStealTargets(gameStateObj, move) if self.unit.checkIfEnemy(unit) and
                             unit.team not in self.team_ignore and unit.name not in self.name_ignore]
            for target in valid_targets:
                for item in target.getStealables():
                    tp = (item.value * item.uses.uses) if item.uses else item.value 
                    if tp > max_tp:
                        self.target_to_interact_with = target.position
                        self.position_to_move_to = move
                        self.item_to_use = item
                        max_tp = tp

        if max_tp > 0:
            # If we've stolen everything possible, escape time -- team ignore is used to set limit
            if len(self.unit.items) >= cf.CONSTANTS['max_items'] or \
                    (self.team_ignore and len(self.unit.items) >= self.team_ignore[0]):
                self.change_ai(6, 6)
            return True
        return False

    # === LOOT AI ===
    def run_loot_ai(self, gameStateObj, valid_moves):
        if self.ai1_state == 3: # Village/HP terrain
            available_targets = [tile for position, tile in gameStateObj.map.tiles.iteritems()
                                 if 'Village' in gameStateObj.map.tile_info_dict[position] or
                                 'HP' in gameStateObj.map.tile_info_dict[position]]
            if not available_targets:
                self.change_ai(1, 1)
        elif self.ai1_state == 4: # Chests/Doors
            available_targets = [tile for position, tile in gameStateObj.map.tiles.iteritems()
                                 if 'Locked' in gameStateObj.map.tile_info_dict[position]]
            if not available_targets or len(self.unit.items) >= cf.CONSTANTS['max_items'] \
               and (not self.team_ignore or len(self.unit.items) >= self.team_ignore[0]): # Leave
                self.change_ai(6, 6)
        elif self.ai1_state == 5: # Escape
            available_targets = [tile for position, tile in gameStateObj.map.tiles.iteritems()
                                 if 'Escape' in gameStateObj.map.tile_info_dict[position]]
        if self.ai1_state in [6, 7]: # ThiefEscape
            available_targets = [tile for position, tile in gameStateObj.map.tiles.iteritems()
                                 if 'ThiefEscape' in gameStateObj.map.tile_info_dict[position]]
            if not available_targets:
                self.change_ai(1, 1)

        for move in valid_moves:
            for target in available_targets:
                # Adjacent
                if any(pattern in gameStateObj.map.tile_info_dict[target.position] for pattern in ('Locked', 'HP')) and \
                        Utility.calculate_distance(move, target.position) == 1:
                    self.target_to_interact_with = target.position
                    self.position_to_move_to = move
                    if target.name in 'HP':
                        self.item_to_use = self.unit.getMainWeapon()
                    return True
                # On top of
                elif ('Locked' in gameStateObj.map.tile_info_dict[move] and target.name == 'Chest' or
                      any(pattern in gameStateObj.map.tile_info_dict[move] for pattern in ['Village', 'Escape', 'ThiefEscape'])) \
                        and Utility.calculate_distance(move, target.position) == 0:
                    self.target_to_interact_with = target.position
                    self.position_to_move_to = move
                    return True

    # === TERTIARY AI ===
    def run_tertiary_ai(self, valid_moves, available_targets, gameStateObj):
        """
        # If there are no legal paths to enemy units that are worth moving towards,
        # just move to the position closest to the average position of the available_targets
        """
        if valid_moves:
            avg_position = [0, 0]
            if available_targets:
                for unit in available_targets:
                    avg_position[0] += unit.position[0]
                    avg_position[1] += unit.position[1]
                avg_position[0] = avg_position[0]/len(available_targets)
                avg_position[1] = avg_position[1]/len(available_targets)
                self.position_to_move_to = sorted(valid_moves, key=lambda move: Utility.calculate_distance(avg_position, move))[0]
                return True
"""
# === ATTACK AI ===
# There are two different orderings for the Primary AI
# Choose between them by setting or resetting ATTACK_MODE

# === ATTACK AI 1 ===
# Pseudocode
# valid_moves = unit.getValidMoves()
# for move in valid_moves:
#     unit.quick_move(move)
#     for item in items:
#         targets = unit.getTargets(item, [move])
#         for target in targets:
#             tp = determine_utility(move, item, target)

# === ATTACK AI 2 ===
# This one is slightly faster... 20%?
# Pseudocode
# valid_moves = unit.getValidMoves()
# for item in items:
#     targets = unit.getTargets(item, moves)
#     for target in targets:
#         valid_moves = unit.get_valid_spots_to_attack_from(item, target)
#         for valid_move in valid_moves:
#             unit.quick_move(valid_move)
#             tp = determine_utility(valid_move, item, target)
""" 
ATTACK_MODE = True  # Determines which order to use the ATTACK AI
EQUIP = True  # Determines whether to equip the weapons you are testing or not

class Primary_AI(object):
    def __init__(self, unit, valid_moves, team_ignore, name_ignore, gameStateObj):
        self.unit = unit
        self.orig_pos = self.unit.position
        self.orig_item = self.unit.items[0] if self.unit.items else None
        self.max_tp = 0
        self.skip_flag = False
        closest_enemy_distance = self.unit.distance_to_closest_enemy(gameStateObj)

        self.items = [item for item in self.unit.items if self.unit.canWield(item) and not item.no_ai]

        # Determine if I can skip this unit's AI
        # Remove any items that only give statuses if there are no enemies nearby
        self.items = [i for i in self.items if not 
                      (i.spell and i.status and i.beneficial and not i.heal and closest_enemy_distance > self.unit.stats['MOV'] + 2)]
        # Remove any items that heal only me if I don't need healing
        if self.unit.currenthp >= self.unit.stats['HP']:
            self.items = [i for i in self.items if not (i.heal and max(i.RNG) == 0)]

        # Remove any items that heal others if there are no allies in need of healing nearby
        if any(item.heal for item in self.items):
            distance_to_heal = self.distance_to_closest_ally_in_need_of_healing(gameStateObj)
            self.items = [i for i in self.items if not (i.heal and distance_to_heal > self.unit.stats['MOV'] + max(i.RNG))]

        if self.determine_skip(gameStateObj, closest_enemy_distance):
            self.skip_flag = True
            return
        # I guess I must proceed

        # Must have determined which mode you are using by now
        self.item_index = 0

        self.valid_moves = list(valid_moves)
        self.possible_moves = []
        self.move_index = 0
        if not ATTACK_MODE and QUICK_MOVE and self.valid_moves:
            self.quick_move(self.valid_moves[self.move_index], gameStateObj, test=True)

        self.target_to_interact_with = None
        self.position_to_move_to = None
        self.item_to_use = None

        self.team_ignore = team_ignore
        self.name_ignore = name_ignore

        self.target_index = 0
        if ATTACK_MODE:
            self.get_all_valid_targets(gameStateObj)
            self.possible_moves = self.get_possible_moves(gameStateObj)
        else:
            self.get_valid_targets(gameStateObj)

    def determine_skip(self, gameStateObj, closest_enemy_distance):
        # Determine if there is really no enemies around, so just can skip
        if not self.items:
            return True
        if self.unit.currenthp < self.unit.stats['HP']:
            return False
        detrimental_items = [item for item in self.unit.items if (item.weapon or (item.spell and item.detrimental)) and self.unit.canWield(item)]
        if len(detrimental_items) == len(self.items):
            max_range = max(max(item.RNG) for item in detrimental_items) + self.unit.stats['MOV']/cf.CONSTANTS['normal_movement']
            if closest_enemy_distance > max_range:
                return True
        return False

    def distance_to_closest_ally_in_need_of_healing(self, gameStateObj):
        distance = 100
        for unit in gameStateObj.allunits:
            if unit.position and self.unit.checkIfAlly(unit) and unit.currenthp < unit.stats['HP']:
                dist = Utility.calculate_distance(unit.position, self.unit.position)
                if dist < distance:
                    distance = dist
        return distance

    def get_valid_targets(self, gameStateObj):
        if self.item_index < len(self.items) and self.move_index < len(self.valid_moves):
            move = self.valid_moves[self.move_index]
            self.valid_targets = self.unit.getTargets(gameStateObj, self.items[self.item_index], [move], 
                                                      team_ignore=self.team_ignore, name_ignore=self.name_ignore)
            if 0 in self.items[self.item_index].RNG:
                self.valid_targets.append(self.unit.position) # Hack to target self
        else:
            self.valid_targets = []

    def get_all_valid_targets(self, gameStateObj):
        self.valid_targets = self.unit.getTargets(gameStateObj, self.items[self.item_index], self.valid_moves,
                                                  team_ignore=self.team_ignore, name_ignore=self.name_ignore)
        if 0 in self.items[self.item_index].RNG:
            self.valid_targets += self.valid_moves # Hack to target self in all valid positions
            self.valid_targets = list(set(self.valid_targets))  # Only uniques
        logger.debug('Valid Targets: %s', self.valid_targets)

    def get_possible_moves(self, gameStateObj):
        # logger.debug('%s %s %s %s', self.target_index, self.valid_targets, self.item_index, self.items)
        if self.target_index < len(self.valid_targets) and self.item_index < len(self.items):
            # Given an item and a target, find all positions in valid_moves that I can strike the target at.
            a = Utility.find_manhattan_spheres(self.items[self.item_index].RNG, self.valid_targets[self.target_index])
            b = set(self.valid_moves)
            return list(a & b)
        else:
            return []

    def quick_move(self, move, gameStateObj, test=False):
        self.unit.leave(gameStateObj, serializing=test)
        self.unit.position = move
        self.unit.arrive(gameStateObj, serializing=test)

    def run(self, gameStateObj):
        if ATTACK_MODE:
            return self.run_2(gameStateObj)
        return self.run_1(gameStateObj)

    def run_1(self, gameStateObj):
        # Iterated through every move?
        if self.move_index > len(self.valid_moves) - 1:
            if QUICK_MOVE:
                self.quick_move(self.orig_pos, gameStateObj, test=True)
            if self.orig_item and EQUIP:
                self.unit.equip(self.orig_item)
            return (True, self.target_to_interact_with, self.position_to_move_to, self.item_to_use)
        # Iterated through every weapon at this move?
        elif self.item_index > len(self.items) - 1:
            self.item_index = 0
            self.move_index += 1
            # Quick move at this moment so valid_targets can include self -- normal time the quick move is used
            if QUICK_MOVE and self.move_index < len(self.valid_moves):
                self.quick_move(self.valid_moves[self.move_index], gameStateObj, test=True)
            self.get_valid_targets(gameStateObj)
        # Check if find new targets using a different move
        elif self.target_index > len(self.valid_targets) - 1:
            self.target_index = 0
            self.item_index += 1
            if self.item_index < len(self.items):
                if EQUIP:
                    self.unit.equip(self.items[self.item_index])
                self.get_valid_targets(gameStateObj)
        else:
            move = self.valid_moves[self.move_index]
            target = self.valid_targets[self.target_index]
            item = self.items[self.item_index]
            if QUICK_MOVE and self.unit.position != move:
                self.quick_move(move, gameStateObj, test=True)
            self.determine_utility(move, target, item, gameStateObj)
            self.target_index += 1

        # Not done yet
        return (False, self.target_to_interact_with, self.position_to_move_to, self.item_to_use)

    def run_2(self, gameStateObj):
        # logger.debug('%s %s %s %s %s %s', self.move_index, self.target_index, self.item_index, self.possible_moves, self.valid_targets, self.items)
        if self.item_index >= len(self.items):
            if QUICK_MOVE:
                self.quick_move(self.orig_pos, gameStateObj, test=True)
            if self.orig_item and EQUIP:
                self.unit.equip(self.orig_item)
            return (True, self.target_to_interact_with, self.position_to_move_to, self.item_to_use)
        elif self.target_index >= len(self.valid_targets):
            self.target_index = 0
            self.item_index += 1
            if self.item_index < len(self.items):
                if EQUIP:
                    self.unit.equip(self.items[self.item_index])
                self.get_all_valid_targets(gameStateObj)
                self.possible_moves = self.get_possible_moves(gameStateObj)
        elif self.move_index >= len(self.possible_moves):
            self.move_index = 0
            self.target_index += 1
            self.possible_moves = self.get_possible_moves(gameStateObj)
            # logger.debug('Possible Moves %s', self.possible_moves)
        else:
            # Only check one move for each target if using an item with ai_speed_up
            # Otherwise it spends way too long trying every possible position to strike from
            if self.items[self.item_index].ai_speed_up:
                move = Utility.farthest_away_pos(self.unit, self.possible_moves, gameStateObj.allunits)
            else:   
                move = self.possible_moves[self.move_index]
            if QUICK_MOVE and self.unit.position != move:
                self.quick_move(move, gameStateObj, test=True)
            target = self.valid_targets[self.target_index]
            item = self.items[self.item_index]
            # logger.debug('%s %s %s %s %s', self.unit.klass, self.unit.position, move, target, item)
            # Only if we have line of sight, since we get every possible position to strike from
            # Determine whether we need line of sight
            los_flag = True
            if item.spell and cf.CONSTANTS['spell_line_of_sight'] and not Utility.line_of_sight([move], [target], max(item.RNG), gameStateObj):
                los_flag = False
            elif item.weapon and cf.CONSTANTS['line_of_sight'] and not Utility.line_of_sight([move], [target], max(item.RNG), gameStateObj):
                los_flag = False
            # Actually finding the utility here
            if los_flag:
                self.determine_utility(move, target, item, gameStateObj)
            self.move_index += 1
            if item.ai_speed_up:
                self.move_index = len(self.possible_moves)

        # Not done yet
        return (False, self.target_to_interact_with, self.position_to_move_to, self.item_to_use)

    def determine_utility(self, move, target, item, gameStateObj):
        defender, splash = Interaction.convert_positions(gameStateObj, self.unit, move, target, item)
        if defender or splash:
            # if QUICK_MOVE and self.unit.position != move: # Just in case... This is needed!
            #     self.quick_move(move, gameStateObj, test=True)
            if item.spell:
                tp = self.compute_priority_spell(defender, splash, move, item, gameStateObj)
            elif item.weapon:
                tp = self.compute_priority_weapon(defender, splash, move, item, gameStateObj)
            else:
                tp = self.compute_priority_item(defender, splash, move, item, gameStateObj)
            unit = gameStateObj.get_unit_from_pos(target)
            if unit:
                name = unit.name
            else:
                name = '--'
            logger.debug("Choice %s - Weapon: %s, Position: %s, Target: %s, Target's Position: %s", tp, item.name, move, name, target)
            if tp > self.max_tp:
                self.target_to_interact_with = target
                self.position_to_move_to = move
                self.item_to_use = item
                self.max_tp = tp

    def compute_priority_weapon(self, defender, splash, move, item, gameStateObj):
        terms = []

        offensive_term = 0
        defensive_term = 1
        status_term = 0

        if defender:
            target = defender
            raw_damage = self.unit.compute_damage(target, gameStateObj, item, 'Attack')
            # Damage I do compared to targets current health
            my_damage = Utility.clamp(raw_damage/float(target.currenthp), 0, 1) # Essentially incorporates weakness into calc
            # Do I add a new status to the target
            my_status = 1 if item.status and any(s_id not in [s.id for s in target.status_effects] for s_id in item.status) else 0
            my_accuracy = Utility.clamp(self.unit.compute_hit(target, gameStateObj, item, 'Attack')/100.0, 0, 1)

            target_damage = 0
            target_accuracy = 0
            # Determine if I would be countered
            if target.getMainWeapon() and Utility.calculate_distance(move, target.position) in target.getMainWeapon().RNG:
                target_damage = Utility.clamp(target.compute_damage(self.unit, gameStateObj, target.getMainWeapon(), 'Defense')/float(self.unit.currenthp), 0, 1)
                target_accuracy = Utility.clamp(target.compute_hit(self.unit, gameStateObj, target.getMainWeapon(), 'Defense')/100.0, 0, 1)

            double = 1 if self.unit.stats['SPD'] >= target.stats['SPD'] + cf.CONSTANTS['speed_to_double'] else 0
            chance_i_kill_target_on_first = my_damage*my_accuracy if my_damage == 1 else 0

            if double and target_damage >= 1:
                double *= (1 - (target_accuracy*(1 - chance_i_kill_target_on_first))) # Chance that I actually get to double

            offensive_term += 3 if my_damage*my_accuracy >= 1 else my_damage*my_accuracy*(double+1) 
            status_term += my_status*min(1, my_accuracy*(double+1)) if my_status else 0
            defensive_term -= target_damage*target_accuracy*(1-chance_i_kill_target_on_first)

        splash = [s for s in splash if isinstance(s, UnitObject.UnitObject)]

        for target in splash:
            raw_damage = self.unit.compute_damage(target, gameStateObj, item, 'Attack')
            # Damage I do compared to targets current health
            my_damage = Utility.clamp(raw_damage/float(target.currenthp), 0, 1) # Essentially incorporates weakness into calc
            # Do I add a new status to the target
            my_status = 1 if item.status and any(s_id not in [s.id for s in target.status_effects] for s_id in item.status) else 0
            my_accuracy = Utility.clamp(self.unit.compute_hit(target, gameStateObj, item, 'Attack')/100.0, 0, 1)

            offensive_term += 3 if my_damage*my_accuracy == 1 else my_damage*my_accuracy 
            status_term += my_status*my_accuracy if my_status else 0

        # If neither of these is good, just skip it
        if not offensive_term and not status_term:
            logger.debug("Offense: %s, Defense: %s, Status: %s", offensive_term, defensive_term, status_term)
            return 0

        # How far do I have to move -- really small. Only here to break ties
        max_distance = self.unit.stats['MOV']/cf.CONSTANTS['normal_movement']
        if max_distance > 0:
            distance_term = (max_distance - Utility.calculate_distance(move, self.orig_pos))/float(max_distance)
        else:
            distance_term = 1

        logger.debug("Damage: %s, Accuracy: %s", my_damage, my_accuracy)
        logger.debug("Offense: %s, Defense: %s, Status: %s, Distance: %s", offensive_term, defensive_term, status_term, distance_term)
        terms.append((offensive_term, 50))
        terms.append((status_term, 10))
        # Defensive term is modified by offensive term so that just being hard to damage does not mean you should do useless things.
        terms.append((defensive_term*offensive_term, 40))
        terms.append((distance_term, 1))

        return Utility.process_terms(terms)

    def compute_priority_spell(self, defender, splash, move, spell, gameStateObj):
        terms = []
        closest_enemy_distance = self.unit.distance_to_closest_enemy(gameStateObj, move)

        targets = [s for s in splash if isinstance(s, UnitObject.UnitObject)]
        if defender:
            targets.insert(0, defender)

        if spell.beneficial:
            if spell.heal:
                heal_term = 0
                help_term = 0

                for target in targets:
                    if self.unit.checkIfAlly(target):
                        missing_health = target.stats['HP'] - target.currenthp
                        help_term += Utility.clamp(missing_health/float(target.stats['HP']), 0, 1)
                        spell_heal = self.unit.compute_heal(target, gameStateObj, spell, 'Attack')
                        heal_term += Utility.clamp(min(spell_heal, missing_health)/float(target.stats['HP']), 0, 1)

                logger.debug("Help: %s, Heal: %s", help_term, heal_term)
                if help_term <= 0:
                    return 0
                
                terms.append((help_term, 40))
                terms.append((heal_term, 40))

            elif spell.status:
                status_term = 0
                for target in targets:
                    if any(status_id not in [s.id for s in target.status_effects] for status_id in spell.status):
                        if (not spell.target_restrict or eval(spell.target_restrict)) and \
                           (not spell.custom_ai or eval(spell.custom_ai)):
                            status_term += eval(spell.custom_ai_value) if spell.custom_ai_value else 0.5

                logger.debug("Status: %s", status_term)
                if status_term <= 0:
                    return 0
                terms.append((status_term, 40)) # Status term

            closest_enemy_term = Utility.clamp(closest_enemy_distance/100.0, 0, 1)
            terms.append((closest_enemy_term, 10))

        else:
            offensive_term = 0
            defensive_term = 1
            status_term = 0

            for target in targets:
                raw_damage = self.unit.compute_damage(target, gameStateObj, spell)
                my_damage = Utility.clamp(raw_damage/float(target.currenthp), 0, 1)
                if spell.status and any(s_id not in [s.id for s in target.status_effects] for s_id in spell.status):
                    if (not spell.target_restrict or eval(spell.target_restrict)) and \
                       (not spell.custom_ai or eval(spell.custom_ai)):
                        my_status = eval(spell.custom_ai_value) if spell.custom_ai_value else 1
                    else:
                        my_status = 0
                else:
                    my_status = 0
                my_accuracy = Utility.clamp(self.unit.compute_hit(target, gameStateObj, spell)/100.0, 0, 1)

                if self.unit.checkIfEnemy(target):
                    offensive_term += my_damage*my_accuracy
                    status_term += my_status*my_accuracy
                else:
                    offensive_term -= my_damage*my_accuracy
                    status_term -= my_status*my_accuracy

            # If neither of these is good, just skip it
            if offensive_term <= 0 and status_term <= 0:
                logger.debug("Offense: %s, Defense: %s, Status: %s", offensive_term, defensive_term, status_term)
                return 0

            # Only here to break ties
            closest_enemy_term = Utility.clamp(closest_enemy_distance/100.0, 0, 1)
            terms.append((closest_enemy_term, 1))

            logger.debug("Offense: %s, Defense: %s, Status: %s", offensive_term, defensive_term, status_term)
            terms.append((offensive_term, 60))
            terms.append((status_term, 20))
            terms.append((defensive_term, 20)) # Set to 1 since perfectly defended

        return Utility.process_terms(terms)

    # Currently only computes utility correctly for healing items
    def compute_priority_item(self, defender, splash, move, item, gameStateObj):
        if item.heal:
            terms = []
            missing_health = defender.stats['HP'] - defender.currenthp
            if missing_health <= 0:
                return 0
            healing_term = Utility.clamp(int(eval(item.heal))/float(missing_health), 0, 1)
            help_term = Utility.clamp(missing_health/float(defender.stats['HP']), 0, 1)
            terms.append((healing_term, 10))
            terms.append((help_term, 20))

            closest_enemy_term = Utility.clamp(defender.distance_to_closest_enemy(gameStateObj, move)/100.0, 0, 1)
            terms.append((closest_enemy_term, 5))

            return Utility.process_terms(terms)/2  # Divide by two to make it less likely to make this choice
        else:
            return 0

# === SECONDARY AI ===
class Secondary_AI(object):
    def __init__(self, available_targets, unit, view_range, gameStateObj):
        self.all_targets = available_targets

        self.unit = unit
        self.range = view_range
        self.double_move = self.unit.stats['MOV']*2 + self.unit.getMaxRange()*cf.CONSTANTS['normal_movement']

        self.grid = gameStateObj.grid_manager.get_grid(self.unit)
        self.pathfinder = AStar.AStar(self.unit.position, None, self.grid, gameStateObj.map.width, gameStateObj.map.height,
                                      self.unit.team, 'pass_through' in self.unit.status_bundle)

        # Flags so we don't do things twice
        self.widen_flag = False # Determines if we've already widened our search
        self.ally_flag = False # Determines if we've already taken into account our allies' positions when determining reachable squares

        self.reset()

    def reset(self):
        self.max_tp = 0
        self.best_target = None
        self.best_path = None
        self.available_targets = [unit for unit in self.all_targets if Utility.calculate_distance(unit.position, self.unit.position) <= self.double_move]
        self.position_to_move_to = None

    def update(self, gameStateObj):
        """
        Returns True when done, False when not done.
        Parse self.position_to_move_to for output. If None, then not good output
        """
        if self.available_targets:
            target = self.available_targets.pop()
            # time1 = Engine.get_time()
            # Find a path to target
            my_path = None
            limit = self.double_move if not self.widen_flag else None
            my_path = self.getPath(target.position, gameStateObj, limit=limit)
            # We didn't find a path, or the path was longer than double move, so ignore target and continue
            if not my_path:
                logger.debug("No valid path to %s.", target.name)
                # if cf.OPTIONS['debug']: print("No valid path to this target.", target.name)
                # time2 = Engine.get_time()
                # print('No Path - Secondary AI Time', time2 - time1)
                return False
            # We found a path
            tp = self.compute_priority_secondary(target, gameStateObj, len(my_path))
            logger.debug("Path to %s. -- %s", target.name, tp)
            if tp > self.max_tp:
                self.max_tp = tp
                self.best_target = target
                self.best_path = my_path
            # time2 = Engine.get_time()
            # print('Found Path - Secondary AI Time', time2 - time1)

        elif self.best_target:
            # So we have the position I will move to.
            self.position_to_move_to = Utility.travel_algorithm(gameStateObj, self.best_path, self.unit.movement_left, self.unit, self.grid)

            # Check to make sure there's not some better path if we take into account our ally's positions
            # If we didn''t move very far
            if Utility.calculate_distance(self.position_to_move_to, self.unit.position) <= 1 and not self.ally_flag:
                logger.debug("Pathfinder is trying again, taking into account allies' positions")
                self.ally_flag = True
                self.widen_flag = False
                self.reset()
                return False

            return True

        else:
            if self.range == 2 and not self.widen_flag:
                # Widen search to all not looked over yet
                logger.debug("Widening Search!")
                self.widen_flag = True
                self.available_targets = [item for item in self.all_targets if item not in self.available_targets]
            else:
                return True

        return False

    def getPath(self, goal_pos, gameStateObj, limit=None):
        self.pathfinder.set_goal_pos(goal_pos)
        self.pathfinder.process(gameStateObj, adj_good_enough=True, ally_block=self.ally_flag, limit=limit)
        my_path = self.pathfinder.path
        self.pathfinder.reset()
        return my_path

    def compute_priority_secondary(self, target, gameStateObj, distance=0):
        # Distance Term: How close is the target to you?
        terms = []
        if distance:
            distance_term = (100 - distance)/100.0
        else:
            target_distance = Utility.calculate_distance(self.unit.position, target.position)
            distance_term = (100 - target_distance)/100.0
        terms.append((distance_term, 120))

        # If we're moving toward enemies
        if isinstance(target, UnitObject.UnitObject) and self.unit.checkIfEnemy(target):
            weakness_term = float(target.stats['HP'] - target.currenthp)/float(target.stats['HP'])

            # Damage Term: How much damage can I inflict on the target (fraction of total HP)?
            # Mutiliply that by the chance I hit
            max_damage = 0
            status_term = 0
            for item in self.unit.items:
                if item.status:
                    status_term = 1
                if item.weapon or item.spell:
                    raw_damage = self.unit.compute_damage(target, gameStateObj, item)
                    chance_to_hit = Utility.clamp(self.unit.compute_hit(target, gameStateObj, item)/100.0, 0, 1)
                    true_damage = raw_damage*chance_to_hit
                    if true_damage > max_damage:
                        max_damage = true_damage

            if max_damage <= 0 and status_term <= 0:
                return 0 # If no damage could be dealt, ignore.
            damage_term = min(float(max_damage)/float(target.stats['HP']), 1.0)
            terms.append((damage_term, 30))
            terms.append((weakness_term, 30))
            terms.append((status_term, 20))

        return Utility.process_terms(terms)
