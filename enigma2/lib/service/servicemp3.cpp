	/* note: this requires gstreamer 0.10.x and a big list of plugins. */
	/* it's currently hardcoded to use a big-endian alsasink as sink. */
#include <lib/base/ebase.h>
#include <lib/base/eerror.h>
#include <lib/base/init_num.h>
#include <lib/base/init.h>
#include <lib/base/nconfig.h>
#include <lib/base/object.h>
#include <lib/dvb/epgcache.h>
#include <lib/dvb/decoder.h>
#include <lib/components/file_eraser.h>
#include <lib/gui/esubtitle.h>
#include <lib/service/servicemp3.h>
#include <lib/service/service.h>
#include <lib/gdi/gpixmap.h>

#include <string>

#include <gst/gst.h>
#include <gst/pbutils/missing-plugins.h>
#include <sys/stat.h>

#define HTTP_TIMEOUT 30

// eServiceFactoryMP3

/*
 * gstreamer suffers from a bug causing sparse streams to loose sync, after pause/resume / skip
 * see: https://bugzilla.gnome.org/show_bug.cgi?id=619434
 * As a workaround, we run the subsink in sync=false mode
 */
#define GSTREAMER_SUBTITLE_SYNC_MODE_BUG
/**/

eServiceFactoryMP3::eServiceFactoryMP3()
{
	ePtr<eServiceCenter> sc;
	
	eServiceCenter::getPrivInstance(sc);
	if (sc)
	{
		std::list<std::string> extensions;
		extensions.push_back("dts");
		extensions.push_back("mp2");
		extensions.push_back("mp3");
		extensions.push_back("ogg");
		extensions.push_back("ogm");
		extensions.push_back("ogv");
		extensions.push_back("mpg");
		extensions.push_back("vob");
		extensions.push_back("wav");
		extensions.push_back("wave");
		extensions.push_back("m4v");
		extensions.push_back("mkv");
		extensions.push_back("avi");
		extensions.push_back("divx");
		extensions.push_back("dat");
		extensions.push_back("flac");
		extensions.push_back("flv");
		extensions.push_back("mp4");
		extensions.push_back("mov");
		extensions.push_back("m4a");
		extensions.push_back("3gp");
		extensions.push_back("3g2");
		extensions.push_back("asf");
		extensions.push_back("wmv");
		extensions.push_back("wma");
		extensions.push_back("m2ts");
		extensions.push_back("webm");
		extensions.push_back("ts");
		sc->addServiceFactory(eServiceFactoryMP3::id, this, extensions);
	}

	m_service_info = new eStaticServiceMP3Info();
}

eServiceFactoryMP3::~eServiceFactoryMP3()
{
	ePtr<eServiceCenter> sc;
	
	eServiceCenter::getPrivInstance(sc);
	if (sc)
		sc->removeServiceFactory(eServiceFactoryMP3::id);
}

DEFINE_REF(eServiceFactoryMP3)

	// iServiceHandler
RESULT eServiceFactoryMP3::play(const eServiceReference &ref, ePtr<iPlayableService> &ptr)
{
		// check resources...
	ptr = new eServiceMP3(ref);
	return 0;
}

RESULT eServiceFactoryMP3::record(const eServiceReference &ref, ePtr<iRecordableService> &ptr)
{
	ptr=0;
	return -1;
}

RESULT eServiceFactoryMP3::list(const eServiceReference &, ePtr<iListableService> &ptr)
{
	ptr=0;
	return -1;
}

RESULT eServiceFactoryMP3::info(const eServiceReference &ref, ePtr<iStaticServiceInformation> &ptr)
{
	ptr = m_service_info;
	return 0;
}

class eMP3ServiceOfflineOperations: public iServiceOfflineOperations
{
	DECLARE_REF(eMP3ServiceOfflineOperations);
	eServiceReference m_ref;
public:
	eMP3ServiceOfflineOperations(const eServiceReference &ref);
	
	RESULT deleteFromDisk(int simulate);
	RESULT getListOfFilenames(std::list<std::string> &);
	RESULT reindex();
};

DEFINE_REF(eMP3ServiceOfflineOperations);

eMP3ServiceOfflineOperations::eMP3ServiceOfflineOperations(const eServiceReference &ref): m_ref((const eServiceReference&)ref)
{
}

RESULT eMP3ServiceOfflineOperations::deleteFromDisk(int simulate)
{
	if (!simulate)
	{
		std::list<std::string> res;
		if (getListOfFilenames(res))
			return -1;
		
		eBackgroundFileEraser *eraser = eBackgroundFileEraser::getInstance();
		if (!eraser)
			eDebug("FATAL !! can't get background file eraser");

		for (std::list<std::string>::iterator i(res.begin()); i != res.end(); ++i)
		{
			eDebug("Removing %s...", i->c_str());
			if (eraser)
				eraser->erase(i->c_str());
			else
				::unlink(i->c_str());
		}
	}
	return 0;
}

RESULT eMP3ServiceOfflineOperations::getListOfFilenames(std::list<std::string> &res)
{
	res.clear();
	res.push_back(m_ref.path);
	return 0;
}

RESULT eMP3ServiceOfflineOperations::reindex()
{
	return -1;
}


RESULT eServiceFactoryMP3::offlineOperations(const eServiceReference &ref, ePtr<iServiceOfflineOperations> &ptr)
{
	ptr = new eMP3ServiceOfflineOperations(ref);
	return 0;
}

// eStaticServiceMP3Info


// eStaticServiceMP3Info is seperated from eServiceMP3 to give information
// about unopened files.

// probably eServiceMP3 should use this class as well, and eStaticServiceMP3Info
// should have a database backend where ID3-files etc. are cached.
// this would allow listing the mp3 database based on certain filters.

DEFINE_REF(eStaticServiceMP3Info)

eStaticServiceMP3Info::eStaticServiceMP3Info()
{
}

RESULT eStaticServiceMP3Info::getName(const eServiceReference &ref, std::string &name)
{
	if ( ref.name.length() )
		name = ref.name;
	else
	{
		size_t last = ref.path.rfind('/');
		if (last != std::string::npos)
			name = ref.path.substr(last+1);
		else
			name = ref.path;
	}
	return 0;
}

int eStaticServiceMP3Info::getLength(const eServiceReference &ref)
{
	return -1;
}

int eStaticServiceMP3Info::getInfo(const eServiceReference &ref, int w)
{
	switch (w)
	{
	case iServiceInformation::sTimeCreate:
		{
			struct stat s;
			if (stat(ref.path.c_str(), &s) == 0)
			{
				return s.st_mtime;
			}
		}
		break;
	case iServiceInformation::sFileSize:
		{
			struct stat s;
			if (stat(ref.path.c_str(), &s) == 0)
			{
				return s.st_size;
			}
		}
		break;
	}
	return iServiceInformation::resNA;
}

long long eStaticServiceMP3Info::getFileSize(const eServiceReference &ref)
{
	struct stat s;
	if (stat(ref.path.c_str(), &s) == 0)
	{
		return s.st_size;
	}
	return 0;
}

RESULT eStaticServiceMP3Info::getEvent(const eServiceReference &ref, ePtr<eServiceEvent> &evt, time_t start_time)
{
	if (ref.path.find("://") != std::string::npos)
	{
		eServiceReference equivalentref(ref);
		equivalentref.type = eServiceFactoryMP3::id;
		equivalentref.path.clear();
		return eEPGCache::getInstance()->lookupEventTime(equivalentref, start_time, evt);
	}
	evt = 0;
	return -1;
}

// eServiceMP3
int eServiceMP3::ac3_delay = 0,
    eServiceMP3::pcm_delay = 0;

eServiceMP3::eServiceMP3(eServiceReference ref):
	m_ref(ref),
