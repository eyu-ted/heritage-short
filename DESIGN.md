# DESIGN: audience, intent, and what the audience changed

Written **before any film image, clip or music was generated** (25 Nov 2026). The only generated media so far are provider smoke-test samples (`outputs/smoke/`), which are not film material.

## 1. Brief

|                                |                                                                                                                              |
| :----------------------------- | :--------------------------------------------------------------------------------------------------------------------------- |
| **Film**                       | *Buna*: my grandmother's coffee ceremony, 60-90 s, Amharic narration, English subtitles, original score                      |
| **Who watches**                | Young Ethiopians and diaspora family members, especially grandchildren who grew up away from these mornings                  |
| **Where**                      | On a phone, in a social feed or a family chat, vertical, often starting muted (hence burned-in subtitles)                    |
| **The one feeling at the end** | Belonging: the wish to slow down and sit with family. The ceremony is not about coffee, it is about time and being together. |
| **Logline**                    | Three small cups, three rounds, and nobody is left out.                                                                      |
| **Define (how might we)**      | How might we help grandchildren far from home feel the warmth of their grandmother's coffee ceremony in 70 seconds?          |

## 2. Treatment

Before the city wakes, my grandmother spreads fresh grass on the floor and begins the ceremony she has led every morning: washing the beans, roasting them over charcoal until the smell calls the neighbours in, burning incense, grinding. Then the waiting, which she taught her grandchild is part of the gift. One pot pours into many small cups, and no one is ever left out. Three rounds, *abol*, *tona* and *baraka*, the blessing, and by the third cup strangers have become family. The film ends at her open door: stay a little longer, the coffee is still warm.

## 3. Structure and why each shot exists

The ceremony's three rounds give the film its acts, its music cues and its ending. Every shot has one idea and one gentle movement. No faces are shown: hands, objects, smoke, steam and one elder seen only from behind (see ETHICS.md).

| Shot | Act      | Picture                                    | Why it exists                                        |
| :--- | :------- | :----------------------------------------- | :--------------------------------------------------- |
| s01  | prologue | Dawn courtyard, fresh grass on the floor   | Establish where and when, and the slow pace          |
| s02  | prologue | Green beans washed in a clay bowl          | First object; patient, tactile rhythm                |
| s03  | abol     | Beans roasting over charcoal, smoke rising | Sensory hook: fire and the smell that gathers people |
| s04  | abol     | Incense smoke, backlit                     | Mood and welcome without hands or faces              |
| s05  | abol     | Mortar and pestle, pounding                | Rhythm that links picture to score                   |
| s06  | tona     | Jebena on the coals, steam                 | A breath in the pacing: waiting is part of the gift  |
| s07  | tona     | The pour from the jebena into many cups    | Hero shot and recurring motif: one pot, many cups    |
| s08  | baraka   | Elder from behind, offering a cup          | The human presence, without any real likeness        |
| s09  | baraka   | Cups on a tray, empty stools in warm light | Emotional peak: the blessing, community implied      |
| s10  | close    | The door opens onto morning light          | Closes the circle with shot 1: the invitation stays  |

The narration sets the pace: each shot lasts its spoken line plus a one-second breath, never less than its planned minimum (`pipeline/timeline.py`).

## 4. User test 1: the radio cut

**Prototype:** `outputs/final/radio_cut.mp4` (84.2 s), Amharic narration (`gemini-3.8-flash-lite-tts`, voice Sulafat) over a placeholder drone on a black screen, with English subtitles. Built by `python -m pipeline radio` on 25 Nov.

Timing from the real narration (66.2 s of speech in 84.2 s): s01 9.3 s, s02 9.2, s03 8.6, s04 8.5, s05 6.2, s06 8.1, s07 8.0, s08 8.3, s09 7.0, s10 8.0, end card 3.0. The film is near the 90 s ceiling, so test 1 should listen for lines that can be cut or shortened.

**Who:** at least 3 people from the audience (young Ethiopians / diaspora family). Record initials only.

**How (think-aloud, \~5 minutes each):** play it once without comment, then ask:

1. What did you picture while listening?
2. Which line did you feel the most? Which line did nothing?
3. Where did you get lost or bored?
4. Was the pace right: too slow, too fast?
5. Did any Amharic word sound wrong or unnatural?
6. What does this film make you want to do?

