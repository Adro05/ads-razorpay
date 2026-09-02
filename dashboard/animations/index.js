/* Bootstrap: wires the one-time, document-level interactions once the DOM
 * exists. Everything per-render (counters, chart reveals, panel transitions)
 * is called directly by app.js at the moment it builds that content.
 */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    if (window.FimMotion.initCardGlow) window.FimMotion.initCardGlow();
    if (window.FimMotion.initButtonFeedback) window.FimMotion.initButtonFeedback();
  });
})();
