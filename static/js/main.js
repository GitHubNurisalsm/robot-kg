/* Robot.KG.Baiel — клиентские улучшения. Сайт полностью работает и без JS. */
(function () {
  "use strict";

  // Мобильное меню
  var toggle = document.querySelector("[data-nav-toggle]");
  var nav = document.querySelector("[data-nav]");
  if (toggle && nav) {
    var setOpen = function (open) {
      nav.classList.toggle("is-open", open);
      toggle.setAttribute("aria-expanded", String(open));
    };
    toggle.addEventListener("click", function () {
      setOpen(toggle.getAttribute("aria-expanded") !== "true");
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") setOpen(false);
    });
  }

  // Тень у шапки при прокрутке
  var header = document.querySelector("[data-header]");
  if (header) {
    var onScroll = function () { header.classList.toggle("is-scrolled", window.scrollY > 8); };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  // Плавное появление блоков
  var items = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.15 });
    items.forEach(function (el) { io.observe(el); });
  } else {
    items.forEach(function (el) { el.classList.add("is-visible"); });
  }
})();

/* Корзина: изменение количества отправляет форму само (без JS работает кнопка «Обновить»). */
(function () {
  "use strict";
  document.querySelectorAll("form[data-autosubmit]").forEach(function (form) {
    var btn = form.querySelector("[data-autosubmit-btn]");
    var input = form.querySelector("input[name=quantity]");
    if (!btn || !input) return;
    btn.hidden = true;
    var submitted = false;
    input.addEventListener("change", function () {
      if (submitted || input.value === "" || !input.checkValidity()) {
        btn.hidden = false; // некорректный ввод — даём явную кнопку
        return;
      }
      submitted = true; // защита от двойной отправки
      form.submit();
    });
  });
})();

/* Аренда: выбор робота из карточки и предварительный расчёт. Итог считает сервер. */
(function () {
  "use strict";
  var form = document.querySelector("[data-rental-form]");
  var pricesEl = document.getElementById("rental-prices");
  if (!form || !pricesEl) return;
  var prices = JSON.parse(pricesEl.textContent);
  var product = form.querySelector("[name=product]");
  var start = form.querySelector("[name=start_date]");
  var end = form.querySelector("[name=end_date]");
  var box = form.querySelector("[data-estimate]");
  var out = form.querySelector("[data-estimate-value]");
  var fmt = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });

  function recalc() {
    var price = prices[product.value];
    var s = start.valueAsDate, e = end.valueAsDate;
    if (!price || !s || !e || e < s) { box.hidden = true; return; }
    var days = Math.round((e - s) / 86400000) + 1;
    out.textContent = fmt.format(price * days) + " сом за " + days + " дн.";
    box.hidden = false;
  }
  [product, start, end].forEach(function (el) { el.addEventListener("change", recalc); });
  start.addEventListener("change", function () { if (start.value) end.min = start.value; });

  document.querySelectorAll("[data-pick]").forEach(function (a) {
    a.addEventListener("click", function () {
      product.value = a.getAttribute("data-pick");
      recalc();
    });
  });

  form.addEventListener("submit", function () {
    var btn = form.querySelector("[data-submit]");
    if (btn) { btn.disabled = true; btn.textContent = "Отправляем…"; } // защита от двойного клика
  });
  // Возврат «назад» из bfcache не должен оставлять кнопку заблокированной.
  window.addEventListener("pageshow", function () {
    var btn = form.querySelector("[data-submit]");
    if (btn) { btn.disabled = false; btn.textContent = "Отправить заявку"; }
  });
  recalc();
})();

/* Формы с data-once: блокируем кнопку после отправки (двойной клик). */
(function () {
  "use strict";
  document.querySelectorAll("form[data-once]").forEach(function (form) {
    var btn = form.querySelector("[data-submit]");
    if (!btn) return;
    var label = btn.textContent;
    form.addEventListener("submit", function () { btn.disabled = true; btn.textContent = "Отправляем…"; });
    window.addEventListener("pageshow", function () { btn.disabled = false; btn.textContent = label; });
  });
})();

/* Оформление: поле адреса показываем только для доставки (без JS видно всегда). */
(function () {
  "use strict";
  var form = document.querySelector("[data-checkout]");
  if (!form) return;
  var wrap = form.querySelector("[data-address]");
  var radios = form.querySelectorAll("input[name=delivery_method]");
  function sync() {
    var checked = form.querySelector("input[name=delivery_method]:checked");
    wrap.hidden = !checked || checked.value !== "delivery";
  }
  radios.forEach(function (r) { r.addEventListener("change", sync); });
  sync();
})();

/* Дашборд: подсказки при наведении и фокусе (данные — через textContent, не innerHTML). */
(function () {
  "use strict";
  var tip = document.querySelector("[data-viz-tooltip]");
  if (!tip) return;
  var tipValue = tip.querySelector("strong"), tipLabel = tip.querySelector("span");

  function show(el, x, y) {
    tipValue.textContent = el.getAttribute("data-tip-value") || "";
    tipLabel.textContent = el.getAttribute("data-tip-label") || "";
    tip.style.left = x + "px";
    tip.style.top = y + "px";
    tip.hidden = false;
  }
  function anchor(el) {
    var r = el.getBoundingClientRect();
    return [r.left + r.width / 2, r.top];
  }
  function crosshair(el, on) {
    var svg = el.ownerSVGElement;
    if (!svg || !svg.hasAttribute("data-line-chart")) return;
    var line = svg.querySelector("[data-crosshair]"), dot = svg.querySelector("[data-hover-dot]");
    if (!on) { line.setAttribute("hidden", ""); dot.setAttribute("hidden", ""); return; }
    var cx = el.getAttribute("data-cx"), cy = el.getAttribute("data-cy");
    line.setAttribute("x1", cx); line.setAttribute("x2", cx); line.removeAttribute("hidden");
    dot.setAttribute("cx", cx); dot.setAttribute("cy", cy); dot.removeAttribute("hidden");
  }

  document.querySelectorAll("[data-tip-value]").forEach(function (el) {
    el.addEventListener("pointermove", function (e) { show(el, e.clientX, e.clientY); crosshair(el, true); });
    el.addEventListener("pointerleave", function () { tip.hidden = true; crosshair(el, false); });
    el.addEventListener("focus", function () { var a = anchor(el); show(el, a[0], a[1]); crosshair(el, true); });
    el.addEventListener("blur", function () { tip.hidden = true; crosshair(el, false); });
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") tip.hidden = true; });
})();