| #  | Who (participant, relation, location) | What they said | What I will change |
| :- | :------------------------------------ | :-------------- | :----------------- |
| 1  | **D. (friend), Ethiopia**, wired earphones | Pictured "close-up shots of the coffee preparation". Liked s06 ("waiting is part of the gift"); s07 "One pot. Many cups…" "felt more like a slogan". Lost interest "around 33–36 seconds… the screen went black and there were no subtitles. I wasn't sure if that was intentional". "The middle dragged a little… removing around 5–8 seconds would make it flow better." ጎረቤቶች (s03) "sounded unnatural… the rhythm". "Maybe a small click near the beginning, around 6 seconds." | Dead air cut (s07, s09); ጎረቤቶች logged as a TTS limitation (see §5 table) |
| 2  | **E. (friend), Ethiopia**, headphones | Pictured "my grandmother's house early in the morning… fresh grass… charcoal smoke… small coffee cups on the rekebot". s10 "stood out the most… my grandmother… used to say the same thing"; s04 incense "didn't really have much impact". "Around 45–50 seconds, there was a quiet moment where I briefly lost focus." Pace "a little slow, but that actually suits the coffee ceremony". "Baraka" "the emphasis didn't feel quite natural". "The background music was slightly too loud in a few places." No clicks. | Dead air cut; deeper music ducking (EXPERIMENTS E9) |
| 3  | **K. (family), Ethiopia**, phone speaker | Pictured "a relaxed Sunday at home, with neighbours coming over". s09 ("strangers had become family") "captured the feeling… really well"; s02 "a little too simple". "A little [bored] during the middle, especially around the incense and grinding sections. My attention came back when the three rounds of coffee started." "Slightly slow for my taste." Voice "a little too formal, almost like someone reading the news." No clicks. | Middle tightened (s07, s09 holds); voice tone left open (see §5) |

**Testing status:** done on **26 Nov 2026**, late in the project, after the pictures existed. The file was `outputs/final/radio_cut__score-seed22.mp4`: narration and the chosen score on a black screen with subtitles. It was used instead of the older `radio_cut.mp4`, which still had the C2PA noise at the end of every line (FAILURES F11). Answers are in the participants' own words, sent by message. Who listened: 2 friends and 1 family member, all in Ethiopia, so no diaspora viewer, and 1 family member, which may make the answers kinder. The same three also did test 2 (§5) right after this one.

**What test 1 changed:** two of the three lost focus in a quiet stretch with no subtitles (D. at 33–36 s, E. at 45–50 s), and two said the middle drags (D., K.). This confirms the dead air that the AI-assisted review measured in §4a (2.4 s after s07, 2.9 s after s09). `min_duration_s` went from 8 to 6.5 for s07 and from 7 to 5.5 for s09. Only the shots and the films rebuilt; the Wan clip hashes did not change. The lines each person liked least were all different (s04, s07, s02), so no line was cut on one opinion.

### Quick way to collect the feedback

Send each participant the same radio cut and ask them to listen/watch independently. Then ask the six questions below. Record their answers in their own words; short answers are acceptable.

1. What did you picture while listening?
2. Which line did you feel the most? Which line did nothing for you?
3. Where did you get lost or bored?
4. Was the pace right: too slow or too fast?
5. Did any Amharic word sound wrong or unnatural?
6. What does this film make you want to do?

For a useful comparison, ask each participant the same two additional questions:

7. Did you understand when each coffee round (abol, tona and baraka) was happening?
8. Would you watch the film to the end if it appeared in your social-media feed?

**Important:** Do not fill in their answers on their behalf. If someone cannot listen to the audio, record that limitation rather than treating their response as an audio evaluation.

### 4a. Preparation notes (AI-assisted review, NOT user testing)

An AI assistant previously reviewed the radio cut's script, subtitle file (`outputs/final/radio_cut.srt`) and timings while role-playing three audience personas. **It did not hear the audio**, so it could not judge the TTS voice, pronunciation or how the drone sounds. Those simulated reactions are not feedback from D., E. or K. and are not counted as audience evidence.

Measured from the SRT (facts, not opinions):

- After s07 the subtitles stop for **2.4 s** (55.9 to 58.3 s), and after s09 for **2.9 s** (70.8 to 73.6 s). Both gaps happen because `min_duration_s` is longer than the line plus its 1 s breath. On a black screen these are the most likely places for people to get bored.
- Two subtitle line breaks split a phrase: "No / one was ever left out" (s07) and "It was / her way of saying" (s04).
- The audience hears the names abol and tona only at s08, after both rounds are already over.

What the AI-assisted review suggests testing with the three participants. These are proposals only and are not applied to `storyboard.json` until feedback has been collected:

1. Lower `min_duration_s` for s07 (8 to 6) and s09 (7 to 5.5) to remove about 4 s of dead air, or keep the floors and let the score carry those beats in the final cut.
2. Move or split the round names so each round is named as it begins.
3. Fix subtitle line breaks so "No one" and "her way" stay together.
4. Ask whether the film feels too long for a social-media feed.

