"use strict";

// Category tooltips are grounded in the automatic evaluator's own rubric
// (react-agent/config.yaml: prompt_adherence / motion_quality / visual_quality /
// consistency analyses + the morphing / artifact / physics scoring criteria).
const CATS = {
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
};
const SCALE_LO = "0 = poor";
const SCALE_HI = "10 = perfect";

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
    if (!SESSION.items.length) return fail("No videos are available yet.");
    $("consent-text").textContent = SESSION.consent;
    show("consent");
  } catch (e) {
    fail("Could not load the survey. " + e.message);
  }
}

function buildSliders(container, side) {
  container.innerHTML = "";
  SESSION.rubric.forEach((cat) => {
    const c = CATS[cat] || { label: cat, tip: "" };
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
      `<div class="scale"><span>${SCALE_LO}</span><span>${SCALE_HI}</span></div>`;
    container.appendChild(row);
  });
}

function allTouched() {
  return [...document.querySelectorAll("#rating input[type=range]")]
    .every((s) => s.dataset.touched === "1");
}

function onSlider(e) {
  const s = e.target;
  s.dataset.touched = "1";
  const v = $(`v_${s.dataset.side}_${s.dataset.cat}`);
  v.textContent = s.value;
  v.classList.add("set");
  $("next-btn").disabled = !allTouched();
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
    s.value = ans[side][cat];
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

function renderItem() {
  const it = SESSION.items[idx];
  $("prompt-text").textContent = it.prompt_text || "";
  $("counter").textContent = `Pair ${idx + 1} of ${SESSION.items.length}`;
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
  $("next-btn").textContent = idx === SESSION.items.length - 1 ? "Finish" : "Next";
  $("next-btn").disabled = !allTouched();
  window.scrollTo({ top: 0, behavior: "smooth" });
  shownAt = Date.now();
}

function collect(side) {
  const out = {};
  SESSION.rubric.forEach((cat) => {
    out[cat] = Number(
      document.querySelector(`input[data-side="${side}"][data-cat="${cat}"]`).value
    );
  });
  return out;
}

function setBusy(busy) {
  $("saving").classList.toggle("hidden", !busy);
  $("next-btn").disabled = busy || !allTouched();
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
    return fail("Could not save your rating. " + e.message);
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

$("flag-issue").addEventListener("change", toggleNote);
$("start-btn").addEventListener("click", () => {
  hide("consent");
  show("rating");
  renderItem();
});
$("next-btn").addEventListener("click", submit);
$("back-btn").addEventListener("click", goBack);
$("again").addEventListener("click", (e) => { e.preventDefault(); location.reload(); });

loadSession();
