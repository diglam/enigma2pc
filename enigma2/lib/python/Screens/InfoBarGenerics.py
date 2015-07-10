from ChannelSelection import ChannelSelection, BouquetSelector, SilentBouquetSelector

from Components.ActionMap import ActionMap, HelpableActionMap
from Components.ActionMap import NumberActionMap
from Components.Harddisk import harddiskmanager
from Components.Input import Input
from Components.Label import Label
from Components.MovieList import AUDIO_EXTENSIONS, MOVIE_EXTENSIONS, DVD_EXTENSIONS
from Components.PluginComponent import plugins
from Components.ServiceEventTracker import ServiceEventTracker
from Components.Sources.Boolean import Boolean
from Components.config import config, ConfigBoolean, ConfigClock
from Components.SystemInfo import SystemInfo
from Components.UsageConfig import preferredInstantRecordPath, defaultMoviePath, ConfigSelection
from Components.Sources.StaticText import StaticText
from EpgSelection import EPGSelection
from Plugins.Plugin import PluginDescriptor

from Screen import Screen
from Screens import ScreenSaver
from Screens import Standby
from Screens.ChoiceBox import ChoiceBox
from Screens.Dish import Dish
from Screens.EventView import EventViewEPGSelect, EventViewSimple, EventViewRecording
from Screens.InputBox import InputBox
from Screens.MessageBox import MessageBox
from Screens.MinuteInput import MinuteInput
from Screens.TimerSelection import TimerSelection
from Screens.PictureInPicture import PictureInPicture
import Screens.Standby
from Screens.SubtitleDisplay import SubtitleDisplay
from Screens.RdsDisplay import RdsInfoDisplay, RassInteractive
from Screens.TimeDateInput import TimeDateInput
from Screens.UnhandledKey import UnhandledKey
from ServiceReference import ServiceReference, isPlayableForCur

from Tools import Notifications, ASCIItranslit
from Tools.Directories import fileExists, getRecordingFilename, moveFiles

from enigma import eTimer, eServiceCenter, eDVBServicePMTHandler, iServiceInformation, \
	iPlayableService, eServiceReference, eEPGCache, eActionMap

from time import time, localtime, strftime
from os import stat as os_stat
from os import rename as os_rename
import os
from bisect import insort
#from sys import maxint
maxint = 0x7FFFFFFF

from RecordTimer import RecordTimerEntry, RecordTimer, findSafeRecordPath

# hack alert!
from Menu import MainMenu, mdom

def isStandardInfoBar(self):
	return self.__class__.__name__ == "InfoBar"

def setResumePoint(session):
	global resumePointCache, resumePointCacheLast
	service = session.nav.getCurrentService()
	ref = session.nav.getCurrentlyPlayingServiceOrGroup()
	if (service is not None) and (ref is not None): # and (ref.type != 1):
		# ref type 1 has its own memory...
		seek = service.seek()
		if seek:
			pos = seek.getPlayPosition()
			if not pos[0]:
				key = ref.toString()
				lru = int(time())
				l = seek.getLength()
				if l:
					l = l[1]
				else:
					l = None
				resumePointCache[key] = [lru, pos[1], l]
				if len(resumePointCache) > 50:
					candidate = key
					for k,v in resumePointCache.items():
						if v[0] < lru:
							candidate = k
					del resumePointCache[candidate]
				if lru - resumePointCacheLast > 3600:
					saveResumePoints()

def delResumePoint(ref):
	global resumePointCache, resumePointCacheLast
	try:
		del resumePointCache[ref.toString()]
	except KeyError:
		pass
	if int(time()) - resumePointCacheLast > 3600:
		saveResumePoints()

def getResumePoint(session):
	global resumePointCache
	ref = session.nav.getCurrentlyPlayingServiceOrGroup()
	if (ref is not None) and (ref.type != 1):
		try:
			entry = resumePointCache[ref.toString()]
			entry[0] = int(time()) # update LRU timestamp
			return entry[1]
		except KeyError:
			return None

def saveResumePoints():
	global resumePointCache, resumePointCacheLast
	import cPickle
	try:
		f = open('/root/resumepoints.pkl', 'wb')
		cPickle.dump(resumePointCache, f, cPickle.HIGHEST_PROTOCOL)
	except Exception, ex:
		print "[InfoBar] Failed to write resumepoints:", ex
	resumePointCacheLast = int(time())

def loadResumePoints():
	import cPickle
	try:
		return cPickle.load(open('/root/resumepoints.pkl', 'rb'))
	except Exception, ex:
		print "[InfoBar] Failed to load resumepoints:", ex
		return {}

resumePointCache = loadResumePoints()
resumePointCacheLast = int(time())

class InfoBarDish:
	def __init__(self):
		self.dishDialog = self.session.instantiateDialog(Dish)

class InfoBarUnhandledKey:
	def __init__(self):
		self.unhandledKeyDialog = self.session.instantiateDialog(UnhandledKey)
		self.hideUnhandledKeySymbolTimer = eTimer()
		self.hideUnhandledKeySymbolTimer.callback.append(self.unhandledKeyDialog.hide)
		self.checkUnusedTimer = eTimer()
		self.checkUnusedTimer.callback.append(self.checkUnused)
		self.onLayoutFinish.append(self.unhandledKeyDialog.hide)
		eActionMap.getInstance().bindAction('', -maxint -1, self.actionA) #highest prio
		eActionMap.getInstance().bindAction('', maxint, self.actionB) #lowest prio
		self.flags = (1<<1)
		self.uflags = 0

	#this function is called on every keypress!
	def actionA(self, key, flag):
		self.unhandledKeyDialog.hide()
		if flag != 4:
			if self.flags & (1<<1):
				self.flags = self.uflags = 0
			self.flags |= (1<<flag)
			if flag == 1: # break
				self.checkUnusedTimer.start(0, True)
		return 0

	#this function is only called when no other action has handled this key
	def actionB(self, key, flag):
		if flag != 4:
			self.uflags |= (1<<flag)

	def checkUnused(self):
		if self.flags == self.uflags:
			self.unhandledKeyDialog.show()
			self.hideUnhandledKeySymbolTimer.start(2000, True)

class InfoBarScreenSaver:
	def __init__(self):
		self.onExecBegin.append(self.__onExecBegin)
		self.onExecEnd.append(self.__onExecEnd)
		self.screenSaverTimer = eTimer()
		self.screenSaverTimer.callback.append(self.screensaverTimeout)
		self.screensaver = self.session.instantiateDialog(ScreenSaver.Screensaver)
		self.onLayoutFinish.append(self.__layoutFinished)

	def __layoutFinished(self):
		self.screensaver.hide()

	def __onExecBegin(self):
		eActionMap.getInstance().bindAction('', -maxint - 1, self.keypressScreenSaver)
		self.ScreenSaverTimerStart()

	def __onExecEnd(self):
		if self.screensaver.shown:
			self.screensaver.hide()
			eActionMap.getInstance().unbindAction('', self.keypressScreenSaver)
		self.screenSaverTimer.stop()

	def ScreenSaverTimerStart(self):
		time = int(config.usage.screen_saver.value)
		flag = self.seekstate[0]
		if not flag:
			ref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
			if ref:
				ref = ref.toString().split(":")
				flag = ref[2] == "2" or os.path.splitext(ref[10])[1].lower() in AUDIO_EXTENSIONS
		if time and flag:
			self.screenSaverTimer.startLongTimer(time)
		else:
			self.screenSaverTimer.stop()

	def screensaverTimeout(self):
		if self.execing and not Standby.inStandby and not Standby.inTryQuitMainloop:
			self.hide()
			if hasattr(self, "pvrStateDialog"):
				self.pvrStateDialog.hide()
			self.screensaver.show()
			eActionMap.getInstance().bindAction('', -maxint - 1, self.keypressScreenSaver)

	def keypressScreenSaver(self, key, flag):
		if flag:
			self.screensaver.hide()
			self.show()
			self.ScreenSaverTimerStart()
			eActionMap.getInstance().unbindAction('', self.keypressScreenSaver)

class SecondInfoBar(Screen):

	def __init__(self, session):
		Screen.__init__(self, session)
		self.skin = None

class InfoBarShowHide(InfoBarScreenSaver):
	""" InfoBar show/hide control, accepts toggleShow and hide actions, might start
	fancy animations. """
	STATE_HIDDEN = 0
	STATE_HIDING = 1
	STATE_SHOWING = 2
	STATE_SHOWN = 3

	def __init__(self):
		self["ShowHideActions"] = ActionMap( ["InfobarShowHideActions"] ,
			{
				"toggleShow": self.toggleShow,
				"hide": self.keyHide,
			}, 1) # lower prio to make it possible to override ok and cancel..

		self.__event_tracker = ServiceEventTracker(screen=self, eventmap=
			{
				iPlayableService.evStart: self.serviceStarted,
			})

		InfoBarScreenSaver.__init__(self)
		self.__state = self.STATE_SHOWN
		self.__locked = 0

		self.hideTimer = eTimer()
		self.hideTimer.callback.append(self.doTimerHide)
		self.hideTimer.start(5000, True)

		self.onShow.append(self.__onShow)
		self.onHide.append(self.__onHide)

		self.onShowHideNotifiers = []

		self.secondInfoBarScreen = ""
		if isStandardInfoBar(self):
			self.secondInfoBarScreen = self.session.instantiateDialog(SecondInfoBar)
			self.secondInfoBarScreen.show()

		self.onLayoutFinish.append(self.__layoutFinished)

	def __layoutFinished(self):
		if self.secondInfoBarScreen:
			self.secondInfoBarScreen.hide()

	def __onShow(self):
		self.__state = self.STATE_SHOWN
		for x in self.onShowHideNotifiers:
			x(True)
		self.startHideTimer()

	def __onHide(self):
		self.__state = self.STATE_HIDDEN
		if self.secondInfoBarScreen:
			self.secondInfoBarScreen.hide()
		for x in self.onShowHideNotifiers:
			x(False)

	def keyHide(self):
		if self.__state == self.STATE_SHOWN:
			self.hide()
		elif self.session.pipshown and "popup" in config.usage.pip_hideOnExit.value:
			if config.usage.pip_hideOnExit.value == "popup":
				self.session.openWithCallback(self.hidePipOnExitCallback, MessageBox, _("Disable Picture in Picture"), simple=True)
			else:
				self.hidePipOnExitCallback(True)

	def hidePipOnExitCallback(self, answer):
		if answer == True:
			self.showPiP()

	def connectShowHideNotifier(self, fnc):
		if not fnc in self.onShowHideNotifiers:
			self.onShowHideNotifiers.append(fnc)

	def disconnectShowHideNotifier(self, fnc):
		if fnc in self.onShowHideNotifiers:
			self.onShowHideNotifiers.remove(fnc)

	def serviceStarted(self):
		if self.execing:
			if config.usage.show_infobar_on_zap.value:
				self.doShow()

	def startHideTimer(self):
		if self.__state == self.STATE_SHOWN and not self.__locked:
			self.hideTimer.stop()
			if self.secondInfoBarScreen and self.secondInfoBarScreen.shown:
				idx = config.usage.show_second_infobar.index - 1
			else:
				idx = config.usage.infobar_timeout.index
			if idx:
				self.hideTimer.start(idx*1000, True)

	def doShow(self):
		self.show()
		self.startHideTimer()

	def doTimerHide(self):
		self.hideTimer.stop()
		if self.__state == self.STATE_SHOWN:
			self.hide()

	def toggleShow(self):
		if self.__state == self.STATE_HIDDEN:
			self.show()
			if self.secondInfoBarScreen:
				self.secondInfoBarScreen.hide()
		elif isStandardInfoBar(self) and config.usage.show_second_infobar.value == "EPG":
			self.showDefaultEPG()
		elif self.secondInfoBarScreen and config.usage.show_second_infobar.value and not self.secondInfoBarScreen.shown:
			self.secondInfoBarScreen.show()
			self.startHideTimer()
		else:
			self.hide()
			self.hideTimer.stop()

	def lockShow(self):
		self.__locked = self.__locked + 1
		if self.execing:
			self.show()
			self.hideTimer.stop()

	def unlockShow(self):
		self.__locked = self.__locked - 1
		if self.execing:
			self.startHideTimer()

#	def startShow(self):
#		self.instance.m_animation.startMoveAnimation(ePoint(0, 600), ePoint(0, 380), 100)
#		self.__state = self.STATE_SHOWN
#
#	def startHide(self):
#		self.instance.m_animation.startMoveAnimation(ePoint(0, 380), ePoint(0, 600), 100)
#		self.__state = self.STATE_HIDDEN

class NumberZap(Screen):
	def quit(self):
		self.Timer.stop()
		self.close()

	def keyOK(self):
		self.Timer.stop()
		self.close(self.service, self.bouquet)

	def handleServiceName(self):
		if self.searchNumber:
			self.service, self.bouquet = self.searchNumber(int(self["number"].getText()))
			self["servicename"].text = self["servicename_summary"].text = ServiceReference(self.service).getServiceName()
			if not self.startBouquet:
				self.startBouquet = self.bouquet

	def keyBlue(self):
		self.Timer.start(3000, True)
		if self.searchNumber:
			if self.startBouquet == self.bouquet:
				self.service, self.bouquet = self.searchNumber(int(self["number"].getText()), firstBouquetOnly = True)
			else:
				self.service, self.bouquet = self.searchNumber(int(self["number"].getText()))
			self["servicename"].text = self["servicename_summary"].text = ServiceReference(self.service).getServiceName()

	def keyNumberGlobal(self, number):
		self.Timer.start(1000, True)
		self.numberString = self.numberString + str(number)
		self["number"].text = self["number_summary"].text = self.numberString

		self.handleServiceName()

		if len(self.numberString) >= 5:
			self.keyOK()

	def __init__(self, session, number, searchNumberFunction = None):
		Screen.__init__(self, session)
		self.numberString = str(number)
		self.searchNumber = searchNumberFunction
		self.startBouquet = None

		self["channel"] = Label(_("Channel:"))
		self["number"] = Label(self.numberString)
		self["servicename"] = Label()
		self["channel_summary"] = StaticText(_("Channel:"))
		self["number_summary"] = StaticText(self.numberString)
		self["servicename_summary"] = StaticText()

		self.handleServiceName()

		self["actions"] = NumberActionMap( [ "SetupActions", "ShortcutActions" ],
			{
				"cancel": self.quit,
				"ok": self.keyOK,
				"blue": self.keyBlue,
				"1": self.keyNumberGlobal,
				"2": self.keyNumberGlobal,
				"3": self.keyNumberGlobal,
				"4": self.keyNumberGlobal,
				"5": self.keyNumberGlobal,
				"6": self.keyNumberGlobal,
				"7": self.keyNumberGlobal,
				"8": self.keyNumberGlobal,
				"9": self.keyNumberGlobal,
				"0": self.keyNumberGlobal
			})

		self.Timer = eTimer()
		self.Timer.callback.append(self.keyOK)
		self.Timer.start(3000, True)

