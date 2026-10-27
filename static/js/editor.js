// Espace bureau : barre d'outils Markdown, aperçu, téléversement d'images, aperçu de l'affiche.
(function () {
  "use strict";

  var form = document.querySelector("form[data-urls]");
  if (!form) return;
  var urls = JSON.parse(form.dataset.urls);
  var csrf = form.querySelector("[name=csrfmiddlewaretoken]").value;

  function post(url, body) {
    return fetch(url, { method: "POST", body: body, headers: { "X-CSRFToken": csrf }, credentials: "same-origin" })
      .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); });
  }

  // Entoure la sélection, ou insère un modèle si rien n'est sélectionné.
  function wrap(area, before, after, placeholder) {
    var start = area.selectionStart, end = area.selectionEnd;
    var selected = area.value.slice(start, end) || placeholder;
    area.setRangeText(before + selected + after, start, end, "end");
    if (!area.value.slice(start, end).length || selected === placeholder) {
      area.setSelectionRange(start + before.length, start + before.length + selected.length);
    }
    area.focus();
    area.dispatchEvent(new Event("input"));
  }

  function linePrefix(area, prefix) {
    var start = area.value.lastIndexOf("\n", area.selectionStart - 1) + 1;
    area.setRangeText(prefix, start, start, "end");
    area.focus();
  }

  var actions = {
    bold: function (a) { wrap(a, "**", "**", "texte en gras"); },
    italic: function (a) { wrap(a, "*", "*", "texte en italique"); },
    heading: function (a) { linePrefix(a, "## "); },
    list: function (a) { linePrefix(a, "- "); },
    link: function (a) {
      var url = window.prompt("Adresse du lien (https://…)", "https://");
      if (url) wrap(a, "[", "](" + url + ")", "texte du lien");
    },
    image: function (a, editor) { editor.querySelector(".md-file").click(); }
  };

  document.querySelectorAll("[data-md]").forEach(function (editor) {
    var area = editor.querySelector("textarea");
    var preview = editor.querySelector(".md-preview");
    var file = editor.querySelector(".md-file");

    editor.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-md-action]");
      if (btn) { actions[btn.dataset.mdAction](area, editor); return; }
      var tab = e.target.closest("[data-md-tab]");
      if (!tab) return;
      var showPreview = tab.dataset.mdTab === "preview";
      editor.querySelectorAll("[data-md-tab]").forEach(function (t) { t.setAttribute("aria-selected", String(t === tab)); });
      if (showPreview) {
        var body = new FormData();
        body.append("text", area.value);
        preview.innerHTML = "<p>Chargement de l'aperçu…</p>";
        post(urls.preview, body).then(function (res) {
          preview.innerHTML = res.data.html || "<p><em>Rien à afficher pour l'instant.</em></p>";
        });
      }
      preview.hidden = !showPreview;
      area.hidden = showPreview;
    });

    area.addEventListener("keydown", function (e) {
      if (!(e.ctrlKey || e.metaKey)) return;
      var key = e.key.toLowerCase();
      var map = { b: "bold", i: "italic", k: "link" };
      if (map[key]) { e.preventDefault(); actions[map[key]](area, editor); }
    });

    file.addEventListener("change", function () {
      if (!file.files.length) return;
      var body = new FormData();
      body.append("file", file.files[0]);
      editor.classList.add("is-busy");
      post(urls.upload, body).then(function (res) {
        editor.classList.remove("is-busy");
        file.value = "";
        if (!res.ok) { window.alert(res.data.error || "Téléversement impossible."); return; }
        var before = area.value.slice(0, area.selectionStart);
        // L'image va dans son propre paragraphe.
        var gap = !before || /\n\n$/.test(before) ? "" : (/\n$/.test(before) ? "\n" : "\n\n");
        wrap(area, gap + "![", "](" + res.data.url + ")\n\n", "description de l'image");
      }).catch(function () {
        editor.classList.remove("is-busy");
        window.alert("Téléversement impossible, vérifie ta connexion.");
      });
    });
  });

  // Aperçu immédiat de l'affiche ou de la couverture choisie.
  form.querySelectorAll("input[type=file][accept^='image']").forEach(function (input) {
    if (input.classList.contains("md-file")) return;
    var box = input.closest(".g-panel") && input.closest(".g-panel").querySelector("[data-poster-preview]");
    if (!box) return;
    input.addEventListener("change", function () {
      if (!input.files.length) return;
      var img = document.createElement("img");
      img.alt = "";
      img.src = URL.createObjectURL(input.files[0]);
      box.replaceChildren(img);
    });
  });

  // Prévenir avant de quitter une page modifiée sans l'enregistrer.
  var dirty = false;
  form.addEventListener("input", function () { dirty = true; });
  form.addEventListener("submit", function () { dirty = false; });
  window.addEventListener("beforeunload", function (e) { if (dirty) { e.preventDefault(); e.returnValue = ""; } });
})();

// Diffusion : nombre de caractères sous chaque texte
(function () {
  "use strict";
  document.querySelectorAll("[data-count-for]").forEach(function (out) {
    var field = document.getElementById(out.dataset.countFor);
    if (!field) return;
    var update = function () { out.textContent = field.value.length; };
    field.addEventListener("input", update);
    update();
  });
})();
