# Conversational flows

**Lars has no slash commands.** Users talk to it like a person; Lars classifies
intent with the LLM and routes accordingly. A few interactions add **inline
tap-buttons** (pulse check, confirmations) for speed, but typing always works too.

This document replaces the command list in the original plan. It defines the
intent taxonomy, the confirm-before-write rule, and example dialogs.

## Three input modes

1. **Text** — free-form natural language.
2. **Photo** — Apple Fitness summary, smart-scale screenshot, or nutrition label.
3. **Button tap** — inline-keyboard callbacks (pulse check answers, yes/no confirms).

## Intent taxonomy

The classifier maps each message to one intent (or `onboarding` if the user is
mid-setup):

| Intent | Triggered by | Routes to |
|---|---|---|
| `onboarding` | first message from a new allowlisted user, or resuming setup | onboarding flow |
| `log_workout` | Apple Fitness screenshot, or "did legs today" | vision/manual workout log → pulse check |
| `log_weight` | smart-scale screenshot, or "weighed 181 this morning" | vision/manual body-metric log |
| `log_nutrition` | "had a chicken sandwich", barcode/branded item, label photo | nutrition log |
| `view_plan` | "what's today?", "what's tomorrow's workout?" | read-only plan summary |
| `view_trends` | "how's my weight trending?", "how'd this week go?" | read-only summary |
| `change_schedule` | "move leg day to Saturday", "I can't train Friday anymore" | schedule update (confirmed) |
| `report_skip` | "I missed Monday", "skipping today" | skip handling (confirmed) |
| `request_generation` | "make me tomorrow's workout now" | explicit generation |
| `help` / `chitchat` | "what can you do?", general talk | conversational reply |

Ambiguous messages → Lars asks a short clarifying question rather than guessing.

## Confirm-before-write rule

- **Confirm (echo values, ask yes/no):** schedule changes, weight/body metrics,
  marking a workout done or skipped, and **any vision-parsed values**.
- **Acknowledge only (no confirm):** casual nutrition logs, chit-chat, read-only
  questions.

Confirmations use inline Yes / Edit / Cancel buttons; the user can also just
type a correction.

## Flows

### Onboarding (first message)

```
User: hey
Lars: Hi! I'm Lars, your training + nutrition coach. I'll ask a few quick
      questions to set you up — takes about a minute. First, what should I call you?
User: Greg
Lars: Nice to meet you, Greg. How old are you, and what's your sex (for calorie/
      training math)?
User: 34, male
Lars: Got it. How tall are you, and what do you weigh right now?
User: 5'11", 183
Lars: Thanks. What's your main goal — lose fat, build muscle, maintain, or recomp?
...
Lars: Which days do you want to train, and what's your split? (e.g. Push/Pull/Legs
      Mon/Wed/Fri)
...
Lars: Last thing — what timezone are you in? I'll send tomorrow's workout the
      night before.
User: Eastern
Lars: All set, Greg. I'll build your first workout the night before your next
      training day. Send me an Apple Fitness screenshot after you train, and a
      scale screenshot whenever you weigh in.
```

A non-allowlisted user gets a single polite decline and nothing is stored.

### Logging a workout (screenshot) → pulse check

```
User: [sends Apple Fitness summary screenshot]
Lars: Reading that… Traditional Strength Training, 52 min, 415 active cal,
      avg HR 128, on Jun 4. Log it as Wednesday's Pull day? [Yes] [Edit] [Cancel]
User: [taps Yes]
Lars: Logged ✅ Quick check-in — how hard did that feel?
      [Easy] [Just right] [Hard] [Brutal]
User: [taps Hard]
Lars: Energy today? [Low] [OK] [High]
User: [taps OK]
Lars: Soreness right now? [None] [Some] [A lot]
User: [taps Some]
Lars: Thanks — anything else I should know? (or skip)
User: left elbow a little cranky
Lars: Noted, I'll keep volume on pulling movements sensible. 💪
```

The pulse check fires **only after a confirmed completion**, is fully skippable,
and never nags.

### Logging weight (screenshot)

```
User: [sends smart-scale app screenshot]
Lars: Got it — 181.6 lb, 17.2% body fat, dated Jun 5 (this morning). Save? [Yes] [Edit]
User: [taps Yes]
Lars: Saved ✅ You're down ~0.8 lb on your 7-day average — right on track for your cut.
```

### Logging nutrition (three paths)

```
# Natural language → best-effort estimate
User: had a chicken caesar wrap and a banana for lunch
Lars: Logged ~620 cal, 38g protein, 55g carbs, 28g fat (estimate). 👍

# Branded / barcode → Open Food Facts
User: [sends barcode photo / "Chobani vanilla, one cup"]
Lars: Found it in Open Food Facts — Chobani Vanilla, 1 cup: 140 cal, 12g P,
      20g C, 2.5g F. Logged.

# Nutrition label photo
User: [sends nutrition-label photo]
Lars: Read the label — 1 serving: 240 cal, 9g P, 31g C, 9g F. How many servings
      did you have?
User: two
Lars: Logged 480 cal for 2 servings. 👍
```

For home cooking, the user can list ingredients and Lars estimates from the raw
ingredients.

### Viewing the plan / trends

```
User: what's on for tomorrow?
Lars: Tomorrow's Push day. I'll send the full workout tonight around 8pm. Want a
      preview now?

User: how's my weight going?
Lars: Over the last 2 weeks you're down 2.1 lb (7-day avg 181.4 → 179.3). Steady ~1 lb/week.
```

### Nightly generation (Lars initiates)

```
Lars (8:02pm): Here's tomorrow's Pull day 💪
      1) Deadlift — 3×5 @ ~225 lb
      2) Pull-ups — 3×8
      3) Barbell row — 3×10
      4) Face pulls — 3×15
      Going easy on heavy pulling given your elbow note. Reply if you want changes.
```

### Skip detection (Lars initiates) + rescheduling

```
Lars (9:00pm): Looks like Push day didn't get logged today — everything OK, or
      did you skip? [Did it] [Skipped] [Rescheduled]
User: [taps Skipped] busy day at work
Lars: No worries. Want me to push Push to tomorrow and shift the week, or just
      skip it this week? [Push to tomorrow] [Skip it]
User: [taps Skip it]
Lars: Done — marked it skipped. I'll factor that into your next session.
```

A user can also volunteer it first ("won't make today's workout"), which routes
to the same handler.

### Changing the schedule

```
User: I can't do Fridays anymore, move leg day to Saturday
Lars: Update your schedule so Legs is Saturday instead of Friday, starting this
      week? [Yes] [Cancel]
User: [taps Yes]
Lars: Updated ✅ Your next Legs day is Saturday.
```