class InfoBarNumberZap:
	""" Handles an initial number for NumberZapping """
	def __init__(self):
		self["NumberActions"] = NumberActionMap( [ "NumberActions"],
			{
				"1": self.keyNumberGlobal,
				"2": self.keyNumberGlobal,
				"3": self.keyNumberGlobal,
				"4": self.keyNumberGlobal,
				"5": self.keyNumberGlobal,
				"6": self.keyNumberGlobal,
				"7": self.keyNumberGlobal,
				"8": self.keyNumberGlobal,
				"9": self.keyNumberGlobal,
				"0": self.keyNumberGlobal,
			})

	def keyNumberGlobal(self, number):
		if number == 0:
			if isinstance(self, InfoBarPiP) and self.pipHandles0Action():
				self.pipDoHandle0Action()
			elif len(self.servicelist.history) > 1:
				self.checkTimeshiftRunning(self.recallPrevService)
		else:
			if self.has_key("TimeshiftActions") and self.timeshiftEnabled():
				ts = self.getTimeshift()
				if ts and ts.isTimeshiftActive():
					return
			self.session.openWithCallback(self.numberEntered, NumberZap, number, self.searchNumber)

	def recallPrevService(self, reply):
		if reply:
			self.servicelist.recallPrevService()

	def numberEntered(self, service = None, bouquet = None):
		if service:
			self.selectAndStartService(service, bouquet)

	def searchNumberHelper(self, serviceHandler, num, bouquet):
		servicelist = serviceHandler.list(bouquet)
		if servicelist:
			serviceIterator = servicelist.getNext()
			while serviceIterator.valid():
				if num == serviceIterator.getChannelNum():
					return serviceIterator
				serviceIterator = servicelist.getNext()
		return None

	def searchNumber(self, number, firstBouquetOnly = False):
		bouquet = self.servicelist.getRoot()
		service = None
		serviceHandler = eServiceCenter.getInstance()
		if not firstBouquetOnly:
			service = self.searchNumberHelper(serviceHandler, number, bouquet)
		if config.usage.multibouquet.value and not service:
			bouquet = self.servicelist.bouquet_root
			bouquetlist = serviceHandler.list(bouquet)
			if bouquetlist:
				bouquet = bouquetlist.getNext()
				while bouquet.valid():
					if bouquet.flags & eServiceReference.isDirectory:
						service = self.searchNumberHelper(serviceHandler, number, bouquet)
						if service:
							playable = not (service.flags & (eServiceReference.isMarker|eServiceReference.isDirectory)) or (service.flags & eServiceReference.isNumberedMarker)
							if not playable:
								service = None
							break
						if config.usage.alternative_number_mode.value or firstBouquetOnly:
							break
					bouquet = bouquetlist.getNext()
		return service, bouquet

	def selectAndStartService(self, service, bouquet):
		if service:
			if self.servicelist.getRoot() != bouquet: #already in correct bouquet?
				self.servicelist.clearPath()
				if self.servicelist.bouquet_root != bouquet:
					self.servicelist.enterPath(self.servicelist.bouquet_root)
				self.servicelist.enterPath(bouquet)
			self.servicelist.setCurrentSelection(service) #select the service in servicelist
			self.servicelist.zap(enable_pipzap = True)
			self.servicelist.correctChannelNumber()
			self.servicelist.startRoot = None

	def zapToNumber(self, number):
		service, bouquet = self.searchNumber(number)
		self.selectAndStartService(service, bouquet)

config.misc.initialchannelselection = ConfigBoolean(default = True)

class InfoBarChannelSelection:
	""" ChannelSelection - handles the channelSelection dialog and the initial
	channelChange actions which open the channelSelection dialog """
	def __init__(self):
		#instantiate forever
		self.servicelist = self.session.instantiateDialog(ChannelSelection)

		if config.misc.initialchannelselection.value:
			self.onShown.append(self.firstRun)

		self["ChannelSelectActions"] = HelpableActionMap(self, "InfobarChannelSelection",
			{
				"switchChannelUp": (self.switchChannelUp, _("Open service list and select previous channel")),
				"switchChannelDown": (self.switchChannelDown, _("Open service list and select next channel")),
				"zapUp": (self.zapUp, _("Switch to previous channel")),
				"zapDown": (self.zapDown, _("Switch next channel")),
				"historyBack": (self.historyBack, _("Switch to previous channel in history")),
				"historyNext": (self.historyNext, _("Switch to next channel in history")),
				"openServiceList": (self.openServiceList, _("Open service list")),
			})

	def showTvChannelList(self, zap=False):
		self.servicelist.setModeTv()
		if zap:
			self.servicelist.zap()

	def showRadioChannelList(self, zap=False):
		self.servicelist.setModeRadio()
		if zap:
			self.servicelist.zap()

	def firstRun(self):
		self.onShown.remove(self.firstRun)
		config.misc.initialchannelselection.value = False
		config.misc.initialchannelselection.save()
		self.switchChannelDown()

	def historyBack(self):
		self.checkTimeshiftRunning(self.historyBackCheckTimeshiftCallback)

	def historyBackCheckTimeshiftCallback(self, answer):
		if answer:
			self.servicelist.historyBack()

	def historyNext(self):
		self.checkTimeshiftRunning(self.historyNextCheckTimeshiftCallback)

	def historyNextCheckTimeshiftCallback(self, answer):
		if answer:
			self.servicelist.historyNext()

	def switchChannelUp(self):
		if "keep" not in config.usage.servicelist_cursor_behavior.value:
			self.servicelist.moveUp()
		self.session.execDialog(self.servicelist)

	def switchChannelDown(self):
		if "keep" not in config.usage.servicelist_cursor_behavior.value:
			self.servicelist.moveDown()
		self.session.execDialog(self.servicelist)

	def openServiceList(self):
		self.session.execDialog(self.servicelist)

	def zapUp(self):
		if self.servicelist.inBouquet():
			prev = self.servicelist.getCurrentSelection()
			if prev:
				prev = prev.toString()
				while True:
					if config.usage.quickzap_bouquet_change.value:
						if self.servicelist.atBegin():
							self.servicelist.prevBouquet()
					self.servicelist.moveUp()
					cur = self.servicelist.getCurrentSelection()
					if cur:
						if self.servicelist.dopipzap:
							isPlayable = self.session.pip.isPlayableForPipService(cur)
						else:
							isPlayable = isPlayableForCur(cur)
					if cur and (cur.toString() == prev or isPlayable):
							break
		else:
			self.servicelist.moveUp()
		self.servicelist.zap(enable_pipzap = True)

	def zapDown(self):
		if self.servicelist.inBouquet():
			prev = self.servicelist.getCurrentSelection()
			if prev:
				prev = prev.toString()
				while True:
					if config.usage.quickzap_bouquet_change.value and self.servicelist.atEnd():
						self.servicelist.nextBouquet()
					else:
						self.servicelist.moveDown()
					cur = self.servicelist.getCurrentSelection()
					if cur:
						if self.servicelist.dopipzap:
							isPlayable = self.session.pip.isPlayableForPipService(cur)
						else:
							isPlayable = isPlayableForCur(cur)
					if cur and (cur.toString() == prev or isPlayable):
							break
		else:
			self.servicelist.moveDown()
		self.servicelist.zap(enable_pipzap = True)

class InfoBarMenu:
	""" Handles a menu action, to open the (main) menu """
	def __init__(self):
		self["MenuActions"] = HelpableActionMap(self, "InfobarMenuActions",
			{
				"mainMenu": (self.mainMenu, _("Enter main menu...")),
			})
		self.session.infobar = None

	def mainMenu(self):
		print "loading mainmenu XML..."
		menu = mdom.getroot()
		assert menu.tag == "menu", "root element in menu must be 'menu'!"

		self.session.infobar = self
		# so we can access the currently active infobar from screens opened from within the mainmenu
		# at the moment used from the SubserviceSelection

		self.session.openWithCallback(self.mainMenuClosed, MainMenu, menu)

	def mainMenuClosed(self, *val):
		self.session.infobar = None

class InfoBarSimpleEventView:
	""" Opens the Eventview for now/next """
	def __init__(self):
		self["EPGActions"] = HelpableActionMap(self, "InfobarEPGActions",
			{
				"showEventInfo": (self.openEventView, _("Show event details")),
				"showEventInfoSingleEPG": (self.openEventView, _("Show event details")),
				"showInfobarOrEpgWhenInfobarAlreadyVisible": self.showEventInfoWhenNotVisible,
			})

	def showEventInfoWhenNotVisible(self):
		if self.shown:
			self.openEventView()
		else:
			self.toggleShow()
			return 1

	def openEventView(self):
		epglist = [ ]
		self.epglist = epglist
		service = self.session.nav.getCurrentService()
		ref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		info = service.info()
		ptr=info.getEvent(0)
		if ptr:
			epglist.append(ptr)
		ptr=info.getEvent(1)
		if ptr:
			epglist.append(ptr)
		if epglist:
			self.session.open(EventViewSimple, epglist[0], ServiceReference(ref), self.eventViewCallback)

	def eventViewCallback(self, setEvent, setService, val): #used for now/next displaying
		epglist = self.epglist
		if len(epglist) > 1:
			tmp = epglist[0]
			epglist[0] = epglist[1]
			epglist[1] = tmp
			setEvent(epglist[0])

class SimpleServicelist:
	def __init__(self, services):
		self.services = services
		self.length = len(services)
		self.current = 0

	def selectService(self, service):
		if not self.length:
			self.current = -1
			return False
		else:
			self.current = 0
			while self.services[self.current].ref != service:
				self.current += 1
				if self.current >= self.length:
					return False
		return True

	def nextService(self):
		if not self.length:
			return
		if self.current+1 < self.length:
			self.current += 1
		else:
			self.current = 0

	def prevService(self):
		if not self.length:
			return
		if self.current-1 > -1:
			self.current -= 1
		else:
			self.current = self.length - 1

	def currentService(self):
		if not self.length or self.current >= self.length:
			return None
		return self.services[self.current]