//	m_pump(eApp, 1),
	m_nownext_timer(eTimer::create(eApp))
{
	m_subtitle_sync_timer = eTimer::create(eApp);
	m_streamingsrc_timeout = 0;
	//m_stream_tags = 0; openpliPC
	m_currentAudioStream = -1;
	m_currentSubtitleStream = -1;
	m_cachedSubtitleStream = 0; /* report the first subtitle stream to be 'cached'. TODO: use an actual cache. */
	m_subtitle_widget = 0;
	m_currentTrickRatio = 1.0;
	m_buffer_size = 5*1024*1024;
	m_buffer_duration = 5 * GST_SECOND;
	m_use_prefillbuffer = FALSE;
	m_prev_decoder_time = -1;
	m_decoder_time_valid_state = 0;
	m_errorInfo.missing_codec = "";
//	audioSink = videoSink = NULL; openPLiPC
	
	CONNECT(m_subtitle_sync_timer->timeout, eServiceMP3::pushSubtitles);
	//CONNECT(m_pump.recv_msg, eServiceMP3::gstPoll); openpliPC
	CONNECT(m_nownext_timer->timeout, eServiceMP3::updateEpgCacheNowNext);
	m_aspect = m_width = m_height = m_framerate = m_progressive = -1;

	m_state = stIdle;
	eDebug("eServiceMP3::construct!");

	const char *filename = m_ref.path.c_str();
	const char *ext = strrchr(filename, '.');
	if (!ext)
		ext = filename;

	m_sourceinfo.is_video = FALSE;
	m_sourceinfo.audiotype = atUnknown;
	if ( (strcasecmp(ext, ".mpeg") && strcasecmp(ext, ".mpg") && strcasecmp(ext, ".vob") && strcasecmp(ext, ".bin") && strcasecmp(ext, ".dat") ) == 0 )
	{
		m_sourceinfo.containertype = ctMPEGPS;
		m_sourceinfo.is_video = TRUE;
	}
	else if ( strcasecmp(ext, ".ts") == 0 )
	{
		m_sourceinfo.containertype = ctMPEGTS;
		m_sourceinfo.is_video = TRUE;
	}
	else if ( strcasecmp(ext, ".mkv") == 0 )
	{
		m_sourceinfo.containertype = ctMKV;
		m_sourceinfo.is_video = TRUE;
	}
	else if ( strcasecmp(ext, ".ogm") == 0 || strcasecmp(ext, ".ogv") == 0)
	{
		m_sourceinfo.containertype = ctOGG;
		m_sourceinfo.is_video = TRUE;
	}
	else if ( strcasecmp(ext, ".avi") == 0 || strcasecmp(ext, ".divx") == 0)
	{
		m_sourceinfo.containertype = ctAVI;
		m_sourceinfo.is_video = TRUE;
	}
	else if ( strcasecmp(ext, ".mp4") == 0 || strcasecmp(ext, ".mov") == 0 || strcasecmp(ext, ".m4v") == 0 || strcasecmp(ext, ".3gp") == 0 || strcasecmp(ext, ".3g2") == 0)
	{
		m_sourceinfo.containertype = ctMP4;
		m_sourceinfo.is_video = TRUE;
	}
	else if ( strcasecmp(ext, ".asf") == 0 || strcasecmp(ext, ".wmv") == 0)
	{
		m_sourceinfo.containertype = ctASF;
		m_sourceinfo.is_video = TRUE;
	}
	else if ( strcasecmp(ext, ".m4a") == 0 )
	{
		m_sourceinfo.containertype = ctMP4;
		m_sourceinfo.audiotype = atAAC;
	}
	else if ( strcasecmp(ext, ".mp3") == 0 )
		m_sourceinfo.audiotype = atMP3;
	else if ( strcasecmp(ext, ".wma") == 0 )
		m_sourceinfo.audiotype = atWMA;
	else if ( (strncmp(filename, "/autofs/", 8) || strncmp(filename+strlen(filename)-13, "/track-", 7) || strcasecmp(ext, ".wav")) == 0 )
		m_sourceinfo.containertype = ctCDA;
	if ( strcasecmp(ext, ".dat") == 0 )
	{
		m_sourceinfo.containertype = ctVCD;
		m_sourceinfo.is_video = TRUE;
	}
	if ( strstr(filename, "://") )
		m_sourceinfo.is_streaming = TRUE;
	if ( strstr(filename, " buffer=1") )
		m_use_prefillbuffer = TRUE;

/*	 openPLiPC

	gchar *uri;

	if ( m_sourceinfo.is_streaming )
	{
		uri = g_strdup_printf ("%s", filename);
		m_streamingsrc_timeout = eTimer::create(eApp);;
		CONNECT(m_streamingsrc_timeout->timeout, eServiceMP3::sourceTimeout);

		std::string config_str;
		if( ePythonConfigQuery::getConfigValue("config.mediaplayer.useAlternateUserAgent", config_str) == 0 )
		{
			if ( config_str == "True" )
				ePythonConfigQuery::getConfigValue("config.mediaplayer.alternateUserAgent", m_useragent);
		}
		if ( m_useragent.length() == 0 )
			m_useragent = "Dream Multimedia Dreambox Enigma2 Mediaplayer";
	}
	else if ( m_sourceinfo.containertype == ctCDA )
	{
		int i_track = atoi(filename+18);
		uri = g_strdup_printf ("cdda://%i", i_track);
	}
	else if ( m_sourceinfo.containertype == ctVCD )
	{
		int ret = -1;
		int fd = open(filename,O_RDONLY);
		if (fd >= 0)
		{
			char tmp[128*1024];
			ret = read(fd, tmp, 128*1024);
			close(fd);
		}
		if ( ret == -1 ) // this is a "REAL" VCD
			uri = g_strdup_printf ("vcd://");
		else
			uri = g_filename_to_uri(filename, NULL, NULL);
	}
	else
		uri = g_filename_to_uri(filename, NULL, NULL);

	eDebug("eServiceMP3::playbin2 uri=%s", uri);

	m_gst_playbin = gst_element_factory_make("playbin2", "playbin");
	if ( m_gst_playbin )
	{
		g_object_set (G_OBJECT (m_gst_playbin), "uri", uri, NULL);
		int flags = 0x47; // ( GST_PLAY_FLAG_VIDEO | GST_PLAY_FLAG_AUDIO | GST_PLAY_FLAG_NATIVE_VIDEO | GST_PLAY_FLAG_TEXT );
		if ( m_sourceinfo.is_streaming )
		{
			g_signal_connect (G_OBJECT (m_gst_playbin), "notify::source", G_CALLBACK (gstHTTPSourceSetAgent), this);
			if (m_use_prefillbuffer)
			{
				g_object_set (G_OBJECT (m_gst_playbin), "buffer_duration", m_buffer_duration, NULL);
				flags |= 0x100; // USE_BUFFERING
			}
		}
		g_object_set (G_OBJECT (m_gst_playbin), "flags", flags, NULL);
		GstElement *subsink = gst_element_factory_make("subsink", "subtitle_sink");
		if (!subsink)
			eDebug("eServiceMP3::sorry, can't play: missing gst-plugin-subsink");
		else
		{
			m_subs_to_pull_handler_id = g_signal_connect (subsink, "new-buffer", G_CALLBACK (gstCBsubtitleAvail), this);
			g_object_set (G_OBJECT (subsink), "caps", gst_caps_from_string("text/plain; text/x-plain; text/x-pango-markup; video/x-dvd-subpicture; subpicture/x-pgs"), NULL);
			g_object_set (G_OBJECT (m_gst_playbin), "text-sink", subsink, NULL);
			g_object_set (G_OBJECT (m_gst_playbin), "current-text", m_currentSubtitleStream, NULL);
		}
		GstBus *bus = gst_pipeline_get_bus(GST_PIPELINE (m_gst_playbin));
		gst_bus_set_sync_handler(bus , gstBusSyncHandler, this);
		gst_object_unref(bus);
		char srt_filename[strlen(filename)+1];
		strncpy(srt_filename,filename,strlen(filename)-3);
		srt_filename[strlen(filename)-3]='\0';
		strcat(srt_filename, "srt");
		struct stat buffer;
		if (stat(srt_filename, &buffer) == 0)
		{
			eDebug("eServiceMP3::subtitle uri: %s", g_filename_to_uri(srt_filename, NULL, NULL));
			g_object_set (G_OBJECT (m_gst_playbin), "suburi", g_filename_to_uri(srt_filename, NULL, NULL), NULL);
		}
	} else
	{
		m_event((iPlayableService*)this, evUser+12);
		m_gst_playbin = 0;
		m_errorInfo.error_message = "failed to create GStreamer pipeline!\n";

		eDebug("eServiceMP3::sorry, can't play: %s",m_errorInfo.error_message.c_str());
	}
	g_free(uri);

	setBufferSize(m_buffer_size);

*/
  
  cXineLib *xineLib = cXineLib::getInstance();
	int uzunluk;
	uzunluk=strlen(filename);
	char myfilesrt[1000];
	sprintf(myfilesrt,"%s",filename);
	myfilesrt[uzunluk-4]='\0';
	char myfile[1000];
	sprintf(myfile,"%s#subtitle:%s.srt",filename,myfilesrt);
	xineLib->FilmVideo(myfile); 
}

