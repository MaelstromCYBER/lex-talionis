#! usr/bine/env python2.7
from GlobalConstants import *
from configuration import *
import Image_Modification, Utility, Engine

import logging
logger = logging.getLogger(__name__)

WARP_OUT_SET = {'warp_out', 'fade_out', 'fade_move', 'warp_move'}

class UnitSprite(object):
    def __init__(self, unit):
        self.unit = unit
        self.state = 'normal' # what state the unit sprite is in
        self.image_state = 'passive' # What the image looks like
        self.transition_state = 'normal' # fade_in, fade_out, warp_in, warp_out, fake_in, fake_out
        self.transition_counter = 0
        self.transition_time = 400
        self.next_position = None
        self.spriteOffset = [0, 0]
        self.old_sprite_offset = (0, 0)

        self.loadSprites()

        self.netposition = (0, 0)
        self.moveSpriteCounter = 0
        self.lastUpdate = 0
        self.spriteMvm = [1, 2, 3, 2, 1, 0]
        self.spriteMvmindex = 0
        self.lastSpriteUpdate = Engine.get_time()

        self.lastHPUpdate = 0
        self.current_cut_off = int((self.unit.currenthp/float(self.unit.stats['HP']))*12) + 1

    def set_transition(self, new_state):
        self.transition_counter = self.transition_time
        self.transition_state = new_state
        if self.transition_state == 'fake_in':
            self.change_state('fake_transition_in')
        elif self.transition_state == 'fake_out' or self.transition_state == 'rescue':
            self.change_state('fake_transition_out')

    def set_next_position(self, new_pos):
        self.next_position = new_pos

    def draw(self, surf, gameStateObj):
        """Assumes image has already been developed."""
        image = self.create_image(self.image_state)
        x, y = self.unit.position
        left = x * TILEWIDTH + self.spriteOffset[0]
        top = y * TILEHEIGHT + self.spriteOffset[1]

        # Active Skill Icon
        if not self.unit.isDying and 'ActiveSkillCharged' in self.unit.tags:
            active_icon = ICONDICT["ActiveSkill"]
            active_icon = Engine.subsurface(active_icon, (PASSIVESPRITECOUNTER.count*32, 0, 32, 32))
            topleft = (left - max(0, (active_icon.get_width() - 16)/2), top - max(0, (active_icon.get_height() - 16)/2))
            surf.blit(active_icon, topleft)

        if self.transition_state in WARP_OUT_SET:
            if self.unit.deathCounter:
                image = Image_Modification.flickerImageTranslucentColorKey(image, self.unit.deathCounter/2)
            else:
                self.transition_counter -= Engine.get_delta()
                if self.transition_counter < 0:
                    self.transition_counter = 0
                image = Image_Modification.flickerImageTranslucentColorKey(image, 100 - self.transition_counter/(self.transition_time/100))
                if self.transition_counter <= 0:
                    if self.transition_state == 'fade_out':
                        self.transition_state = 'normal'
                        self.change_state('normal', gameStateObj)
                        self.unit.die(gameStateObj, event=True)
                    elif self.transition_state == 'warp_out':
                        gameStateObj.map.initiate_warp_flowers(self.unit.position)
                        self.unit.die(gameStateObj, event=True)
                        self.transition_state = 'normal'
                        self.change_state('normal', gameStateObj)
                    elif self.transition_state == 'fade_move' or self.transition_state == 'warp_move':
                        gameStateObj.map.initiate_warp_flowers(self.unit.position)
                        self.unit.leave(gameStateObj)
                        self.unit.position = self.next_position
                        self.unit.arrive(gameStateObj)
                        self.next_position = None
                        gameStateObj.map.initiate_warp_flowers(self.unit.position)
                        if self.transition_state == 'fade_move':
                            self.set_transition('fade_in')
                        elif self.transition_state == 'warp_move':
                            self.set_transition('warp_in')
        elif self.transition_state == 'warp_in' or self.transition_state == 'fade_in':
            self.transition_counter -= Engine.get_delta()
            if self.transition_counter < 0:
                self.transition_counter = 0
            image = Image_Modification.flickerImageTranslucentColorKey(image, self.transition_counter/(self.transition_time/100))
            if self.transition_counter <= 0:
                self.transition_state = 'normal'
                self.change_state('normal', gameStateObj)
        elif self.unit.flicker:
            color = self.unit.flicker[2]
            total_time = self.unit.flicker[1]
            starting_time = self.unit.flicker[0]
            time_passed = Engine.get_time() - starting_time
            if time_passed >= total_time:
                self.unit.end_flicker()
            else:
                color = ((total_time - time_passed)*float(c)/total_time for c in color)
                #image = Image_Modification.flicker_image(image.convert_alpha(), color)
                image = Image_Modification.change_image_color(image.convert_alpha(), color)
        elif self.unit.flickerRed and gameStateObj.boundary_manager.draw_flag:
            image = Image_Modification.flickerImageRed(image.convert_alpha(), 80)
        #if any(status.unit_translucent for status in self.unit.status_effects):
        if 'unit_translucent' in self.unit.status_bundle:
            image = Image_Modification.flickerImageTranslucentColorKey(image, 50)
        # What is this line even doing? - Something majorly important though
        # Each image has (self.image.get_width() - 32)/2 buffers on the left and right of it, to handle any off tile spriting
        # Without self.image.get_width() - 32)/2, we would output the left buffer along with the unit, and the unit would end up +left buffer width to the right of where he should be
        topleft = left - max(0, (image.get_width() - 16)/2), top - 24
        surf.blit(image, topleft)

        # =======
        # Status Aura Icon
        if not self.unit.isDying and 'aura' in self.unit.status_bundle:
            aura_icon_name = self.unit.team + 'AuraIcon'
            aura_icon = IMAGESDICT[aura_icon_name] if aura_icon_name in IMAGESDICT else IMAGESDICT['AuraIcon']
            aura_icon = Engine.subsurface(aura_icon, (0, PASSIVESPRITECOUNTER.count*10, 32, 10))
            topleft = (left - max(0, (aura_icon.get_width() - 16)/2), top - max(0, (aura_icon.get_height() - 16)/2) + 8)
            surf.blit(aura_icon, topleft)
        # Status always animationss
        for status in self.unit.status_effects:
            if status.always_animation:
                x,y = self.unit.position
                topleft = (x-1) * TILEWIDTH + self.spriteOffset[0], (y-1) * TILEHEIGHT + self.spriteOffset[1]
                surf.blit(status.always_animation.image, topleft)

        if self.transition_state.startswith('warp'):
            num_frames = 12
            fps = self.transition_time/num_frames
            frame = (self.transition_time - self.transition_counter)/fps
            if frame >= 0 and frame < num_frames:
                warp_anim = Engine.subsurface(IMAGESDICT['Warp'], (frame*32, 0, 32, 48))
                topleft = (left - max(0, (warp_anim.get_width() - 16)/2), top - max(0, (warp_anim.get_height() - 16)/2) - 4)
                surf.blit(warp_anim, topleft)

        if gameStateObj.cursor.currentSelectedUnit and (gameStateObj.cursor.currentSelectedUnit.name, self.unit.name) in gameStateObj.talk_options:
            frame = (Engine.get_time()/100)%8
            topleft = (left + 6, top - 12)
            surf.blit(Engine.subsurface(IMAGESDICT['TalkMarker'], (frame*8, 0, 8, 16)), topleft)

    def draw_hp(self, surf, gameStateObj):
        current_time = Engine.get_time()
        if self.transition_state == 'normal':
            #print('draw_hp')
            x, y = self.unit.position
            left = x * TILEWIDTH + self.spriteOffset[0]
            top = y * TILEHEIGHT + self.spriteOffset[1]
            # Health Bar
            if not self.unit.isDying:
                if (OPTIONS['HP Map Team'] == 'All') or (OPTIONS['HP Map Team'] == 'Ally' and self.unit.team in ['player', 'other']) or (OPTIONS['HP Map Team'] == 'Enemy' and self.unit.team.startswith('enemy')):
                    if (OPTIONS['HP Map Cull'] == 'All') or (OPTIONS['HP Map Cull'] == 'Wounded' and (self.unit.currenthp < self.unit.stats['HP'] or self.current_cut_off != 13)):
                        health_outline = IMAGESDICT['Map_Health_Outline']
                        health_bar = IMAGESDICT['Map_Health_Bar']
                        if(self.unit.currenthp >= int(self.unit.stats['HP'])):
                            cut_off = 13
                        elif self.unit.currenthp <= 0:
                            cut_off = 0
                        else:
                            cut_off = int((self.unit.currenthp/float(self.unit.stats['HP']))*12) + 1
                        if gameStateObj.combatInstance and self.unit in gameStateObj.combatInstance.health_bars:
                            self.current_cut_off = int(float(gameStateObj.combatInstance.health_bars[self.unit].true_hp)/self.unit.stats['HP']*13)
                        else:
                            if current_time - self.lastHPUpdate > 50:
                                self.lastHPUpdate = current_time
                                if self.current_cut_off < cut_off:
                                    self.current_cut_off += 1
                                elif self.current_cut_off > cut_off:
                                    self.current_cut_off -= 1

                        surf.blit(health_outline, (left, top+13))
                        health_bar = Engine.subsurface(health_bar, (0, 0, self.current_cut_off, 1))
                        surf.blit(health_bar, (left+1, top+14))
            # Extra Icons
            if 'Boss' in self.unit.tags and self.image_state in ['gray', 'passive'] and int((current_time%450)/150) in [1, 2]: # Essentially an every 132 millisecond timer
                bossIcon = ICONDICT['BossIcon']
                surf.blit(bossIcon, (left - 8, top - 8))
            if self.unit.TRV:
                # For now no rescue icon color change, because I would need to add in the gameStateObj...
                """if self.unit.TRV.team == 'player':
                    rescueIcon = ICONDICT['BlueRescueIcon']
                else: # self.TRV.team == 'other':
                    rescueIcon = ICONDICT['GreenRescueIcon']"""
                rescueIcon = ICONDICT['BlueRescueIcon']
                topleft = (left - max(0, (rescueIcon.get_width() - 16)/2), top - max(0, (rescueIcon.get_height() - 16)/2))
                surf.blit(rescueIcon, topleft)

    def get_sprites(self, team):
        unit_stand_sprites = UNITDICT[team + self.unit.klass + self.unit.gender]
        unit_move_sprites = UNITDICT[team + self.unit.klass + self.unit.gender + '_move']
        return unit_stand_sprites, unit_move_sprites

    def loadSprites(self):
        # Load sprites
        try:
            unit_stand_sprites, unit_move_sprites = self.get_sprites(self.unit.team)
        except KeyError as e:
            logger.warning('KeyError. Trying Title Case %s', e)
            unit_stand_sprites, unit_move_sprites = self.get_sprites(self.unit.team.title())
        self.unit_sprites = self.formatSprite(unit_stand_sprites, unit_move_sprites)

    def removeSprites(self):
        self.unit_sprites = None
        self.image = None

    def formatSprite(self, standSprites, moveSprites):
        return {'passive': [Engine.subsurface(standSprites, (num*64, 0, 64, 48)) for num in xrange(3)],
                'gray': [Engine.subsurface(standSprites, (num*64, 48, 64, 48)) for num in xrange(3)],
                'active': [Engine.subsurface(standSprites, (num*64, 96, 64, 48)) for num in xrange(3)],
                'down': [Engine.subsurface(moveSprites, (num*48, 0, 48, 40)) for num in xrange(4)],
                'left': [Engine.subsurface(moveSprites, (num*48, 40, 48, 40)) for num in xrange(4)],
                'right': [Engine.subsurface(moveSprites, (num*48, 80, 48, 40)) for num in xrange(4)],
                'up': [Engine.subsurface(moveSprites, (num*48, 120, 48, 40)) for num in xrange(4)]}

    def create_image(self, state):
        return self.select_frame(self.unit_sprites[state], state).copy()

    def select_frame(self, image, state):
        if state == 'passive' or state == 'gray':
            return image[PASSIVESPRITECOUNTER.count]
        elif state == 'active':
            return image[ACTIVESPRITECOUNTER.count]
        else:
            return image[self.moveSpriteCounter]

    def handle_net_position(self, pos):
        if abs(pos[0]) >= abs(pos[1]):
            if pos[0] > 0:
                self.image_state = 'right'
            elif pos[0] < 0:
                self.image_state = 'left'
            else:
                self.image_state = 'down' # default
        else:
            if pos[1] < 0:
                self.image_state = 'up'
            else:
                self.image_state = 'down'

    def update_move_sprite_counter(self, currentTime, update_speed=50):
        ### MOVE SPRITE COUNTER LOGIC
        if self.moveSpriteCounter == 0 or self.moveSpriteCounter == 2:
            update_speed *= 2
        if currentTime - self.lastUpdate > update_speed:
            self.moveSpriteCounter += 1
            if self.moveSpriteCounter >= 4:
                self.moveSpriteCounter = 0
            self.lastUpdate = currentTime

    def reset_sprite_offset(self):
        self.spriteMvmindex = 0
        self.spriteOffset = [0, 0]

    def change_state(self, new_state, gameStateObj=None):
        self.state = new_state
        if self.state in {'combat_attacker', 'combat_anim'}:
            self.netposition = gameStateObj.cursor.position[0] - self.unit.position[0], gameStateObj.cursor.position[1] - self.unit.position[1]
            self.handle_net_position(self.netposition)
            self.reset_sprite_offset()
        elif self.state == {'combat_active', 'status_active'}:
            self.image_state = 'active'
        elif self.state == 'combat_defender':
            attacker = gameStateObj.combatInstance.p1
            self.netposition = attacker.position[0] - self.unit.position[0], attacker.position[1] - self.unit.position[1]
            self.handle_net_position(self.netposition)
        elif self.state == 'menu':
            self.handle_net_position(self.old_sprite_offset)
        elif self.state == 'fake_transition_in':
            newPosition = (self.unit.position[0] + Utility.clamp(self.spriteOffset[0], -1, 1), self.unit.position[1] + Utility.clamp(self.spriteOffset[1], -1, 1))
            self.netposition = (newPosition[0] - self.unit.position[0], newPosition[1] - self.unit.position[1])
            self.netposition = (-self.netposition[0], -self.netposition[1])
            self.handle_net_position(self.netposition)
        elif self.state == 'fake_transition_out':
            newPosition = (self.unit.position[0] + Utility.clamp(self.spriteOffset[0], -1, 1), self.unit.position[1] + Utility.clamp(self.spriteOffset[1], -1, 1))
            self.netposition = (newPosition[0] - self.unit.position[0], newPosition[1] - self.unit.position[1])
            self.handle_net_position(self.netposition)
        elif self.state == 'selected':
            self.image_state = 'down'

    def update_state(self, gameStateObj):
        currentTime = Engine.get_time()
        #if self.unit == gameStateObj.cursor.currentSelectedUnit:
        #    print(self.state)
        if self.state == 'normal':
            if self.unit.finished and not self.unit.isDying and not self.unit.isActive:
                self.image_state = 'gray'
            elif gameStateObj.cursor.currentHoveredUnit == self.unit and self.unit.team == 'player' and gameStateObj.cursor.drawState:
                self.image_state = 'active'
            else:
                self.image_state = 'passive'
        elif self.state == 'combat_anim':
            self.spriteOffset[0] = Utility.clamp(self.netposition[0], -1, 1) * self.spriteMvm[self.spriteMvmindex]
            self.spriteOffset[1] = Utility.clamp(self.netposition[1], -1, 1) * self.spriteMvm[self.spriteMvmindex]
            if currentTime - self.lastSpriteUpdate > 50:
                self.spriteMvmindex += 1
                if self.spriteMvmindex > len(self.spriteMvm) - 1:
                    self.spriteMvmindex = len(self.spriteMvm) - 1
                self.lastSpriteUpdate = currentTime
            self.update_move_sprite_counter(currentTime, 50)
        elif self.state in {'menu', 'selected'}:
            self.update_move_sprite_counter(currentTime, 80)
        elif self.state == 'chosen': # NETPOSITION SET
            self.netposition = (gameStateObj.cursor.position[0] - self.unit.position[0], gameStateObj.cursor.position[1] - self.unit.position[1])
            if self.netposition == (0, 0):
                self.netposition = self.old_sprite_offset
            self.handle_net_position(self.netposition)
            self.update_move_sprite_counter(currentTime, 80)
        elif self.state == 'moving':
            try:
                newPosition = self.unit.path[-1]
            except IndexError:
                if self.spriteOffset[0] != 0 or self.spriteOffset[1] != 0:
                    self.old_sprite_offset = tuple(self.spriteOffset)
                self.spriteOffset = [0, 0]
                self.transition_state = 'normal'
                #self.change_state('normal', gameStateObj)
                return
            self.netposition = (newPosition[0] - self.unit.position[0], newPosition[1] - self.unit.position[1])
            self.spriteOffset[0] = int(TILEWIDTH * (currentTime - self.unit.lastMoveTime) / CONSTANTS['Unit Speed'] * self.netposition[0])
            self.spriteOffset[1] = int(TILEHEIGHT * (currentTime - self.unit.lastMoveTime) / CONSTANTS['Unit Speed'] * self.netposition[1])
            self.handle_net_position(self.netposition)
            self.update_move_sprite_counter(currentTime, 80)
        elif self.state == 'fake_transition_in':
            if self.spriteOffset[0] > 0:
                self.spriteOffset[0] -= 2
            elif self.spriteOffset[0] < 0:
                self.spriteOffset[0] += 2
            if self.spriteOffset[1] > 0:
                self.spriteOffset[1] -= 2
            elif self.spriteOffset[1] < 0:
                self.spriteOffset[1] += 2

            if self.spriteOffset[0] == 0 and self.spriteOffset[1] == 0:
                self.transition_state = 'normal'
                self.change_state('normal', gameStateObj)
        elif self.state == 'fake_transition_out':
            if self.spriteOffset[0] < 0:
                self.spriteOffset[0] -= 2
            elif self.spriteOffset[0] > 0:
                self.spriteOffset[0] += 2
            if self.spriteOffset[1] < 0:
                self.spriteOffset[1] -= 2
            elif self.spriteOffset[1] > 0:
                self.spriteOffset[1] += 2
            if abs(self.spriteOffset[0]) >= TILEWIDTH or abs(self.spriteOffset[1]) >= TILEHEIGHT:
                self.transition_state = 'normal'
                self.change_state('normal', gameStateObj)
                self.spriteOffset = [0, 0]
                if self.transition_state == 'fake_out':
                    self.unit.die(gameStateObj, event=True)
                else: # Rescue
                    self.unit.leave(gameStateObj)
                    self.unit.position = None

    def update(self, gameStateObj):
        self.update_state(gameStateObj)
            
        # Update status effects
        # Status effects
        if 'always_animation' in self.unit.status_bundle:
            for status in self.unit.status_effects:
                if status.always_animation:
                    staa = status.always_animation
                    currentTime = Engine.get_time()
                    if currentTime - staa.lastUpdate > staa.animation_speed:
                        staa.frameCount += int((currentTime - staa.lastUpdate)/staa.animation_speed) # 1
                        staa.lastUpdate = currentTime
                        if staa.frameCount >= staa.num_frames:
                            staa.frameCount = 0

                    indiv_width, indiv_height = staa.sprite.get_width()/staa.x, staa.sprite.get_height()/staa.y
                    staa.image = Engine.subsurface(staa.sprite, (staa.frameCount%staa.x * indiv_width, staa.frameCount/staa.x * indiv_height, indiv_width, indiv_height))