## 5. User test 2: the near-final cut

**When and what:** 26 Nov 2026, right after test 1, with the same three people (D. friend, E. friend, K. family; all in Ethiopia). They watched `film_9x16__abf8dc622407.mp4` on a phone (all 10 shots Ken Burns, score `score-seed22`) using the kit's 9 questions. Then all three answered the pronunciation and wording questions for the native-speaker check. Listening: E. and D. on headphones, K. on the phone speaker. Their answers are in their own words.

| Question | D. | E. | K. |
|---|---|---|---|
| What happens | "a traditional Ethiopian coffee ceremony presented as a memory… only the jebena remains, suggesting that the grandmother is no longer there" | "the jebena left near the open door, but the grandmother is no longer there" | "a grandmother making coffee… eventually people come together" |
| Feeling | "calm… the ending works quite well… the middle feels more like a collection of beautiful objects… than a story about the grandmother herself" | "a little sad, but in a comforting way… the empty coffee pot sitting in the sunlight was especially emotional" | "peaceful and a little emotional. It actually made me miss home." |
| Anything wrong? | roasting pan "sitting on top of another pan filled with coals"; the jebena in s06 "unusually large and shiny"; images "still for… 6–9 seconds"; noticed "pounding" vs the earlier "grinding" | incense burner "placed outside on the grass… more like a flower pot than a traditional girgira"; "would have liked to see her at least once" | beans "a bit too perfect, almost like plastic"; the elder from behind "almost like a character from a video game" |
| Lost interest | "incense and pounding sections, around 30–40 seconds… not much visual movement" | no; bean washing "a little too long" | "the incense and pounding scenes… felt slow" |
| Subtitles | "too small for a vertical video… without a shadow or background, it gets lost… sit quite low" | "a little difficult to read… quite small… no background… over the fire and roasting beans, especially around 20–30 seconds" | "small, and sometimes it blended into the background" |
| Voice and music | "the background music was a little too loud during the first 20 seconds" | voice clear; music "slightly loud when the narrator said 'Then came the fire'" | "no problems with the sound" |
| End card | "the transition from the warm final scene to a completely black screen feels abrupt" | "surprised to see it after… such an emotional and personal story. The transition… a little sudden" | "could say who made the video or briefly explain what Buna means" |
| In a feed? | "not sure… I might scroll past… around 10–15 seconds" | "Yes… the opening shots of the grass and the open door caught my attention" | "not sure I would finish it… might scroll past around 15–20 seconds" |

**Native-speaker check** (the same three; the author did not judge their own script):

| Point | D. | E. | K. | Decision |
|---|---|---|---|---|
| Mispronounced | ቄጤማ "too soft, almost sounded like ተ"; ጎረቤቶች "robotic" | በረካ "emphasis… on the wrong syllable" | ዕጣን "a little unusual, but… not distracting" | see below |
| Reading or remembering? | "reading… almost like a newsreader" | "reading… [but] the final line… felt more personal" | "reading a script… a little formal" | 3 of 3: reading |
| strangers / guests (s09) | strangers | strangers | guests | **keep "strangers"** (2 of 3) |
| baraka / bereka (s08) | bereka | bereka | bereka | **subtitle now "bereka"** |
| ቄጠማ / ቄጤማ (s01) | ቄጤማ | ቄጤማ | ቄጤማ | **Amharic now ቄጤማ; s01 voice regenerated** (1 TTS call) |
| Keep the voice? | "acceptable for this version"; try a slower take or a human voice | yes; redo the last line "slower, with more emotion" | yes, "fine for social media" | keep for now (see below) |

### Findings to changes

| Finding (how many said it) | Change | Where in `storyboard.json` |
|---|---|---|
| Subtitles too small, no background, lost over busy images, too low (**3 of 3**) | A dark box behind the text, text 20% larger, lines in 9:16 at most 32 characters so the bigger text still fits, raised from 20% to 22% of the frame height | new `subtitles` block (schema updated; `pipeline/subtitles.py`) |
| Music too loud under the voice, especially in the first 20 s (**2 of 3**, and E. in test 1) | Measured first (EXPERIMENTS E9): at the old settings the score sat only 9.3 dB under the voice in s08 and 12.6 dB in the first 20 s. The new duck puts it 17–24 dB under. | `mix.duck`: threshold 0.02 → 0.01, ratio 6 → 10, attack 300 → 100 ms |
| Cut to the black end card abrupt (**2 of 3**) | Slower fade, longer card | `endcard.fade_s` 1 → 2 (new field), `endcard.duration_s` 3 → 4 |
| Card should say what Buna means (**1**) | Card subtitle "Buna means coffee - a Heritage Short" | `endcard.subtitle` |
| Quiet gaps, slow middle (test 1, **3 of 3**) | Shorter holds after s07 and s09 | `shots[s07/s09].min_duration_s` |
| ቄጤማ, bereka (**3 of 3** each) | Amharic spelling fixed and voiced again; subtitle spelling fixed | `shots[s01].narration.am`, `shots[s08].narration.en` |
| Images too still (**2 of 3**) | Real motion for the hero shots s03, s07, s10 (Wan 2.2, FAILURES F12) | shots stage, from the ingested clips |

