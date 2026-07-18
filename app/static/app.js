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
      "You will watch pairs of short videos and rate each one on six aspects. " +
      "It takes about 8-10 minutes. No personal data is collected (only an anonymous " +
      "session id). Participation is voluntary and you may stop at any time. " +
      "By pressing Start you consent to participate.",
    setup_note:
      "ℹ️ The <strong>starting image is a real photo</strong>. The prompt and both " +
      "videos (A and B) are <strong>AI-generated</strong> — so a prompt may " +
      "occasionally describe something that can’t happen given the image. If that " +
      "occurs, rate what you actually see and tick the box on that screen.",
    start: "Start",
    requested_action: "Requested action:",
    hint_line: "Starting image = real photo · prompt & both videos = AI-generated",
    starting_image: "Starting image",
    video_a: "Video A",
    video_b: "Video B",
    flag_label:
      "There’s a problem with this pair — e.g. the prompt is impossible or doesn’t " +
      "match the starting image, contains NSFW/inappropriate content, or anything else",
    flag_note_ph:
      "Please describe what’s wrong (e.g. the action can’t happen given this image, " +
      "NSFW content, …)",
    back: "Back",
    next: "Next",
    finish: "Finish",
    saving: "Saving…",
    next_hint:
      "To continue, move every slider for both videos — or tick the “there’s a " +
      "problem” box above if this pair can’t be rated.",
    done_title: "Thank you!",
    done_text: "Your ratings were recorded. You may close this tab, or",
    again: "rate another set",
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
      "תצפו בזוגות של סרטונים קצרים ותדרגו כל אחד מהם בשישה היבטים. " +
      "הסקר אורך כ-8 עד 10 דקות. לא נאסף מידע אישי (רק מזהה סשן אנונימי). " +
      "ההשתתפות היא בהתנדבות וניתן להפסיק בכל עת. " +
      "בלחיצה על 'התחל' אתם מסכימים להשתתף.",
    setup_note:
      "ℹ️ <strong>תמונת הפתיחה היא צילום אמיתי</strong>. ההנחיה ושני הסרטונים " +
      "(A ו-B) <strong>נוצרו בבינה מלאכותית</strong> — כך שלעיתים הנחיה עשויה לתאר " +
      "משהו שאינו אפשרי בהתחשב בתמונה. אם זה קורה, דרגו את מה שאתם באמת רואים וסמנו " +
      "את התיבה באותו מסך.",
    start: "התחל",
    requested_action: "הפעולה המבוקשת:",
    hint_line: "תמונת הפתיחה = צילום אמיתי · ההנחיה ושני הסרטונים = תוצרי בינה מלאכותית",
    starting_image: "תמונת הפתיחה",
    video_a: "וידאו A",
    video_b: "וידאו B",
    flag_label:
      "יש בעיה עם הזוג הזה — למשל ההנחיה בלתי אפשרית או אינה תואמת את תמונת הפתיחה, " +
      "מכילה תוכן פוגעני/לא הולם, או כל דבר אחר",
    flag_note_ph:
      "אנא תארו מה הבעיה (למשל הפעולה אינה אפשרית בהתחשב בתמונה, תוכן לא הולם, …)",
    back: "חזור",
    next: "הבא",
    finish: "סיום",
    saving: "שומר…",
    next_hint:
      "כדי להמשיך, הזיזו כל מחוון בשני הסרטונים — או סמנו את התיבה 'יש בעיה' למעלה " +
      "אם לא ניתן לדרג את הזוג הזה.",
    done_title: "תודה!",
    done_text: "הדירוגים שלכם נשמרו. אפשר לסגור את הכרטיסייה הזו, או",
    again: "לדרג מערך נוסף",
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
  $("flag-note").placeholder = t("flag_note_ph");
  $("back-btn").textContent = t("back");
  $("saving-text").textContent = t("saving");
  $("next-hint").textContent = t("next_hint");

  $("done-title").textContent = t("done_title");
  $("done-text").textContent = t("done_text");
  $("again").textContent = t("again");
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

async function loadSession() {
  try {
    const seen = getSeen();
    const q = seen.length ? "?seen=" + encodeURIComponent(seen.join(",")) : "";
    const r = await fetch("/api/session" + q);
    if (!r.ok) throw new Error("session " + r.status);
    SESSION = await r.json();
    if (!SESSION.items.length) return fail(t("err_no_videos"));
    show("consent");
  } catch (e) {
    fail(t("err_load") + e.message);
  }
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

// A flagged pair may be submitted with partial (or no) ratings — the flag + note
// are the signal; untouched sliders are simply not sent.
function canProceed() {
  return allTouched() || $("flag-issue").checked;
}

function updateNav() {
  const ok = canProceed();
  $("next-btn").disabled = !ok;
  $("next-hint").classList.toggle("hidden", ok);
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
  $("flag-note").classList.toggle("hidden", !$("flag-issue").checked);
}

// read the current on-screen state into answers[idx]
function captureCurrent() {
  const touched = {};
  document.querySelectorAll("#rating input[type=range]").forEach((s) => {
    touched[`${s.dataset.side}_${s.dataset.cat}`] = s.dataset.touched === "1";
  });
  answers[idx] = {
    a: collect("a"), b: collect("b"), touched,
    issue: $("flag-issue").checked,
    note: $("flag-note").value.trim(),
  };
}

// restore a previously answered item back onto the freshly-built sliders
function restore(i) {
  const ans = answers[i];
  if (!ans) return;
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

  buildSliders($("sliders-a"), "a");
  buildSliders($("sliders-b"), "b");
  document.querySelectorAll("#rating input[type=range]")
    .forEach((s) => s.addEventListener("input", onSlider));

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
    if (s.dataset.touched === "1") out[cat] = Number(s.value);
  });
  return out;
}

function setBusy(busy) {
  $("saving").classList.toggle("hidden", !busy);
  $("next-btn").disabled = busy || !canProceed();
  $("back-btn").disabled = busy;
}

async function submit() {
  captureCurrent();
  const it = SESSION.items[idx];
  const ans = answers[idx];
  setBusy(true);
  try {
    const r = await fetch("/api/response", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: SESSION.session_id,
        index: it.index,
        video_a: ans.a,
        video_b: ans.b,
        elapsed_ms: Date.now() - shownAt,
        flag_issue: ans.issue,
        note: ans.note,
      }),
    });
    if (!r.ok) throw new Error("response " + r.status);
  } catch (e) {
    setBusy(false);
    return fail(t("err_save") + e.message);
  }
  markSeen(it.token);   // remember across rounds so its clips aren't shown again
  setBusy(false);
  idx += 1;
  if (idx >= SESSION.items.length) {
    $("progress-bar").style.width = "100%";
    hide("rating");
    show("done");
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
  hide("consent");
  show("rating");
  renderItem();
});
$("next-btn").addEventListener("click", submit);
$("back-btn").addEventListener("click", goBack);
$("again").addEventListener("click", (e) => { e.preventDefault(); location.reload(); });

applyStaticI18n();
loadSession();
