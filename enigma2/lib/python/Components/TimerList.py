from HTMLComponent import HTMLComponent
from GUIComponent import GUIComponent
from skin import parseFont

from Tools.FuzzyDate import FuzzyTime

from enigma import eListboxPythonMultiContent, eListbox, gFont,\
	RT_HALIGN_LEFT, RT_HALIGN_RIGHT, RT_VALIGN_CENTER, RT_VALIGN_TOP, RT_VALIGN_BOTTOM
from Tools.Alternatives import GetWithAlternative
from Tools.LoadPixmap import LoadPixmap
from Tools.TextBoundary import getTextBoundarySize
from timer import TimerEntry
from Tools.Directories import resolveFilename, SCOPE_CURRENT_SKIN, SCOPE_SKIN_IMAGE

class TimerList(HTMLComponent, GUIComponent, object):
#
#  | <Name of the Timer>     <Service>  |
#  | <state>  <orb.pos.>  <start, end>  |
#
	def buildTimerEntry(self, timer, processed):
		width = self.l.getItemSize().width()
		res = [ None ]
		serviceName = timer.service_ref.getServiceName()

		serviceNameWidth = getTextBoundarySize(self.instance, self.serviceNameFont, self.l.getItemSize(), serviceName).width()
		if 200 > width - serviceNameWidth - self.iconWidth - self.iconMargin:
			serviceNameWidth = width - 200 - self.iconWidth - self.iconMargin

		res.append((eListboxPythonMultiContent.TYPE_TEXT, width - serviceNameWidth, 0, serviceNameWidth, self.rowSplit, 0, RT_HALIGN_RIGHT|RT_VALIGN_BOTTOM, serviceName))
		res.append((eListboxPythonMultiContent.TYPE_TEXT, self.iconWidth + self.iconMargin, 0, width - serviceNameWidth - self.iconWidth - self.iconMargin, self.rowSplit, 1, RT_HALIGN_LEFT|RT_VALIGN_BOTTOM, timer.name))

		days = ( _("Mon"), _("Tue"), _("Wed"), _("Thu"), _("Fri"), _("Sat"), _("Sun") )
		begin = FuzzyTime(timer.begin)
		if timer.repeated:
			repeatedtext = []
			flags = timer.repeated
			for x in (0, 1, 2, 3, 4, 5, 6):
				if (flags & 1 == 1):
					repeatedtext.append(days[x])
				flags = flags >> 1
			repeatedtext = ", ".join(repeatedtext)
			if self.iconRepeat:
				res.append((eListboxPythonMultiContent.TYPE_PIXMAP_ALPHATEST, self.iconMargin / 2, self.rowSplit + (self.itemHeight - self.rowSplit - self.iconHeight) / 2, self.iconWidth, self.iconHeight, self.iconRepeat))
		else:
			repeatedtext = begin[0] # date
		if timer.justplay:
			text = repeatedtext + ((" %s "+ _("(ZAP)")) % (begin[1]))
		else:
			text = repeatedtext + ((" %s ... %s (%d " + _("mins") + ")") % (begin[1], FuzzyTime(timer.end)[1], (timer.end - timer.begin) / 60))
		textWidth = getTextBoundarySize(self.instance, self.font, self.l.getItemSize(), text).width()
		res.append((eListboxPythonMultiContent.TYPE_TEXT, width - textWidth, self.rowSplit, textWidth, self.itemHeight - self.rowSplit, 1, RT_HALIGN_RIGHT|RT_VALIGN_TOP, text))
		icon = None
		if not processed:
			if timer.state == TimerEntry.StateWaiting:
				state = _("waiting")
				icon = self.iconWait
			elif timer.state == TimerEntry.StatePrepared:
				state = _("about to start")
				icon = self.iconPrepared
			elif timer.state == TimerEntry.StateRunning:
				if timer.justplay:
					state = _("zapped")
					icon = self.iconZapped
				else:
					state = _("recording...")
					icon = self.iconRecording
			elif timer.state == TimerEntry.StateEnded:
				state = _("done!")
				icon = self.iconDone
			else:
				state = _("<unknown>")
				icon = None
		else:
			state = _("done!")
			icon = self.iconDone
		if timer.disabled:
			icon = self.iconDisabled

		if timer.disabled:
			state = _("disabled")

		orbpos = self.getOrbitalPos(timer.service_ref)
		res.append((eListboxPythonMultiContent.TYPE_TEXT, self.satPosLeft, self.rowSplit, getTextBoundarySize(self.instance, self.font, self.l.getItemSize(), orbpos).width(), self.itemHeight - self.rowSplit, 1, RT_HALIGN_LEFT|RT_VALIGN_TOP, orbpos))
		res.append((eListboxPythonMultiContent.TYPE_TEXT, self.iconWidth + self.iconMargin, self.rowSplit, self.satPosLeft - self.iconWidth - self.iconMargin, self.itemHeight - self.rowSplit, 1, RT_HALIGN_LEFT|RT_VALIGN_TOP, state))
		if icon:
			res.append((eListboxPythonMultiContent.TYPE_PIXMAP_ALPHATEST, self.iconMargin / 2, (self.rowSplit - self.iconHeight) / 2, self.iconWidth, self.iconHeight, icon))
		return res

	def __init__(self, list):
		GUIComponent.__init__(self)
		self.l = eListboxPythonMultiContent()
		self.l.setBuildFunc(self.buildTimerEntry)
		self.serviceNameFont = gFont("Regular", 20)
		self.l.setFont(0, self.serviceNameFont)
		self.font = gFont("Regular", 18)
		self.l.setFont(1, self.font)
		self.itemHeight = 50
		self.l.setItemHeight(self.itemHeight)
		self.rowSplit = 25
		self.l.setList(list)
		self.iconWait = LoadPixmap(resolveFilename(SCOPE_SKIN_IMAGE, "skin_default/icons/timer_wait.png"))
		#currently intended that all icons have the same size
		self.iconWidth = self.iconWait.size().width()
		self.iconHeight = self.iconWait.size().height()
		self.iconMargin = 4
		self.satPosLeft = 160
		self.iconRecording = LoadPixmap(resolveFilename(SCOPE_SKIN_IMAGE, "skin_default/icons/timer_rec.png"))
		self.iconPrepared = LoadPixmap(resolveFilename(SCOPE_SKIN_IMAGE, "skin_default/icons/timer_prep.png"))
		self.iconDone = LoadPixmap(resolveFilename(SCOPE_SKIN_IMAGE, "skin_default/icons/timer_done.png"))
		self.iconRepeat = LoadPixmap(resolveFilename(SCOPE_SKIN_IMAGE, "skin_default/icons/timer_rep.png"))
		self.iconZapped = LoadPixmap(resolveFilename(SCOPE_SKIN_IMAGE, "skin_default/icons/timer_zap.png"))
		self.iconDisabled = LoadPixmap(resolveFilename(SCOPE_SKIN_IMAGE, "skin_default/icons/timer_off.png"))

	def applySkin(self, desktop, parent):
		def itemHeight(value):
			self.itemHeight = int(value)
			self.l.setItemHeight(self.itemHeight)
		def setServiceNameFont(value):
			self.serviceNameFont = parseFont(value, ((1,1),(1,1)))
			self.l.setFont(0, self.serviceNameFont)
		def setFont(value):
			self.font = parseFont(value, ((1,1),(1,1)))
			self.l.setFont(1, self.font)
		def rowSplit(value):
			self.rowSplit = int(value)
		def iconMargin(value):
			self.iconMargin = int(value)
		def satPosLeft(value):
			self.satPosLeft = int(value)
		for (attrib, value) in [x for x in self.skinAttributes if x[0] in dir()]:
			eval (attrib + "('" + value + "')")
			self.skinAttributes.remove((attrib, value))
		return GUIComponent.applySkin(self, desktop, parent)

	def getCurrent(self):
		cur = self.l.getCurrentSelection()
		return cur and cur[0]

	GUI_WIDGET = eListbox

	def postWidgetCreate(self, instance):
		instance.setContent(self.l)
		self.instance = instance
		instance.setWrapAround(True)

	def moveToIndex(self, index):
		self.instance.moveSelectionTo(index)

	def getCurrentIndex(self):
		return self.instance.getCurrentIndex()

	currentIndex = property(getCurrentIndex, moveToIndex)
	currentSelection = property(getCurrent)

	def moveDown(self):
		self.instance.moveSelection(self.instance.moveDown)

	def invalidate(self):
		self.l.invalidate()

	def entryRemoved(self, idx):
		self.l.entryRemoved(idx)

	def getOrbitalPos(self, ref):
		refstr = ''
		if hasattr(ref, 'sref'):
			refstr = str(ref.sref)
		else:
			refstr = str(ref)
		refstr = refstr and GetWithAlternative(refstr)
		if '%3a//' in refstr:
			return "%s" % _("Stream")
		op = int(refstr.split(':', 10)[6][:-4] or "0",16)
		if op == 0xeeee:
			return "%s" % _("DVB-T")
		if op == 0xffff:
			return "%s" % _("DVB-C")
		direction = 'E'
		if op > 1800:
			op = 3600 - op
			direction = 'W'
		return ("%d.%d\xc2\xb0%s") % (op // 10, op % 10, direction)
