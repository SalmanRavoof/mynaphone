# Mynaphone logo brief

The designer's mark has been in the app since 2 October 2026. Its SVG source files, PNG exports and
Windows icons are in `mynaphone/gui/assets/mark`. To change the mark, edit an SVG source file and
export it again. This brief stays as the record of what was asked for.

## What the app does

A small Windows desktop app that lives in the system tray and quietly records the songs a person
plays. It keeps only the ones captured cleanly from start to finish, tags them properly and files
them into a personal offline music library.

It exists for people with unreliable internet who want the music they love available without a
connection. It's an archiving tool that never streams, downloads or shares anyone's music.
Picture a careful librarian with good ears.

## Where the name comes from

**Myna** + **gramophone**. The myna is a common bird across India, and some mynas can copy almost
any sound they hear: whistles, ringtones, other birds, human voices. Mynaphone repeats what it hears and
keeps it.

The gramophone half nods to record collections. A wind-up gramophone played music with no power at
all, and Mynaphone's library plays without a connection. Pronounced MY-nuh-fone.

## How the mark should feel

Attentive, faithful, calm, a little witty. A bird that listens closely and keeps a perfect copy. Not
loud, not "music app energetic", not retro-kitsch.

## Decisions to keep

**A myna's head in profile, as a simple vector, beak and all.** The common myna has a black head, a
yellow beak and bare yellow skin around the eye. The mark keeps the ink silhouette of the head, the
yellow beak and the yellow eye patch, and nothing else.

**The eye is the status light.** It's a round dot in the middle of a large yellow patch. It's dark
while the app listens and turns record red only while a song is being recorded.

In the tray and in the window, that color change is the whole signal. Lit up, the eye is also a
little larger than at rest, so the change still shows at 16 px.

The app's 64-unit drawing gives the eye a radius of 6 while listening and 7.5 while recording. The
patch around it is 30 units wide and 25 tall.

Paused grays the eye patch and stopped grays the whole head. Both are secondary states, and you can
redesign them if they hurt the mark.

**The tile.** In the tray and the title bar the head is drawn on a rounded paper square, because a
bare ink head disappears on a dark taskbar.

## Still not working

1. **The beak.** It's drawn as 2 triangles with the mouth open, and the black head shows between
   them. It's also long and flat for a common myna, whose bill is shorter, stout at the base and
   slightly curved down.
2. **The beak explorations.** The `explorations/beak` folder has 3 closed shapes I tried as a
   starting point.
3. **The eye patch.** Since it grew, it crosses the head's outline at the top right, so yellow pokes
   out of the silhouette. It also runs straight into the beak. In life, a common myna has a strip of
   dark feathers between the eye and the bill.
4. **The head.** It's a plain ellipse, which looks like a generic round bird. A myna's crown is
   flatter, and its forehead slopes down into the bill.
5. **Paused and stopped.** At 16 px they're hard to tell apart from listening.
6. **The bare mark.** Without the tile it vanishes on dark backgrounds.

## Changes to make

Refine the mark within the decisions above and fix the beak, the eye patch, the head and the 2
smaller states. Keep the eye as the status light, keep it flat, and check every state at 16 px
against light and dark backgrounds.

Please avoid the obvious: headphones, music notes, equalizer bars, a play triangle, a microphone, a
cassette, a parody of the HMV dog, a bird on a wire. No speech bubbles, no full bird, no wings.

## Hard requirements

- **Must read at 16 x 16 px** in the Windows system tray on light and dark taskbars. The red eye has
  to be obvious at that size.
- **Flat, solid shapes.** No gradients, glows, drop shadows, 3-D, neon, "AI-generated" shine, or
  mesh backgrounds. Think Fluent or a modern utility app, not a music-festival poster.
- **Works in one color.** A monochrome version is mandatory. Ink plus ochre, with red for the
  recording eye, is the most color the mark should use.
- **Wordmark.** "Mynaphone", lowercase or title case, in a clean humanist sans (Segoe UI, Inter or
  similar). The mark must also work alone without the wordmark.

These are the colors the app already uses.

| Name | Hex | Used for |
|---|---|---|
| Ink | `#1c1b19` | Head, sidebar |
| Ochre | `#e0a526` | Beak, eye patch, the one highlight in the window |
| Record red | `#e5484d` | The eye while recording, only |
| Paper | `#f3efe6` | The tile, the window's canvas |
| Eye | `#0b0b0a` | The eye while listening |
| Ink dim | `#5b574f` | The head when stopped |
| Ochre dim | `#8d877b` | The patch when paused or stopped |
| Ring | `#ede7da` | The eye when stopped |

## Deliverables

- SVG files of the mark alone for each of the 4 states, on the tile and bare.
- PNG files of each at 16, 20, 24, 32, 48, 64, 128, 256 and 512 px.
- A Windows `.ico` with 16, 20, 24, 32, 48 and 256 px.
- A monochrome mark in white and in black at 16 and 32 px.
- Browser extension icons at 16, 32, 48 and 128 px. The 128 px one has the mark at 96 px with 16 px
  of transparent padding per side, as the Chrome Web Store asks.
- A horizontal lockup (mark + wordmark) as SVG and as PNG at 2x, for the README.
- A one-page sheet with every state at 16 px next to the Windows tray icons around it.

## Places the mark appears

- **The system tray and the title bar**, at 16 to 24 px. People see it there a hundred times a day,
  and the full logo rarely.
- **The Status page**, at 56 px, in place of the song's cover art when it has none. Its eye follows
  the recorder's state there too.
- **The browser extension**, at 16 to 128 px.

The window has an ink sidebar, white cards on a warm paper canvas, one ochre highlight and Segoe UI.
For tone, look at the understated marks of utility software (Everything, 7-Zip's recent redesign
attempts, Obsidian) rather than Spotify, Deezer or SoundCloud.

## A prompt for AI design tools

> Flat vector logo mark for "Mynaphone", a Windows tray app that records the music you play for
> offline listening. A common myna's head in profile facing right: black head silhouette with a
> flatter crown and a forehead that slopes into a short, stout, slightly down-curved yellow bill
> (closed, with no opening). A large bare yellow skin patch around the eye, kept inside the head's
> outline and separated from the bill by black feathers. The eye is a round dot in the center of the
> patch, dark when idle and record red (#e5484d) when recording. Colors: ink #1c1b19, ochre #e0a526,
> paper #f3efe6 rounded-square tile. Flat solid shapes, no gradients, no shadows, no outlines, no text.
> Must read clearly at 16 x 16 px. Show the idle and recording versions side by side.
