"use strict";

// ---------------------------------------------------------------- i18n
// English is the default. Hebrew is a full translation; the language switcher
// (top of the page) is always visible. Category labels/tips are grounded in the
// automatic evaluator's own rubric (react-agent/config.yaml). Survey prompts are
// translated separately and served from Mongo as `prompt_text_he` (see
// scripts/push_hebrew_prompts.py); English is used as a fallback when a given
// prompt has no Hebrew yet.
const I18N = {
  en: {
    dir: "ltr",
    doc_title: "Video Quality Survey",
    consent_title: "AI Video Quality Survey",
    consent_text:
      "This is an anonymous academic research survey on AI-generated video quality. " +
      "You will see pairs of short videos and pick the one that better matches its " +
      "description. Each comparison takes well under a minute — do as few or as many " +
      "as you like, and stop whenever you want. No personal data is collected (only " +
      "an anonymous session id). Participation is voluntary. " +
      "By pressing Start you consent to participate.",
    // Some prompts carry one deliberately wrong detail. The previous wording told
    // raters to flag exactly that as a problem, which would have thrown away the
    // subgroup this round exists to measure.
    setup_note:
      "ℹ️ The <strong>starting image is a real photo</strong>. The prompt and both " +
      "videos (A and B) are <strong>AI-generated</strong>. Some prompts " +
      "<strong>deliberately contain a small detail that does not match the image</strong> " +
      "— a wrong colour, count, or object. That is intentional and part of what we are " +
      "testing: still just pick the video that handles the description better. " +
      "Use the “there’s a problem” box only when a pair is genuinely unusable — a video " +
      "will not play, or the content is inappropriate.",
    start: "Start",
    requested_action: "Requested action:",
    // Shown on every item. The setup note is read once and forgotten, and raters
    // were flagging the deliberately-mismatched prompts as broken — so the
    // reminder has to live next to the task, not only on the consent screen.
    hint_line:
      "Starting image = real photo · prompt & both videos = AI-generated · " +
      "some prompts don’t quite match the image on purpose — just pick the better video",
    starting_image: "Starting image",
    video_a: "Video A",
    video_b: "Video B",
    // Must NOT mention the prompt not matching the image: that is the designed
    // condition, and naming it here told raters to flag the entire subgroup.
    flag_label:
      "This pair is unusable — a video won’t play or is blank, or the content is " +
      "inappropriate",
    flag_reminder:
      "A prompt that doesn’t quite match the image is <strong>intentional</strong> — " +
      "please don’t flag it for that. Untick this and just pick the video that " +
      "handles the description better.",
    flag_note_ph:
      "What’s wrong? (e.g. video B never loads, black frames, inappropriate content …)",
    back: "Back",
    next: "Next",
    finish: "Finish",
    saving: "Saving…",
    next_hint:
      "To continue, move every slider for both videos — or tick the “there’s a " +
      "problem” box above if this pair can’t be rated.",
    // Forced-choice pairs. Kept here rather than taken from the server so the
    // question reads naturally in both languages; the server's wording is the
    // fallback and stays the record of what was asked.
    choice_prompt: "Which video better matches the description, and looks more realistic?",
    choice_a: "Video A is clearly better",
    choice_b: "Video B is clearly better",
    choice_tie: "About the same",
    // Both parts are real data; the wording deliberately avoids calling part 1 a
    // warm-up, because those answers are the ones the study most depends on.
    section_choice: (i, n) => `Part 1 of 2 — quick comparisons (${i} of ${n})`,
    section_rating: (i, n) => `Part 2 of 2 — detailed ratings (${i} of ${n})`,
    // Optional on purpose. Which defects a person actually notices is the thing a
    // score cannot tell us, but requiring prose here would cost far more answers
    // than the prose is worth.
    choice_note_label: "Optional — anything wrong in either video? (a few words is plenty)",
    choice_note_ph: "e.g. the legs merge together, the object vanishes halfway, the camera jumps",
    next_hint_choice:
      "To continue, pick one of the three options above — or tick the “there’s a " +
      "problem” box if this pair can’t be judged.",
    done_title: "Saved — thank you!",
    exhausted_title: "That is all of them — thank you!",
    exhausted_text: "You have compared every pair we have. If you would like to keep helping,",
    done_tally: (n) => n === 1
      ? "That is 1 comparison you have contributed."
      : `That is ${n} comparisons you have contributed.`,
    done_text: "Prefer to score videos in detail instead?",
    again: "Keep going →",
    switch_rating: "Switch to detailed rating",
    error_title: "Something went wrong",
    counter: (i, n) => `Pair ${i} of ${n}`,
    scale_lo: "0 = poor",
    scale_hi: "10 = perfect",
    err_no_videos: "No videos are available yet.",
    err_load: "Could not load the survey. ",
    err_save: "Could not save your rating. ",
    cats: {
      prompt_adherence: {
        label: "Prompt adherence",
        tip: "How well the video does what the prompt asked for — the right objects, action and details actually appear and match the request.",
      },
      scene_fidelity: {
        label: "Scene fidelity",
        tip: "How faithfully the video stays true to the starting image — same scene, colours, camera viewpoint and main subject; it should not morph or drift into a different scene.",
      },
      motion_quality: {
        label: "Motion quality",
        tip: "How natural and smooth the movement is — steady, believable motion with no jitter, stutter, flicker or unnatural speed.",
      },
      object_consistency: {
        label: "Object consistency",
        tip: "Whether objects keep a stable identity and shape throughout — no morphing, splitting, disappearing/reappearing, or drifting into something else.",
      },
      visual_quality: {
        label: "Visual quality",
        tip: "Overall image quality of the frames — sharp and clean, free of blur, distortion, warping or compression artifacts.",
      },
      physical_realism: {
        label: "Physical realism",
        tip: "Whether motion and interactions obey real-world physics — believable gravity, contact and movement, with no impossible or broken physics.",
      },
    },
  },
  he: {
    dir: "rtl",
    doc_title: "סקר איכות וידאו",
    consent_title: "סקר איכות וידאו שנוצר בבינה מלאכותית",
    consent_text:
      "זהו סקר מחקר אקדמי אנונימי על איכות וידאו שנוצר בבינה מלאכותית. " +
      "תראו זוגות של סרטונים קצרים ותבחרו את זה שמתאים יותר לתיאור. " +
      "כל השוואה נמשכת פחות מדקה — אפשר לעשות מעט או הרבה, ולעצור מתי שרוצים. " +
      "לא נאסף מידע אישי (רק מזהה סשן אנונימי). ההשתתפות היא בהתנדבות. " +
      "בלחיצה על 'התחל' אתם מסכימים להשתתף.",
    setup_note:
      "ℹ️ <strong>תמונת הפתיחה היא צילום אמיתי</strong>. ההנחיה ושני הסרטונים " +
      "(A ו-B) <strong>נוצרו בבינה מלאכותית</strong>. חלק מההנחיות " +
      "<strong>מכילות בכוונה פרט קטן שאינו תואם את התמונה</strong> — צבע, כמות או " +
      "עצם שגויים. זה מכוון וזה חלק ממה שאנחנו בודקים: פשוט בחרו את הסרטון שמתמודד " +
      "טוב יותר עם התיאור. סמנו את התיבה 'יש בעיה' רק כשזוג באמת אינו שמיש — סרטון " +
      "שאינו מתנגן, או תוכן לא הולם.",
    start: "התחל",
    requested_action: "הפעולה המבוקשת:",
    hint_line:
      "תמונת הפתיחה = צילום אמיתי · ההנחיה ושני הסרטונים = תוצרי בינה מלאכותית · " +
      "חלק מההנחיות אינן תואמות במדויק את התמונה בכוונה — פשוט בחרו את הסרטון הטוב יותר",
    starting_image: "תמונת הפתיחה",
    video_a: "וידאו A",
    video_b: "וידאו B",
    flag_label:
      "לא ניתן להשתמש בזוג הזה — סרטון שאינו מתנגן או ריק, או תוכן לא הולם",
    flag_reminder:
      "הנחיה שאינה תואמת במדויק את התמונה היא <strong>מכוונת</strong> — נא לא לסמן " +
      "בעיה בגלל זה. בטלו את הסימון ופשוט בחרו את הסרטון שמתמודד טוב יותר עם התיאור.",
    flag_note_ph:
      "מה הבעיה? (למשל וידאו B לא נטען, פריימים שחורים, תוכן לא הולם …)",
    back: "חזור",
    next: "הבא",
    finish: "סיום",
    saving: "שומר…",
    next_hint:
      "כדי להמשיך, הזיזו כל מחוון בשני הסרטונים — או סמנו את התיבה 'יש בעיה' למעלה " +
      "אם לא ניתן לדרג את הזוג הזה.",
    choice_prompt: "איזה וידאו תואם יותר לתיאור ונראה מציאותי יותר?",
    choice_a: "וידאו A טוב יותר באופן ברור",
    choice_b: "וידאו B טוב יותר באופן ברור",
    choice_tie: "בערך אותו דבר",
    section_choice: (i, n) => `חלק 1 מתוך 2 — השוואות מהירות (${i} מתוך ${n})`,
    section_rating: (i, n) => `חלק 2 מתוך 2 — דירוגים מפורטים (${i} מתוך ${n})`,
    choice_note_label: "רשות — משהו לא תקין באחד הסרטונים? (גם כמה מילים יעזרו)",
    choice_note_ph: "למשל הרגליים מתמזגות, האובייקט נעלם באמצע, המצלמה קופצת",
    next_hint_choice:
      "כדי להמשיך, בחרו אחת משלוש האפשרויות למעלה — או סמנו את התיבה 'יש בעיה' " +
      "אם לא ניתן לשפוט את הזוג הזה.",
    done_title: "נשמר — תודה!",
    exhausted_title: "זה הכול — תודה!",
    exhausted_text: "השוויתם כל זוג שיש לנו. אם תרצו להמשיך לעזור,",
    done_tally: (n) => n === 1
      ? "זו השוואה אחת שתרמתם."
      : `אלו ${n} השוואות שתרמתם.`,
    done_text: "מעדיפים לדרג סרטונים לעומק במקום?",
    again: "ממשיכים →",
    switch_rating: "מעבר לדירוג מפורט",
    error_title: "משהו השתבש",
    counter: (i, n) => `זוג ${i} מתוך ${n}`,
    scale_lo: "0 = גרוע",
    scale_hi: "10 = מושלם",
    err_no_videos: "אין עדיין סרטונים זמינים.",
    err_load: "לא ניתן היה לטעון את הסקר. ",
    err_save: "לא ניתן היה לשמור את הדירוג שלך. ",
    cats: {
      prompt_adherence: {
        label: "נאמנות להנחיה",
        tip: "עד כמה הווידאו עושה את מה שההנחיה ביקשה — האובייקטים, הפעולה והפרטים הנכונים אכן מופיעים ותואמים לבקשה.",
      },
      scene_fidelity: {
        label: "נאמנות לסצנה",
        tip: "עד כמה הווידאו נשאר נאמן לתמונת הפתיחה — אותה סצנה, צבעים, זווית מצלמה ונושא מרכזי; הוא לא אמור להשתנות או להיסחף לסצנה אחרת.",
      },
      motion_quality: {
        label: "איכות התנועה",
        tip: "עד כמה התנועה טבעית וחלקה — תנועה יציבה ואמינה, ללא רעידות, קפיצות, הבהובים או מהירות לא טבעית.",
      },
      object_consistency: {
        label: "עקביות האובייקטים",
        tip: "האם האובייקטים שומרים על זהות וצורה יציבות לאורך כל הווידאו — ללא שינוי צורה, התפצלות, היעלמות והופעה מחדש, או הידמות למשהו אחר.",
      },
      visual_quality: {
        label: "איכות חזותית",
        tip: "איכות התמונה הכללית של הפריימים — חדה ונקייה, ללא טשטוש, עיוות, מתיחות או ארטיפקטים של דחיסה.",
      },
      physical_realism: {
        label: "ריאליזם פיזיקלי",
        tip: "האם התנועה והאינטראקציות מצייתות לחוקי הפיזיקה של העולם האמיתי — כוח משיכה, מגע ותנועה אמינים, ללא פיזיקה בלתי אפשרית או שבורה.",
      },
    },
  },
};

