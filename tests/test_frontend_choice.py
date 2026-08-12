"""Drive the real page in headless Chrome, from file://, with a stubbed session.

The Python tests exercise the API and can say nothing about the client, and the
forced-choice branch is exactly where that gap bit: `collect()` dereferenced a slider
element that a forced-choice item never builds, the throw happened inside
`captureCurrent()` — the first line of `submit()` — and Next silently did nothing on
every part-1 item. No server error, no visible message, nothing in the API tests.

Skipped when google-chrome is absent, so it never blocks a run that cannot do it.
"""
from __future__ import annotations

import html
import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
CHROME = shutil.which("google-chrome") or shutil.which("chromium")

pytestmark = pytest.mark.skipif(CHROME is None, reason="needs google-chrome")

RUBRIC = ["prompt_adherence", "scene_fidelity", "motion_quality",
          "object_consistency", "visual_quality", "physical_realism"]


def _session(n_choice=5, n_rating=4):
    def item(i, mode):
        return {"index": i, "token": f"t{i}", "prompt_text": f"prompt {i}",
                "prompt_text_he": None, "image_url": None,
                "video_a": f"a{i}.mp4", "video_b": f"b{i}.mp4", "mode": mode}
    items = [item(i, "2afc") for i in range(n_choice)]
    items += [item(i, "mos") for i in range(n_choice, n_choice + n_rating)]
    return {"session_id": "S", "consent": "consent", "rubric": RUBRIC,
            "choice_question": {"prompt": "Which video is better?", "options": [
                {"value": "A", "label": "A better"},
                {"value": "B", "label": "B better"},
                {"value": "tie", "label": "Same"}]},
            "items": items}


def _run(driver_js: str, tmp_path: Path) -> dict:
    """Build a single-file page from the real markup + real app.js, run it, read back
    whatever the driver put in document.title."""
    page = (STATIC / "index.html").read_text()
    body = page.split("<body>", 1)[1].split("</body>")[0]
    body = body.replace('<script src="/app.js"></script>', "")
    harness = f"""<!doctype html><html><head><meta charset="utf-8">
<style>{(STATIC / 'style.css').read_text()}</style></head><body>
{body}
<script>
window.__posts = []; window.__err = [];
window.onerror = (m) => {{ window.__err.push(String(m)); }};
window.fetch = (url, opts) => {{
  if (String(url).indexOf('/api/session') === 0)
    return Promise.resolve({{ok:true, json:() => Promise.resolve({json.dumps(_session())})}});
  window.__posts.push(JSON.parse(opts.body));
  return Promise.resolve({{ok:true, json:() => Promise.resolve({{ok:true}})}});
}};
localStorage.clear();
</script>
<script>{(STATIC / 'app.js').read_text()}</script>
<script>
setTimeout(async () => {{
  const out = {{}};
  // Drivers may be async: submit() awaits the pending saves before showing the done
  // screen, so anything checking end-of-session state has to wait for that too.
  try {{ await ({driver_js})(out); }} catch (e) {{ out.thrown = String(e); }}
  out.errors = window.__err;
  document.title = "RESULT " + JSON.stringify(out);
}}, 300);
</script></body></html>"""
    f = tmp_path / "harness.html"
    f.write_text(harness)
    dom = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
         "--virtual-time-budget=4000", "--dump-dom", f"file://{f}"],
        capture_output=True, text=True, timeout=120).stdout
    marker = "<title>RESULT "
    assert marker in dom, "driver never reported; the page probably failed to load"
    return json.loads(html.unescape(dom.split(marker, 1)[1].split("</title>", 1)[0]))


def test_next_advances_through_the_choice_block(tmp_path):
    """The regression: picking an option must enable Next AND Next must submit."""
    out = _run("""(out) => {
        document.getElementById("start-btn").click();
        out.choiceVisible = !document.getElementById("choice-block").classList.contains("hidden");
        out.disabledBefore = document.getElementById("next-btn").disabled;
        document.querySelector('.choice-btn[data-value="A"]').click();
        out.disabledAfterPick = document.getElementById("next-btn").disabled;
        document.getElementById("next-btn").click();
        out.section = document.getElementById("section-label").textContent;
        out.posts = window.__posts;
    }""", tmp_path)
    assert out["errors"] == [] and "thrown" not in out
    assert out["choiceVisible"] is True
    assert out["disabledBefore"] is True, "Next must start disabled"
    assert out["disabledAfterPick"] is False, "picking an option must enable Next"
    assert "(2 of 5)" in out["section"], f"Next did not advance: {out['section']}"
    assert len(out["posts"]) == 1
    post = out["posts"][0]
    assert post["choice"] == "A"
    # sliders must not be sent for a forced-choice item; the server 400s on that
    assert "video_a" not in post and "video_b" not in post


