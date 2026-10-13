# Sound credits

Each theme folder holds the same eleven events, as `<event>.mp3` (played on
the Mac) and `<event>.wav` (16-bit, 44.1 kHz, played on Windows): `done`,
`failed`, `item_done`, `added`, `stopped`, `waiting`, `results`, `no_more`,
`copied`, `update`, `queue_end`.

Every file was trimmed the same way: 10 ms of silence, a 3 ms fade-in, a
150 ms fade-out, a 40 ms silent tail, and the peak set to -1.5 dBFS.

## rhodes (the default)

Matthew Whitaker's own sounds, made for his tools. `done` and `failed` are
the Rhodes pair he chose by ear on 2026-10-13. The other nine use single notes
taken out of those same two recordings, moved to new pitches (no more than
seven semitones) and arranged into short figures. Same licence as the rest of
this repository.

## kalimba

Matthew Whitaker's own sounds, made for his tools: the kalimba family from
his `hark` client. All eleven are built from three single notes in those
recordings (B4, D#5 and F#5), moved to new pitches and arranged. Same licence
as the rest of this repository.

## soft

From **Interface Sounds** by Kenney (www.kenney.nl),
https://kenney.nl/assets/interface-sounds. License: Creative Commons Zero
(CC0 1.0), http://creativecommons.org/publicdomain/zero/1.0/. Free to use in
personal, educational and commercial projects. Credit is welcome but not
required. The licence file from the pack is `soft/LICENSE-kenney.txt`.

Source file for each event, levelled and trimmed as above:

| event | Kenney file |
|---|---|
| done | confirmation_004 |
| failed | error_006 |
| item_done | glass_006 |
| added | drop_002 |
| stopped | minimize_008 |
| waiting | back_004, its first tap played twice, 0.2 s apart |
| results | maximize_006 |
| no_more | bong_001 |
| copied | select_002 |
| update | confirmation_001 |
| queue_end | question_004 |
