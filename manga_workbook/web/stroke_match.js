/* Lenient stroke-order matcher for kanji/kana writing practice.
 *
 * Pure geometry, no dependencies — compares the learner's strokes (in drawing
 * order) against a reference (KanjiVG, also in stroke order). Both inputs are
 * polylines in normalised [0,1] cell coordinates. Lenient by design: it gates
 * on stroke ORDER + DIRECTION + rough position, and treats shape loosely, so
 * sloppy-but-correct handwriting passes while wrong-order/reversed strokes fail.
 *
 * Works in the browser (window.StrokeMatch) and in node (module.exports) so the
 * algorithm can be unit-tested without a DOM.
 */
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.StrokeMatch = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const N = 16;            // resample resolution per stroke
  const DIR_MIN = 0.25;    // min cos(angle) between user/ref direction (~<75 deg off)
  const END_MAX = 0.40;    // max endpoint offset (fraction of cell)
  const MEAN_MAX = 0.45;   // max mean point distance (loose shape check)

  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);

  function resample(pts, n = N) {
    if (!pts.length) return [];
    if (pts.length === 1) return Array.from({ length: n }, () => pts[0].slice());
    const cum = [0];
    for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + dist(pts[i - 1], pts[i]));
    const total = cum[cum.length - 1] || 1e-9;
    const out = [];
    for (let k = 0; k < n; k++) {
      const target = (total * k) / (n - 1);
      let i = 1;
      while (i < cum.length - 1 && cum[i] < target) i++;
      const seg = cum[i] - cum[i - 1] || 1e-9;
      const t = (target - cum[i - 1]) / seg;
      out.push([
        pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * t,
        pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * t,
      ]);
    }
    return out;
  }

  function direction(pts) {
    const a = pts[0], b = pts[pts.length - 1];
    const v = [b[0] - a[0], b[1] - a[1]];
    const m = Math.hypot(v[0], v[1]) || 1e-9;
    return [v[0] / m, v[1] / m];
  }

  function matchStroke(user, ref) {
    if (!user.length || !ref.length) return { pass: false, empty: true };
    const u = resample(user), r = resample(ref);
    const ud = direction(u), rd = direction(r);
    const dirDot = ud[0] * rd[0] + ud[1] * rd[1];     // 1 = same dir, -1 = reversed
    const startDist = dist(u[0], r[0]);
    const endDist = dist(u[u.length - 1], r[r.length - 1]);
    let s = 0;
    for (let i = 0; i < u.length; i++) s += dist(u[i], r[i]);
    const meanDist = s / u.length;
    const pass = dirDot > DIR_MIN && startDist < END_MAX && endDist < END_MAX && meanDist < MEAN_MAX;
    return { pass, dirDot, startDist, endDist, meanDist };
  }

  function matchChar(userStrokes, refStrokes) {
    const n = Math.max(userStrokes.length, refStrokes.length);
    const results = [];
    for (let i = 0; i < n; i++) {
      if (i >= userStrokes.length) results.push({ pass: false, missing: true });
      else if (i >= refStrokes.length) results.push({ pass: false, extra: true });
      else results.push(matchStroke(userStrokes[i], refStrokes[i]));
    }
    const correct = results.filter((x) => x.pass).length;
    const countOk = userStrokes.length === refStrokes.length;
    return { results, correct, total: refStrokes.length, countOk,
             done: countOk && correct === refStrokes.length };
  }

  return { resample, direction, matchStroke, matchChar, N, DIR_MIN, END_MAX, MEAN_MAX };
});
