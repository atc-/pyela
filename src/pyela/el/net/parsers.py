# Copyright 2008 Alex Collins
#
# This file is part of Pyela.
# 
# Pyela is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# Pyela is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with Pyela.  If not, see <http://www.gnu.org/licenses/>.
"""Numerous objects for parsing the messages (raw bytes) from a server 
into their relevant format for use with the rest of the API.

The MessageParser base class defines common functionality for using these 
objects without prior knowledge of the instance at runtime.
"""
import logging
import struct
import time

from pyela.el.common.actors import ELActor
from pyela.el.util.strings import strip_chars, split_str, is_colour, el_colour_to_rgb
from pyela.el.net.packets import ELPacket
from pyela.el.net.elconstants import ELNetFromServer, ELNetToServer, ELConstants
from pyela.el.net.channel import Channel
from pyela.el.logic.eventmanagers import ELSimpleEventManager
from pyela.el.logic.events import ELEventType, ELEvent

log = logging.getLogger('pyela.el.net.parsers')
em = ELSimpleEventManager()

class MessageParser(object):
	"""A message received from the Eternal Lands server"""

	def __init__(self, session):
		"""The session should be an instance of ELSession"""
		self.session = session
	
	def parse(self, packet):
		"""Parse the given packet and return a list of Packet
		instances (or derivatives) ready for output (if any)
		"""
		pass

class BotRawTextMessageParser(MessageParser):
	"""Handles RAW_TEXT messages

	Attributes:
		commands - a dict of command name ('who', 'inv') and the 
					respective callback to use
	"""

	def __init__(self, session):
		super(BotRawTextMessageParser, self).__init__(session)
		self.commands = {}
		self.commands['WHO'] = self._do_who
		self.commands['HI'] = self._do_hi
		self.commands['TIME'] = self._do_time
		self.commands['LICK'] = self._do_lick
	
	def parse(self, packet):
		"""Parses a RAW_TEXT message"""
		data = strip_chars(packet.data[2:])
		if log.isEnabledFor(logging.DEBUG): log.debug("Data for RAW_TEXT packet %s: %s" % (packet.type, data))
		name_str = "%s:" % self.session.name
		if not data.startswith(name_str):
			if log.isEnabledFor(logging.DEBUG): log.debug("Not a message from me! (%s)" % name_str)
			if log.isEnabledFor(logging.DEBUG): log.debug("Found: %d" % (data.find(':') + 1))
			person = data[:data.find(':')]
			data = data[data.find(':') + 2:]
			if log.isEnabledFor(logging.DEBUG): log.debug("is message for me: (%s) %s" % (data, data.startswith("%s," % name_str[0].lower())))
			if data.startswith("%s," % name_str[0].lower()):
				words = data[data.find(",") + 1:].split()
				if log.isEnabledFor(logging.DEBUG): log.debug("Data; %s" % data)
				if log.isEnabledFor(logging.DEBUG): log.debug("Words for commands: %s" % words)
				if len(words) >= 1 and words[0].upper() in self.commands:
					if log.isEnabledFor(logging.DEBUG): log.debug("Found command '%s', executing" % words[0].upper())
					# data[1] is the params onwards to the command
		em.raise_event(ELEvent(ELEventType(ELNetFromServer.RAW_TEXT)))
	
	def _do_who(self, person, params):
		packets = []
		actors_str = ""
		for actor in self.session.actors.values():
			actors_str += "%s, " % actor
		actors_strs = split_str(actors_str, 157) 
		for str in actors_strs:
			packets.append(ELPacket(ELNetToServer.RAW_TEXT, str))

		return packets
	
	def _do_hi(self, person, params):
		return [ELPacket(ELNetToServer.RAW_TEXT, "Hi there, %s :D" % person)]

	def _do_time(self, person, params):
		return [ELPacket(ELNetToServer.RAW_TEXT, "%s: %s" % (person, time.asctime()))]
	
	def _do_lick(self, person, params):
		if len(words) > 1:
			return [ELPacket(ELNetToServer.RAW_TEXT, ":licks %s" % words[0])]
		else:
			return [ELPacket(ELNetToServer.RAW_TEXT, "...I'm not going to lick the air...")]

