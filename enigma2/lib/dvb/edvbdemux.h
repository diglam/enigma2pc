#ifndef __dvb_edvbdemux_h
#define __dvb_edvbdemux_h

#include <lib/dvb/idvb.h>
#include <lib/dvb/idemux.h>
#include <lib/dvb/decsa.h>

class eDVBDemux: public iDVBDemux
{
	DECLARE_REF(eDVBDemux);
public:
	enum {
		evtFlush
	};
	eDVBDemux(int adapter, int demux);
	virtual ~eDVBDemux();

	RESULT setSourceFrontend(int fenum);
	int getSource() { return source; }
	RESULT setSourcePVR(int pvrnum);

	RESULT createSectionReader(eMainloop *context, ePtr<iDVBSectionReader> &reader);
	RESULT createPESReader(eMainloop *context, ePtr<iDVBPESReader> &reader);
	RESULT createTSRecorder(ePtr<iDVBTSRecorder> &recorder, int packetsize = 188, bool streaming=false);
	RESULT getMPEGDecoder(ePtr<iTSMPEGDecoder> &reader, int index);
	RESULT getSTC(pts_t &pts, int num);
	RESULT getCADemuxID(uint8_t &id) { id = demux; return 0; }
	RESULT getCAAdapterID(uint8_t &id) { id = adapter; return 0; }
	RESULT flush();
	RESULT connectEvent(const Slot1<void,int> &event, ePtr<eConnection> &conn);
	int openDVR(int flags);

	int getRefCount() { return ref; }

	RESULT setCaDescr(ca_descr_t *ca_descr, bool initial);
	RESULT setCaPid(ca_pid_t *ca_pid);
	bool decrypt(uint8_t *data, int len, int &packetsCount);
private:
	int adapter, demux, source;
	cDeCSA *decsa;

	int m_dvr_busy;
	friend class eDVBSectionReader;
	friend class eDVBPESReader;
	friend class eDVBAudio;
	friend class eDVBVideo;
	friend class eDVBPCR;
	friend class eDVBTText;
	friend class eDVBTSRecorder;
	friend class eDVBCAService;
	friend class eTSMPEGDecoder;
	Signal1<void, int> m_event;

	int openDemux(void);
};

#endif