eServiceMP3::~eServiceMP3()
{
/*	openPLiPC

		// disconnect subtitle callback
	GstElement *subsink = gst_bin_get_by_name(GST_BIN(m_gst_playbin), "subtitle_sink");

	if (subsink)
	{
		g_signal_handler_disconnect (subsink, m_subs_to_pull_handler_id);
		gst_object_unref(subsink);
	}

	delete m_subtitle_widget;

	if (m_gst_playbin)
	{
		// disconnect sync handler callback
		GstBus *bus = gst_pipeline_get_bus(GST_PIPELINE (m_gst_playbin));
		gst_bus_set_sync_handler(bus, NULL, NULL);
		gst_object_unref(bus);
	}

*/
  
	if (m_state == stRunning)
		stop();

/*	openPLiPC

	if (m_stream_tags)
		gst_tag_list_free(m_stream_tags);

	if (audioSink)
	{
		gst_object_unref(GST_OBJECT(audioSink));
		audioSink = NULL;
	}
	if (videoSink)
	{
		gst_object_unref(GST_OBJECT(videoSink));
		videoSink = NULL;
	}
	if (m_gst_playbin)
	{
		gst_object_unref (GST_OBJECT (m_gst_playbin));
		eDebug("eServiceMP3::destruct!");
	}

*/
}

void eServiceMP3::updateEpgCacheNowNext()
{
	bool update = false;
	ePtr<eServiceEvent> next = 0;
	ePtr<eServiceEvent> ptr = 0;
	eServiceReference ref(m_ref);
	ref.type = eServiceFactoryMP3::id;
	ref.path.clear();
	if (eEPGCache::getInstance() && eEPGCache::getInstance()->lookupEventTime(ref, -1, ptr) >= 0)
	{
		ePtr<eServiceEvent> current = m_event_now;
		if (!current || !ptr || current->getEventId() != ptr->getEventId())
		{
			update = true;
			m_event_now = ptr;
			time_t next_time = ptr->getBeginTime() + ptr->getDuration();
			if (eEPGCache::getInstance()->lookupEventTime(ref, next_time, ptr) >= 0)
			{
				next = ptr;
				m_event_next = ptr;
			}
		}
	}

	int refreshtime = 60;
	if (!next)
	{
		next = m_event_next;
	}
	if (next)
	{
		time_t now = eDVBLocalTimeHandler::getInstance()->nowTime();
		refreshtime = (int)(next->getBeginTime() - now) + 3;
		if (refreshtime <= 0 || refreshtime > 60)
		{
			refreshtime = 60;
		}
	}
	m_nownext_timer->startLongTimer(refreshtime);
	if (update)
	{
		m_event((iPlayableService*)this, evUpdatedEventInfo);
	}
}

DEFINE_REF(eServiceMP3);

//DEFINE_REF(eServiceMP3::GstMessageContainer); openpliPC

RESULT eServiceMP3::connectEvent(const Slot2<void,iPlayableService*,int> &event, ePtr<eConnection> &connection)
{
	connection = new eConnection((iPlayableService*)this, m_event.connect(event));
	return 0;
}

RESULT eServiceMP3::start()
{
//	ASSERT(m_state == stIdle); openpliPC

	m_state = stRunning;

/*	openPLiPC

	if (m_gst_playbin)
	{
		eDebug("eServiceMP3::starting pipeline");
		gst_element_set_state (m_gst_playbin, GST_STATE_PLAYING);
	}

*/

	updateEpgCacheNowNext();
	m_event(this, evStart);

	return 0;
}

void eServiceMP3::sourceTimeout()
{
	eDebug("eServiceMP3::http source timeout! issuing eof...");
	m_event((iPlayableService*)this, evEOF);
}

RESULT eServiceMP3::stop()
{
	ASSERT(m_state != stIdle);

	if (m_state == stStopped)
		return -1;

	eDebug("eServiceMP3::stop %s", m_ref.path.c_str());
	//gst_element_set_state(m_gst_playbin, GST_STATE_NULL); openpliPC
	cXineLib *xineLib = cXineLib::getInstance();
	xineLib->stopVideo();
	m_state = stStopped;
	m_nownext_timer->stop();

	return 0;
}

RESULT eServiceMP3::setTarget(int target)
{
	return -1;
}

RESULT eServiceMP3::pause(ePtr<iPauseableService> &ptr)
{
	ptr=this;
	return 0;
}

RESULT eServiceMP3::setSlowMotion(int ratio)
{
	if (!ratio)
		return 0;
	eDebug("eServiceMP3::setSlowMotion ratio=%f",1.0/(gdouble)ratio);
	return trickSeek(1.0/(gdouble)ratio);
}

RESULT eServiceMP3::setFastForward(int ratio)
{
	eDebug("eServiceMP3::setFastForward ratio=%i",ratio);
	return trickSeek(ratio);
}

		// iPausableService
RESULT eServiceMP3::pause()
{
	//if (!m_gst_playbin || m_state != stRunning) openpliPC
	if (m_state != stRunning)
		return -1;

	//trickSeek(0.0); openpliPC

	cXineLib *xineLib = cXineLib::getInstance();
	xineLib->VideoPause();

	return 0;
}

RESULT eServiceMP3::unpause()
{
	//if (!m_gst_playbin || m_state != stRunning) openpliPC
	if (m_state != stRunning)
		return -1;

	//trickSeek(1.0); openpliPC

	cXineLib *xineLib = cXineLib::getInstance();
	xineLib->VideoResume();

	return 0;
}

	/* iSeekableService */
RESULT eServiceMP3::seek(ePtr<iSeekableService> &ptr)
{
	ptr = this;
	return 0;
}

RESULT eServiceMP3::getLength(pts_t &pts)
{
	if (m_state != stRunning)
		return -1;

	cXineLib *xineLib = cXineLib::getInstance();
	xineLib->VideoPosisyon();
	pts=xineLib->Vlength*90;
	return 0;
}

RESULT eServiceMP3::seekToImpl(pts_t to)
{
	return 0;
}

RESULT eServiceMP3::seekTo(pts_t to)
{
	cXineLib *xineLib = cXineLib::getInstance();
	xineLib->SeekTo(to/90);

	RESULT ret = 0;
	return ret;
}


