# EvoMind launch video v2: plan

**What it is:** EvoMind reads a Git repository's commit history and ranks its files by the chance they will need a bug fix in the next year, with the reasons.
**Who it's for:** developers and teams who want to know where the next bug will land before it lands.
**What sets it apart:** it learns from the repo's own past instead of generic lint rules, explains every score, and is re-tested at several points in history (rolling origin) to show the result holds.
**Most impressive claim (real, pallets/flask):** `src/flask/sansio/blueprints.py` risk 0.94; ROC-AUC 0.900 on held-out files; rolling-origin ROC-AUC 0.668 ± 0.006 across three cutoffs; 17 files in one dependency loop; learned from 17 years of commits.
**Hook:** "Your code is keeping secrets." on paper with a hatched question mark, wiped away by a pencil line.
**Shock:** the music drops out for half a beat, the screen floods red, "94%" counts up: "chance this file needs a bug fix this year."
**Tone:** default, in EvoMind's own sketchbook identity. Motion: entrances ease out, exits ease in, UI springs (about 9% overshoot), nothing at constant speed.
**Footage:** the user's own screen recording (EvomindScreenrecordingV3.mp4) of the working app. No invented numbers; no personal data on screen.

## Visual identity
Paper `#e8e2db`, bubble `#f7f4ee`, ink `#16161a`, red pen `#c8322b`. Permanent Marker, Caveat, JetBrains Mono. Paper stickers with hard ink shadow, red pen circles, site's inked rubber stamp.

## Music
Original track built in code: 88 BPM (beat 0.682 s), swing 0.58, Fmaj9 - Em7 - Dm9 - G13, Rhodes, pad, gliding bass, soft drums, chimes, vinyl air. 14 bars = 40.18 s. Drop before beat 24 and a sub impact on the red flood (16.36 s). Site's own stamp and whoosh on beats 11, 12, 24, 50, 54.
Foley (CC0, Freesound via Openverse), each placed so its loudest point lands on the motion frame, levelled against the music around it, with one shared short room: pen strokes on every underline and circle, paper slaps on sticker springs, paper swipes on the two wipes, a paper slide as the red shrinks into 0.94, soft ticks on the 17-year counter, typewriter keys on the URL, a low hit on the ink dip.

## Storyboard (40.18 s)
| # | Time | Shot | Overlay |
|---|---|---|---|
| 1 Hook | 0.00-2.75 | Paper card | "Your code / is keeping / secrets." on 16th notes, red underline, hatched ?, pencil wipe |
| 2 Front | 2.40-5.45 | Front page, slow push | "your codebase, probably" + arrow to the head |
| 3 Meet | 5.45-8.18 | Bubble close-up, Analyze stamped on beat 11, pull back as the page dives | Sticker "Meet EvoMind." |
| 4 Dive | 8.18-9.55 | Through the question marks, 1x | |
| 5 Scan | 9.55-13.64 | Ink city scan, ~6x | Counter card "17 years of commits" |
| 6 Riskiest | 13.64-16.80 | Camera to the riskiest file | Red underline under the path |
| 7 Shock | 16.36-20.45 | Red flood | "94%", "chance this file needs a bug fix this year.", path; red shrinks into the 0.94 |
| 8 Ranked | 20.10-23.18 | Results | Circle on 0.94, sticker "ranked, riskiest first" |
| 9 Why | 23.18-25.91 | Ranking scroll | Sticker "each one with the why" |
| 10 Loops | 25.91-28.64 | Dependency loop | Circle on "17 files", sticker "17 files stuck in one loop" |
| 11 Model | 28.64-31.36 | Evaluation | Circle on 0.900, sticker "0.90 on files it never saw" |
| 12 Rolling origin | 31.36-34.32 | Stability across time running, results land | Circle on 0.668 ± 0.006, "re-tested later: it holds." |
| 13 Dark | 34.09-35.86 | Ink dip into the dark theme | Sticker "day or night." |
| 14 Outro | 35.45-40.18 | Paper card, question-mark head | "EvoMind", underline, "find the files that will break next.", TRY IT stamp on beat 54, URL typed |

Poster (frame 0 and brag.jpg): the settled 94% shock frame.

## Sound credits (all CC0)
Underlining Stroke on Paper (zembacraftworks), Marker Lines (TubbsMedia), scribble (indigosierra), Rolled paper slapping 2 and 8 (kaonaya), Paper Swipe Surface2 Short/Mid (Frank1100), Paper slide (Kingofgamers_cz), Soft UI Button Click (Jummit), Typewriter snippet 03 (cabled_mess), Typewriter single key type 2 (yottasounds), LowHit_01 (Faulkin). Site sounds: CC0 Freesound (see EvoMind README).
