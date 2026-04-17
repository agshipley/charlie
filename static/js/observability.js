/**
 * Charlie client-side error capture.
 * Loaded in <head> before all other scripts so it catches errors in
 * subsequent scripts. POSTs to /api/client-error.
 *
 * Client-side debounce: if the same message fires > 10 times in 10s,
 * stop sending until the burst subsides.
 * Server-side rate limit: backend drops if same source+line+col fires
 * > 50 times in 5 min.
 */
(function () {
  'use strict';

  var DEBOUNCE_MAX = 10;
  var DEBOUNCE_WINDOW = 10000; // ms

  // message -> { count, since }
  var _sent = {};

  function shouldSend(message) {
    var now = Date.now();
    var entry = _sent[message];
    if (!entry || now - entry.since > DEBOUNCE_WINDOW) {
      _sent[message] = { count: 1, since: now };
      return true;
    }
    entry.count += 1;
    return entry.count <= DEBOUNCE_MAX;
  }

  function reportError(payload) {
    try {
      var msg = payload.message || '';
      if (!shouldSend(msg)) return;

      var body = JSON.stringify({
        message:    msg.substring(0, 500),
        source:     payload.source    || '',
        lineno:     payload.lineno    || null,
        colno:      payload.colno     || null,
        stack:      (payload.stack || '').substring(0, 2000),
        url:        window.location.href,
        user_agent: navigator.userAgent,
        event_type: payload.event_type || 'error',
        context:    payload.context   || {}
      });

      fetch('/api/client-error', {
        method:    'POST',
        headers:   { 'Content-Type': 'application/json' },
        body:      body,
        keepalive: true
      });
    } catch (e) {
      // swallow — the error reporter must never throw
    }
  }

  // Global JS errors
  window.addEventListener('error', function (event) {
    reportError({
      message:    event.message,
      source:     event.filename,
      lineno:     event.lineno,
      colno:      event.colno,
      stack:      event.error && event.error.stack ? event.error.stack : '',
      event_type: 'error'
    });
  });

  // Unhandled promise rejections
  window.addEventListener('unhandledrejection', function (event) {
    reportError({
      message:    String(event.reason),
      stack:      event.reason && event.reason.stack ? event.reason.stack : '',
      event_type: 'unhandledrejection'
    });
  });

  // Manual reporting
  window.reportClientError = function (message, context) {
    reportError({
      message:    message,
      event_type: 'manual',
      context:    context || {}
    });
  };
})();