const LANG_KEY = "survey_lang";
let lang = "en";
try { const s = localStorage.getItem(LANG_KEY); if (s && I18N[s]) lang = s; } catch {}

const L = () => I18N[lang];
const t = (key) => L()[key];

let SESSION = null;   // {session_id, rubric, items:[...]}
let idx = 0;          // current item index
let shownAt = 0;      // timestamp for elapsed_ms of current item
let answers = [];     // answers[i] = {a:{cat:n}, b:{cat:n}, touched:{}, issue, note}

const $ = (id) => document.getElementById(id);
const show = (id) => $(id).classList.remove("hidden");
const hide = (id) => $(id).classList.add("hidden");

function fail(msg) {
  $("error-text").textContent = msg;
  ["consent", "rating", "done"].forEach(hide);
  show("error");
}

// ---------------------------------------------------------------- language
// Apply all static (non-per-item) strings for the current language, set page
// direction, and highlight the active language button.
function applyStaticI18n() {
  document.documentElement.lang = lang;
  document.documentElement.dir = L().dir;
  document.title = t("doc_title");

  $("consent-title").textContent = t("consent_title");
  $("consent-text").textContent = t("consent_text");
  $("setup-note").innerHTML = t("setup_note");
  $("start-btn").textContent = t("start");

  $("prompt-label").textContent = t("requested_action");
  $("hint-line").textContent = t("hint_line");
  $("cap-starting-image").textContent = t("starting_image");
  $("label-video-a").textContent = t("video_a");
  $("label-video-b").textContent = t("video_b");
  $("flag-label-text").textContent = t("flag_label");
  $("flag-reminder").innerHTML = t("flag_reminder");
  $("flag-note").placeholder = t("flag_note_ph");
  $("back-btn").textContent = t("back");
  $("saving-text").textContent = t("saving");
  $("next-hint").textContent = t("next_hint");

  $("done-title").textContent = t("done_title");
  $("done-tally").textContent = L().done_tally(doneCount());
  $("done-text").textContent = t("done_text");
  $("again").textContent = t("again");
  $("switch-rating").textContent = t("switch_rating");
  $("error-title").textContent = t("error_title");

  $("lang-en").classList.toggle("active", lang === "en");
  $("lang-he").classList.toggle("active", lang === "he");
}

