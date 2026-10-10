# VANI: The Persona Voyage (submission video)

A 2 min 30 s explainer in a pirate-voyage theme: VANI's ship, a straw-hat sail, and a crew of six persona agents. The narration is Sarvam Bulbul (`shubh_enhi_banking`, Indian English). Every number on screen comes from this project's own outputs.

## Files (in `out/`)

| File | What it is | Length |
|---|---|---|
| `VANI_full_with_demo_slot.mp4` | The whole film. At 0:38 a "Call demos" card lists the three calls | 2:30 |
| `1_opening.mp4` | Title, the problem, the idea | 0:38 |
| `2_demo_slot_card.mp4` | The "Call demos" card on its own, to put in front of your recordings | 0:12 |
| `3_solution_and_close.mp4` | How it works: map, evidence, personas, agents, live switch, learning loop, results, close | 1:39 |

## Adding the call demos

Use any editor (Clipchamp is built into Windows, or CapCut):

1. Put `1_opening.mp4` on the timeline.
2. Add `2_demo_slot_card.mp4`, or only its first 3 to 4 seconds as a title.
3. Add your three call recordings from Sarvam (Call Logs → each call → download recording):
   - Warm Hinglish · Noida retailer: rush, then frustration, then a meeting on Saturday at 5 pm
   - Formal Hinglish · Morbi wholesaler: switches to Gujarati, then a meeting on Thursday at 10 am
   - English-led · Chennai seller: confusion, then interest, then an online meeting on Monday at 6 pm

   Call recordings are audio only. Over each one, show the Talk page from the local VANI page or the call transcript, and add a small caption naming the switch as it happens.
4. Add `3_solution_and_close.mp4`.

## Scene list

| Time | Scene | On screen |
|---|---|---|
| 0:00 | Title | Ship sails in; "VANI · The Persona Voyage" |
| 0:10 | The problem | Five islands, one identical script; 11.5% meeting-fix |
| 0:25 | The idea | A crew of six persona agents |
| 0:38 | Call demos | Slot for your recordings |
| 0:50 | How the voyage works | Chapter card |
| 0:53 | Step 1 · The map | 1,49,363 sellers · 2,69,455 calls · 2,78,000+ audits |
| 1:04 | Step 2 · Evidence | First vs 4th+ call 16.3% vs 4.3%; slower pitch 32.1% vs 21.6%; slot after interest 61% vs 27.2% |
| 1:18 | Step 3 · Persona | Morbi wholesaler's persona: six settings, each with its reason; 9,002 distinct personas |
| 1:33 | Step 4 · Agents | Sellers per Sarvam agent; 17 variables per call |
| 1:41 | Live switch | Rush, then frustration, then interest, each answered on the next turn; switch log |
| 2:00 | Learning loop | Call → result → review queue → corrections → tomorrow's personas |
| 2:10 | Results | Right-turn switches: frustration 72%, rush 65%, confusion 34%, interest 30%; zero flip-flopping |
| 2:22 | Close | "One seller, one persona." |

## Changing it

- Edit the narration in `script.json`, then run `python tts.py` (add a speaker name as an argument to change the voice) and `python timeline.py`.
- The visuals are in `stage.html`; each scene is one function.
- Rebuild with `node render.js frames`, then `python assemble.py`. `node render.js stills` gives one picture per scene for a quick check.

## About the theme and Higgsfield

- The theme is an original pirate voyage. It uses no One Piece characters, names, flags or artwork, so the video is safe to submit and share.
- Higgsfield: the Claude connector can't generate media, and the workspace currently has 0 credits on the free plan. If you add credits, the opening and closing could be replaced with cinematic shots made in Higgsfield's own app. For example: "a small wooden sailing ship with a plain straw-hat emblem on its white sail crossing a moonlit ocean, cinematic, 16:9". Keep the prompts free of character or franchise names.