### What was heard but not changed, and why
- **The voice sounds like reading (3 of 3), and E. asked for a slower last line.** The fix would be a new style instruction or model for all 10 lines, which is the whole free daily TTS quota (FAILURES F7, F8), with no time left to test it again. Recorded as the top open item. EXPERIMENTS E1 already lists a blind A/B of the style instruction as still open.
- **Pronunciation: ጎረቤቶች (D.), በረካ stress (E.), ዕጣን (K.).** Each was raised by one person, about a preset TTS voice, and there is no pronunciation control in the API. Recorded as a language limit (FAILURES F13).
- **Visual details: incense burner (E., s04), pan on coals (D., s03), jebena size (D., s06), plastic-looking beans and the game-like elder (K.).** Each was seen by one person. Each needs a keyframe retake and a new review, and s03 is a Wan shot. Listed as next work.
- **"Would have liked to see her at least once" (E.).** Not changed on purpose: no face is part of the consent and privacy choice (ETHICS §1–2).
- **The opening is slow for a feed; might scroll at 10–20 s (D., K.).** E. said the opening is what kept them watching. A stronger hook, for example the pour earlier, would mean re-ordering the story. Left for a next version.

### 5a. Review of the test-2 kit (26 Nov): AI-assisted, NOT user testing

The **written test kit** (questions, consent line, checklist) and the script text were reviewed before the test **with AI assistance**, written from the points of view of D., E. and K. (the same three people as §4). As in §4a, these are **not their own words and not audience evidence.** Nobody watched or heard the film for this review. It is recorded because it changed the test plan and one subtitle. Each change below was checked against the repo before it was applied; for example, the s05 fix was checked against the keyframe prompt.

| Finding | Persona | Change |
|---|---|---|
| Nothing asks about the pictures, though Ethiopian viewers are the ones most likely to spot a wrong jebena, odd cups or melted hands | D. | New neutral Q3: "Did anything you saw look wrong, strange, or out of place?" |
| The consent line says "I used AI tools", so the end-card question can't show whether the card is *noticed* | D. | The disclosure stays (ethically right). The kit now says that the question tests whether the card is readable and understood, not whether it is discovered. |
| Family viewers will be kind on "would you watch it?" | D. | Asks about behaviour too: "Where would you have scrolled away?" Family is marked as family, so the bias shows in the summary. |
| Feeds autoplay muted, and every test was sound-on | D. | Optional muted check: one viewer sees the first 5 s muted and says what they think it's about. |
| A phone speaker hides clicks | D. | At least one listen must be on headphones; the click check (F11) counts only from that. |
| Four films in `outputs/assemble/`, and the wrong one is easy to grab | E. | The kit names both full filenames; the two superseded films were deleted. |
| The gallery app's controls can cover the bottom subtitle line | E. | The kit says to tap once so the controls hide. |
| Initials + relation + city can identify someone in a public repo | E. | Public records use only initials, friend/family, and Ethiopia/diaspora. §4 had full first names, which are now initials. |
| The author approved the narration, so the author hears what they expect | K. | The separate native listener is required, not optional. |
| Regenerating one line on `gemini-3.8-flash-tts` while nine stay on lite would sound like a different speaker | K. | Verdict options: keep lite / regenerate the line on lite / regenerate all 10 on flash-tts (the whole daily quota). |
| s05: መውቀጥ is *pounding* (mortar), but the subtitle said *grinding* | K. | Checked against the picture: the s05 keyframe prompt is a wooden mortar with a pestle. The subtitle is now "pounding". It was a subtitle-only change, so the 2 films were re-rendered with no API calls. |
| s09 እንግዶች = *guests*, not *strangers*; s08 *baraka* vs *bereka*; s01 ቄጠማ vs ቄጤማ | K. | Left as they are, and added to the kit as questions for the native listener. These are wording and spelling choices, not errors. |