function setLang(next) {
  if (!I18N[next] || next === lang) return;
  lang = next;
  try { localStorage.setItem(LANG_KEY, lang); } catch {}
  applyStaticI18n();
  // Re-render the current rating item so prompt text, category labels/tips,
  // scale ends and Next/Finish all switch language in place.
  if (!$("rating").classList.contains("hidden") && SESSION) {
    captureCurrent();
    renderItem();
  }
}

// ---------------------------------------------------------------- session
const SEEN_KEY = "survey_seen_tokens";
function getSeen() {
  try { return JSON.parse(localStorage.getItem(SEEN_KEY) || "[]"); }
  catch { return []; }
}
function markSeen(token) {
  if (!token) return;
  const set = new Set(getSeen());
  set.add(token);
  try { localStorage.setItem(SEEN_KEY, JSON.stringify([...set])); } catch {}
}

// Comparisons are the default and the continuation. A rating set is something a
// rater opts into from the done screen, never something they are handed.
let BLOCK = "choice";

async function loadSession(block, skipConsent) {
  try {
    BLOCK = block || BLOCK;
    const seen = getSeen();
    const p = new URLSearchParams();
    if (seen.length) p.set("seen", seen.join(","));
    if (BLOCK) p.set("block", BLOCK);
    const qs = p.toString();
    const r = await fetch("/api/session" + (qs ? "?" + qs : ""));
    if (!r.ok) throw new Error("session " + r.status);
    SESSION = await r.json();
    if (SESSION.exhausted) {
      // Not an error: this rater has genuinely seen every pair. Strict dedup
      // means we would rather end than show one twice.
      hide("rating");
      $("done-title").textContent = t("exhausted_title");
      $("done-tally").textContent = L().done_tally(doneCount());
      $("done-text").textContent = t("exhausted_text");
      $("again").style.display = "none";
      return show("done");
    }
    if (!SESSION.items.length) return fail(t("err_no_videos"));
    idx = 0;
    answers = {};
    if (skipConsent) {
      // A continuation: they already consented and are mid-flow. Dropping them
      // back on the consent screen is the reload we are removing.
      hide("done");
      show("rating");
      renderItem();
    } else {
      show("consent");
    }
  } catch (e) {
    fail(t("err_load") + e.message);
  }
}