RESULT eServiceMP3::trickSeek(gdouble ratio)
{
//	m_currentTrickRatio = ratio;
	printf("----Ratio=%d\n",ratio);
	cXineLib *xineLib = cXineLib::getInstance();
	xineLib->VideoIleriF();
	//if (!ratio) return seekRelative(0, 0);	
	m_subtitle_pages.clear();
	m_prev_decoder_time = -1;
	m_decoder_time_valid_state = 0;
	return 0;
}

/*	openPLiPC

gint eServiceMP3::match_sinktype(GstElement *element, gpointer type)
{
	return strcmp(g_type_name(G_OBJECT_TYPE(element)), (const char*)type);
}

*/

RESULT eServiceMP3::seekRelative(int direction, pts_t to)
{
	eDebug("eDVBServicePlay::seekRelative: jump %d, %lld", direction, to);
	cXineLib *xineLib = cXineLib::getInstance();
	xineLib->VideoGeriT(to/90*direction);
	return 0;
}

RESULT eServiceMP3::getPlayPosition(pts_t &pts)
{
	if (m_state != stRunning)
		return -1;

	cXineLib *xineLib = cXineLib::getInstance();
	xineLib->VideoPosisyon();
	pts=xineLib->Vpos*90;
	return 0;
}

RESULT eServiceMP3::setTrickmode(int trick)
{
		/* trickmode is not yet supported by our dvbmediasinks. */
	return -1;
}

RESULT eServiceMP3::isCurrentlySeekable()
{
	if (m_state != stRunning)
		return 0;

	int ret = 3; // seeking and fast/slow winding possible
	return ret;
}

RESULT eServiceMP3::info(ePtr<iServiceInformation>&i)
{
	i = this;
	return 0;
}

RESULT eServiceMP3::getName(std::string &name)
{
	std::string title = m_ref.getName();
	if (title.empty())
	{
		name = m_ref.path;
		size_t n = name.rfind('/');
		if (n != std::string::npos)
			name = name.substr(n + 1);
	}
	else
		name = title;
	return 0;
}

RESULT eServiceMP3::getEvent(ePtr<eServiceEvent> &evt, int nownext)
{
	evt = nownext ? m_event_next : m_event_now;
	if (!evt)
		return -1;
	return 0;
}

int eServiceMP3::getInfo(int w)
{
	cXineLib *xineLib = cXineLib::getInstance();
 
 	switch (w)
 	{
 	case sServiceref: return m_ref;
	case sVideoHeight:
		return xineLib->getVideoHeight();
		break;
	case sVideoWidth:
		return xineLib->getVideoWidth();
		break;
	case sFrameRate:
		return xineLib->getVideoFrameRate();
		break;
 	case sTagTitle:
 	case sTagArtist:
 	case sTagAlbum:
	case sTagTitleSortname:
	case sTagArtistSortname:
	case sTagAlbumSortname:
	case sTagDate:
	case sTagComposer:
	case sTagGenre:
	case sTagComment:
	case sTagExtendedComment:
	case sTagLocation:
	case sTagHomepage:
	case sTagDescription:
	case sTagVersion:
	case sTagISRC:
	case sTagOrganization:
	case sTagCopyright:
	case sTagCopyrightURI:
	case sTagContact:
	case sTagLicense:
	case sTagLicenseURI:
	case sTagCodec:
	case sTagAudioCodec:
	case sTagVideoCodec:
	case sTagEncoder:
	case sTagLanguageCode:
	case sTagKeywords:
	case sTagChannelMode:
	case sUser+12:
		return resIsString;
	case sTagTrackGain:
	case sTagTrackPeak:
	case sTagAlbumGain:
	case sTagAlbumPeak:
	case sTagReferenceLevel:
	case sTagBeatsPerMinute:
	case sTagImage:
 	case sTagPreviewImage:
 	case sTagAttachment:
		return resIsPyObject;
		break;
	case sBuffer: return m_bufferInfo.bufferPercent;
	default:
		return resNA;
	}

	return 0;
}

std::string eServiceMP3::getInfoString(int w)
{
	return "";
}

PyObject *eServiceMP3::getInfoObject(int w)
{
	Py_RETURN_NONE;
}

RESULT eServiceMP3::audioChannel(ePtr<iAudioChannelSelection> &ptr)
{
	ptr = this;
	return 0;
}

RESULT eServiceMP3::audioTracks(ePtr<iAudioTrackSelection> &ptr)
{
	ptr = this;
	return 0;
}

RESULT eServiceMP3::subtitle(ePtr<iSubtitleOutput> &ptr)
{
	ptr = this;
	return 0;
}

RESULT eServiceMP3::audioDelay(ePtr<iAudioDelay> &ptr)
{
	ptr = this;
	return 0;
}

int eServiceMP3::getNumberOfTracks()
{
	cXineLib *xineLib = cXineLib::getInstance();
	int ret=xineLib->getNumberOfTracksAudio();
	//printf("Number of tracks - %d\n", ret);
	if (ret) 
	{
		return ret;
	}
	return 0;
}

int eServiceMP3::getCurrentTrack()
{
	cXineLib *xineLib = cXineLib::getInstance();
	int ret = xineLib->getCurrentTrackAudio();
	//printf("Current  track audio - %d\n", ret);
	return ret;
}

RESULT eServiceMP3::selectTrack(unsigned int i)
{
	pts_t ppos;
	getPlayPosition(ppos);
	ppos -= 90000;
	if (ppos < 0)
		ppos = 0;

	int ret = selectAudioStream(i);
	if (!ret) {
		/* flush */
		//seekTo(ppos);
	}

	return ret;
}

int eServiceMP3::selectAudioStream(int i)
{
	cXineLib *xineLib = cXineLib::getInstance();
	xineLib->selectAudioStream(i);

	//return 0;
	return i;
}

int eServiceMP3::getCurrentChannel()
{
	return STEREO;
}

RESULT eServiceMP3::selectChannel(int i)
{
	eDebug("eServiceMP3::selectChannel(%i)",i);
	return 0;
}

RESULT eServiceMP3::getTrackInfo(struct iAudioTrackInfo &info, unsigned int i)
{
	cXineLib *xineLib = cXineLib::getInstance();
	info.m_description = "???";

	if (info.m_language.empty())
		info.m_language = xineLib->getAudioLang(i);

	return 0;
}