class ELAddActorMessageParser(MessageParser):
	def parse(self, packet):
		"""Parse an ADD_NEW_(ENHANCED)_ACTOR message"""
		if log.isEnabledFor(logging.DEBUG): log.debug("New actor: %s" % packet)
		actor = ELActor()
		actor.id, actor.x_pos, actor.y_pos, actor.z_pos, \
		actor.z_rot, actor.type, frame, actor.max_health, \
		actor.cur_health, actor.kind_of_actor \
		= struct.unpack('<HHHHHBBHHB', packet.data[:17])

		#Remove the buffs from the x/y coordinates
		actor.x_pos = actor.x_pos & 0x7FF
		actor.y_pos = actor.y_pos & 0x7FF

		if packet.type == ELNetFromServer.ADD_NEW_ENHANCED_ACTOR:
			actor.name = packet.data[28:]
			frame = struct.unpack('B', packet.data[22])[0] #For some reason, data[11] is unused in the ENHANCED message
			actor.kind_of_actor = struct.unpack('B', packet.data[27])[0]
		else:
			actor.name = packet.data[17:]
		
		#The end of name is a \0, and there _might_ be two more bytes
		# containing actor-scale info.
		if actor.name[-3] == '\0':
			#There are two more bytes after the name,
			# the actor scaling bytes
			unpacked = struct.unpack('<H', actor.name[-2:])
			actor.scale = unpacked[0]
			#actor.scale = float(scale)/ELConstants.ACTOR_SCALE_BASE
			actor.name = actor.name[:-3]
		else:
			actor.scale = 1
			actor.name = actor.name[:-1]

		#Find the actor's name's colour char
		i = 0
		while i < len(actor.name) and is_colour(actor.name[i]):
			actor.name_colour = el_colour_to_rgb(ord(actor.name[i]))
			i += 1
		if actor.name_colour[0] == -1:
			#We didn't find any colour codes, use kind_of_actor
			if actor.kind_of_actor == ELConstants.NPC:
				#NPC, bluish
				#The real client colour is (0.3, 0.8, 1.0), but it's too green to see on the minimap
				actor.name_colour = (0.0, 0.0, 1.0)
			elif actor.kind_of_actor in (ELConstants.HUMAN, ELConstants.COMPUTER_CONTROLLED_HUMAN):
				#Regular player, white
				actor.name_colour = (1.0, 1.0, 1.0)
			elif packet.type == ELNetFromServer.ADD_NEW_ENHANCED_ACTOR and actor.kind_of_actor in (ELConstants.PKABLE_HUMAN, ELConstants.PKABLE_COMPUTER_CONTROLLED):
				#PKable player, red
				actor.name_colour = (1.0, 0.0, 0.0)
			else:
				#Animal, yellow
				actor.name_colour = (1.0, 1.0, 0.0)

		space = actor.name.rfind(' ')
		if space != -1 and space > 0 and space+1 < len(actor.name) and is_colour(actor.name[space+1]):
			if log.isEnabledFor(logging.DEBUG): log.debug("Actor has a guild. Parsing from '%s'" % actor.name)
			# split the name into playername and guild
			tokens = actor.name.rsplit(' ', 1)
			actor.name = tokens[0]
			actor.guild = strip_chars(tokens[1])
		actor.name = strip_chars(actor.name)
		
		#Deal with the current frame of the actor
		if frame in (ELConstants.FRAME_DIE1, ELConstants.FRAME_DIE2):
			actor.dead = True
		elif frame in (ELConstants.FRAME_COMBAT_IDLE, ELConstants.FRAME_IN_COMBAT):
			actor.fighting = True
		elif frame >= ELConstants.FRAME_ATTACK_UP_1 and frame <= ELConstants.FRAME_ATTACK_UP_10:
			actor.fighting = True
		elif frame in (ELConstants.PAIN1, ELConstants.PAIN2):
			actor.fighting = True

		self.session.actors[actor.id] = actor
		
		event = ELEvent(ELEventType(ELNetFromServer.ADD_NEW_ACTOR))
		event.data = actor
		em.raise_event(event)
		
		if actor.id == self.session.own_actor_id:
			self.session.own_actor = actor
			event = ELEvent(ELEventType(ELNetFromServer.YOU_ARE))
			event.data = actor
			em.raise_event(event)

		if log.isEnabledFor(logging.DEBUG): log.debug("Actor parsed: %s, %s, %s, %s, %s, %s, %s, %s, %s, %s" % (actor.id, actor.x_pos, actor.y_pos, actor.z_pos, \
			actor.z_rot, actor.type, actor.max_health, \
			actor.cur_health, actor.kind_of_actor, actor.name))
		return []

