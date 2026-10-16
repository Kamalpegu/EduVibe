import { AudioBar } from "./AudioBar.js";
import { SlideSVG } from "./SlideSVG.js";
import { tts } from "../services/tts.js";

function make(className, tag = "div", text = "") {
  const node = document.createElement(tag);
  node.className = className;
  if (text) node.textContent = text;
  return node;
}

export function Turn(turn, onSlideChange, onUseTurn, onDownload) {
  const article = make("turn", "article");
  article.setAttribute("aria-label", `Search: ${turn.query}`);

  const query = make("user-bubble", "p", turn.query);
  article.append(query);

  if (turn.status === "loading") {
    const loading = make("assistant-loading");
    loading.setAttribute("role", "status");
    loading.append(make("loading-mark", "span", "✦"), make("loading-label", "span", "Building slides…"));
    article.append(loading);
    return article;
  }

  if (turn.status === "error") {
    const error = make("assistant-error");
    error.setAttribute("role", "alert");
    error.append(
      make("error-title", "strong", "That search didn’t finish."),
      make("error-copy", "p", `${turn.error || "Something interrupted slide generation."} Resend your search to try again.`),
    );
    article.append(error);
    return article;
  }

  if (!turn.slides?.length) return article;
  const slideIndex = Math.max(0, Math.min(turn.currentSlide || 0, turn.slides.length - 1));
  const result = make("assistant-result");
  const card = make("slide-card");
  card.append(SlideSVG(turn.slides[slideIndex], slideIndex + 1, turn.slides.length));
  result.append(card, AudioBar(turn, slideIndex, onSlideChange, onUseTurn));

  const dots = make("slide-dots");
  dots.setAttribute("role", "group");
  dots.setAttribute("aria-label", "Choose a slide");
  turn.slides.forEach((slide, index) => {
    const dot = make("slide-dot", "button");
    dot.type = "button";
    dot.setAttribute("aria-label", `Show slide ${index + 1}: ${slide.title}`);
    dot.setAttribute("aria-pressed", String(index === slideIndex));
    dot.title = slide.title;
    dot.addEventListener("click", () => {
      onUseTurn(turn.id);
      onSlideChange(index);
      if (tts.isPlaying(turn.id)) tts.playTurn(turn, index, onSlideChange);
    });
    dots.append(dot);
  });
  const footer = make("slide-footer");
  footer.append(dots);
  const download = make("slide-download", "button", "↓  Download slide");
  download.type = "button";
  download.setAttribute("aria-label", "Download current slide as SVG");
  download.addEventListener("click", onDownload);
  footer.append(download);
  result.append(footer);
  article.append(result);
  return article;
}