class InfoBarEPG:
	""" EPG - Opens an EPG list when the showEPGList action fires """
	def __init__(self):
		self.is_now_next = False
		self.dlg_stack = [ ]
		self.bouquetSel = None
		self.eventView = None
		self.epglist = []
		self.defaultEPGType = self.getDefaultEPGtype()
		self.defaultGuideType = self.getDefaultGuidetype()
		self.__event_tracker = ServiceEventTracker(screen=self, eventmap=
			{
				iPlayableService.evUpdatedEventInfo: self.__evEventInfoChanged,
			})

		self["EPGActions"] = HelpableActionMap(self, "InfobarEPGActions",
			{
				"showEventInfo": (self.showDefaultEPG, _("Show EPG...")),
				"showEventInfoSingleEPG": (self.showSingleEPG, _("Show single service EPG")),
				"showEventInfoMultiEPG": (self.showMultiEPG, _("Show multi channel EPG")),
				"showEventInfoPlugin": (self.showEventInfoPlugins, _("List EPG functions...")),
				"showEventGuidePlugin": (self.showEventGuidePlugins, _("List EPG functions...")),
				"showInfobarOrEpgWhenInfobarAlreadyVisible": self.showEventInfoWhenNotVisible,
			})

	def getEPGPluginList(self, getAll=False):
		pluginlist = [(p.name, boundFunction(self.runPlugin, p)) for p in plugins.getPlugins(where = PluginDescriptor.WHERE_EVENTINFO) \
				if 'selectedevent' not in p.__call__.func_code.co_varnames]
		if pluginlist:
			from Components.ServiceEventTracker import InfoBarCount
			if getAll or InfoBarCount == 1:
				pluginlist.append((_("Show EPG for current channel..."), self.openSingleServiceEPG))
			pluginlist.append((_("Multi EPG"), self.openMultiServiceEPG))
			pluginlist.append((_("Current event EPG"), self.openEventView))
		return pluginlist

	def getDefaultEPGtype(self):
		pluginlist = self.getEPGPluginList()
		config.usage.defaultEPGType=ConfigSelection(default = "None", choices = pluginlist)
		for plugin in pluginlist:
			if plugin[0] == config.usage.defaultEPGType.value:
				return plugin[1]
		return None

	def getDefaultGuidetype(self):
		pluginlist = self.getEPGPluginList()
		config.usage.defaultGuideType=ConfigSelection(default = "None", choices = pluginlist)
		for plugin in pluginlist:
			if plugin[0] == config.usage.defaultGuideType.value:
				return plugin[1]
		return None

	def showEventInfoWhenNotVisible(self):
		if self.shown:
			self.openEventView()
		else:
			self.toggleShow()
			return 1

	def zapToService(self, service, preview = False, zapback = False):
		if self.servicelist.startServiceRef is None:
			self.servicelist.startServiceRef = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		if service is not None:
			if self.servicelist.getRoot() != self.epg_bouquet: #already in correct bouquet?
				self.servicelist.clearPath()
				if self.servicelist.bouquet_root != self.epg_bouquet:
					self.servicelist.enterPath(self.servicelist.bouquet_root)
				self.servicelist.enterPath(self.epg_bouquet)
			self.servicelist.setCurrentSelection(service) #select the service in servicelist
		if not zapback or preview:
			self.servicelist.zap(enable_pipzap = True)
		if (self.servicelist.dopipzap or zapback) and not preview:
			self.servicelist.zapBack()
		if not preview:
			self.servicelist.startServiceRef = None
			self.servicelist.startRoot = None

	def getBouquetServices(self, bouquet):
		services = [ ]
		servicelist = eServiceCenter.getInstance().list(bouquet)
		if not servicelist is None:
			while True:
				service = servicelist.getNext()
				if not service.valid(): #check if end of list
					break
				if service.flags & (eServiceReference.isDirectory | eServiceReference.isMarker): #ignore non playable services
					continue
				services.append(ServiceReference(service))
		return services

	def openBouquetEPG(self, bouquet, withCallback=True):
		services = self.getBouquetServices(bouquet)
		if services:
			self.epg_bouquet = bouquet
			if withCallback:
				self.dlg_stack.append(self.session.openWithCallback(self.closed, EPGSelection, services, self.zapToService, None, self.changeBouquetCB))
			else:
				self.session.open(EPGSelection, services, self.zapToService, None, self.changeBouquetCB)

	def changeBouquetCB(self, direction, epg):
		if self.bouquetSel:
			if direction > 0:
				self.bouquetSel.down()
			else:
				self.bouquetSel.up()
			bouquet = self.bouquetSel.getCurrent()
			services = self.getBouquetServices(bouquet)
			if services:
				self.epg_bouquet = bouquet
				epg.setServices(services)

	def closed(self, ret=False):
		closedScreen = self.dlg_stack.pop()
		if self.bouquetSel and closedScreen == self.bouquetSel:
			self.bouquetSel = None
		elif self.eventView and closedScreen == self.eventView:
			self.eventView = None
		if ret:
			dlgs=len(self.dlg_stack)
			if dlgs > 0:
				self.dlg_stack[dlgs-1].close(dlgs > 1)

	def openMultiServiceEPG(self, withCallback=True):
		bouquets = self.servicelist.getBouquetList()
		if bouquets is None:
			cnt = 0
		else:
			cnt = len(bouquets)
		if config.usage.multiepg_ask_bouquet.value:
			self.openMultiServiceEPGAskBouquet(bouquets, cnt, withCallback)
		else:
			self.openMultiServiceEPGSilent(bouquets, cnt, withCallback)

	def openMultiServiceEPGAskBouquet(self, bouquets, cnt, withCallback):
		if cnt > 1: # show bouquet list
			if withCallback:
				self.bouquetSel = self.session.openWithCallback(self.closed, BouquetSelector, bouquets, self.openBouquetEPG, enableWrapAround=True)
				self.dlg_stack.append(self.bouquetSel)
			else:
				self.bouquetSel = self.session.open(BouquetSelector, bouquets, self.openBouquetEPG, enableWrapAround=True)
		elif cnt == 1:
			self.openBouquetEPG(bouquets[0][1], withCallback)

	def openMultiServiceEPGSilent(self, bouquets, cnt, withCallback):
		root = self.servicelist.getRoot()
		rootstr = root.toCompareString()
		current = 0
		for bouquet in bouquets:
			if bouquet[1].toCompareString() == rootstr:
				break
			current += 1
		if current >= cnt:
			current = 0
		if cnt > 1: # create bouquet list for bouq+/-
			self.bouquetSel = SilentBouquetSelector(bouquets, True, self.servicelist.getBouquetNumOffset(root))
		if cnt >= 1:
			self.openBouquetEPG(root, withCallback)

	def changeServiceCB(self, direction, epg):
		if self.serviceSel:
			if direction > 0:
				self.serviceSel.nextService()
			else:
				self.serviceSel.prevService()
			epg.setService(self.serviceSel.currentService())

	def SingleServiceEPGClosed(self, ret=False):
		self.serviceSel = None

	def openSingleServiceEPG(self):
		from Components.ServiceEventTracker import InfoBarCount
		if InfoBarCount > 1:
			self.openMultiServiceEPG(False)
		else:
			ref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
			if ref:
				if self.servicelist.getMutableList() is not None: # bouquet in channellist
					current_path = self.servicelist.getRoot()
					services = self.getBouquetServices(current_path)
					self.serviceSel = SimpleServicelist(services)
					if self.serviceSel.selectService(ref):
						self.epg_bouquet = current_path
						self.session.openWithCallback(self.SingleServiceEPGClosed, EPGSelection, ref, self.zapToService, serviceChangeCB = self.changeServiceCB)
					else:
						self.session.openWithCallback(self.SingleServiceEPGClosed, EPGSelection, ref)
				else:
					self.session.open(EPGSelection, ref)

	def runPlugin(self, plugin):
		plugin(session = self.session, servicelist = self.servicelist)

	def showEventInfoPlugins(self):
		pluginlist = self.getEPGPluginList()
		if pluginlist:
			pluginlist.append((_("Select default EPG type..."), self.SelectDefaultInfoPlugin))
			self.session.openWithCallback(self.EventInfoPluginChosen, ChoiceBox, title=_("Please choose an extension..."), list = pluginlist, skin_name = "EPGExtensionsList")
		else:
			self.openSingleServiceEPG()

	def EventInfoPluginChosen(self, answer):
		if answer is not None:
			answer[1]()

	def SelectDefaultInfoPlugin(self):
		self.session.openWithCallback(self.DefaultInfoPluginChosen, ChoiceBox, title=_("Please select a default EPG type..."), list = self.getEPGPluginList(True), skin_name = "EPGExtensionsList")

	def DefaultInfoPluginChosen(self, answer):
		if answer is not None:
			self.defaultEPGType = answer[1]
			config.usage.defaultEPGType.value = answer[0]
			config.usage.defaultEPGType.save()

	def showEventGuidePlugins(self):
		pluginlist = self.getEPGPluginList()
		if pluginlist:
			pluginlist.append((_("Select default EPG type..."), self.SelectDefaultGuidePlugin))
			self.session.openWithCallback(self.EventGuidePluginChosen, ChoiceBox, title=_("Please choose an extension..."), list = pluginlist, skin_name = "EPGExtensionsList")
		else:
			self.openSingleServiceEPG()

	def EventGuidePluginChosen(self, answer):
		if answer is not None:
			answer[1]()

	def SelectDefaultGuidePlugin(self):
		self.session.openWithCallback(self.DefaultGuidePluginChosen, ChoiceBox, title=_("Please select a default EPG type..."), list = self.getEPGPluginList(True), skin_name = "EPGExtensionsList")

	def DefaultGuidePluginChosen(self, answer):
		if answer is not None:
			self.defaultGuideType = answer[1]
			config.usage.defaultGuideType.value = answer[0]
			config.usage.defaultGuideType.save()

	def openSimilarList(self, eventid, refstr):
		self.session.open(EPGSelection, refstr, None, eventid)

	def getNowNext(self):
		epglist = [ ]
		service = self.session.nav.getCurrentService()
		info = service and service.info()
		ptr = info and info.getEvent(0)
		if ptr:
			epglist.append(ptr)
		ptr = info and info.getEvent(1)
		if ptr:
			epglist.append(ptr)
		self.epglist = epglist

	def __evEventInfoChanged(self):
		if self.is_now_next and len(self.dlg_stack) == 1:
			self.getNowNext()
			if self.eventView and self.epglist:
				self.eventView.setEvent(self.epglist[0])

	def showDefaultEPG(self):
		if self.defaultEPGType is not None:
			self.defaultEPGType()
			return
		self.openEventView()

	def showSingleEPG(self):
		if self.defaultGuideType is not None:
			self.defaultGuideType()
			return
		pluginlist = self.getEPGPluginList()
		self.openSingleServiceEPG()

	def showMultiEPG(self):
		if self.defaultGuideType is not None:
			self.defaultGuideType()
			return
		pluginlist = self.getEPGPluginList()
		self.openMultiServiceEPG()		

	def openEventView(self):
		from Components.ServiceEventTracker import InfoBarCount
		if InfoBarCount > 1:
			epglist = [ ]
			self.epglist = epglist
			service = self.session.nav.getCurrentService()
			ref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
			info = service.info()
			ptr=info.getEvent(0)
			if ptr:
				epglist.append(ptr)
			ptr=info.getEvent(1)
			if ptr:
				epglist.append(ptr)
			if epglist:
				self.session.open(EventViewRecording, epglist[0], ServiceReference(ref), self.eventViewCallback, self.openMultiServiceEPG, self.openSimilarList)
		else:
			ref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
			self.getNowNext()
			epglist = self.epglist
			if not epglist:
				self.is_now_next = False
				epg = eEPGCache.getInstance()
				ptr = ref and ref.valid() and epg.lookupEventTime(ref, -1)
				if ptr:
					epglist.append(ptr)
					ptr = epg.lookupEventTime(ref, ptr.getBeginTime(), +1)
					if ptr:
						epglist.append(ptr)
			else:
				self.is_now_next = True
			if epglist:
				self.eventView = self.session.openWithCallback(self.closed, EventViewEPGSelect, epglist[0], ServiceReference(ref), self.eventViewCallback, self.openSingleServiceEPG, self.openMultiServiceEPG, self.openSimilarList)
				self.dlg_stack.append(self.eventView)
		if not epglist:
			print "no epg for the service avail.. so we show multiepg instead of eventinfo"
			self.openMultiServiceEPG(False)

	def eventViewCallback(self, setEvent, setService, val): #used for now/next displaying
		epglist = self.epglist
		if len(epglist) > 1:
			tmp = epglist[0]
			epglist[0]=epglist[1]
			epglist[1]=tmp
			setEvent(epglist[0])

class InfoBarRdsDecoder:
	"""provides RDS and Rass support/display"""
	def __init__(self):
		self.rds_display = self.session.instantiateDialog(RdsInfoDisplay)
		self.session.instantiateSummaryDialog(self.rds_display)
		self.rass_interactive = None

		self.__event_tracker = ServiceEventTracker(screen=self, eventmap=
			{
				iPlayableService.evEnd: self.__serviceStopped,
				iPlayableService.evUpdatedRassSlidePic: self.RassSlidePicChanged
			})

		self["RdsActions"] = ActionMap(["InfobarRdsActions"],
		{
			"startRassInteractive": self.startRassInteractive
		},-1)

		self["RdsActions"].setEnabled(False)

		self.onLayoutFinish.append(self.rds_display.show)
		self.rds_display.onRassInteractivePossibilityChanged.append(self.RassInteractivePossibilityChanged)

	def RassInteractivePossibilityChanged(self, state):
		self["RdsActions"].setEnabled(state)

	def RassSlidePicChanged(self):
		if not self.rass_interactive:
			service = self.session.nav.getCurrentService()
			decoder = service and service.rdsDecoder()
			if decoder:
				decoder.showRassSlidePicture()

	def __serviceStopped(self):
		if self.rass_interactive is not None:
			rass_interactive = self.rass_interactive
			self.rass_interactive = None
			rass_interactive.close()

	def startRassInteractive(self):
		self.rds_display.hide()
		self.rass_interactive = self.session.openWithCallback(self.RassInteractiveClosed, RassInteractive)

	def RassInteractiveClosed(self, *val):
		if self.rass_interactive is not None:
			self.rass_interactive = None
			self.RassSlidePicChanged()
		self.rds_display.show()

class InfoBarSeek:
	"""handles actions like seeking, pause"""

	SEEK_STATE_PLAY = (0, 0, 0, ">")
	SEEK_STATE_PAUSE = (1, 0, 0, "||")
	SEEK_STATE_EOF = (1, 0, 0, "END")

	def __init__(self, actionmap = "InfobarSeekActions"):
		self.__event_tracker = ServiceEventTracker(screen=self, eventmap=
			{
				iPlayableService.evSeekableStatusChanged: self.__seekableStatusChanged,
				iPlayableService.evStart: self.__serviceStarted,
				iPlayableService.evEOF: self.__evEOF,
				iPlayableService.evSOF: self.__evSOF,
			})
		self.fast_winding_hint_message_showed = False

		class InfoBarSeekActionMap(HelpableActionMap):
			def __init__(self, screen, *args, **kwargs):
				HelpableActionMap.__init__(self, screen, *args, **kwargs)
				self.screen = screen

			def action(self, contexts, action):
				print "action:", action
				if action[:5] == "seek:":
					time = int(action[5:])
					self.screen.doSeekRelative(time * 90000)
					return 1
				elif action[:8] == "seekdef:":
					key = int(action[8:])
					time = (-config.seek.selfdefined_13.value, False, config.seek.selfdefined_13.value,
						-config.seek.selfdefined_46.value, False, config.seek.selfdefined_46.value,
						-config.seek.selfdefined_79.value, False, config.seek.selfdefined_79.value)[key-1]
					self.screen.doSeekRelative(time * 90000)
					return 1
				else:
					return HelpableActionMap.action(self, contexts, action)

		self["SeekActions"] = InfoBarSeekActionMap(self, actionmap,
			{
				"playpauseService": self.playpauseService,
				"pauseService": (self.pauseService, _("Pause playback")),
				"unPauseService": (self.unPauseService, _("Continue playback")),

				"seekFwd": (self.seekFwd, _("Seek forward")),
				"seekFwdManual": (self.seekFwdManual, _("Seek forward (enter time)")),
				"seekBack": (self.seekBack, _("Seek backward")),
				"seekBackManual": (self.seekBackManual, _("Seek backward (enter time)")),
				"jumpPreviousMark": (self.seekPreviousMark, _("Jump to previous marked position")),
				"jumpNextMark": (self.seekNextMark, _("Jump to next marked position")),
			}, prio=-1)
			# give them a little more priority to win over color buttons

		self["SeekActions"].setEnabled(False)

		self.seekstate = self.SEEK_STATE_PLAY
		self.lastseekstate = self.SEEK_STATE_PLAY

		self.onPlayStateChanged = [ ]

		self.lockedBecauseOfSkipping = False

		self.__seekableStatusChanged()

	def makeStateForward(self, n):
		return (0, n, 0, ">> %dx" % n)

	def makeStateBackward(self, n):
		return (0, -n, 0, "<< %dx" % n)

	def makeStateSlowMotion(self, n):
		return (0, 0, n, "/%d" % n)

	def isStateForward(self, state):
		return state[1] > 1

	def isStateBackward(self, state):
		return state[1] < 0

	def isStateSlowMotion(self, state):
		return state[1] == 0 and state[2] > 1

	def getHigher(self, n, lst):
		for x in lst:
			if x > n:
				return x
		return False

	def getLower(self, n, lst):
		lst = lst[:]
		lst.reverse()
		for x in lst:
			if x < n:
				return x
		return False

	def showAfterSeek(self):
		if isinstance(self, InfoBarShowHide):
			self.doShow()

	def up(self):
		pass

	def down(self):
		pass

	def getSeek(self):
		service = self.session.nav.getCurrentService()
		if service is None:
			return None

		seek = service.seek()

		if seek is None or not seek.isCurrentlySeekable():
			return None

		return seek

	def isSeekable(self):
		if self.getSeek() is None or (isStandardInfoBar(self) and not self.timeshiftEnabled()):
			return False
		return True

	def __seekableStatusChanged(self):