class ELRemoveActorMessageParser(MessageParser):
	def _get_ids(data):
		offset = 0
		while offset < len(data):
			yield struct.unpack_from('<H', data, offset)[0]
			offset += 2
	_get_ids = staticmethod(_get_ids)

	def parse(self, packet):
		"""Remove actor packet. Remove from self.session.actors dict"""
		if log.isEnabledFor(logging.DEBUG): log.debug("Remove actor packet: '%s'" % packet.data)
		if log.isEnabledFor(logging.DEBUG): log.debug("Actors: %s" % self.session.actors)
		for actor_id in self._get_ids(packet.data):
			event = ELEvent(ELEventType(ELNetFromServer.REMOVE_ACTOR))
			event.data = actor_id
			em.raise_event(event)
			if actor_id in self.session.actors:
				del self.session.actors[actor_id]
			if actor_id == self.session.own_actor_id:
				self.session.own_actor_id = -1
				self.session.own_actor = None
		return []

class ELRemoveAllActorsParser(MessageParser):
	def parse(self, packet):
		event = ELEvent(ELEventType(ELNetFromServer.KILL_ALL_ACTORS))
		em.raise_event(event)
		
		self.session.actors = {}
		if log.isEnabledFor(logging.DEBUG): log.debug("Remove all actors packet")
		return []

class ELAddActorCommandParser(MessageParser):
	def _get_commands(data):
		offset = 0
		while offset < len(data):
			yield struct.unpack_from('<HB', data, offset)
			offset += 3
	_get_commands = staticmethod(_get_commands)

	def parse(self, packet):
		if log.isEnabledFor(logging.DEBUG): log.debug("Actor command packet: '%s'" % packet.data)
		for actor_id, command in self._get_commands(packet.data):
			if actor_id in self.session.actors:
				self.session.actors[actor_id].handle_command(command)
	
				event = ELEvent(ELEventType(ELNetFromServer.ADD_ACTOR_COMMAND))
				event.data = {'actor': self.session.actors[actor_id], 'command': command}
				em.raise_event(event)
		return []

class ELYouAreParser(MessageParser):
	def parse(self, packet):
		if log.isEnabledFor(logging.DEBUG): log.debug("YouAre packet: '%s'" % packet.data)
		id = struct.unpack('<H', packet.data)[0]
		self.session.own_actor_id = id
		if id in self.session.actors:
			self.session.own_actor = self.session.actors[id]
			
			event = ELEvent(ELEventType(ELNetFromServer.YOU_ARE))
			event.data = self.own_actor
			em.raise_event(event)
		return []

class ELGetActiveChannelsMessageParser(MessageParser):
	"""parse the GET_ACTIVE_CHANNELS message"""
	def parse(self, packet):
		del self.session.channels[:]
		chans = struct.unpack('<BIII', packet.data)
		i = 0
		active = chans[0]
		for c in chans[1:]:
			if c != 0:
				self.session.channels.append(Channel(c, i == active))
			i += 1
		return []

class ELBuddyEventMessageParser(MessageParser):
	"""Parse the BUDDY_EVENT message"""

	def parse(self, packet):
		event = ord(packet.data[0])# 1 is online, 0 offline
		if event == 1:
			buddy = str(strip_chars(packet.data[2:]))
			self.session.buddies.append(buddy)
		else:
			buddy = str(strip_chars(packet.data[1:]))
			self.session.buddies.remove(buddy)
		return []