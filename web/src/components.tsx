import clsx from "clsx";
import {
  AlertCircle,
  BadgeCheck,
  BookOpenText,
  BriefcaseBusiness,
  ChartNoAxesCombined,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Clock3,
  ExternalLink,
  FileSearch,
  FolderKanban,
  Info,
  Layers3,
  ListChecks,
  Menu,
  SearchCheck,
  ShieldCheck,
  Sparkles,
  UserRound,
  X,
  XCircle,
} from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { NavLink } from "react-router-dom";

import type {
  Eligibility,
  EvidenceFit,
  Opportunity,
  RuntimeMeta,
  Trust,
  VerificationResult,
} from "./api";
import { humanDate, isConfirmedOfficialLink } from "./api";

const navItems = [
  { to: "/about", label: "产品介绍", icon: BookOpenText },
  { to: "/", label: "今日决策", icon: ListChecks, end: true },
  { to: "/jobs", label: "岗位工作区", icon: BriefcaseBusiness },
  { to: "/shortlist", label: "投递计划", icon: FolderKanban },
  { to: "/evidence", label: "评测结果", icon: ChartNoAxesCombined },
];

export function AppShell({
  children,
  profileOpen,
  onProfileOpen,
  mobileNavOpen,
  onMobileNavToggle,
  runtime,
}: {
  children: ReactNode;
  profileOpen: boolean;
  onProfileOpen: () => void;
  mobileNavOpen: boolean;
  onMobileNavToggle: () => void;
  runtime?: RuntimeMeta;
}) {
  const navigationRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    document.body.classList.toggle("mobile-nav-open", mobileNavOpen);
    return () => document.body.classList.remove("mobile-nav-open");
  }, [mobileNavOpen]);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 900px)");
    const syncNavigationState = () => {
      const navigation = navigationRef.current;
      if (!navigation) return;
      const hidden = media.matches && !mobileNavOpen;
      navigation.inert = hidden;
      if (hidden) navigation.setAttribute("aria-hidden", "true");
      else navigation.removeAttribute("aria-hidden");
    };
    syncNavigationState();
    media.addEventListener("change", syncNavigationState);
    return () => media.removeEventListener("change", syncNavigationState);
  }, [mobileNavOpen]);

  useEffect(() => {
    if (!mobileNavOpen) return;
    closeButtonRef.current?.focus();
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      onMobileNavToggle();
      requestAnimationFrame(() => menuButtonRef.current?.focus());
    };
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [mobileNavOpen, onMobileNavToggle]);

  const closeMobileNavigation = () => {
    onMobileNavToggle();
    requestAnimationFrame(() => menuButtonRef.current?.focus());
  };

  return (
    <div className="app-shell">
      {mobileNavOpen && (
        <button
          className="mobile-nav-scrim"
          onClick={closeMobileNavigation}
          aria-label="关闭导航遮罩"
        />
      )}
      <header className="global-header">
        <NavLink className="brand" to="/" aria-label="校招岗位决策台首页">
          <div className="brand-mark" aria-hidden="true">
            <ShieldCheck size={20} strokeWidth={2.2} />
          </div>
          <div>
            <strong>校招岗位决策台</strong>
            <span>证据优先 · 投递前核验</span>
          </div>
        </NavLink>
        <nav
          id="primary-navigation"
          ref={navigationRef}
          className={clsx("global-navigation", mobileNavOpen && "is-open")}
          aria-label="主导航"
        >
          <button
            ref={closeButtonRef}
            className="icon-button mobile-close"
            onClick={closeMobileNavigation}
            aria-label="关闭导航"
          >
            <X size={19} />
          </button>
          <div className="nav-list">
            {navItems.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                onClick={() => mobileNavOpen && closeMobileNavigation()}
                className={({ isActive }) =>
                  clsx("nav-item", isActive && "is-active")
                }
              >
                <Icon size={18} />
                <span>{label}</span>
              </NavLink>
            ))}
          </div>
          <div className="mobile-navigation-actions">
            <NavLink className="button secondary small" to="/sources">
              <Layers3 size={15} /> 数据来源
            </NavLink>
            <NavLink className="button primary small" to="/verify">
              打开核验台 <ChevronRight size={15} />
            </NavLink>
          </div>
        </nav>
        <div className="global-actions">
          <span className="prototype-badge">
            <span className="status-dot" aria-hidden="true" />
            {runtime?.label ?? "本地证据工作区"}
          </span>
          <NavLink
            className="button secondary small source-action"
            to="/sources"
          >
            <Layers3 size={15} /> 数据来源
          </NavLink>
          <NavLink className="button primary small verify-action" to="/verify">
            打开核验台 <ChevronRight size={15} />
          </NavLink>
          <button
            className={clsx("profile-trigger", profileOpen && "is-active")}
            onClick={onProfileOpen}
            aria-label="打开我的证据画像"
          >
            <UserRound size={17} />
            <span>证据画像</span>
          </button>
          <button
            ref={menuButtonRef}
            className="icon-button mobile-menu"
            onClick={onMobileNavToggle}
            aria-label="打开导航"
            aria-expanded={mobileNavOpen}
            aria-controls="primary-navigation"
          >
            <Menu size={20} />
          </button>
        </div>
      </header>

      <section
        className="app-stage"
        inert={mobileNavOpen}
        aria-hidden={mobileNavOpen || undefined}
      >
        {runtime?.read_only && (
          <div className="readonly-banner" role="status">
            <Info size={16} />
            <span>
              当前为在线展示版：使用预置的合成岗位与虚构画像；真实使用时会根据用户导入的岗位来源和已确认简历画像动态生成筛选、三轴结论与推荐。
            </span>
          </div>
        )}
        <main className="page-stage">{children}</main>
      </section>
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <p className="page-eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