#		print "seekable status changed!"
		if not self.isSeekable():
			self["SeekActions"].setEnabled(False)
#			print "not seekable, return to play"
			self.setSeekState(self.SEEK_STATE_PLAY)
		else:
			self["SeekActions"].setEnabled(True)
#			print "seekable"

	def __serviceStarted(self):
		self.fast_winding_hint_message_showed = False
		self.setSeekState(self.SEEK_STATE_PLAY)
		self.__seekableStatusChanged()

	def setSeekState(self, state):
		service = self.session.nav.getCurrentService()

		if service is None:
			return False

		if not self.isSeekable():
			if state not in (self.SEEK_STATE_PLAY, self.SEEK_STATE_PAUSE):
				state = self.SEEK_STATE_PLAY

		pauseable = service.pause()

		if pauseable is None:
			print "not pauseable."
			state = self.SEEK_STATE_PLAY

		self.seekstate = state

		if pauseable is not None:
			if self.seekstate[0]:
				print "resolved to PAUSE"
				pauseable.pause()
			elif self.seekstate[1]:
				if not pauseable.setFastForward(self.seekstate[1]):
					print "resolved to FAST FORWARD"
				else:
					self.seekstate = self.SEEK_STATE_PLAY
					print "FAST FORWARD not possible: resolved to PLAY"
			elif self.seekstate[2]:
				if not pauseable.setSlowMotion(self.seekstate[2]):
					print "resolved to SLOW MOTION"
				else:
					self.seekstate = self.SEEK_STATE_PAUSE
					print "SLOW MOTION not possible: resolved to PAUSE"
			else:
				print "resolved to PLAY"
				pauseable.unpause()

		for c in self.onPlayStateChanged:
			c(self.seekstate)

		self.checkSkipShowHideLock()

		if hasattr(self, "ScreenSaverTimerStart"):
			self.ScreenSaverTimerStart()

		return True

	def playpauseService(self):
		if self.seekstate != self.SEEK_STATE_PLAY:
			self.unPauseService()
		else:
			self.pauseService()

	def pauseService(self):
		if self.seekstate == self.SEEK_STATE_PAUSE:
			if config.seek.on_pause.value == "play":
				self.unPauseService()
			elif config.seek.on_pause.value == "step":
				self.doSeekRelative(1)
			elif config.seek.on_pause.value == "last":
				self.setSeekState(self.lastseekstate)
				self.lastseekstate = self.SEEK_STATE_PLAY
		else:
			if self.seekstate != self.SEEK_STATE_EOF:
				self.lastseekstate = self.seekstate
			self.setSeekState(self.SEEK_STATE_PAUSE)

	def unPauseService(self):
		print "unpause"
		if self.seekstate == self.SEEK_STATE_PLAY:
			return 0
		self.setSeekState(self.SEEK_STATE_PLAY)

	def doSeek(self, pts):
		seekable = self.getSeek()
		if seekable is None:
			return
		seekable.seekTo(pts)

	def doSeekRelative(self, pts):
		seekable = self.getSeek()
		if seekable is None:
			return
		prevstate = self.seekstate

		if self.seekstate == self.SEEK_STATE_EOF:
			if prevstate == self.SEEK_STATE_PAUSE:
				self.setSeekState(self.SEEK_STATE_PAUSE)
			else:
				self.setSeekState(self.SEEK_STATE_PLAY)
		seekable.seekRelative(pts<0 and -1 or 1, abs(pts))
		if abs(pts) > 100 and config.usage.show_infobar_on_skip.value:
			self.showAfterSeek()

	def seekFwd(self):
		seek = self.getSeek()
		if seek and not (seek.isCurrentlySeekable() & 2):
			if not self.fast_winding_hint_message_showed and (seek.isCurrentlySeekable() & 1):
				self.session.open(MessageBox, _("No fast winding possible yet.. but you can use the number buttons to skip forward/backward!"), MessageBox.TYPE_INFO, timeout=10)
				self.fast_winding_hint_message_showed = True
				return
			return 0 # trade as unhandled action
		if self.seekstate == self.SEEK_STATE_PLAY:
			self.setSeekState(self.makeStateForward(int(config.seek.enter_forward.value)))
		elif self.seekstate == self.SEEK_STATE_PAUSE:
			if len(config.seek.speeds_slowmotion.value):
				self.setSeekState(self.makeStateSlowMotion(config.seek.speeds_slowmotion.value[-1]))
			else:
				self.setSeekState(self.makeStateForward(int(config.seek.enter_forward.value)))
		elif self.seekstate == self.SEEK_STATE_EOF:
			pass
		elif self.isStateForward(self.seekstate):
			speed = self.seekstate[1]
			if self.seekstate[2]:
				speed /= self.seekstate[2]
			speed = self.getHigher(speed, config.seek.speeds_forward.value) or config.seek.speeds_forward.value[-1]
			self.setSeekState(self.makeStateForward(speed))
		elif self.isStateBackward(self.seekstate):
			speed = -self.seekstate[1]
			if self.seekstate[2]:
				speed /= self.seekstate[2]
			speed = self.getLower(speed, config.seek.speeds_backward.value)
			if speed:
				self.setSeekState(self.makeStateBackward(speed))
			else:
				self.setSeekState(self.SEEK_STATE_PLAY)
		elif self.isStateSlowMotion(self.seekstate):
			speed = self.getLower(self.seekstate[2], config.seek.speeds_slowmotion.value) or config.seek.speeds_slowmotion.value[0]
			self.setSeekState(self.makeStateSlowMotion(speed))

	def seekBack(self):
		seek = self.getSeek()
		if seek and not (seek.isCurrentlySeekable() & 2):
			if not self.fast_winding_hint_message_showed and (seek.isCurrentlySeekable() & 1):
				self.session.open(MessageBox, _("No fast winding possible yet.. but you can use the number buttons to skip forward/backward!"), MessageBox.TYPE_INFO, timeout=10)
				self.fast_winding_hint_message_showed = True
				return
			return 0 # trade as unhandled action
		seekstate = self.seekstate
		if seekstate == self.SEEK_STATE_PLAY:
			self.setSeekState(self.makeStateBackward(int(config.seek.enter_backward.value)))
		elif seekstate == self.SEEK_STATE_EOF:
			self.setSeekState(self.makeStateBackward(int(config.seek.enter_backward.value)))
			self.doSeekRelative(-6)
		elif seekstate == self.SEEK_STATE_PAUSE:
			self.doSeekRelative(-1)
		elif self.isStateForward(seekstate):
			speed = seekstate[1]
			if seekstate[2]:
				speed /= seekstate[2]
			speed = self.getLower(speed, config.seek.speeds_forward.value)
			if speed:
				self.setSeekState(self.makeStateForward(speed))
			else:
				self.setSeekState(self.SEEK_STATE_PLAY)
		elif self.isStateBackward(seekstate):
			speed = -seekstate[1]
			if seekstate[2]:
				speed /= seekstate[2]
			speed = self.getHigher(speed, config.seek.speeds_backward.value) or config.seek.speeds_backward.value[-1]
			self.setSeekState(self.makeStateBackward(speed))
		elif self.isStateSlowMotion(seekstate):
			speed = self.getHigher(seekstate[2], config.seek.speeds_slowmotion.value)
			if speed:
				self.setSeekState(self.makeStateSlowMotion(speed))
			else:
				self.setSeekState(self.SEEK_STATE_PAUSE)

	def seekFwdManual(self):
		self.session.openWithCallback(self.fwdSeekTo, MinuteInput)

	def fwdSeekTo(self, minutes):
		print "Seek", minutes, "minutes forward"
		self.doSeekRelative(minutes * 60 * 90000)

	def seekBackManual(self):
		self.session.openWithCallback(self.rwdSeekTo, MinuteInput)

	def rwdSeekTo(self, minutes):
		print "rwdSeekTo"
		self.doSeekRelative(-minutes * 60 * 90000)

	def checkSkipShowHideLock(self):
		wantlock = self.seekstate != self.SEEK_STATE_PLAY

		if config.usage.show_infobar_on_skip.value:
			if self.lockedBecauseOfSkipping and not wantlock:
				self.unlockShow()
				self.lockedBecauseOfSkipping = False

			if wantlock and not self.lockedBecauseOfSkipping:
				self.lockShow()
				self.lockedBecauseOfSkipping = True

	def calcRemainingTime(self):
		seekable = self.getSeek()
		if seekable is not None:
			len = seekable.getLength()
			try:
				tmp = self.cueGetEndCutPosition()
				if tmp:
					len = (False, tmp)
			except:
				pass
			pos = seekable.getPlayPosition()
			speednom = self.seekstate[1] or 1
			speedden = self.seekstate[2] or 1
			if not len[0] and not pos[0]:
				if len[1] <= pos[1]:
					return 0
				time = (len[1] - pos[1])*speedden/(90*speednom)
				return time
		return False

	def __evEOF(self):
		if self.seekstate == self.SEEK_STATE_EOF:
			return

		# if we are seeking forward, we try to end up ~1s before the end, and pause there.
		seekstate = self.seekstate
		if self.seekstate != self.SEEK_STATE_PAUSE:
			self.setSeekState(self.SEEK_STATE_EOF)

		if seekstate not in (self.SEEK_STATE_PLAY, self.SEEK_STATE_PAUSE): # if we are seeking
			seekable = self.getSeek()
			if seekable is not None:
				seekable.seekTo(-1)
		if seekstate == self.SEEK_STATE_PLAY: # regular EOF
			self.doEofInternal(True)
		else:
			self.doEofInternal(False)

	def doEofInternal(self, playing):
		pass		# Defined in subclasses

	def __evSOF(self):
		self.setSeekState(self.SEEK_STATE_PLAY)
		self.doSeek(0)

	# This is needed, because some Mediaplayer use InfoBarSeek but not InfoBarCueSheetSupport
	def seekPreviousMark(self):
		if isinstance(self, InfoBarCueSheetSupport):
			self.jumpPreviousMark()

	def seekNextMark(self):
		if isinstance(self, InfoBarCueSheetSupport):
			self.jumpNextMark()

from Screens.PVRState import PVRState, TimeshiftState

class InfoBarPVRState:
	def __init__(self, screen=PVRState, force_show = False):
		self.onPlayStateChanged.append(self.__playStateChanged)
		self.pvrStateDialog = self.session.instantiateDialog(screen)
		self.onShow.append(self._mayShow)
		self.onHide.append(self.pvrStateDialog.hide)
		self.force_show = force_show

	def _mayShow(self):
		if self.shown and self.seekstate != self.SEEK_STATE_PLAY:
			self.pvrStateDialog.show()

	def __playStateChanged(self, state):
		playstateString = state[3]
		self.pvrStateDialog["state"].setText(playstateString)

		# if we return into "PLAY" state, ensure that the dialog gets hidden if there will be no infobar displayed
		if not config.usage.show_infobar_on_skip.value and self.seekstate == self.SEEK_STATE_PLAY and not self.force_show:
			self.pvrStateDialog.hide()
		else:
			self._mayShow()

class InfoBarTimeshiftState(InfoBarPVRState):
	def __init__(self):
		InfoBarPVRState.__init__(self, screen=TimeshiftState, force_show = True)
		self.__hideTimer = eTimer()
		self.__hideTimer.callback.append(self.__hideTimeshiftState)

	def _mayShow(self):
		if self.shown and self.timeshiftEnabled():
			self.pvrStateDialog.show()
			if self.seekstate == self.SEEK_STATE_PLAY and not self.shown:
				self.__hideTimer.start(5*1000, True)

	def __hideTimeshiftState(self):
		self.pvrStateDialog.hide()

class InfoBarShowMovies:

	# i don't really like this class.
	# it calls a not further specified "movie list" on up/down/movieList,
	# so this is not more than an action map
	def __init__(self):
		self["MovieListActions"] = HelpableActionMap(self, "InfobarMovieListActions",
			{
				"movieList": (self.showMovies, _("Open the movie list")),
				"up": (self.up, _("Open the movie list")),
				"down": (self.down, _("Open the movie list"))
			})

# InfoBarTimeshift requires InfoBarSeek, instantiated BEFORE!

# Hrmf.
#
# Timeshift works the following way:
#                                         demux0   demux1                    "TimeshiftActions" "TimeshiftActivateActions" "SeekActions"
# - normal playback                       TUNER    unused      PLAY               enable                disable              disable
# - user presses "yellow" button.         FILE     record      PAUSE              enable                disable              enable
# - user presess pause again              FILE     record      PLAY               enable                disable              enable
# - user fast forwards                    FILE     record      FF                 enable                disable              enable
# - end of timeshift buffer reached       TUNER    record      PLAY               enable                enable               disable
# - user backwards                        FILE     record      BACK  # !!         enable                disable              enable
#

