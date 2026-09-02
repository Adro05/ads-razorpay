/* Chart and risk-visual animation - bar growth, sparkline draw-in, and a
 * one-shot highlight used when a scan brings in genuinely new numbers.
 *
 * Every helper here operates on DOM that app.js has already built with the
 * correct final values (widths, path data, text) - animation is layered on
 * top as a pure transform/stroke overlay, so a failure here can never make a
 * number wrong, only less decorated.
 */
(function () {
  'use strict';

  var FM = window.FimMotion;

  function growBars(container, selector) {
    if (!container) return;
    var fills = container.querySelectorAll(selector || '.chart-fill');
    if (!fills.length) return;
    if (!FM.gsapReady()) return;
    fills.forEach(function (fill) { fill.style.transformOrigin = 'left center'; });
    window.gsap.from(fills, {
      scaleX: 0, duration: FM.DUR.slow, ease: FM.EASE.soft, stagger: 0.05,
    });
  }

  function drawSparkline(container) {
    if (!container) return;
    var svg = container.querySelector('svg.trend-spark');
    if (!svg) return;
    var line = svg.querySelector('polyline');
    if (!line || !FM.gsapReady()) return;
    var dot = svg.querySelector('circle');
    var length = line.getTotalLength();
    line.style.strokeDasharray = length;
    line.style.strokeDashoffset = length;
    var gsap = window.gsap;
    var tl = gsap.timeline();
    if (dot) gsap.set(dot, { transformOrigin: '50% 50%', scale: 0, opacity: 0 });
    tl.to(line, { strokeDashoffset: 0, duration: 0.75, ease: FM.EASE.out });
    if (dot) tl.to(dot, { scale: 1, opacity: 1, duration: 0.28, ease: FM.EASE.pop }, '-=0.12');
  }

  // A single, restrained flash used right after a scan or dataset switch
  // brings in new figures - marks "this changed" without shouting about it.
  function flashUpdated(el) {
    if (!el || !FM.gsapReady()) return;
    window.gsap.fromTo(el,
      { boxShadow: '0 0 0 0 rgba(76,141,255,0)' },
      {
        boxShadow: '0 0 0 3px rgba(76,141,255,0.22)',
        duration: 0.3, ease: 'power1.out', yoyo: true, repeat: 1,
      });
  }

  FM.growBars = growBars;
  FM.drawSparkline = drawSparkline;
  FM.flashUpdated = flashUpdated;
})();
