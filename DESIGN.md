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
| s05  | abol     | Mortar and pestle, grinding                | Rhythm that links picture to score                   |
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
| 1  | **Daniel (friend), Ethiopia** | **Awaiting feedback.** Share the radio cut and record Daniel's own words after he watches/listens. | To be decided after his feedback. |
| 2  | **Estifanos (friend), Ethiopia** | **Awaiting feedback.** Share the radio cut and record Estifanos's own words after he watches/listens. | To be decided after his feedback. |
| 3  | **Kidus (cousin), Ethiopia** | **Awaiting feedback.** Share the radio cut and record Kidus's own words after he watches/listens. | To be decided after his feedback. |

**Testing status:** These three people are the intended audience-test participants. Their feedback has not yet been collected, so this table must be completed using their actual responses before it is described as a completed user test.

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

An AI assistant previously reviewed the radio cut's script, subtitle file (`outputs/final/radio_cut.srt`) and timings while role-playing three audience personas. **It did not hear the audio**, so it could not judge the TTS voice, pronunciation or how the drone sounds. Those simulated reactions are not feedback from Daniel, Estifanos or Kidus and are not counted as audience evidence.

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

*Pending (Phase 8).*
