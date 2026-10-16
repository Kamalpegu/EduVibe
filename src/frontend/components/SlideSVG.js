const SVG_NS = "http://www.w3.org/2000/svg";
let nextGradientId = 0;

function svgElement(name, attributes = {}, text = "") {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) {
    node.setAttribute(key, String(value));
  }
  if (text) node.textContent = text;
  return node;
}

function wrappedText(svg, text, x, y, className, maxCharacters, lineHeight, maxLines = 2) {
  const node = svgElement("text", { x, y, class: className });
  const words = String(text).split(/\s+/);
  const lines = [];
  let line = "";
  for (const word of words) {
    if (line && `${line} ${word}`.length > maxCharacters) {
      lines.push(line);
      line = word;
    } else {
      line = line ? `${line} ${word}` : word;
    }
  }
  if (line) lines.push(line);
  const shownLines = lines.slice(0, maxLines);
  if (lines.length > maxLines) shownLines[maxLines - 1] = `${shownLines[maxLines - 1].slice(0, maxCharacters - 1)}…`;
  shownLines.forEach((value, index) => {
    node.append(svgElement("tspan", { x, dy: index === 0 ? 0 : lineHeight }, value));
  });
  svg.append(node);
}

export function SlideSVG(slide, slideNumber, total) {
  if (slide.svgUrl) {
    const image = document.createElement("img");
    image.className = "slide-svg";
    image.src = slide.svgUrl;
    image.alt = `${slide.title}, slide ${slideNumber} of ${total}`;
    return image;
  }

  const gradientId = `slide-bg-${++nextGradientId}`;
  const svg = svgElement("svg", {
    class: "slide-svg",
    viewBox: "0 0 1280 720",
    role: "img",
    "aria-label": `${slide.title}, slide ${slideNumber} of ${total}`,
    preserveAspectRatio: "xMidYMid meet",
  });
  const defs = svgElement("defs");
  defs.append(svgElement("style", {}, `
    .slide-eyebrow{fill:#c9c3ff;font:700 17px "Segoe UI",sans-serif;letter-spacing:5px}
    .slide-title{fill:#fff;font:800 47px "Segoe UI",sans-serif}
    .slide-bullet{fill:#f3f2ff;font:500 31px "Segoe UI",sans-serif}
    .slide-counter{fill:#d2d0ed;font:600 17px "Segoe UI",sans-serif}
  `));
  const gradient = svgElement("linearGradient", { id: gradientId, x1: "0", y1: "0", x2: "1", y2: "1" });
  gradient.append(
    svgElement("stop", { offset: "0", "stop-color": "#20234e" }),
    svgElement("stop", { offset: "1", "stop-color": "#5142a8" }),
  );
  defs.append(gradient);
  svg.append(defs, svgElement("rect", { width: 1280, height: 720, fill: `url(#${gradientId})` }));
  svg.append(svgElement("rect", { x: 0, y: 0, width: 1280, height: 9, fill: "#db3045" }));
  const logo = svgElement("image", {
    x: 1000,
    y: 625,
    width: 200,
    height: 55,
    href: "/assets/eduvibe-slide-logo-white.png",
    preserveAspectRatio: "xMaxYMid meet",
  });
  svg.append(logo);
  wrappedText(svg, slide.title, 86, 196, "slide-title", 37, 55);

  const bullets = slide.bullets.slice(0, 5);
  const lineGap = bullets.length > 3 ? 78 : 91;
  bullets.forEach((bullet, index) => {
    const y = 298 + index * lineGap;
    svg.append(svgElement("circle", { cx: 103, cy: y - 9, r: 7, fill: "#b9b1ff" }));
    wrappedText(svg, bullet, 128, y, "slide-bullet", 66, 37);
  });
  svg.append(svgElement("text", { x: 940, y: 666, class: "slide-counter", "text-anchor": "end" }, `${slideNumber} / ${total}`));
  return svg;
}
