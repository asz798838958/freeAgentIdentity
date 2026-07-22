import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { API_BASE, apiFetch } from "@/lib/utils";
import { getTaskStatusText, isTerminalTaskStatus } from "@/lib/tasks";
import { useI18n } from "@/lib/i18n-context";

/**
 * 单条日志事件。`subtaskId` 来自后端 ``serialize_event(...).detail.subtask_id``——
 * ``TaskLogger.log`` 在每个并发 worker 进入时通过 thread-local 自动注入。前端
 * 按这个字段分组折叠展示；空字符串表示主任务（任务级状态、汇总日志等）。
 */
type LogEvent = {
  id: number;
  line: string;
  subtaskId: string;
  subtaskLabel: string;
};

type LogGroup = {
  id: string;
  label: string;
  events: LogEvent[];
};

const MAIN_GROUP_ID = "__main__";

function classifyLine(line: string): string {
  if (line.includes("✓") || line.includes("成功")) return "text-emerald-400";
  if (line.includes("✗") || line.includes("失败") || line.includes("错误"))
    return "text-red-400";
  return "text-[var(--text-secondary)]";
}

export function TaskLogPanel({
  taskId,
  onDone,
}: {
  taskId: string;
  onDone: (status: string) => void;
}) {
  const { t, language } = useI18n();
  const [events, setEvents] = useState<LogEvent[]>([]);
  const [task, setTask] = useState<any | null>(null);
  const [doneStatus, setDoneStatus] = useState<string | null>(null);
  // 折叠状态：默认全展开（undefined / false 都视为展开）
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const seenEventIdsRef = useRef<Set<number>>(new Set());
  const cursorRef = useRef(0);
  const doneRef = useRef(false);
  const onDoneRef = useRef(onDone);
  const sseHealthyRef = useRef(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    onDoneRef.current = onDone;
  }, [onDone]);

  useEffect(() => {
    if (!taskId) return;
    seenEventIdsRef.current = new Set();
    cursorRef.current = 0;
    doneRef.current = false;
    sseHealthyRef.current = false;
    setEvents([]);
    setTask(null);
    setDoneStatus(null);
    setCollapsed({});

    const pushEvent = (payload: any) => {
      const eventId = Number(payload?.id || 0);
      if (eventId && seenEventIdsRef.current.has(eventId)) return;
      if (eventId) {
        seenEventIdsRef.current.add(eventId);
        cursorRef.current = Math.max(cursorRef.current, eventId);
      }
      if (payload?.line) {
        const detail = payload?.detail || {};
        setEvents((prev) => [
          ...prev,
          {
            id: eventId || prev.length + 1,
            line: String(payload.line),
            subtaskId: String(detail?.subtask_id || ""),
            subtaskLabel: String(detail?.subtask_label || ""),
          },
        ]);
      }
      if (payload?.done && !doneRef.current) {
        doneRef.current = true;
        sseHealthyRef.current = false;
        eventSourceRef.current?.close();
        eventSourceRef.current = null;
        const nextStatus = payload.status || "succeeded";
        setDoneStatus(nextStatus);
        onDoneRef.current(nextStatus);
      }
    };

    const syncTask = async () => {
      const latest = await apiFetch(`/tasks/${taskId}`);
      setTask(latest);
      if (isTerminalTaskStatus(latest.status) && !doneRef.current) {
        pushEvent({ done: true, status: latest.status });
      }
    };

    const es = new EventSource(`${API_BASE}/tasks/${taskId}/logs/stream`);
    eventSourceRef.current = es;
    es.onopen = () => {
      sseHealthyRef.current = true;
    };
    es.onmessage = (e) => {
      sseHealthyRef.current = true;
      pushEvent(JSON.parse(e.data));
    };
    es.onerror = () => {
      if (doneRef.current) {
        es.close();
        if (eventSourceRef.current === es) {
          eventSourceRef.current = null;
        }
        return;
      }
      sseHealthyRef.current = false;
    };

    syncTask().catch(() => {});

    // 进度需要持续轮询：SSE 只发 events，progress 在 task model 上，
    // 必须主动 GET /tasks/{id} 拿。原实现里只在 SSE 不健康时轮询，导致
    // SSE 正常时进度从来不更新。
    const progressPoll = window.setInterval(() => {
      if (doneRef.current) return;
      syncTask().catch(() => {});
    }, 1500);

    const fallbackPoll = window.setInterval(async () => {
      if (doneRef.current || sseHealthyRef.current) return;
      try {
        const data = await apiFetch(
          `/tasks/${taskId}/events?since=${cursorRef.current}`,
        );
        for (const item of data.items || []) {
          pushEvent(item);
        }
      } catch {
        // passive
      }
    }, 1000);

    return () => {
      sseHealthyRef.current = false;
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      window.clearInterval(progressPoll);
      window.clearInterval(fallbackPoll);
    };
  }, [taskId]);

  // 按 subtaskId 把事件切成分组：主任务 + 每个 worker。
  // 顺序按"首次出现"排，保证 worker 折叠面板顺序稳定（worker_1 / worker_2…）。
  const groups: LogGroup[] = useMemo(() => {
    const map = new Map<string, LogGroup>();
    map.set(MAIN_GROUP_ID, {
      id: MAIN_GROUP_ID,
      label: t("taskLog.mainGroup"),
      events: [],
    });
    for (const ev of events) {
      const key = ev.subtaskId || MAIN_GROUP_ID;
      if (!map.has(key)) {
        map.set(key, {
          id: key,
          label: ev.subtaskLabel || key,
          events: [],
        });
      }
      const group = map.get(key)!;
      group.events.push(ev);
      if (key !== MAIN_GROUP_ID && ev.subtaskLabel) {
        group.label = ev.subtaskLabel;
      }
    }
    return Array.from(map.values());
  }, [events, t]);

  const toggleGroup = (id: string) => {
    setCollapsed((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const currentStatus = doneStatus || task?.status || "running";
  const progress = task?.progress_detail || {};
  const progressTotal = Number(progress.total || 0);
  const progressCurrent = Number(progress.current || 0);
  const progressPercent =
    progressTotal > 0
      ? Math.min(100, Math.round((progressCurrent / progressTotal) * 100))
      : 0;
  const errorText =
    task?.error || (Array.isArray(task?.errors) ? task.errors[0] : "");
  const statusTone =
    currentStatus === "succeeded"
      ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-200"
      : currentStatus === "failed"
        ? "border-red-400/40 bg-red-400/10 text-red-200"
        : currentStatus === "cancelled" || currentStatus === "interrupted"
          ? "border-amber-400/40 bg-amber-400/10 text-amber-200"
          : "border-sky-400/40 bg-sky-400/10 text-sky-200";

  const copyLogs = () => {
    navigator.clipboard
      ?.writeText(events.map((ev) => ev.line).join("\n"))
      .catch(() => {});
  };

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="grid gap-3 md:grid-cols-3">
        <div className={`rounded-2xl border px-4 py-3 ${statusTone}`}>
          <div className="text-[11px] uppercase tracking-[0.18em] opacity-70">
            {t("taskLog.status")}
          </div>
          <div className="mt-1 text-sm font-semibold">
            {getTaskStatusText(currentStatus, language)}
          </div>
        </div>
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-hover)] px-4 py-3">
          <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--text-muted)]">
            {t("taskLog.progress")}
          </div>
          <div className="mt-1 text-sm font-semibold text-[var(--text-primary)]">
            {progress.label || task?.progress || "0/0"}
          </div>
        </div>
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-hover)] px-4 py-3">
          <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--text-muted)]">
            {t("taskLog.events")}
          </div>
          <div className="mt-1 text-sm font-semibold text-[var(--text-primary)]">
            {t("taskLog.logCount", { count: events.length })}
          </div>
        </div>
      </div>

      <div className="h-2 overflow-hidden rounded-full bg-[var(--bg-hover)] ring-1 ring-[var(--border)]">
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            currentStatus === "failed"
              ? "bg-red-400"
              : currentStatus === "succeeded"
                ? "bg-emerald-400"
                : "bg-sky-400"
          }`}
          style={{
            width: `${progressTotal > 0 ? progressPercent : isTerminalTaskStatus(currentStatus) ? 100 : 18}%`,
          }}
        />
      </div>

      {errorText ? (
        <div className="rounded-2xl border border-red-400/35 bg-red-500/10 px-4 py-3 text-sm text-red-100">
          <div className="mb-1 font-semibold">
            {t("taskLog.failureReason")}
          </div>
          <div className="break-words text-red-100/85">{errorText}</div>
        </div>
      ) : null}

      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--text-muted)]">
            {t("taskLog.liveLog")}
          </div>
          <div className="mt-1 text-sm font-medium text-[var(--text-primary)]">
            {t("taskLog.liveTitle")}
          </div>
        </div>
        <button
          type="button"
          onClick={copyLogs}
          className="rounded-full border border-[var(--border)] bg-[var(--bg-hover)] px-3 py-1.5 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
        >
          {t("taskLog.copyLogs")}
        </button>
      </div>

      <div className="min-h-[260px] flex-1 overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--bg-input)] p-3 font-mono text-xs">
        {events.length === 0 ? (
          <div className="flex h-full min-h-[180px] items-center justify-center rounded-2xl border border-dashed border-[var(--border)] text-[var(--text-muted)]">
            {t("taskLog.waiting")}
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {groups.map((group) => {
              if (group.id === MAIN_GROUP_ID && group.events.length === 0) {
                return null;
              }
              return (
                <LogGroupView
                  key={group.id}
                  group={group}
                  collapsed={!!collapsed[group.id]}
                  isMain={group.id === MAIN_GROUP_ID}
                  onToggle={() => toggleGroup(group.id)}
                />
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * 单个分组（主任务或一个 worker）。
 *
 * 用 React 自身的虚拟 DOM diff 渲染日志列表，关键点：
 *   - 每条事件用稳定的 ``id`` 当 key（避免 React 整列重渲），
 *   - 折叠时 events 被卸载，DOM 不留滞；展开时按 100 条上限做软裁剪
 *     （单 worker 一般 50~80 条事件，超过 100 条只显示最近的 100 条，
 *     底部加提示让用户知道历史被截断），保护极端长任务不挂死浏览器。
 */
const MAX_VISIBLE_PER_GROUP = 200;

function LogGroupView({
  group,
  collapsed,
  isMain,
  onToggle,
}: {
  group: LogGroup;
  collapsed: boolean;
  isMain: boolean;
  onToggle: () => void;
}) {
  const { t } = useI18n();
  const total = group.events.length;
  const truncated = total > MAX_VISIBLE_PER_GROUP;
  const visible = truncated
    ? group.events.slice(total - MAX_VISIBLE_PER_GROUP)
    : group.events;
  const bottomRef = useRef<HTMLDivElement>(null);

  // 展开时新事件到来自动滚到底部
  useEffect(() => {
    if (collapsed) return;
    bottomRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
  }, [collapsed, total]);

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg-pane)]/40">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-2 border-b border-[var(--border)] bg-[var(--bg-hover)]/60 px-3 py-1.5 text-left text-[11px] uppercase tracking-[0.16em] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
      >
        {collapsed ? (
          <ChevronRight className="h-3.5 w-3.5" />
        ) : (
          <ChevronDown className="h-3.5 w-3.5" />
        )}
        <span className="truncate">
          {isMain ? t("taskLog.mainGroup") : group.label}
        </span>
        <span className="ml-auto text-[10px] text-[var(--text-muted)]">
          {t("taskLog.logCount", { count: total })}
        </span>
      </button>
      {!collapsed && (
        <div className="max-h-[280px] overflow-y-auto px-2 py-2">
          {truncated && (
            <div className="mb-2 rounded border border-amber-400/30 bg-amber-400/10 px-2 py-1 text-[10px] text-amber-200">
              {t("taskLog.truncatedHint", {
                shown: MAX_VISIBLE_PER_GROUP,
                total,
              })}
            </div>
          )}
          <div className="space-y-1">
            {visible.map((ev) => (
              <div
                key={ev.id}
                className={`rounded-md border border-white/5 bg-white/[0.025] px-3 py-1.5 leading-5 ${classifyLine(ev.line)}`}
              >
                {ev.line}
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        </div>
      )}
    </div>
  );
}