type Tone = "positive" | "negative" | "warning" | "neutral" | "info" | "violet";

function StatusPill({
  tone,
  icon,
  children,
}: {
  tone: Tone;
  icon?: ReactNode;
  children: ReactNode;
}) {
  return (
    <span className={clsx("status-pill", `tone-${tone}`)}>
      {icon}
      <span>{children}</span>
    </span>
  );
}

export function EligibilityBadge({ value }: { value?: Eligibility | null }) {
  const values = {
    PASS: ["positive", <CheckCircle2 key="i" />, "符合"] as const,
    FAIL: ["negative", <XCircle key="i" />, "不符合"] as const,
    UNKNOWN: ["warning", <CircleHelp key="i" />, "待确认"] as const,
  };
  const [tone, icon, label] = values[value ?? "UNKNOWN"];
  return (
    <StatusPill tone={tone}>
      {icon}
      {label}
    </StatusPill>
  );
}

export function FitBadge({ value }: { value?: EvidenceFit | null }) {
  const values = {
    PRIMARY: ["violet", <Sparkles key="i" />, "证据强"] as const,
    APPLY: ["info", <BadgeCheck key="i" />, "证据较强"] as const,
    STRETCH: ["warning", <Clock3 key="i" />, "可迁移"] as const,
    LOW: ["negative", <AlertCircle key="i" />, "证据弱"] as const,
    UNKNOWN: ["neutral", <CircleHelp key="i" />, "待分析"] as const,
  };
  const [tone, icon, label] = values[value ?? "UNKNOWN"];
  return (
    <StatusPill tone={tone}>
      {icon}
      {label}
    </StatusPill>
  );
}

export function TrustBadge({ value }: { value?: Trust | null }) {
  const values = {
    VERIFIED: ["positive", <ShieldCheck key="i" />, "官网已核验"] as const,
    VERIFIED_WITH_CONFLICT: [
      "warning",
      <ShieldCheck key="i" />,
      "已核验有冲突",
    ] as const,
    CONSISTENT: ["info", <Layers3 key="i" />, "多源一致"] as const,
    CONFLICTED: ["negative", <AlertCircle key="i" />, "来源冲突"] as const,
    STALE: ["warning", <Clock3 key="i" />, "证据陈旧"] as const,
    UNKNOWN: ["neutral", <CircleHelp key="i" />, "未核验"] as const,
  };
  const [tone, icon, label] = values[value ?? "UNKNOWN"];
  return (
    <StatusPill tone={tone}>
      {icon}
      {label}
    </StatusPill>
  );
}

export function VerificationBadge({
  value,
}: {
  value?: VerificationResult | null;
}) {
  const values = {
    OPEN: ["positive", <CheckCircle2 key="i" />, "官网在招"] as const,
    CLOSED: ["negative", <XCircle key="i" />, "官网明确关闭"] as const,
    NOT_FOUND: ["warning", <FileSearch key="i" />, "页面未找到"] as const,
    BLOCKED: ["warning", <AlertCircle key="i" />, "访问受阻"] as const,
    UNKNOWN: ["neutral", <CircleHelp key="i" />, "尚无法判断"] as const,
  };
  const [tone, icon, label] = values[value ?? "UNKNOWN"];
  return (
    <StatusPill tone={tone}>
      {icon}
      {label}
    </StatusPill>
  );
}

export function KindBadge({ kind }: { kind: Opportunity["kind"] }) {
  return kind === "CAMPAIGN" ? (
    <StatusPill tone="warning" icon={<Layers3 />}>
      招聘项目线索
    </StatusPill>
  ) : (
    <StatusPill tone="info" icon={<BriefcaseBusiness />}>
      具体岗位
    </StatusPill>
  );
}

export function AxisStrip({ item }: { item: Opportunity }) {
  return (
    <div className="axis-strip" aria-label="三轴判断">
      <EligibilityBadge value={item.eligibility} />
      <FitBadge value={item.evidence_fit} />
      <TrustBadge value={item.trust} />
    </div>
  );
}

