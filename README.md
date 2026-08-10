# 校招岗位决策台

把多份校招岗位表整理成一份**能解释、能核验、能安全导出的投递清单**。系统不会用一个看似精确的“匹配度”替代判断，而是先确认岗位到底是什么、信息来自哪里、现在是否仍可投，再结合简历中已经确认的经历证据给出行动建议。

## [打开在线产品演示 →](https://saintjupiter.github.io/campus-job-decision-desk/)

[在本机运行完整版](#快速开始) · [了解工作流](#从岗位线索到投递行动) · [使用自己的简历与岗位表](#使用自己的简历与岗位表) · [阅读产品案例](docs/PRODUCT_CASE_STUDY.md)

> 在线版直接在浏览器中读取预生成的合成数据，可体验岗位筛选、证据详情、虚构简历画像、三轴决策、短名单与评测结果。真实简历上传、飞书同步和重新计算保留在本地完整版中，避免在公开网站收集个人信息。

## 快速开始

要求：Python 3.9+、Node.js 20.19+ 或 22.12+。

```bash
make install
make demo-db
CJD_ENVIRONMENT=public-demo \
CJD_DATABASE_URL=sqlite:///data/demo/public-demo.sqlite \
npm run dev
```

打开 `http://127.0.0.1:5173/about`，可先了解产品，再进入今日决策与岗位工作区。这个模式会运行完整前后端和真实决策流程，但只读取合成数据，所有写请求由服务端拒绝。

## 为什么需要它

国内校招信息往往分散在飞书表格、付费清单、企业招聘页和转发链接中。一行数据可能同时包含多个岗位族和多个城市；不同来源又可能给出不同届次、截止时间或开放状态。此时直接让模型匹配简历，等于默认输入已经是一个真实、具体且仍开放的岗位。

在本地聚合基线的 7,909 条岗位型记录中，启发式检查发现：

- 53.1% 可能是一行多岗位或宽泛岗位族；
- 39.1% 包含多个城市；
- 77.2% 的截止字段缺失或不是明确日期。

因此，这个项目不再造一个普通求职平台，而是补上岗位表与投递工具之间缺失的**可信决策层**。

## 从岗位线索到投递行动

```mermaid
flowchart LR
    A["多份岗位表 / 飞书视图"] --> B["保留原始记录与字段来源"]
    B --> C["区分招聘项目 Campaign 与具体岗位 Posting"]
    C --> D["核验官网身份、状态与关键条件"]
    D --> E["结合已确认简历事实生成三轴结论"]
    E --> F["形成可信短名单与投递计划"]
```

首页优先回答“今天先处理什么”：把已经具备具体岗位身份和官网依据的机会，与仍缺关键证据的招聘项目分开，避免把聚合活动页、城市合集或失效链接误当成可直接投递岗位。

![今日决策：从证据进入行动](docs/screenshots/dashboard-desktop.png)

## 关键产品能力

### 1. 接入多源岗位信息，但不破坏原始事实

系统支持 CSV、TSV、XLSX、指定 Markdown 快照，以及带 `table` / `view` 参数的飞书多维表格连接。导入先经过 `preview → confirm`：展示字段映射、解析结果和粒度判断，确认后才写入不可变的 `DataSource → ImportBatch → RawRecord` 血缘。

手动或每日同步会区分新增、修改、缺失和未变记录；读取不完整时不会覆盖上一次成功快照。匿名公开分享页也可以通过浏览器复制后粘贴导入，但系统会明确标记这是人工辅助模式，不把它包装成稳定 API。

### 2. 把“招聘项目”与“具体岗位”分开处理

多岗位、多城市的 Campaign 不会被自动展开成凭空生成的 Posting。招聘项目只能进入核验队列；只有绑定具体官方岗位身份的 Posting，才可以进入可投判断和可信导出。

岗位池同时提供届次、城市、招聘批次、企业性质、笔试要求和截止窗口筛选，并保留无法解析的“招满即止”等原始表述，而不是伪造日期。

![岗位工作区：招聘项目与具体岗位分流](docs/screenshots/jobs-desktop.png)

### 3. 每个结论都能回到字段来源和简历证据

公司、岗位、城市、届次、批次、截止时间、状态和投递链接分别保存为 Field Claim。同权威来源发生冲突时，系统展示差异而不是静默覆盖；模糊相似只进入人工复核，不会直接合并同名岗位。

上传 TXT、Markdown 或 PDF 简历后，系统先生成带原文位置的候选事实。只有用户确认的教育、项目和技能证据才参与经历判断；修改画像、岗位身份、官网域或核验证据后，旧结论会失效并要求重新计算。

具体岗位分别回答三个问题：

- **可投性：** 届次、学历、城市、招聘类型和开放状态等明确条件是否满足；
- **经历证据：** 简历中哪些已确认事实能够支撑岗位任务；
- **信息可信度：** 当前结论是否有具体官网页、多源一致性和足够新鲜的证据。

![岗位详情：三轴结论、字段证据与官网核验](docs/screenshots/job-detail-desktop.png)

### 4. 从结论继续推进，而不是停在推荐卡片

服务端会在加入短名单前重新检查具体岗位身份、硬条件、官网状态、决策新鲜度和 14 天证据窗口。阻断记录可以保留跟踪，但只有 `ready` 记录能够导出 CSV、JSON 或 Markdown。

可信记录还可以跟踪待投递、已投递、笔试/测评、面试、Offer、结束或放弃，并记录下一步行动和日期。系统因此覆盖“发现线索 → 补证据 → 判断 → 投递 → 跟踪”，而不是只给一张 AI 推荐卡。

### 5. 把可证明的结果与尚未验证的效果分开

评测页公开安全边界、合成样本、私有数据结构检查和接口运行结果，同时明确这些证据不能推出推荐准确率、面试率或 Offer 率。

![评测结果：证据、样本和声明边界](docs/screenshots/evaluation-desktop.png)

## 评测证据

当前可复现评测结果：

- 25 / 25 条安全边界契约通过；
- 8 / 8 条开发者编写的合成启发式样本与预期一致；
- 私有聚合基线：7,919 条 RawRecord、7,890 个 Opportunity、79,648 条 FieldClaim；
- 机会实体来源覆盖率 100%，原始记录物化覆盖率 99.87%；
- 本地 TestClient 观测：岗位池首屏中位 28.46 ms，工作区汇总 52.92 ms，详情 3.35 ms。

这些结果证明边界、结构和本地可运行性，**不代表真实推荐准确率、面试率或 Offer 率**。完整可交互报告见 [docs/evaluation/report.html](docs/evaluation/report.html)，原始聚合结果见 [evaluation/results/latest.md](evaluation/results/latest.md)。

## 使用自己的简历与岗位表

本地可写工作区：

```bash
make init-db
npm run dev
```

在“证据画像”中上传 TXT、Markdown 或 PDF 后，系统不会直接采信抽取结果。确认需要采用的事实，再点击“用已确认事实刷新全部岗位”，即可批量更新三轴和推荐队列；历史简历仍可切换。这个显式确认步骤用于避免错误抽取静默影响投递判断。

导入用户有权使用的本地表格：

```bash
make import-latest-private
```

路径可覆盖，不需要修改仓库：

```bash
make import-latest-private LATEST_SNAPSHOT='/path/to/authorized-list.md'
```

连接需要登录或权限的飞书多维表格时，凭证仅从本地环境读取，不写入数据库或前端：

```bash
# 二选一：现有 user/tenant access token
export CJD_FEISHU_ACCESS_TOKEN='...'

# 或自建应用凭证（表格必须授权给该应用）
export CJD_FEISHU_APP_ID='cli_...'
export CJD_FEISHU_APP_SECRET='...'
```

在“数据来源与批次”页粘贴 URL，先执行全量预览，再保存连接。手动执行所有 `DAILY` 连接：

```bash
make sync-remote
```

生产或本机定时运行时，由 cron/launchd/Codex 定时任务每日调用该幂等命令；应用进程本身不启动重复调度器。

如果是无需登录、但没有可用 API 凭证的公开分享页，可在浏览器中复制表格并粘贴到“公开飞书分享页”入口。该模式适合临时导入和抽样检查；每日无人值守同步仍使用上面的官方 API 连接。

2026-08-10 已使用公开飞书视图的 300 行真实样本完成导入、分类、画像、三轴计算和短名单门禁检查。聚合统计与诚实边界见 [真实流程检查报告](docs/LIVE_WORKFLOW_REPORT_2026-08-10.md)。

## 质量门禁

```bash
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build
make evaluate
```

## 更新在线演示

静态演示使用与完整版相同的 React 页面和数据结构。构建时从合成 SQLite 工作区导出岗位、画像、证据和决策结果，再由 GitHub Pages 直接提供，不依赖持续运行的 Python 服务。

```bash
make pages
```

命令会重建纯合成演示库、生成 `web/public/demo-data.json` 和三种短名单示例，并输出到 `dist-pages/`。当前线上版本发布在 `gh-pages` 分支：

[https://saintjupiter.github.io/campus-job-decision-desk/](https://saintjupiter.github.io/campus-job-decision-desk/)

## 部署完整前后端

仓库包含 `Dockerfile` 与 `render.yaml`。部署镜像只复制合成数据，并在构建时重建带内容封印的只读演示库；`data/private`、个人简历、环境变量和所有 SQLite 工作库都不会进入镜像。

```bash
docker build -t campus-job-desk .
docker run --rm -p 8000:8000 campus-job-desk
```

访问 `http://127.0.0.1:8000/about`。若需要让公开网站真正执行简历解析、来源导入或同步，还需要部署该完整后端，并在开放写入前补充账号、用户隔离、存储和删除机制。

## 技术架构

- Backend：FastAPI、SQLAlchemy、SQLite、Pydantic；
- Frontend：React、TypeScript、Vite；
- Parsing：openpyxl、pypdf；
- Entity review：RapidFuzz 只生成候选，不直接做低置信合并；
- Evaluation：pytest、Vitest、可复现评测器与自包含 HTML 报告。

界面采用从 SolutionScope B 版迁移并针对决策工作台收敛的视觉系统；配色、层级、组件边界和禁用项见 [DESIGN.md](DESIGN.md)。

更完整的数据模型、信任边界和状态机见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 公开与隐私边界

- 付费表、完整简历和私有数据库只留本地并被 Git 忽略；
- 公开仓库只包含合成数据、聚合指标和脱敏界面示例；
- 公开在线演示保持只读；需要上传个人简历时，应在本机可写工作区运行，避免把简历个人信息交给公共实例；
- SPA 静态文件路由执行目录 containment，不能读取构建目录外文件；
- 公开演示启动时验证数据源类型，并在服务端统一禁写；
- 系统不抓取或复制 Offerbiu，也不再分发第三方岗位表。

详见 [docs/PRIVACY_AND_DATA.md](docs/PRIVACY_AND_DATA.md)。

## 与已有产品的关系

- Offerbiu / OfferComing：岗位发现、国内校招筛选与投递管理的交互参考；本项目吸收批次/企业性质/笔试/截止维度和基础投递阶段，但不复刻完整 CRM、简历优化或自动填表。
- FreeHire：统一 Schema、来源适配、确定性匹配和事件审计的工程参考；本项目聚焦中国校招届次、批次、聚合表与用户自带来源。
- 本项目的差异化：`BYO Lists + Campaign/Posting + Claim Provenance + Official Verification + Three-axis Decision`。

按“通用求职平台”评价，本项目主动放弃了海量岗位发现、简历改写、自动填表和完整面试 CRM；按“用户自带多份中国校招情报后，如何得到可追溯结论并推进投递”评价，已完成从筛选、核验到行动跟踪的核心闭环。详细功能边界和证据链见 [竞品功能矩阵](docs/COMPETITOR_MATRIX.md)。

## 明确不做

自动投递、全网爬虫、Offer 概率、薪资预测、简历改写、会员体系、通用聊天 Agent、RAG 问答和不可解释的综合匹配百分比。

## 作品集材料

- [产品案例研究](docs/PRODUCT_CASE_STUDY.md)
- [三分钟演示脚本](docs/DEMO_SCRIPT.md)
- [用户任务测试协议](docs/USER_TASK_PROTOCOL.md)
- [简历与面试表述](docs/RESUME_BULLETS.md)
- [数据基线](docs/DATA_BASELINE.md)
- [API 概览](docs/API.md)
- [界面信息架构](docs/UI_INFORMATION_ARCHITECTURE.md)

## 当前边界

产品、合成演示、评测器和文档已完成。真实 3 人任务测试仍需邀请外部参与者执行；在此之前，项目只能声称“工程边界可复现、私有数据结构可追溯”，不能声称“已经验证节省多少时间”或“提升求职结果”。
