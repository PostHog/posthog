// PostHog Loading Inspector — paste into browser DevTools console.
// Extracts script tags, init config, runtime state, and load method.
(() => {
  const scripts = [...document.querySelectorAll("script")];

  const posthogScripts = scripts.filter((s) => {
    const src = (s.src || "").toLowerCase();
    const id = (s.id || "").toLowerCase();
    const text = (s.textContent || "").toLowerCase();
    return (
      src.includes("posthog") ||
      src.includes("array.js") ||
      id.includes("posthog") ||
      text.includes("posthog") ||
      text.includes("phc_") ||
      text.includes("ph_init")
    );
  });

  const hasPosthogInitId = !!document.getElementById("posthog-init");

  const hasNextJsHydration = scripts.some((s) => {
    const text = s.textContent || "";
    return text.includes("self.__next_s") && text.includes("posthog");
  });

  let initConfig = null;
  for (const s of posthogScripts) {
    const text = s.textContent || "";
    const initMatch = text.match(
      /posthog\.init\s*\(\s*['"]([^'"]+)['"]\s*,\s*(\{[\s\S]*?\})\s*\)/
    );
    if (initMatch) {
      try {
        const configStr = initMatch[2]
          .replace(/(\w+)\s*:/g, '"$1":')
          .replace(/'/g, '"')
          .replace(/,\s*}/g, "}");
        const parsed = JSON.parse(configStr);
        initConfig = {
          api_key: initMatch[1],
          api_host: parsed.api_host || null,
          ui_host: parsed.ui_host || null,
          person_profiles: parsed.person_profiles || null,
          session_recording: parsed.session_recording || null,
        };
      } catch {
        initConfig = { api_key: initMatch[1], raw: initMatch[2] };
      }
      break;
    }
  }

  if (!initConfig && window.posthog && window.posthog.config) {
    const c = window.posthog.config;
    initConfig = {
      api_key: c.token || null,
      api_host: c.api_host || null,
      ui_host: c.ui_host || null,
      person_profiles: c.person_profiles || null,
      session_recording: c.session_recording || null,
    };
  }

  const arrayjsScript = posthogScripts.find(
    (s) => s.src && s.src.includes("array")
  );

  const runtimeDefined = typeof window.posthog !== "undefined";
  let runtimeState = { defined: runtimeDefined, loaded: false };
  if (runtimeDefined && window.posthog) {
    runtimeState = {
      defined: true,
      loaded: !!window.posthog.__loaded,
      distinct_id: window.posthog.get_distinct_id
        ? window.posthog.get_distinct_id()
        : null,
      config_api_host: window.posthog.config
        ? window.posthog.config.api_host
        : null,
    };
  }

  let loadMethod = "none";
  if (runtimeState.loaded && hasPosthogInitId) {
    loadMethod = "snippet";
  } else if (runtimeState.loaded) {
    loadMethod = "npm";
  }

  const result = {
    url: window.location.href,
    script_tag_count: posthogScripts.length,
    has_posthog_init_id: hasPosthogInitId,
    has_nextjs_hydration: hasNextJsHydration,
    init_config: initConfig,
    runtime_state: runtimeState,
    load_method: loadMethod,
    arrayjs_src: arrayjsScript ? arrayjsScript.src : null,
    script_details: posthogScripts.map((s) => ({
      id: s.id || null,
      src: s.src || null,
      type: s.type || null,
      text_preview: (s.textContent || "").slice(0, 200),
    })),
  };

  console.info(JSON.stringify(result, null, 2));
  return result;
})();
