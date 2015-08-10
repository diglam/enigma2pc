import sys
import os
import time
from Tools.HardwareInfo import HardwareInfo

def getVersionString():
	return getImageVersionString()

def getImageVersionString():
	try:
		if os.path.isfile('/var/lib/opkg/status'):
			st = os.stat('/var/lib/opkg/status')
		else:
			st = os.stat('/usr/lib/ipkg/status')
		tm = time.localtime(st.st_mtime)
		if tm.tm_year >= 2011:
			return time.strftime("%Y-%m-%d %H:%M:%S", tm)
	except:
		pass
	return _("unavailable")

def getEnigmaVersionString():
	import enigma
	enigma_version = enigma.getEnigmaVersionString()
	if '-(no branch)' in enigma_version:
		enigma_version = enigma_version [:-12]
	return enigma_version

def getKernelVersionString():
	try:
		return open("/proc/version","r").read().split(' ', 4)[2].split('-',2)[0]
	except:
		return _("unknown")

def getHardwareTypeString():
#	try:
#		if os.path.isfile("/usr/local/e2/etc/stb/info/boxtype"):
#			return open("/usr/local/e2/etc/stb/info/boxtype").read().strip().upper() + " (" + open("/usr/local/e2/etc/stb/info/board_revision").read().strip() + "-" + open("/usr/local/e2/etc/stb/info/version").read().strip() + ")"
#		if os.path.isfile("/usr/local/e2/etc/stb/info/vumodel"):
#			return "VU+" + open("/usr/local/e2/etc/stb/info/vumodel").read().strip().upper() + "(" + open("/usr/local/e2/etc/stb/info/version").read().strip().upper() + ")"
#		if os.path.isfile("/usr/local/e2/etc/stb/info/model"):
#			return open("/usr/local/e2/etc/stb/info/model").read().strip().upper()
#	except:
#		pass
#	return _("unavailable")
	return HardwareInfo().get_device_string()

def getImageTypeString():
	try:
		return open("/etc/issue").readlines()[-2].capitalize().strip()[:-6]
	except:                                
		pass
	return _("undefined")

# For modules that do "from About import about"
about = sys.modules[__name__]
