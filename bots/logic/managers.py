# Copyright 2011 Pyela project
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

from pyela.el.logic.managers import MultiConnectionManager
from logic.eventhandlers import BotRawTextEventHandler

class BotMultiConnectionManager(MultiConnectionManager):
	def _map_events(self):
		self._em.add_handler(BotRawTextEventHandler())
