#!/usr/bin/env python3
"""Receive-only RC400 SDRangel IQ and packet CSV decoder.

Usage:
  python rc400_decoder.py 'capture.sdriq' --csv packets.csv --events events.csv --state states.csv
  python rc400_decoder.py --from-csv packets.csv --csv enriched.csv --events events.csv --state states.csv

RF input requires NumPy and SciPy; --from-csv uses the standard library only.
This tool does not transmit RF. SDRangel .sdriq files use a 32-byte header.
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import struct
from collections import defaultdict

# Imported on demand so CSV-only analysis has no third-party dependencies.
np = None
uniform_filter1d = None
binary_closing = None


def _require_rf_dependencies():
    global np, uniform_filter1d, binary_closing
    if np is not None:
        return
    try:
        import numpy
        from scipy.ndimage import uniform_filter1d as smooth, binary_closing as close
    except ImportError as exc:
        raise SystemExit("SDR decoding requires NumPy and SciPy: uv add numpy scipy") from exc
    np = numpy
    uniform_filter1d = smooth
    binary_closing = close


SYNC = bytes.fromhex('2d d4')
FRAME_BYTES = 27

def header(path):
    _require_rf_dependencies()
    with open(path,'rb') as f: h=f.read(32)
    if len(h)!=32: raise ValueError('Too short for SDRangel header')
    rate, center=struct.unpack_from('<IQ',h,0)
    bits=struct.unpack_from('<I',h,20)[0]
    if not (10000 <= rate <= 20000000 and 1000000 <= center <= 10000000000 and bits in (16,24)):
        raise ValueError(f'Unexpected SDRangel header: sample rate={rate}, center={center}, bits={bits}')
    dtype='<i2' if bits==16 else '<i4'
    count=(os.path.getsize(path)-32)//(2*np.dtype(dtype).itemsize)
    return rate,center,bits,np.memmap(path,mode='r',dtype=dtype,offset=32,shape=(count,2))

def iq_segment(raw, start, end, stride):
    a=np.asarray(raw[start:end:stride],dtype=np.float32)
    return a[:,0]+1j*a[:,1]

def bursts(raw, rate, stride, threshold_db=9):
    _require_rf_dependencies()
    """Adaptive 1 ms energy gate; preserves quiet space and burst edges."""
    n=len(raw); block=max(1,round(rate*.001)); step=block*8
    powers=[]
    for s in range(0,n,step):
        a=np.asarray(raw[s:min(n,s+step):stride],dtype=np.float64)
        powers.append(np.mean(a[:,0]**2+a[:,1]**2) if len(a) else 0)
    p=np.asarray(powers); positive=p[p>0]
    if not len(positive):return []
    floor=np.percentile(positive,25)
    # When receiver background is nonzero, robust dB threshold relative to noise floor.
    active=p>max(floor*10**(threshold_db/10),np.max(p)*1e-7)
    # Fill short dropouts, merge adjacent segments within 12 ms.
    gap=max(1,int(np.ceil(.012*rate/step)))
    active=binary_closing(active,structure=np.ones(gap),border_value=0)
    edges=np.diff(np.r_[False,active,False].astype(np.int8))
    starts=np.where(edges==1)[0]; ends=np.where(edges==-1)[0]
    result=[]
    for a,b in zip(starts,ends):
        st=max(0,int(a*step-.008*rate)); en=min(n,int(b*step+.008*rate))
        if en-st>=rate*.008:result.append((st,en))
    return result

def sync_bits():
    return np.unpackbits(np.frombuffer(SYNC,dtype=np.uint8))

def extract_frames(bits, quality, t0, sample_rate_decimated, polarity):
    pat=sync_bits(); frames=[]
    # Exact sync; checksum makes false positives exceedingly unlikely.
    matches=np.where(np.convolve(bits.astype(np.int16)*2-1,(pat[::-1].astype(np.int16)*2-1),'valid')==16)[0]
    for pos in matches:
        if pos+FRAME_BYTES*8>len(bits):continue
        dat=np.packbits(bits[pos:pos+FRAME_BYTES*8]).tobytes()
        if dat[-1]!=0x2a:continue
        if ((sum(dat[:25])-1)&255)!=dat[25]:continue
        frames.append((pos,dat,float(np.mean(quality[pos:pos+FRAME_BYTES*8])),polarity))
    return frames

def decode_burst(raw, st, en, rate, center, decimation=8, baud=25000):
    _require_rf_dependencies()
    # Decimate by integer factor; low-pass first to prevent aliasing.
    # FSK tones at +150/+250 kHz for 913.0 MHz center, so shift first.
    x=iq_segment(raw,st,en,1)
    if len(x)<1000:return []
    # Mix around +200 kHz so both tones fit safely into decimated baseband.
    # For 913.1 MHz captures the tone midpoint is +100 kHz instead.
    offset=913200000-center
    idx=np.arange(len(x),dtype=np.float64)
    x*=np.exp(-2j*np.pi*offset/rate*idx).astype(np.complex64)
    from scipy.signal import resample_poly
    x=resample_poly(x,1,decimation).astype(np.complex64)
    fs=rate/decimation
    spb=fs/baud
    if abs(spb-round(spb))>.01:raise ValueError('Sample rate / decimation / baud must give integral samples per bit')
    spb=int(round(spb))
    # Discriminator. Phase derivative represents instantaneous FSK frequency.
    d=np.angle(x[1:]*np.conj(x[:-1]))
    d=uniform_filter1d(d,size=max(3,spb//3))
    # Threshold from robust percentiles; center at the midpoint of FSK tones.
    lo,hi=np.percentile(d,[15,85]); threshold=(lo+hi)/2
    soft=(d-threshold)/(max((hi-lo)/2,1e-5))
    out=[]; seen=set()
    # Try all symbol phases and both polarities at the configured symbol rate.
    for period in (spb,):
        for phase in range(period):
            nbits=(len(soft)-phase)//period
            if nbits<FRAME_BYTES*8:continue
            shaped=soft[phase:phase+nbits*period].reshape(-1,period)
            # Integrate central 60% of each symbol, rejecting transitions.
            margin=max(1,period//5)
            scores=shaped[:,margin:period-margin].mean(axis=1)
            for polarity in (1,-1):
                bits=(scores*polarity>0).astype(np.uint8)
                for pos,dat,quality,pol in extract_frames(bits,np.abs(scores),st/rate+phase/fs,fs,polarity):
                    time=st/rate+(phase+pos*period)/fs
                    key=(round(time,4),dat)
                    if key in seen:continue
                    seen.add(key)
                    out.append(dict(time_s=round(time,6),hex=dat.hex(' ').upper(),byte13=f'{dat[13]:02X}',byte16=f'{dat[16]:02X}',byte20=f'{dat[20]:02X}',quality=round(quality,3),polarity=pol))
    # A frame can be detected at multiple adjacent phases: consolidate by time.
    out.sort(key=lambda v:(v['time_s'],-v['quality']))
    unique=[]
    for p in out:
        if any(abs(p['time_s']-q['time_s'])<.001 and p['hex']==q['hex'] for q in unique):continue
        unique.append(p)
    return unique


FAMILIES = {0x09:('cold_climate','command'),0x89:('cold_climate','reply'),0x0A:('flame','command'),0x8A:('flame','reply'),
            0x10:('fan','command'),0x90:('fan','reply'),
            0x22:('timer','command'),0xA2:('timer','reply'),
            0x25:('thermostat','command'),0xA5:('thermostat','reply'),
            0x9A:('status','broadcast'),0x26:('room_temperature','command'),0xA6:('room_temperature','reply')}
PACKET_FIELDS=['file','time_s','hex','byte13','byte16','byte20','quality','polarity','family','direction','requested_value','reported_flame','reported_fan','reported_timer_minutes','reported_hot','requested_thermostat_c','reported_thermostat_c','thermostat_enabled','thermostat_setpoint_f','remote_temperature_c','remote_temperature_f','requested_cold_climate','reported_cold_climate']
EVENT_FIELDS=['file','time_s','family','direction','requested_value','flame_status','fan_status','timer_minutes_status','hot_status','requested_thermostat_c','thermostat_c_status','thermostat_enabled','thermostat_setpoint_f','remote_temperature_c','remote_temperature_f','requested_cold_climate','cold_climate_status','details']
STATE_FIELDS=['file','time_s','flame_level','fan_level','timer_remaining_minutes','hot_flag','last_flame_request','last_fan_request','last_timer_request','last_thermostat_request_c','thermostat_setpoint_c','thermostat_setpoint_f','thermostat_enabled','remote_temperature_c','remote_temperature_f','last_cold_climate_request','cold_climate_enabled','event']

def frame(row):
    try:
        data=bytes.fromhex(row['hex'])
        if len(data)!=27 or data[:2]!=b'\x2d\xd4' or data[-1]!=0x2a or data[25]!=((sum(data[:25])-1)&255):return None
        return data
    except (ValueError,KeyError,TypeError):return None

def thermostat_f(c):
    # The remote's exact Fahrenheit display rounding is not established.
    return round(c * 9 / 5 + 32, 1) if c else ''

def temperature_f(c):
    return round(c * 9 / 5 + 32, 1)

def enrich(row):
    data=frame(row)
    if data is None:return None
    fam,direction=FAMILIES.get(data[11],('other','unknown'))
    out={k:row.get(k,'') for k in PACKET_FIELDS}
    out.update(family=fam,direction=direction,requested_value=(data[13] if direction in ('command','reply') else ''),
               reported_flame=(data[14] if direction=='broadcast' else ''),
               reported_fan=(data[16] if direction=='broadcast' else ''),
               reported_timer_minutes=(data[22] if direction=='broadcast' else ''),
               reported_hot=(data[20] if direction=='broadcast' else ''),
               requested_thermostat_c=(data[13] if fam=='thermostat' and direction in ('command','reply') else ''),
               reported_thermostat_c=(data[13] if direction=='broadcast' else ''),
               thermostat_enabled=(int(data[13]!=0) if direction=='broadcast' else ''),
               thermostat_setpoint_f=(thermostat_f(data[13]) if direction=='broadcast' else ''),
               remote_temperature_c=(data[13] if fam=='room_temperature' and direction=='command' else ''),
               remote_temperature_f=(temperature_f(data[13]) if fam=='room_temperature' and direction=='command' else ''),
               requested_cold_climate=(data[13] if fam=='cold_climate' and direction in ('command','reply') else ''),
               reported_cold_climate=(data[15] if direction=='broadcast' else ''))
    return out

def read_existing(path):
    with open(path,newline='',encoding='utf-8-sig') as f:return list(csv.DictReader(f))

def decode_files(paths, threshold_db, max_burst_seconds):
    _require_rf_dependencies()
    rows=[]
    for pattern in paths:
        matches = sorted(glob.glob(pattern))
        if not matches:
            raise FileNotFoundError(f"No recordings match: {pattern}")
        for path in matches:
            rate,center,bits,raw=header(path)
            segments=bursts(raw,rate,stride=16,threshold_db=threshold_db)
            print(f'{os.path.basename(path)}: {len(segments)} candidate bursts',flush=True)
            for st,en in segments:
                maxlen=max(1,int(max_burst_seconds*rate))
                for start in range(st,en,maxlen):
                    stop=min(en,start+maxlen+int(.05*rate))
                    for p in decode_burst(raw,start,stop,rate,center):
                        p['file']=os.path.basename(path)
                        rows.append(p)
    return rows

def write_csv(path,fields,rows):
    with open(path,'w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)

def build_timelines(packets):
    groups=defaultdict(list)
    for p in packets:groups[p['file']].append(p)
    events=[];states=[]
    for filename, ps in groups.items():
        ps.sort(key=lambda p:float(p['time_s']))
        # Keep all valid packets in the packet CSV, but ignore duplicate detections in state updates.
        seen=set(); state={'flame_level':'','fan_level':'','timer_remaining_minutes':'','hot_flag':'',
                          'last_flame_request':'','last_fan_request':'','last_timer_request':'',
                          'last_thermostat_request_c':'','thermostat_setpoint_c':'',
                          'thermostat_setpoint_f':'','thermostat_enabled':'',
                          'remote_temperature_c':'','remote_temperature_f':'',
                          'last_cold_climate_request':'','cold_climate_enabled':''}
        for p in ps:
            t=float(p['time_s']); data=frame(p)
            key=(round(t,3),p['hex'])
            if key in seen:continue
            seen.add(key)
            family=p['family']; direction=p['direction']; val=p['requested_value']
            changed=[]
            if direction=='broadcast':
                for field,idx in [('flame_level',14),('fan_level',16),('timer_remaining_minutes',22),('hot_flag',20),('thermostat_setpoint_c',13),('cold_climate_enabled',15)]:
                    new=data[idx]
                    if state[field]!=new:
                        changed.append(f'{field}: {state[field] if state[field] != "" else "?"} -> {new}')
                        state[field]=new
                if state['thermostat_setpoint_c'] != '':
                    state['thermostat_enabled']=int(state['thermostat_setpoint_c'] != 0)
                    state['thermostat_setpoint_f']=thermostat_f(state['thermostat_setpoint_c'])
            elif direction=='command' and family=='room_temperature':
                if state['remote_temperature_c'] != val:
                    changed.append(f'remote_temperature_c: {state["remote_temperature_c"] if state["remote_temperature_c"] != "" else "?"} -> {val}')
                state['remote_temperature_c']=val
                state['remote_temperature_f']=temperature_f(val)
            elif direction=='command' and family in ('fan','flame','timer','thermostat','cold_climate'):
                state['last_thermostat_request_c' if family=='thermostat' else 'last_cold_climate_request' if family=='cold_climate' else 'last_'+family+'_request']=val
            # All command/reply frames are events; broadcasts only on a state change.
            if direction in ('command','reply') or changed:
                events.append(dict(file=filename,time_s=t,family=family,direction=direction,
                    requested_value=val,flame_status=state['flame_level'],fan_status=state['fan_level'],
                    timer_minutes_status=state['timer_remaining_minutes'],hot_status=state['hot_flag'],requested_thermostat_c=(val if family=='thermostat' else ''),
                    thermostat_c_status=state['thermostat_setpoint_c'],thermostat_enabled=state['thermostat_enabled'],
                    thermostat_setpoint_f=state['thermostat_setpoint_f'],
                    remote_temperature_c=state['remote_temperature_c'],remote_temperature_f=state['remote_temperature_f'],
                    requested_cold_climate=(val if family=='cold_climate' else ''),cold_climate_status=state['cold_climate_enabled'],
                    details='; '.join(changed) if changed else ('requested/echoed value' if family in ('fan','flame','timer','thermostat','cold_climate') else 'temperature report' if family=='room_temperature' and direction=='command' else 'auxiliary/unknown')))
            if direction=='broadcast' or (direction=='command' and family in ('fan','flame','timer','thermostat','room_temperature','cold_climate')):
                states.append(dict(file=filename,time_s=t,**state,event=('broadcast: '+', '.join(changed)) if direction=='broadcast' else family+' request '+str(val)))
    return events,states


def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('files',nargs='*',help='SDRangel .sdriq files or glob patterns')
    ap.add_argument('--from-csv',help='Process an existing packets.csv without SDR re-decoding')
    ap.add_argument('--csv',default='rc400_packets.csv',help='Enriched decoded packet CSV')
    ap.add_argument('--events',default='rc400_events.csv',help='Commands, replies and state changes')
    ap.add_argument('--state',default='rc400_states.csv',help='Status timeline plus last requested values')
    ap.add_argument('--threshold-db',type=float,default=9)
    ap.add_argument('--max-burst-seconds',type=float,default=1.5)
    args=ap.parse_args()
    if not args.from_csv and not args.files:ap.error('Supply .sdriq files or --from-csv packets.csv')
    if args.from_csv and args.files:ap.error('Choose either .sdriq files or --from-csv, not both')
    if args.max_burst_seconds <= 0:ap.error('--max-burst-seconds must be positive')
    if args.from_csv and os.path.abspath(args.from_csv)==os.path.abspath(args.csv):
        ap.error('--csv must not overwrite the --from-csv input')
    source=read_existing(args.from_csv) if args.from_csv else decode_files(args.files,args.threshold_db,args.max_burst_seconds)
    packets=[p for row in source if (p:=enrich(row)) is not None]
    packets.sort(key=lambda p:(p['file'],float(p['time_s'])))
    events,states=build_timelines(packets)
    write_csv(args.csv,PACKET_FIELDS,packets)
    write_csv(args.events,EVENT_FIELDS,events)
    write_csv(args.state,STATE_FIELDS,states)
    print(f'Validated {len(packets)} packets; {len(events)} events; {len(states)} state timeline rows')
    print(f'Wrote {args.csv}, {args.events}, {args.state}')

if __name__=='__main__':main()