/*	openPLiPC

subtype_t getSubtitleType(GstPad* pad, gchar *g_codec=NULL)
{
	subtype_t type = stUnknown;
	GstCaps* caps = gst_pad_get_negotiated_caps(pad);
	if (!caps && !g_codec)
	{
		caps = gst_pad_get_allowed_caps(pad);
	}

	if ( caps )
	{
		GstStructure* str = gst_caps_get_structure(caps, 0);
		const gchar *g_type = gst_structure_get_name(str);
		eDebug("getSubtitleType::subtitle probe caps type=%s", g_type);

		if ( !strcmp(g_type, "video/x-dvd-subpicture") )
			type = stVOB;
		else if ( !strcmp(g_type, "text/x-pango-markup") )
			type = stSRT;
		else if ( !strcmp(g_type, "text/plain") )
			type = stPlainText;
		else if ( !strcmp(g_type, "subpicture/x-pgs") )
			type = stPGS;
		else
			eDebug("getSubtitleType::unsupported subtitle caps %s (%s)", g_type, g_codec);
	}
	else if ( g_codec )
	{
		eDebug("getSubtitleType::subtitle probe codec tag=%s", g_codec);
		if ( !strcmp(g_codec, "VOB") )
			type = stVOB;
		else if ( !strcmp(g_codec, "SubStation Alpha") || !strcmp(g_codec, "SSA") )
			type = stSSA;
		else if ( !strcmp(g_codec, "ASS") )
			type = stASS;
		else if ( !strcmp(g_codec, "SRT") )
			type = stSRT;
		else if ( !strcmp(g_codec, "UTF-8 plain text") )
			type = stPlainText;
		else
			eDebug("getSubtitleType::unsupported subtitle codec %s", g_codec);
	}
	else
		eDebug("getSubtitleType::unidentifiable subtitle stream!");

	return type;
}

void eServiceMP3::gstBusCall(GstMessage *msg)
{
	if (!msg)
		return;
	gchar *sourceName;
	GstObject *source;
	source = GST_MESSAGE_SRC(msg);
	if (!GST_IS_OBJECT(source))
		return;
	sourceName = gst_object_get_name(source);
#if 0
	gchar *string;
	if (gst_message_get_structure(msg))
		string = gst_structure_to_string(gst_message_get_structure(msg));
	else
		string = g_strdup(GST_MESSAGE_TYPE_NAME(msg));
	eDebug("eTsRemoteSource::gst_message from %s: %s", sourceName, string);
	g_free(string);
#endif
	switch (GST_MESSAGE_TYPE (msg))
	{
		case GST_MESSAGE_EOS:
			m_event((iPlayableService*)this, evEOF);
			break;
		case GST_MESSAGE_STATE_CHANGED:
		{
			if(GST_MESSAGE_SRC(msg) != GST_OBJECT(m_gst_playbin))
				break;

			GstState old_state, new_state;
			gst_message_parse_state_changed(msg, &old_state, &new_state, NULL);
		
			if(old_state == new_state)
				break;
	
			eDebug("eServiceMP3::state transition %s -> %s", gst_element_state_get_name(old_state), gst_element_state_get_name(new_state));
	
			GstStateChange transition = (GstStateChange)GST_STATE_TRANSITION(old_state, new_state);
	
			switch(transition)
			{
				case GST_STATE_CHANGE_NULL_TO_READY:
				{
				}	break;
				case GST_STATE_CHANGE_READY_TO_PAUSED:
				{
					GstIterator *children;
					GstElement *subsink = gst_bin_get_by_name(GST_BIN(m_gst_playbin), "subtitle_sink");
					if (subsink)
					{
#ifdef GSTREAMER_SUBTITLE_SYNC_MODE_BUG
						//
						// HACK: disable sync mode for now, gstreamer suffers from a bug causing sparse streams to loose sync, after pause/resume / skip
						// see: https://bugzilla.gnome.org/show_bug.cgi?id=619434
						// Sideeffect of using sync=false is that we receive subtitle buffers (far) ahead of their
						// display time.
						// Not too far ahead for subtitles contained in the media container.
						// But for external srt files, we could receive all subtitles at once.
						// And not just once, but after each pause/resume / skip.
						// So as soon as gstreamer has been fixed to keep sync in sparse streams, sync needs to be re-enabled.
						//
						g_object_set (G_OBJECT (subsink), "sync", FALSE, NULL);
#endif
#if 0
						// we should not use ts-offset to sync with the decoder time, we have to do our own decoder timekeeping
						g_object_set (G_OBJECT (subsink), "ts-offset", -2L * GST_SECOND, NULL);
						// late buffers probably will not occur very often
						g_object_set (G_OBJECT (subsink), "max-lateness", 0L, NULL);
						// avoid prerolling (it might not be a good idea to preroll a sparse stream)
						g_object_set (G_OBJECT (subsink), "async", TRUE, NULL);
#endif
						eDebug("eServiceMP3::subsink properties set!");
						gst_object_unref(subsink);
					}
					if (audioSink)
					{
						gst_object_unref(GST_OBJECT(audioSink));
						audioSink = NULL;
					}
					if (videoSink)
					{
						gst_object_unref(GST_OBJECT(videoSink));
						videoSink = NULL;
					}
					children = gst_bin_iterate_recurse(GST_BIN(m_gst_playbin));
					audioSink = GST_ELEMENT_CAST(gst_iterator_find_custom(children, (GCompareFunc)match_sinktype, (gpointer)"GstDVBAudioSink"));
					videoSink = GST_ELEMENT_CAST(gst_iterator_find_custom(children, (GCompareFunc)match_sinktype, (gpointer)"GstDVBVideoSink"));
					gst_iterator_free(children);

					setAC3Delay(ac3_delay);
					setPCMDelay(pcm_delay);
				}	break;
				case GST_STATE_CHANGE_PAUSED_TO_PLAYING:
				{
					if ( m_sourceinfo.is_streaming && m_streamingsrc_timeout )
						m_streamingsrc_timeout->stop();
				}	break;
				case GST_STATE_CHANGE_PLAYING_TO_PAUSED:
				{
				}	break;
				case GST_STATE_CHANGE_PAUSED_TO_READY:
				{
					if (audioSink)
					{
						gst_object_unref(GST_OBJECT(audioSink));
						audioSink = NULL;
					}
					if (videoSink)
					{
						gst_object_unref(GST_OBJECT(videoSink));
						videoSink = NULL;
					}
				}	break;
				case GST_STATE_CHANGE_READY_TO_NULL:
				{
				}	break;
			}
			break;
		}
		case GST_MESSAGE_ERROR:
		{
			gchar *debug;
			GError *err;
			gst_message_parse_error (msg, &err, &debug);
			g_free (debug);
			eWarning("Gstreamer error: %s (%i) from %s", err->message, err->code, sourceName );
			if ( err->domain == GST_STREAM_ERROR )
			{
				if ( err->code == GST_STREAM_ERROR_CODEC_NOT_FOUND )
				{
					if ( g_strrstr(sourceName, "videosink") )
						m_event((iPlayableService*)this, evUser+11);
					else if ( g_strrstr(sourceName, "audiosink") )
						m_event((iPlayableService*)this, evUser+10);
				}
			}
			g_error_free(err);
			break;
		}
		case GST_MESSAGE_INFO:
		{
			gchar *debug;
			GError *inf;
	
			gst_message_parse_info (msg, &inf, &debug);
			g_free (debug);
			if ( inf->domain == GST_STREAM_ERROR && inf->code == GST_STREAM_ERROR_DECODE )
			{
				if ( g_strrstr(sourceName, "videosink") )
					m_event((iPlayableService*)this, evUser+14);
			}
			g_error_free(inf);
			break;
		}
		case GST_MESSAGE_TAG:
		{
			GstTagList *tags, *result;
			gst_message_parse_tag(msg, &tags);
	
			result = gst_tag_list_merge(m_stream_tags, tags, GST_TAG_MERGE_REPLACE);
			if (result)
			{
				if (m_stream_tags)
					gst_tag_list_free(m_stream_tags);
				m_stream_tags = result;
			}
	
			const GValue *gv_image = gst_tag_list_get_value_index(tags, GST_TAG_IMAGE, 0);
			if ( gv_image )
			{
				GstBuffer *buf_image;
				buf_image = gst_value_get_buffer (gv_image);
				int fd = open("/tmp/.id3coverart", O_CREAT|O_WRONLY|O_TRUNC, 0644);
				if (fd >= 0)
				{
					int ret = write(fd, GST_BUFFER_DATA(buf_image), GST_BUFFER_SIZE(buf_image));
					close(fd);
					eDebug("eServiceMP3::/tmp/.id3coverart %d bytes written ", ret);
				}
				m_event((iPlayableService*)this, evUser+13);
			}
			gst_tag_list_free(tags);
			m_event((iPlayableService*)this, evUpdatedInfo);
			break;
		}
		case GST_MESSAGE_ASYNC_DONE:
		{
			if(GST_MESSAGE_SRC(msg) != GST_OBJECT(m_gst_playbin))
				break;

			GstTagList *tags;
			gint i, active_idx, n_video = 0, n_audio = 0, n_text = 0;

			g_object_get (m_gst_playbin, "n-video", &n_video, NULL);
			g_object_get (m_gst_playbin, "n-audio", &n_audio, NULL);
			g_object_get (m_gst_playbin, "n-text", &n_text, NULL);

			eDebug("eServiceMP3::async-done - %d video, %d audio, %d subtitle", n_video, n_audio, n_text);

			if ( n_video + n_audio <= 0 )
				stop();

			active_idx = 0;

			m_audioStreams.clear();
			m_subtitleStreams.clear();

			for (i = 0; i < n_audio; i++)
			{
				audioStream audio;
				gchar *g_codec, *g_lang;
				GstPad* pad = 0;
				g_signal_emit_by_name (m_gst_playbin, "get-audio-pad", i, &pad);
				GstCaps* caps = gst_pad_get_negotiated_caps(pad);
				if (!caps)
					continue;
				GstStructure* str = gst_caps_get_structure(caps, 0);
				const gchar *g_type = gst_structure_get_name(str);
				eDebug("AUDIO STRUCT=%s", g_type);
				audio.type = gstCheckAudioPad(str);
				g_codec = g_strdup(g_type);
				g_lang = g_strdup_printf ("und");
				g_signal_emit_by_name (m_gst_playbin, "get-audio-tags", i, &tags);
				if ( tags && gst_is_tag_list(tags) )
				{
					gst_tag_list_get_string(tags, GST_TAG_AUDIO_CODEC, &g_codec);
					gst_tag_list_get_string(tags, GST_TAG_LANGUAGE_CODE, &g_lang);
					gst_tag_list_free(tags);
				}
				audio.language_code = std::string(g_lang);
				audio.codec = std::string(g_codec);
				eDebug("eServiceMP3::audio stream=%i codec=%s language=%s", i, g_codec, g_lang);
				m_audioStreams.push_back(audio);
				g_free (g_lang);
				g_free (g_codec);
				gst_caps_unref(caps);
			}

			for (i = 0; i < n_text; i++)
			{	
				gchar *g_codec = NULL, *g_lang = NULL;
				g_signal_emit_by_name (m_gst_playbin, "get-text-tags", i, &tags);
				subtitleStream subs;

				g_lang = g_strdup_printf ("und");
				if ( tags && gst_is_tag_list(tags) )
				{
					gst_tag_list_get_string(tags, GST_TAG_LANGUAGE_CODE, &g_lang);
					gst_tag_list_get_string(tags, GST_TAG_SUBTITLE_CODEC, &g_codec);
					gst_tag_list_free(tags);
				}

				subs.language_code = std::string(g_lang);
				eDebug("eServiceMP3::subtitle stream=%i language=%s codec=%s", i, g_lang, g_codec);
				
				GstPad* pad = 0;
				g_signal_emit_by_name (m_gst_playbin, "get-text-pad", i, &pad);
				if ( pad )
					g_signal_connect (G_OBJECT (pad), "notify::caps", G_CALLBACK (gstTextpadHasCAPS), this);
				subs.type = getSubtitleType(pad, g_codec);

				m_subtitleStreams.push_back(subs);
				g_free (g_lang);
			}
			m_event((iPlayableService*)this, evUpdatedInfo);

			if ( m_errorInfo.missing_codec != "" )
			{
				if ( m_errorInfo.missing_codec.find("video/") == 0 || ( m_errorInfo.missing_codec.find("audio/") == 0 && getNumberOfTracks() == 0 ) )
					m_event((iPlayableService*)this, evUser+12);
			}
			break;
		}
		case GST_MESSAGE_ELEMENT:
		{
			const GstStructure *msgstruct = gst_message_get_structure(msg);
			if (msgstruct)
			{
				if ( gst_is_missing_plugin_message(msg) )
				{
					GstCaps *caps = NULL;
					gst_structure_get (msgstruct, "detail", GST_TYPE_CAPS, &caps, NULL);
					if (caps)
					{
						std::string codec = (const char*) gst_caps_to_string(caps);
						gchar *description = gst_missing_plugin_message_get_description(msg);
						if ( description )
						{
							eDebug("eServiceMP3::m_errorInfo.missing_codec = %s", codec.c_str());
							m_errorInfo.error_message = "GStreamer plugin " + (std::string)description + " not available!\n";
							m_errorInfo.missing_codec = codec.substr(0,(codec.find_first_of(',')));
							g_free(description);
						}
						gst_caps_unref(caps);
					}
				}
				else
				{
					const gchar *eventname = gst_structure_get_name(msgstruct);
					if ( eventname )
					{
						if (!strcmp(eventname, "eventSizeChanged") || !strcmp(eventname, "eventSizeAvail"))
						{
							gst_structure_get_int (msgstruct, "aspect_ratio", &m_aspect);
							gst_structure_get_int (msgstruct, "width", &m_width);
							gst_structure_get_int (msgstruct, "height", &m_height);
							if (strstr(eventname, "Changed"))
								m_event((iPlayableService*)this, evVideoSizeChanged);
						}
						else if (!strcmp(eventname, "eventFrameRateChanged") || !strcmp(eventname, "eventFrameRateAvail"))
						{
							gst_structure_get_int (msgstruct, "frame_rate", &m_framerate);
							if (strstr(eventname, "Changed"))
								m_event((iPlayableService*)this, evVideoFramerateChanged);
						}
						else if (!strcmp(eventname, "eventProgressiveChanged") || !strcmp(eventname, "eventProgressiveAvail"))
						{
							gst_structure_get_int (msgstruct, "progressive", &m_progressive);
							if (strstr(eventname, "Changed"))
								m_event((iPlayableService*)this, evVideoProgressiveChanged);
						}
						else if (!strcmp(eventname, "redirect"))
						{
							const char *uri = gst_structure_get_string(msgstruct, "new-location");
							eDebug("redirect to %s", uri);
							gst_element_set_state (m_gst_playbin, GST_STATE_NULL);
							g_object_set(G_OBJECT (m_gst_playbin), "uri", uri, NULL);
							gst_element_set_state (m_gst_playbin, GST_STATE_PLAYING);
						}
					}
				}
			}
			break;
		}
		case GST_MESSAGE_BUFFERING:
		{
			GstBufferingMode mode;
			gst_message_parse_buffering(msg, &(m_bufferInfo.bufferPercent));
			eDebug("Buffering %u percent done", m_bufferInfo.bufferPercent);
			gst_message_parse_buffering_stats(msg, &mode, &(m_bufferInfo.avgInRate), &(m_bufferInfo.avgOutRate), &(m_bufferInfo.bufferingLeft));
			m_event((iPlayableService*)this, evBuffering);
			if (m_state == stRunning && m_use_prefillbuffer)
			{
				if (m_bufferInfo.bufferPercent == 100)
				{
					eDebug("start playing");
					gst_element_set_state (m_gst_playbin, GST_STATE_PLAYING);
				}
				if (m_bufferInfo.bufferPercent == 0)
				{
					eDebug("start pause");
					gst_element_set_state (m_gst_playbin, GST_STATE_PAUSED);
				}
			}
			break;
		}
		case GST_MESSAGE_STREAM_STATUS:
		{
			GstStreamStatusType type;
			GstElement *owner;
			gst_message_parse_stream_status (msg, &type, &owner);
			if ( type == GST_STREAM_STATUS_TYPE_CREATE && m_sourceinfo.is_streaming )
			{
				if ( GST_IS_PAD(source) )
					owner = gst_pad_get_parent_element(GST_PAD(source));
				else if ( GST_IS_ELEMENT(source) )
					owner = GST_ELEMENT(source);
				else
					owner = 0;
				if ( owner )
				{
					GstElementFactory *factory = gst_element_get_factory(GST_ELEMENT(owner));
					const gchar *name = gst_plugin_feature_get_name(GST_PLUGIN_FEATURE(factory));
					if (!strcmp(name, "souphttpsrc"))
					{
						m_streamingsrc_timeout->start(HTTP_TIMEOUT*1000, true);
						g_object_set (G_OBJECT (owner), "timeout", HTTP_TIMEOUT, NULL);
						eDebug("eServiceMP3::GST_STREAM_STATUS_TYPE_CREATE -> setting timeout on %s to %is", name, HTTP_TIMEOUT);
					}
				}
				if ( GST_IS_PAD(source) )
					gst_object_unref(owner);
			}
			break;
		}
		default:
			break;
	}
	g_free (sourceName);
}

void eServiceMP3::handleMessage(GstMessage *msg)
{
	if (GST_MESSAGE_TYPE(msg) == GST_MESSAGE_STATE_CHANGED && GST_MESSAGE_SRC(msg) != GST_OBJECT(m_gst_playbin))
	{
		//
		// ignore verbose state change messages for all active elements;
		// we only need to handle state-change events for the playbin
		//
		gst_message_unref(msg);
		return;
	}
	m_pump.send(new GstMessageContainer(1, msg, NULL, NULL));
}

GstBusSyncReply eServiceMP3::gstBusSyncHandler(GstBus *bus, GstMessage *message, gpointer user_data)
{
	eServiceMP3 *_this = (eServiceMP3*)user_data;
	if (_this) _this->handleMessage(message);
	return GST_BUS_DROP;
}

void eServiceMP3::gstHTTPSourceSetAgent(GObject *object, GParamSpec *unused, gpointer user_data)
{
	eServiceMP3 *_this = (eServiceMP3*)user_data;
	GstElement *source = NULL;
	g_object_get(_this->m_gst_playbin, "source", &source, NULL);
	if (source)
	{
		g_object_set (G_OBJECT (source), "user-agent", _this->m_useragent.c_str(), NULL);
		gst_object_unref(source);
	}
}

audiotype_t eServiceMP3::gstCheckAudioPad(GstStructure* structure)
{
	if (!structure)
		return atUnknown;

	if ( gst_structure_has_name (structure, "audio/mpeg"))
	{
		gint mpegversion, layer = -1;
		if (!gst_structure_get_int (structure, "mpegversion", &mpegversion))
			return atUnknown;

		switch (mpegversion) {
			case 1:
				{
					gst_structure_get_int (structure, "layer", &layer);
					if ( layer == 3 )
						return atMP3;
					else
						return atMPEG;
					break;
				}
			case 2:
				return atAAC;
			case 4:
				return atAAC;
			default:
				return atUnknown;
		}
	}

	else if ( gst_structure_has_name (structure, "audio/x-ac3") || gst_structure_has_name (structure, "audio/ac3") )
		return atAC3;
	else if ( gst_structure_has_name (structure, "audio/x-dts") || gst_structure_has_name (structure, "audio/dts") )
		return atDTS;
	else if ( gst_structure_has_name (structure, "audio/x-raw-int") )
		return atPCM;

	return atUnknown;
}

void eServiceMP3::gstPoll(ePtr<GstMessageContainer> const &msg)
{
	switch (msg->getType())
	{
		case 1:
		{
			GstMessage *gstmessage = *((GstMessageContainer*)msg);
			if (gstmessage)
			{
				gstBusCall(gstmessage);
			}
			break;
		}
		case 2:
		{
			GstBuffer *buffer = *((GstMessageContainer*)msg);
			if (buffer)
			{
				pullSubtitle(buffer);
			}
			break;
		}
		case 3:
		{
			GstPad *pad = *((GstMessageContainer*)msg);
			gstTextpadHasCAPS_synced(pad);
			break;
		}
	}
}

*/

