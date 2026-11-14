#!/usr/bin/env python3
"""RC400 receive-only RF decoder with fan, flame, timer, thermostat, room temperature and Cold Climate mode tracking.

Requires numpy and scipy for .sdriq decoding. CSV-only mode needs standard Python.
Examples:
  python3 rc400_decoder_unified.py 'capture.sdriq' --csv packets.csv --events events.csv --state states.csv
  python3 rc400_decoder_unified.py --from-csv packets.csv --events events.csv --state states.csv
"""
import argparse, csv, os, sys
from collections import defaultdict

# Reuse the validated IQ demodulator without modifying its FSK/framing logic.
from rc400_decoder_old import header, bursts, decode_burst

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
    with open(path,newline='') as f:return list(csv.DictReader(f))

def decode_files(paths, threshold_db, max_burst_seconds):
    import glob
    rows=[]
    for pattern in paths:
        for path in sorted(glob.glob(pattern)):
            rate,center,bits,raw=header(path)
            segments=bursts(raw,rate,stride=16,threshold_db=threshold_db)
            print(f'{os.path.basename(path)}: {len(segments)} candidate bursts',flush=True)
            for st,en in segments:
                maxlen=int(max_burst_seconds*rate)
                for start in range(st,en,maxlen):
                    stop=min(en,start+maxlen+int(.05*rate))
                    for p in decode_burst(raw,start,stop,rate,center):
                        p['file']=os.path.basename(path)
                        rows.append(p)
    return rows

def write_csv(path,fields,rows):
    with open(path,'w',newline='') as f:
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