// Lifetime count across rounds, so a returning rater sees their own total
// rather than starting from zero every set.
const DONE_KEY = "survey_done_count";
function doneCount() {
  const n = parseInt(localStorage.getItem(DONE_KEY) || "0", 10);
  return isNaN(n) ? 0 : n;
}
function bumpDone() {
  try { localStorage.setItem(DONE_KEY, String(doneCount() + 1)); } catch {}
}

function buildSliders(container, side) {
  container.innerHTML = "";
  SESSION.rubric.forEach((cat) => {
    const c = L().cats[cat] || { label: cat, tip: "" };
    const row = document.createElement("div");
    row.className = "slider-row";
    row.dataset.cat = cat;
    row.innerHTML =
      `<div class="cat-head">` +
        `<span class="cat-label">${c.label}</span>` +
        `<span class="info" tabindex="0">ⓘ<span class="tip">${c.tip}</span></span>` +
        `<span class="val" id="v_${side}_${cat}">–</span>` +
      `</div>` +
      `<input type="range" min="0" max="10" step="1" value="5" ` +
        `data-side="${side}" data-cat="${cat}" data-touched="0">` +
      `<div class="scale"><span>${t("scale_lo")}</span><span>${t("scale_hi")}</span></div>`;
    container.appendChild(row);
  });
}

