/* Page-load reveal and tab (panel) transitions.
 *
 * Both are purely cosmetic wrappers around DOM state that app.js already
 * controls correctly - which panel carries `.active`, when a tab's data
 * loads - so navigation behaviour is identical with or without GSAP.
 */
(function () {
  'use strict';

  var FM = window.FimMotion;

  function runPageLoad() {
    if (!FM.gsapReady()) return;
    var gsap = window.gsap;
    var DUR = FM.DUR;

    var tl = gsap.timeline({ defaults: { ease: FM.EASE.out } });
    tl.from('.sidebar', { opacity: 0, x: -18, duration: DUR.slow })
      .from('.topbar', { opacity: 0, y: -10, duration: DUR.base }, '-=0.32')
      .from('.scan-line', { opacity: 0, duration: DUR.fast }, '-=0.2');
  }

  function revealChildren(container, selector, opts) {
    if (!container || !FM.gsapReady()) return;
    var targets = selector ? container.querySelectorAll(selector) : container.children;
    if (!targets || !targets.length) return;
    window.gsap.from(targets, Object.assign({
      opacity: 0, y: 12, duration: FM.DUR.base, ease: FM.EASE.out, stagger: 0.05,
    }, opts || {}));
  }

  function transitionPanel(oldPanel, newPanel) {
    if (!newPanel) return;
    if (!FM.gsapReady()) {
      if (oldPanel && oldPanel !== newPanel) oldPanel.classList.remove('active');
      newPanel.classList.add('active');
      return;
    }
    var gsap = window.gsap;
    var DUR = FM.DUR;

    if (oldPanel && oldPanel !== newPanel) {
      gsap.to(oldPanel, {
        opacity: 0, y: -6, duration: DUR.fast, ease: 'power1.in',
        onComplete: function () {
          oldPanel.classList.remove('active');
          gsap.set(oldPanel, { clearProps: 'opacity,transform' });
          newPanel.classList.add('active');
          gsap.fromTo(newPanel, { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: DUR.base, ease: FM.EASE.out });
        },
      });
    } else {
      newPanel.classList.add('active');
      gsap.fromTo(newPanel, { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: DUR.base, ease: FM.EASE.out });
    }
  }

  document.addEventListener('DOMContentLoaded', runPageLoad);

  FM.revealChildren = revealChildren;
  FM.transitionPanel = transitionPanel;
})();