eAutoInitPtr<eServiceFactoryMP3> init_eServiceFactoryMP3(eAutoInitNumbers::service+1, "eServiceFactoryMP3");

/*	openPLiPC

void eServiceMP3::gstCBsubtitleAvail(GstElement *subsink, GstBuffer *buffer, gpointer user_data)
{
	eServiceMP3 *_this = (eServiceMP3*)user_data;
	if (_this->m_currentSubtitleStream < 0) 
	{
		if (buffer) gst_buffer_unref(buffer);
		return;
	}
	eDebug("gstCBsubtitleAvail: %s", GST_BUFFER_DATA(buffer));
	_this->m_pump.send(new GstMessageContainer(2, NULL, NULL, buffer));
}

void eServiceMP3::gstTextpadHasCAPS(GstPad *pad, GParamSpec * unused, gpointer user_data)
{
	eServiceMP3 *_this = (eServiceMP3*)user_data;

	gst_object_ref (pad);

	_this->m_pump.send(new GstMessageContainer(3, NULL, pad, NULL));
}

void eServiceMP3::gstTextpadHasCAPS_synced(GstPad *pad)
{
	GstCaps *caps = NULL;

	g_object_get (G_OBJECT (pad), "caps", &caps, NULL);

	if (caps)
	{
		subtitleStream subs;

		eDebug("gstTextpadHasCAPS:: signal::caps = %s", gst_caps_to_string(caps));
//		eDebug("gstGhostpadHasCAPS_synced %p %d", pad, m_subtitleStreams.size());

		if (m_currentSubtitleStream >= 0 && m_currentSubtitleStream < (int)m_subtitleStreams.size())
			subs = m_subtitleStreams[m_currentSubtitleStream];
		else {
			subs.type = stUnknown;
			subs.pad = pad;
		}

		if ( subs.type == stUnknown )
		{
			GstTagList *tags;
//			eDebug("gstGhostpadHasCAPS::m_subtitleStreams[%i].type == stUnknown...", m_currentSubtitleStream);

			gchar *g_lang;
			g_signal_emit_by_name (m_gst_playbin, "get-text-tags", m_currentSubtitleStream, &tags);

			g_lang = g_strdup_printf ("und");
			if ( tags && gst_is_tag_list(tags) )
				gst_tag_list_get_string(tags, GST_TAG_LANGUAGE_CODE, &g_lang);

			subs.language_code = std::string(g_lang);
			subs.type = getSubtitleType(pad);

			if (m_currentSubtitleStream >= 0 && m_currentSubtitleStream < (int)m_subtitleStreams.size())
				m_subtitleStreams[m_currentSubtitleStream] = subs;
			else
				m_subtitleStreams.push_back(subs);

			g_free (g_lang);
		}

//		eDebug("gstGhostpadHasCAPS:: m_gst_prev_subtitle_caps=%s equal=%i",gst_caps_to_string(m_gst_prev_subtitle_caps),gst_caps_is_equal(m_gst_prev_subtitle_caps, caps));

		gst_caps_unref (caps);
	}
}

void eServiceMP3::pullSubtitle(GstBuffer *buffer)
{
	if (buffer && m_currentSubtitleStream >= 0 && m_currentSubtitleStream < (int)m_subtitleStreams.size())
	{
		gint64 buf_pos = GST_BUFFER_TIMESTAMP(buffer);
		gint64 duration_ns = GST_BUFFER_DURATION(buffer);
		size_t len = GST_BUFFER_SIZE(buffer);
		eDebug("pullSubtitle m_subtitleStreams[m_currentSubtitleStream].type=%i",m_subtitleStreams[m_currentSubtitleStream].type);

		if ( m_subtitleStreams[m_currentSubtitleStream].type )
		{
			if ( m_subtitleStreams[m_currentSubtitleStream].type < stVOB )
			{
				unsigned char line[len+1];
				SubtitlePage page;
				memcpy(line, GST_BUFFER_DATA(buffer), len);
				line[len] = 0;
				eDebug("got new text subtitle @ buf_pos = %lld ns (in pts=%lld): '%s' ", buf_pos, buf_pos/11111, line);
				gRGB rgbcol(0xD0,0xD0,0xD0);
				page.type = SubtitlePage::Pango;
				page.pango_page.m_elements.push_back(ePangoSubtitlePageElement(rgbcol, (const char*)line));
				page.pango_page.m_show_pts = buf_pos / 11111L;
				page.pango_page.m_timeout = duration_ns / 1000000;
				m_subtitle_pages.push_back(page);
				if (m_subtitle_pages.size()==1)
					pushSubtitles();
			}
			else
			{
				eDebug("unsupported subpicture... ignoring");
			}
		}
	}
}

*/

