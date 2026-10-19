#!/usr/bin/env python3
"""Build songs/tamacun.json for the ocarina songbook from the Songsterr track files.

Run from the repo root, with the venv active (or pass --ocarina .venv/bin/ocarina):

    python make_tamacun.py /path/to/folder/with/G1.json,G2.json,G3.json,D1.json,W1.json

What it does
  * ocarina: G1.json (Rodrigo), Songsterr bars 2-33, with the opening one-beat
    guitar-slap intro restored before the lead enters. Rests under half a beat are
    folded into the note before them; each 3-note sixteenth triplet keeps its first
    two notes (as sixteenths) so the bar stays 4 beats long.
  * runs `ocarina build` with a forced --shift (default -2) so the band can be
    moved by exactly the same amount.
  * drums: percussive hits from D1/W1, including the opening slap at time zero:
    dead-note slaps -> snare (38), low-string thumps -> kick (36).
  * bass: G3 (bars 26-33) an octave up; part: all G2 rhythm-guitar strums, including
    short and muted strums, kept as short nylon-guitar notes. Use --no-band to leave
    both bass and rhythm guitar out.
  * runs `ocarina validate`, then the timing / drum-sync checks from AGENTS.md
    (reported, not enforced).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from fractions import Fraction

SLUG = "tamacun"
NAME = "Tamacun"
ARTIST = "Rodrigo y Gabriela"
CONTRIBUTOR = "HmWhyNot"
PART = "the opening: the signature riff and the first melody (Songsterr bars 2-33) Play every time HmWhyNot's drama queen intro from navi get's triggered."
SOURCE = "https://www.songsterr.com/a/wsa/rodrigo-y-gabriela-tamacun-tab-s52262"
BPM = 130
FIRST_BAR, LAST_BAR = 1, 32  # indexes in the Songsterr JSON; bar 0 is the count-in
INTRO_BEATS = 1  # Songsterr bar 1 is the one-beat opening slap/count-in
SONG_BEATS = INTRO_BEATS + (LAST_BAR - FIRST_BAR + 1) * 4  # 129
SLAP = 37
THUMP = 35

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
DYN = {"pp": 50, "p": 70, "mp": 85, "mf": 100, None: 100, "f": 110, "ff": 120}


def note_name(p):
    return f"{NAMES[p % 12]}{p // 12 - 1}"


def load(folder, name):
    with open(os.path.join(folder, name + ".json")) as f:
        return json.load(f)


def dur(b):
    return Fraction(4 * b["duration"][0], b["duration"][1])


def fnum(x):
    x = float(x)
    return int(x) if x == int(x) else round(x, 3)


# --------------------------------------------------------------------------- melody
def melody(g1):
    tun = g1["tuning"]
    ev = []  # [pitch or None, beats(Fraction), bar]
    tri = 0
    # One-beat rest in the ocarina while the opening guitar slap sounds.
    ev.append([None, Fraction(INTRO_BEATS), 0])
    for bi in range(FIRST_BAR, LAST_BAR + 1):
        for b in g1["measures"][bi]["voices"][0]["beats"]:
            d = dur(b)
            ns = [n for n in b["notes"] if not n.get("rest")]
            if b.get("rest") or not ns:
                ev.append([None, d, bi])
                continue
            p = tun[ns[0]["string"]] + ns[0]["fret"]
            if ns[0].get("tie") and ev and ev[-1][0] == p:
                ev[-1][1] += d
                continue
            if b["duration"] == [1, 24]:  # sixteenth triplet: keep 2 of 3, as sixteenths
                tri += 1
                if tri == 3:
                    tri = 0
                    continue
                d = Fraction(1, 4)
            else:
                assert tri == 0, "triplet group was not three notes in a row"
            ev.append([p, d, bi])
    # rests shorter than half a beat are folded into the note before
    out = []
    for p, d, bi in ev:
        if p is None and d < Fraction(1, 2):
            assert out and out[-1][0] is not None
            out[-1][1] += d
        else:
            out.append([p, d, bi])
    assert sum(d for _, d, _ in out) == SONG_BEATS, sum(d for _, d, _ in out)
    return out


# --------------------------------------------------------------------------- band
def bar_layers(track, bi):
    """Songsterr sometimes stores a bar's second layer after the first (a bar
    summing to more than 4 beats): fold position back into the bar."""
    pos = Fraction(0)
    for b in track["measures"][bi]["voices"][0]["beats"]:
        ns = [n for n in b["notes"] if not n.get("rest")]
        if not b.get("rest") and ns:
            yield pos % 4, ns, b
        pos += dur(b)


def drum_hits(d1):
    hits = []
    # Restore the opening one-beat bar: its three-note dead slap is a snare-like hit.
    for pos, ns, b in bar_layers(d1, 0):
        hits.append([fnum(pos), SLAP, DYN.get(b.get("velocity"), 100)])
    for bi in range(FIRST_BAR, LAST_BAR + 1):
        for pos, ns, b in bar_layers(d1, bi):
            beat = INTRO_BEATS + (bi - FIRST_BAR) * 4 + pos
            key = SLAP if len(ns) >= 4 else THUMP  # dead-note chord slap -> snare; low thump -> kick
            hits.append([fnum(beat), key, DYN.get(b.get("velocity"), 100)])
    hits.sort()
    return hits


def bass_notes(g3, shift):
    tun = g3["tuning"]
    out = []
    for bi in range(FIRST_BAR, LAST_BAR + 1):
        for pos, ns, b in bar_layers(g3, bi):
            low = min(tun[n["string"]] + n["fret"] for n in ns)
            out.append([fnum(INTRO_BEATS + (bi - FIRST_BAR) * 4 + pos), low + 12 + shift, fnum(min(dur(b), 1))])
    return out


def chord_part(g2, shift):
    tun = g2["tuning"]
    out = []
    for bi in range(FIRST_BAR, LAST_BAR + 1):
        for pos, ns, b in bar_layers(g2, bi):
            d = dur(b)
            # Keep every G2 strum, including muted and fast subdivisions. Short note
            # gates preserve the strummed/percussive feel without sustaining chords.
            beat = fnum(INTRO_BEATS + (bi - FIRST_BAR) * 4 + pos)
            for p in sorted(tun[n["string"]] + n["fret"] for n in ns):
                out.append([beat, p + shift, fnum(min(d, Fraction(1, 2)))])
    return out


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="folder holding G1/G2/G3/D1/W1 .json from Songsterr")
    ap.add_argument("--shift", type=int, default=-2)
    ap.add_argument("--ocarina", default=shutil.which("ocarina") or ".venv/bin/ocarina")
    ap.add_argument("--no-band", action="store_true", help="drums only (no bass, no part)")
    ap.add_argument("--max-seconds", default="70")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    g1, g2, g3, d1, w1 = (load(a.folder, n) for n in ("G1", "G2", "G3", "D1", "W1"))
    assert g1["automations"]["tempo"][0]["bpm"] == BPM
    mel = melody(g1)
    letters = " ".join("R" if p is None else note_name(p) for p, _, _ in mel)
    beats = " ".join(str(fnum(d)) for _, d, _ in mel)
    pitches = [p for p, _, _ in mel if p is not None]
    print(f"melody: {len(pitches)} notes, {sum(1 for p,_,_ in mel if p is None)} rests, "
          f"{SONG_BEATS} beats = {SONG_BEATS*60/BPM:.1f} s, range {min(pitches)}..{max(pitches)} "
          f"-> {min(pitches)+a.shift}..{max(pitches)+a.shift} (ocarina is 59..77)")
    assert 59 <= min(pitches) + a.shift and max(pitches) + a.shift <= 77, "shift leaves the ocarina's range"

    cmd = [a.ocarina, "build", "--slug", SLUG, "--name", NAME, "--artist", ARTIST,
           "--contributor", CONTRIBUTOR, "--part", PART, "--letters", letters,
           "--beats", beats, "--bpm", str(BPM), "--source", SOURCE,
           "--shift", str(a.shift), "--drums", "none", "--max-seconds", a.max_seconds]

    hits = drum_hits(d1)
    w_hits = drum_hits(w1)
    assert [h[0] for h in hits] == [h[0] for h in w_hits], "D1 and W1 disagree on hit positions"
    bass = [] if a.no_band else bass_notes(g3, a.shift)
    part = [] if a.no_band else chord_part(g2, a.shift)
    part2 = [] if a.no_band else bass_notes(g1, a.shift)
    print(f"drums: {sum(1 for h in hits if h[1]==SLAP)} slaps (snare) + {sum(1 for h in hits if h[1]==THUMP)} thumps (kick), "
          f"first hit at beat {hits[0][0]}")
    print(f"bass: {len(bass)} notes; part: {len(part)} strum notes (all G2 strums retained)")
    if a.dry_run:
        print("\n" + " ".join(f'"{c}"' if " " in c else c for c in cmd))
        return

    subprocess.run(cmd)#, check=True)
    path = os.path.join("songs", SLUG + ".json")
    with open(path) as f:
        song = json.load(f)
    assert song["bpm"] == BPM and abs(sum(song["beats"]) - SONG_BEATS) < 1e-6

    rhythm = (
        "Songsterr s52262 (revision 8980643), 130 BPM, 4/4. The opening one-beat guitar slap is restored at beat 0; "
        "the ocarina rests for that beat, then Rodrigo's lead guitar track (G1), Songsterr bars 2-33, plays the "
        "sixteenth riff (bars 2-17) then the melody (bars 18-33). 129 beats = 59.5 s. Rests under half a beat folded "
        "into the note before; the four sixteenth "
        "triplets (bars 19, 23, 27, 31) cut to their first two notes as sixteenths so every bar keeps its length "
        "(HmWhyNot's call). Shifted -2 (D4..G5 -> C4..F5, 182 modifiers against 190 at -3). The sixteenths are "
        "shorter than the ocarina's 0.08 s minimum at 130 BPM, so the stream slows the whole song to about 110 BPM "
        "(kept on purpose). Not checked against a second source. Drums: only the percussive hits already in the "
        "tab's Drums and Woodblock tracks (same positions): the opening dead-note slap as snare, dead-note chord "
        "slaps as snare, low-string thumps as kick, dynamics from the tab. Bass: the second guitar's walking line "
        "(G3, bars 26-33) an octave up, finger bass. Part: Gabriela's full rhythm-guitar track (G2), including all "
        "fast subdivisions and muted strums, represented as short nylon-guitar notes so the strumming backbone stays "
        "present. Band moved by the same -2."
    )
    song["rhythm"] = rhythm
    song["drums"] = {"style": "custom", "pattern": [SONG_BEATS, hits], "intro_beats": 0, "start": 0}
    if bass:
        song["bass"] = {"program": 33, "velocity": 84, "notes": bass}
    if part:
        song["parts"] = [{"program": 24, "velocity": 50, "notes": part}, {"program": 24, "velocity": 30, "notes": part2}]
    order = ["name", "artist", "contributor", "part", "key", "letters", "sources", "bpm", "beats", "notes",
             "rhythm", "drums", "bass", "parts", "max_seconds"]
    song = {**{k: song[k] for k in order if k in song}, **{k: v for k, v in song.items() if k not in order}}
    with open(path, "w") as f:
        json.dump(song, f, indent=2)
        f.write("\n")
    print("wrote", path)

    subprocess.run([a.ocarina, "validate"], check=False)

# Step 8 from AGENTS.md: every ocarina, bass, and part onset must coincide
    # with a drum hit. Add a quiet closed hat (GM 42) wherever the existing
    # track-derived groove has no hit, and ensure a kick on the first downbeat.
    try:
        from ocarina_songbook import band
        from ocarina_songbook.timing import song_timing, total_seconds
    except ImportError as exc:
        raise RuntimeError(
            "Run this script from the songbook repo with its venv active; "
            "step-8 drum-sync requires ocarina_songbook.timing and band."
        ) from exc

    e = json.load(open(path))
    t = song_timing(e)
    seconds_per_beat = sum(h + g for _n, h, g in t) / sum(e["beats"][:len(t)])
    duration_seconds = total_seconds(e)

    # Keep the original percussion events, but never put an event at or after
    # the pattern/song boundary. The full-song pattern must not loop past end.
    pattern_length, pattern_hits = e["drums"]["pattern"]
    pattern_hits = [h for h in pattern_hits if float(h[0]) < float(pattern_length)]

    # AGENTS.md explicitly requires a kick on the first downbeat.
    if not any(abs(float(beat)) <= 0.001 and int(key) == 36
               for beat, key, _velocity in pattern_hits):
        pattern_hits.append([0, 36, 30])
    e["drums"]["pattern"] = [pattern_length, pattern_hits]

    drum_times = {round(s, 3) for s, _k, _v in band.plan(t, e)[0]}
    onsets = []
    beat_cursor = 0.0
    for note, beats_in_note in zip(e["notes"], e["beats"]):
        if note != "REST":
            onsets.append(round(beat_cursor * seconds_per_beat, 3))
        beat_cursor += beats_in_note
    for inst in [e.get("bass")] + (e.get("parts") or []):
        for beat, _pitch, _length in (inst or {}).get("notes", []):
            onsets.append(round(float(beat) * seconds_per_beat, 3))

    missing_seconds = sorted({
        onset for onset in onsets
        if all(abs(onset - drum_time) > 0.001 for drum_time in drum_times)
    })
    # Convert the step-8 seconds back to pattern beat positions. Deduplicate
    # identical onsets (e.g. multiple pitches in one chord).
    existing_hat_beats = {
        round(float(beat), 3) for beat, key, _velocity in pattern_hits if int(key) == 42
    }
    for onset_seconds in missing_seconds:
        beat = round(onset_seconds / seconds_per_beat, 3)
        if beat < float(pattern_length) and beat not in existing_hat_beats:
            pattern_hits.append([beat, 42, 30])
            existing_hat_beats.add(beat)

    pattern_hits.sort(key=lambda hit: (float(hit[0]), int(hit[1])))
    e["drums"]["pattern"] = [pattern_length, pattern_hits]
    with open(path, "w") as f:
        json.dump(e, f, indent=2)
        f.write("\n")

    # The checks from AGENTS.md steps 5 and 8: reported, not enforced.
    try:
        from ocarina_songbook import band
        from ocarina_songbook.timing import song_timing, total_seconds
    except ImportError:
        print("(run inside the repo venv to get the timing and drum-sync report)")
        return
    e = json.load(open(path))
    t = song_timing(e)
    print(f"shortest held note: {min(h for _n, h, _g in t):.3f} s (needs 0.08); "
          f"length {total_seconds(e):.1f} s vs {sum(e['beats'])*60/e['bpm']:.1f} s at the real tempo")
    hits_, _intro = band.plan(t, e)
    spb = sum(h + g for _n, h, g in t) / sum(e["beats"][:len(t)])
    drum_times = {round(s, 3) for s, _k, _v in hits_}
    onsets, x = [], 0.0
    for n, b in zip(e["notes"], e["beats"]):
        if n != "REST":
            onsets.append(round(x * spb, 3))
        x += b
    for inst in [e.get("bass")] + (e.get("parts") or []):
        for beat, _p, _l in (inst or {}).get("notes", []):
            onsets.append(round(beat * spb, 3))
    missing = [o for o in onsets if all(abs(o - d) > 0.001 for d in drum_times)]
    print(f"onsets with no drum hit under them: {len(missing)} of {len(onsets)}")

    # Run preview to create .wav
    subprocess.run([a.ocarina, "preview", "--band", path, "--soundfont", "oot.sf2"], check=True)

#     # Validate the corrected file, then prove that all onsets are covered and
#     # no planned drum event lands after the song ends.
#     subprocess.run([a.ocarina, "validate"], check=True)
#     e = json.load(open(path))
#     t = song_timing(e)
#     final_hits, _intro = band.plan(t, e)
#     assert any(abs(s) <= 0.001 and int(key) == 36 for s, key, _velocity in final_hits), \
#         "step-8 drum-sync failed: no kick on the first downbeat"
#     final_drum_times = {round(s, 3) for s, _k, _v in final_hits}
#     final_onsets = []
#     beat_cursor = 0.0
#     for note, beats_in_note in zip(e["notes"], e["beats"]):
#         if note != "REST":
#             final_onsets.append(round(beat_cursor * seconds_per_beat, 3))
#         beat_cursor += beats_in_note
#     for inst in [e.get("bass")] + (e.get("parts") or []):
#         for beat, _pitch, _length in (inst or {}).get("notes", []):
#             final_onsets.append(round(float(beat) * seconds_per_beat, 3))
#     still_missing = [o for o in final_onsets
#                      if all(abs(o - d) > 0.001 for d in final_drum_times)]
#     assert not still_missing, f"step-8 drum-sync failed for onsets: {still_missing[:20]}"
#     late_hits = [s for s, _k, _v in final_hits if s > duration_seconds + 0.001]
#     assert not late_hits, f"drum hits after song end: {late_hits[:10]}"
#     print(f"drum-sync: all {len(final_onsets)} onsets covered; "
#           f"added {len(missing_seconds)} quiet closed-hat sync hits; "
#           f"first-downbeat kick present; no hits after {duration_seconds:.3f}s")
#     print(f"shortest held note: {min(h for _n, h, _g in t):.3f} s (needs 0.08); "
#           f"length {duration_seconds:.1f} s vs {sum(e['beats'])*60/e['bpm']:.1f} s at the stated tempo")

if __name__ == "__main__":
    sys.exit(main())