function allTouched() {
  return [...document.querySelectorAll("#rating input[type=range]")]
    .every((s) => s.dataset.touched === "1");
}

// Forced-choice pairs (base vs finetuned) ask for one decision instead of ten
// sliders. The mode comes from the server per item; anything unset is a rating pair.
function isChoice(it) {
  // Tolerates being asked about nothing. submit() increments idx past the last item
  // before calling setBusy(false), which recomputes canProceed() -> isChoice() with
  // SESSION.items[idx] undefined. Dereferencing that threw, and the throw happened
  // between setBusy(true) and show("done"), so the survey froze on the last item with
  // Finish stuck disabled and no error on screen.
  const item = it || (SESSION && SESSION.items[idx]);
  return !!item && item.mode === "2afc";
}

let choicePick = null;   // "A" | "B" | "tie" | null, for the item on screen

function buildChoices() {
  const box = $("choice-options");
  box.innerHTML = "";
  const opts = (SESSION.choice_question && SESSION.choice_question.options) || [];
  opts.forEach((opt) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "choice-btn";
    b.dataset.value = opt.value;
    // Translated label where we have one, else the server's wording — which stays
    // the record of what was actually asked.
    b.textContent = t(`choice_${opt.value.toLowerCase()}`) || opt.label;
    b.addEventListener("click", () => {
      choicePick = opt.value;
      [...box.children].forEach((c) =>
        c.classList.toggle("selected", c.dataset.value === choicePick));
      updateNav();
    });
    box.appendChild(b);
  });
}

// A flagged pair may be submitted with partial (or no) ratings — the flag + note
// are the signal; untouched sliders are simply not sent.
function canProceed() {
  if (isChoice()) return choicePick !== null || $("flag-issue").checked;
  return allTouched() || $("flag-issue").checked;
}

function updateNav() {
  const ok = canProceed();
  $("next-btn").disabled = !ok;
  $("next-hint").classList.toggle("hidden", ok);
  $("next-hint").textContent = isChoice() ? t("next_hint_choice") : t("next_hint");
}

function onSlider(e) {
  const s = e.target;
  s.dataset.touched = "1";
  const v = $(`v_${s.dataset.side}_${s.dataset.cat}`);
  v.textContent = s.value;
  v.classList.add("set");
  updateNav();
}

function toggleNote() {
  const on = $("flag-issue").checked;
  $("flag-note").classList.toggle("hidden", !on);
  // Surfaced only when the box is ticked: this is the moment a rater is about to
  // flag a deliberately-mismatched prompt, and the only point where a reminder
  // still changes the outcome.
  $("flag-reminder").classList.toggle("hidden", !on);
}

