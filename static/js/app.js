/* ПожЭксперт+ — интерактивные элементы интерфейса (без внешних библиотек). */
(function () {
  "use strict";

  function store(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      window.localStorage.setItem(key, value);
    } catch (e) { return null; }
  }

  /* ---------- тема ---------- */
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    document.querySelectorAll("[data-theme-label]").forEach(function (el) {
      el.textContent = theme === "dark" ? "Светлая тема" : "Тёмная тема";
    });
  }
  applyTheme(store("pe-theme") || "light");
  document.addEventListener("click", function (e) {
    var t = e.target.closest("[data-toggle-theme]");
    if (!t) return;
    e.preventDefault();
    var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    store("pe-theme", next);
    applyTheme(next);
  });

  /* ---------- боковое меню на узком экране, меню профиля ---------- */
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-menu-toggle]")) {
      document.body.classList.toggle("nav-open");
      return;
    }
    var pm = e.target.closest("[data-profile-toggle]");
    document.querySelectorAll(".profile-menu").forEach(function (m) {
      if (pm && m.contains(pm)) m.classList.toggle("open"); else m.classList.remove("open");
    });
    if (document.body.classList.contains("nav-open") && !e.target.closest(".sidebar")) {
      document.body.classList.remove("nav-open");
    }
  });

  /* ---------- показать / скрыть пароль ---------- */
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-toggle-password]");
    if (!b) return;
    var input = document.getElementById(b.getAttribute("data-toggle-password"));
    if (!input) return;
    var show = input.type === "password";
    input.type = show ? "text" : "password";
    b.textContent = show ? "Скрыть" : "Показать";
  });

  /* ---------- кликабельные строки таблиц ---------- */
  document.addEventListener("click", function (e) {
    var row = e.target.closest("tr[data-href]");
    if (!row || e.target.closest("a, button, input, select, label, form")) return;
    window.location = row.getAttribute("data-href");
  });
  document.addEventListener("keydown", function (e) {
    var row = e.target.closest && e.target.closest("tr[data-href]");
    if (row && e.key === "Enter") window.location = row.getAttribute("data-href");
  });

  /* ---------- подтверждение значимых действий ---------- */
  var dlg = document.getElementById("confirm-dialog");
  var pendingForm = null;
  document.addEventListener("submit", function (e) {
    var form = e.target;
    var submitter = e.submitter;
    var text = (submitter && submitter.getAttribute("data-confirm")) || form.getAttribute("data-confirm");
    if (!text || form.dataset.confirmed === "1") return;
    if (!form.checkValidity()) return;
    e.preventDefault();
    if (!dlg || typeof dlg.showModal !== "function") {
      if (window.confirm(text)) { form.dataset.confirmed = "1"; submitWith(form, submitter); }
      return;
    }
    pendingForm = { form: form, submitter: submitter };
    dlg.querySelector("[data-confirm-title]").textContent =
      (submitter && submitter.getAttribute("data-confirm-title")) || form.getAttribute("data-confirm-title") || "Подтвердите действие";
    dlg.querySelector("[data-confirm-text]").textContent = text;
    dlg.showModal();
  }, true);
  function submitWith(form, submitter) {
    if (submitter && submitter.name) {
      var h = document.createElement("input");
      h.type = "hidden"; h.name = submitter.name; h.value = submitter.value;
      form.appendChild(h);
    }
    form.dataset.confirmed = "1";
    form.submit();
  }
  if (dlg) {
    dlg.querySelector("[data-confirm-ok]").addEventListener("click", function () {
      dlg.close();
      if (pendingForm) submitWith(pendingForm.form, pendingForm.submitter);
    });
    dlg.querySelector("[data-confirm-cancel]").addEventListener("click", function () { dlg.close(); pendingForm = null; });
  }

  /* ---------- проверка файла ДО загрузки ---------- */
  var cfg = document.body.dataset;
  var allowed = (cfg.allowedExt || "pdf,docx,xlsx,dwg,dxf").split(",");
  var maxMb = parseInt(cfg.maxMb || "25", 10);
  function checkFile(input) {
    var box = input.closest("[data-upload]");
    var msg = box ? box.querySelector(".file-msg") : null;
    var form = input.form;
    var submit = form ? form.querySelector("[data-upload-submit]") : null;
    if (!input.files || !input.files.length) { if (msg) { msg.textContent = ""; } return; }
    var f = input.files[0];
    var ext = (f.name.split(".").pop() || "").toLowerCase();
    var err = "";
    if (allowed.indexOf(ext) === -1) {
      err = "Файл не загружен: формат ." + ext + " не поддерживается. Выберите " + allowed.join(", ").toUpperCase() + ".";
    } else if (f.size > maxMb * 1024 * 1024) {
      err = "Превышен максимальный размер: " + (f.size / 1048576).toFixed(1) + " МБ при лимите " + maxMb + " МБ.";
    }
    if (msg) {
      msg.className = "file-msg " + (err ? "bad" : "good");
      msg.textContent = err || ("Выбран файл: " + f.name + " (" + (f.size / 1048576).toFixed(2) + " МБ)");
    }
    if (submit) submit.disabled = !!err;
    if (err) input.value = "";
  }
  document.addEventListener("change", function (e) {
    if (e.target.matches("[data-upload] input[type=file]")) checkFile(e.target);
  });
  document.querySelectorAll("[data-upload] .dropzone").forEach(function (zone) {
    var input = zone.querySelector("input[type=file]");
    ["dragenter", "dragover"].forEach(function (ev) {
      zone.addEventListener(ev, function (e) { e.preventDefault(); zone.classList.add("drag"); });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      zone.addEventListener(ev, function (e) { e.preventDefault(); zone.classList.remove("drag"); });
    });
    zone.addEventListener("drop", function (e) {
      if (input && e.dataTransfer.files.length) { input.files = e.dataTransfer.files; checkFile(input); }
    });
  });

  /* ---------- диалог назначения: причина при перегрузке ---------- */
  document.querySelectorAll("[data-assign-form]").forEach(function (form) {
    var reasonBox = form.querySelector("[data-reason-box]");
    function update() {
      var checked = form.querySelector("input[name=executor]:checked");
      var over = checked && checked.getAttribute("data-overloaded") === "1";
      if (reasonBox) {
        reasonBox.style.display = over ? "block" : "none";
        var ta = reasonBox.querySelector("textarea");
        if (ta) ta.required = !!over;
      }
    }
    form.addEventListener("change", update);
    update();
  });

  /* ---------- ИИ: использовать как черновик ---------- */
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-copy-draft]");
    if (!b) return;
    var text = b.getAttribute("data-copy-draft");
    store("pe-ai-draft", text);
    var done = function () {
      b.textContent = "Скопировано — вставьте в форму замечания";
      setTimeout(function () { b.textContent = "Использовать как черновик"; }, 3500);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, done);
    } else { done(); }
  });
  // если в форме замечания пусто, а в браузере есть черновик из помощника — предложить его
  document.querySelectorAll("[data-draft-target]").forEach(function (ta) {
    var draft = store("pe-ai-draft");
    var holder = document.querySelector("[data-draft-offer]");
    if (draft && !ta.value && holder) {
      holder.style.display = "flex";
      holder.querySelector("button").addEventListener("click", function () {
        ta.value = draft; ta.focus(); holder.style.display = "none"; store("pe-ai-draft", "");
      });
    }
  });

  /* ---------- открыть форму возврата ---------- */
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-open-return]");
    if (!b) return;
    var box = document.getElementById("return-box");
    if (box) { box.style.display = "block"; box.scrollIntoView({ behavior: "smooth", block: "start" });
      var first = box.querySelector("textarea, input, select"); if (first) first.focus(); }
  });

  /* ---------- демо-входы на странице логина ---------- */
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-demo-login]");
    if (!b) return;
    var email = document.getElementById("id_email");
    var pwd = document.getElementById("id_password");
    if (email && pwd) { email.value = b.getAttribute("data-demo-login"); pwd.value = b.getAttribute("data-demo-pass"); pwd.form.submit(); }
  });

  /* ---------- сообщения исчезают сами ---------- */
  setTimeout(function () {
    document.querySelectorAll(".alert[data-autohide]").forEach(function (a) { a.style.transition = "opacity .4s"; a.style.opacity = "0"; setTimeout(function () { a.remove(); }, 450); });
  }, 6000);
})();
