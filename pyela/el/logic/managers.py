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
import time
import select
import struct
import sys
import datetime
import logging

from pyela.el.net.connections import ELConnection
from pyela.el.net.elconstants import ELConstants
from pyela.el.net.elconstants import ELNetFromServer, ELNetToServer
from pyela.el.net.packets import ELPacket
from pyela.el.logic.session import ELSession
from pyela.el.common.exceptions import ConnectionException, ManagerException
from pyela.el.logic.eventmanagers import ELSimpleEventManager

log = logging.getLogger('pyela.el.logic.managers')

LAST_ASTRO_MAX_SECS = 60

LAST_ASTRO_MAX_MINS = 1

HEART_BEAT_MAX_SECS = 18

POLL_TIMEOUT_MILLIS = HEART_BEAT_MAX_SECS * 1000

class ConnectionManager(object):
	"""A manager for a Connection object."""

	def __init__(self, connection):
		self.connection = connection

	def process(self):
		"""Process the connection's input"""
		pass

class MultiConnectionManager(ConnectionManager):
	"""A derived class from ConnectionManager.
	This implementation can handle multiple instances of 
	pyela.el.net.connections.Connection. 

	All messages received (instances of pyela.el.net.packets.Packet) are passed to 
	the particular connection's packet handler (pyela.el.net.packethandlers)

	Attributes:
		_p 			- instance of select.poll(); leave it alone
		_em			- instance of ELSimpleEventManager; used to map events
		connections - a list of pyela.net.connections.BaseConnection or derivative
					  to manage
		config		- the instance of ConfigParser, passed to init
		session		- the ELSession instance, representing the data
					  for this connection
	"""

	def __init__(self, connections):
		"""Creates an instane with the given config, and the given connections"""
		self._em = ELSimpleEventManager()
		self._map_events()
		if None not in connections:
			self.connections = connections
		else:
			raise ManagerException('None cannot be a connection')

	def _map_events(self):
		pass

	def __set_opt(self, val):
		log.info("Something's trying to set my output queue. Blocked!")
		pass

	def add_connection(self, con):
		"""Appends the given connection to the connection list, and calls connect"""
		con.connect()
		self.connections.append(con)
		self.__register_connections()

	def process(self):
		"""Overrides super's process impl to govern all the connections """
		self.__connect_all() #TODO: Does this belong here?

		if len(self.connections) == 0:
			raise ManagerException('Cannot register connections. None provided.')

		while len(self.connections) > 0:
			self._p = select.poll()
			self.__register_connections() #Rebuild the poll object for each loop. It's the best way to get rid of old file descriptors.
			poll_time = self.__calc_poll_time()
			if log.isEnabledFor(logging.DEBUG): log.debug("Setting poll with timeout %d" % poll_time)
			p_opt = self._p.poll(poll_time)
			if log.isEnabledFor(logging.DEBUG): log.debug("Poll ended: %s" % p_opt)

			# p_opt may be empty, which means the timeout occured
			if len(p_opt) == 0:
				# no input from our connections
				if log.isEnabledFor(logging.DEBUG): log.debug("Poll returned nothing. Processing connection opt queue")
				# check if we need to send a keep-alive
				for con in self.connections:
					if con.last_send+HEART_BEAT_MAX_SECS <= time.time()+1:
						# send a keep-alive packet if we need to, with a
						# 1 second margin to avoid having to poll() for just a few ms
						con.keep_alive()
				# process output queue??
			else:
				# data received in a connection
				# get the connection poll is referring to

				p_event = None
				for p in p_opt:
					p_fileno = p[0] # the file descriptor and poll event
					p_event = p[1]
					con = self.get_connection_by_id(p_fileno)
					if con != None and (p_event & select.POLLIN or p_event & select.POLLPRI):
						# found the con poll's referring to
						if log.isEnabledFor(logging.DEBUG): log.debug("Got data for connection '%s'" % con)
						try:
							packets = con.recv(2048)
						except ConnectionException:
							self.__reconnect(con)
						#log.debug("Bytes (%d): %s" % (len(bytes), bytes))
						if len(packets) != 0:
							if log.isEnabledFor(logging.DEBUG): log.debug("Received %d packets" % len(packets))
							for e in con.process_packets(packets):
								ELSimpleEventManager().raise_event(e)
						else:
							log.error("Empty packets returned. Connection down? Reconnecting... (con=%s)" % con)
					con.process_queue()
			del self._p
			self._p = None

	def __reconnect(self, con):
		# connection retries sleep
		try:
			if log.isEnabledFor(logging.DEBUG): log.debug("Sleeping 5 seconds before reconnect")
			time.sleep(5) #TODO: This will block everything for 5 seconds. Not good.
			return con.reconnect()
		except ConnectionException as ce:
			log.error("Exception when reconnecting: %s" % ce)

	def get_connection_by_id(self, id):
		for con in self.connections:
			if con.is_connected() and con.fileno() == id:
				return con
		return None

	def __calc_poll_time(self):
		"""Calculate the poll time from all the connections in milliseconds, 
		based on their MAX_LAST_SEND_SECS and their last_send value
		"""
		poll_time = HEART_BEAT_MAX_SECS
		for con in self.connections:
			if con.is_connected():
				this_pt = int(con.MAX_LAST_SEND_SECS - int(time.time() - con.last_send))
				if this_pt < poll_time and this_pt > 0 and poll_time > 0:
					poll_time = this_pt
		if log.isEnabledFor(logging.DEBUG): log.debug("Calc'd poll time for %s is %d" % (con, int(poll_time)))

		return int(poll_time * 1000)

	def __connect_all(self):
		"""call connect on all the connections if con.is_connected() yields False"""
		for con in self.connections:
			if not con.is_connected():
				con.connect()

	def __register_connections(self):
		"""Registers socket file descriptors in the manager's poll object"""
		if self._p == None:
			return #Fall through, the connections will be registered when required
		for con in self.connections:
			if con.is_connected():
				self._p.register(con, select.POLLIN | select.POLLPRI | select.POLLERR)
