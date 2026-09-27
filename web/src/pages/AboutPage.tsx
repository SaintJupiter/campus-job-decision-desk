import { useState } from "react";
import { ArrowRight } from "lucide-react";
import { NavLink } from "react-router-dom";
import "../styles/product-story.css";

const cases = [
  {
    label: "经验直接匹配",
    status: "值得优先了解",
    requirement: "岗位要求：设计产品流程，并开展用户访谈",
    fact: "简历事实：校园项目中负责访谈、需求整理与交互原型",
    judgment: "访谈与原型经历可支持这项要求；不据此推断商业产品上线经验。",
    action: "继续检查届次、地点和官网开放状态，再决定是否加入投递计划。",
  },
  {
    label: "能力可迁移",
    status: "有基础，仍需补证",
    requirement: "岗位要求：设计 AI 产品的效果评估方案",
    fact: "简历事实：做过实验对照与误差分析，未记录模型评测经历",
    judgment: "实验设计方法可迁移，但不能改写成已有大模型评测经验。",
    action: "展示可迁移依据，同时保留 AI 评测经验缺口，供求职者判断。",
  },
  {
    label: "证据不足",
    status: "不作肯定推荐",
    requirement: "岗位要求：具备 SQL 数据分析经验",
    fact: "简历事实：只有用户访谈与原型经历，没有 SQL 相关记录",
    judgment: "语义相近不能代替能力证据；缺少记录不等于断言本人不会。",
    action: "先补充或确认真实经历。若明确不满足硬性条件，则拦截推荐。",
  },
];
export function AboutPage() {
  const [selected, setSelected] = useState(0);
  const example = cases[selected] ?? cases[0]!;
  return (
    <div className="product-story">
      <section className="career-intro">
        <div>
          <p className="story-kicker">校招 AI 求职助手 / 岗位匹配与投递决策</p>
          <h1>
            不只找岗位，
            <br />
            <em>看清为什么适合你。</em>
          </h1>
          <p className="story-lead">
            岗位散在多份表里，要求藏在长 JD 中，AI
            推荐又说不清依据。把岗位要求与真实简历经历对上，分清值得投、需要补证和暂不推荐。
          </p>
          <div className="story-actions">
            <NavLink className="button primary" to="/jobs">
              体验岗位筛选 <ArrowRight size={18} />
            </NavLink>
            <button
              className="story-jump"
              onClick={() =>
                document
                  .getElementById("matching-example")
                  ?.scrollIntoView({ behavior: "smooth" })
              }
            >
              先看一次匹配判断 ↓
            </button>
          </div>
          <p className="story-boundary">
            公开演示使用合成岗位与虚构画像；不收集简历、不现场调用模型。真实数据导入与语义计算在本地完整版运行。
          </p>
        </div>
        <aside className="career-result" aria-label="投递决策示意">
          <div className="result-topline">
            <span>你最终拿到什么</span>
            <span>示意</span>
          </div>
          <h2>
            一份有依据的
            <br />
            投递清单。
          </h2>
          <div>
            <b>能不能投</b>
            <small>届次、学历与其他硬性条件</small>
          </div>
          <div>
            <b>为什么匹配</b>
            <small>直接经验、可迁移能力、待补缺口</small>
          </div>
          <div>
            <b>信息是否可信</b>
            <small>官网状态、来源与待核实冲突</small>
          </div>
          <NavLink to="/shortlist">
            查看投递计划 <ArrowRight size={18} />
          </NavLink>
        </aside>
      </section>
      <section className="career-problems" aria-label="问题与设计回应">
        <article>
          <span>01 / 找得累</span>
          <h3>岗位多，线索不等于机会</h3>
          <p>合并来源并区分招聘活动与具体职位，先确认是不是一个可投岗位。</p>
        </article>
        <article>
          <span>02 / 看不懂</span>
          <h3>名称相似，不代表要求相同</h3>
          <p>拆解工作任务、能力要求与硬条件，再关联已确认的简历经历。</p>
        </article>
        <article>
          <span>03 / 不敢信</span>
          <h3>一句“适合”，不足以决策</h3>
          <p>呈现依据、缺口和不确定性，不用一个匹配分数掩盖风险。</p>
        </article>
      </section>
      <section
        className="career-example"
        id="matching-example"
        aria-labelledby="matching-title"
      >
        <header>
          <p className="story-kicker">一个例子，看懂推荐依据</p>
          <h2 id="matching-title">同样是“相关”，结论可以不同。</h2>
          <p>机制讲解示例，切换查看；不是实时模型输出或真实求职者数据。</p>
        </header>
        <div className="case-controls" aria-label="选择匹配场景">
          {cases.map((item, i) => (
            <button
              key={item.label}
              aria-pressed={selected === i}
              onClick={() => setSelected(i)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className={"career-case case-" + selected} aria-live="polite">
          <div className="case-evidence">
            <span>输入 / 原始依据</span>
            <h3>{example.requirement}</h3>
            <p>{example.fact}</p>
          </div>
          <div className="case-verdict">
            <span>输出 / 匹配判断</span>
            <h3>{example.status}</h3>
            <p>{example.judgment}</p>
            <strong>下一步</strong>
            <p>{example.action}</p>
          </div>
        </div>
        <NavLink className="text-link" to="/jobs">
          进入岗位工作区，查看预置岗位的证据详情 <ArrowRight size={16} />
        </NavLink>
      </section>
      <section className="career-method">
        <header>
          <p className="story-kicker">AI 在哪里发挥作用</p>
          <h2>检索找线索，模型判关系，规则守边界。</h2>
        </header>
        <div className="method-steps">
          <article>
            <span>01 · EMBEDDING</span>
            <h3>召回相关经历</h3>
            <p>
              用岗位要求检索已确认的简历事实。相似度只决定候选证据，不等于匹配结论。
            </p>
          </article>
          <article>
            <span>02 · 大模型</span>
            <h3>解释匹配关系</h3>
            <p>
              结合原始证据，区分直接匹配、能力可迁移与无证据支持，并明确能力缺口。
            </p>
          </article>
          <article>
            <span>03 · 规则校验</span>
            <h3>拦截不可靠推荐</h3>
            <p>
              硬条件、岗位身份和信息可信度独立检查，不允许模型用“很适合”覆盖风险。
            </p>
          </article>
        </div>
        <p className="story-boundary">
          语义推荐为本地完整版的可选流程，需要配置 Embedding
          与模型复核组件；未配置时不以关键词或固定结果冒充 AI。
        </p>
      </section>
      <section className="career-tour">
        <p className="story-kicker">亲手走一遍</p>
        <h2>从岗位线索，到投递选择。</h2>
        <div className="tour-links">
          <NavLink to="/sources">
            <b>01</b>
            <span>
              看来源<small>信息从哪来，哪里有冲突</small>
            </span>
            <ArrowRight />
          </NavLink>
          <NavLink to="/jobs">
            <b>02</b>
            <span>
              看匹配<small>筛选岗位，展开经历依据</small>
            </span>
            <ArrowRight />
          </NavLink>
          <NavLink to="/shortlist">
            <b>03</b>
            <span>
              看计划<small>检查预置短名单与下一步</small>
            </span>
            <ArrowRight />
          </NavLink>
        </div>
      </section>
    </div>
  );
}