// read the current on-screen state into answers[idx]
function captureCurrent() {
  const touched = {};
  document.querySelectorAll("#rating input[type=range]").forEach((s) => {
    touched[`${s.dataset.side}_${s.dataset.cat}`] = s.dataset.touched === "1";
  });
  const choice = isChoice();
  answers[idx] = {
    a: choice ? {} : collect("a"), b: choice ? {} : collect("b"), touched,
    choice: choice ? choicePick : null,
    choiceNote: choice ? $("choice-note").value.trim() : "",
    issue: $("flag-issue").checked,
    note: $("flag-note").value.trim(),
  };
}

// restore a previously answered item back onto the freshly-built sliders
function restore(i) {
  const ans = answers[i];
  if (!ans) return;
  if (ans.choice !== null && ans.choice !== undefined) {
    choicePick = ans.choice;
    [...$("choice-options").children].forEach((c) =>
      c.classList.toggle("selected", c.dataset.value === choicePick));
  }
  if (ans.choiceNote) $("choice-note").value = ans.choiceNote;
  document.querySelectorAll("#rating input[type=range]").forEach((s) => {
    const side = s.dataset.side, cat = s.dataset.cat;
    if (ans[side][cat] !== undefined) s.value = ans[side][cat];
    if (ans.touched[`${side}_${cat}`]) {
      s.dataset.touched = "1";
      const v = $(`v_${side}_${cat}`);
      v.textContent = s.value;
      v.classList.add("set");
    }
  });
  $("flag-issue").checked = ans.issue;
  $("flag-note").value = ans.note || "";
  toggleNote();
}

// Prompt text in the current language, English as fallback.
function promptFor(it) {
  if (lang === "he" && it.prompt_text_he) return it.prompt_text_he;
  return it.prompt_text || "";
}

function renderItem() {
  const it = SESSION.items[idx];
  $("prompt-text").textContent = promptFor(it);
  $("counter").textContent = t("counter")(idx + 1, SESSION.items.length);
  $("progress-bar").style.width = `${(idx / SESSION.items.length) * 100}%`;

  const img = $("cond-image");
  if (it.image_url) { img.src = it.image_url; img.style.display = ""; }
  else { img.style.display = "none"; }

  $("video-a").src = it.video_a;
  $("video-b").src = it.video_b;

  // Position within the current block, so the rater sees "3 of 5" for the part they
  // are in rather than a running count across two different tasks.
  const choice = isChoice(it);
  const block = SESSION.items.filter((x) => isChoice(x) === choice);
  const posInBlock = block.indexOf(it) + 1;
  $("section-label").textContent =
    (choice ? t("section_choice") : t("section_rating"))(posInBlock, block.length);

  // Exactly one of the two answer UIs is live per item.
  choicePick = null;
  $("choice-block").classList.toggle("hidden", !choice);
  $("sliders-a").classList.toggle("hidden", choice);
  $("sliders-b").classList.toggle("hidden", choice);
  if (choice) {
    $("choice-prompt").textContent =
      t("choice_prompt") ||
      ((SESSION.choice_question && SESSION.choice_question.prompt) || "");
    buildChoices();
    $("choice-note-label").textContent = t("choice_note_label");
    $("choice-note").placeholder = t("choice_note_ph");
    $("choice-note").value = "";      // cleared here, refilled by restore() below
  } else {
    buildSliders($("sliders-a"), "a");
    buildSliders($("sliders-b"), "b");
    document.querySelectorAll("#rating input[type=range]")
      .forEach((s) => s.addEventListener("input", onSlider));
  }

  // reset flag UI, then restore any prior answer for this item
  $("flag-issue").checked = false;
  $("flag-note").value = "";
  toggleNote();
  restore(idx);

  $("back-btn").classList.toggle("hidden", idx === 0);
  $("next-btn").textContent = idx === SESSION.items.length - 1 ? t("finish") : t("next");
  updateNav();
  window.scrollTo({ top: 0, behavior: "smooth" });
  shownAt = Date.now();
}

