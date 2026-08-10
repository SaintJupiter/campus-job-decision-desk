import {
  ArrowRight,
  BadgeCheck,
  DatabaseZap,
  GitCompareArrows,
  Layers3,
  SearchCheck,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

const capabilities = [
  {
    index: "01",
    icon: DatabaseZap,
    title: "多源岗位统一接入",
    copy: "支持 CSV、XLSX、Markdown 与飞书多维表；每次导入均保留来源、快照时间、字段映射和原始记录。",
    tone: "violet",
  },
  {
    index: "02",
    icon: Layers3,
    title: "区分招聘项目与具体岗位",
    copy: "将招聘活动、岗位族和具体职位分层保存；宽泛项目只进入核验队列，不直接参与岗位匹配。",
    tone: "mint",
  },
  {
    index: "03",
    icon: GitCompareArrows,
    title: "保留字段来源与冲突",
    copy: "公司、岗位、城市、届次、截止时间和链接分别记录来源；冲突显式展示，历史值完整保留。",
    tone: "cyan",
  },
  {
    index: "04",
    icon: SearchCheck,
    title: "聚焦高价值官网核验",
    copy: "分别判断可投性、经历证据和信息可信度，优先核验最可能改变投递结论的岗位。",
    tone: "coral",
  },
];

export function AboutPage() {
  return (
    <div className="about-page">
      <section className="about-hero">
        <div className="about-hero-copy">
          <p className="page-eyebrow">PORTFOLIO PRODUCT · EVIDENCE FIRST</p>
          <h1>
            多份校招表，
            <span>先核验，再决定。</span>
          </h1>
          <p className="about-lead">
            系统面向国内校招多源信息不一致的问题，将招聘项目、具体岗位、字段来源和官网状态分层处理，再生成可追溯的投递建议。
          </p>
          <div className="about-demo-context" role="note">
            <strong>当前页面是在线展示版</strong>
            <span>
              页面使用预置合成岗位和虚构简历，便于直接体验完整流程；真实使用时，岗位池、证据匹配和推荐顺序会根据用户自己的岗位来源、简历画像与核验结果动态生成。
            </span>
          </div>
          <div className="about-actions">
            <NavLink className="button primary" to="/dashboard">
              开始规划投递 <ArrowRight size={18} />
            </NavLink>
            <NavLink className="button secondary" to="/evidence">
              查看评测结果
            </NavLink>
          </div>
        </div>

        <div className="about-product-window" aria-label="产品决策流程示意">
          <div className="about-window-bar">
            <span aria-hidden="true" />
            <span aria-hidden="true" />
            <span aria-hidden="true" />
            <strong>job-evidence.local / decision-005</strong>
            <em>DEMO</em>
          </div>
          <div className="about-window-body">
            <div className="about-source-column">
              <small>可接入的数据来源</small>
              <strong>3 类来源</strong>
              <div>
                <span>飞书多维表</span>
                <b>定时同步</b>
              </div>
              <div>
                <span>本地岗位表</span>
                <b>批量导入</b>
              </div>
              <div>
                <span>企业官网</span>
                <b>核验证据</b>
              </div>
            </div>
            <div className="about-decision-column">
              <small>三轴结论</small>
              <DecisionRow
                icon={<BadgeCheck />}
                label="可投性"
                value="条件通过"
              />
              <DecisionRow
                icon={<Sparkles />}
                label="经历证据"
                value="2 项经历支持"
              />
              <DecisionRow
                icon={<ShieldCheck />}
                label="信息可信度"
                value="官网已确认"
              />
              <p>来源负责提供线索，企业官网负责确认当前岗位事实。</p>
            </div>
          </div>
        </div>
      </section>

      <section className="about-problem-strip" aria-label="产品问题定义">
        <strong>真实问题</strong>
        <span>同一岗位的关键字段相互冲突</span>
        <span>招聘项目与具体岗位混在同一行</span>
        <span>链接访问失败被误判为岗位关闭</span>
        <span>投递建议缺少简历证据支持</span>
      </section>

      <section className="about-capability-section">
        <div className="about-section-head">
          <div>
            <p className="page-eyebrow">HOW IT WORKS</p>
            <h2>从岗位线索到可信投递</h2>
          </div>
          <p>
            流程先校正岗位事实，再判断资格、经历证据与信息可信度；无法确认的信息保持未知。
          </p>
        </div>
        <div className="about-capability-grid">
          {capabilities.map(({ index, icon: Icon, title, copy, tone }) => (
            <article
              className={`about-capability-card tone-${tone}`}
              key={index}
            >
              <div>
                <span>{index}</span>
                <Icon size={22} />
              </div>
              <h3>{title}</h3>
              <p>{copy}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="about-difference-panel">
        <div>
          <p className="page-eyebrow">WHY THIS PRODUCT</p>
          <h2>将多源岗位信息转化为可追溯的投递判断。</h2>
        </div>
        <div className="about-difference-grid">
          <div>
            <span>常见求职工具</span>
            <strong>岗位检索、简历优化与投递管理</strong>
          </div>
          <ArrowRight size={24} aria-hidden="true" />
          <div>
            <span>本项目的切入点</span>
            <strong>多源融合、字段溯源、官网核验与三轴决策</strong>
          </div>
        </div>
        <NavLink className="text-link" to="/sources">
          查看数据接入与来源审计 <ArrowRight size={14} />
        </NavLink>
      </section>
    </div>
  );
}

function DecisionRow({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="about-decision-row">
      <span>
        {icon}
        {label}
      </span>
      <strong>{value}</strong>
    </div>
  );
}
