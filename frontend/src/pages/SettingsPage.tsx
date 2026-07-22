import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Sun, Moon, Monitor } from "lucide-react";
import { cn, apiFetch } from "@/lib/utils";
import {
  getConfig,
  getConfigOptions,
  invalidateConfigCache,
} from "@/lib/app-data";
import type { ConfigOptionsResponse } from "@/lib/config-options";
import { LANGUAGE_OPTIONS, type Language } from "@/lib/i18n";
import { useI18n } from "@/lib/i18n-context";
import { Button } from "@/components/ui/button";
import { Save } from "lucide-react";
import Settings from "@/pages/Settings";

/* ------------------------------------------------------------------ */
/*  Tab definitions                                                    */
/* ------------------------------------------------------------------ */
/*  Reusable setting group card                                        */
/* ------------------------------------------------------------------ */
function SettingGroup({
  title,
  desc,
  children,
}: {
  title: string;
  desc?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-[15px] font-semibold text-[var(--text-primary)]">
          {title}
        </h3>
        {desc && (
          <p className="mt-0.5 text-[13px] text-[var(--text-muted)]">{desc}</p>
        )}
      </div>
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Theme selector                                                     */
/* ------------------------------------------------------------------ */
const THEME_OPTIONS = [
  { value: "light", labelKey: "settings.theme.light", icon: Sun },
  { value: "dark", labelKey: "settings.theme.dark", icon: Moon },
  { value: "system", labelKey: "settings.theme.system", icon: Monitor },
] as const;

function ThemeSelector({
  theme,
  setTheme,
}: {
  theme: string;
  setTheme: (t: string) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="inline-flex rounded-xl border border-[var(--border)] bg-[var(--chip-bg)] p-1">
      {THEME_OPTIONS.map(({ value, labelKey, icon: Icon }) => (
        <button
          key={value}
          onClick={() => setTheme(value)}
          className={cn(
            "inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-sm font-medium transition-all",
            theme === value
              ? "bg-[var(--accent)] text-white shadow-sm"
              : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
          )}
        >
          <Icon className="h-4 w-4" />
          {t(labelKey)}
        </button>
      ))}
    </div>
  );
}

function LanguageSelector({
  language,
  setLanguage,
}: {
  language: Language;
  setLanguage: (language: Language) => void;
}) {
  return (
    <div className="inline-flex rounded-xl border border-[var(--border)] bg-[var(--chip-bg)] p-1">
      {LANGUAGE_OPTIONS.map(({ value, label }) => (
        <button
          key={value}
          onClick={() => setLanguage(value)}
          className={cn(
            "inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-sm font-medium transition-all",
            language === value
              ? "bg-[var(--accent)] text-white shadow-sm"
              : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  General tab — theme + default register strategy + browser reuse    */
/* ------------------------------------------------------------------ */
function GeneralTab({
  theme,
  setTheme,
}: {
  theme: string;
  setTheme: (t: string) => void;
}) {
  const { t, language, setLanguage } = useI18n();
  const [form, setForm] = useState<Record<string, string>>({});
  const [configOptions, setConfigOptions] =
    useState<ConfigOptionsResponse | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    Promise.all([
      getConfig().catch(() => ({})),
      getConfigOptions().catch(() => null),
    ]).then(([cfg, opts]) => {
      setForm(cfg);
      if (opts) setConfigOptions(opts);
    });
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      await apiFetch("/config", {
        method: "PUT",
        body: JSON.stringify({ data: form }),
      });
      invalidateConfigCache();
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  };

  const executorOptions = configOptions?.executor_options || [];
  const identityOptions = configOptions?.identity_mode_options || [];
  return (
    <div className="space-y-8">
      <SettingGroup
        title={t("settings.theme.title")}
        desc={t("settings.theme.desc")}
      >
        <ThemeSelector theme={theme} setTheme={setTheme} />
      </SettingGroup>

      <SettingGroup title={t("language.title")} desc={t("language.desc")}>
        <LanguageSelector language={language} setLanguage={setLanguage} />
      </SettingGroup>

      <div className="border-t border-[var(--border)]" />

      <SettingGroup
        title={t("settings.defaultStrategy.title")}
        desc={t("settings.defaultStrategy.desc")}
      >
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] divide-y divide-[var(--border)]/50">
          <SettingRow label={t("settings.defaultIdentity")}>
            <select
              value={
                form.default_identity_provider ||
                identityOptions[0]?.value ||
                ""
              }
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  default_identity_provider: e.target.value,
                }))
              }
              className="control-surface appearance-none"
            >
              {identityOptions.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </SettingRow>
          <SettingRow label={t("settings.defaultExecutor")}>
            <select
              value={form.default_executor || executorOptions[0]?.value || ""}
              onChange={(e) =>
                setForm((f) => ({ ...f, default_executor: e.target.value }))
              }
              className="control-surface appearance-none"
            >
              {executorOptions.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </SettingRow>
        </div>
      </SettingGroup>

      <Button onClick={save} disabled={saving} className="w-full">
        <Save className="mr-2 h-4 w-4" />
        {saved
          ? `${t("common.saved")} ✓`
          : saving
            ? t("common.saving")
            : t("common.saveSettings")}
      </Button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Setting row — label + control                                      */
/* ------------------------------------------------------------------ */
function SettingRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4 px-4 py-3.5">
      <label className="shrink-0 text-sm font-medium text-[var(--text-secondary)]">
        {label}
      </label>
      <div className="min-w-0 max-w-[320px] flex-1">{children}</div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  About tab                                                          */
/* ------------------------------------------------------------------ */
export default function SettingsPage({
  theme,
  setTheme,
}: {
  theme: string;
  setTheme: (t: string) => void;
}) {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const requestedTab = searchParams.get("tab") || "general";
  const tab = ["general", "mailbox"].includes(requestedTab)
    ? requestedTab
    : "general";

  const configTabs = ["mailbox"];
  const isConfigTab = configTabs.includes(tab);

  // Page title mapping
  const titles: Record<string, string> = {
    general: t("settings.title.general"),
    mailbox: t("settings.title.mailbox"),
  };

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="mb-6 text-xl font-semibold text-[var(--text-primary)]">
        {titles[tab] || t("settings.title.fallback")}
      </h1>

      {tab === "general" && <GeneralTab theme={theme} setTheme={setTheme} />}
      {isConfigTab && <Settings />}
    </div>
  );
}
