/* User-triggered micro-interactions: card cursor glow, button press feedback,
 * the scan progress line, and the audit verify icon.
 *
 * The glow and press-feedback listeners are attached once, on `document`,
 * using event delegation - so they keep working after app.js tears down and
 * rebuilds cards/buttons on every render, with nothing to clean up.
 */
(function () {
  'use strict';

  var FM = window.FimMotion;

  /* ---- card cursor-following glow --------------------------------- */
  function initCardGlow() {
    if (FM.prefersReducedMotion()) return; // static hover glow (CSS) is enough
    var selector = '.card, .section-card, .kpi-card, .alert-card';
    var current = null;
    var setX = null;
    var setY = null;

    document.addEventListener('pointermove', function (ev) {
      var el = ev.target.closest ? ev.target.closest(selector) : null;
      if (el !== current) {
        if (current) current.classList.remove('glow-active');
        current = el;
        if (current) {
          current.classList.add('glow-active');
          if (window.gsap) {
            setX = window.gsap.quickSetter(current, '--mx', 'px');
            setY = window.gsap.quickSetter(current, '--my', 'px');
          } else {
            setX = setY = null;
          }
        }
      }
      if (!current) return;
      var rect = current.getBoundingClientRect();
      var x = ev.clientX - rect.left;
      var y = ev.clientY - rect.top;
      if (setX) { setX(x); setY(y); } else {
        current.style.setProperty('--mx', x + 'px');
        current.style.setProperty('--my', y + 'px');
      }
    }, { passive: true });
  }

  /* ---- button / chip press feedback -------------------------------- */
  function initButtonFeedback() {
    if (!FM.gsapReady()) return;
    var selector = '.btn, .icon-btn, .chip, .side-tab';
    var pressed = null;

    function release() {
      if (!pressed) return;
      window.gsap.to(pressed, { scale: 1, duration: 0.22, ease: FM.EASE.pop });
      pressed = null;
    }

    document.addEventListener('pointerdown', function (ev) {
      var el = ev.target.closest ? ev.target.closest(selector) : null;
      if (!el || el.disabled) return;
      pressed = el;
      window.gsap.to(el, { scale: 0.96, duration: 0.12, ease: 'power1.out' });
    });
    document.addEventListener('pointerup', release);
    document.addEventListener('pointercancel', release);
  }

  /* ---- scan progress line ------------------------------------------- */
  function scanStart(button) {
    var line = document.getElementById('scan-line');
    if (line) line.classList.add('is-active');
    if (button) button.classList.add('is-loading');
  }

  function scanEnd(button, ok) {
    var line = document.getElementById('scan-line');
    if (line) {
      line.classList.remove('is-active');
      line.classList.add(ok === false ? 'is-error' : 'is-done');
      window.setTimeout(function () { line.classList.remove('is-done', 'is-error'); }, 500);
    }
    if (button) button.classList.remove('is-loading');
  }

  /* ---- audit verify icon ---------------------------------------------- */
  function verifyStart(iconEl) {
    if (!iconEl) return;
    iconEl.classList.remove('is-ok', 'is-bad');
    iconEl.classList.add('is-checking');
  }

  function verifyResult(iconEl, ok) {
    if (!iconEl) return;
    iconEl.classList.remove('is-checking');
    iconEl.classList.add(ok ? 'is-ok' : 'is-bad');
    if (!FM.gsapReady()) return;
    var gsap = window.gsap;
    if (ok) {
      var checkPath = iconEl.querySelector('svg path');
      if (checkPath && checkPath.getTotalLength) {
        var len = checkPath.getTotalLength();
        checkPath.style.strokeDasharray = len;
        checkPath.style.strokeDashoffset = len;
        gsap.fromTo(iconEl, { scale: 0.85, opacity: 0.6 }, { scale: 1, opacity: 1, duration: 0.25, ease: FM.EASE.out });
        gsap.to(checkPath, { strokeDashoffset: 0, duration: 0.45, ease: FM.EASE.out, delay: 0.05 });
        return;
      }
    }
    gsap.fromTo(iconEl, { scale: 0.85 }, { scale: 1, duration: 0.35, ease: FM.EASE.pop });
  }

  FM.initCardGlow = initCardGlow;
  FM.initButtonFeedback = initButtonFeedback;
  FM.scanStart = scanStart;
  FM.scanEnd = scanEnd;
  FM.verifyStart = verifyStart;
  FM.verifyResult = verifyResult;
})();