def test_block_boundary_switches_the_ui(tmp_path):
    out = _run("""(out) => {
        document.getElementById("start-btn").click();
        for (let i = 0; i < 5; i++) {
          document.querySelector('.choice-btn[data-value="B"]').click();
          document.getElementById("next-btn").click();
        }
        out.section = document.getElementById("section-label").textContent;
        out.choiceHidden = document.getElementById("choice-block").classList.contains("hidden");
        out.slidersShown = !document.getElementById("sliders-a").classList.contains("hidden");
        out.sliderCount = document.querySelectorAll("#rating input[type=range]").length;
        out.posts = window.__posts.length;
    }""", tmp_path)
    assert out["errors"] == [] and "thrown" not in out
    assert out["posts"] == 5
    assert "Part 2" in out["section"] and "(1 of 4)" in out["section"]
    assert out["choiceHidden"] is True and out["slidersShown"] is True
    assert out["sliderCount"] == 2 * len(RUBRIC)


def test_choice_note_is_optional_and_survives_back(tmp_path):
    """The comment box must never gate Next, must reach the server when filled, and
    must still be there if the rater goes Back to change their mind."""
    out = _run("""(out) => {
        document.getElementById("start-btn").click();
        out.noteVisible = !!document.getElementById("choice-note").offsetParent;
        // answer item 1 WITHOUT a note
        document.querySelector('.choice-btn[data-value="A"]').click();
        out.nextEnabledWithEmptyNote = !document.getElementById("next-btn").disabled;
        document.getElementById("next-btn").click();
        // answer item 2 WITH a note
        const box = document.getElementById("choice-note");
        box.value = "the dog's legs merge together";
        document.querySelector('.choice-btn[data-value="B"]').click();
        document.getElementById("next-btn").click();
        // item 3 must start clean, not inherit the previous note
        out.item3NoteAfterAdvance = document.getElementById("choice-note").value;
        document.getElementById("back-btn").click();
        out.noteRestoredOnBack = document.getElementById("choice-note").value;
        out.pickRestoredOnBack =
            document.querySelector(".choice-btn.selected").dataset.value;
        out.posts = window.__posts;
    }""", tmp_path)
    assert out["errors"] == [] and "thrown" not in out
    assert out["noteVisible"] is True
    assert out["nextEnabledWithEmptyNote"] is True, "an empty note must not block Next"
    assert "choice_note" not in out["posts"][0], "empty note must not be sent"
    assert out["posts"][1]["choice_note"] == "the dog's legs merge together"
    assert out["posts"][1]["choice"] == "B"
    assert out["item3NoteAfterAdvance"] == "", "note leaked to the next item"
    assert out["noteRestoredOnBack"] == "the dog's legs merge together"
    assert out["pickRestoredOnBack"] == "B"


def test_finish_completes_the_session(tmp_path):
    """Clicking Finish on the last item must reach the done screen.

    The regression: submit() increments idx past the end before setBusy(false)
    recomputes canProceed(), so isChoice() was asked about SESSION.items[idx] when
    that is undefined. The throw landed between setBusy(true) and show("done") —
    Finish stayed disabled, the rating screen stayed up, and nothing said why.
    Every earlier test stopped one click short of this.
    """
    out = _run("""async (out) => {
        document.getElementById("start-btn").click();
        for (let i = 0; i < 5; i++) {
          document.querySelector('.choice-btn[data-value="A"]').click();
          document.getElementById("next-btn").click();
        }
        for (let r = 0; r < 4; r++) {
          document.querySelectorAll("#rating input[type=range]")
            .forEach(s => { s.value = 7; s.dispatchEvent(new Event("input")); });
          document.getElementById("next-btn").click();   // includes the final Finish
        }
        await new Promise(r => setTimeout(r, 100));      // submit() awaits its saves
        out.doneShown = !document.getElementById("done").classList.contains("hidden");
        out.ratingHidden = document.getElementById("rating").classList.contains("hidden");
        out.posts = window.__posts.length;
        out.progress = document.getElementById("progress-bar").style.width;
    }""", tmp_path)
    assert out["errors"] == [] and "thrown" not in out
    assert out["posts"] == 9, f"every item must be submitted, got {out['posts']}"
    assert out["doneShown"] is True, "Finish did not reach the done screen"
    assert out["ratingHidden"] is True
    assert out["progress"] == "100%"


def test_rating_item_still_needs_every_slider(tmp_path):
    """The forced-choice path must not have loosened the rule for rating pairs."""
    out = _run("""(out) => {
        document.getElementById("start-btn").click();
        for (let i = 0; i < 5; i++) {
          document.querySelector('.choice-btn[data-value="A"]').click();
          document.getElementById("next-btn").click();
        }
        out.disabledOnEntry = document.getElementById("next-btn").disabled;
        const sliders = document.querySelectorAll("#rating input[type=range]");
        sliders.forEach((s, i) => {
          if (i === sliders.length - 1) return;      // leave one untouched
          s.value = 7; s.dispatchEvent(new Event("input"));
        });
        out.disabledWithOneMissing = document.getElementById("next-btn").disabled;
        const last = sliders[sliders.length - 1];
        last.value = 7; last.dispatchEvent(new Event("input"));
        out.disabledWhenComplete = document.getElementById("next-btn").disabled;
    }""", tmp_path)
    assert out["errors"] == [] and "thrown" not in out
    assert out["disabledOnEntry"] is True
    assert out["disabledWithOneMissing"] is True, "a partial rating must not submit"
    assert out["disabledWhenComplete"] is False
