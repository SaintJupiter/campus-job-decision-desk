import {
  Check,
  CircleHelp,
  FileText,
  RefreshCw,
  Save,
  Sparkles,
  Trash2,
  UploadCloud,
  UserRound,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { api, type Preference, type Profile } from "./api";
import {
  EmptyState,
  ErrorBlock,
  LoadingBlock,
  SectionHeading,
} from "./components";
import { useRemote } from "./useRemote";
import { useRuntime } from "./runtime";

const categoryLabels: Record<string, string> = {
  EDUCATION: "学历",
  GRADUATION_YEAR: "毕业届次",
  SKILL: "技能与能力",
  EXPERIENCE: "经历",
  PROJECT: "项目",
  LOCATION: "地点",
};

export function ProfileDrawer({ onClose }: { onClose: () => void }) {
  const drawerRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  const runtime = useRuntime();
  const profile = useRemote(() => api<Profile>("/api/workspace/profile"));
  const [resumeText, setResumeText] = useState("");
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [cities, setCities] = useState("");
  const [types, setTypes] = useState("");
  const [roles, setRoles] = useState("");
  const [exclusions, setExclusions] = useState("");

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const frame = window.requestAnimationFrame(() =>
      closeButtonRef.current?.focus(),
    );
    function handleKeydown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) return;
      const focusable = [
        ...drawerRef.current.querySelectorAll<HTMLElement>(
          "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href]",
        ),
      ].filter((element) => element.getClientRects().length > 0);
      if (!focusable.length) return;
      const first = focusable[0]!;
      const last = focusable[focusable.length - 1]!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.body.classList.add("drawer-open");
    document.addEventListener("keydown", handleKeydown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.body.classList.remove("drawer-open");
      document.removeEventListener("keydown", handleKeydown);
      previouslyFocused?.focus();
    };
  }, []);

  useEffect(() => {
    if (!profile.data) return;
    setCities(preferenceText(profile.data.preferences, "accepted_cities"));
    setTypes(
      preferenceText(profile.data.preferences, "accepted_recruitment_types"),
    );
    setRoles(preferenceText(profile.data.preferences, "target_role_keywords"));
    setExclusions(
      preferenceText(profile.data.preferences, "excluded_work_patterns"),
    );
  }, [profile.data]);

  const groupedFacts = useMemo(() => {
    const groups = new Map<string, Profile["facts"]>();
    const activeResumeId = profile.data?.active_resume_id;
    const visibleFacts = (profile.data?.facts ?? []).filter((fact) =>
      activeResumeId ? fact.resume_document_id === activeResumeId : true,
    );
    for (const fact of visibleFacts)
      groups.set(fact.category, [...(groups.get(fact.category) ?? []), fact]);
    return [...groups.entries()];
  }, [profile.data]);

  async function activateResume(id: string) {
    if (runtime.read_only) return;
    setSaving(true);
    setMessage("");
    try {
      await api(`/api/workspace/profile/resumes/${id}/activate`, {
        method: "PUT",
      });
      setMessage("已切换默认简历；岗位三轴需要按该版本重新计算。");
      profile.reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "切换简历失败");
    } finally {
      setSaving(false);
    }
  }

  async function extract() {
    if (runtime.read_only) return;
    if (!resumeText.trim()) {
      setMessage("请先粘贴简历文本");
      return;
    }
    setSaving(true);
    setMessage("");
    try {
      const result = await api<{ created: number }>(
        "/api/workspace/profile/extract",
        {
          method: "POST",
          body: JSON.stringify({
            text: resumeText,
            source_name: "pasted-resume.txt",
          }),
        },
      );
      setMessage(
        `已提取 ${result.created} 条候选事实；确认需要采用的事实后，一键刷新全部岗位。`,
      );
      setResumeText("");
      profile.reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "提取失败");
    } finally {
      setSaving(false);
    }
  }

  async function uploadResume() {
    if (runtime.read_only) return;
    if (!resumeFile) {
      setMessage("请先选择 TXT、Markdown 或 PDF 简历");
      return;
    }
    setSaving(true);
    setMessage("");
    const form = new FormData();
    form.set("file", resumeFile);
    try {
      const result = await api<{ created: number }>(
        "/api/workspace/profile/upload",
        { method: "POST", body: form },
      );
      setMessage(
        `已从 ${resumeFile.name} 提取 ${result.created} 条候选事实；确认需要采用的事实后，一键刷新全部岗位。`,
      );
      setResumeFile(null);
      profile.reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "简历上传失败");
    } finally {
      setSaving(false);
    }
  }

  async function deleteProfile() {
    if (runtime.read_only) return;
    const confirmed = window.confirm(
      "确定删除全部画像事实、求职偏好和关联的岗位决策快照吗？此操作无法撤销。",
    );
    if (!confirmed) return;
    setSaving(true);
    setMessage("");
    try {
      await api("/api/workspace/profile", { method: "DELETE" });
      profile.setData({
        active_resume_id: null,
        resumes: [],
        facts: [],
        preferences: [],
      });
      setCities("");
      setTypes("");
      setRoles("");
      setExclusions("");
      setResumeText("");
      setResumeFile(null);
      setMessage("证据画像已删除；岗位需在新画像下重新计算。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除失败");
    } finally {
      setSaving(false);
    }
  }

  async function toggleFact(id: string, confirmed: boolean) {
    if (runtime.read_only) return;
    try {
      await api(`/api/workspace/profile/facts/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ confirmed }),
      });
      profile.setData((current) =>
        current
          ? {
              ...current,
              facts: current.facts.map((fact) =>
                fact.id === id ? { ...fact, confirmed } : fact,
              ),
            }
          : current,
      );
      setMessage(
        confirmed
          ? "事实已确认；完成选择后可一键刷新全部岗位。"
          : "事实已取消确认；旧三轴已失效，请重新刷新岗位。",
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    }
  }

  async function recomputeDecisions() {
    if (runtime.read_only) return;
    setSaving(true);
    setMessage("");
    try {
      const result = await api<{ recomputed: number }>(
        "/api/workspace/decisions/recompute",
        {
          method: "POST",
          body: JSON.stringify({ opportunity_ids: null }),
        },
      );
      setMessage(
        `已按当前默认简历、已确认事实和求职偏好刷新 ${result.recomputed} 个岗位。`,
      );
      profile.reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "批量刷新失败");
    } finally {
      setSaving(false);
    }
  }

  async function savePreferences() {
    if (runtime.read_only) return;
    setSaving(true);
    setMessage("");
    const values = [
      ["accepted_cities", parseList(cities), true],
      ["accepted_recruitment_types", parseList(types), true],
      ["target_role_keywords", parseList(roles), false],
      ["excluded_work_patterns", parseList(exclusions), false],
    ] as const;
    try {
      for (const [key, value, hard_constraint] of values) {
        await api(`/api/workspace/profile/preferences/${key}`, {
          method: "PUT",
          body: JSON.stringify({
            key,
            value,
            hard_constraint,
            confirmed: true,
          }),
        });
      }
      setMessage("偏好与硬条件已保存");
      profile.reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="drawer-layer" role="presentation">
      <button
        className="drawer-scrim"
        onClick={onClose}
        aria-label="关闭画像抽屉"
      />
      <aside
        ref={drawerRef}
        className="profile-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="profile-title"
      >
        <header className="drawer-header">
          <div className="drawer-heading">
            <div className="drawer-icon">
              <UserRound size={20} />
            </div>
            <div>
              <span>FACTS, NOT PERSONAS</span>
              <h2 id="profile-title">我的证据画像</h2>
            </div>
          </div>
          <button
            ref={closeButtonRef}
            className="icon-button"
            onClick={onClose}
            aria-label="关闭"
          >
            <X size={20} />
          </button>
        </header>
        <div className="drawer-body">
          <p className="drawer-intro">
            简历事实、规则抽取和用户确认保持分离。未经确认的内容不会参与硬条件或经历匹配。
          </p>
          {runtime.read_only && (
            <div className="notice warning" role="status">
              <CircleHelp size={17} />
              <span>
                只读演示可查看证据画像，但不会接收简历或保存任何修改。
              </span>
            </div>
          )}
          {message && (
            <div className="notice info" role="status">
              <CircleHelp size={17} />
              <span>{message}</span>
            </div>
          )}

          <section className="drawer-section">
            <SectionHeading
              title="1. 提供简历证据"
              description="可上传 TXT、Markdown 或 PDF，也可直接粘贴文本；系统只抽取带原文证据的候选事实。"
            />
            {(profile.data?.resumes ?? []).length ? (
              <div className="resume-version-list" aria-label="简历版本">
                {(profile.data?.resumes ?? []).map((resume) => (
                  <article
                    key={resume.id}
                    className={`resume-version ${resume.is_active ? "is-active" : ""}`}
                  >
                    <div>
                      <span>
                        {resume.is_active ? "当前默认简历" : "历史简历"}
                      </span>
                      <strong>{resume.name}</strong>
                      <small>
                        {resume.fact_count} 条候选事实 · {resume.source_format}
                      </small>
                    </div>
                    {!resume.is_active && (
                      <button
                        className="button secondary small"
                        disabled={runtime.read_only || saving}
                        onClick={() => activateResume(resume.id)}
                      >
                        设为默认
                      </button>
                    )}
                  </article>
                ))}
              </div>
            ) : (
              <p className="resume-version-empty">
                上传第一份简历后，它会成为默认画像；后续上传会保留为可切换版本。
              </p>
            )}
            <label className="profile-file-input">
              <UploadCloud size={18} />
              <span>{resumeFile ? resumeFile.name : "选择简历文件"}</span>
              <small>TXT / MD / PDF</small>
              <input
                type="file"
                disabled={runtime.read_only}
                accept=".txt,.md,.markdown,.pdf"
                onChange={(event) =>
                  setResumeFile(event.target.files?.[0] ?? null)
                }
              />
            </label>
            <button
              className="button secondary"
              onClick={uploadResume}
              disabled={runtime.read_only || saving || !resumeFile}
            >
              <UploadCloud size={16} />
              上传并提取候选事实
            </button>
            <div className="or-divider">
              <span>或粘贴文本</span>
            </div>
            <textarea
              className="resume-textarea"
              value={resumeText}
              disabled={runtime.read_only}
              onChange={(event) => setResumeText(event.target.value)}
              placeholder="粘贴简历文本…"
            />
            <button
              className="button secondary"
              onClick={extract}
              disabled={runtime.read_only || saving}
            >
              <Sparkles size={16} />
              提取候选事实
            </button>
          </section>

          <section className="drawer-section">
            <SectionHeading
              title="2. 确认事实"
              description="确认代表“简历原文确实支持这条事实”，不代表具备岗位要求的全部深度。"
            />
            {profile.loading ? (
              <LoadingBlock />
            ) : profile.error ? (
              <ErrorBlock message={profile.error} onRetry={profile.reload} />
            ) : groupedFacts.length ? (
              <div className="fact-groups">
                {groupedFacts.map(([category, facts]) => (
                  <details
                    key={category}
                    className="fact-group"
                    open={category === "EDUCATION" || category === "EXPERIENCE"}
                  >
                    <summary>
                      {categoryLabels[category] ?? category}
                      <span>
                        {facts.filter((fact) => fact.confirmed).length}/
                        {facts.length} 已确认
                      </span>
                    </summary>
                    {facts.map((fact) => (
                      <label
                        key={fact.id}
                        className={`fact-row ${fact.confirmed ? "is-confirmed" : ""}`}
                      >
                        <input
                          type="checkbox"
                          disabled={runtime.read_only}
                          checked={fact.confirmed}
                          onChange={(event) =>
                            toggleFact(fact.id, event.target.checked)
                          }
                        />
                        <span className="fact-check">
                          {fact.confirmed ? <Check size={14} /> : null}
                        </span>
                        <span className="fact-content">
                          <strong>{fact.value}</strong>
                          {evidenceDetail(fact.value, fact.evidence_text) && (
                            <q>
                              {evidenceDetail(fact.value, fact.evidence_text)}
                            </q>
                          )}
                        </span>
                      </label>
                    ))}
                  </details>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={<FileText />}
                title="还没有画像事实"
                description="粘贴简历文本后，候选事实会显示在这里等待确认。"
              />
            )}
            <button
              className="button primary profile-recompute-button"
              onClick={recomputeDecisions}
              disabled={
                runtime.read_only ||
                saving ||
                !(profile.data?.facts ?? []).some(
                  (fact) =>
                    fact.resume_document_id ===
                      profile.data?.active_resume_id && fact.confirmed,
                )
              }
            >
              <RefreshCw size={17} />
              {saving ? "正在刷新岗位…" : "用已确认事实刷新全部岗位"}
            </button>
            <p className="profile-recompute-note">
              上传不会自动采信候选事实；只用你勾选确认的内容更新三轴与推荐队列。
            </p>
          </section>

          <section className="drawer-section">
            <SectionHeading
              title="3. 确认求职偏好"
              description="城市和招聘类型参与硬条件；目标岗位与排斥工作当前仅记录，供人工判断。"
            />
            <div className="stack-form">
              <label>
                <span>可接受城市（硬条件）</span>
                <input
                  value={cities}
                  onChange={(event) => setCities(event.target.value)}
                  placeholder="上海、杭州、苏州"
                />
              </label>
              <label>
                <span>可接受招聘类型（硬条件）</span>
                <input
                  value={types}
                  onChange={(event) => setTypes(event.target.value)}
                  placeholder="秋招、实习"
                />
              </label>
              <label>
                <span>目标岗位关键词</span>
                <input
                  value={roles}
                  onChange={(event) => setRoles(event.target.value)}
                  placeholder="AI产品、平台产品、解决方案"
                />
              </label>
              <label>
                <span>不希望长期从事</span>
                <input
                  value={exclusions}
                  onChange={(event) => setExclusions(event.target.value)}
                  placeholder="销售指标、长期驻场"
                />
              </label>
              <button
                className="button primary"
                onClick={savePreferences}
                disabled={runtime.read_only || saving}
              >
                <Save size={16} />
                保存画像与偏好
              </button>
            </div>
          </section>

          <section className="drawer-section danger-zone">
            <SectionHeading
              title="删除证据画像"
              description="将同时删除事实、偏好和旧决策快照；原始岗位数据与导入批次不会受影响。"
            />
            <button
              className="button danger"
              onClick={deleteProfile}
              disabled={runtime.read_only || saving}
            >
              <Trash2 size={16} />
              删除全部画像数据
            </button>
          </section>
        </div>
      </aside>
    </div>
  );
}

function parseList(value: string) {
  return value
    .split(/[\u3001,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function preferenceText(preferences: Preference[], key: string) {
  const value = preferences.find((item) => item.key === key)?.value;
  return Array.isArray(value)
    ? value.join("、")
    : typeof value === "string"
      ? value
      : "";
}

function evidenceDetail(value: string, evidence: string) {
  const trimmed = evidence.trim();
  if (trimmed === value) return "";
  for (const prefix of [`${value}：`, `${value}:`]) {
    if (trimmed.startsWith(prefix)) return trimmed.slice(prefix.length).trim();
  }
  return trimmed;
}
