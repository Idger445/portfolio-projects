"use strict";

const form = document.querySelector("#equation-form");
const input = document.querySelector("#equation");
const errorBox = document.querySelector("#solve-error");
const kind = document.querySelector("#solution-kind");
const roots = document.querySelector("#solution-roots");
const discriminant = document.querySelector("#discriminant");
const formula = document.querySelector("#formula");
const legend = document.querySelector("#legend");
const canvas = document.querySelector("#plot");
const context = canvas.getContext("2d");
const zoomIn = document.querySelector("#zoom-in");
const zoomOut = document.querySelector("#zoom-out");
const zoomReset = document.querySelector("#zoom-reset");
const minScale = .25;
const maxScale = 4;

let solution = null;
let activeRequest = null;
let scale = 1;

function tickValues(min, max, count) {
  const spacing = (max - min) / count;
  const exponent = 10 ** Math.floor(Math.log10(spacing));
  const ratio = spacing / exponent;
  const step = [1, 2, 2.5, 5, 10].find(value => value >= ratio) * exponent;
  const values = [];
  for (let index = Math.ceil(min / step); index <= Math.floor(max / step); index++) {
    values.push(index * step);
  }
  return values;
}

function tickLabel(value) {
  if (value !== 0 && (Math.abs(value) >= 100000 || Math.abs(value) < .001)) {
    return value.toExponential(1).replace(".0e", "e").replace("e+", "e");
  }
  return String(Number(value.toPrecision(6)));
}

function line(x1, y1, x2, y2) {
  context.beginPath();
  context.moveTo(x1, y1);
  context.lineTo(x2, y2);
  context.stroke();
}

function drawPlot() {
  const bounds = canvas.getBoundingClientRect();
  const pixelRatio = window.devicePixelRatio;
  canvas.width = Math.round(bounds.width * pixelRatio);
  canvas.height = Math.round(bounds.height * pixelRatio);
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  if (!solution || bounds.width < 110 || bounds.height < 100) {
    return;
  }

  const [a, b, c] = solution.coefficients;
  const value = x => (a * x + b) * x + c;
  const points = [0, ...solution.roots.map(root => root.x)];
  if (solution.vertex !== null) {
    points.push(solution.vertex);
  }
  const leftmost = Math.min(...points);
  const rightmost = Math.max(...points);
  const center = (leftmost + rightmost) / 2;
  const halfWidth = Math.max(4, (rightmost - leftmost) * .7) / scale;
  const xMin = center - halfWidth;
  const xMax = center + halfWidth;
  const samples = [0, value(xMin), value(xMax)];
  if (solution.vertex >= xMin && solution.vertex <= xMax && a !== 0) {
    samples.push(value(solution.vertex));
  }
  const low = Math.min(...samples);
  const high = Math.max(...samples);
  const verticalPadding = high === low ? 2 : (high - low) * .12;
  const yMin = low - verticalPadding;
  const yMax = high + verticalPadding;

  const left = 58;
  const top = 17;
  const right = bounds.width - 17;
  const bottom = bounds.height - 30;
  const px = x => left + (x - xMin) / (xMax - xMin) * (right - left);
  const py = y => bottom - (y - yMin) / (yMax - yMin) * (bottom - top);

  context.font = "11px Consolas, monospace";
  context.strokeStyle = "#dce7df";
  context.fillStyle = "#4d6258";
  context.textAlign = "center";
  context.textBaseline = "top";
  for (const x of tickValues(xMin, xMax, Math.max(2, Math.floor((right - left) / 64)))) {
    const position = px(x);
    line(position, top, position, bottom);
    context.fillText(tickLabel(x), position, bottom + 6);
  }
  context.textAlign = "right";
  context.textBaseline = "middle";
  for (const y of tickValues(yMin, yMax, Math.floor((bottom - top) / 44))) {
    const position = py(y);
    line(left, position, right, position);
    context.fillText(tickLabel(y), left - 7, position);
  }

  context.strokeStyle = "#739285";
  line(left, py(0), right, py(0));
  context.fillText("x", right - 2, py(0) - 10);
  if (xMin <= 0 && xMax >= 0) {
    line(px(0), top, px(0), bottom);
    context.textAlign = "left";
    context.fillText("y", Math.min(px(0) + 7, right - 8), top + 7);
  }

  context.save();
  context.beginPath();
  context.rect(left - 1, top - 1, right - left + 2, bottom - top + 2);
  context.clip();
  context.strokeStyle = "#176b4c";
  context.lineWidth = 2.5;
  context.beginPath();
  context.moveTo(left, py(value(xMin)));
  for (let step = 1; step <= 300; step++) {
    const x = xMin + (xMax - xMin) * step / 300;
    context.lineTo(px(x), py(value(x)));
  }
  context.stroke();

  for (const root of solution.roots) {
    if (root.x < xMin || root.x > xMax) {
      continue;
    }
    context.beginPath();
    context.arc(px(root.x), py(0), 5, 0, Math.PI * 2);
    context.strokeStyle = "#fbfcfb";
    context.lineWidth = 2;
    context.stroke();
    context.fillStyle = "#ab4925";
    context.fill();
  }
  context.restore();
}

function updatePlotControls() {
  zoomIn.disabled = !solution || scale >= maxScale;
  zoomOut.disabled = !solution || scale <= minScale;
  zoomReset.disabled = !solution || scale === 1;
  zoomReset.textContent = Math.round(scale * 100) + "%";
  drawPlot();
}

function showSolution(data) {
  solution = data;
  scale = 1;
  kind.textContent = data.kind;
  roots.textContent = data.result;
  discriminant.hidden = data.discriminant === null;
  discriminant.textContent = "Дискриминант D = " + (data.discriminant ?? "");
  formula.textContent = "y = " + data.expression;
  legend.hidden = !data.roots.length;
  canvas.setAttribute("aria-label", "График y = " + data.expression + ". " + data.kind + ". " + data.result);
  updatePlotControls();
}

async function submitEquation() {
  activeRequest?.abort();
  const request = new AbortController();
  activeRequest = request;
  errorBox.hidden = true;
  input.removeAttribute("aria-invalid");
  try {
    const response = await fetch("/api/solve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ equation: input.value }),
      signal: request.signal,
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Не удалось обработать уравнение.");
    }
    if (activeRequest === request) {
      showSolution(data);
    }
  } catch (error) {
    if (activeRequest !== request) {
      return;
    }
    errorBox.textContent = error instanceof TypeError ? "Проверьте, запущена ли программа." : error.message;
    errorBox.hidden = false;
    input.setAttribute("aria-invalid", "true");
    solution = null;
    scale = 1;
    kind.textContent = "Ожидаем уравнение";
    roots.textContent = "";
    discriminant.hidden = true;
    formula.textContent = "y = …";
    legend.hidden = true;
    canvas.setAttribute("aria-label", "Ожидаем уравнение");
    updatePlotControls();
  }
}

form.addEventListener("submit", event => {
  event.preventDefault();
  submitEquation();
});

document.querySelectorAll(".example-list button").forEach(button => {
  button.addEventListener("click", () => {
    input.value = button.value;
    submitEquation();
  });
});

zoomOut.addEventListener("click", () => {
  scale = Math.max(minScale, scale / 1.25);
  updatePlotControls();
});
zoomIn.addEventListener("click", () => {
  scale = Math.min(maxScale, scale * 1.25);
  updatePlotControls();
});
zoomReset.addEventListener("click", () => {
  scale = 1;
  updatePlotControls();
});
new ResizeObserver(drawPlot).observe(canvas);
submitEquation();