// Only sliders the rater actually moved are collected: an untouched slider means
// "not rated" (possible only on flagged pairs), never a default value.
function collect(side) {
  const out = {};
  SESSION.rubric.forEach((cat) => {
    const s = document.querySelector(`input[data-side="${side}"][data-cat="${cat}"]`);
    // A forced-choice item builds no sliders, so there is nothing to query. Without
    // this guard the null deref threw inside captureCurrent(), which is the first
    // thing submit() calls — so Next silently did nothing on every part-1 item.
    if (s && s.dataset.touched === "1") out[cat] = Number(s.value);
  });
  return out;
}

function setBusy(busy) {
  $("saving").classList.toggle("hidden", !busy);
  $("next-btn").disabled = busy || !canProceed();
  $("back-btn").disabled = busy;
}

// Ratings are sent without blocking the rater. The database is a free-tier Atlas
// in another region and a single write can take tens of seconds; waiting for that
// between every pair is how a survey gets abandoned half-finished. The send is
// idempotent server-side (keyed on session+index), so a retry cannot double-count.
const pendingSaves = [];
let saveFailures = 0;

function sendRating(it, ans, elapsed) {
  // The server rejects a payload of the wrong shape for the pair's mode, so send
  // the choice OR the sliders, never both.
  const payload = {
    session_id: SESSION.session_id,
    index: it.index,
    elapsed_ms: elapsed,
    flag_issue: ans.issue,
    note: ans.note,
  };
  if (isChoice(it)) {
    if (ans.choice !== null && ans.choice !== undefined) payload.choice = ans.choice;
    if (ans.choiceNote) payload.choice_note = ans.choiceNote;
  } else {
    payload.video_a = ans.a;
    payload.video_b = ans.b;
  }
  const body = JSON.stringify(payload);
  const post = () => fetch("/api/response", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    // survive the page being closed right after the last answer
    keepalive: true,
  }).then(r => { if (!r.ok) throw new Error("response " + r.status); });

  // one retry: these are unrecoverable if dropped, and the upsert makes it safe
  const p = post().catch(() => post()).catch(() => { saveFailures += 1; });
  pendingSaves.push(p);
  return p;
}

async function submit() {
  captureCurrent();
  const it = SESSION.items[idx];
  const ans = answers[idx];

  sendRating(it, ans, Date.now() - shownAt);
  markSeen(it.token);   // remember across rounds so its clips aren't shown again
  bumpDone();
  idx += 1;

  if (idx >= SESSION.items.length) {
    // Only the last one waits, so nothing is lost if the tab closes on "done".
    setBusy(true);
    await Promise.allSettled(pendingSaves);
    setBusy(false);
    $("progress-bar").style.width = "100%";
    hide("rating");
    // Refresh the tally here, not only in applyStaticI18n: it is rendered once at
    // page load and would otherwise show the count from before this set.
    $("done-tally").textContent = L().done_tally(doneCount());
    $("again").style.display = "";      // may have been hidden by an exhausted set
    show("done");
    if (saveFailures > 0) fail(t("err_save") + saveFailures);
  } else {
    renderItem();
  }
}

function goBack() {
  if (idx === 0) return;
  captureCurrent();     // keep whatever is on screen
  idx -= 1;
  renderItem();
}

$("lang-en").addEventListener("click", () => setLang("en"));
$("lang-he").addEventListener("click", () => setLang("he"));
$("flag-issue").addEventListener("change", () => { toggleNote(); updateNav(); });
$("start-btn").addEventListener("click", () => {
  // Best-effort and deliberately not awaited: the funnel measurement must never
  // put a network round trip between pressing Start and seeing the first video.
  if (SESSION && SESSION.session_id) {
    fetch("/api/session/" + encodeURIComponent(SESSION.session_id) + "/consent",
          {method: "POST", keepalive: true}).catch(() => {});
  }
  hide("consent");
  show("rating");
  renderItem();
});
$("next-btn").addEventListener("click", submit);
$("back-btn").addEventListener("click", goBack);
$("again").addEventListener("click", (e) => {
  e.preventDefault();
  // Was location.reload(): a full round trip that re-ran consent and threw away
  // every buffered video. Fetch the next set in place instead.
  loadSession("choice", true);
});
$("switch-rating").addEventListener("click", (e) => {
  e.preventDefault();
  loadSession("rating", true);
});

applyStaticI18n();
loadSession();
