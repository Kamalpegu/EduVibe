import { tts } from "../services/tts.js";

function button(label, symbol, action, disabled = false) {
  const control = document.createElement("button");
  control.type = "button";
  control.className = "audio-control";
  control.setAttribute("aria-label", label);
  control.title = label;
  control.textContent = symbol;
  control.disabled = disabled;
  control.addEventListener("click", action);
  return control;
}

export function AudioBar(turn, slideIndex, onSlideChange, onUseTurn) {
  const wrap = document.createElement("section");
  wrap.className = "audio-card";
  wrap.setAttribute("aria-label", "Slide audio player");

  const controls = document.createElement("div");
  controls.className = "audio-controls";
  const progress = document.createElement("input");
  progress.type = "range";
  progress.className = "audio-progress";
  progress.min = "0";
  progress.max = "100";
  progress.value = String(Math.round(tts.snapshot(turn.id).progress * 100));
  progress.disabled = !tts.isSeekable(turn.id);
  progress.setAttribute("aria-label", "Narration progress");

  const updateProgress = () => {
    progress.value = String(Math.round(tts.snapshot(turn.id).progress * 100));
    progress.disabled = !tts.isSeekable(turn.id);
  };
  const navigate = (nextIndex) => {
    const next = Math.max(0, Math.min(turn.slides.length - 1, nextIndex));
    if (next === slideIndex) return;
    onUseTurn(turn.id);
    onSlideChange(next);
    if (tts.isPlaying(turn.id)) tts.playTurn(turn, next, onSlideChange);
  };

  controls.append(
    button("Previous slide", "‹", () => navigate(slideIndex - 1), slideIndex === 0),
    button(tts.isPlaying(turn.id) ? "Pause narration" : "Play narration", tts.isPlaying(turn.id) ? "Ⅱ" : "▶", () => {
      onUseTurn(turn.id);
      if (tts.isActive(turn.id)) tts.toggle(turn.id);
      else tts.playTurn(turn, slideIndex, onSlideChange);
    }),
    button("Stop narration", "■", () => tts.stop(turn.id), !tts.isActive(turn.id)),
    button("Next slide", "›", () => navigate(slideIndex + 1), slideIndex === turn.slides.length - 1),
  );
  progress.addEventListener("input", () => tts.seek(turn.id, Number(progress.value) / 100));
  const text = document.createElement("div");
  text.className = "audio-info";
  const title = document.createElement("strong");
  title.textContent = turn.slides[slideIndex].title;
  const count = document.createElement("span");
  count.textContent = `Slide ${slideIndex + 1} of ${turn.slides.length}`;
  text.append(title, count);
  wrap.append(controls, progress, text);

  wrap._unsubscribe = tts.subscribe((activeId, playing) => {
    const isPlaying = activeId === turn.id;
    const playButton = controls.children[1];
    playButton.textContent = isPlaying && playing ? "Ⅱ" : "▶";
    playButton.setAttribute("aria-label", isPlaying && playing ? "Pause narration" : "Play narration");
    controls.children[2].disabled = activeId !== turn.id;
    updateProgress();
  });
  return wrap;
}
