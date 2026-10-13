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

## pizzicato, steel, retro and sax

All four come from **Music Jingles** by Kenney (www.kenney.nl),
https://kenney.nl/assets/music-jingles. License: Creative Commons Zero
(CC0 1.0), http://creativecommons.org/publicdomain/zero/1.0/. Free to use in
personal, educational and commercial projects. Credit is welcome but not
required. Each folder holds the pack's licence file as `LICENSE-kenney.txt`.

The pack plays the same seventeen short melodies on five instruments. Each
set uses one of them: `pizzicato` the Pizzicato jingles (`jingles_PIZZI`),
`steel` the Steel jingles (`jingles_STEEL`), `retro` the 8-Bit jingles
(`jingles_NES`) and `sax` the Sax jingles (`jingles_SAX`).

`done` and `failed` are whole jingles, played as recorded: `done` is the
rising D, E, F sharp, G figure and `failed` the falling F, E, E flat, D one,
shortened to fit under 1.4 seconds where the recording ran longer. The other
nine events are built the same way as the Rhodes and kalimba sets: the last
note of a jingle (the only one with a full decay) is cut out, moved to a new
pitch where needed, and arranged into the same short figures. In the steel and
pizzicato sets the ring of the note before was filtered out of each cut note.
Built notes keep each instrument's own tuning.

| event | pizzicato | steel | retro | sax |
|---|---|---|---|---|
| done | PIZZI10 | STEEL10 | NES03 | SAX10 |
| failed | PIZZI07 | STEEL07 | NES00 | SAX07 |
| item_done | PIZZI04 | STEEL11 | NES14 | SAX15 |
| added | PIZZI02 | STEEL10 | NES12 | SAX02, SAX16 |
| copied | PIZZI02 | STEEL10 | NES12 | SAX16 |
| stopped | PIZZI08, PIZZI01 | STEEL01, STEEL05 | NES01, NES11 | SAX11, SAX05 |
| waiting | PIZZI16 | STEEL08 | NES09 | SAX04 |
| results | PIZZI16, PIZZI02 | STEEL08, STEEL10 | NES09, NES12 | SAX04, SAX02, SAX16 |
| no_more | PIZZI05 | STEEL05 | NES15 | SAX05 |
| update | PIZZI04, PIZZI02 | STEEL11, STEEL10 | NES14, NES12 | SAX15, SAX02, SAX16 |
| queue_end | PIZZI01, 11, 04, 08, 02 | STEEL05, 11, 01, 10 | NES11, 04, 14, 01, 12 | SAX05, 14, 15, 11, 02 |
