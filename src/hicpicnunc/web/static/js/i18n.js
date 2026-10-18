// Strings built in JavaScript, from the per-language table the page injects as window.__I18N__.
// Same catalog format as the server: "{name}" placeholders, plurals keyed by CLDR category.
window.i18n = (function () {
  const data = window.__I18N__ || { lang: "en", strings: {} };
  const pluralRules = new Intl.PluralRules(data.lang);

  function format(text, vars) {
    return text.replace(/\{(\w+)\}/g, (match, name) =>
      vars && name in vars ? String(vars[name]) : match
    );
  }

  function t(key, vars) {
    const message = data.strings[key];
    return format(typeof message === "string" ? message : key, vars);
  }

  function tn(key, count, vars) {
    const forms = data.strings[key] || {};
    const text = forms[pluralRules.select(count)] || forms.other || key;
    return format(text, { count, ...vars });
  }

  return { t, tn };
})();
