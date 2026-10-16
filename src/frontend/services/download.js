import { SlideSVG } from "../components/SlideSVG.js";

export function downloadSlide(slide, index, total) {
  const anchor = document.createElement("a");
  const filename = slide.title.replace(/[^\w-]+/g, "_").replace(/^_+|_+$/g, "") || `slide-${index + 1}`;
  anchor.download = `${filename}.svg`;
  let objectUrl = null;
  if (slide.svgUrl) {
    anchor.href = slide.svgUrl;
  } else {
    const svg = SlideSVG(slide, index + 1, total);
    const source = new XMLSerializer().serializeToString(svg);
    const blob = new Blob([source], { type: "image/svg+xml;charset=utf-8" });
    objectUrl = URL.createObjectURL(blob);
    anchor.href = objectUrl;
  }
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  if (objectUrl) window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

export async function downloadPresentation(query, lang = "en") {
  const response = await fetch("/api/ppt/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, lang }),
  });
  if (!response.ok) {
    let message = `PowerPoint export failed (${response.status}).`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch (error) {
      console.warn("Could not read the PowerPoint export error response.", error);
    }
    throw new Error(message);
  }

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = response.headers.get("Content-Disposition")
    ?.match(/filename="?([^";]+)"?/i)?.[1]
    || `${query.trim().replace(/[^\w-]+/g, "_").replace(/^_+|_+$/g, "") || "EduVibe"}.pptx`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}