# in other words:
# - when a service is playing, pressing the "timeshiftStart" button ("yellow") enables recording ("enables timeshift"),
# freezes the picture (to indicate timeshift), sets timeshiftMode ("activates timeshift")
# now, the service becomes seekable, so "SeekActions" are enabled, "TimeshiftEnableActions" are disabled.
# - the user can now PVR around
# - if it hits the end, the service goes into live mode ("deactivates timeshift", it's of course still "enabled")
# the service looses it's "seekable" state. It can still be paused, but just to activate timeshift right
# after!
# the seek actions will be disabled, but the timeshiftActivateActions will be enabled
# - if the user rewinds, or press pause, timeshift will be activated again

# note that a timeshift can be enabled ("recording") and
# activated (currently time-shifting).

class InfoBarTimeshift:
	def __init__(self):
		self["TimeshiftActions"] = HelpableActionMap(self, "InfobarTimeshiftActions",
			{
				"timeshiftStart": (self.startTimeshift, _("Start timeshift")),  # the "yellow key"
				"timeshiftStop": (self.stopTimeshift, _("Stop timeshift"))      # currently undefined :), probably 'TV'
			}, prio=1)
		self["TimeshiftActivateActions"] = ActionMap(["InfobarTimeshiftActivateActions"],
			{
				"timeshiftActivateEnd": self.activateTimeshiftEnd, # something like "rewind key"
				"timeshiftActivateEndAndPause": self.activateTimeshiftEndAndPause  # something like "pause key"
			}, prio=-1) # priority over record

		self["TimeshiftActivateActions"].setEnabled(False)
		self.ts_rewind_timer = eTimer()
		self.ts_rewind_timer.callback.append(self.rewindService)
		self.ts_start_delay_timer = eTimer()
		self.ts_start_delay_timer.callback.append(self.startTimeshiftWithoutPause)
		self.save_timeshift_file = False
		self.timeshift_was_activated = False

		self.__event_tracker = ServiceEventTracker(screen=self, eventmap=
			{
				iPlayableService.evStart: self.__serviceStarted,
				iPlayableService.evSeekableStatusChanged: self.__seekableStatusChanged,
				iPlayableService.evEnd: self.__serviceEnd
			})

	def getTimeshift(self):
		service = self.session.nav.getCurrentService()
		return service and service.timeshift()

	def timeshiftEnabled(self):
		ts = self.getTimeshift()
		return ts and ts.isTimeshiftEnabled()

	def startTimeshift(self, pauseService = True):
		print "enable timeshift"
		ts = self.getTimeshift()
		if ts is None:
			if not pauseService and not int(config.usage.timeshift_start_delay.value):
				self.session.open(MessageBox, _("Timeshift not possible!"), MessageBox.TYPE_ERROR, simple = True)
			print "no ts interface"
			return 0

		if ts.isTimeshiftEnabled():
			print "hu, timeshift already enabled?"
		else:
			if not ts.startTimeshift():
				# we remove the "relative time" for now.
				#self.pvrStateDialog["timeshift"].setRelative(time.time())

				if pauseService:
					# PAUSE.
					#self.setSeekState(self.SEEK_STATE_PAUSE)
					self.activateTimeshiftEnd(False)

				# enable the "TimeshiftEnableActions", which will override
				# the startTimeshift actions
				self.__seekableStatusChanged()

				# get current timeshift filename and calculate new
				self.save_timeshift_file = False
				self.save_timeshift_in_movie_dir = False
				self.current_timeshift_filename = ts.getTimeshiftFilename()
				self.new_timeshift_filename = self.generateNewTimeshiftFileName()
			else:
				print "timeshift failed"

	def startTimeshiftWithoutPause(self):
		self.startTimeshift(False)

	def stopTimeshift(self):
		ts = self.getTimeshift()
		if ts and ts.isTimeshiftEnabled():
			if int(config.usage.timeshift_start_delay.value):
				ts.switchToLive()
			else:
				self.checkTimeshiftRunning(self.stopTimeshiftcheckTimeshiftRunningCallback)
		else:
			return 0

	def stopTimeshiftcheckTimeshiftRunningCallback(self, answer):
		ts = self.getTimeshift()
		if answer and ts:
			ts.stopTimeshift()
			self.pvrStateDialog.hide()

			# disable actions
			self.__seekableStatusChanged()

	# activates timeshift, and seeks to (almost) the end
	def activateTimeshiftEnd(self, back = True):
		ts = self.getTimeshift()
		print "activateTimeshiftEnd"

		if ts is None:
			return

		if ts.isTimeshiftActive():
			print "!! activate timeshift called - but shouldn't this be a normal pause?"
			self.pauseService()
		else:
			print "play, ..."
			ts.activateTimeshift() # activate timeshift will automatically pause
			self.setSeekState(self.SEEK_STATE_PAUSE)
			seekable = self.getSeek()
			if seekable is not None:
				seekable.seekTo(-90000) # seek approx. 1 sec before end
			self.timeshift_was_activated = True
		if back:
			self.ts_rewind_timer.start(200, 1)

	def rewindService(self):
		self.setSeekState(self.makeStateBackward(int(config.seek.enter_backward.value)))

	# generates only filename without path
	def generateNewTimeshiftFileName(self):
		name = "timeshift record"
		info = { }
		self.getProgramInfoAndEvent(info, name)

		serviceref = info["serviceref"]

		service_name = ""
		if isinstance(serviceref, eServiceReference):
			service_name = ServiceReference(serviceref).getServiceName()
		begin_date = strftime("%Y%m%d %H%M", localtime(time()))
		filename = begin_date + " - " + service_name

		if config.recording.filename_composition.value == "short":
			filename = strftime("%Y%m%d", localtime(time())) + " - " + info["name"]
		elif config.recording.filename_composition.value == "long":
			filename += " - " + info["name"] + " - " + info["description"]
		else:
			filename += " - " + info["name"] # standard

		if config.recording.ascii_filenames.value:
			filename = ASCIItranslit.legacyEncode(filename)

		print "New timeshift filename: ", filename
		return filename

	# same as activateTimeshiftEnd, but pauses afterwards.
	def activateTimeshiftEndAndPause(self):
		print "activateTimeshiftEndAndPause"
		#state = self.seekstate
		self.activateTimeshiftEnd(False)

	def __seekableStatusChanged(self):
		self["TimeshiftActivateActions"].setEnabled(not self.isSeekable() and self.timeshiftEnabled())
		state = self.getSeek() is not None and self.timeshiftEnabled()
		self["SeekActions"].setEnabled(state)
		if not state:
			self.setSeekState(self.SEEK_STATE_PLAY)
		self.restartSubtitle()

	def __serviceStarted(self):
		self.pvrStateDialog.hide()
		self.__seekableStatusChanged()
		if self.ts_start_delay_timer.isActive():
			self.ts_start_delay_timer.stop()
		if int(config.usage.timeshift_start_delay.value):
			self.ts_start_delay_timer.start(int(config.usage.timeshift_start_delay.value) * 1000, True)

	def checkTimeshiftRunning(self, returnFunction):
		if self.timeshiftEnabled() and config.usage.check_timeshift.value and self.timeshift_was_activated:
			message = _("Stop timeshift?")
			if not self.save_timeshift_file:
				choice = [(_("yes"), "stop"), (_("no"), "continue"), (_("Yes and save"), "save"), (_("Yes and save in movie dir"), "save_movie")]
			else:
				choice = [(_("yes"), "stop"), (_("no"), "continue")]
				message += "\n" + _("Reminder, you have chosen to save timeshift file.")
			self.session.openWithCallback(boundFunction(self.checkTimeshiftRunningCallback, returnFunction), MessageBox, message, simple = True, list = choice)
		else:
			returnFunction(True)

	def checkTimeshiftRunningCallback(self, returnFunction, answer):
		if answer:
			if "movie" in answer:
				self.save_timeshift_in_movie_dir = True
			if "save" in answer:
				self.save_timeshift_file = True
				ts = self.getTimeshift()
				if ts:
					ts.saveTimeshiftFile()
					del ts
			if "continue" not in answer:
				self.saveTimeshiftFiles()
		returnFunction(answer and answer != "continue")

	# renames/moves timeshift files if requested
	def __serviceEnd(self):
		self.saveTimeshiftFiles()
		self.timeshift_was_activated = False

	def saveTimeshiftFiles(self):
		if self.save_timeshift_file and self.current_timeshift_filename and self.new_timeshift_filename:
			if config.usage.timeshift_path.value and not self.save_timeshift_in_movie_dir:
				dirname = config.usage.timeshift_path.value
			else:
				dirname = defaultMoviePath()
			filename = getRecordingFilename(self.new_timeshift_filename, dirname) + ".ts"

			fileList = []
			fileList.append((self.current_timeshift_filename, filename))
			if fileExists(self.current_timeshift_filename + ".sc"):
				fileList.append((self.current_timeshift_filename + ".sc", filename + ".sc"))
			if fileExists(self.current_timeshift_filename + ".cuts"):
				fileList.append((self.current_timeshift_filename + ".cuts", filename + ".cuts"))

			moveFiles(fileList)
			self.save_timeshift_file = False

from Screens.PiPSetup import PiPSetup

