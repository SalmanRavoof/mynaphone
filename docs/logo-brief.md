# Mynaphone logo brief

## What Mynaphone is

A small Windows desktop app that lives in the system tray and quietly records the songs a person
plays, keeps only the ones captured cleanly from start to finish, tags them properly and files them
into a personal offline music library. It exists for people with unreliable internet who want the
music they love available without a connection. It is a personal archiving tool, not a streaming
service and not a piracy tool. Picture a careful librarian with good ears.

## The name

**Myna** + **gramophone**. The myna is a common bird across India, famous for repeating any sound it
hears: whistles, ringtones, other birds, people. Mynaphone repeats what it hears, faithfully, and keeps
it. The gramophone half nods to archives, record collections and the idea of a permanent copy.
Pronounced MY-na-phone.

## What the mark should say

Attentive, faithful, calm, a little witty. A bird that listens closely and keeps a perfect copy. Not
loud, not "music app energetic", not retro-kitsch.

## The chosen direction

**A myna's head in profile, as a simple vector, beak and all.** The common myna has a dark head, a
yellow beak and a patch of bare yellow skin behind the eye. The mark keeps exactly those three
things: the ink silhouette of the head, the yellow beak, and the yellow eye patch. Nothing else.

**The eye is the status light.** In every state but one the eye is dark, as a bird's eye is. While
a song is being recorded, and only then, the eye turns record red. That one change is the whole
"recording" signal, in the tray and in the window, so the eye must be large enough to read at
16 px and placed where a red dot is unmistakable. The in-app placeholder drawn in code already
works this way, and the designed mark replaces it.

A paused state greys the eye patch and a stopped state greys the whole head; both are secondary and
may be dropped if they hurt the mark.

Please avoid the obvious: headphones, music notes, equaliser bars, a play triangle, a microphone, a
cassette, a parody of the HMV dog, a bird on a wire. No speech bubbles, no full bird, no wings.

## Hard requirements

- **Must read at 16 x 16 px** in the Windows system tray, in a single color on both a light and a
  dark taskbar. The tray version needs a tiny status dot (red = recording) placed where it will not
  collide with the mark; show where it goes.
- **Flat, solid shapes.** No gradients, glows, drop shadows, 3-D, neon, "AI-generated" shine, or
  mesh backgrounds. Think Fluent / modern utility app, not a music-festival poster.
- **Works in one color.** A monochrome version is mandatory; a two-color version (ink + one accent)
  is the maximum.
- Palette, which the app already uses: ink #1c1b19 for the head, ochre #e0a526 for the beak and eye
  patch, paper #f4f1ea for the canvas, record red #e5484d for the eye while recording only.
- Wordmark: "Mynaphone", lowercase or title case, set in a clean humanist sans (Segoe UI, Inter or
  similar). The mark must also work alone without the wordmark.
- Square app icon composition (Windows app icon, 256 px) and a horizontal lockup (mark + wordmark)
  for the window header and README.

## Deliverables

- Mark alone: SVG, plus PNG at 16, 24, 32, 48, 64, 128, 256, 512 px, light and dark variants.
- Windows `.ico` containing 16/24/32/48/256.
- Tray variants: monochrome white and monochrome black at 16 and 32 px, with the recording-dot
  position marked.
- Horizontal lockup: SVG and PNG at 2x.
- Browser extension icon: 128 px PNG, square.
- A one-page sheet showing the mark at 16 px next to the Windows tray icons it will live beside, so legibility can be judged.

## Context for the designer

- Users: one person at a desk, Windows 10, music playing from Spotify in the background while they
  work. They see the icon in the tray a hundred times a day and the full logo rarely.
- Tone reference: the understated marks of utility software (e.g., Everything, 7-Zip's recent redesign
  attempts, Obsidian's simplicity) rather than Spotify, Deezer or SoundCloud.
- The app's interface has an ink-dark sidebar, white cards on a warm paper canvas, one ochre
  highlight, Segoe UI. The mark sits at the top of the sidebar at 24 px tall, on the dark ground.
