from enigma import eDVBResourceManager, Misc_Options
from Tools.Directories import fileExists
from Tools.HardwareInfo import HardwareInfo
from enigma import eEnv
SystemInfo = { }

#FIXMEE...
def getNumVideoDecoders():
	idx = 0
	while fileExists("/dev/dvb/adapter0/video%d"%(idx), 'f'):
		idx += 1
	return idx

SystemInfo["NumVideoDecoders"] = getNumVideoDecoders()
SystemInfo["CanMeasureFrontendInputPower"] = eDVBResourceManager.getInstance().canMeasureFrontendInputPower()


def countFrontpanelLEDs():
	leds = 0
	if fileExists(eEnv.resolve("${sysconfdir}/stb/fp/led_set_pattern")):
		leds += 1

	while fileExists(eEnv.resolve("${sysconfdir}/stb/fp/led%d_pattern") % leds):
		leds += 1

	return leds

SystemInfo["12V_Output"] = Misc_Options.getInstance().detected_12V_output()
SystemInfo["ZapMode"] = fileExists(eEnv.resolve("${sysconfdir}/stb/video/zapmode"))
SystemInfo["NumFrontpanelLEDs"] = countFrontpanelLEDs()
SystemInfo["FrontpanelDisplay"] = fileExists("/dev/dbox/oled0") or fileExists("/dev/dbox/lcd0")
SystemInfo["FrontpanelDisplayGrayscale"] = fileExists("/dev/dbox/oled0")
SystemInfo["DeepstandbySupport"] = HardwareInfo().get_device_name() != "dm800"
SystemInfo["Fan"] = fileExists(eEnv.resolve("${sysconfdir}/stb/fp/fan"))
SystemInfo["FanPWM"] = SystemInfo["Fan"] and fileExists(eEnv.resolve("${sysconfdir}/stb/fp/fan_pwm"))
SystemInfo["StandbyLED"] = fileExists(eEnv.resolve("${sysconfdir}/stb/power/standbyled"))
SystemInfo["WakeOnLAN"] = fileExists(eEnv.resolve("${sysconfdir}/stb/power/wol"))