#!/usr/bin/env python3
"""Analyze RC400 command/reply/status transitions from rc400_decoder.py packet CSV.

Standard library only. Frames are validated from the `hex` column; any derived
columns in the input are ignored. Times are relative to each recording.

Example:
  uv run python tools/analysis/rc400_transition_report.py rc400_packets.csv \
      --csv-out transitions.csv --output transitions.md
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

# Command byte, response byte, status broadcast offset (None = no broadcast field).
COMMANDS = {
    0x09: ("cold_climate", 0x89, 15),
    0x0A: ("flame", 0x8A, 14),
    0x10: ("fan", 0x90, 16),
    0x22: ("timer", 0xA2, 22),
    0x25: ("thermostat", 0xA5, 13),
    0x26: ("room_temperature", 0xA6, None),
}
FIELDS = ["recording", "family", "command_time_s", "requested_value", "unit",
          "previous_reported", "first_reply_time_s", "reply_delay_ms", "matching_replies",
          "first_status_time_s", "first_reported", "first_target_time_s",
          "last_status_time_s", "last_reported", "observed_status_changes",
          "hot_before", "hot_after", "flame_after", "fan_after", "timer_after",
          "thermostat_c_after", "cold_climate_after", "room_temperature_c",
          "outcome", "notes"]


def valid_frame(text):
    try:
        b = bytes.fromhex(text)
    except (TypeError, ValueError):
        return None
    if len(b) != 27 or b[:2] != b"\x2d\xd4" or b[26] != 0x2A:
        return None
    return b if b[25] == ((sum(b[:25]) - 1) & 0xFF) else None


def read_packets(path):
    groups = defaultdict(list)
    skipped = 0
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            b = valid_frame(row.get("hex"))
            try:
                t = float(row["time_s"])
            except (ValueError, TypeError, KeyError):
                t = None
            if b is None or t is None:
                skipped += 1
                continue
            groups[row.get("file") or path.name].append((t, b))
    for filename in groups:
        groups[filename].sort(key=lambda x: x[0])
        # Multiple symbol phases can detect the same frame at almost the same time.
        unique = []
        for t, b in groups[filename]:
            if unique and any(abs(t - prev_t) < 0.001 and b == prev_b
                              for prev_t, prev_b in unique[-4:]):
                continue
            unique.append((t, b))
        groups[filename] = unique
    return groups, skipped


def observed_value(family, b):
    if family == "timer":
        return b[22]
    return b[COMMAND_OFFSET[family]]


COMMAND_OFFSET = {name: offset for name, _, offset in COMMANDS.values() if offset is not None}


def target_match(family, reported, requested):
    # Timer status reports remaining minutes, so it may have counted down.
    if family == "timer":
        return reported == requested  # exact match only; don't infer success from countdown
    return reported == requested


def analyze(groups):
    results = []
    for filename, packets in sorted(groups.items()):
        for i, (t, b) in enumerate(packets):
            if b[11] not in COMMANDS or b[12] not in (0x05, 0x0A):
                continue
            family, reply_code, status_offset = COMMANDS[b[11]]
            requested = b[13]
            # A later command of the same family closes the observation window;
            # unrelated commands and status broadcasts remain in scope.
            end = next((j for j in range(i + 1, len(packets))
                        if packets[j][1][11] == b[11] and packets[j][1][12] == b[12]), len(packets))
            before = [p for p in packets[:i] if p[1][11] == 0x9A]
            after = [p for p in packets[i + 1:end] if p[1][11] == 0x9A]
            prior = before[-1][1] if before else None
            latest = after[-1][1] if after else None
            statuses = [(ts, sb[status_offset]) for ts, sb in after] if status_offset is not None else []
            replies = [(ts, rb) for ts, rb in packets[i + 1:end]
                       if rb[11] == reply_code and rb[12] == b[12] and rb[13] == requested
                       and rb[3:7] == b[7:11] and rb[7:11] == b[3:7]]
            # Address reversal is typical, but historical captures may not all
            # follow it; report non-matching replies as ambiguous, not confirmed.
            ambiguous = sum(1 for _, rb in packets[i + 1:end]
                            if rb[11] == reply_code and rb[12] == b[12] and rb[13] == requested) - len(replies)
            first_target = next(((ts, v) for ts, v in statuses if target_match(family, v, requested)), None)
            changes = []
            last = prior[status_offset] if prior is not None and status_offset is not None else None
            for ts, value in statuses:
                if value != last:
                    changes.append(f"{ts:.3f}s:{'?' if last is None else last}->{value}")
                    last = value
            if not replies:
                outcome = "no matching reply captured"
            elif status_offset is None:
                outcome = "reply captured; no broadcast status field"
            elif first_target:
                outcome = "reply and matching status captured"
            elif not statuses:
                outcome = "reply captured; no subsequent status"
            else:
                outcome = "reply captured; requested status not observed"
            notes = []
            if ambiguous:
                notes.append(f"{ambiguous} reply(s) matched type/value but not reversed addresses")
            if family == "timer":
                notes.append("timer status is remaining minutes and may decrease")
            if family == "room_temperature":
                notes.append("room temperature is reported by remote, not in status broadcast")
            if family == "fan":
                notes.append("fan status may reflect cooling behavior rather than selected setting")
            if not after:
                notes.append("no broadcast after command within observation window")
            result = dict.fromkeys(FIELDS, "")
            result.update(recording=filename, family=family, command_time_s=round(t, 6),
                          requested_value=requested,
                          unit="°C" if family in ("thermostat", "room_temperature") else "minutes" if family == "timer" else "level" if family in ("flame", "fan") else "boolean",
                          previous_reported=prior[status_offset] if prior is not None and status_offset is not None else "",
                          first_reply_time_s=round(replies[0][0], 6) if replies else "",
                          reply_delay_ms=round((replies[0][0] - t) * 1000, 2) if replies else "",
                          matching_replies=len(replies),
                          first_status_time_s=round(statuses[0][0], 6) if statuses else "",
                          first_reported=statuses[0][1] if statuses else "",
                          first_target_time_s=round(first_target[0], 6) if first_target else "",
                          last_status_time_s=round(statuses[-1][0], 6) if statuses else "",
                          last_reported=statuses[-1][1] if statuses else "",
                          observed_status_changes="; ".join(changes),
                          hot_before=prior[20] if prior else "", hot_after=latest[20] if latest else "",
                          flame_after=latest[14] if latest else "", fan_after=latest[16] if latest else "",
                          timer_after=latest[22] if latest else "",
                          thermostat_c_after=latest[13] if latest else "",
                          cold_climate_after=latest[15] if latest else "",
                          room_temperature_c=requested if family == "room_temperature" else "",
                          outcome=outcome, notes="; ".join(notes))
            results.append(result)
    return results


def markdown(rows, skipped, source):
    lines = ["# RC400 command transition report", "",
             f"Source: `{source.name}` · {len(rows)} recognized commands · {skipped} invalid/skipped packet rows.", "",
             "Frames use zero-based byte offsets. Reply matching requires command family, subtype, value, and reversed source/destination addresses.",
             "A reply indicates an RF response, not proof that the appliance mechanically reached the requested state.",
             "Broadcast observations end at the next command of the same family in each recording. Blank values mean not observed.", "",
             "| Recording | Family | Command (s) | Request | Reply (ms) | Previous → final reported | Outcome |",
             "|---|---|---:|---:|---:|---|---|"]
    for r in rows:
        def esc(x): return str(x).replace("|", "\\|")
        lines.append(f"| {esc(r['recording'])} | {r['family']} | {r['command_time_s']} | {r['requested_value']} {r['unit']} | {r['reply_delay_ms'] or '—'} | {r['previous_reported'] if r['previous_reported'] != '' else '?'} → {r['last_reported'] if r['last_reported'] != '' else '?'} | {r['outcome']} |")
    lines += ["", "## Command details", ""]
    for r in rows:
        lines += [f"### {r['recording']} — {r['family']} at {r['command_time_s']}s", "",
                  f"- Requested: {r['requested_value']} {r['unit']}; matching replies: {r['matching_replies']}; first reply delay: {r['reply_delay_ms'] if r['reply_delay_ms'] != '' else 'not captured'} ms",
                  f"- Status changes: {r['observed_status_changes'] or 'none observed'}",
                  f"- First target status: {str(r['first_target_time_s']) + 's' if r['first_target_time_s'] != '' else 'not observed'}",
                  f"- Last broadcast: flame={r['flame_after']}, fan={r['fan_after']}, timer={r['timer_after']}, thermostat°C={r['thermostat_c_after']}, cold_climate={r['cold_climate_after']}, HOT={r['hot_after']}",
                  f"- Assessment: {r['outcome']}", f"- Notes: {r['notes'] or 'none'}", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="Packet CSV from rc400_decoder.py (requires file,time_s,hex)")
    parser.add_argument("--csv-out", type=Path, default=Path("rc400_transitions.csv"))
    parser.add_argument("--output", type=Path, default=Path("rc400_transitions.md"))
    args = parser.parse_args()
    if args.input.resolve() in (args.csv_out.resolve(), args.output.resolve()):
        parser.error("Output must not overwrite input")
    groups, skipped = read_packets(args.input)
    rows = analyze(groups)
    with args.csv_out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    args.output.write_text(markdown(rows, skipped, args.input), encoding="utf-8")
    print(f"{len(rows)} recognized commands, {skipped} skipped rows; wrote {args.csv_out} and {args.output}")


if __name__ == "__main__":
    main()
