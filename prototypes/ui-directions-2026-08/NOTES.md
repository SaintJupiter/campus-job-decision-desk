# 校招岗位决策台视觉方向原型

问题：如何让本项目摆脱常见的“深色侧栏 + 白色 SaaS 卡片”模板，同时与 SolutionScope 的紫黑审核工具气质明显区分？

这是一次性原型，不进入生产构建。三个方向使用相同的岗位、指标与证据内容：

- `?variant=A`：证据公报 / Evidence Ledger；
- `?variant=B`：数据工作台 / Data Workbench；
- `?variant=C`：求职调查手册 / Field Journal。
- `?variant=D`：多彩证据台 / Evidence Spectrum；根据“色彩稍微丰富”反馈追加的 A 视觉语言 + B 工作台结构候选。
- `?variant=E`：松弛色块 / Relaxed Color Fields；根据“色块铺满、间距太近、缺乏焦点”的反馈重做：仅保留淡紫主视觉、淡黄任务、薄荷证据三块主色，其余交还给明亮背景和留白。

运行：

```bash
python3 -m http.server 4312 --directory prototypes/ui-directions-2026-08
```

打开 `http://127.0.0.1:4312/?variant=A`，使用底部按钮或左右方向键切换。选定后将设计原则写入正式 `DESIGN.md`，重写正式前端，并删除未选方案及本原型。

待记录结论：尚未选择。