class InfoBarExtensions:
	EXTENSION_SINGLE = 0
	EXTENSION_LIST = 1

	def __init__(self):
		self.list = []

		self["InstantExtensionsActions"] = HelpableActionMap(self, "InfobarExtensions",
			{
				"extensions": (self.showExtensionSelection, _("Show extensions...")),
			}, 1) # lower priority

	def addExtension(self, extension, key = None, type = EXTENSION_SINGLE):
		self.list.append((type, extension, key))

	def updateExtension(self, extension, key = None):
		self.extensionsList.append(extension)
		if key is not None:
			if self.extensionKeys.has_key(key):
				key = None

		if key is None:
			for x in self.availableKeys:
				if not self.extensionKeys.has_key(x):
					key = x
					break

		if key is not None:
			self.extensionKeys[key] = len(self.extensionsList) - 1

	def updateExtensions(self):
		self.extensionsList = []
		self.availableKeys = [ "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "red", "green", "yellow", "blue" ]
		self.extensionKeys = {}
		for x in self.list:
			if x[0] == self.EXTENSION_SINGLE:
				self.updateExtension(x[1], x[2])
			else:
				for y in x[1]():
					self.updateExtension(y[0], y[1])

	def showExtensionSelection(self):
		self.updateExtensions()
		extensionsList = self.extensionsList[:]
		keys = []
		list = []
		for x in self.availableKeys:
			if self.extensionKeys.has_key(x):
				entry = self.extensionKeys[x]
				extension = self.extensionsList[entry]
				if extension[2]():
					name = str(extension[0]())
					list.append((extension[0](), extension))
					keys.append(x)
					extensionsList.remove(extension)
				else:
					extensionsList.remove(extension)
		list.extend([(x[0](), x) for x in extensionsList])

		keys += [""] * len(extensionsList)
		self.session.openWithCallback(self.extensionCallback, ChoiceBox, title=_("Please choose an extension..."), list = list, keys = keys, skin_name = "ExtensionsList")

	def extensionCallback(self, answer):
		if answer is not None:
			answer[1][1]()

from Tools.BoundFunction import boundFunction
import inspect

# depends on InfoBarExtensions

class InfoBarPlugins:
	def __init__(self):
		self.addExtension(extension = self.getPluginList, type = InfoBarExtensions.EXTENSION_LIST)

	def getPluginName(self, name):
		return name

	def getPluginList(self):
		l = []
		for p in plugins.getPlugins(where = PluginDescriptor.WHERE_EXTENSIONSMENU):
			args = inspect.getargspec(p.__call__)[0]
			if len(args) == 1 or len(args) == 2 and isinstance(self, InfoBarChannelSelection):
				l.append(((boundFunction(self.getPluginName, p.name), boundFunction(self.runPlugin, p), lambda: True), None, p.name))
		l.sort(key = lambda e: e[2]) # sort by name
		return l

	def runPlugin(self, plugin):
		if isinstance(self, InfoBarChannelSelection):
			plugin(session = self.session, servicelist = self.servicelist)
		else:
			plugin(session = self.session)

from Components.Task import job_manager
class InfoBarJobman:
	def __init__(self):
		self.addExtension(extension = self.getJobList, type = InfoBarExtensions.EXTENSION_LIST)

	def getJobList(self):
		return [((boundFunction(self.getJobName, job), boundFunction(self.showJobView, job), lambda: True), None) for job in job_manager.getPendingJobs()]

	def getJobName(self, job):
		return "%s: %s (%d%%)" % (job.getStatustext(), job.name, int(100*job.progress/float(job.end)))

	def showJobView(self, job):
		from Screens.TaskView import JobView
		job_manager.in_background = False
		self.session.openWithCallback(self.JobViewCB, JobView, job)

	def JobViewCB(self, in_background):
		job_manager.in_background = in_background

# depends on InfoBarExtensions
class InfoBarPiP:
	def __init__(self):
		try:
			self.session.pipshown
		except:
			self.session.pipshown = False
		if SystemInfo.get("NumVideoDecoders", 1) > 1:
			self["PiPActions"] = HelpableActionMap(self, "InfobarPiPActions",
				{
					"activatePiP": (self.activePiP, _("Activate PiP")),
				})
			if (self.allowPiP):
				self.addExtension((self.getShowHideName, self.showPiP, lambda: True), "blue")
				self.addExtension((self.getMoveName, self.movePiP, self.pipShown), "green")
				self.addExtension((self.getSwapName, self.swapPiP, self.pipShown), "yellow")
				self.addExtension((self.getTogglePipzapName, self.togglePipzap, lambda: True), "red")
			else:
				self.addExtension((self.getShowHideName, self.showPiP, self.pipShown), "blue")
				self.addExtension((self.getMoveName, self.movePiP, self.pipShown), "green")

		self.onExecBegin.append(self.reclocatePiP)

	def reclocatePiP(self):
		if self.session.pipshown and config.av.pip_mode.value not in "standard external":
			self.relocatePiPTimer = eTimer()
			self.relocatePiPTimer.callback.append(self.relocatePiPTimeout)
			self.relocatePiPTimer.start(100, True)

	def relocatePiPTimeout(self):
		if self.session.pipshown:
			self.session.pip.relocate()

	def pipShown(self):
		return self.session.pipshown

	def pipHandles0Action(self):
		return self.pipShown() and config.usage.pip_zero_button.value != "standard"

	def getShowHideName(self):
		if self.session.pipshown:
			return _("Disable Picture in Picture")
		else:
			return _("Activate Picture in Picture")

	def getSwapName(self):
		return _("Swap services")

	def getMoveName(self):
		return _("Move Picture in Picture")

	def getTogglePipzapName(self):
		slist = self.servicelist
		if slist and slist.dopipzap:
			return _("Zap focus to main screen")
		return _("Zap focus to Picture in Picture")

	def togglePipzap(self):
		if not self.session.pipshown:
			self.showPiP()
		slist = self.servicelist
		if slist and self.session.pipshown:
			slist.togglePipzap()
			if slist.dopipzap:
				currentServicePath = slist.getCurrentServicePath()
				self.servicelist.setCurrentServicePath(self.session.pip.servicePath, doZap=False)
				self.session.pip.servicePath = currentServicePath

	def showPiP(self):
		if self.session.pipshown:
			slist = self.servicelist
			if slist and slist.dopipzap:
				self.togglePipzap()
			if self.session.pipshown:
				del self.session.pip
				self.session.pipshown = False
		else:
			self.session.pip = self.session.instantiateDialog(PictureInPicture)
			self.session.pip.show()
			newservice = self.session.nav.getCurrentlyPlayingServiceReference() or self.servicelist.servicelist.getCurrent()
			if self.session.pip.playService(newservice):
				self.session.pipshown = True
				self.session.pip.servicePath = self.servicelist.getCurrentServicePath()
				self.reclocatePiP()
			else:
				self.session.pipshown = False
				del self.session.pip

	def activePiP(self):
		if self.session.pipshown:
			self.togglePipzap()
		else:
			self.showPiP()

	def swapPiP(self):
		swapservice = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		pipref = self.session.pip.getCurrentService()
		if swapservice and pipref and pipref.toString() != swapservice.toString():
			currentServicePath = self.servicelist.getCurrentServicePath()
			self.servicelist.setCurrentServicePath(self.session.pip.servicePath, doZap=False)
			self.session.pip.playService(swapservice)
			self.session.nav.playService(pipref, checkParentalControl=False, adjust=False)
			self.session.pip.servicePath = currentServicePath
			if self.servicelist.dopipzap:
				# This unfortunately won't work with subservices
				self.servicelist.setCurrentSelection(self.session.pip.getCurrentService())

	def movePiP(self):
		self.session.open(PiPSetup, pip = self.session.pip)

	def pipDoHandle0Action(self):
		use = config.usage.pip_zero_button.value
		if "swap" == use:
			self.swapPiP()
		elif "swapstop" == use:
			self.swapPiP()
			self.showPiP()
		elif "stop" == use:
			self.showPiP()

from RecordTimer import parseEvent, RecordTimerEntry

class InfoBarInstantRecord:
	"""Instant Record - handles the instantRecord action in order to
	start/stop instant records"""
	def __init__(self):
		self["InstantRecordActions"] = HelpableActionMap(self, "InfobarInstantRecord",
			{
				"instantRecord": (self.instantRecord, _("Instant recording...")),
			})
		if isStandardInfoBar(self):
			self.recording = []
		else:
			from Screens.InfoBar import InfoBar
			InfoBarInstance = InfoBar.instance
			if InfoBarInstance:
				self.recording = InfoBarInstance.recording

	def stopCurrentRecording(self, entry = -1):
		if entry is not None and entry != -1:
			self.session.nav.RecordTimer.removeEntry(self.recording[entry])
			self.recording.remove(self.recording[entry])

	def getProgramInfoAndEvent(self, info, name):
		info["serviceref"] = self.session.nav.getCurrentlyPlayingServiceOrGroup()

		# try to get event info
		event = None
		try:
			service = self.session.nav.getCurrentService()
			epg = eEPGCache.getInstance()
			event = epg.lookupEventTime(info["serviceref"], -1, 0)
			if event is None:
				event = service.info().getEvent(0)
		except:
			pass

		info["event"] = event
		info["name"]  = name
		info["description"] = ""
		info["eventid"] = None

		if event is not None:
			curEvent = parseEvent(event)
			info["name"] = curEvent[2]
			info["description"] = curEvent[3]
			info["eventid"] = curEvent[4]
			info["end"] = curEvent[1]


	def startInstantRecording(self, limitEvent = False):
		begin = int(time())
		end = begin + 3600      # dummy
		name = "instant record"
		info = { }

		self.getProgramInfoAndEvent(info, name)
		serviceref = info["serviceref"]
		event = info["event"]

		if event is not None:
			if limitEvent:
				end = info["end"]
		else:
			if limitEvent:
				self.session.open(MessageBox, _("No event info found, recording indefinitely."), MessageBox.TYPE_INFO)

		if isinstance(serviceref, eServiceReference):
			serviceref = ServiceReference(serviceref)

		recording = RecordTimerEntry(serviceref, begin, end, info["name"], info["description"], info["eventid"], dirname = preferredInstantRecordPath())
		recording.dontSave = True

		if event is None or limitEvent == False:
			recording.autoincrease = True
			recording.setAutoincreaseEnd()

		simulTimerList = self.session.nav.RecordTimer.record(recording)

		if simulTimerList is None:	# no conflict
			recording.autoincrease = False
			self.recording.append(recording)
		else:
			if len(simulTimerList) > 1: # with other recording
				name = simulTimerList[1].name
				name_date = ' '.join((name, strftime('%F %T', localtime(simulTimerList[1].begin))))
				print "[TIMER] conflicts with", name_date
				recording.autoincrease = True	# start with max available length, then increment
				if recording.setAutoincreaseEnd():
					self.session.nav.RecordTimer.record(recording)
					self.recording.append(recording)
					self.session.open(MessageBox, _("Record time limited due to conflicting timer %s") % name_date, MessageBox.TYPE_INFO)
				else:
					self.session.open(MessageBox, _("Could not record due to conflicting timer %s") % name, MessageBox.TYPE_INFO)
			else:
				self.session.open(MessageBox, _("Could not record due to invalid service %s") % serviceref, MessageBox.TYPE_INFO)
			recording.autoincrease = False

	def isInstantRecordRunning(self):
		print "self.recording:", self.recording
		if self.recording:
			for x in self.recording:
				if x.isRunning():
					return True
		return False

	def recordQuestionCallback(self, answer):
		print "pre:\n", self.recording

		if answer is None or answer[1] == "no":
			return
		list = []
		recording = self.recording[:]
		for x in recording:
			if not x in self.session.nav.RecordTimer.timer_list:
				self.recording.remove(x)
			elif x.dontSave and x.isRunning():
				list.append((x, False))

		if answer[1] == "changeduration":
			if len(self.recording) == 1:
				self.changeDuration(0)
			else:
				self.session.openWithCallback(self.changeDuration, TimerSelection, list)
		elif answer[1] == "changeendtime":
			if len(self.recording) == 1:
				self.setEndtime(0)
			else:
				self.session.openWithCallback(self.setEndtime, TimerSelection, list)
		elif answer[1] == "timer":
			import TimerEdit
			self.session.open(TimerEdit.TimerEditList)
		elif answer[1] == "stop":
			self.session.openWithCallback(self.stopCurrentRecording, TimerSelection, list)
		elif answer[1] in ( "indefinitely" , "manualduration", "manualendtime", "event"):
			self.startInstantRecording(limitEvent = answer[1] in ("event", "manualendtime") or False)
			if answer[1] == "manualduration":
				self.changeDuration(len(self.recording)-1)
			elif answer[1] == "manualendtime":
				self.setEndtime(len(self.recording)-1)
		elif "timeshift" in answer[1]:
			ts = self.getTimeshift()
			if ts:
				ts.saveTimeshiftFile()
				self.save_timeshift_file = True
				if "movie" in answer[1]:
					self.save_timeshift_in_movie_dir = True
		print "after:\n", self.recording

	def setEndtime(self, entry):
		if entry is not None and entry >= 0:
			self.selectedEntry = entry
			self.endtime=ConfigClock(default = self.recording[self.selectedEntry].end)
			dlg = self.session.openWithCallback(self.TimeDateInputClosed, TimeDateInput, self.endtime)
			dlg.setTitle(_("Please change recording endtime"))

	def TimeDateInputClosed(self, ret):
		if len(ret) > 1:
			if ret[0]:
				print "stopping recording at", strftime("%F %T", localtime(ret[1]))
				if self.recording[self.selectedEntry].end != ret[1]:
					self.recording[self.selectedEntry].autoincrease = False
				self.recording[self.selectedEntry].end = ret[1]
				self.session.nav.RecordTimer.timeChanged(self.recording[self.selectedEntry])

	def changeDuration(self, entry):
		if entry is not None and entry >= 0:
			self.selectedEntry = entry
			self.session.openWithCallback(self.inputCallback, InputBox, title=_("How many minutes do you want to record?"), text="5", maxSize=False, type=Input.NUMBER)

	def inputCallback(self, value):
		if value is not None:
			print "stopping recording after", int(value), "minutes."
			entry = self.recording[self.selectedEntry]
			if int(value) != 0:
				entry.autoincrease = False
			entry.end = int(time()) + 60 * int(value)
			self.session.nav.RecordTimer.timeChanged(entry)

	def isTimerRecordRunning(self):
		identical = timers = 0
		for timer in self.session.nav.RecordTimer.timer_list:
			if timer.isRunning() and not timer.justplay:
				timers += 1
				if self.recording:
					for x in self.recording:
						if x.isRunning() and x == timer:
							identical += 1
		return timers > identical

	def instantRecord(self):
		pirr = preferredInstantRecordPath()
		if not findSafeRecordPath(pirr) and not findSafeRecordPath(defaultMoviePath()):
			if not pirr:
				pirr = ""
			self.session.open(MessageBox, _("Missing ") + "\n" + pirr +
						 "\n" + _("No HDD found or HDD not initialized!"), MessageBox.TYPE_ERROR)
			return

		if isStandardInfoBar(self):
			common = ((_("Add recording (stop after current event)"), "event"),
				(_("Add recording (indefinitely)"), "indefinitely"),
				(_("Add recording (enter recording duration)"), "manualduration"),
				(_("Add recording (enter recording endtime)"), "manualendtime"),)
		else:
			common = ()
		if self.isInstantRecordRunning():
			title =_("A recording is currently running.\nWhat do you want to do?")
			list = ((_("Stop recording"), "stop"),) + common + \
				((_("Change recording (duration)"), "changeduration"),
				(_("Change recording (endtime)"), "changeendtime"),)
			if self.isTimerRecordRunning():
				list += ((_("Stop timer recording"), "timer"),)
			list += ((_("Do nothing"), "no"),)
		else:
			title=_("Start recording?")
			list = common
			if self.isTimerRecordRunning():
				list += ((_("Stop timer recording"), "timer"),)
			if isStandardInfoBar(self):
				list += ((_("Do not record"), "no"),)
		if isStandardInfoBar(self) and self.timeshiftEnabled():
			list = list + ((_("Save timeshift file"), "timeshift"),
				(_("Save timeshift file in movie directory"), "timeshift_movie"))
		if list:
			self.session.openWithCallback(self.recordQuestionCallback, ChoiceBox, title=title, list=list)
		else:
			return 0

from Tools.ISO639 import LanguageCodes

class InfoBarAudioSelection:
	def __init__(self):
		self["AudioSelectionAction"] = HelpableActionMap(self, "InfobarAudioSelectionActions",
			{
				"audioSelection": (self.audioSelection, _("Audio options...")),
			})

	def audioSelection(self):
		from Screens.AudioSelection import AudioSelection
		self.session.openWithCallback(self.audioSelected, AudioSelection, infobar=self)

	def audioSelected(self, ret=None):
		print "[infobar::audioSelected]", ret

class InfoBarSubserviceSelection:
	def __init__(self):
		self["SubserviceSelectionAction"] = HelpableActionMap(self, "InfobarSubserviceSelectionActions",
			{
				"subserviceSelection": (self.subserviceSelection, _("Subservice list...")),
			})

		self["SubserviceQuickzapAction"] = HelpableActionMap(self, "InfobarSubserviceQuickzapActions",
			{
				"nextSubservice": (self.nextSubservice, _("Switch to next sub service")),
				"prevSubservice": (self.prevSubservice, _("Switch to previous sub service"))
			}, -1)
		self["SubserviceQuickzapAction"].setEnabled(False)

		self.__event_tracker = ServiceEventTracker(screen=self, eventmap=
			{
				iPlayableService.evUpdatedEventInfo: self.checkSubservicesAvail
			})
		self.onClose.append(self.__removeNotifications)

		self.bsel = None

	def __removeNotifications(self):
		self.session.nav.event.remove(self.checkSubservicesAvail)

	def checkSubservicesAvail(self):
		service = self.session.nav.getCurrentService()
		subservices = service and service.subServices()
		if not subservices or subservices.getNumberOfSubservices() == 0:
			self["SubserviceQuickzapAction"].setEnabled(False)

	def nextSubservice(self):
		self.changeSubservice(+1)

	def prevSubservice(self):
		self.changeSubservice(-1)

	def changeSubservice(self, direction):
		service = self.session.nav.getCurrentService()
		subservices = service and service.subServices()
		n = subservices and subservices.getNumberOfSubservices()
		if n and n > 0:
			selection = -1
			ref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
			idx = 0
			while idx < n:
				if subservices.getSubservice(idx).toString() == ref.toString():
					selection = idx
					break
				idx += 1
			if selection != -1:
				selection += direction
				if selection >= n:
					selection=0
				elif selection < 0:
					selection=n-1
				newservice = subservices.getSubservice(selection)
				if newservice.valid():
					del subservices
					del service
					self.session.nav.playService(newservice, False)

	def subserviceSelection(self):
		service = self.session.nav.getCurrentService()
		subservices = service and service.subServices()
		self.bouquets = self.servicelist.getBouquetList()
		n = subservices and subservices.getNumberOfSubservices()
		selection = 0
		if n and n > 0:
			ref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
			tlist = []
			idx = 0
			while idx < n:
				i = subservices.getSubservice(idx)
				if i.toString() == ref.toString():
					selection = idx
				tlist.append((i.getName(), i))
				idx += 1

			if self.bouquets and len(self.bouquets):
				keys = ["red", "blue", "",  "0", "1", "2", "3", "4", "5", "6", "7", "8", "9" ] + [""] * n
				if config.usage.multibouquet.value:
					tlist = [(_("Quick zap"), "quickzap", service.subServices()), (_("Add to bouquet"), "CALLFUNC", self.addSubserviceToBouquetCallback), ("--", "")] + tlist
				else:
					tlist = [(_("Quick zap"), "quickzap", service.subServices()), (_("Add to favourites"), "CALLFUNC", self.addSubserviceToBouquetCallback), ("--", "")] + tlist
				selection += 3
			else:
				tlist = [(_("Quick zap"), "quickzap", service.subServices()), ("--", "")] + tlist
				keys = ["red", "",  "0", "1", "2", "3", "4", "5", "6", "7", "8", "9" ] + [""] * n
				selection += 2

			self.session.openWithCallback(self.subserviceSelected, ChoiceBox, title=_("Please select a sub service..."), list = tlist, selection = selection, keys = keys, skin_name = "SubserviceSelection")

	def subserviceSelected(self, service):
		del self.bouquets
		if not service is None:
			if isinstance(service[1], str):
				if service[1] == "quickzap":
					from Screens.SubservicesQuickzap import SubservicesQuickzap
					self.session.open(SubservicesQuickzap, service[2])
			else:
				self["SubserviceQuickzapAction"].setEnabled(True)
				self.session.nav.playService(service[1], False)

	def addSubserviceToBouquetCallback(self, service):
		if len(service) > 1 and isinstance(service[1], eServiceReference):
			self.selectedSubservice = service
			if self.bouquets is None:
				cnt = 0
			else:
				cnt = len(self.bouquets)
			if cnt > 1: # show bouquet list
				self.bsel = self.session.openWithCallback(self.bouquetSelClosed, BouquetSelector, self.bouquets, self.addSubserviceToBouquet)
			elif cnt == 1: # add to only one existing bouquet
				self.addSubserviceToBouquet(self.bouquets[0][1])
				self.session.open(MessageBox, _("Service has been added to the favourites."), MessageBox.TYPE_INFO)

	def bouquetSelClosed(self, confirmed):
		self.bsel = None
		del self.selectedSubservice
		if confirmed:
			self.session.open(MessageBox, _("Service has been added to the selected bouquet."), MessageBox.TYPE_INFO)

	def addSubserviceToBouquet(self, dest):
		self.servicelist.addServiceToBouquet(dest, self.selectedSubservice[1])
		if self.bsel:
			self.bsel.close(True)
		else:
			del self.selectedSubservice

class InfoBarRedButton:
	def __init__(self):
		self["RedButtonActions"] = HelpableActionMap(self, "InfobarRedButtonActions",
			{
				"activateRedButton": (self.activateRedButton, _("Red button...")),
			})
		self.onHBBTVActivation = [ ]
		self.onRedButtonActivation = [ ]

	def activateRedButton(self):
		service = self.session.nav.getCurrentService()
		info = service and service.info()
		if info and info.getInfoString(iServiceInformation.sHBBTVUrl) != "":
			for x in self.onHBBTVActivation:
				x()
		elif False: # TODO: other red button services
			for x in self.onRedButtonActivation:
				x()

class InfoBarTimerButton:
	def __init__(self):
		self["TimerButtonActions"] = HelpableActionMap(self, "InfobarTimerButtonActions",
			{
				"timerSelection": (self.timerSelection, _("Timer selection...")),
			})

	def timerSelection(self):
		from Screens.TimerEdit import TimerEditList
		self.session.open(TimerEditList)

class InfoBarVmodeButton:
	def __init__(self):
		self["VmodeButtonActions"] = HelpableActionMap(self, "InfobarVmodeButtonActions",
			{
				"vmodeSelection": (self.vmodeSelection, _("Letterbox zoom")),
			})

	def vmodeSelection(self):
		self.session.open(VideoMode)

class VideoMode(Screen):
	def __init__(self,session):
		Screen.__init__(self, session)
		self["videomode"] = Label()

		self["actions"] = NumberActionMap( [ "InfobarVmodeButtonActions" ],
			{
				"vmodeSelection": self.selectVMode
			})

		self.Timer = eTimer()
		self.Timer.callback.append(self.quit)
		self.selectVMode()

	def selectVMode(self):
		policy = config.av.policy_43
		if self.isWideScreen():
			policy = config.av.policy_169
		idx = policy.choices.index(policy.value)
		idx = (idx + 1) % len(policy.choices)
		policy.value = policy.choices[idx]
		self["videomode"].setText(policy.value)
		self.Timer.start(1000, True)

	def isWideScreen(self):
		from Components.Converter.ServiceInfo import WIDESCREEN
		service = self.session.nav.getCurrentService()
		info = service and service.info()
		return info.getInfo(iServiceInformation.sAspect) in WIDESCREEN

	def quit(self):
		self.Timer.stop()
		self.close()

class InfoBarAdditionalInfo:
	def __init__(self):

		self["RecordingPossible"] = Boolean(fixed=harddiskmanager.HDDCount() > 0)
		self["TimeshiftPossible"] = self["RecordingPossible"]
		self["ExtensionsAvailable"] = Boolean(fixed=1)
		# TODO: these properties should be queried from the input device keymap
		self["ShowTimeshiftOnYellow"] = Boolean(fixed=0)
		self["ShowAudioOnYellow"] = Boolean(fixed=0)
		self["ShowRecordOnRed"] = Boolean(fixed=0)

class InfoBarNotifications:
	def __init__(self):
		self.onExecBegin.append(self.checkNotifications)
		Notifications.notificationAdded.append(self.checkNotificationsIfExecing)
		self.onClose.append(self.__removeNotification)

	def __removeNotification(self):
		Notifications.notificationAdded.remove(self.checkNotificationsIfExecing)

	def checkNotificationsIfExecing(self):
		if self.execing:
			self.checkNotifications()

	def checkNotifications(self):
		notifications = Notifications.notifications
		if notifications:
			n = notifications[0]

			del notifications[0]
			cb = n[0]

			if n[3].has_key("onSessionOpenCallback"):
				n[3]["onSessionOpenCallback"]()
				del n[3]["onSessionOpenCallback"]

			if cb:
				dlg = self.session.openWithCallback(cb, n[1], *n[2], **n[3])
			elif not Notifications.current_notifications and n[4] == "ZapError":
				if n[3].has_key("timeout"):
					del n[3]["timeout"]
				n[3]["enable_input"] = False
				dlg = self.session.instantiateDialog(n[1], *n[2], **n[3])
				self.hide()
				dlg.show()
				self.notificationDialog = dlg
				eActionMap.getInstance().bindAction('', -maxint - 1, self.keypressNotification)
			else:
				dlg = self.session.open(n[1], *n[2], **n[3])

			# remember that this notification is currently active
			d = (n[4], dlg)
			Notifications.current_notifications.append(d)
			dlg.onClose.append(boundFunction(self.__notificationClosed, d))

	def closeNotificationInstantiateDialog(self):
		if hasattr(self, "notificationDialog"):
			self.session.deleteDialog(self.notificationDialog)
			del self.notificationDialog
			eActionMap.getInstance().unbindAction('', self.keypressNotification)

	def keypressNotification(self, key, flag):
		if flag:
			self.closeNotificationInstantiateDialog()

	def __notificationClosed(self, d):
		Notifications.current_notifications.remove(d)

class InfoBarServiceNotifications:
	def __init__(self):
		self.__event_tracker = ServiceEventTracker(screen=self, eventmap=
			{
				iPlayableService.evEnd: self.serviceHasEnded
			})

	def serviceHasEnded(self):
		print "service end!"

		try:
			self.setSeekState(self.SEEK_STATE_PLAY)
		except:
			pass

class InfoBarCueSheetSupport:
	CUT_TYPE_IN = 0
	CUT_TYPE_OUT = 1
	CUT_TYPE_MARK = 2
	CUT_TYPE_LAST = 3

	ENABLE_RESUME_SUPPORT = False

	def __init__(self, actionmap = "InfobarCueSheetActions"):
		self["CueSheetActions"] = HelpableActionMap(self, actionmap,
			{
				"jumpPreviousMark": (self.jumpPreviousMark, _("Jump to previous marked position")),
				"jumpNextMark": (self.jumpNextMark, _("Jump to next marked position")),
				"toggleMark": (self.toggleMark, _("Toggle a cut mark at the current position"))
			}, prio=1)

		self.cut_list = [ ]
		self.is_closing = False
		self.__event_tracker = ServiceEventTracker(screen=self, eventmap=
			{
				iPlayableService.evStart: self.__serviceStarted,
				iPlayableService.evCuesheetChanged: self.downloadCuesheet,
			})

	def __serviceStarted(self):
		if self.is_closing:
			return
		print "new service started! trying to download cuts!"
		self.downloadCuesheet()

		if self.ENABLE_RESUME_SUPPORT:
			for (pts, what) in self.cut_list:
				if what == self.CUT_TYPE_LAST:
					last = pts
					break
			else:
				last = getResumePoint(self.session)
			if last is None:
				return
			# only resume if at least 10 seconds ahead, or <10 seconds before the end.
			seekable = self.__getSeekable()
			if seekable is None:
				return # Should not happen?
			length = seekable.getLength() or (None,0)
			print "seekable.getLength() returns:", length
			# Hmm, this implies we don't resume if the length is unknown...
			if (last > 900000) and (not length[1]  or (last < length[1] - 900000)):
				self.resume_point = last
				l = last / 90000
				if config.usage.on_movie_start.value == "ask" or not length[1]:
					Notifications.AddNotificationWithCallback(self.playLastCB, MessageBox, _("Do you want to resume this playback?") + "\n" + (_("Resume position at %s") % ("%d:%02d:%02d" % (l/3600, l%3600/60, l%60))), timeout=10)
				elif config.usage.on_movie_start.value == "resume":
# TRANSLATORS: The string "Resuming playback" flashes for a moment
# TRANSLATORS: at the start of a movie, when the user has selected
# TRANSLATORS: "Resume from last position" as start behavior.
# TRANSLATORS: The purpose is to notify the user that the movie starts
# TRANSLATORS: in the middle somewhere and not from the beginning.
# TRANSLATORS: (Some translators seem to have interpreted it as a
# TRANSLATORS: question or a choice, but it is a statement.)
					Notifications.AddNotificationWithCallback(self.playLastCB, MessageBox, _("Resuming playback"), timeout=2, type=MessageBox.TYPE_INFO)

	def playLastCB(self, answer):
		if answer == True:
			self.doSeek(self.resume_point)
		self.hideAfterResume()

	def hideAfterResume(self):
		if isinstance(self, InfoBarShowHide):
			self.hide()

	def __getSeekable(self):
		service = self.session.nav.getCurrentService()
		if service is None:
			return None
		return service.seek()

	def cueGetCurrentPosition(self):
		seek = self.__getSeekable()
		if seek is None:
			return None
		r = seek.getPlayPosition()
		if r[0]:
			return None
		return long(r[1])

	def cueGetEndCutPosition(self):
		ret = False
		isin = True
		for cp in self.cut_list:
			if cp[1] == self.CUT_TYPE_OUT:
				if isin:
					isin = False
					ret = cp[0]
			elif cp[1] == self.CUT_TYPE_IN:
				isin = True
		return ret

	def jumpPreviousNextMark(self, cmp, start=False):
		current_pos = self.cueGetCurrentPosition()
		if current_pos is None:
			return False
		mark = self.getNearestCutPoint(current_pos, cmp=cmp, start=start)
		if mark is not None:
			pts = mark[0]
		else:
			return False

		self.doSeek(pts)
		return True

	def jumpPreviousMark(self):
		# we add 5 seconds, so if the play position is <5s after
		# the mark, the mark before will be used
		self.jumpPreviousNextMark(lambda x: -x-5*90000, start=True)

	def jumpNextMark(self):
		if not self.jumpPreviousNextMark(lambda x: x-90000):
			self.doSeek(-1)

	def getNearestCutPoint(self, pts, cmp=abs, start=False):
		# can be optimized
		beforecut = True
		nearest = None
		bestdiff = -1
		instate = True
		if start:
			bestdiff = cmp(0 - pts)
			if bestdiff >= 0:
				nearest = [0, False]
		for cp in self.cut_list:
			if beforecut and cp[1] in (self.CUT_TYPE_IN, self.CUT_TYPE_OUT):
				beforecut = False
				if cp[1] == self.CUT_TYPE_IN:  # Start is here, disregard previous marks
					diff = cmp(cp[0] - pts)
					if start and diff >= 0:
						nearest = cp
						bestdiff = diff
					else:
						nearest = None
						bestdiff = -1
			if cp[1] == self.CUT_TYPE_IN:
				instate = True
			elif cp[1] == self.CUT_TYPE_OUT:
				instate = False
			elif cp[1] in (self.CUT_TYPE_MARK, self.CUT_TYPE_LAST):
				diff = cmp(cp[0] - pts)
				if instate and diff >= 0 and (nearest is None or bestdiff > diff):
					nearest = cp
					bestdiff = diff
		return nearest

	def toggleMark(self, onlyremove=False, onlyadd=False, tolerance=5*90000, onlyreturn=False):
		current_pos = self.cueGetCurrentPosition()
		if current_pos is None:
			print "not seekable"
			return

		nearest_cutpoint = self.getNearestCutPoint(current_pos)

		if nearest_cutpoint is not None and abs(nearest_cutpoint[0] - current_pos) < tolerance:
			if onlyreturn:
				return nearest_cutpoint
			if not onlyadd:
				self.removeMark(nearest_cutpoint)
		elif not onlyremove and not onlyreturn:
			self.addMark((current_pos, self.CUT_TYPE_MARK))

		if onlyreturn:
			return None

	def addMark(self, point):
		insort(self.cut_list, point)
		self.uploadCuesheet()
		self.showAfterCuesheetOperation()

	def removeMark(self, point):
		self.cut_list.remove(point)
		self.uploadCuesheet()
		self.showAfterCuesheetOperation()

	def showAfterCuesheetOperation(self):
		if isinstance(self, InfoBarShowHide):
			self.doShow()

	def __getCuesheet(self):
		service = self.session.nav.getCurrentService()
		if service is None:
			return None
		return service.cueSheet()

	def uploadCuesheet(self):
		cue = self.__getCuesheet()

		if cue is None:
			print "upload failed, no cuesheet interface"
			return
		cue.setCutList(self.cut_list)

	def downloadCuesheet(self):
		cue = self.__getCuesheet()

		if cue is None:
			print "download failed, no cuesheet interface"
			self.cut_list = [ ]
		else:
			self.cut_list = cue.getCutList()

class InfoBarSummary(Screen):
	skin = """
	<screen position="0,0" size="132,64">
		<widget source="global.CurrentTime" render="Label" position="62,46" size="82,18" font="Regular;16" >
			<convert type="ClockToText">WithSeconds</convert>
		</widget>
		<widget source="session.RecordState" render="FixedLabel" text=" " position="62,46" size="82,18" zPosition="1" >
			<convert type="ConfigEntryTest">config.usage.blinking_display_clock_during_recording,True,CheckSourceBoolean</convert>
			<convert type="ConditionalShowHide">Blink</convert>
		</widget>
		<widget source="session.CurrentService" render="Label" position="6,4" size="120,42" font="Regular;18" >
			<convert type="ServiceName">Name</convert>
		</widget>
		<widget source="session.Event_Now" render="Progress" position="6,46" size="46,18" borderWidth="1" >
			<convert type="EventTime">Progress</convert>
		</widget>
	</screen>"""

# for picon:  (path="piconlcd" will use LCD picons)
#		<widget source="session.CurrentService" render="Picon" position="6,0" size="120,64" path="piconlcd" >
#			<convert type="ServiceName">Reference</convert>
#		</widget>

class InfoBarSummarySupport:
	def __init__(self):
		pass

	def createSummary(self):
		return InfoBarSummary

class InfoBarMoviePlayerSummary(Screen):
	skin = """
	<screen position="0,0" size="132,64">
		<widget source="global.CurrentTime" render="Label" position="62,46" size="64,18" font="Regular;16" halign="right" >
			<convert type="ClockToText">WithSeconds</convert>
		</widget>
		<widget source="session.RecordState" render="FixedLabel" text=" " position="62,46" size="64,18" zPosition="1" >
			<convert type="ConfigEntryTest">config.usage.blinking_display_clock_during_recording,True,CheckSourceBoolean</convert>
			<convert type="ConditionalShowHide">Blink</convert>
		</widget>
		<widget source="session.CurrentService" render="Label" position="6,4" size="120,42" font="Regular;18" >
			<convert type="ServiceName">Name</convert>
		</widget>
		<widget source="session.CurrentService" render="Progress" position="6,46" size="56,18" borderWidth="1" >
			<convert type="ServicePosition">Position</convert>
		</widget>
	</screen>"""

class InfoBarMoviePlayerSummarySupport:
	def __init__(self):
		pass

	def createSummary(self):
		return InfoBarMoviePlayerSummary

class InfoBarTeletextPlugin:
	def __init__(self):
		self.teletext_plugin = None

		for p in plugins.getPlugins(PluginDescriptor.WHERE_TELETEXT):
			self.teletext_plugin = p

		if self.teletext_plugin is not None:
			self["TeletextActions"] = HelpableActionMap(self, "InfobarTeletextActions",
				{
					"startTeletext": (self.startTeletext, _("View teletext..."))
				})
		else:
			print "no teletext plugin found!"

	def startTeletext(self):
		self.teletext_plugin(session=self.session, service=self.session.nav.getCurrentService())

class InfoBarSubtitleSupport(object):
	def __init__(self):
		object.__init__(self)
		self["SubtitleSelectionAction"] = HelpableActionMap(self, "InfobarSubtitleSelectionActions",
			{
				"subtitleSelection": (self.subtitleSelection, _("Subtitle selection...")),
			})

		self.selected_subtitle = None

		if isStandardInfoBar(self):
			self.subtitle_window = self.session.instantiateDialog(SubtitleDisplay)
		else:
			from Screens.InfoBar import InfoBar
			self.subtitle_window = InfoBar.instance.subtitle_window

		self.subtitle_window.hide()

		self.__event_tracker = ServiceEventTracker(screen=self, eventmap=
			{
				iPlayableService.evStart: self.__serviceChanged,
				iPlayableService.evEnd: self.__serviceChanged,
				iPlayableService.evUpdatedInfo: self.__updatedInfo
			})

	def getCurrentServiceSubtitle(self):
		service = self.session.nav.getCurrentService()
		return service and service.subtitle()

	def subtitleSelection(self):
		subtitle = self.getCurrentServiceSubtitle()
		subtitlelist = subtitle and subtitle.getSubtitleList()
		if self.selected_subtitle or subtitlelist and len(subtitlelist)>0:
			from Screens.AudioSelection import SubtitleSelection
			self.session.open(SubtitleSelection, self)
		else:
			return 0

	def __serviceChanged(self):
		if self.selected_subtitle:
			self.selected_subtitle = None
			self.subtitle_window.hide()

	def __updatedInfo(self):
		if not self.selected_subtitle:
			subtitle = self.getCurrentServiceSubtitle()
			cachedsubtitle = subtitle.getCachedSubtitle()
			if cachedsubtitle:
				self.enableSubtitle(cachedsubtitle)

	def enableSubtitle(self, selectedSubtitle):
		subtitle = self.getCurrentServiceSubtitle()
		self.selected_subtitle = selectedSubtitle
		if subtitle and self.selected_subtitle:
			subtitle.enableSubtitles(self.subtitle_window.instance, self.selected_subtitle)
			self.subtitle_window.show()
		else:
			if subtitle:
				subtitle.disableSubtitles(self.subtitle_window.instance)
			self.subtitle_window.hide()

	def restartSubtitle(self):
		if self.selected_subtitle:
			self.enableSubtitle(self.selected_subtitle)

class InfoBarServiceErrorPopupSupport:
	def __init__(self):
		self.__event_tracker = ServiceEventTracker(screen=self, eventmap=
			{
				iPlayableService.evTuneFailed: self.__tuneFailed,
				iPlayableService.evTunedIn: self.__serviceStarted,
				iPlayableService.evStart: self.__serviceStarted
			})
		self.__serviceStarted()

	def __serviceStarted(self):
		self.closeNotificationInstantiateDialog()
		self.last_error = None
		Notifications.RemovePopup(id = "ZapError")

	def __tuneFailed(self):
		if not config.usage.hide_zap_errors.value:
			service = self.session.nav.getCurrentService()
			info = service and service.info()
			error = info and info.getInfo(iServiceInformation.sDVBState)

			if error == self.last_error:
				error = None
			else:
				self.last_error = error

			error = {
				eDVBServicePMTHandler.eventNoResources: _("No free tuner!"),
				eDVBServicePMTHandler.eventTuneFailed: _("Tune failed!"),
				eDVBServicePMTHandler.eventNoPAT: _("No data on transponder!\n(Timeout reading PAT)"),
				eDVBServicePMTHandler.eventNoPATEntry: _("Service not found!\n(SID not found in PAT)"),
				eDVBServicePMTHandler.eventNoPMT: _("Service invalid!\n(Timeout reading PMT)"),
				eDVBServicePMTHandler.eventNewProgramInfo: None,
				eDVBServicePMTHandler.eventTuned: None,
				eDVBServicePMTHandler.eventSOF: None,
				eDVBServicePMTHandler.eventEOF: None,
				eDVBServicePMTHandler.eventMisconfiguration: _("Service unavailable!\nCheck tuner configuration!"),
			}.get(error) #this returns None when the key not exist in the dict

			if error:
				self.closeNotificationInstantiateDialog()
				if hasattr(self, "dishDialog") and not self.dishDialog.dishState():
					Notifications.AddPopup(text = error, type = MessageBox.TYPE_ERROR, timeout = 5, id = "ZapError")

class InfoBarPowersaver:
	def __init__(self):
		self.inactivityTimer = eTimer()
		self.inactivityTimer.callback.append(self.inactivityTimeout)
		self.restartInactiveTimer()
		self.sleepTimer = eTimer()
		self.sleepTimer.callback.append(self.sleepTimerTimeout)
		eActionMap.getInstance().bindAction('', -maxint - 1, self.keypress)

	def keypress(self, key, flag):
		if flag:
			self.restartInactiveTimer()

	def restartInactiveTimer(self):
		time = abs(int(config.usage.inactivity_timer.value))
		if time:
			self.inactivityTimer.startLongTimer(time)
		else:
			self.inactivityTimer.stop()

	def inactivityTimeout(self):
		if config.usage.inactivity_timer_blocktime.value:
			curtime = localtime(time())
			if curtime.tm_year > 1970: #check if the current time is valid
				curtime = (curtime.tm_hour, curtime.tm_min, curtime.tm_sec)
				begintime = tuple(config.usage.inactivity_timer_blocktime_begin.value)
				endtime = tuple(config.usage.inactivity_timer_blocktime_end.value)
				if begintime <= endtime and (curtime >= begintime and curtime < endtime) or begintime > endtime and (curtime >= begintime or curtime < endtime):
					duration = (endtime[0]*3600 + endtime[1]*60) - (curtime[0]*3600 + curtime[1]*60 + curtime[2])
					if duration:
						if duration < 0:
							duration += 24*3600
						self.inactivityTimer.startLongTimer(duration)
						return
		if Screens.Standby.inStandby:
			self.inactivityTimeoutCallback(True)
		else:
			if int(config.usage.inactivity_timer.value) < 0:
				message = _("Your receiver will shutdown due to inactivity.")
			else:
				message = _("Your receiver will got to standby due to inactivity.")
			message += "\n" + _("Do you want this?")
			self.session.openWithCallback(self.inactivityTimeoutCallback, MessageBox, message, timeout=60, simple=True, default=False, timeout_default=True)	

	def inactivityTimeoutCallback(self, answer):
		if answer:
			self.goShutdownOrStandby(int(config.usage.inactivity_timer.value))
		else:
			print "[InfoBarPowersaver] abort"

	def setSleepTimer(self, time):
		print "[InfoBarPowersaver] set sleeptimer", time
		if time:
			if time < 0:
				message = _("And will shutdown your receiver over ")
			else:
				message = _("And will put your receiver in standby over ")
			m = abs(time / 60)
			message = _("The sleep timer has been activated.") + "\n" + message + ngettext("%d minute", "%d minutes", m) % m
			self.sleepTimer.startLongTimer(abs(time))
		else:
			message = _("The sleep timer has been disabled.")
			self.sleepTimer.stop()
		Notifications.AddPopup(message, type = MessageBox.TYPE_INFO, timeout = 5)
		self.sleepTimerSetting = time

	def sleepTimerTimeout(self):
		if Screens.Standby.inStandby:
			self.sleepTimerTimeoutCallback(True)
		else:
			list = [ (_("Yes"), True), (_("Extend sleeptimer 15 minutes"), "extend"), (_("No"), False) ]
			if self.sleepTimerSetting < 0:
				message = _("Your receiver will shutdown due to the sleeptimer.")
			elif self.sleepTimerSetting > 0:
				message = _("Your receiver will got to stand by due to the sleeptimer.")
			message += "\n" + _("Do you want this?")
			self.session.openWithCallback(self.sleepTimerTimeoutCallback, MessageBox, message, timeout=60, simple=True, list=list, default=False, timeout_default=True)	

	def sleepTimerTimeoutCallback(self, answer):
		if answer == "extend":
			print "[InfoBarPowersaver] extend sleeptimer"
			if self.sleepTimerSetting < 0:
				self.setSleepTimer(-900)
			else:
				self.setSleepTimer(900)
		elif answer:
			self.goShutdownOrStandby(self.sleepTimerSetting)
		else:
			print "[InfoBarPowersaver] abort"
			self.setSleepTimer(0)

	def goShutdownOrStandby(self, value):
		if value < 0:
			if Screens.Standby.inStandby:
				print "[InfoBarPowersaver] already in standby now shut down"
				RecordTimerEntry.TryQuitMainloop()
			elif not Screens.Standby.inTryQuitMainloop:
				print "[InfoBarPowersaver] goto shutdown"
				self.session.open(Screens.Standby.TryQuitMainloop, 1)
		elif not Screens.Standby.inStandby:
			print "[InfoBarPowersaver] goto standby"
			self.session.open(Screens.Standby.Standby)
class InfoBarHDMI:
	def __init__(self):
		self["HDMIActions"] = HelpableActionMap(self, "InfobarHDMIActions",
			{
				"HDMIin":(self.HDMIIn, _("Switch to HDMI in mode")),
			}, prio=2)

	def HDMIIn(self):
		slist = self.servicelist
		if slist.dopipzap:
			curref = self.session.pip.getCurrentService()
			if curref and curref.type != 8192:
				self.session.pip.playService(eServiceReference('8192:0:1:0:0:0:0:0:0:0:'))
			else:
				self.session.pip.playService(slist.servicelist.getCurrent())
		else:
			curref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
			if curref and curref.type != 8192:
				if curref and curref.type != -1 and os.path.splitext(curref.toString().split(":")[10])[1].lower() in AUDIO_EXTENSIONS.union(MOVIE_EXTENSIONS, DVD_EXTENSIONS):
					setResumePoint(self.session)
				self.session.nav.playService(eServiceReference('8192:0:1:0:0:0:0:0:0:0:'))
			elif isStandardInfoBar(self):
				self.session.nav.playService(slist.servicelist.getCurrent())
			else:
				self.session.nav.playService(self.cur_service)
