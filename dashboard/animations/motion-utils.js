/* Motion foundation - shared namespace, reduced-motion detection, and a
 * change-aware number tween used by every metric on the dashboard.
 *
 * Loaded first, before every other animation module and before app.js.
 * Everything here is additive: if GSAP fails to load for any reason, every
 * function degrades to an instant, correct DOM update - the dashboard never
 * depends on animation to show correct data.
 */
(function () {
  'use strict';

  var reduceMotionQuery = window.matchMedia
    ? window.matchMedia('(prefers-reduced-motion: reduce)')
    : null;

  function prefersReducedMotion() {
    return !!(reduceMotionQuery && reduceMotionQuery.matches);
  }

  function gsapReady() {
    return !!window.gsap && !prefersReducedMotion();
  }

  var EASE = { out: 'power2.out', soft: 'power3.out', inOut: 'power2.inOut', pop: 'back.out(1.7)' };
  var DUR = { fast: 0.22, base: 0.42, slow: 0.65 };

  // Last-shown numeric value per stable key, so animateNumber only ever
  // tweens a genuine change - never replays 0 -> N on every re-render of an
  // unchanged value (e.g. typing in the employee search box).
  var lastValues = Object.create(null);

  function animateNumber(target, value, opts) {
    if (!target) return;
    opts = opts || {};
    var key = opts.key;
    var decimals = opts.decimals || 0;
    var prefix = opts.prefix || '';
    var suffix = opts.suffix || '';
    var duration = opts.duration || DUR.slow;
    var format = opts.format;

    function paint(v) {
      target.textContent = format ? format(v) : (prefix + v.toFixed(decimals) + suffix);
    }

    var numeric = Number(value);
    if (!isFinite(numeric)) {
      target.textContent = (value === undefined || value === null) ? '—' : String(value);
      if (key != null) delete lastValues[key];
      return;
    }

    var previous = key != null ? lastValues[key] : undefined;
    if (key != null) lastValues[key] = numeric;

    if (previous === numeric || !gsapReady()) {
      paint(numeric);
      return;
    }

    var from = previous === undefined ? 0 : previous;
    var obj = { v: from };
    window.gsap.to(obj, {
      v: numeric,
      duration: duration,
      ease: EASE.out,
      onUpdate: function () { paint(obj.v); },
      onComplete: function () { paint(numeric); },
    });
  }

  window.FimMotion = window.FimMotion || {};
  window.FimMotion.prefersReducedMotion = prefersReducedMotion;
  window.FimMotion.gsapReady = gsapReady;
  window.FimMotion.EASE = EASE;
  window.FimMotion.DUR = DUR;
  window.FimMotion.animateNumber = animateNumber;
})();
