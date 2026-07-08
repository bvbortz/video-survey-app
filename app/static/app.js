"use strict";

const LABELS = {
  prompt_adherence: "Prompt adherence",
  motion_quality: "Motion quality",
  object_consistency: "Object consistency",
  visual_quality: "Visual quality",
  physical_realism: "Physical realism",
};

let SESSION = null;   // {session_id, rubric, items:[...]}
let idx = 0;          // current item index
let shownAt = 0;      // timestamp for elapsed_ms

const $ = (id) => document.getElementById(id);
const show = (id) => $(id).classList.remove("hidden");
const hide = (id) => $(id).classList.add("hidden");

function fail(msg) {
  $("error-text").textContent = msg;
  ["consent", "rating", "done"].forEach(hide);
  show("error");
}

async function loadSession() {
  try {
    const r = await fetch("/api/session");
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
    const row = document.createElement("div");
    row.className = "slider-row";
    row.innerHTML =
      `<label>${LABELS[cat] || cat}<span class="val" id="v_${side}_${cat}">–</span></label>` +
      `<input type="range" min="0" max="10" step="1" value="5" ` +
      `data-side="${side}" data-cat="${cat}" data-touched="0">`;
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

  $("next-btn").disabled = true;
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

async function submit() {
  const it = SESSION.items[idx];
  $("next-btn").disabled = true;
  try {
    const r = await fetch("/api/response", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: SESSION.session_id,
        index: it.index,
        video_a: collect("a"),
        video_b: collect("b"),
        elapsed_ms: Date.now() - shownAt,
      }),
    });
    if (!r.ok) throw new Error("response " + r.status);
  } catch (e) {
    return fail("Could not save your rating. " + e.message);
  }
  idx += 1;
  if (idx >= SESSION.items.length) {
    $("progress-bar").style.width = "100%";
    hide("rating");
    show("done");
  } else {
    renderItem();
  }
}

$("start-btn").addEventListener("click", () => {
  hide("consent");
  show("rating");
  renderItem();
});
$("next-btn").addEventListener("click", submit);
$("again").addEventListener("click", (e) => { e.preventDefault(); location.reload(); });

loadSession();