export function OpportunityCard({
  item,
  compact = false,
}: {
  item: Opportunity;
  compact?: boolean;
}) {
  const unknown = item.unknowns?.[0]?.message;
  const deadline = deadlineLabel(item.deadline);
  const cityLabel = summarizeCities(item.cities);
  const domesticTags = [
    item.recruitment_type,
    item.employer_type,
    item.written_test,
  ].filter(
    (tag): tag is string =>
      Boolean(tag) &&
      !/^(未说明|未明确|未知|待确认|不详|-|—)$/u.test(tag!.trim()),
  );
  return (
    <article className={clsx("opportunity-card", compact && "is-compact")}>
      <div className="opportunity-card-head">
        <div>
          <div className="card-kicker">
            <KindBadge kind={item.kind} />
            {item.title_inferred && (
              <StatusPill tone="violet" icon={<Sparkles />}>
                岗位方向推断
              </StatusPill>
            )}
            {item.verification && (
              <VerificationBadge value={item.verification} />
            )}
          </div>
          <h3>{item.title || "未命名岗位线索"}</h3>
          <p className="company-name">
            {item.company || "公司信息待补充"}
            {item.title_inferred && (
              <span title={item.title_inference_reason}> · 具体名称待核验</span>
            )}
          </p>
        </div>
        <NavLink
          className="icon-link"
          to={`/jobs/${item.id}`}
          aria-label={`查看 ${item.title || "岗位"} 详情`}
        >
          <ChevronRight size={20} />
        </NavLink>
      </div>
      <div className="opportunity-scope">
        <div className="metadata-row">
          <span title={item.cities.join("、") || undefined}>{cityLabel}</span>
          <span>
            {item.graduation_years.length
              ? item.graduation_years.join("、")
              : "届次待确认"}
          </span>
          <span>{item.source_count} 个独立来源</span>
          {(item.observation_count ?? 0) > item.source_count && (
            <span>{item.observation_count} 条记录</span>
          )}
          <span>更新于 {humanDate(item.updated_at)}</span>
        </div>
        {(domesticTags.length > 0 || deadline) && (
          <div className="domestic-meta-row" aria-label="国内校招信息">
            {domesticTags.map((tag) => (
              <span key={tag}>{tag}</span>
            ))}
            {deadline && (
              <span className={deadline.urgent ? "is-urgent" : undefined}>
                <Clock3 size={13} />
                {deadline.text}
              </span>
            )}
          </div>
        )}
        {unknown && (
          <p className="unknown-line">
            <CircleHelp size={15} />
            {unknown}
          </p>
        )}
      </div>
      <AxisStrip item={item} />
      <div className="card-footer">
        {item.kind === "CAMPAIGN" ? (
          <NavLink className="button secondary" to={`/jobs/${item.id}`}>
            <SearchCheck size={16} />
            查找具体岗位
          </NavLink>
        ) : (
          <NavLink className="button secondary" to={`/jobs/${item.id}`}>
            查看证据
          </NavLink>
        )}
        {item.kind === "POSTING" && item.apply_url && (
          <a
            className="text-link"
            href={item.apply_url}
            target="_blank"
            rel="noreferrer"
          >
            {isConfirmedOfficialLink(item) ? "打开官网" : "打开来源链接"}{" "}
            <ExternalLink size={14} />
          </a>
        )}
      </div>
    </article>
  );
}

function summarizeCities(cities: string[], limit = 5) {
  if (!cities.length) return "城市待确认";
  const visible = cities.slice(0, limit).join("、");
  return cities.length > limit ? `${visible}…` : visible;
}

function deadlineLabel(value: string) {
  if (!value) return null;
  const parsed = new Date(`${value}T23:59:59`);
  if (Number.isNaN(parsed.getTime())) return { text: value, urgent: false };
  const remaining = Math.ceil(
    (parsed.getTime() - Date.now()) / (24 * 60 * 60 * 1000),
  );
  if (remaining < 0) return { text: `已过截止 ${value}`, urgent: true };
  if (remaining === 0) return { text: "今天截止", urgent: true };
  if (remaining <= 14) return { text: `${remaining} 天后截止`, urgent: true };
  return { text: `截止 ${value}`, urgent: false };
}

export function EmptyState({
  icon = <FileSearch />,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}

export function LoadingBlock({ label = "正在读取证据…" }: { label?: string }) {
  return (
    <div className="loading-block" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorBlock({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="error-block" role="alert">
      <AlertCircle size={18} />
      <div>
        <strong>暂时无法读取</strong>
        <p>{message}</p>
      </div>
      {onRetry && (
        <button className="button secondary small" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  );
}

export function SectionHeading({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="section-heading">
      <div>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {action}
    </div>
  );
}
