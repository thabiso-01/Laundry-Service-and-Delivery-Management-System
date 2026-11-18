// Runs before the page draws so dark mode doesn't flash white.
// Saved choice wins; otherwise follow the device setting.
(function () {
  var saved = null;
  try { saved = localStorage.getItem("lc-theme"); } catch (e) {}
  var dark = saved ? saved === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.classList.toggle("dark", dark);
  var meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", dark ? "#0b1121" : "#4361ee");
})();