void eServiceMP3::pushSubtitles()
{

/*	openPLiPC

	while ( !m_subtitle_pages.empty() )
	{
		SubtitlePage &frontpage = m_subtitle_pages.front();
		pts_t running_pts;
		gint64 diff_ms = 0;
		gint64 show_pts = 0;

		getPlayPosition(running_pts);
		if (m_decoder_time_valid_state < 4) {
			++m_decoder_time_valid_state;
			if (m_prev_decoder_time == running_pts)
				m_decoder_time_valid_state = 0;
			if (m_decoder_time_valid_state < 4) {
				m_subtitle_sync_timer->start(50, true);
				m_prev_decoder_time = running_pts;
				break;
			}
		}

		if (frontpage.type == SubtitlePage::Pango)
			show_pts = frontpage.pango_page.m_show_pts;

		diff_ms = ( show_pts - running_pts ) / 90;
		eDebug("check subtitle: decoder: %lld, show_pts: %lld, diff: %lld ms", running_pts/90, show_pts/90, diff_ms);

		if ( diff_ms < -100 )
		{
			eDebug("subtitle too late... drop");
			m_subtitle_pages.pop_front();
		}
		else if ( diff_ms > 20 )
		{
			eDebug("start timer, %lldms", diff_ms);
			m_subtitle_sync_timer->start(diff_ms, true);
			break;
		}
		else // immediate show
		{
			if ( m_subtitle_widget )
			{
				eDebug("show!\n");
				if ( frontpage.type == SubtitlePage::Pango)
					m_subtitle_widget->setPage(frontpage.pango_page);
				m_subtitle_widget->show();
			}
			m_subtitle_pages.pop_front();
		}
	}

*/

}

