#!/usr/bin/env python3
"""Analyze RC400 decoder CSV: one row per fan-control command (receive only).

python3 rc400_transition_per_command.py packets.csv --output fan_transitions.md --csv-out fan_transitions.csv
"""
import argparse
import csv
from collections import defaultdict
from pathlib import Path


def valid(b):
    return len(b) == 27 and b[:2] == b'\x2d\xd4' and b[26] == 0x2a and b[25] == ((sum(b[:25])-1) & 255)


def category(b):
    if b[3:5] == b'\x00\x00':
        return 'fan command' if (b[11], b[12]) == (0x10, 0x05) else 'other command'
    if b[7:11] == b'\xff'*4:
        return 'fan status' if (b[11], b[12]) == (0x9a, 0x0e) else 'other broadcast'
    return 'fan reply' if (b[11], b[12]) == (0x90, 0x05) else 'other reply'


def hx(v):
    return f'{v:02X}' if v is not None else 'not captured'


def fmt(t):
    return f'{t:.3f}' if t is not None else ''


def changes(states):
    out = []
    for r in states:
        v = r['b'][16]
        if not out or v != out[-1][1]:
            out.append((r['t'], v))
    return out


def analyze(name, rr):
    cmds = [r for r in rr if r['kind'] == 'fan command']
    statuses = [r for r in rr if r['kind'] == 'fan status']
    replies = [r for r in rr if r['kind'] == 'fan reply']
    others = [r for r in rr if r['kind'] == 'other command']
    results = []
    for idx, c in enumerate(cmds):
        t, target = c['t'], c['b'][13]
        end = cmds[idx+1]['t'] if idx+1 < len(cmds) else float('inf')
        pre = next((s for s in reversed(statuses) if s['t'] < t), None)
        post = [s for s in statuses if t < s['t'] < end]
        matching = [r for r in replies if t <= r['t'] < end and r['b'][13] == target]
        first_reply = matching[0] if matching else None
        seq = changes(post)
        first_target = next((s for s in post if s['b'][16] == target), None)
        # Boost only when target is below level 4 and 04 is seen AFTER the command.
        boost = next((s for s in post if s['b'][16] == 4), None) if target < 4 else None
        settled = None
        if boost is not None:
            settled = next((s for s in post if s['t'] > boost['t'] and s['b'][16] == target), None)
        notes = []
        if pre is None: notes.append('no preceding status')
        if first_reply is None: notes.append('no matching reply decoded')
        if not post: notes.append('no subsequent status before next fan command/end')
        if post and first_target is None: notes.append('target not observed in status window')
        if boost: notes.append('level-4 status observed after command')
        if boost and settled: notes.append('returned to target after level 4')
        if boost and not settled: notes.append('return to target not captured')
        other_count = sum(t < r['t'] < end for r in others)
        if other_count: notes.append(f'{other_count} other command(s) in window')
        if not notes: notes.append('matching reply and target status observed')
        results.append({
            'recording': name, 'command_number': idx+1,
            'command_time_s': fmt(t), 'previous_status_hex': hx(pre['b'][16]) if pre else '',
            'target_hex': hx(target), 'target_decimal': target,
            'first_reply_time_s': fmt(first_reply['t']) if first_reply else '',
            'reply_delay_ms': f'{(first_reply["t"]-t)*1000:.2f}' if first_reply else '',
            'reply_previous_state_hex': hx(first_reply['b'][16]) if first_reply else '',
            'matching_reply_count': len(matching),
            'first_status_time_s': fmt(post[0]['t']) if post else '',
            'first_status_hex': hx(post[0]['b'][16]) if post else '',
            'first_target_status_time_s': fmt(first_target['t']) if first_target else '',
            'first_target_delay_ms': f'{(first_target["t"]-t)*1000:.2f}' if first_target else '',
            'last_status_hex': hx(post[-1]['b'][16]) if post else '',
            'boost_first_time_s': fmt(boost['t']) if boost else '',
            'boost_return_time_s': fmt(settled['t']) if settled else '',
            'boost_observed_interval_s': f'{settled["t"]-boost["t"]:.3f}' if settled else '',
            'status_changes': ' → '.join(f'{v:02X}@{st:.3f}s' for st,v in seq),
            'status_packet_count': len(post), 'other_command_count': other_count,
            'notes': '; '.join(notes),
        })
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input', type=Path)
    ap.add_argument('--output', type=Path, default=Path('fan_transitions.md'))
    ap.add_argument('--csv-out', type=Path, default=Path('fan_transitions.csv'))
    a = ap.parse_args()
    groups = defaultdict(list)
    skipped = 0
    with a.input.open(newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            try:
                b = bytes.fromhex(row['hex'])
                if not valid(b):
                    skipped += 1
                    continue
                groups[row['file']].append({'t':float(row['time_s']), 'b':b, 'kind':category(b)})
            except (KeyError, ValueError, TypeError):
                skipped += 1
    results = []
    for name, rr in sorted(groups.items()):
        rr.sort(key=lambda r:r['t'])
        results.extend(analyze(name, rr))
    if not results:
        raise SystemExit('No valid fan commands found (byte11=10, byte12=05).')
    with a.csv_out.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    md = [
        '# RC400 fan transitions — one row per fan command', '',
        f'Input: `{a.input.name}` · {sum(map(len,groups.values()))} validated packets · {len(results)} fan commands · {skipped} invalid/skipped rows.', '',
        'All byte positions are zero-based. The analysis window for each command ends at the **next fan command** in the same recording (or at the recording end).',
        'Other command types do not split a window; they are counted and flagged. Broadcast values are sampled reports, not direct measurements of motor RPM.', '',
        '## Command-by-command summary', '',
        '| Recording | Time (s) | Prior status | Target | First matching reply (ms) | First target status (s) | Status changes after command | Notes |',
        '|---|---:|---:|---:|---:|---:|---|---|',
    ]
    for r in results:
        name = Path(r['recording']).name.replace('|','\\|')
        notes = r['notes'].replace('|','\\|')
        md.append(f"| {name} | {r['command_time_s']} | {r['previous_status_hex'] or '—'} | {r['target_hex']} | {r['reply_delay_ms'] or '—'} | {r['first_target_status_time_s'] or '—'} | {r['status_changes'] or 'none'} | {notes} |")
    md += ['', '## Per-command details', '']
    for r in results:
        md += [f"### {Path(r['recording']).name} — command {r['command_number']} at {r['command_time_s']}s (target {r['target_hex']})", '',
               f"- Previous broadcast byte 16: **{r['previous_status_hex'] or 'not captured'}**; first reply delay: **{r['reply_delay_ms']+' ms' if r['reply_delay_ms'] else 'not captured'}**; matching replies: **{r['matching_reply_count']}**.",
               f"- Reply byte 16: **{r['reply_previous_state_hex'] or 'not captured'}**; first broadcast byte 16: **{r['first_status_hex'] or 'not captured'}**; last broadcast byte 16: **{r['last_status_hex'] or 'not captured'}**.",
               f"- Observed broadcast transitions: **{r['status_changes'] or 'none captured'}**.",
               f"- First broadcast matching target: **{r['first_target_status_time_s']+'s' if r['first_target_status_time_s'] else 'not captured'}**."]
        if r['boost_first_time_s']:
            md.append(f"- Level-4 boost observed at **{r['boost_first_time_s']}s**; return to target: **{r['boost_return_time_s']+'s' if r['boost_return_time_s'] else 'not captured'}**. The interval between status reports is not the exact motor boost duration.")
        md += [f"- Notes: {r['notes']}.", '']
    md += ['## Interpretation cautions', '',
           '- A matching reply is defined as byte 11=`90`, byte 12=`05`, byte 13 matching the command target, occurring before the next fan command.',
           '- Byte 16 in the reply frequently contains the *previous* fan state, not the newly requested target.',
           '- Byte 16 in broadcast `9A 0E` is treated as the reported fan level based on controlled observations; physical speed transitions may occur between broadcasts.',
           '- The analysis does not assume a missing status was zero or that a reply proves mechanical actuation.', '']
    a.output.write_text('\n'.join(md), encoding='utf-8')
    print(f'{len(results)} fan commands -> {a.csv_out} and {a.output} ({skipped} skipped rows)')

if __name__ == '__main__':
    main()
