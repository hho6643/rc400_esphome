#!/usr/bin/env python3
"""Analyze checksum-valid RC400 packet CSV exported by rc400_decoder.py.
Usage: python3 rc400_byte_diff.py rc400_fan_packets.csv --output rc400_byte_report.md
"""
import argparse, csv, collections, pathlib

def classify(b):
    if b[3:5] == b'\x00\x00': return 'remote command'
    if b[7:11] == b'\xff'*4: return 'status broadcast'
    return 'directed reply'

def fmt(b): return ' '.join(f'{x:02X}' for x in b)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('csv_file',type=pathlib.Path)
    p.add_argument('--output',type=pathlib.Path,default=pathlib.Path('rc400_byte_report.md'))
    args=p.parse_args()
    rows=[]
    with args.csv_file.open(newline='') as f:
        for r in csv.DictReader(f):
            try:
                b=bytes.fromhex(r['hex'])
                if len(b)!=27 or b[:2]!=bytes.fromhex('2D D4') or b[-1]!=0x2a or b[25]!=((sum(b[:25])-1)&255):
                    continue
                rows.append({'file':r['file'],'time':float(r['time_s']),'bytes':b,'kind':classify(b)})
            except (KeyError,ValueError): continue
    if not rows: raise SystemExit('No valid 27-byte frames in input CSV')
    out=['# RC400 automated byte-difference report','',f'Validated frames: **{len(rows)}**; recordings: **{len(set(r["file"] for r in rows))}**.','',
         'All byte positions are **zero-based**. The checksum at byte 25 necessarily changes when payload bytes change.','',
         '## Packet families','', '| Family | Frames | Distinct frames | Variable byte positions |','|---|---:|---:|---|']
    for kind in ('remote command','directed reply','status broadcast'):
        rs=[r for r in rows if r['kind']==kind]
        if not rs: continue
        unique=sorted(set(r['bytes'] for r in rs))
        variable=[i for i in range(27) if len({b[i] for b in unique})>1]
        out.append(f'| {kind} | {len(rs)} | {len(unique)} | {", ".join(map(str,variable)) or "none"} |')
    out+=['','## Per-recording packet timeline','',
          '| Recording | Time (s) | Family | Byte 11 | Byte 13 | Byte 16 | Byte 20 |','|---|---:|---|---|---|---|---|']
    for r in sorted(rows,key=lambda r:(r['file'],r['time'])):
        b=r['bytes']; name=pathlib.Path(r['file']).name.replace('|','\\|')
        out.append(f'| {name} | {r["time"]:.3f} | {r["kind"]} | {b[11]:02X} | {b[13]:02X} | {b[16]:02X} | {b[20]:02X} |')
    out+=['','## Unique packets within each family','',
          'Repeated identical frames are consolidated; differences are compared only within each family.','']
    for kind in ('remote command','directed reply','status broadcast'):
        rs=[r for r in rows if r['kind']==kind]
        if not rs: continue
        counts=collections.Counter(r['bytes'] for r in rs)
        base=counts.most_common(1)[0][0]
        out+= [f'### {kind}','',f'Most frequent reference frame ({counts[base]} occurrences):','',f'`{fmt(base)}`','',
               '| Count | Changed byte offsets and values relative to reference | Complete frame |','|---:|---|---|']
        for b,n in counts.most_common():
            delta=', '.join(f'{i}: {base[i]:02X}→{b[i]:02X}' for i in range(27) if b[i]!=base[i]) or 'identical'
            out.append(f'| {n} | {delta} | `{fmt(b)}` |')
        out.append('')
    out+=['## Interpretation notes','',
          '- A changed byte is an observation, not proof of a specific semantic meaning.',
          '- Byte 13 must be interpreted with the message family and other command fields (for example byte 11).',
          '- Broadcast byte 16 may change over time independently of the requested fan level; compare immediate and later status packets.',
          '- A directed reply may echo a command while reporting the previous state in other fields.',
          '- A checksum-valid packet is strong evidence of a correct decode, but does not independently establish transmitter identity.','']
    args.output.write_text('\n'.join(out),encoding='utf-8')
    print(f'Wrote {args.output} ({len(rows)} validated frames)')
if __name__=='__main__': main()