RESULT eServiceMP3::enableSubtitles(iSubtitleUser *user, struct SubtitleTrack &track)
{

/*	openPLiPC

	ePyObject entry;
	int tuplesize = PyTuple_Size(tuple);
	int pid;

	if (!PyTuple_Check(tuple))
		goto error_out;
	if (tuplesize < 1)
		goto error_out;
	entry = PyTuple_GET_ITEM(tuple, 1);
	if (!PyInt_Check(entry))
		goto error_out;
	pid = PyInt_AsLong(entry);

	if (m_currentSubtitleStream != pid)
	{
		g_object_set (G_OBJECT (m_gst_playbin), "current-text", -1, NULL);
		m_subtitle_pages.clear();
		m_prev_decoder_time = -1;
		m_decoder_time_valid_state = 0;
		m_currentSubtitleStream = pid;
		m_cachedSubtitleStream = m_currentSubtitleStream;
		g_object_set (G_OBJECT (m_gst_playbin), "current-text", m_currentSubtitleStream, NULL);

		m_subtitle_widget = 0;
		m_subtitle_widget = new eSubtitleWidget(parent);
		m_subtitle_widget->resize(parent->size()); // full size //

		eDebug ("eServiceMP3::switched to subtitle stream %i", m_currentSubtitleStream);

#ifdef GSTREAMER_SUBTITLE_SYNC_MODE_BUG
		//
		// when we're running the subsink in sync=false mode, 
		// we have to force a seek, before the new subtitle stream will start
		//
		seekRelative(-1, 90000);
#endif
	}

*/

	return 0;
	
/*	openPLiPC

error_out:
	eDebug("eServiceMP3::enableSubtitles needs a tuple as 2nd argument!\n"
		"for gst subtitles (2, subtitle_stream_count, subtitle_type)");
	return -1;

*/

}

RESULT eServiceMP3::disableSubtitles()
{

/*	openPLiPC

	eDebug("eServiceMP3::disableSubtitles");
	m_currentSubtitleStream = -1;
	m_cachedSubtitleStream = m_currentSubtitleStream;
	g_object_set (G_OBJECT (m_gst_playbin), "current-text", m_currentSubtitleStream, NULL);
	m_subtitle_pages.clear();
	m_prev_decoder_time = -1;
	m_decoder_time_valid_state = 0;
	delete m_subtitle_widget;
	m_subtitle_widget = 0;

*/

	return 0;
}

RESULT eServiceMP3::getCachedSubtitle(struct SubtitleTrack &track)
{
// 	eDebug("eServiceMP3::getCachedSubtitle");
	return -1;
}

RESULT eServiceMP3::getSubtitleList(std::vector<struct SubtitleTrack> &subtitlelist)
{
// 	eDebug("eServiceMP3::getSubtitleList");
	int stream_idx = 0;
	eDebug("eServiceMP3::getSubtitleList finished");
	return 0;
}

RESULT eServiceMP3::streamed(ePtr<iStreamedService> &ptr)
{
	ptr = this;
	return 0;
}

PyObject *eServiceMP3::getBufferCharge()
{
	ePyObject tuple = PyTuple_New(5);
	PyTuple_SET_ITEM(tuple, 0, PyInt_FromLong(0));
	PyTuple_SET_ITEM(tuple, 1, PyInt_FromLong(0));
	PyTuple_SET_ITEM(tuple, 2, PyInt_FromLong(0));
	PyTuple_SET_ITEM(tuple, 3, PyInt_FromLong(0));
	PyTuple_SET_ITEM(tuple, 4, PyInt_FromLong(0));
	return tuple;
}

int eServiceMP3::setBufferSize(int size)
{
	m_buffer_size = size;
	return 0;
}

int eServiceMP3::getAC3Delay()
{
	return ac3_delay;
}

int eServiceMP3::getPCMDelay()
{
	return pcm_delay;
}

void eServiceMP3::setAC3Delay(int delay)
{

/*	openPLiPC

	ac3_delay = delay;
	if (!m_gst_playbin || m_state != stRunning)
		return;
	else
	{
		int config_delay_int = delay;

		//
		// NOTE: We only look for dvbmediasinks. 
		// If either the video or audio sink is of a different type,
		// we have no chance to get them synced anyway.
		//
		if (videoSink)
		{
			std::string config_delay;
			if(ePythonConfigQuery::getConfigValue("config.av.generalAC3delay", config_delay) == 0)
				config_delay_int += atoi(config_delay.c_str());
		}
		else
		{
			eDebug("dont apply ac3 delay when no video is running!");
			config_delay_int = 0;
		}

		if (audioSink)
		{
			eTSMPEGDecoder::setHwAC3Delay(config_delay_int);
		}
	}

*/

}

void eServiceMP3::setPCMDelay(int delay)
{

/*	openPLiPC

	pcm_delay = delay;
	if (!m_gst_playbin || m_state != stRunning)
		return;
	else
	{
		int config_delay_int = delay;

		// 
		// NOTE: We only look for dvbmediasinks. 
		// If either the video or audio sink is of a different type,
		// we have no chance to get them synced anyway.
		//
		if (videoSink)
		{
			std::string config_delay;
			if(ePythonConfigQuery::getConfigValue("config.av.generalPCMdelay", config_delay) == 0)
				config_delay_int += atoi(config_delay.c_str());
		}
		else
		{
			eDebug("dont apply pcm delay when no video is running!");
			config_delay_int = 0;
		}

		if (audioSink)
		{
			eTSMPEGDecoder::setHwPCMDelay(config_delay_int);
		}
	}

*/

}

