// Minimal copy-to-clipboard for install command and code blocks.
document.addEventListener("click", function (e) {
  var btn = e.target.closest(".copy");
  if (!btn) return;

  var text = btn.getAttribute("data-copy");
  if (!text) {
    var targetId = btn.getAttribute("data-copy-target");
    var el = targetId && document.getElementById(targetId);
    if (el) text = el.innerText;
  }
  if (!text) return;

  var done = function () {
    var label = btn.textContent;
    btn.textContent = "Copied";
    setTimeout(function () { btn.textContent = label; }, 1200);
  };

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done, done);
  } else {
    var ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (err) {}
    document.body.removeChild(ta);
    done();
  }
});
